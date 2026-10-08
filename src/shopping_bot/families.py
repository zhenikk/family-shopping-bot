"""One family per user, one-use invitations and transactional list transfers."""
from __future__ import annotations

import secrets
import shutil
import sqlite3
import threading
import uuid
import fcntl
from contextlib import contextmanager
from pathlib import Path

from .store import Store, now, key_for
_UNSET=object()

@contextmanager
def family_file_lock(root):
    with open(Path(root)/'.family.lock','a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


class Families:
    def __init__(self, legacy: Store, media_dir: Path):
        self.root = Path(legacy.path).parent
        self.legacy = legacy
        self.legacy_media = media_dir
        self.lock = threading.RLock()
        self.stores = {'legacy': legacy}
        with self.write(),self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS families (id TEXT PRIMARY KEY, invite TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, family_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memberships (user_id INTEGER NOT NULL, family_id TEXT NOT NULL, PRIMARY KEY(user_id,family_id));
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS message_routes (user_id INTEGER NOT NULL,message_id INTEGER NOT NULL,family_id TEXT NOT NULL,PRIMARY KEY(user_id,message_id));
                CREATE TABLE IF NOT EXISTS ui_panels (user_id INTEGER NOT NULL, kind TEXT NOT NULL, message_id INTEGER NOT NULL, media INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(user_id,kind));
                CREATE TABLE IF NOT EXISTS preferences (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL, pending_start TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS invitations (token TEXT PRIMARY KEY,family_id TEXT NOT NULL,created_by INTEGER,created_at TEXT NOT NULL,used_by INTEGER,revoked INTEGER NOT NULL DEFAULT 0);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(families)')}
            if 'name' not in columns:
                db.execute("ALTER TABLE families ADD COLUMN name TEXT NOT NULL DEFAULT 'Наша сім’я'")
                db.execute('ALTER TABLE families ADD COLUMN owner_id INTEGER')
            if not db.execute("SELECT 1 FROM meta WHERE key='legacy_imported'").fetchone():
                if not db.execute("SELECT 1 FROM meta WHERE key='legacy_disabled'").fetchone():
                    db.execute("INSERT OR IGNORE INTO families(id,invite) VALUES ('legacy',?)", (secrets.token_urlsafe(24),))
                    with legacy.db() as old:
                        for row in old.execute('SELECT user_id FROM members'):
                            db.execute("INSERT OR IGNORE INTO users VALUES (?,'legacy')", (row[0],))
                db.execute("INSERT INTO meta VALUES ('legacy_imported','1')")
            db.execute("INSERT OR IGNORE INTO preferences(user_id,language) SELECT user_id,'uk' FROM users")
            # Existing active family is retained; inactive old memberships/data are archived.
            db.execute('DELETE FROM memberships WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id=memberships.user_id AND u.family_id=memberships.family_id)')
            db.execute('INSERT OR IGNORE INTO memberships SELECT user_id,family_id FROM users')
            for family_id, owner_id in db.execute('SELECT id,owner_id FROM families').fetchall():
                active = db.execute('SELECT user_id FROM users WHERE family_id=? ORDER BY rowid', (family_id,)).fetchall()
                if active and owner_id not in [row[0] for row in active]:
                    owner_id = active[0][0]
                    db.execute('UPDATE families SET owner_id=? WHERE id=?', (owner_id,family_id))
                if active:
                    db.execute('INSERT OR IGNORE INTO invitations(token,family_id,created_by,created_at) SELECT invite,id,owner_id,? FROM families WHERE id=?', (now(),family_id))
            if not db.execute("SELECT 1 FROM meta WHERE key='one_family_migrated'").fetchone():
                empty = db.execute("SELECT id FROM families f WHERE id!='legacy' AND NOT EXISTS (SELECT 1 FROM users WHERE family_id=f.id)").fetchall()
                for (family_id,) in empty:
                    self._retire(db,family_id)
                db.execute("INSERT INTO meta VALUES ('one_family_migrated','1')")

    @contextmanager
    def write(self):
        with self.lock,family_file_lock(self.root):
            yield

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root / 'families.sqlite3', timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def preference(self,user_id):
        with self.db() as db:
            row=db.execute('SELECT language FROM preferences WHERE user_id=?',(user_id,)).fetchone()
            return row[0] if row else None

    def set_language(self,user_id,value):
        if value not in ('uk','en'):
            raise ValueError('Invalid language')
        with self.write(),self.db() as db:
            db.execute("INSERT INTO preferences(user_id,language) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET language=excluded.language",(user_id,value))

    def pending_start(self,user_id,value=None):
        with self.write(),self.db() as db:
            if value is not None:
                db.execute("INSERT INTO preferences(user_id,language,pending_start) VALUES (?,'',?) ON CONFLICT(user_id) DO UPDATE SET pending_start=excluded.pending_start",(user_id,value))
                return
            row=db.execute('SELECT pending_start FROM preferences WHERE user_id=?',(user_id,)).fetchone()
            db.execute("UPDATE preferences SET pending_start='' WHERE user_id=?",(user_id,))
            return row[0] if row else ''

    def family(self,user_id):
        with self.db() as db:
            row = db.execute('SELECT family_id FROM users WHERE user_id=?',(user_id,)).fetchone()
            return row[0] if row else None

    def resources(self,family_id):
        if family_id=='legacy':
            return self.legacy,self.legacy_media
        with self.lock:
            if family_id not in self.stores:
                self.stores[family_id]=Store(self.root/'families'/family_id/'shopping.sqlite3')
            media=self.root/'families'/family_id/'photos'
            media.mkdir(parents=True,exist_ok=True)
            return self.stores[family_id],media

    def members(self,family_id):
        store,_=self.resources(family_id)
        with self.db() as db:
            ids={row[0] for row in db.execute('SELECT user_id FROM users WHERE family_id=?',(family_id,))}
        return [row for row in store.members() if row['user_id'] in ids]

    def details(self,user_id):
        with self.db() as db:
            row=db.execute('SELECT f.* FROM families f JOIN users u ON u.family_id=f.id WHERE u.user_id=?',(user_id,)).fetchone()
            return dict(row) if row else None

    def choices(self,user_id):
        info=self.details(user_id)
        return [(info['id'],info['name'],info['owner_id'])] if info else []

    def enroll(self,user_id,name,invite=None,*,legacy=False):
        if invite:
            status=self.accept_invite(user_id,name,invite)
            return self.family(user_id),status
        with self.write(),self.db() as db:
            existing=self.family(user_id)
            if existing:
                return existing,'already'
            family_id='legacy' if legacy else secrets.token_hex(16)
            if legacy and not db.execute("SELECT 1 FROM families WHERE id='legacy'").fetchone():
                return None,'invalid'
            store,_=self.resources(family_id)
            db.execute('ATTACH DATABASE ? AS family_data',(store.path,))
            db.execute('BEGIN IMMEDIATE')
            if not legacy:
                db.execute('INSERT INTO families(id,invite,name,owner_id) VALUES (?,?,?,?)',(family_id,secrets.token_urlsafe(24),('Family ' if self.preference(user_id)=='en' else 'Сім’я ')+name[:40],user_id))
            db.execute('INSERT OR REPLACE INTO family_data.members VALUES (?,?,?)',(user_id,name[:80],now()))
            db.execute('INSERT INTO users VALUES (?,?)',(user_id,family_id))
            db.execute("INSERT OR IGNORE INTO preferences(user_id,language) VALUES (?,'uk')",(user_id,))
            db.execute('INSERT OR REPLACE INTO memberships VALUES (?,?)',(user_id,family_id))
            db.execute('UPDATE families SET owner_id=? WHERE id=? AND owner_id IS NULL',(user_id,family_id))
            return family_id,'joined'

    def create_invite(self,user_id):
        with self.write(),self.db() as db:
            family_id=self.family(user_id)
            if not family_id:
                raise ValueError('Спочатку створіть сім’ю або прийміть запрошення.')
            token=secrets.token_urlsafe(24)
            db.execute('INSERT INTO invitations(token,family_id,created_by,created_at) VALUES (?,?,?,?)',(token,family_id,user_id,now()))
            return token

    def invite(self,user_id):
        with self.db() as db:
            row=db.execute('SELECT token FROM invitations WHERE family_id=? AND created_by=? AND used_by IS NULL AND revoked=0 ORDER BY rowid DESC LIMIT 1',(self.family(user_id),user_id)).fetchone()
        return row[0] if row else self.create_invite(user_id)

    def invite_info(self,token,user_id=None):
        with self.db() as db:
            row=db.execute('SELECT i.*,f.name,f.owner_id FROM invitations i JOIN families f ON f.id=i.family_id WHERE token=?',(token,)).fetchone()
            if not row or row['revoked']:
                return None
            if row['used_by'] is not None and self.family(user_id)!=row['family_id']:
                return None
            info=dict(row)
        store,_=self.resources(info['family_id'])
        info['inviter']=store.member_name(info['created_by']) if info['created_by'] else 'Учасник'
        return info

    def invited_family(self,token,user_id=None):
        info=self.invite_info(token,user_id)
        return info['family_id'] if info else None

    def invites(self,user_id):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT token,created_by,created_at FROM invitations WHERE family_id=? AND used_by IS NULL AND revoked=0 ORDER BY rowid DESC',(self.family(user_id),))]

    def revoke_invite(self,user_id,token):
        with self.write(),self.db() as db:
            info=self.details(user_id)
            if not info:
                return False
            return bool(db.execute('UPDATE invitations SET revoked=1 WHERE token=? AND family_id=? AND used_by IS NULL AND revoked=0 AND (created_by=? OR ?=?)',(token,info['id'],user_id,info['owner_id'],user_id)).rowcount)

    def _retire(self,db,family_id):
        db.execute('UPDATE invitations SET revoked=1 WHERE family_id=?',(family_id,))
        db.execute('DELETE FROM memberships WHERE family_id=?',(family_id,))
        db.execute('DELETE FROM families WHERE id=?',(family_id,))
        if family_id=='legacy':
            db.execute("INSERT OR REPLACE INTO meta VALUES ('legacy_disabled','1')")

    def accept_invite(self,user_id,name,invite,*,transfer=False,expected_family=_UNSET):
        with self.write(),self.db() as db:
            info=self.invite_info(invite,user_id)
            if not info:
                return 'invalid'
            old=self.family(user_id)
            target=info['family_id']
            if old==target:
                return 'already'
            if expected_family is not _UNSET and old!=expected_family:
                return 'stale'
            people=self.members(old) if old else []
            previous=self.details(user_id)
            if old and len(people)>1 and previous['owner_id']==user_id:
                return 'owner_required'
            if transfer and len(people)!=1:
                return 'transfer_forbidden'
            destination,media=self.resources(target)
            db.execute('ATTACH DATABASE ? AS destination',(destination.path,))
            old_store,old_media=self.resources(old) if old else (None,None)
            if old_store:
                db.execute('ATTACH DATABASE ? AS previous',(old_store.path,))
            db.execute('BEGIN IMMEDIATE')
            # Recheck the one-use token while holding the write transaction.
            row=db.execute('SELECT used_by,revoked FROM invitations WHERE token=?',(invite,)).fetchone()
            if not row or row['used_by'] is not None or row['revoked']:
                return 'invalid'
            db.execute('INSERT OR REPLACE INTO destination.members VALUES (?,?,?)',(user_id,name[:80],now()))
            if transfer:
                self._copy_active(db,user_id,old_media,media)
            db.execute('INSERT INTO users VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET family_id=excluded.family_id',(user_id,target))
            db.execute('DELETE FROM memberships WHERE user_id=?',(user_id,))
            db.execute('INSERT INTO memberships VALUES (?,?)',(user_id,target))
            db.execute('UPDATE invitations SET used_by=? WHERE token=?',(user_id,invite))
            if old and len(people)==1:
                self._retire(db,old)
            return 'joined'

    def _copy_active(self,db,user_id,old_media,media):
        rows=db.execute('SELECT p.* FROM previous.products p JOIN previous.needs n ON n.product_id=p.id ORDER BY p.id').fetchall()
        for source in rows:
            candidates=db.execute('SELECT p.* FROM destination.products p LEFT JOIN destination.needs n ON p.id=n.product_id ORDER BY (n.product_id IS NOT NULL) DESC,p.id').fetchall()
            existing=next((row for row in candidates if key_for(row['name'])==key_for(source['name'])),None)
            photo_path=None
            if source['photo_path'] and (not existing or not existing['photo_path']):
                photo=Path(source['photo_path']).resolve()
                if photo.is_relative_to(old_media.resolve()) and photo.is_file():
                    copied=media/(uuid.uuid4().hex+photo.suffix)
                    shutil.copyfile(photo,copied)
                    photo_path=str(copied)
            if existing:
                product_id=existing['id']
                if not existing['note'] and source['note']:
                    db.execute('UPDATE destination.products SET note=? WHERE id=?',(source['note'],product_id))
                if photo_path:
                    db.execute('UPDATE destination.products SET photo_path=?,photo_file_id=? WHERE id=?',(photo_path,source['photo_file_id'],product_id))
            else:
                product_id=db.execute('INSERT INTO destination.products(name,normalized,preferred_store,created_at,category,note,photo_path,photo_file_id) VALUES (?,?,?,?,?,?,?,?)',(source['name'],key_for(source['name']),source['preferred_store'],now(),source['category'],source['note'],photo_path,source['photo_file_id'] if photo_path else None)).lastrowid
            added=db.execute('INSERT OR IGNORE INTO destination.needs VALUES (?,?,?)',(product_id,user_id,now()))
            if added.rowcount:
                db.execute("INSERT INTO destination.events(product_id,actor_id,action,happened_at) VALUES (?,?,'added',?)",(product_id,user_id,now()))

    def rename(self,user_id,name):
        name=name.strip()
        if not name or len(name)>60:
            raise ValueError('Назва має бути від 1 до 60 символів')
        with self.write(),self.db() as db:
            return bool(db.execute('UPDATE families SET name=? WHERE id=?',(name,self.family(user_id))).rowcount)

    def transfer_owner(self,user_id,new_owner):
        with self.write(),self.db() as db:
            info=self.details(user_id)
            if not info or info['owner_id']!=user_id or new_owner==user_id or self.family(new_owner)!=info['id']:
                return False
            return bool(db.execute('UPDATE families SET owner_id=? WHERE id=? AND owner_id=?',(new_owner,info['id'],user_id)).rowcount)

    def leave(self,user_id):
        with self.write(),self.db() as db:
            info=self.details(user_id)
            if not info:
                return 'invalid'
            people=self.members(info['id'])
            if info['owner_id']==user_id and len(people)>1:
                return 'owner_required'
            db.execute('DELETE FROM users WHERE user_id=?',(user_id,))
            db.execute('DELETE FROM memberships WHERE user_id=?',(user_id,))
            if len(people)==1:
                self._retire(db,info['id'])
            return 'left'

    def delete(self,user_id):
        with self.write(),self.db() as db:
            info=self.details(user_id)
            if not info or info['owner_id']!=user_id:
                return False
            db.execute('DELETE FROM users WHERE family_id=?',(info['id'],))
            self._retire(db,info['id'])
            return True

    def ui_panel(self, user_id, kind):
        with self.db() as db:
            return db.execute('SELECT * FROM ui_panels WHERE user_id=? AND kind=?', (user_id, kind)).fetchone()

    def save_ui_panel(self, user_id, kind, message_id, media, signature):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO ui_panels VALUES (?,?,?,?,?)', (user_id, kind, message_id, int(media), signature))

    def route_message(self,user_id,message_id,family_id):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO message_routes VALUES (?,?,?)',(user_id,message_id,family_id))

    def message_family(self,user_id,message_id):
        with self.db() as db:
            row=db.execute('SELECT family_id FROM message_routes WHERE user_id=? AND message_id=?',(user_id,message_id)).fetchone()
            return row[0] if row else None
