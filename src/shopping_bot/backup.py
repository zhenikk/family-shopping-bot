"""Create a consistent local backup of the database and product photos."""

from __future__ import annotations

import argparse
import os
import shutil
import uuid
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .families import family_file_lock


def backup(data_dir: Path, output_dir: Path, keep: int = 14) -> Path:
    if keep < 1:
        raise ValueError('At least one backup must be retained')
    with family_file_lock(data_dir):
        archive = _backup(data_dir, output_dir)
        previous_copies = sorted((path for path in output_dir.glob('family-shopping-*.tar.gz') if path != archive), key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
        for previous in previous_copies[keep - 1:]:
            previous.unlink()
        return archive


def _backup(data_dir: Path, output_dir: Path) -> Path:
    database = data_dir / "shopping.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(database)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output_dir / f"family-shopping-{stamp}-{uuid.uuid4().hex[:8]}.tar.gz"
    descriptor, pending_name = tempfile.mkstemp(prefix='.backup-', suffix='.partial', dir=output_dir)
    os.close(descriptor)
    pending = Path(pending_name)
    try:
        return _snapshot(data_dir, pending, archive)
    finally:
        pending.unlink(missing_ok=True)


def _snapshot(data_dir, pending, archive):
    database = data_dir / "shopping.sqlite3"
    with tempfile.TemporaryDirectory(prefix="shopping-backup-", dir=pending.parent) as temporary:
        snapshot = Path(temporary) / "shopping.sqlite3"
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with tarfile.open(pending, "w:gz") as tar:
            tar.add(snapshot, arcname="shopping.sqlite3")
            photos = data_dir / "photos"
            if photos.is_dir():
                tar.add(photos, arcname="photos")
            registry = data_dir / "families.sqlite3"
            if registry.is_file():
                registry_snapshot = Path(temporary) / "families.sqlite3"
                with closing(sqlite3.connect(registry)) as source, closing(sqlite3.connect(registry_snapshot)) as target:
                    source.backup(target)
                tar.add(registry_snapshot, arcname="families.sqlite3")
            for family_db in sorted((data_dir / "families").glob("*/shopping.sqlite3")):
                family_snapshot = Path(temporary) / (family_db.parent.name + ".sqlite3")
                with closing(sqlite3.connect(family_db)) as source, closing(sqlite3.connect(family_snapshot)) as target:
                    source.backup(target)
                prefix = "families/" + family_db.parent.name
                tar.add(family_snapshot, arcname=prefix + "/shopping.sqlite3")
                if (family_db.parent / "photos").is_dir():
                    tar.add(family_db.parent / "photos", arcname=prefix + "/photos")
    verify_archive(pending)
    with pending.open('rb') as handle:
        os.fsync(handle.fileno())
    pending.replace(archive)
    descriptor = os.open(archive.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return archive


def verify_archive(archive: Path, max_bytes=2_000_000_000) -> dict:
    """Restore into an isolated directory, validate paths and every SQLite snapshot."""
    with tempfile.TemporaryDirectory(prefix='shopping-restore-check-', dir=archive.parent) as temporary:
        root = Path(temporary)
        total = 0
        seen = set()
        databases = []
        with tarfile.open(archive, 'r:gz') as tar:
            for member in tar:
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or path.as_posix() in seen:
                    raise ValueError('Unsafe or duplicate backup path')
                seen.add(path.as_posix())
                if not member.isdir() and not member.isfile():
                    raise ValueError('Backup links and special files are forbidden')
                total += member.size
                if total > max_bytes or len(seen) > 100_000:
                    raise ValueError('Backup exceeds restore verification limits')
                target = root.joinpath(*path.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, target.open('xb') as destination:
                        shutil.copyfileobj(source, destination)
                    if target.suffix == '.sqlite3':
                        databases.append(target)
        if not (root / 'shopping.sqlite3').is_file():
            raise ValueError('Missing shopping database')
        for database in databases:
            with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Invalid SQLite backup')
        registry = root / 'families.sqlite3'
        if registry.exists():
            with closing(sqlite3.connect(f'{registry.as_uri()}?mode=ro', uri=True)) as db:
                for (family_id,) in db.execute('SELECT id FROM families'):
                    if family_id != 'legacy' and not (root / 'families' / family_id / 'shopping.sqlite3').is_file():
                        raise ValueError('Missing family database')
        return {'databases': len(databases), 'files': len(seen), 'bytes': total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--keep", type=int, default=14)
    parser.add_argument("--verify-archive", type=Path)
    args = parser.parse_args()
    if args.verify_archive:
        print(verify_archive(args.verify_archive))
    else:
        if args.data_dir is None or args.output_dir is None:
            parser.error('--data-dir and --output-dir are required for backup')
        print(backup(args.data_dir, args.output_dir, args.keep))


if __name__ == "__main__":
    main()
