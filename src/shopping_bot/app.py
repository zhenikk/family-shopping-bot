from __future__ import annotations

import hmac
import logging
import os
import time
import threading
import uuid
import re
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .categories import CATEGORIES, infer_category
from .speech import SpeechError, transcribe
from .store import STORES, Store, parse_items
from .telegram import Telegram, TelegramError
from .families import Families

LOG = logging.getLogger("shopping_bot")
STORE_CODES = {"M": "Mercadona", "L": "Lidl", "A": "Auchan"}


def buttons(*rows: list[tuple[str, str]]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in rows
        ]
    }


class ShoppingBot:
    def __init__(
        self,
        telegram: Telegram,
        store: Store,
        invite_code: str,
        media_dir: Path,
        whisper_cli: Path,
        whisper_model: Path,
    ):
        self.telegram = telegram
        self.legacy_store = store
        self.invite_code = invite_code
        self.legacy_media_dir = media_dir
        media_dir.mkdir(parents=True, exist_ok=True)
        self.families = Families(store, media_dir)
        self.family_context = ContextVar("shopping_family", default="legacy")
        self.whisper_cli = whisper_cli
        self.whisper_model = whisper_model
        self.pending_photos: dict[int, str] = {}
        self.pending_notes: dict[int, int] = {}
        self.note_panels: dict[int, int] = {}
        self.pending_draft_edits: dict[int, tuple] = {}
        self.pending_family_names: set[int] = set()
        self.purchase_feedback: dict[int, int] = {}
        self.notification_lock = threading.Lock()
        self.voice_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-voice")

    @property
    def store(self):
        return self.families.resources(self.family_context.get())[0]

    @property
    def media_dir(self):
        return self.families.resources(self.family_context.get())[1]

    def bind_user(self, user_id):
        family = self.families.family(user_id)
        self.family_context.set(family or "legacy")
        return family is not None

    def show_invite(self, user_id):
        username=self.telegram.call('getMe')['username']
        token=self.families.create_invite(user_id)
        link=f"https://t.me/{username}?start=invite_{token}"
        self.send(user_id,'Одноразове запрошення до вашої сім’ї. Працює до використання або скасування.\n\n'+link,reply_markup=buttons([('Скасувати запрошення','family:revoke:'+token)]))

    def show_invite_preview(self,user_id,token):
        info=self.families.invite_info(token,user_id)
        if not info:
            self.send(user_id,'Запрошення використане, скасоване або недійсне. Попросіть нове посилання.')
            return
        if self.families.family(user_id)==info['family_id']:
            self.send(user_id,'Ви вже в цій сім’ї.')
            self.show_family(user_id)
            return
        current=self.families.details(user_id)
        people=self.families.members(current['id']) if current else []
        lines=[f"{info['inviter']} запрошує до «{info['name']}»."]
        rows=[]
        if current and current['owner_id']==user_id and len(people)>1:
            lines.append('Перед переходом передайте роль засновника іншому учаснику через «Сім’я».')
            rows.append([('Керувати сім’єю','family:show')])
        elif len(people)==1:
            lines.append('Попередня сім’я буде видалена після переходу. Перенести активний список із фото та нотатками? Каталог куплених товарів та історія не переносяться.')
            rows.extend([[('Перенести список і приєднатися','family:accept:1:'+token)],[('Не переносити й приєднатися','family:accept:0:'+token)]])
        else:
            lines.append('Приєднатися до спільного списку?'+(' Ви вийдете з попередньої сім’ї; її дані залишаться учасникам.' if current else ''))
            rows.append([('Приєднатися','family:accept:0:'+token)])
        self.send(user_id,'\n\n'.join(lines),reply_markup=buttons(*rows))

    def show_family(self, user_id, message_id=None):
        current=self.families.details(user_id)
        if not current:
            self.send(user_id,'Ви ще не в сім’ї. Створіть сім’ю або відкрийте запрошення.',reply_markup=buttons([('Створити сім’ю','family:create')]))
            return
        members=self.families.members(current['id'])
        lines=[f"👥 {current['name']} · {len(members)} учасників",'']
        for member in members:
            suffix=(' (ви)' if member['user_id']==user_id else '')+(' · засновник' if member['user_id']==current['owner_id'] else '')
            lines.append('• '+member['name']+suffix)
        rows=[[('Запросити учасника','family:invite')],[('Змінити назву','family:rename'),('Оновити','family:show')]]
        if current['owner_id']==user_id:
            if len(members)>1:
                rows.append([('Передати роль засновника','family:owners')])
            rows.append([('Видалити сім’ю','family:delete')])
        rows.append([('Вийти із сім’ї','family:leave')])
        for invite in self.families.invites(user_id):
            if invite['created_by']==user_id or current['owner_id']==user_id:
                rows.append([('Скасувати запрошення · '+invite['created_at'][:10],'family:revoke:'+invite['token'])])
        self.panel(user_id,'\n'.join(lines),buttons(*rows),message_id)

    def clear_pending(self,user_id):
        self.pending_notes.pop(user_id,None)
        self.pending_photos.pop(user_id,None)
        self.pending_draft_edits.pop(user_id,None)
        self.pending_family_names.discard(user_id)

    def send(self, chat_id: int, text: str, **kwargs):
        result=self.telegram.call("sendMessage", chat_id=chat_id, text=text, **kwargs)
        self.families.route_message(chat_id,result['message_id'],self.family_context.get() if self.families.family(chat_id) else 'none')
        return result

    def panel(self, user_id: int, text: str, markup: dict, message_id: int | None = None) -> int:
        if message_id is not None:
            self.store.forget_view(user_id, message_id)
            try:
                self.telegram.call("editMessageText", chat_id=user_id, message_id=message_id,
                                   text=text, reply_markup=markup)
                self.families.route_message(user_id,message_id,self.family_context.get())
                return message_id
            except TelegramError as exc:
                if "message is not modified" in str(exc).lower():
                    return message_id
        return self.send(user_id, text, reply_markup=markup)["message_id"]

    def menu(self) -> dict:
        return {
            "keyboard": [[{"text": "🛍 Покупки"}],
                         [{"text": "🎙 Додати голосом"}, {"text": "📋 Список у чаті"}],
                         [{"text": "👥 Сім’я"}]],
            "input_field_placeholder": "Товари текстом або голосом",
            "resize_keyboard": True, "is_persistent": True,
        }

    def show_web_app(self, user_id: int) -> None:
        url = os.getenv("SHOPPING_WEB_URL", "")
        if url.startswith("https://"):
            # Inline/menu launches carry authenticated initData; reply-keyboard
            # web_app launches do not (Telegram's documented launch semantics).
            self.send(user_id, "🛍 Наші покупки · список, фото та нотатки", reply_markup={
                "inline_keyboard": [[{"text": "Відкрити застосунок", "web_app": {"url": url}}]]
            })
        else:
            self.send(user_id, "Застосунок ще не під’єднаний. Поки користуйтеся списком у чаті.")

    def handle_update(self, update: dict) -> None:
        previous = self.family_context.set("legacy")
        try:
            if "message" in update:
                self.handle_message(update["message"])
            elif "callback_query" in update:
                self.handle_callback(update["callback_query"])
        finally:
            self.family_context.reset(previous)

    def handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        user = message.get("from", {})
        if chat.get("type") != "private" or not user.get("id"):
            return
        user_id = int(user["id"])
        text = (message.get("text") or "").strip()
        registered = self.bind_user(user_id)
        name = user.get("first_name") or "Учасник"
        pasted=re.search(r'(?:\?|&)start=invite_([A-Za-z0-9_-]{20,64})',text)
        if pasted:
            self.show_invite_preview(user_id,pasted.group(1))
            return
        if text.startswith('/start invite_'):
            self.show_invite_preview(user_id,text.split('invite_',1)[1])
            return
        if text=='/create':
            _,status=self.families.enroll(user_id,name)
            self.bind_user(user_id)
            self.send(user_id,'Ви вже маєте сім’ю.' if status=='already' else 'Сім’ю створено. Запросіть близьких або відкрийте покупки.',reply_markup=self.menu())
            self.show_family(user_id)
            self.show_web_app(user_id)
            return
        if text.startswith("/whoami"):
            self.send(user_id, f"Ваш Telegram ID: {user_id}")
            return
        if text.startswith("/join"):
            supplied = text.partition(" ")[2].strip()
            if not supplied or not hmac.compare_digest(supplied, self.invite_code):
                self.send(user_id, "Неправильний код. Надішліть /join КОД.")
                return
            _,status=self.families.enroll(user_id, name, legacy=True)
            if status=='invalid':
                self.send(user_id,'Стару сім’ю видалено. Створіть нову через /start або прийміть запрошення.')
                return
            self.bind_user(user_id)
            self.send(user_id, "Готово! Ваш сімейний список доступний.", reply_markup=self.menu())
            return
        if not registered:
            self.send(user_id, "Створіть сім’ю або приєднайтеся за запрошенням. Можна відкрити посилання чи надіслати його в цей чат.", reply_markup=buttons([("Створити сім’ю", "family:create"),("Приєднатися", "family:joinhelp")]))
            self.show_web_app(user_id)
            return
        if user_id in self.pending_family_names and text and not text.startswith('/'):
            try:
                renamed=self.families.rename(user_id,text)
            except ValueError as exc:
                self.send(user_id,str(exc))
                return
            self.pending_family_names.discard(user_id)
            self.send(user_id,'Назву оновлено.' if renamed else 'Сім’я більше недоступна.')
            self.show_family(user_id)
            return
        if text in ("/family", "👥 Сім’я"):
            self.clear_pending(user_id)
            self.pending_notes.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.show_family(user_id)
            return
        if text in ("/invite", "👥 Запросити до сім’ї"):
            self.pending_notes.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.show_invite(user_id)
            return
        if text.startswith("/start") or text.startswith("/help"):
            self.clear_pending(user_id)
            self.pending_photos.pop(user_id, None)
            self.pending_notes.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
            self.send(user_id,
                "Ваш спільний список покупок. Відкрийте застосунок або надішліть товари текстом чи голосом.\n/family — учасники сім’ї.\n/invite — запросити учасника.",
                reply_markup=self.menu())
            if os.getenv("SHOPPING_WEB_URL", "").startswith("https://"):
                self.show_web_app(user_id)
            return
        if text.startswith("/cancel"):
            self.pending_family_names.discard(user_id)
            edit = self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.pending_notes.pop(user_id, None)
            if edit:
                self.show_draft(user_id, edit[0], edit[2])
            else:
                self.send(user_id, "Дію скасовано.")
            return
        if text in ("🛒 Список", "📚 Каталог", "🕘 Історія", "➕ Додати", "🛍 Застосунок", "🛍 Покупки", "🎙 Додати голосом", "📋 Список у чаті", *STORES) or text.startswith(("/list", "/catalog", "/history", "/app")):
            self.pending_notes.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
        if user_id in self.pending_draft_edits:
            if text:
                self.finish_draft_edit(user_id, text)
            else:
                self.send(user_id, "Надішліть виправлення текстом або /cancel, щоб повернутися до чернетки.")
            return
        if user_id in self.pending_notes and text:
            if len(text) > 200:
                self.send(user_id, "Нотатка має бути до 200 символів. Спробуйте коротше або /cancel.")
                return
            product_id = self.pending_notes.pop(user_id)
            self.store.set_note(product_id, text)
            self.show_item(user_id, product_id, self.note_panels.pop(user_id, None))
            self.refresh_views()
            return
        if message.get("photo"):
            self.handle_photo(user_id, message)
            return
        if message.get("voice"):
            self.send(user_id, "Голосове в черзі. Повідомлю, коли почну розпізнавання.")
            self.voice_pool.submit(copy_context().run, self.process_voice, user_id, message["voice"]["file_id"],
                                   self.pending_notes.get(user_id))
            return
        if not text:
            self.send(user_id, "Надішліть список текстом, голосове або фото товару з підписом.")
            return
        if user_id in self.pending_photos:
            file_id = self.pending_photos.pop(user_id)
            self.save_photo(user_id, text, file_id)
            return
        if text in ("🛍 Застосунок", "🛍 Покупки", "/app"):
            self.show_web_app(user_id)
        elif text in STORES or text in ("🛒 Список", "📋 Список у чаті"):
            self.show_list(user_id)
        elif text in ("➕ Додати", "🎙 Додати голосом"):
            self.send(user_id, "🎙 Надішліть голосове українською: «молоко, яйця, хліб». Покажу чернетку для перевірки.",
                      reply_markup=buttons([("Скасувати", "list:all")]))
        elif text == "📚 Каталог" or text.startswith("/catalog"):
            self.show_catalog(user_id)
        elif text == "🕘 Історія" or text.startswith("/history"):
            self.show_history(user_id)
        elif text.startswith("/list"):
            self.show_list(user_id)
        elif text.startswith("/add "):
            self.make_draft(user_id, text[5:])
        elif text.startswith("/"):
            self.send(user_id, "Невідома команда. Натисніть /help.")
        else:
            self.make_draft(user_id, text)

    def make_draft(self, user_id: int, raw: str) -> None:
        items = parse_items(raw)
        if not items:
            self.send(user_id, "Не знайшов товарів. Спробуйте: молоко, яйця, хліб.")
            return
        draft_items = []
        for name, note in items:
            existing = self.store.product_by_name(name)
            draft_items.append({"key": uuid.uuid4().hex[:8], "name": name,
                                "note": ("Купити в " + note if note in STORES else note) or (existing["note"] if existing else ""),
                                "category": existing["category"] if existing else infer_category(name)})
        self.pending_draft_edits.pop(user_id, None)
        draft_id = self.store.save_draft(user_id, draft_items)
        self.show_draft(user_id, draft_id)

    def show_draft(self, user_id: int, draft_id: int, panel_id=None, editing=False) -> None:
        items = self.store.draft(user_id, draft_id)
        if items is None:
            self.panel(user_id, "Цю чернетку вже оброблено.", buttons([("До списку", "list:all")]), panel_id)
            return
        lines = [f"Додати до спільного списку? · {len(items)} товарів"]
        for index, item in enumerate(items, 1):
            lines.append(f"{index}. {item['name']} · {CATEGORIES[item['category']]}" + (f"\n   📝 {item['note']}" if item['note'] else ""))
        controls = []
        if editing:
            lines.append("\nОберіть товар для виправлення:")
            controls += [[(item["name"][:35], f"ditem:{draft_id}:{item['key']}")] for item in items]
        if items:
            controls.append([("✅ Додати", f"confirm:{draft_id}"), ("✏️ Виправити", f"dedit:{draft_id}")])
        else:
            lines.append("Чернетка порожня. Надішліть новий список.")
        controls.append([("Скасувати", f"cancel:{draft_id}")])
        self.panel(user_id, "\n".join(lines)[:3900], buttons(*controls), panel_id)

    def show_draft_item(self, user_id, draft_id, key, panel_id):
        items = self.store.draft(user_id, draft_id)
        item = next((item for item in items or [] if item["key"] == key), None)
        if item is None:
            self.show_draft(user_id, draft_id, panel_id, editing=True)
            return
        self.panel(user_id, f"✏️ {item['name']}\n{CATEGORIES[item['category']]}\nНотатка: {item['note'] or '—'}", buttons(
            [("Назва", f"dname:{draft_id}:{key}"), ("Нотатка", f"dnote:{draft_id}:{key}")],
            [("Категорія", f"dcats:{draft_id}:{key}"), ("Прибрати", f"ddel:{draft_id}:{key}")],
            [("⬅️ До чернетки", f"dedit:{draft_id}")]), panel_id)

    def finish_draft_edit(self, user_id, text):
        draft_id, key, panel_id, field = self.pending_draft_edits[user_id]
        limit = 120 if field == "name" else 200
        if len(text) > limit:
            self.send(user_id, f"До {limit} символів. Спробуйте коротше або /cancel.")
            return
        self.store.change_draft(user_id, draft_id, key, {field: "" if field == "note" and text == "-" else text.strip()})
        self.pending_draft_edits.pop(user_id, None)
        self.show_draft_item(user_id, draft_id, key, panel_id)

    def process_voice(self, user_id: int, file_id: str, note_product_id: int | None = None) -> None:
        expected_family=self.family_context.get()
        if self.families.family(user_id)!=expected_family:
            self.send(user_id,'Голосове не додано: сім’ю переключено. Надішліть його ще раз у потрібній сім’ї.')
            return
        if not self.bind_user(user_id):
            return
        try:
            self.send(user_id, "Розпізнаю голосове повідомлення локально…")
            transcript = transcribe(self.telegram, file_id, self.whisper_cli, self.whisper_model)
            if self.families.family(user_id)!=expected_family:
                self.send(user_id,'Голосове не додано: під час розпізнавання сім’ю переключено.')
                return
            if not transcript:
                self.send(user_id, "Не вдалося розпізнати повідомлення. Спробуйте ще раз або надішліть текст.")
                return
            if note_product_id is not None:
                # A delayed transcription must not replace a cancelled or edited note.
                if self.pending_notes.get(user_id) != note_product_id:
                    return
                if len(transcript) > 200:
                    self.send(user_id, "Нотатка має бути до 200 символів. Надішліть коротше голосове або текст, або /cancel.")
                    return
                self.store.set_note(note_product_id, transcript)
                self.pending_notes.pop(user_id, None)
                self.send(user_id, f"Нотатку збережено: {transcript}")
                self.show_item(user_id, note_product_id, self.note_panels.pop(user_id, None))
                self.refresh_views()
                return
            self.send(user_id, f"Почув: {transcript}")
            self.make_draft(user_id, transcript)
        except (SpeechError, TelegramError) as exc:
            self.send(user_id, f"{exc}. Повідомлення можна надіслати текстом.")
        except Exception:
            LOG.exception("Voice processing failed for user %s", user_id)
            self.send(user_id, "Помилка розпізнавання. Спробуйте текстовий список.")

    def handle_photo(self, user_id: int, message: dict) -> None:
        file_id = message["photo"][-1]["file_id"]
        caption = (message.get("caption") or "").strip()
        if caption:
            self.save_photo(user_id, caption, file_id)
        else:
            self.pending_photos[user_id] = file_id
            self.send(user_id, "Напишіть назву товару для цього фото. Щоб скасувати, /cancel.")

    def save_photo(self, user_id: int, raw_name: str, file_id: str) -> None:
        items = parse_items(raw_name, split_conjunctions=False)
        if len(items) != 1:
            self.send(user_id, "Для фото потрібна одна назва товару, наприклад: молоко.")
            return
        name, preferred = items[0]
        destination = self.media_dir / f"{uuid.uuid4().hex}.jpg"
        try:
            self.telegram.download(file_id, destination)
        except TelegramError as exc:
            self.send(user_id, f"Не вдалося зберегти фото: {exc}")
            return
        product_id = self.store.ensure_product(name, preferred)
        self.store.set_photo(product_id, file_id, str(destination))
        added = self.store.add_need(product_id, user_id)
        self.send(user_id,
            f"Фото для «{name}» збережено. " +
            ("Товар додано до списку." if added else "Товар уже є в активному списку."))
        self.refresh_views()

    def list_content(self, store_name: str = "") -> tuple[str, dict]:
        rows = self.store.needs()
        order = list(CATEGORIES)
        rows = sorted(rows, key=lambda row: (order.index(row["category"]) if row["category"] in order else len(order), row["name"].casefold()))
        lines = ["🛒 Спільний список"]
        keyboard = []
        previous = None
        shown = 0
        for row in rows[:40]:
            if sum(len(line) + 1 for line in lines) + len(row["note"]) + 150 > 3600:
                break
            shown += 1
            if row["category"] != previous:
                lines.append("\n" + CATEGORIES.get(row["category"], CATEGORIES["other"]))
                previous = row["category"]
            suffix = " 📷" if row["photo_file_id"] else ""
            lines.append(f"• {row['name'][:70]}{suffix}")
            if row["note"]:
                lines.append(f"  📝 {row['note']}")
            controls = [(row["name"][:28], f"item:{row['id']}"), ("✅ Куплено", f"buy:{row['id']}:all")]
            if row["photo_file_id"]:
                controls.append(("📷", f"photo:{row['id']}"))
            keyboard.append(controls)
        if not rows:
            lines.append("Список порожній для вас обох. Додайте товари текстом чи голосом.")
            keyboard.append([("➕ Додати товари", "add")])
        if len(rows) > shown:
            lines.append(f"\nПоказано {shown} із {len(rows)} товарів. Куплені зникатимуть, решта з’являться далі.")
        keyboard.append([("🔄 Оновити", "list:all"), ("📚 Каталог", "catalog:0")])
        return "\n".join(lines), buttons(*keyboard)

    def show_list(self, user_id: int, store_name: str = "", message_id: int | None = None) -> None:
        store_name = "all"
        content, markup = self.list_content()
        if message_id is not None:
            try:
                self.telegram.call("editMessageText", chat_id=user_id, message_id=message_id,
                                   text=content, reply_markup=markup)
                self.store.set_view(user_id, store_name, message_id)
                return
            except TelegramError as exc:
                if "message is not modified" in str(exc).lower():
                    self.store.set_view(user_id, store_name, message_id)
                    return
        result = self.send(user_id, content, reply_markup=markup)
        self.store.set_view(user_id, store_name, result["message_id"])

    def refresh_views(self) -> None:
        """Keep each person's latest store lists aligned after shared changes."""
        for view in self.store.views():
            if self.families.family(view['user_id'])!=self.family_context.get():
                continue
            content, markup = self.list_content(view["store"])
            try:
                self.telegram.call("editMessageText", chat_id=view["user_id"],
                                   message_id=view["message_id"], text=content, reply_markup=markup)
            except TelegramError as exc:
                if "message is not modified" not in str(exc).lower():
                    LOG.warning("Could not refresh shopping list: %s", exc)

    def show_catalog(self, user_id: int, offset: int = 0, message_id: int | None = None) -> None:
        count = self.store.catalog_count()
        rows = self.store.catalog(offset)
        lines = [f"📚 Каталог · {count} товарів · {offset // 10 + 1}/{max(1, (count + 9) // 10)}", "Оберіть товар для повторної покупки, фото чи нотатки."]
        keyboard = [[(f"{r['name'][:36]}{' ✅' if r['active'] else ''}", f"item:{r['id']}")] for r in rows]
        pages = []
        if offset > 0:
            pages.append(("⬅️ Назад", f"catalog:{max(0, offset - 10)}"))
        if offset + 10 < count:
            pages.append(("Далі ➡️", f"catalog:{offset + 10}"))
        if pages:
            keyboard.append(pages)
        if not rows:
            lines.append("Ще немає товарів. Надішліть назви або фото з підписом.")
        keyboard.append([("🛒 До списку", "list:all")])
        self.panel(user_id, "\n".join(lines), buttons(*keyboard), message_id)

    def show_item(self, user_id: int, product_id: int, message_id: int | None = None) -> None:
        product = self.store.product(product_id)
        if not product:
            self.send(user_id, "Товар не знайдено.")
            return
        active = any(row["id"] == product_id for row in self.store.needs())
        text = f"{product['name']}\n{CATEGORIES.get(product['category'], CATEGORIES['other'])}"
        text += "\nУ списку покупок" if active else "\nЗбережено в каталозі"
        if product["note"]:
            text += f"\n\n📝 {product['note']}"
        rows = [[("✅ Куплено", f"buy:{product_id}:all")] if active else [("➕ До списку", f"readd:{product_id}")]]
        rows.append([("📝 Змінити нотатку" if product["note"] else "📝 Додати нотатку", f"note:{product_id}")])
        if product["note"]:
            rows[-1].append(("Прибрати", f"clearnote:{product_id}"))
        if product["photo_file_id"]:
            rows.append([("📷 Фото упаковки", f"photo:{product_id}")])
        else:
            text += "\n\n📷 Щоб додати фото, надішліть його з назвою цього товару в підписі."
        rows.append([("🗂 Категорія", f"categories:{product_id}")])
        rows.append([("🛒 До списку", "list:all"), ("📚 Каталог", "catalog:0")])
        self.panel(user_id, text, buttons(*rows), message_id)

    def show_history(self, user_id: int) -> None:
        events = self.store.recent_history()
        if not events:
            self.send(user_id, "Історія поки порожня.")
            return
        lines = ["🕘 Останні дії:"]
        verbs = {"added": "додав(ла)", "bought": "купив(ла)", "restored": "повернув(ла) у список"}
        for event in events:
            local = datetime.fromisoformat(event["happened_at"]).astimezone(ZoneInfo("Europe/Lisbon"))
            suffix = f" у {event['store']}" if event["store"] else ""
            if event["undone"]:
                suffix += " (скасовано)"
            lines.append(f"{local:%d.%m %H:%M} — {event['actor_name']} {verbs.get(event['action'], event['action'])} "
                         f"{event['product_name']}{suffix}")
        self.send(user_id, "\n".join(lines))

    def notify_partner(self, batch_id: int) -> None:
        # Web requests can arrive concurrently; keep one notification per batch.
        with self.notification_lock:
            self._notify_partner(batch_id)

    def _notify_partner(self, batch_id: int) -> None:
        batch = self.store.batch(batch_id)
        if not batch:
            return
        partners = [row for row in self.families.members(self.family_context.get()) if row['user_id']!=batch['actor_id']]
        if not partners:
            return
        items = self.store.batch_items(batch_id)
        actor = self.store.member_name(batch["actor_id"])
        if items:
            shown = [name[:70] + ("…" if len(name) > 70 else "") for name in items[:40]]
            text = f"{actor} купив(ла):\n" + "\n".join(f"✅ {name}" for name in shown)
            if len(items) > 40:
                text += f"\n…і ще {len(items) - 40} товарів. Усі є в історії."
        else:
            text = f"{actor} скасував(ла) покупки."
        for partner in partners:
            notification = self.store.notification(batch_id, partner["user_id"])
            if notification:
                try:
                    self.telegram.call("editMessageText", chat_id=partner["user_id"],
                                       message_id=notification, text=text)
                    continue
                except TelegramError as exc:
                    if "message is not modified" in str(exc).lower():
                        continue
                    LOG.warning("Could not edit purchase notification")
            try:
                result = self.send(partner["user_id"], text)
                self.store.save_notification(batch_id, partner["user_id"], result["message_id"])
                if len(partners) == 1:
                    self.store.set_batch_notification(batch_id, result["message_id"])
            except TelegramError:
                LOG.warning("Could not send purchase notification")

    def handle_family_action(self,user_id,name,data,message_id=None):
        current=self.families.details(user_id)
        if data.startswith('family:join:'):
            self.show_invite_preview(user_id,data.split(':',2)[2])
            return
        if data.startswith('family:accept:'):
            _,_,mode,token=data.split(':',3)
            status=self.families.accept_invite(user_id,name,token,transfer=mode=='1',expected_family=self.families.family(user_id))
            if status in ('joined','already'):
                self.clear_pending(user_id)
                self.bind_user(user_id)
                self.send(user_id,'Готово! Ви в спільній сім’ї. Відкрийте покупки.',reply_markup=self.menu())
                self.show_family(user_id)
                self.show_web_app(user_id)
            else:
                errors={'owner_required':'Спочатку передайте роль засновника іншому учаснику.','transfer_forbidden':'Перенесення доступне лише коли ви єдиний учасник попередньої сім’ї.','stale':'Сім’ю змінено. Відкрийте запрошення знову.'}
                self.send(user_id,errors.get(status,'Запрошення використане, скасоване або недійсне.'))
            return
        if not current:
            self.show_family(user_id)
            return
        if data=='family:show':
            self.show_family(user_id,message_id)
        elif data=='family:invite':
            self.show_invite(user_id)
        elif data.startswith('family:revoke:'):
            revoked=self.families.revoke_invite(user_id,data.split(':',2)[2])
            self.send(user_id,'Запрошення скасовано.' if revoked else 'Запрошення вже недоступне або ви не маєте права його скасувати.')
            self.show_family(user_id)
        elif data=='family:rename':
            self.clear_pending(user_id)
            self.pending_family_names.add(user_id)
            self.send(user_id,'Надішліть нову назву сім’ї (до 60 символів) або /cancel.')
        elif data=='family:owners':
            if current['owner_id']!=user_id:
                self.send(user_id,'Передати роль може лише засновник.')
                return
            rows=[[(row['name'],'family:owner:'+str(row['user_id']))] for row in self.families.members(current['id']) if row['user_id']!=user_id]
            rows.append([('Скасувати','family:show')])
            self.panel(user_id,'Кому передати роль засновника?',buttons(*rows),message_id)
        elif data.startswith('family:owner:'):
            target=int(data.split(':',2)[2])
            if current['owner_id']==user_id and self.families.family(target)==current['id']:
                self.panel(user_id,'Передати роль засновника учаснику «'+self.store.member_name(target)+'»? Він зможе видаляти сім’ю.',buttons([('Передати','family:owner-confirm:'+str(target))],[('Скасувати','family:show')]),message_id)
        elif data.startswith('family:owner-confirm:'):
            success=self.families.transfer_owner(user_id,int(data.split(':',2)[2]))
            self.send(user_id,'Роль передано.' if success else 'Передача недоступна. Оновіть сім’ю.')
            self.show_family(user_id)
        elif data in ('family:delete','family:leave'):
            deleting=data=='family:delete'
            if deleting and current['owner_id']!=user_id:
                self.send(user_id,'Видалити сім’ю може лише засновник.')
                return
            people=self.families.members(current['id'])
            if not deleting and current['owner_id']==user_id and len(people)>1:
                self.send(user_id,'Перед виходом передайте роль засновника іншому учаснику.')
                self.show_family(user_id)
                return
            description=(f"Видалити «{current['name']}» для всіх? Учасників: {len(people)}, товарів: {self.store.catalog_count()}. Список і каталог стануть недоступними; резервні копії можуть містити попередні дані." if deleting else 'Вийти з сім’ї? Ви втратите доступ до спільного списку.'+(' Ви єдиний учасник, тому сім’ю буде видалено.' if len(people)==1 else ' Дані інших учасників залишаться.'))
            action='family:delete-confirm:' if deleting else 'family:leave-confirm:'
            self.panel(user_id,description,buttons([('Підтвердити',action+current['id'])],[('Скасувати','family:show')]),message_id)
        elif data.startswith(('family:delete-confirm:','family:leave-confirm:')):
            if data.split(':',2)[2]!=current['id']:
                self.send(user_id,'Сім’ю змінено. Оновіть екран.')
                return
            status=self.families.delete(user_id) if data.startswith('family:delete-confirm:') else self.families.leave(user_id)
            if status is True or status=='left':
                self.clear_pending(user_id)
                self.bind_user(user_id)
                self.send(user_id,'Готово. Створіть нову сім’ю або прийміть запрошення.',reply_markup=buttons([('Створити сім’ю','family:create'),('Приєднатися','family:joinhelp')]))
            else:
                self.send(user_id,'Дія недоступна. Засновник перед виходом має передати роль.')

    def handle_callback(self, query: dict) -> None:
        user = query.get("from", {})
        user_id = user.get("id")
        message = query.get("message") or {}
        if not user_id or message.get("chat", {}).get("type") != "private":
            return
        callback_id = query.get("id")
        registered = self.bind_user(user_id)
        if query.get('data')=='family:joinhelp':
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            self.send(user_id,'Попросіть учасника сім’ї створити одноразове запрошення. Відкрийте посилання або надішліть його сюди.')
            return
        if query.get("data") == "family:create":
            self.telegram.call("answerCallbackQuery", callback_query_id=callback_id)
            self.handle_message({"from": user, "chat": message["chat"], "text": "/create"})
            return
        if query.get('data','').startswith(('family:accept:','family:join:')):
            route=self.families.message_family(user_id,message.get('message_id'))
            if route and route!=(self.families.family(user_id) or 'none'):
                self.telegram.call('answerCallbackQuery',callback_query_id=callback_id,text='Сім’ю змінено. Відкрийте запрошення знову.',show_alert=True)
                return
            self.handle_family_action(user_id,user.get('first_name') or 'Учасник',query['data'],message.get('message_id'))
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            return
        if not registered:
            self.telegram.call("answerCallbackQuery", callback_query_id=callback_id,
                               text="Відкрийте /start і створіть сім’ю або прийміть запрошення.", show_alert=True)
            return
        data=query.get('data','')
        message_family=self.families.message_family(user_id,message.get('message_id'))
        if data not in ('family:show','family:invite') and ((message_family and message_family!=self.families.family(user_id)) or (not message_family and len(self.families.choices(user_id))>1)):
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id,text='Ця кнопка зі старої сім’ї. Відкрийте актуальний список.',show_alert=True)
            return
        if data.startswith('family:'):
            self.handle_family_action(user_id,user.get('first_name') or self.store.member_name(user_id),data,message.get('message_id'))
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            return
        data = query.get("data", "")
        answer = "Готово"
        try:
            parts = data.split(":")
            action = parts[0]
            if action in {"list", "catalog", "item", "categories", "buy", "readd", "add", "dedit", "ditem", "confirm", "cancel"}:
                self.pending_notes.pop(user_id, None)
            if action not in {"dname", "dnote", "photo"}:
                self.pending_draft_edits.pop(user_id, None)
            panel_id = message.get("message_id")
            if panel_id == self.purchase_feedback.get(user_id) and action != "undo":
                self.purchase_feedback.pop(user_id, None)
            if action == "add":
                self.panel(user_id, "➕ Надішліть товари через кому або голосове українською.\nНаприклад: молоко, яйця, хліб.\nБот покаже список для підтвердження.",
                           buttons([("🛒 До списку", "list:all")]), panel_id)
            elif action == "list" and len(parts) == 2:
                self.show_list(user_id, message_id=message.get("message_id"))
            elif action == "dedit" and len(parts) == 2:
                self.show_draft(user_id, int(parts[1]), panel_id, editing=True)
            elif action == "ditem" and len(parts) == 3:
                self.show_draft_item(user_id, int(parts[1]), parts[2], panel_id)
            elif action in {"dname", "dnote", "dcats", "ddel", "dcat"} and len(parts) in {3, 4}:
                draft_id, key = int(parts[1]), parts[2]
                items = self.store.draft(user_id, draft_id)
                item = next((item for item in items or [] if item["key"] == key), None)
                if item is None:
                    answer = "Товар уже прибрано або чернетку оброблено"
                elif action in {"dname", "dnote"}:
                    self.pending_notes.pop(user_id, None)
                    field = "name" if action == "dname" else "note"
                    self.pending_draft_edits[user_id] = (draft_id, key, panel_id, field)
                    self.panel(user_id, f"✏️ {item['name']}\nНадішліть {'нову назву' if field == 'name' else 'нотатку (або - щоб прибрати)'} текстом.",
                               buttons([("Скасувати", f"ditem:{draft_id}:{key}")]), panel_id)
                elif action == "dcats":
                    choices = [[(label, f"dcat:{draft_id}:{key}:{category}")] for category, label in CATEGORIES.items()]
                    choices.append([("⬅️ Назад", f"ditem:{draft_id}:{key}")])
                    self.panel(user_id, "Оберіть категорію:", buttons(*choices), panel_id)
                elif action == "ddel":
                    self.store.change_draft(user_id, draft_id, key, remove=True)
                    self.show_draft(user_id, draft_id, panel_id, editing=True)
                elif action == "dcat" and len(parts) == 4:
                    self.store.change_draft(user_id, draft_id, key, {"category": parts[3]})
                    self.show_draft_item(user_id, draft_id, key, panel_id)
            elif action == "confirm" and len(parts) == 2:
                items = self.store.take_draft(user_id, int(parts[1]))
                if items is None:
                    answer = "Цей список уже оброблено"
                else:
                    added = 0
                    for item in items:
                        product_id = self.store.ensure_product(item["name"])
                        self.store.set_note(product_id, item["note"])
                        self.store.set_category(product_id, item["category"])
                        added += self.store.add_need(product_id, user_id)
                    self.panel(user_id, f"✅ Додано: {added}. Уже у списку: {len(items) - added}.",
                               buttons([("🛒 Відкрити список", "list:all")]), panel_id)
                    if items:
                        self.refresh_views()
            elif action == "cancel" and len(parts) == 2:
                self.store.cancel_draft(user_id, int(parts[1]))
                answer = "Скасовано"
                self.panel(user_id, "Додавання скасовано.", buttons([("🛒 До списку", "list:all")]), panel_id)
            elif action == "buy" and len(parts) == 3:
                product_id, store_name = int(parts[1]), ""
                product = self.store.product(product_id)
                bought, batch_id, event_id = self.store.purchase(product_id, user_id, store_name)
                if bought:
                    answer = f"Куплено: {product['name']}"[:180]
                    self.purchase_feedback[user_id] = self.panel(user_id,
                        f"✅ Остання покупка: {product['name']}",
                        buttons([("↩️ Скасувати останню покупку", f"undo:{event_id}:{batch_id}")]),
                        self.purchase_feedback.get(user_id))
                    self.show_list(user_id, message_id=panel_id)
                    try:
                        self.notify_partner(batch_id)
                    except TelegramError as exc:
                        LOG.warning("Purchase saved; notification failed: %s", exc)
                    self.refresh_views()
                else:
                    answer = "Товар уже куплено"
                    self.show_list(user_id, store_name, message.get("message_id"))
            elif action == "undo" and len(parts) == 3:
                product_id = self.store.undo_purchase(int(parts[1]), user_id)
                if product_id is None:
                    answer = "Уже скасовано"
                else:
                    try:
                        self.notify_partner(int(parts[2]))
                    except TelegramError as exc:
                        LOG.warning("Undo saved; notification failed: %s", exc)
                    self.panel(user_id, f"↩️ Повернуто до списку: {self.store.product(product_id)['name']}",
                               buttons([("🛒 До списку", "list:all")]), panel_id)
                    self.refresh_views()
            elif action == "photo" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product and product["photo_file_id"]:
                    self.telegram.call("sendPhoto", chat_id=user_id, photo=product["photo_file_id"],
                                       caption=product["name"])
                else:
                    answer = "Фото ще немає"
            elif action == "catalog" and len(parts) == 2:
                self.show_catalog(user_id, max(0, int(parts[1])), panel_id)
            elif action == "item" and len(parts) == 2:
                self.show_item(user_id, int(parts[1]), panel_id)
            elif action == "readd" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product:
                    added = self.store.add_need(product["id"], user_id)
                    answer = "Додано" if added else "Уже у списку"
                    self.show_item(user_id, product["id"], panel_id)
                    if added:
                        self.refresh_views()
                else:
                    answer = "Товар не знайдено"
            elif action == "categories" and len(parts) == 2:
                product_id = int(parts[1])
                if self.store.product(product_id):
                    choices = [[(label, f"setcategory:{product_id}:{key}")] for key, label in CATEGORIES.items()]
                    choices.append([("⬅️ До товару", f"item:{product_id}")])
                    self.panel(user_id, f"Категорія · {self.store.product(product_id)['name']}", buttons(*choices), panel_id)
            elif action == "setcategory" and len(parts) == 3:
                self.store.set_category(int(parts[1]), parts[2])
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            elif action == "note" and len(parts) == 2:
                product_id = int(parts[1])
                if self.store.product(product_id):
                    self.pending_notes[user_id] = product_id
                    self.note_panels[user_id] = self.panel(user_id, f"📝 Нотатка · {self.store.product(product_id)['name']}\n\nНадішліть текст або голосове українською (до 200 символів).\nНаприклад: купити в Mercadona.",
                               buttons([("Скасувати", f"item:{product_id}")]), panel_id)
            elif action == "clearnote" and len(parts) == 2:
                self.store.set_note(int(parts[1]), "")
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            elif action == "setstore" and len(parts) == 3:
                self.store.set_note(int(parts[1]), "Купити в " + STORE_CODES[parts[2]])
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            else:
                answer = "Кнопка застаріла"
        except TelegramError as exc:
            LOG.warning("Callback Telegram error for user %s: %s", user_id, exc)
            answer = "Не вдалося виконати дію"
        except (ValueError, KeyError, IndexError):
            LOG.exception("Callback failed for user %s", user_id)
            answer = "Не вдалося виконати дію"
        finally:
            try:
                self.telegram.call("answerCallbackQuery", callback_query_id=callback_id, text=answer)
            except TelegramError:
                LOG.warning("Could not answer callback")

    def run(self) -> None:
        offset = self.legacy_store.get_offset()
        LOG.info("Shopping bot started")
        while True:
            try:
                updates = self.telegram.call(
                    "getUpdates", offset=offset, timeout=25,
                    allowed_updates=["message", "callback_query"],
                )
                for update in updates:
                    try:
                        self.handle_update(update)
                    except Exception:
                        LOG.exception("Failed update %s", update.get("update_id"))
                    offset = update["update_id"] + 1
                    self.legacy_store.set_offset(offset)
            except TelegramError as exc:
                LOG.warning("Telegram polling error: %s", exc)
                time.sleep(5)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    invite = os.environ.get("SHOPPING_INVITE_CODE", "")
    if not token or len(invite) < 12:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and SHOPPING_INVITE_CODE (at least 12 characters)")
    data_dir = Path(os.getenv("SHOPPING_DATA_DIR", "./data")).expanduser().resolve()
    bot = ShoppingBot(
        Telegram(token), Store(data_dir / "shopping.sqlite3"), invite, data_dir / "photos",
        Path(os.getenv("WHISPER_CLI", "./whisper.cpp/build/bin/whisper-cli")),
        Path(os.getenv("WHISPER_MODEL", "./whisper.cpp/models/ggml-small.bin")),
    )
    from .webserver import make_server
    server = make_server(bot, token, os.getenv("SHOPPING_WEB_HOST", "127.0.0.1"),
                         int(os.getenv("SHOPPING_WEB_PORT", "8080")))
    threading.Thread(target=server.serve_forever, daemon=True, name="mini-app").start()
    web_url = os.getenv("SHOPPING_WEB_URL", "")
    if web_url.startswith("https://"):
        try:
            bot.telegram.call("setChatMenuButton", menu_button={"type": "web_app", "text": "Покупки", "web_app": {"url": web_url}})
        except TelegramError:
            LOG.warning("Could not configure Mini App menu button")
    bot.run()


if __name__ == "__main__":
    main()
