"""Create a consistent local backup of the database and product photos."""

from __future__ import annotations

import argparse
import sqlite3
import tarfile
import tempfile
from contextlib import closing
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
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with tarfile.open(archive, "w:gz") as tar:
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
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(backup(args.data_dir, args.output_dir))


if __name__ == "__main__":
    main()
