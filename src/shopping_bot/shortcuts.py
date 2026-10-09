"""Revocable, user-scoped credentials for Apple Shortcuts uploads."""
import hashlib
import secrets
import time

class Shortcuts:
    def __init__(self, families):
        self.families = families
        with families.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shortcut_keys (user_id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, expires REAL NOT NULL)')

    def issue(self, user_id):
        key = secrets.token_urlsafe(32)
        with self.families.db() as db:
            db.execute('INSERT OR REPLACE INTO shortcut_keys VALUES (?,?,?)', (user_id, hashlib.sha256(key.encode()).hexdigest(), time.time()+90*86400))
        return key

    def revoke(self, user_id):
        with self.families.db() as db:
            db.execute('DELETE FROM shortcut_keys WHERE user_id=?', (user_id,))

    def authenticate(self, key):
        if not isinstance(key, str) or not 40 <= len(key) <= 64:
            return None
        with self.families.db() as db:
            row = db.execute('SELECT user_id FROM shortcut_keys WHERE digest=? AND expires>?', (hashlib.sha256(key.encode()).hexdigest(), time.time())).fetchone()
        return row[0] if row and self.families.family(row[0]) else None
