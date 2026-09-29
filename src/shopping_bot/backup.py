"""Create a consistent local backup of the database and product photos."""

from __future__ import annotations

import argparse
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def backup(data_dir: Path, output_dir: Path) -> Path:
    database = data_dir / "shopping.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(database)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output_dir / f"family-shopping-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="shopping-backup-") as temporary:
        snapshot = Path(temporary) / "shopping.sqlite3"
        with sqlite3.connect(database) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(snapshot, arcname="shopping.sqlite3")
            photos = data_dir / "photos"
            if photos.is_dir():
                tar.add(photos, arcname="photos")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(backup(args.data_dir, args.output_dir))


if __name__ == "__main__":
    main()
