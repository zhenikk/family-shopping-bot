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
                CREATE TABLE IF NOT EXISTS memberships (user_id INTEGER NOT NULL, family_id TEXT NOT NULL, PRIMARY KEY(user_id,family_id));
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS message_routes (user_id INTEGER NOT NULL, message_id INTEGER NOT NULL, family_id TEXT NOT NULL, PRIMARY KEY(user_id,message_id));
            """)
            columns={row[1] for row in db.execute('PRAGMA table_info(families)')}
            if 'name' not in columns:
                db.execute("ALTER TABLE families ADD COLUMN name TEXT NOT NULL DEFAULT 'Наша сім’я'")
                db.execute('ALTER TABLE families ADD COLUMN owner_id INTEGER')
            if not db.execute("SELECT value FROM meta WHERE key='legacy_disabled'").fetchone():
                db.execute("INSERT OR IGNORE INTO families(id,invite) VALUES ('legacy', ?)", (secrets.token_urlsafe(24),))
            with legacy.db() as old:
                for row in old.execute("SELECT user_id FROM members"):
                    if db.execute("SELECT value FROM meta WHERE key='legacy_disabled'").fetchone():
                        break
                    db.execute("INSERT OR IGNORE INTO users VALUES (?, 'legacy')", (row[0],))
            db.execute('INSERT OR IGNORE INTO memberships SELECT user_id,family_id FROM users')
            for family_id, in db.execute('SELECT id FROM families WHERE owner_id IS NULL').fetchall():
                owner=db.execute('SELECT user_id FROM memberships WHERE family_id=? ORDER BY rowid LIMIT 1',(family_id,)).fetchone()
                if owner:
                    store,_=self.resources(family_id)
                    db.execute('UPDATE families SET owner_id=?,name=? WHERE id=?',(owner[0],'Сім’я '+store.member_name(owner[0]),family_id))

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
                if not db.execute("SELECT 1 FROM families WHERE id='legacy'").fetchone():
                    return None, "invalid"
                family_id = "legacy"
            elif invite:
                row = db.execute("SELECT id FROM families WHERE invite=?", (invite,)).fetchone()
                if not row:
                    return None, "invalid"
                family_id = row[0]
            else:
                family_id = secrets.token_hex(16)
                db.execute("INSERT INTO families(id,invite,name,owner_id) VALUES (?, ?, ?, ?)", (family_id, secrets.token_urlsafe(24),'Сім’я '+name[:40],user_id))
            store, _ = self.resources(family_id)
            store.join(user_id, name)
            db.execute("INSERT INTO users VALUES (?, ?)", (user_id, family_id))
            db.execute("INSERT OR IGNORE INTO memberships VALUES (?, ?)",(user_id,family_id))
            db.execute("UPDATE families SET owner_id=? WHERE id=? AND owner_id IS NULL",(user_id,family_id))
            return family_id, "joined"

    def invite(self, user_id):
        with self.db() as db:
            row = db.execute("SELECT f.invite FROM families f JOIN users u ON u.family_id=f.id WHERE u.user_id=?", (user_id,)).fetchone()
            return row[0] if row else None

    def invited_family(self, invite):
        with self.db() as db:
            row = db.execute("SELECT id FROM families WHERE invite=?", (invite,)).fetchone()
            return row[0] if row else None

    def route_message(self,user_id,message_id,family_id):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO message_routes VALUES (?,?,?)',(user_id,message_id,family_id))

    def message_family(self,user_id,message_id):
        with self.db() as db:
            row=db.execute('SELECT family_id FROM message_routes WHERE user_id=? AND message_id=?',(user_id,message_id)).fetchone()
            return row[0] if row else None

    def accept_invite(self, user_id, name, invite):
        """Join and activate an invited family; retain previous memberships/data."""
        with self.lock, self.db() as db:
            target = self.invited_family(invite)
            if not self.family(user_id) or not target:
                return "invalid"
            store, _ = self.resources(target)
            db.execute("ATTACH DATABASE ? AS destination", (store.path,))
            db.execute("BEGIN IMMEDIATE")
            from .store import now
            db.execute("INSERT OR IGNORE INTO destination.members VALUES (?, ?, ?)", (user_id,name[:80],now()))
            db.execute("INSERT OR IGNORE INTO memberships VALUES (?, ?)", (user_id,target))
            db.execute("UPDATE users SET family_id=? WHERE user_id=?", (target,user_id))
            return "joined"

    def choices(self, user_id):
        with self.db() as db:
            return db.execute("SELECT f.id,f.name,f.owner_id FROM families f JOIN memberships m ON m.family_id=f.id WHERE m.user_id=? ORDER BY f.rowid", (user_id,)).fetchall()

    def activate(self, user_id, family_id):
        with self.lock, self.db() as db:
            if not db.execute("SELECT 1 FROM memberships WHERE user_id=? AND family_id=?", (user_id,family_id)).fetchone():
                return False
            db.execute("UPDATE users SET family_id=? WHERE user_id=?", (family_id,user_id))
            return True

    def rename(self, user_id, name):
        name=name.strip()
        if not name or len(name)>60:
            raise ValueError("Назва має бути від 1 до 60 символів")
        with self.db() as db:
            return bool(db.execute("UPDATE families SET name=? WHERE id=? AND owner_id=?", (name,self.family(user_id),user_id)).rowcount)

    def delete(self, user_id):
        """Revoke family access; keep files for recovery in existing backups."""
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            family_id=self.family(user_id)
            if not db.execute("SELECT 1 FROM families WHERE id=? AND owner_id=?", (family_id,user_id)).fetchone():
                return False
            affected=db.execute("SELECT user_id FROM memberships WHERE family_id=?", (family_id,)).fetchall()
            db.execute("DELETE FROM memberships WHERE family_id=?", (family_id,))
            for (member,) in affected:
                active=db.execute("SELECT family_id FROM users WHERE user_id=?", (member,)).fetchone()
                if active and active[0]==family_id:
                    other=db.execute("SELECT family_id FROM memberships WHERE user_id=? LIMIT 1", (member,)).fetchone()
                    if other:
                        db.execute("UPDATE users SET family_id=? WHERE user_id=?", (other[0],member))
                    else:
                        db.execute("DELETE FROM users WHERE user_id=?", (member,))
            db.execute("DELETE FROM families WHERE id=?", (family_id,))
            if family_id=='legacy':
                db.execute("INSERT OR REPLACE INTO meta VALUES ('legacy_disabled','1')")
            return True
