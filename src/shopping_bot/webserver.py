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

        def authenticated_user(self):
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("tma ") or len(auth) > 12000:
                raise AccessError("Open through Telegram")
            try:
                user_id = validate_init_data(auth[4:], token)
            except (ValueError, TypeError, KeyError):
                raise AccessError("Open through Telegram") from None
            user=json.loads(dict(parse_qsl(auth[4:]))['user'])
            self.user_name=str(user.get('first_name') or 'Учасник')[:80]
            return user_id

        def member(self):
            user_id=self.authenticated_user()
            if not bot.bind_user(user_id) or not bot.store.is_member(user_id):
                raise AccessError("Family members only")
            return user_id

        def family_payload(self,user_id):
            info=bot.families.details(user_id)
            if not info:
                return {'family_id':None,'members':[],'invites':[]}
            return {'family_id':info['id'],'name':info['name'],'owner_id':info['owner_id'],'self_id':user_id,
                    'members':[{'id':row['user_id'],'name':row['name'],'self':row['user_id']==user_id,'owner':row['user_id']==info['owner_id'],'joined_at':row['joined_at']} for row in bot.families.members(info['id'])],
                    'invites':[row for row in bot.families.invites(user_id) if row['created_by']==user_id or info['owner_id']==user_id],
                    'product_count':bot.families.resources(info['id'])[0].catalog_count()}

        def family_mutation(self,path,user_id,data):
            with bot.families.lock:
                current=bot.families.family(user_id)
                header=self.headers.get('X-Shopping-Family')
                if header and header!=current:
                    self.respond(409,{'error':'Сім’ю змінено. Оновіть екран.'})
                    return
                if path=='/api/family/create':
                    _,status=bot.families.enroll(user_id,self.user_name)
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                    return
                if path=='/api/family/preview':
                    token=str(data.get('token',''))
                    info=bot.families.invite_info(token,user_id)
                    if not info:
                        self.respond(410,{'error':'Запрошення використане, скасоване або недійсне. Попросіть нове.'})
                        return
                    own=bot.families.details(user_id)
                    people=bot.families.members(current) if current else []
                    self.respond(200,{'token':token,'name':info['name'],'inviter':info['inviter'],'already':current==info['family_id'],'source_family':current,'can_transfer':len(people)==1,'owner_required':bool(own and own['owner_id']==user_id and len(people)>1),'delete_previous':len(people)==1})
                    return
                if path=='/api/family/accept':
                    if data.get('confirm') is not True or type(data.get('transfer',False)) is not bool:
                        raise ValueError('Confirm invitation')
                    status=bot.families.accept_invite(user_id,self.user_name,str(data.get('token','')),transfer=data.get('transfer',False),expected_family=data.get('source_family'))
                    if status not in ('joined','already'):
                        errors={'owner_required':'Спочатку передайте роль засновника іншому учаснику.','transfer_forbidden':'Перенести список можна лише якщо ви єдиний учасник.','stale':'Сім’ю змінено. Відкрийте запрошення знову.'}
                        self.respond(409,{'error':errors.get(status,'Запрошення використане, скасоване або недійсне.')})
                        return
                    bot.clear_pending(user_id)
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                    return
                if not current:
                    raise AccessError('Family required')
                if not header:
                    self.respond(409,{'error':'Оновіть екран сім’ї перед змінами.'})
                    return
                if path=='/api/family/invite':
                    token=bot.families.create_invite(user_id)
                    username=getattr(bot,'username',None) or bot.telegram.call('getMe')['username']
                    bot.username=username
                    self.respond(200,{'url':f'https://t.me/{username}?start=invite_{token}','token':token})
                elif path=='/api/family/revoke':
                    if not bot.families.revoke_invite(user_id,str(data.get('token',''))):
                        self.respond(403,{'error':'Запрошення недоступне або ви не можете його скасувати.'})
                        return
                    self.respond(200,{'revoked':True})
                elif path=='/api/family/rename':
                    bot.families.rename(user_id,str(data.get('name','')))
                    self.respond(200,{'renamed':True})
                elif path in ('/api/family/owner','/api/family/leave','/api/family/delete'):
                    if data.get('confirm') is not True:
                        raise ValueError('Confirmation required')
                    if path.endswith('/owner'):
                        success=bot.families.transfer_owner(user_id,int(data['user_id']))
                        status='done' if success else 'denied'
                    elif path.endswith('/leave'):
                        status=bot.families.leave(user_id)
                    else:
                        status='done' if bot.families.delete(user_id) else 'denied'
                    if status not in ('done','left'):
                        self.respond(403,{'error':'Засновник має передати роль перед виходом.' if status=='owner_required' else 'Ця дія недоступна.'})
                        return
                    bot.clear_pending(user_id)
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                else:
                    self.respond(404,{'error':'Невідома дія.'})

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
                user_id=self.authenticated_user()
                if path=='/api/family':
                    self.respond(200,self.family_payload(user_id))
                    return
                if path=='/api/state' and not bot.families.family(user_id):
                    self.respond(200,{'family_id':None,'onboarding':True,'products':[],'categories':CATEGORIES,'history':[]})
                    return
                user_id = self.member()
                if path == "/api/state":
                    active = {row["id"] for row in bot.store.needs()}
                    # All items for a small family catalog; bounded to avoid unbounded responses.
                    catalog = [self.product_json(row) | {"active": row["id"] in active}
                               for row in bot.store.catalog(limit=2000)]
                    history = [{key: row[key] for key in ("id", "product_name", "actor_name", "action", "happened_at", "undone")}
                               for row in bot.store.recent_history(60)]
                    self.respond(200, {"family_id": bot.families.family(user_id), "products": catalog, "categories": CATEGORIES, "history": history})
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
                path=urlsplit(self.path).path
                if path.startswith('/api/family/'):
                    self.family_mutation(path,self.authenticated_user(),self.body())
                    return
                user_id = self.member()
                requested_family=self.headers.get('X-Shopping-Family')
                if requested_family != bot.families.family(user_id):
                    self.respond(409, {'error':'Сім’ю змінено. Закрийте й відкрийте застосунок перед покупками.'})
                    return
                path = urlsplit(self.path).path
                data = self.body()
                notification_batch = None
                if path == "/api/draft":
                    items = bot.store.resolved_items(str(data.get("text", "")))
                    if not items:
                        raise ValueError("Empty list")
                    result = []
                    for name, note in items:
                        existing = bot.store.product_by_name(name)
                        result.append({"name": name, "active": bool(existing and any(row["id"]==existing["id"] for row in bot.store.needs())), "note": ("Купити в " + note if note in STORES else note) or (existing["note"] if existing else ""),
                                       "category": existing["category"] if existing else infer_category(name)})
                    self.respond(200, {"items": result})
                    return
                if path == "/api/add":
                    items = bot.store.resolved_items(str(data.get("text", "")))
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
            except (ValueError, TypeError, KeyError) as exc:
                self.respond(400, {"error": str(exc) if path.startswith('/api/family/') else "Перевірте назви, категорію й нотатку (до 200 символів)."})
            except Exception:
                LOG.error("Mini App mutation failed")
                self.respond(500, {"error": "Не вдалося зберегти. Оновіть список перед повторною спробою."})

    server = MiniAppServer((host, port), Handler)
    server.daemon_threads = True
    return server
