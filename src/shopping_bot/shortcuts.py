"""Scoped, revocable credentials and persistent admission quotas for Shopping."""
import hashlib
import secrets
import time
from datetime import datetime, timezone

class Shortcuts:
    DAILY_USER = 10
    DAILY_TOTAL = 100
    def __init__(self, families):
        self.families = families
        with families.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shortcut_keys (user_id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, expires REAL NOT NULL, family_id TEXT, last_used REAL)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(shortcut_keys)')}
            if 'family_id' not in columns:
                # Legacy keys were sent in chat and were not bound to a family.
                db.execute('DELETE FROM shortcut_keys')
                db.execute('ALTER TABLE shortcut_keys ADD COLUMN family_id TEXT')
                db.execute('ALTER TABLE shortcut_keys ADD COLUMN last_used REAL')
            db.execute('CREATE TABLE IF NOT EXISTS shortcut_usage (day TEXT NOT NULL, user_id INTEGER NOT NULL, requests INTEGER NOT NULL, PRIMARY KEY(day,user_id))')

    def issue(self, user_id):
        family = self.families.family(user_id)
        if not family:
            raise ValueError('Account required')
        key = secrets.token_urlsafe(32)
        with self.families.db() as db:
            db.execute('INSERT OR REPLACE INTO shortcut_keys VALUES (?,?,?,?,NULL)', (user_id, hashlib.sha256(key.encode()).hexdigest(), time.time()+30*86400, family))
        return key

    def revoke(self, user_id):
        with self.families.db() as db:
            db.execute('DELETE FROM shortcut_keys WHERE user_id=?', (user_id,))

    def authenticate(self, key):
        if not isinstance(key, str) or not 40 <= len(key) <= 64:
            return None
        with self.families.db() as db:
            row = db.execute('SELECT user_id,family_id FROM shortcut_keys WHERE digest=? AND expires>?', (hashlib.sha256(key.encode()).hexdigest(), time.time())).fetchone()
        return row['user_id'] if row and row['family_id'] == self.families.family(row['user_id']) else None

    def status(self, user_id):
        day = datetime.now(timezone.utc).date().isoformat()
        with self.families.db() as db:
            row = db.execute('SELECT expires,last_used,family_id FROM shortcut_keys WHERE user_id=?', (user_id,)).fetchone()
            count = db.execute('SELECT requests FROM shortcut_usage WHERE day=? AND user_id=?', (day,user_id)).fetchone()
        return {'active': bool(row and row['expires'] > time.time() and row['family_id'] == self.families.family(user_id)),
                'expires': row['expires'] if row else None, 'last_used': row['last_used'] if row else None,
                'used_today': count[0] if count else 0, 'daily_limit': self.DAILY_USER, 'max_seconds': 30}

    def reserve(self, key):
        """Charge an attempt atomically before reading its body; no retries or refunds."""
        day = datetime.now(timezone.utc).date().isoformat()
        digest = hashlib.sha256(key.encode()).hexdigest()
        with self.families.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT user_id,family_id FROM shortcut_keys WHERE digest=? AND expires>?', (digest,time.time())).fetchone()
            if not row or row['family_id'] != self.families.family(row['user_id']):
                return False
            db.execute('DELETE FROM shortcut_usage WHERE day<?', (day,))
            own = db.execute('SELECT requests FROM shortcut_usage WHERE day=? AND user_id=?', (day,row['user_id'])).fetchone()
            total = db.execute('SELECT COALESCE(SUM(requests),0) FROM shortcut_usage WHERE day=?', (day,)).fetchone()[0]
            if (own and own[0] >= self.DAILY_USER) or total >= self.DAILY_TOTAL:
                return False
            db.execute('INSERT INTO shortcut_usage VALUES (?,?,1) ON CONFLICT(day,user_id) DO UPDATE SET requests=requests+1', (day,row['user_id']))
            db.execute('UPDATE shortcut_keys SET last_used=? WHERE digest=?', (time.time(),digest))
            return True
