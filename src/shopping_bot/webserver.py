"""Private Mini App API. Telegram initData is checked on every data request."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .categories import CATEGORIES, infer_category
from .store import STORES, parse_items
from .telegram import TelegramError

LOG = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "web"


class AccessError(ValueError):
    pass


def validate_init_data(raw: str, token: str, now: float | None = None) -> int:
    """Telegram's HMAC protocol; reject duplicate fields and expired launches."""
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise AccessError("Invalid Telegram session")
    supplied = fields.pop("hash", "")
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise AccessError("Invalid Telegram session")
    age = (time.time() if now is None else now) - int(fields.get("auth_date", "0"))
    if age < -30 or age > 3600:
        raise AccessError("Expired Telegram session")
    user = json.loads(fields.get("user", "{}"))
    if not isinstance(user, dict):
        raise AccessError("Invalid Telegram user")
    user_id = user.get("id")
    if type(user_id) is not int or user_id <= 0:
        raise AccessError("Invalid Telegram user")
    return user_id


def make_server(bot, token: str, host: str = "127.0.0.1", port: int = 8080):
    class MiniAppServer(ThreadingHTTPServer):
        def __init__(self, *args, **kwargs):
            self.sync_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mini-app-sync")
            super().__init__(*args, **kwargs)

        def server_close(self):
            super().server_close()
            self.sync_pool.shutdown(wait=True)

    def sync_changes(batch_id=None):
        if batch_id:
            try:
                bot.notify_partner(batch_id)
            except TelegramError:
                LOG.warning("Mini App saved; partner notification failed")
        try:
            bot.refresh_views()
        except TelegramError:
            LOG.warning("Mini App saved; chat refresh failed")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShoppingMiniApp"

        def log_message(self, *args):
            # Never log query strings, launch credentials, or personal payloads.
            pass

        def respond(self, status, value, content_type="application/json; charset=utf-8", cache="no-store"):
            data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org")
            self.end_headers()
            self.wfile.write(data)

        def member(self):
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("tma ") or len(auth) > 12000:
                raise AccessError("Open through Telegram")
            try:
                user_id = validate_init_data(auth[4:], token)
            except (ValueError, TypeError, KeyError):
                raise AccessError("Open through Telegram") from None
            if not bot.bind_user(user_id) or not bot.store.is_member(user_id):
                raise AccessError("Family members only")
            return user_id

        def product_json(self, row):
            return {key: row[key] for key in ("id", "name", "note", "category")} | {
                "photo": bool(row["photo_path"]),
            }

        def body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Invalid request")
            return data

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8"),
                          "/fonts/onest.woff2": ("fonts/onest.woff2", "font/woff2"),
                          "/fonts/manrope.woff2": ("fonts/manrope.woff2", "font/woff2")}
                if path in assets:
                    filename, mime = assets[path]
                    data = (STATIC / filename).read_bytes()
                    if filename == "index.html":
                        for asset in ("app.js", "style.css"):
                            version = hashlib.sha256((STATIC / asset).read_bytes()).hexdigest()[:12]
                            data = data.replace(("/" + asset).encode(), ("/" + asset + "?v=" + version).encode())
                    self.respond(200, data, mime, "no-store" if filename == "index.html" else "public, max-age=31536000, immutable")
                    return
                self.member()
                if path == "/api/state":
                    active = {row["id"] for row in bot.store.needs()}
                    # All items for a small family catalog; bounded to avoid unbounded responses.
                    catalog = [self.product_json(row) | {"active": row["id"] in active}
                               for row in bot.store.catalog(limit=2000)]
                    history = [{key: row[key] for key in ("id", "product_name", "actor_name", "action", "happened_at", "undone")}
                               for row in bot.store.recent_history(60)]
                    self.respond(200, {"products": catalog, "categories": CATEGORIES, "history": history})
                elif path.startswith("/api/photo/"):
                    row = bot.store.product(int(path.rsplit("/", 1)[1]))
                    if not row or not row["photo_path"]:
                        self.respond(404, {"error": "Фото ще немає"})
                        return
                    photo = Path(row["photo_path"]).resolve()
                    if not photo.is_relative_to(bot.media_dir.resolve()) or not photo.is_file():
                        self.respond(404, {"error": "Фото недоступне"})
                        return
                    self.respond(200, photo.read_bytes(), "image/jpeg")
                else:
                    self.respond(404, {"error": "Не знайдено"})
            except AccessError:
                self.respond(401, {"error": "Відкрийте застосунок через кнопку в боті. Доступ лише для вашої сім’ї."})
            except (ValueError, TypeError, KeyError):
                self.respond(400, {"error": "Некоректний запит"})
            except Exception:
                LOG.error("Mini App read failed")
                self.respond(500, {"error": "Не вдалося завантажити дані. Спробуйте ще раз."})

        def do_POST(self):
            try:
                user_id = self.member()
                path = urlsplit(self.path).path
                data = self.body()
                notification_batch = None
                if path == "/api/draft":
                    items = parse_items(str(data.get("text", "")))
                    if not items:
                        raise ValueError("Empty list")
                    result = []
                    for name, note in items:
                        existing = bot.store.product_by_name(name)
                        result.append({"name": name, "note": ("Купити в " + note if note in STORES else note) or (existing["note"] if existing else ""),
                                       "category": existing["category"] if existing else infer_category(name)})
                    self.respond(200, {"items": result})
                    return
                if path == "/api/add":
                    items = parse_items(str(data.get("text", "")))
                    if not items:
                        raise ValueError("Empty list")
                    added = sum(bot.store.add_need(bot.store.ensure_product(name, note), user_id) for name, note in items)
                    result = {"added": added}
                elif path == "/api/undo":
                    restored = bot.store.undo_purchase(int(data["event_id"]), user_id)
                    if restored:
                        with bot.store.db() as db:
                            row = db.execute("SELECT batch_id FROM events WHERE id=?", (int(data["event_id"]),)).fetchone()
                        if row and row[0]:
                            notification_batch = row[0]
                    result = {"restored": bool(restored)}
                elif path in ("/api/buy", "/api/readd", "/api/edit"):
                    product_id = int(data["id"])
                    if not bot.store.product(product_id):
                        self.respond(404, {"error": "Товар не знайдено"})
                        return
                    if path == "/api/buy":
                        bought, batch_id, event_id = bot.store.purchase(product_id, user_id, "")
                        if bought:
                            notification_batch = batch_id
                        result = {"bought": bought, "event_id": event_id}
                    elif path == "/api/readd":
                        result = {"added": bot.store.add_need(product_id, user_id)}
                    else:
                        note, category = data.get("note"), data.get("category")
                        if not isinstance(note, str) or len(note) > 200 or category not in CATEGORIES:
                            raise ValueError("Invalid product edit")
                        # Both fields are committed atomically.
                        with bot.store.db() as db:
                            db.execute("UPDATE products SET note=?, category=? WHERE id=?", (note.strip(), category, product_id))
                        result = {"saved": True}
                else:
                    self.respond(404, {"error": "Не знайдено"})
                    return
                self.server.sync_pool.submit(copy_context().run, sync_changes, notification_batch)
                self.respond(200, result)
            except AccessError:
                self.respond(401, {"error": "Сесія завершилась. Закрийте застосунок і відкрийте знову через бота."})
            except (ValueError, TypeError, KeyError):
                self.respond(400, {"error": "Перевірте назви, категорію й нотатку (до 200 символів)."})
            except Exception:
                LOG.error("Mini App mutation failed")
                self.respond(500, {"error": "Не вдалося зберегти. Оновіть список перед повторною спробою."})

    server = MiniAppServer((host, port), Handler)
    server.daemon_threads = True
    return server
