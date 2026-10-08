"""Explicit support submissions, kept separately from content-free analytics."""
import json
import time
import uuid


class Support:
    def __init__(self, families):
        self.families = families
        with families.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS support_drafts (
                    user_id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL DEFAULT '', expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, draft_token TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL, name TEXT NOT NULL, username TEXT NOT NULL,
                    text TEXT NOT NULL, metadata TEXT NOT NULL, created REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS support_user_created ON support_tickets(user_id, created);
            ''')

    def begin(self, user_id):
        token = uuid.uuid4().hex
        with self.families.db() as db:
            db.execute('DELETE FROM support_drafts WHERE expires < ?', (time.time(),))
            db.execute('DELETE FROM support_tickets WHERE created < ?', (time.time() - 90 * 86400,))
            db.execute('INSERT OR REPLACE INTO support_drafts VALUES (?, ?, ?, ?)', (user_id, token, '', time.time() + 900))
        return token

    def draft(self, user_id):
        with self.families.db() as db:
            row = db.execute('SELECT * FROM support_drafts WHERE user_id=? AND expires>=?', (user_id, time.time())).fetchone()
            return dict(row) if row else None

    def describe(self, user_id, text):
        text = text.strip()
        if not 10 <= len(text) <= 2000:
            raise ValueError('Опис має містити від 10 до 2000 символів.')
        with self.families.db() as db:
            db.execute('UPDATE support_drafts SET text=?,token=?,expires=? WHERE user_id=? AND expires>=?', (text, uuid.uuid4().hex, time.time() + 900, user_id, time.time()))
        draft = self.draft(user_id)
        if not draft:
            raise ValueError('Звернення застаріло. Відкрийте /support ще раз.')
        return draft

    def cancel(self, user_id, token=None):
        with self.families.db() as db:
            if token is None:
                db.execute('DELETE FROM support_drafts WHERE user_id=?', (user_id,))
            else:
                return bool(db.execute('DELETE FROM support_drafts WHERE user_id=? AND token=?', (user_id, token)).rowcount)

    def submit(self, user, token, metadata):
        user_id = user['id']
        with self.families.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM support_tickets WHERE user_id=? AND draft_token=?', (user_id, token)).fetchone()
            if existing:
                return existing[0]
            draft = db.execute('SELECT text FROM support_drafts WHERE user_id=? AND token=? AND expires>=?', (user_id, token, time.time())).fetchone()
            if not draft or not 10 <= len(draft[0]) <= 2000:
                raise ValueError('Звернення застаріло. Відкрийте /support ще раз.')
            if db.execute('SELECT count(*) FROM support_tickets WHERE user_id=? AND created>?', (user_id, time.time() - 86400)).fetchone()[0] >= 5:
                raise ValueError('Можна надіслати до 5 звернень на добу. Спробуйте пізніше.')
            ticket = db.execute('INSERT INTO support_tickets(draft_token,user_id,name,username,text,metadata,created) VALUES (?,?,?,?,?,?,?)', (token, user_id, str(user.get('first_name') or '')[:80], str(user.get('username') or '')[:80], draft[0], json.dumps(metadata), time.time())).lastrowid
            db.execute('DELETE FROM support_drafts WHERE user_id=?', (user_id,))
            return ticket

    def tickets(self, before=None, include_resolved=False):
        clauses = ['1=1']; values = []
        if before:
            clauses.append('id < ?'); values.append(int(before))
        if not include_resolved:
            clauses.append("status='open'")
        with self.families.db() as db:
            rows = db.execute('SELECT id,user_id,name,username,text,metadata,created,status FROM support_tickets WHERE ' + ' AND '.join(clauses) + ' AND created>=? ORDER BY id DESC LIMIT 51', (*values, time.time() - 90 * 86400)).fetchall()
        items = [dict(row) | {'metadata': json.loads(row['metadata'])} for row in rows[:50]]
        return {'items': items, 'has_more': len(rows) > 50, 'next': items[-1]['id'] if items else None}

    def resolve(self, ticket_id):
        with self.families.db() as db:
            return bool(db.execute("UPDATE support_tickets SET status='resolved' WHERE id=?", (int(ticket_id),)).rowcount)
