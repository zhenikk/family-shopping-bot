from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .categories import CATEGORIES, infer_category

STORES = ("Mercadona", "Lidl", "Auchan")
DEFAULT_STORE = "Mercadona"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key_for(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def parse_items(raw: str, *, split_conjunctions: bool = True) -> list[tuple[str, str | None]]:
    """Parse a dictated list. Explicit @Store is optional; no generative parsing."""
    raw = re.sub(
        r"^\s*(?:сьогодні\s+)?(?:(?:мені|нам)\s+)?(?:треба|потрібно)\s+(?:купити|взяти)\s+",
        "", raw, flags=re.I,
    )
    raw = re.sub(r"^\s*(?:купи|купіть|buy)\s+", "", raw, flags=re.I)
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

    def set_note(self, product_id: int, note: str) -> None:
        if len(note) > 200:
            raise ValueError("Note too long")
        with self.db() as db:
            db.execute("UPDATE products SET note=? WHERE id=?", (note.strip(), product_id))

    def needs(self) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("SELECT p.*, n.added_by, n.added_at FROM needs n JOIN products p ON p.id=n.product_id ORDER BY p.name COLLATE NOCASE").fetchall()

    def set_category(self, product_id: int, category: str) -> None:
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
            if db.execute("SELECT COUNT(*) FROM members").fetchone()[0] >= 2:
                return "full"
            db.execute("INSERT INTO members VALUES (?, ?, ?)", (user_id, name[:80], now()))
            return "joined"

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

    def product_by_name(self, name: str) -> sqlite3.Row | None:
        with self.db() as db:
            return db.execute("SELECT * FROM products WHERE normalized=?", (key_for(name),)).fetchone()

    def ensure_product(self, name: str, preferred_store: str | None = None) -> int:
        if preferred_store is not None and len(preferred_store) > 200:
            raise ValueError("Note too long")
        normalized = key_for(name)
        if not normalized or len(name) > 120:
            raise ValueError("Invalid product name")
        with self.db() as db:
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
