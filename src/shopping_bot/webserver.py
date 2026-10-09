"""Private Mini App API. Telegram initData is checked on every data request."""
from __future__ import annotations
from .i18n import tr, language

import tempfile
import os
from .shortcuts import Shortcuts

import hashlib
import hmac
import json
import logging
import time
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .limits import RateLimiter
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
    shortcuts = Shortcuts(bot.families)
    shortcut_limits = RateLimiter(3, 1 / 30)
    reads = RateLimiter(100, 2)
    writes = RateLimiter(30, 0.5)

    class MiniAppServer(ThreadingHTTPServer):
        request_queue_size = 32
        request_timeout = 10

        def __init__(self, *args, **kwargs):
            self.request_slots = threading.BoundedSemaphore(32)
            self.sync_slots = threading.BoundedSemaphore(64)
            self.sync_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mini-app-sync")
            super().__init__(*args, **kwargs)

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(self.request_timeout)
            return connection, address

        def process_request(self, request, client_address):
            if not self.request_slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.request_slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.request_slots.release()

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
            if getattr(self, 'defer_response', False):
                self.pending_response = (status, value, content_type, cache)
                return
            if status>=500:
                bot.analytics.record('web_error',getattr(self,'user_profile',None),status='error',value=1)
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
            language.set(bot.families.preference(user_id) or "uk")
            user=json.loads(dict(parse_qsl(auth[4:]))['user'])
            self.user_profile=user
            self.user_name=str(user.get('first_name') or tr('ui_9e0a513bdc07'))[:80]
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
            bot.analytics.record('web_family',self.user_profile)
            with bot.families.lock:
                current=bot.families.family(user_id)
                header=self.headers.get('X-Shopping-Family')
                if header and header!=current:
                    self.respond(409,{'error':tr('ui_4942d160189f')})
                    return
                if path=='/api/family/create':
                    _,status=bot.families.enroll(user_id,self.user_name,mode=data.get('mode'))
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                    return
                if path=='/api/family/preview':
                    token=str(data.get('token',''))
                    info=bot.families.invite_info(token,user_id)
                    if not info:
                        self.respond(410,{'error':tr('ui_1fb9fe6dbff2')})
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
                        errors={'owner_required':tr('ui_006b7c354b8a'),'transfer_forbidden':tr('ui_51dbcae1e020'),'stale':tr('ui_ec20e7b8a7be')}
                        self.respond(409,{'error':errors.get(status,tr('ui_5d077df0d079'))})
                        return
                    bot.clear_pending(user_id)
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                    return
                if not current:
                    raise AccessError('Family required')
                if not header:
                    self.respond(409,{'error':tr('ui_aba4d96508c4')})
                    return
                if path=='/api/family/invite':
                    token=bot.families.create_invite(user_id)
                    username=getattr(bot,'username',None) or bot.telegram.call('getMe')['username']
                    bot.username=username
                    self.respond(200,{'url':f'https://t.me/{username}?start=invite_{token}','token':token})
                elif path=='/api/family/revoke':
                    if not bot.families.revoke_invite(user_id,str(data.get('token',''))):
                        self.respond(403,{'error':tr('ui_10a2e8ef134a')})
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
                        self.respond(403,{'error':tr('ui_57bbe0bd6194') if status=='owner_required' else tr('ui_880d5e897fe6')})
                        return
                    bot.clear_pending(user_id)
                    bot.bind_user(user_id)
                    self.respond(200,{'status':status})
                else:
                    self.respond(404,{'error':tr('ui_ab0679edd735')})

        def product_json(self, row):
            return {key: row[key] for key in ("id", "name", "note", "category")} | {
                "photo": bool(row["photo_path"]),
            }

        def body(self):
            if hasattr(self, 'parsed_body'):
                return self.parsed_body
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Invalid request")
            return data

        def dispatch(self, method):
            # Read sockets before taking the membership lock; write after releasing it.
            try:
                path = urlsplit(self.path).path
                if path == '/shortcuts/audio' and method == 'POST':
                    self.shortcut_upload()
                    return
                if path.startswith('/api/'):
                    user_id = self.authenticated_user()
                    limiter = writes if method == 'POST' else reads
                    if not limiter.allow(user_id):
                        self.respond(429, {'error': 'Too many requests. Try again shortly.'})
                        return
                if method == 'POST':
                    self.parsed_body = self.body()
                    if path in ('/api/add', '/api/undo', '/api/buy', '/api/readd', '/api/edit'):
                        if not self.server.sync_slots.acquire(blocking=False):
                            self.respond(429, {'error': 'Server is busy. Try again shortly.'})
                            return
                        self.sync_reserved = True
                self.defer_response = True
                with bot.families.lock:
                    getattr(self, '_' + method)()
                self.defer_response = False
                self.respond(*self.pending_response)
            except AccessError:
                self.defer_response = False
                self.respond(401, {'error': 'Open through Telegram'})
            except (ValueError, UnicodeError):
                self.defer_response = False
                self.respond(400, {'error': 'Invalid request'})
            except socket.timeout:
                self.defer_response = False
                self.respond(408, {'error': 'Request timeout'})
            finally:
                if getattr(self, 'sync_reserved', False):
                    self.server.sync_slots.release()
                self.close_connection = True

        def shortcut_upload(self):
            auth = self.headers.get('Authorization', '')
            user_id = shortcuts.authenticate(auth[7:] if auth.startswith('Bearer ') else '')
            if not user_id:
                self.respond(401, {'error': 'Invalid or expired Shopping key'})
                return
            if not shortcut_limits.allow(user_id):
                self.respond(429, {'error': 'Try again in a minute'})
                return
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Content-Length required')
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 8 * 1024 * 1024:
                self.respond(413, {'error': 'Audio must be between 1 byte and 8 MB'})
                return
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError('Incomplete audio')
            fd, filename = tempfile.mkstemp(prefix='shopping-shortcut-', suffix='.audio')
            handed_off = False
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                with bot.families.lock:
                    if not bot.bind_user(user_id):
                        raise AccessError('Account required')
                    language.set(bot.families.preference(user_id) or 'uk')
                    handed_off = bot.queue_voice(user_id, 'shortcut', uploaded_path=filename)
                self.respond(202 if handed_off else 429, {'status': 'queued' if handed_off else 'busy'})
            finally:
                if not handed_off:
                    Path(filename).unlink(missing_ok=True)

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')

        def _GET(self):
            try:
                path = urlsplit(self.path).path
                if path == '/healthz':
                    last_poll = bot.last_poll_at
                    ready = (time.monotonic() - (last_poll if last_poll is not None else bot.started_at)) < 120
                    with bot.families.db() as db:
                        db.execute('SELECT 1 FROM families LIMIT 1').fetchone()
                    self.respond(200 if ready else 503, {'status': 'ok' if ready else 'unavailable'})
                    return
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8"),
                          "/admin": ("admin.html", "text/html; charset=utf-8"),
                          "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
                          "/admin.css": ("admin.css", "text/css; charset=utf-8"),
                          "/fonts/onest.woff2": ("fonts/onest.woff2", "font/woff2"),
                          "/fonts/manrope.woff2": ("fonts/manrope.woff2", "font/woff2")}
                assets.update({'/help': ('help.html', 'text/html; charset=utf-8'), '/help.css': ('help.css', 'text/css; charset=utf-8'), '/help.js': ('help.js', 'text/javascript; charset=utf-8')})
                assets.update({f'/help/{lang}-{role}-{step}.png': (f'help/{lang}-{role}-{step}.png', 'image/png') for lang in ('uk', 'en') for role in ('c', 'j') for step in range(6)})
                if path in assets:
                    filename, mime = assets[path]
                    chosen='en' if dict(parse_qsl(urlsplit(self.path).query)).get('lang')=='en' else 'uk'
                    if chosen=='en' and filename in ('index.html','app.js','admin.html','admin.js'):
                        filename=filename.replace('.', '.en.', 1)
                    data = (STATIC / filename).read_bytes()
                    if filename in ("index.html","index.en.html","admin.html","admin.en.html"):
                        for asset in (("admin.js","admin.css") if filename in ("admin.html","admin.en.html") else ("app.js", "style.css")):
                            asset_file=asset.replace(".",".en.",1) if chosen=="en" and asset in ("app.js","admin.js") else asset
                            version = hashlib.sha256((STATIC / asset_file).read_bytes()).hexdigest()[:12]
                            data = data.replace(("/" + asset).encode(), ("/" + asset + "?lang=" + (chosen or "uk") + "&v=" + version).encode())
                    if filename == 'help.html':
                        for asset in ('help.css', 'help.js'):
                            version = hashlib.sha256((STATIC / asset).read_bytes()).hexdigest()[:12]
                            data = data.replace(('/' + asset).encode(), ('/' + asset + '?v=' + version).encode())
                    self.respond(200, data, mime, "no-store" if filename == "help.html" or filename in ("index.html","index.en.html","admin.html","admin.en.html") else "public, max-age=31536000, immutable")
                    return
                user_id=self.authenticated_user()
                if path.startswith('/api/admin/'):
                    if user_id not in bot.admin_ids:
                        self.respond(403,{'error':'Owner access only'})
                        return
                    query=dict(parse_qsl(urlsplit(self.path).query))
                    if path=='/api/admin/stats':
                        result=bot.analytics.snapshot(query.get('days',30))
                        result['voice_queue']=bot.voice_metrics.snapshot()
                    elif path=='/api/admin/jev':result=bot.analytics.jev_experiments()
                    elif path=='/api/admin/speech':result=bot.analytics.speech_benchmarks(query.get('before'))
                    elif path=='/api/admin/users':result=bot.analytics.users(query.get('offset',0),query.get('q',''))
                    elif path=='/api/admin/support':result=bot.support.tickets(query.get('before'),query.get('resolved')=='1')
                    elif path=='/api/admin/events':result=bot.analytics.events(query.get('before'),query.get('user'),query.get('errors')=='1',query.get('version'),query.get('commit'))
                    else:
                        self.respond(404,{'error':'Not found'})
                        return
                    self.respond(200,result)
                    return
                if path=='/api/preferences':
                    self.respond(200,{'language':bot.families.preference(user_id) or None,'admin':user_id in bot.admin_ids})
                    return
                if path=='/api/family':
                    self.respond(200,self.family_payload(user_id))
                    return
                if path=='/api/state' and not bot.families.family(user_id):
                    self.respond(200,{'language':language.get(),'family_id':None,'onboarding':True,'products':[],'categories':{key:tr(value) for key,value in CATEGORIES.items()},'history':[]})
                    return
                user_id = self.member()
                if path == "/api/state":
                    active = {row["id"] for row in bot.store.needs()}
                    # All items for a small family catalog; bounded to avoid unbounded responses.
                    catalog = [self.product_json(row) | {"active": row["id"] in active}
                               for row in bot.store.catalog(limit=2000)]
                    history = [{key: row[key] for key in ("id", "product_name", "actor_name", "action", "happened_at", "undone")}
                               for row in bot.store.recent_history(60)]
                    self.respond(200, {"language":language.get(), "family_id": bot.families.family(user_id), "family_member_count": len(bot.store.members()), "products": catalog, "categories": {key:tr(value) for key,value in CATEGORIES.items()}, "history": history})
                elif path.startswith("/api/photo/"):
                    row = bot.store.product(int(path.rsplit("/", 1)[1]))
                    if not row or not row["photo_path"]:
                        self.respond(404, {"error": tr('ui_16aff7a8a36c')})
                        return
                    photo = Path(row["photo_path"]).resolve()
                    if not photo.is_relative_to(bot.media_dir.resolve()) or not photo.is_file():
                        self.respond(404, {"error": tr('ui_49f7f5d3052f')})
                        return
                    self.respond(200, photo.read_bytes(), "image/jpeg")
                else:
                    self.respond(404, {"error": tr('ui_08c66d1111a3')})
            except AccessError:
                self.respond(401, {"error": tr('ui_9690765dd168')})
            except (ValueError, TypeError, KeyError):
                self.respond(400, {"error": tr('ui_ac2e1cbfde52')})
            except Exception:
                LOG.error("Mini App read failed")
                self.respond(500, {"error": tr('ui_ac9e82cc0e40')})

        def _POST(self):
            try:
                path=urlsplit(self.path).path
                if path == '/api/admin/support/resolve':
                    user_id = self.authenticated_user()
                    if user_id not in bot.admin_ids:
                        self.respond(403, {'error': 'Owner access only'})
                        return
                    found = bot.support.resolve(self.body()['id'])
                    self.respond(200 if found else 404, {'resolved': found})
                    return
                if path=='/api/session':
                    self.authenticated_user()
                    recorded=bot.analytics.record('web_session',self.user_profile)
                    self.respond(200,{'recorded':recorded})
                    return
                if path=='/api/language':
                    user_id=self.authenticated_user()
                    value=self.body().get('language')
                    bot.families.set_language(user_id,value)
                    language.set(value)
                    bot.analytics.record('language',self.user_profile)
                    self.respond(200,{'language':value})
                    return
                if path.startswith('/api/family/'):
                    self.family_mutation(path,self.authenticated_user(),self.body())
                    return
                user_id = self.member()
                requested_family=self.headers.get('X-Shopping-Family')
                if requested_family != bot.families.family(user_id):
                    self.respond(409, {'error':tr('ui_6ecf0e92694e')})
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
                        result.append({"name": name, "active": bool(existing and any(row["id"]==existing["id"] for row in bot.store.needs())), "note": (tr('ui_b0c5ef5f2ea3') + note if note in STORES else note) or (existing["note"] if existing else ""),
                                       "category": existing["category"] if existing else infer_category(name)})
                    self.respond(200, {"items": result})
                    return
                if path == "/api/add":
                    items = bot.store.resolved_items(str(data.get("text", "")))
                    if not items:
                        raise ValueError("Empty list")
                    added = sum(bot.store.add_need(bot.store.ensure_product(name, note), user_id) for name, note in items)
                    bot.analytics.record("products_added",self.user_profile,value=added)
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
                        self.respond(404, {"error": tr('ui_5383e75496a0')})
                        return
                    if path == "/api/buy":
                        bought, batch_id, event_id = bot.store.purchase(product_id, user_id, "")
                        if bought:
                            bot.analytics.record("purchase",self.user_profile)
                            notification_batch = batch_id
                        result = {"bought": bought, "event_id": event_id}
                    elif path == "/api/readd":
                        result = {"added": bot.store.add_need(product_id, user_id)}
                    else:
                        note, category = data.get("note"), data.get("category")
                        if category in ("vegetables", "fruit"):
                            category = "produce"
                        if not isinstance(note, str) or len(note) > 200 or category not in CATEGORIES:
                            raise ValueError("Invalid product edit")
                        # Both fields are committed atomically.
                        with bot.store.db() as db:
                            db.execute("UPDATE products SET note=?, category=? WHERE id=?", (note.strip(), category, product_id))
                        result = {"saved": True}
                else:
                    self.respond(404, {"error": tr('ui_08c66d1111a3')})
                    return
                event={'/api/add':'web_add','/api/buy':'web_buy','/api/edit':'web_edit','/api/undo':'web_undo','/api/readd':'web_add'}.get(path)
                if event:bot.analytics.record(event,self.user_profile)
                future = self.server.sync_pool.submit(copy_context().run, sync_changes, notification_batch)
                self.sync_reserved = False
                future.add_done_callback(lambda _: self.server.sync_slots.release())
                self.respond(200, result)
            except AccessError:
                self.respond(401, {"error": tr('ui_02e40f40a5f9')})
            except (ValueError, TypeError, KeyError) as exc:
                self.respond(400, {"error": tr(str(exc)) if path.startswith('/api/family/') else tr('ui_56c892566df1')})
            except Exception:
                LOG.error("Mini App mutation failed")
                self.respond(500, {"error": tr('ui_481b37e9167a')})

    server = MiniAppServer((host, port), Handler)
    server.daemon_threads = True
    return server
