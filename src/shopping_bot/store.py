from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .categories import CATEGORIES, infer_category
from .product_names import canonical_name, product_key, suggested_name

STORES = ("Mercadona", "Lidl", "Auchan")
DEFAULT_STORE = "Mercadona"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key_for(name: str) -> str:
    return product_key(name)


def parse_items(raw: str, *, split_conjunctions: bool = True) -> list[tuple[str, str | None]]:
    """Parse a dictated list. Explicit @Store is optional; no generative parsing."""
    # Strip a conversational introduction only when followed by an explicit buy command.
    trip_store = None
    command = re.search(r"\b(?:купи|купіть|купити|buy)\s+", raw, flags=re.I)
    if command:
        prelude = raw[:command.start()]
        stores = {"Mercadona": r"меркадон\w*|міркадон\w*|mercadona", "Lidl": r"лідл\w*|lidl", "Auchan": r"ашан\w*|auchan"}
        for label, pattern in stores.items():
            if re.search(r"\b(?:" + pattern + r")\b", prelude, flags=re.I):
                trip_store = label
                break
        if not prelude.strip() or re.search(r"\b(?:як|коли|підеш|пидеш|треба|потрібно|please|need|when)\b", prelude, flags=re.I):
            raw = raw[command.end():]
    raw = re.sub(
        r"^\s*(?:сьогодні\s+)?(?:(?:мені|нам)\s+)?(?:треба|потрібно)\s+(?:купити|взяти)\s+",
        "", raw, flags=re.I,
    )
    raw = re.sub(r"^\s*(?:(?:please\s+)?buy|(?:today\s+)?(?:we|i)\s+need(?:\s+to\s+buy)?|купи|купіть)\s+", "", raw, flags=re.I)
    separator = r"[,;\n]+|(?<=[.!?])\s+"
    if split_conjunctions:
        separator += r"|\s+(?:і|й|та|e|and)\s+"
    parts = re.split(separator, raw, flags=re.I)
    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for part in parts:
        part = part.strip(" .!?:\t\r\n")
        if not part:
            continue
        part = re.sub(r"^(?:(?:купи|купіть|додай|додайте|buy|add)\s+)?(?:будь ласка[, ]*|please\s+)", "", part, flags=re.I).strip()
        part = re.sub(r"\s+(?:(?:мені|нам|вони|це)\s+)*(?:дуже\s+)?(?:треба|потрібн[оі])$", "", part, flags=re.I).strip()
        if re.fullmatch(r"(?:дуже\s+)?(?:дякую|спасибі|thank you|thanks)(?:\s+(?:тобі|вам|a lot|very much))?", part, flags=re.I) or not part:
            continue
        store = None
        match = re.search(r"\s+@\s*(Mercadona|Lidl|Auchan)\s*$", part, flags=re.I)
        if match:
            store = next(s for s in STORES if s.casefold() == match.group(1).casefold())
            part = part[: match.start()].strip()
        if not part or len(part) > 120:
            continue
        if "::" in part:
            part, note = (value.strip() for value in part.split("::", 1))
            if not part or len(note) > 200:
                continue
            store = note or None
        if "::" not in part:
            packaging = re.search(r"\s+((?:в|у)\s+(?:(?:маленькій|великій|малій|невеликій)\s+)?(?:упаковці|пачці|банці|пляшці)\b.*|in (?:a )?(?:small |large )?(?:pack|package|bottle|jar)\b.*)$", part, flags=re.I)
            if packaging:
                store = "; ".join(value for value in (store, packaging.group(1)) if value)
                part = part[:packaging.start()].strip()
        part = re.sub(r"^(?:фасоль|квасоля)\s+(?:біленьк\w*|біл[аоу])$", "Квасоля біла", part, flags=re.I)
        if trip_store:
            trip_note = "Store: " + trip_store if re.search(r"[a-z]", part, flags=re.I) else "Купити в " + trip_store
            store = "; ".join(value for value in (store, trip_note) if value)
        part = canonical_name(part)
        normalized = key_for(part)
        if normalized not in seen:
            seen.add(normalized)
            result.append((part, store))
    return result[:20]


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS members (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    joined_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE,
                    preferred_store TEXT NOT NULL DEFAULT 'Mercadona',
                    photo_file_id TEXT,
                    photo_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS needs (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id),
                    added_by INTEGER NOT NULL REFERENCES members(user_id),
                    added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY,
                    actor_id INTEGER NOT NULL REFERENCES members(user_id),
                    store TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    notification_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    actor_id INTEGER NOT NULL REFERENCES members(user_id),
                    action TEXT NOT NULL,
                    store TEXT,
                    happened_at TEXT NOT NULL,
                    batch_id INTEGER REFERENCES batches(id),
                    undone INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY,
                    actor_id INTEGER NOT NULL REFERENCES members(user_id),
                    items_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS views (
                    user_id INTEGER NOT NULL REFERENCES members(user_id),
                    store TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY(user_id, store)
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batch_notifications (
                    batch_id INTEGER NOT NULL REFERENCES batches(id),
                    user_id INTEGER NOT NULL REFERENCES members(user_id),
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY(batch_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_time ON events(happened_at DESC);
            """)

            columns = {row[1] for row in db.execute("PRAGMA table_info(products)")}
            if "category" not in columns:
                db.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'other'")
                for row in db.execute("SELECT id, name FROM products").fetchall():
                    db.execute("UPDATE products SET category=? WHERE id=?", (infer_category(row["name"]), row["id"]))

            if "note" not in columns:
                db.execute("ALTER TABLE products ADD COLUMN note TEXT NOT NULL DEFAULT ''")
                # The old default Mercadona was automatic, not an explicit request.
                db.execute("UPDATE products SET note='Купити в ' || preferred_store WHERE preferred_store != 'Mercadona'")

            # Exact alias migration preserves references, events and card metadata.
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            rows=db.execute("SELECT p.* FROM products p LEFT JOIN needs n ON n.product_id=p.id ORDER BY (n.product_id IS NOT NULL) DESC,p.id").fetchall()
            keep={}
            for row in rows:
                key=key_for(row['name'])
                if key in keep:
                    target=keep[key]
                    db.execute("INSERT OR IGNORE INTO needs SELECT ?,added_by,added_at FROM needs WHERE product_id=?",(target,row['id']))
                    db.execute("DELETE FROM needs WHERE product_id=?",(row['id'],))
                    db.execute("UPDATE events SET product_id=? WHERE product_id=?",(target,row['id']))
                    db.execute("UPDATE products SET note=CASE WHEN note='' THEN ? ELSE note END, photo_file_id=CASE WHEN photo_path IS NULL OR photo_path='' THEN ? ELSE photo_file_id END, photo_path=CASE WHEN photo_path IS NULL OR photo_path='' THEN ? ELSE photo_path END WHERE id=?",(row['note'],row['photo_file_id'],row['photo_path'],target))
                    db.execute("DELETE FROM products WHERE id=?",(row['id'],))
                else:
                    keep[key]=row['id']
            for key,product_id in keep.items():
                row=db.execute("SELECT name FROM products WHERE id=?",(product_id,)).fetchone()
                db.execute("UPDATE products SET name=?,normalized=? WHERE id=?",(canonical_name(row['name']),key,product_id))

            # One-time aisle taxonomy upgrade. Later manual choices remain untouched.
            if not db.execute("SELECT 1 FROM meta WHERE key='category_taxonomy_v2'").fetchone():
                for product in db.execute("SELECT id,name FROM products").fetchall():
                    db.execute("UPDATE products SET category=? WHERE id=?", (infer_category(product["name"]), product["id"]))
                for draft in db.execute("SELECT id,items_json FROM drafts").fetchall():
                    items = json.loads(draft["items_json"])
                    for item in items:
                        item["category"] = infer_category(item["name"])
                    db.execute("UPDATE drafts SET items_json=? WHERE id=?", (json.dumps(items, ensure_ascii=False), draft["id"]))
                db.execute("INSERT INTO meta(key,value) VALUES ('category_taxonomy_v2','1')")

    def resolve_name(self, name):
        exact=self.product_by_name(name)
        if exact:
            return canonical_name(exact['name'])
        with self.db() as db:
            names=[row[0] for row in db.execute('SELECT name FROM products')]
        return suggested_name(name,names)

    def resolved_items(self, raw):
        result=[];seen=set()
        for name,note in parse_items(raw):
            name=self.resolve_name(name)
            key=key_for(name)
            if key not in seen:
                result.append((name,note));seen.add(key)
        return result

    def set_note(self, product_id: int, note: str) -> None:
        if len(note) > 200:
            raise ValueError("Note too long")
        with self.db() as db:
            db.execute("UPDATE products SET note=? WHERE id=?", (note.strip(), product_id))

    def needs(self) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("SELECT p.*, n.added_by, n.added_at FROM needs n JOIN products p ON p.id=n.product_id ORDER BY p.name COLLATE NOCASE").fetchall()

    def set_category(self, product_id: int, category: str) -> None:
        if category in ("vegetables", "fruit"):
            category = "produce"
        if category not in CATEGORIES:
            raise ValueError("Unknown category")
        with self.db() as db:
            db.execute("UPDATE products SET category=? WHERE id=?", (category, product_id))

    def is_member(self, user_id: int) -> bool:
        with self.db() as db:
            return db.execute("SELECT 1 FROM members WHERE user_id=?", (user_id,)).fetchone() is not None

    def join(self, user_id: int, name: str) -> str:
        with self.db() as db:
            if db.execute("SELECT 1 FROM members WHERE user_id=?", (user_id,)).fetchone():
                db.execute("UPDATE members SET name=? WHERE user_id=?", (name[:80], user_id))
                return "already"
            db.execute("INSERT INTO members VALUES (?, ?, ?)", (user_id, name[:80], now()))
            return "joined"

    def partners(self, user_id):
        with self.db() as db:
            return db.execute("SELECT * FROM members WHERE user_id != ?", (user_id,)).fetchall()

    def members(self):
        with self.db() as db:
            return db.execute("SELECT user_id, name, joined_at FROM members ORDER BY joined_at, user_id").fetchall()

    def notification(self, batch_id, user_id):
        with self.db() as db:
            row = db.execute("SELECT message_id FROM batch_notifications WHERE batch_id=? AND user_id=?", (batch_id, user_id)).fetchone()
            if row:
                return row[0]
            # Existing two-person batches retain their original notification.
            batch = db.execute("SELECT notification_id, actor_id FROM batches WHERE id=?", (batch_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM members WHERE user_id != ?", (batch[1],)).fetchone()[0] if batch else 0
            return batch[0] if batch and count == 1 else None

    def save_notification(self, batch_id, user_id, message_id):
        with self.db() as db:
            db.execute("INSERT INTO batch_notifications VALUES (?, ?, ?) ON CONFLICT(batch_id, user_id) DO UPDATE SET message_id=excluded.message_id", (batch_id, user_id, message_id))

    def other_member(self, user_id: int) -> sqlite3.Row | None:
        with self.db() as db:
            return db.execute("SELECT * FROM members WHERE user_id != ? LIMIT 1", (user_id,)).fetchone()

    def member_name(self, user_id: int) -> str:
        with self.db() as db:
            row = db.execute("SELECT name FROM members WHERE user_id=?", (user_id,)).fetchone()
            return row[0] if row else str(user_id)

    def product(self, product_id: int) -> sqlite3.Row | None:
        with self.db() as db:
            return db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def _matching_product(self, db, name):
        normalized = key_for(name)
        # Existing legacy spellings are reused without changing or deleting cards.
        rows = db.execute("SELECT p.* FROM products p LEFT JOIN needs n ON n.product_id=p.id ORDER BY (n.product_id IS NOT NULL) DESC, p.id").fetchall()
        return next((row for row in rows if key_for(row["name"]) == normalized), None)

    def product_by_name(self, name: str) -> sqlite3.Row | None:
        with self.db() as db:
            return self._matching_product(db, name)

    def ensure_product(self, name: str, preferred_store: str | None = None) -> int:
        if preferred_store is not None and len(preferred_store) > 200:
            raise ValueError("Note too long")
        name = canonical_name(name)
        normalized = key_for(name)
        if not normalized or len(name) > 120:
            raise ValueError("Invalid product name")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self._matching_product(db, name)
            if existing:
                if preferred_store:
                    db.execute("UPDATE products SET note=? WHERE id=?", ("Купити в " + preferred_store if preferred_store in STORES else preferred_store, existing["id"]))
                return existing["id"]
            db.execute(
                "INSERT OR IGNORE INTO products(name, normalized, preferred_store, created_at, category) VALUES (?, ?, ?, ?, ?)",
                (name.strip(), normalized, DEFAULT_STORE, now(), infer_category(name)),
            )
            row = db.execute("SELECT id FROM products WHERE normalized=?", (normalized,)).fetchone()
            if preferred_store:
                db.execute("UPDATE products SET note=? WHERE id=?", ("Купити в " + preferred_store if preferred_store in STORES else preferred_store, row[0]))
            return row[0]

    def add_need(self, product_id: int, actor_id: int) -> bool:
        with self.db() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO needs(product_id, added_by, added_at) VALUES (?, ?, ?)",
                (product_id, actor_id, now()),
            )
            if cursor.rowcount:
                db.execute(
                    "INSERT INTO events(product_id, actor_id, action, happened_at) VALUES (?, ?, 'added', ?)",
                    (product_id, actor_id, now()),
                )
            return bool(cursor.rowcount)

    def needs_for_store(self, store: str) -> list[sqlite3.Row]:
        if store not in STORES:
            raise ValueError("Unknown store")
        with self.db() as db:
            return db.execute("""
                SELECT p.*, n.added_by, n.added_at FROM needs n
                JOIN products p ON p.id=n.product_id
                ORDER BY CASE WHEN p.preferred_store=? THEN 0 ELSE 1 END, p.name COLLATE NOCASE
            """, (store,)).fetchall()

    def catalog(self, offset: int = 0, limit: int = 10) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("""
                SELECT p.*, CASE WHEN n.product_id IS NULL THEN 0 ELSE 1 END AS active
                FROM products p LEFT JOIN needs n ON p.id=n.product_id
                ORDER BY p.name COLLATE NOCASE LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()

    def catalog_count(self) -> int:
        with self.db() as db:
            return db.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def set_store(self, product_id: int, store: str) -> None:
        if store not in STORES:
            raise ValueError("Unknown store")
        with self.db() as db:
            db.execute("UPDATE products SET preferred_store=? WHERE id=?", (store, product_id))

    def set_photo(self, product_id: int, file_id: str, path: str) -> None:
        with self.db() as db:
            db.execute("UPDATE products SET photo_file_id=?, photo_path=? WHERE id=?", (file_id, path, product_id))

    def save_draft(self, actor_id: int, items: list) -> int:
        with self.db() as db:
            db.execute("DELETE FROM drafts WHERE actor_id=?", (actor_id,))
            cursor = db.execute(
                "INSERT INTO drafts(actor_id, items_json, created_at) VALUES (?, ?, ?)",
                (actor_id, json.dumps(items, ensure_ascii=False), now()),
            )
            return cursor.lastrowid

    def _draft_items(self, items: list) -> list[dict]:
        result = []
        for index, item in enumerate(items):
            if isinstance(item, dict):
                result.append(item)
            else:
                name, note = item
                existing = self.product_by_name(name)
                result.append({"key": str(index), "name": name,
                               "note": ("Купити в " + note if note in STORES else note) or (existing["note"] if existing else ""),
                               "category": existing["category"] if existing else infer_category(name)})
        return result

    def draft(self, actor_id: int, draft_id: int) -> list[dict] | None:
        with self.db() as db:
            row = db.execute("SELECT items_json FROM drafts WHERE id=? AND actor_id=?", (draft_id, actor_id)).fetchone()
        return self._draft_items(json.loads(row[0])) if row else None

    def change_draft(self, actor_id: int, draft_id: int, key: str, changes: dict | None = None, *, remove=False) -> bool:
        with self.db() as db:
            row = db.execute("SELECT items_json FROM drafts WHERE id=? AND actor_id=?", (draft_id, actor_id)).fetchone()
            if not row:
                return False
            items = self._draft_items(json.loads(row[0]))
            item = next((item for item in items if item["key"] == key), None)
            if item is None:
                return False
            if remove:
                items.remove(item)
            elif changes:
                if "category" in changes and changes["category"] not in CATEGORIES:
                    raise ValueError("Unknown category")
                if "name" in changes and (not changes["name"].strip() or len(changes["name"]) > 120):
                    raise ValueError("Invalid name")
                if "note" in changes and len(changes["note"]) > 200:
                    raise ValueError("Invalid note")
                if "name" in changes:
                    changes["name"] = canonical_name(changes["name"])
                item.update(changes)
            db.execute("UPDATE drafts SET items_json=? WHERE id=? AND actor_id=?", (json.dumps(items, ensure_ascii=False), draft_id, actor_id))
            return True

    def take_draft(self, actor_id: int, draft_id: int) -> list[dict] | None:
        with self.db() as db:
            row = db.execute("SELECT items_json FROM drafts WHERE id=? AND actor_id=?", (draft_id, actor_id)).fetchone()
            if not row:
                return None
            db.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
            return self._draft_items(json.loads(row[0]))

    def cancel_draft(self, actor_id: int, draft_id: int) -> None:
        with self.db() as db:
            db.execute("DELETE FROM drafts WHERE id=? AND actor_id=?", (draft_id, actor_id))

    def purchase(self, product_id: int, actor_id: int, store: str) -> tuple[bool, int | None, int | None]:
        if store not in (*STORES, ""):
            raise ValueError("Unknown store")
        with self.db() as db:
            cursor = db.execute("DELETE FROM needs WHERE product_id=?", (product_id,))
            if not cursor.rowcount:
                return False, None, None
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
            batch = db.execute("""
                SELECT id FROM batches WHERE actor_id=? AND store=? AND created_at>=?
                ORDER BY id DESC LIMIT 1
            """, (actor_id, store, cutoff)).fetchone()
            if batch:
                batch_id = batch[0]
            else:
                batch_id = db.execute(
                    "INSERT INTO batches(actor_id, store, created_at) VALUES (?, ?, ?)",
                    (actor_id, store, now()),
                ).lastrowid
            event_id = db.execute("""
                INSERT INTO events(product_id, actor_id, action, store, happened_at, batch_id)
                VALUES (?, ?, 'bought', ?, ?, ?)
            """, (product_id, actor_id, store, now(), batch_id)).lastrowid
            return True, batch_id, event_id

    def undo_purchase(self, event_id: int, actor_id: int) -> int | None:
        with self.db() as db:
            row = db.execute("""
                SELECT product_id FROM events
                WHERE id=? AND actor_id=? AND action='bought' AND undone=0
            """, (event_id, actor_id)).fetchone()
            if not row:
                return None
            product_id = row[0]
            db.execute("UPDATE events SET undone=1 WHERE id=?", (event_id,))
            db.execute(
                "INSERT OR IGNORE INTO needs(product_id, added_by, added_at) VALUES (?, ?, ?)",
                (product_id, actor_id, now()),
            )
            db.execute("""
                INSERT INTO events(product_id, actor_id, action, happened_at)
                VALUES (?, ?, 'restored', ?)
            """, (product_id, actor_id, now()))
            return product_id

    def batch(self, batch_id: int) -> sqlite3.Row | None:
        with self.db() as db:
            return db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()

    def batch_items(self, batch_id: int) -> list[str]:
        with self.db() as db:
            rows = db.execute("""
                SELECT p.name FROM events e JOIN products p ON p.id=e.product_id
                WHERE e.batch_id=? AND e.action='bought' AND e.undone=0 ORDER BY e.id
            """, (batch_id,)).fetchall()
            return [row[0] for row in rows]

    def set_batch_notification(self, batch_id: int, message_id: int) -> None:
        with self.db() as db:
            db.execute("UPDATE batches SET notification_id=? WHERE id=?", (message_id, batch_id))

    def set_view(self, user_id: int, store: str, message_id: int) -> None:
        with self.db() as db:
            db.execute("""
                INSERT INTO views(user_id, store, message_id) VALUES (?, ?, ?)
                ON CONFLICT(user_id, store) DO UPDATE SET message_id=excluded.message_id
            """, (user_id, store, message_id))

    def forget_view(self, user_id: int, message_id: int) -> None:
        with self.db() as db:
            db.execute("DELETE FROM views WHERE user_id=? AND message_id=?", (user_id, message_id))

    def views(self) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("SELECT * FROM views").fetchall()

    def recent_history(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("""
                SELECT e.*, p.name AS product_name, m.name AS actor_name
                FROM events e JOIN products p ON p.id=e.product_id
                JOIN members m ON m.user_id=e.actor_id
                ORDER BY e.id DESC LIMIT ?
            """, (limit,)).fetchall()

    def get_offset(self) -> int:
        with self.db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
            return int(row[0]) if row else 0

    def set_offset(self, offset: int) -> None:
        with self.db() as db:
            db.execute("""
                INSERT INTO meta(key, value) VALUES ('telegram_offset', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (str(offset),))
