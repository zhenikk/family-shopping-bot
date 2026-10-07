"""Family routing; each family owns a separate database and photo directory."""
from __future__ import annotations

import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .store import Store


class Families:
    def __init__(self, legacy: Store, media_dir: Path):
        self.root = Path(legacy.path).parent
        self.legacy = legacy
        self.legacy_media = media_dir
        self.lock = threading.RLock()
        self.stores = {"legacy": legacy}
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS families (id TEXT PRIMARY KEY, invite TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, family_id TEXT NOT NULL REFERENCES families(id));
            """)
            db.execute("INSERT OR IGNORE INTO families VALUES ('legacy', ?)", (secrets.token_urlsafe(24),))
            with legacy.db() as old:
                for row in old.execute("SELECT user_id FROM members"):
                    db.execute("INSERT OR IGNORE INTO users VALUES (?, 'legacy')", (row[0],))

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root / "families.sqlite3", timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def family(self, user_id):
        with self.db() as db:
            row = db.execute("SELECT family_id FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row[0] if row else None

    def resources(self, family_id):
        if family_id == "legacy":
            return self.legacy, self.legacy_media
        with self.lock:
            if family_id not in self.stores:
                self.stores[family_id] = Store(self.root / "families" / family_id / "shopping.sqlite3")
            media = self.root / "families" / family_id / "photos"
            media.mkdir(parents=True, exist_ok=True)
            return self.stores[family_id], media

    def enroll(self, user_id, name, invite=None, *, legacy=False):
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT family_id FROM users WHERE user_id=?", (user_id,)).fetchone()
            if existing:
                return existing[0], "already"
            if legacy:
                family_id = "legacy"
            elif invite:
                row = db.execute("SELECT id FROM families WHERE invite=?", (invite,)).fetchone()
                if not row:
                    return None, "invalid"
                family_id = row[0]
            else:
                family_id = secrets.token_hex(16)
                db.execute("INSERT INTO families VALUES (?, ?)", (family_id, secrets.token_urlsafe(24)))
            store, _ = self.resources(family_id)
            store.join(user_id, name)
            db.execute("INSERT INTO users VALUES (?, ?)", (user_id, family_id))
            return family_id, "joined"

    def invite(self, user_id):
        with self.db() as db:
            row = db.execute("SELECT f.invite FROM families f JOIN users u ON u.family_id=f.id WHERE u.user_id=?", (user_id,)).fetchone()
            return row[0] if row else None
