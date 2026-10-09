"""Owner-only operational analytics. No messages, credentials or product content."""
from .version import release
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import sqlite3
import time

LOG=logging.getLogger(__name__)
KINDS={'guest_voice','guest_text','bot_start','bot_message','bot_photo','bot_callback','voice_queued','voice_done','voice_error','web_session','web_add','web_buy','web_edit','web_undo','web_family','language','products_added','purchase','bot_error','web_error','poll_error'}

class Analytics:
    def __init__(self, families):
        self.families=families
        self.path=Path(families.root)/'families.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS analytics_users(user_id INTEGER PRIMARY KEY,name TEXT NOT NULL,username TEXT NOT NULL,first_seen REAL NOT NULL,last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS analytics_events(id INTEGER PRIMARY KEY,user_id INTEGER,kind TEXT NOT NULL,occurred REAL NOT NULL,status TEXT NOT NULL,value INTEGER NOT NULL,duration_ms INTEGER);
                CREATE TABLE IF NOT EXISTS analytics_daily(day TEXT NOT NULL,kind TEXT NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(day,kind));
                CREATE TABLE IF NOT EXISTS analytics_sessions(user_id INTEGER PRIMARY KEY,started REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS analytics_last_seen ON analytics_users(last_seen DESC,user_id);
                CREATE INDEX IF NOT EXISTS analytics_event_time ON analytics_events(occurred);
                CREATE INDEX IF NOT EXISTS analytics_error_time ON analytics_events(status,id DESC);
                CREATE INDEX IF NOT EXISTS analytics_user_events ON analytics_events(user_id,id DESC);
                CREATE INDEX IF NOT EXISTS analytics_username ON analytics_users(username COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS users_family ON users(family_id);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(analytics_events)')}
            for column in ('version', 'commit_sha'):
                if column not in columns:
                    db.execute(f"ALTER TABLE analytics_events ADD COLUMN {column} TEXT NOT NULL DEFAULT 'unknown'")
            db.execute('CREATE INDEX IF NOT EXISTS analytics_release ON analytics_events(version,commit_sha,id DESC)')
            if not db.execute("SELECT 1 FROM meta WHERE key='analytics_started'").fetchone():
                current=time.time()
                db.execute("INSERT INTO meta VALUES ('analytics_started',?)",(str(current),))
                # Import known registration dates; historical visits are not invented.
                for row in db.execute('SELECT user_id,family_id FROM users').fetchall():
                    store,_=families.resources(row['family_id'])
                    with store.db() as family_db:
                        member=family_db.execute('SELECT name,joined_at FROM members WHERE user_id=?',(row['user_id'],)).fetchone()
                    joined=datetime.fromisoformat(member['joined_at']).timestamp() if member else current
                    db.execute('INSERT OR IGNORE INTO analytics_users VALUES (?,?,?,?,?)',(row['user_id'],member['name'] if member else '', '',joined,0))

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=3)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def record(self,kind,user=None,*,status='ok',value=1,duration_ms=None):
        """Fail open: analytics failure must not interrupt shopping."""
        if kind not in KINDS or status not in ('ok','error') or type(value) is not int or not 0<=value<=1000:
            raise ValueError('Invalid telemetry event')
        stamp=time.time()
        user_id=user.get('id') if user else None
        if user_id is not None and (type(user_id) is not int or user_id<=0):return False
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if user_id:
                    name=str(user.get('first_name') or '')[:80];username=str(user.get('username') or '')[:80]
                    db.execute('''INSERT INTO analytics_users VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                        name=CASE WHEN excluded.name='' THEN name ELSE excluded.name END,
                        username=CASE WHEN excluded.name='' THEN username ELSE excluded.username END,last_seen=excluded.last_seen''',(user_id,name,username,stamp,stamp))
                if kind=='web_session':
                    previous=db.execute('SELECT started FROM analytics_sessions WHERE user_id=?',(user_id,)).fetchone()
                    if previous and stamp-previous[0]<1800:return False
                    db.execute('INSERT OR REPLACE INTO analytics_sessions VALUES (?,?)',(user_id,stamp))
                identity = release()
                db.execute('INSERT INTO analytics_events(user_id,kind,occurred,status,value,duration_ms,version,commit_sha) VALUES (?,?,?,?,?,?,?,?)',(user_id,kind,stamp,status,value,duration_ms,identity['version'],identity['commit']))
                day=datetime.fromtimestamp(stamp,timezone.utc).date().isoformat()
                db.execute('INSERT INTO analytics_daily VALUES (?,?,?) ON CONFLICT(day,kind) DO UPDATE SET count=count+excluded.count',(day,kind,value))
                # Retain detailed events for 90 days; cumulative daily totals remain.
                db.execute('DELETE FROM analytics_events WHERE id IN (SELECT id FROM analytics_events WHERE occurred<? LIMIT 200)',(stamp-90*86400,))
            return True
        except sqlite3.Error:
            LOG.warning('Analytics write unavailable')
            return False

    def snapshot(self,days=30):
        stamp=time.time();days=max(1,min(int(days),90));since=stamp-days*86400
        with self.db() as db:
            users=db.execute('SELECT count(*) FROM analytics_users').fetchone()[0]
            active={str(day):db.execute('SELECT count(*) FROM analytics_users WHERE last_seen>=?',(stamp-day*86400,)).fetchone()[0] for day in (1,7,30)}
            families=db.execute('SELECT count(DISTINCT family_id) FROM users').fetchone()[0]
            members=db.execute('SELECT count(*) FROM users').fetchone()[0]
            new=db.execute('SELECT count(*) FROM analytics_users WHERE first_seen>=?',(stamp-7*86400,)).fetchone()[0]
            totals={row['kind']:row['total'] for row in db.execute('SELECT kind,sum(count) total FROM analytics_daily GROUP BY kind')}
            daily=[dict(row) for row in db.execute('SELECT day,kind,count FROM analytics_daily WHERE day>=? ORDER BY day',(datetime.fromtimestamp(since,timezone.utc).date().isoformat(),))]
            daily_active=[dict(row) for row in db.execute("SELECT date(occurred,'unixepoch') day,count(DISTINCT user_id) count FROM analytics_events WHERE occurred>=? AND user_id IS NOT NULL GROUP BY day",(since,))]
            last_error=db.execute("SELECT occurred,kind FROM analytics_events WHERE status='error' ORDER BY id DESC LIMIT 1").fetchone()
            started=float(db.execute("SELECT value FROM meta WHERE key='analytics_started'").fetchone()[0])
            recent_errors=db.execute("SELECT count(*) FROM analytics_events WHERE status='error' AND occurred>=?",(stamp-86400,)).fetchone()[0]
            releases = [dict(row) for row in db.execute('SELECT version,commit_sha,count(*) events FROM analytics_events WHERE occurred>=? GROUP BY version,commit_sha ORDER BY max(id) DESC LIMIT 100',(stamp-90*86400,))]
        return {'release':release(),'releases':releases,'users':users,'members':members,'families':families,'new_7d':new,'active':active,'totals':totals,'daily':daily,'daily_active':daily_active,'errors_24h':recent_errors,'last_error':dict(last_error) if last_error else None,'started':started,'generated':stamp,'retention_days':90}

    def users(self,offset=0,query=''):
        offset=max(0,min(int(offset),1000000));query=query.strip()[:80]
        with self.db() as db:
            condition='';args=[]
            if query:
                condition='WHERE CAST(a.user_id AS TEXT)=? OR a.username LIKE ? ESCAPE \'\\\' OR a.name LIKE ? ESCAPE \'\\\''
                prefix=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';args=[query,prefix,prefix]
            rows=db.execute(f'''SELECT a.*,u.family_id,p.language FROM analytics_users a LEFT JOIN users u ON u.user_id=a.user_id
                LEFT JOIN preferences p ON p.user_id=a.user_id {condition} ORDER BY a.last_seen DESC,a.user_id LIMIT 51 OFFSET ?''',(*args,offset)).fetchall()
        return {'items':[dict(row) for row in rows[:50]],'has_more':len(rows)>50,'offset':offset}

    def events(self,before=None,user_id=None,errors=False,version=None,commit=None):
        conditions=['e.occurred>=?'];args=[time.time()-90*86400]
        if version:conditions.append('e.version=?');args.append(str(version)[:100])
        if commit:conditions.append('e.commit_sha=?');args.append(str(commit)[:64])
        if before:conditions.append('e.id<?');args.append(int(before))
        if user_id:conditions.append('e.user_id=?');args.append(int(user_id))
        if errors:conditions.append("e.status='error'")
        where='WHERE '+' AND '.join(conditions) if conditions else ''
        with self.db() as db:
            rows=db.execute(f'''SELECT e.*,u.name,u.username FROM analytics_events e LEFT JOIN analytics_users u ON u.user_id=e.user_id
                {where} ORDER BY e.id DESC LIMIT 51''',args).fetchall()
        return {'items':[dict(row) for row in rows[:50]],'has_more':len(rows)>50,'next':rows[49]['id'] if len(rows)>50 else None}
