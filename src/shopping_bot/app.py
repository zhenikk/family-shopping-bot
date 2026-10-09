from __future__ import annotations
from .support import Support
from .version import release, configure_logging
from .limits import RateLimiter, VoiceAdmission
from .analytics import Analytics
from .i18n import tr, language, CategoryLabels

import hmac
import json
import html
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


CATEGORIES = CategoryLabels(CATEGORIES)


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
        self.started_at = time.monotonic()
        self.last_poll_at = None
        self.telegram = telegram
        self.legacy_store = store
        self.invite_code = invite_code
        self.legacy_media_dir = media_dir
        media_dir.mkdir(parents=True, exist_ok=True)
        self.families = Families(store, media_dir)
        self.analytics = Analytics(self.families)
        self.support = Support(self.families)
        self.admin_ids={int(value.strip()) for value in os.getenv('SHOPPING_ADMIN_IDS','').split(',') if value.strip().isdigit()}

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
        self.update_limits = RateLimiter(30, 1)
        self.voice_admission = VoiceAdmission()
        self.voice_limits = RateLimiter(6, 1 / 60)
        self.photo_limits = RateLimiter(5, 1 / 300)
        self.voice_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-voice")

    @property
    def store(self):
        return self.families.resources(self.family_context.get())[0]

    @property
    def media_dir(self):
        return self.families.resources(self.family_context.get())[1]

    def bind_user(self, user_id):
        language.set(self.families.preference(user_id) or "uk")
        family = self.families.family(user_id)
        self.family_context.set(family or "legacy")
        return family is not None

    def show_usage_choice(self, user_id):
        self.send(user_id, tr('Як плануєте користуватися списком? Для себе або разом з іншими — обидва варіанти повноцінні. Запросити когось можна пізніше.'), reply_markup=buttons([(tr('🙋 Для себе'), 'family:solo')], [(tr('👥 Разом з іншими'), 'family:shared')], [(tr('У мене є запрошення'), 'family:joinhelp')]))

    def start_list(self, user_id, name, mode):
        _, status = self.families.enroll(user_id, name, mode=mode)
        self.bind_user(user_id)
        if status == 'already':
            self.show_list(user_id, bring_to_bottom=True)
            return
        text = 'Ваш особистий список готовий. Додавайте товари текстом або голосом. Запрошувати когось не потрібно; за бажанням це можна зробити пізніше.' if mode == 'solo' else 'Список готовий — вже можна додавати товари. Щоб користуватися разом, запросіть інших у розділі «Сім’я». Це можна зробити пізніше.'
        self.send(user_id, tr(text), reply_markup=self.menu())
        if mode == 'shared':
            self.show_family(user_id)
        self.show_list(user_id)

    def show_invite(self, user_id):
        username=self.telegram.call('getMe')['username']
        token=self.families.create_invite(user_id)
        link=f"https://t.me/{username}?start=invite_{token}"
        self.send(user_id,tr('ui_f275062357b4')+link,reply_markup=buttons([(tr('ui_2be3fb25cd68'),'family:revoke:'+token)]))

    def show_invite_preview(self,user_id,token):
        info=self.families.invite_info(token,user_id)
        if not info:
            self.send(user_id,tr('ui_aef1daa71b4a'))
            return
        if self.families.family(user_id)==info['family_id']:
            self.send(user_id,tr('ui_cdb41a006258'))
            self.show_family(user_id)
            return
        current=self.families.details(user_id)
        people=self.families.members(current['id']) if current else []
        lines=[f"{info['inviter']}{tr('ui_c94b6235f03d')}{info['name']}»."]
        rows=[]
        if current and current['owner_id']==user_id and len(people)>1:
            lines.append(tr('ui_8d6d7c1e81ca'))
            rows.append([(tr('ui_f51530f0cb99'),'family:show')])
        elif len(people)==1:
            lines.append(tr('ui_c2df410b3e53'))
            rows.extend([[(tr('ui_563f940fd610'),'family:accept:1:'+token)],[(tr('ui_fed82bd9ac82'),'family:accept:0:'+token)]])
        else:
            lines.append(tr('ui_463e85e9abca')+(tr('ui_b76585e6073f') if current else ''))
            rows.append([(tr('ui_cc3a50c1e3fb'),'family:accept:0:'+token)])
        self.send(user_id,'\n\n'.join(lines),reply_markup=buttons(*rows))

    def show_family(self, user_id, message_id=None):
        current=self.families.details(user_id)
        if not current:
            self.send(user_id,tr('ui_6337eda17267'),reply_markup=buttons([(tr('ui_fa354ddf77af'),'family:create')]))
            return
        members=self.families.members(current['id'])
        lines=[f"👥 {current['name']} · {len(members)}{tr('ui_5f022cf87ad2')}",'']
        if len(members)==1:
            lines.append(tr('Списком можна повноцінно користуватися самостійно. Запрошення необов’язкове: за бажанням додайте інших учасників пізніше.'))
            lines.append('')
        for member in members:
            suffix=(tr('ui_109e3f46b4ae') if member['user_id']==user_id else '')+(tr('ui_d22aad051523') if member['user_id']==current['owner_id'] else '')
            lines.append('• '+member['name']+suffix)
        rows=[[(tr('ui_aa604e9d68b3'),'family:invite')],[(tr('ui_a1efd43db3c8'),'family:rename'),(tr('ui_fe32bae01c21'),'family:show')]]
        if current['owner_id']==user_id:
            if len(members)>1:
                rows.append([(tr('ui_0e81fbcf3f39'),'family:owners')])
            rows.append([(tr('ui_bca182050a3e'),'family:delete')])
        rows.append([(tr('ui_f4937f3c1393'),'family:leave')])
        for invite in self.families.invites(user_id):
            if invite['created_by']==user_id or current['owner_id']==user_id:
                rows.append([(tr('ui_0823e11095ca')+invite['created_at'][:10],'family:revoke:'+invite['token'])])
        self.panel(user_id,'\n'.join(lines),buttons(*rows),message_id)

    def clear_pending(self,user_id):
        self.support.cancel(user_id)
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
                if not any(reason in str(exc).lower() for reason in ('message to edit not found', "message can't be edited", 'message_id_invalid')):
                    LOG.warning('Panel edit failed; preserving existing message')
                    return message_id
        result = self.send(user_id, text, reply_markup=markup)["message_id"]
        if message_id is not None:
            self.remove_obsolete_panel(user_id, message_id)
        return result

    def show_help(self, user_id, chosen=None, role='c', step=0, message=None):
        chosen = chosen or self.families.preference(user_id) or 'uk'
        if chosen not in ('uk', 'en') or role not in ('c', 'j') or type(step) is not int or not 0 <= step < 6:
            return
        content = json.loads(Path(__file__).with_name('help.json').read_text())[chosen]
        item = content['steps'][role][step]
        caption = f"<b>{step + 1}/6 · {html.escape(item['title'])}</b>\n\n{html.escape(item['body'])}\n\n💡 {html.escape(item['tip'])}"
        rows = [[(content['creator'], f'help:{chosen}:c:0'), (content['invited'], f'help:{chosen}:j:0')]] if step == 0 else []
        navigation = []
        if step:
            navigation.append((content['back'], f'help:{chosen}:{role}:{step-1}'))
        if step < 5:
            navigation.append((content['next'], f'help:{chosen}:{role}:{step+1}'))
        if step == 5:
            navigation.append(('Start again ↺' if chosen == 'en' else 'На початок ↺', f'help:{chosen}:{role}:0'))
        rows.append(navigation)
        rows.append([('🇺🇦 UA', f'help:uk:{role}:{step}'), ('🇬🇧 EN', f'help:en:{role}:{step}')])
        markup = buttons(*(row for row in rows if row))
        url = os.getenv('SHOPPING_WEB_URL', '').rstrip('/')
        anchor = self.families.ui_panel(user_id, 'help')
        legacy = message and (message.get('photo') or re.match(r'^[1-6]/6', message.get('text', '')))
        target = anchor['message_id'] if anchor else message['message_id'] if legacy else None
        media = bool(anchor['media']) if anchor else bool(legacy and message.get('photo'))
        signature = json.dumps([chosen, role, step, caption, markup], ensure_ascii=False)
        if anchor and anchor['signature'] == signature:
            if legacy and message['message_id'] != target:
                self.remove_obsolete_panel(user_id, message['message_id'])
            return
        photo = f"{url}/help/{chosen}-{role}-{step}.png?v={release()['commit']}"
        if target:
            try:
                if media:
                    if url.startswith('https://'):
                        self.telegram.call('editMessageMedia', chat_id=user_id, message_id=target, media={'type':'photo','media':photo,'caption':caption,'parse_mode':'HTML'}, reply_markup=markup)
                    else:
                        self.telegram.call('editMessageCaption', chat_id=user_id, message_id=target, caption=caption, parse_mode='HTML', reply_markup=markup)
                else:
                    self.telegram.call('editMessageText', chat_id=user_id, message_id=target, text=caption, parse_mode='HTML', reply_markup=markup)
                self.families.save_ui_panel(user_id, 'help', target, media, signature)
                if legacy and message['message_id'] != target:
                    self.remove_obsolete_panel(user_id, message['message_id'])
                return
            except TelegramError as exc:
                if 'message is not modified' in str(exc).lower():
                    self.families.save_ui_panel(user_id, 'help', target, media, signature)
                    return
                if not any(reason in str(exc).lower() for reason in ('message to edit not found', "message can't be edited", 'message_id_invalid')):
                    LOG.warning('Help panel edit failed; preserving existing message')
                    return
        result = None
        if url.startswith('https://'):
            try:
                result = self.telegram.call('sendPhoto', chat_id=user_id, photo=photo, caption=caption, parse_mode='HTML', reply_markup=markup)
                media = True
            except TelegramError:
                LOG.warning('Help illustration unavailable; sending text guide')
        if result is None:
            result = self.send(user_id, caption, parse_mode='HTML', reply_markup=markup)
            media = False
        self.families.save_ui_panel(user_id, 'help', result['message_id'], media, signature)
        if target:
            self.remove_obsolete_panel(user_id, target)

    def remove_obsolete_panel(self, user_id, message_id):
        try:
            self.telegram.call('deleteMessage', chat_id=user_id, message_id=message_id)
        except TelegramError:
            try:
                self.telegram.call('editMessageReplyMarkup', chat_id=user_id, message_id=message_id, reply_markup={'inline_keyboard':[]})
            except TelegramError:
                LOG.info('Old panel could not be removed')

    def show_language(self,user_id):
        self.send(user_id,'Оберіть мову / Choose your language',reply_markup=buttons([('🇺🇦 Українська','language:uk'),('🇬🇧 English','language:en')], [('📖 Як користуватися / Help', 'help:uk:c:0')]))

    def menu(self) -> dict:
        return {
            "keyboard": [[{"text": tr('ui_58d659bf993e')}],
                         [{"text": tr('ui_8c4317311ad3')}, {"text": tr('ui_45b58c75117f')}],
                         [{"text": tr('ui_33ed8513acbd')}, {"text": "🌐 Language" if language.get()=="en" else "🌐 Мова"}],
                         [{"text": tr("🐞 Повідомити про проблему")}, {"text": "📖 How to use" if language.get()=="en" else "📖 Як користуватися"}]],
            "input_field_placeholder": tr('ui_366933c83ece'),
            "resize_keyboard": True, "is_persistent": True,
        }

    def show_web_app(self, user_id: int) -> None:
        url = os.getenv("SHOPPING_WEB_URL", "")
        if url.startswith("https://"):
            try:
                self.telegram.call('setChatMenuButton',chat_id=user_id,menu_button={'type':'web_app','text':'Shopping' if language.get()=='en' else 'Покупки','web_app':{'url':url}})
            except TelegramError:
                LOG.warning('Could not update personal app menu')
            # Inline/menu launches carry authenticated initData; reply-keyboard
            # web_app launches do not (Telegram's documented launch semantics).
            self.send(user_id, tr('ui_02e3f68d1e6a'), reply_markup={
                "inline_keyboard": [[{"text": tr('ui_be653d74c655'), "web_app": {"url": url}}]]
            })
        else:
            self.send(user_id, tr('ui_486022a30c33'))

    def handle_update(self, update: dict) -> None:
        event = update.get('guest_message') or update.get('message') or update.get('callback_query') or {}
        user_id = event.get('from', {}).get('id')
        if 'guest_message' in update:
            LOG.info('Guest update: caller=%s query=%s voice=%s reply=%s', type(user_id) is int, bool(event.get('guest_query_id')), bool(event.get('voice')), bool(event.get('reply_to_message')))
        if type(user_id) is not int or not self.update_limits.allow(user_id):
            return
        previous = self.family_context.set("legacy")
        try:
            with self.families.lock:
                if "guest_message" in update:
                    self.handle_guest_message(update["guest_message"])
                elif "message" in update:
                    self.handle_message(update["message"])
                elif "callback_query" in update:
                    self.handle_callback(update["callback_query"])
        finally:
            self.family_context.reset(previous)

    def handle_guest_message(self, message: dict) -> None:
        """Guest chats are untrusted destinations; drafts stay in the caller's DM."""
        user = message.get("from", {})
        user_id = user.get("id")
        query_id = message.get("guest_query_id")
        if type(user_id) is not int or user.get("is_bot") or not query_id:
            return
        registered = self.bind_user(user_id)
        english = language.get() == "en"
        username = self.telegram.call("getMe")["username"]
        def answer(text):
            self.telegram.call("answerGuestQuery", guest_query_id=query_id, result={
                "type": "article", "id": "shopping", "title": "Shopping list",
                "input_message_content": {"message_text": text},
                "reply_markup": {"inline_keyboard": [[{
                    "text": "Open bot" if english else "Відкрити бота",
                    "url": f"https://t.me/{username}",
                }]]},
            })
        if not registered:
            answer("Open the bot and create or join a list first." if english else
                   "Спочатку відкрийте бота та створіть список або приєднайтеся до нього.")
            return
        voice = message.get("voice") or message.get("reply_to_message", {}).get("voice")
        raw = re.sub(r"@" + re.escape(username) + r"\b", "", message.get("text") or "", flags=re.IGNORECASE).strip()
        for prefix in ("додай ", "додати ", "add "):
            if raw.lower().startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        if not raw and not voice:
            original = message.get("reply_to_message", {})
            raw = (original.get("text") or original.get("caption") or "").strip()
        if not voice and (not raw or len(raw) > 4000):
            answer("Mention me with your items, or reply to a voice message with my @username." if english else
                   "Згадайте мене разом зі списком товарів або відповідайте на голосове моїм @username.")
            return
        answer("I’ll send a draft to your private chat with the bot. Confirm it there." if english else
               "Надішлю чернетку в особистий чат із ботом. Підтвердьте її там.")
        self.analytics.record("guest_voice" if voice else "guest_text", user)
        if voice:
            self.queue_voice(user_id, voice["file_id"])
        else:
            self.make_draft(user_id, raw)

    def handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        user = message.get("from", {})
        if chat.get("type") != "private" or not user.get("id"):
            return
        user_id = int(user["id"])
        text = (message.get("text") or "").strip()
        registered = self.bind_user(user_id)
        if text.split('@', 1)[0] == '/version':
            identity = release()
            self.send(user_id, f"Version: {identity['version']}\nGit: {identity['commit']}")
            return
        if text.split('@', 1)[0] in ('/help', '📖 Як користуватися', '📖 How to use') or text == '/start help':
            self.show_help(user_id, step=3 if registered else 0)
            return
        kind='bot_start' if text.startswith('/start') else 'voice_queued' if message.get('voice') else 'bot_photo' if message.get('photo') else 'bot_message'
        self.analytics.record(kind,user)
        if text in ('/support', '/bug', '🐞 Повідомити про проблему', '🐞 Report a problem'):
            self.clear_pending(user_id)
            token = self.support.begin(user_id)
            self.send(user_id, tr('Опишіть проблему одним текстовим повідомленням: що зробили, чого очікували та що сталося. Опис і ваш Telegram-профіль прочитає власник бота. Додамо час, мову та кількість учасників сім’ї. Не надсилайте паролі чи токени.'), reply_markup=buttons([(tr('Скасувати'), 'support:cancel:' + token)]))
            return
        draft = self.support.draft(user_id)
        if draft and text == '/cancel':
            self.support.cancel(user_id)
            self.send(user_id, tr('Звернення скасовано.'), reply_markup=self.menu())
            return
        menu_actions = {button['text'] for row in self.menu()['keyboard'] for button in row} | {'📋 Список у чаті', '📋 List in chat'}
        if draft and (text.startswith('/') or text in menu_actions):
            self.support.cancel(user_id)
            draft = None
        if draft:
            if not text:
                self.send(user_id, tr('Поки підтримуємо текстовий опис. Напишіть проблему текстом або скасуйте звернення.'))
                return
            try:
                draft = self.support.describe(user_id, text)
            except ValueError as exc:
                self.send(user_id, tr(str(exc)))
                return
            self.send(user_id, tr('Надіслати цей опис у підтримку?') + '\n\n' + text, reply_markup=buttons([(tr('Надіслати'), 'support:send:' + draft['token']), (tr('Скасувати'), 'support:cancel:' + draft['token'])]))
            return
        if text=='/admin':
            if user_id not in self.admin_ids:
                self.send(user_id,'Адмінка доступна лише власнику / Owner access only.')
                return
            url=os.getenv('SHOPPING_WEB_URL','')
            if url.startswith('https://'):
                self.send(user_id,'📊 Статистика бота / Bot analytics',reply_markup={'inline_keyboard':[[{'text':'Відкрити адмінку / Open admin','web_app':{'url':url.rstrip('/')+'/admin?lang='+language.get()}}]]})
            else:self.send(user_id,'Admin requires SHOPPING_WEB_URL (HTTPS).')
            return
        if registered and not self.families.preference(user_id):
            self.families.set_language(user_id, language.get())
        if text == '/language' or text in ('🌐 Мова', '🌐 Language') or (text.startswith('/start') and not self.families.preference(user_id)):
            self.families.pending_start(user_id,text if text.startswith('/start') else '')
            self.show_language(user_id)
            return
        name = user.get("first_name") or tr('ui_9e0a513bdc07')
        pasted=re.search(r'(?:\?|&)start=invite_([A-Za-z0-9_-]{20,64})',text)
        if pasted:
            self.show_invite_preview(user_id,pasted.group(1))
            return
        if text.startswith('/start invite_'):
            self.show_invite_preview(user_id,text.split('invite_',1)[1])
            return
        if text == '/create':
            if registered:
                self.show_list(user_id, bring_to_bottom=True)
            else:
                self.show_usage_choice(user_id)
            return
        if text.startswith("/whoami"):
            self.send(user_id, f"{tr('ui_4f0929df6f64')}{user_id}")
            return
        if text.startswith("/join"):
            supplied = text.partition(" ")[2].strip()
            if not supplied or not hmac.compare_digest(supplied, self.invite_code):
                self.send(user_id, tr('ui_1194471b223e'))
                return
            _,status=self.families.enroll(user_id, name, legacy=True)
            if status=='invalid':
                self.send(user_id,tr('ui_fa8c34c73d06'))
                return
            self.bind_user(user_id)
            self.send(user_id, tr('ui_06ea442c02cb'), reply_markup=self.menu())
            return
        if not registered:
            self.show_usage_choice(user_id)
            self.show_web_app(user_id)
            return
        if user_id in self.pending_family_names and text and not text.startswith('/'):
            try:
                renamed=self.families.rename(user_id,text)
            except ValueError as exc:
                self.send(user_id,str(exc))
                return
            self.pending_family_names.discard(user_id)
            self.send(user_id,tr('ui_a81997d616d2') if renamed else tr('ui_b4bc5b9b1531'))
            self.show_family(user_id)
            return
        if text in ("/family", tr('ui_33ed8513acbd')):
            self.clear_pending(user_id)
            self.pending_notes.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.show_family(user_id)
            return
        if text in ("/invite", tr('ui_0eb483441299')):
            self.pending_notes.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.show_invite(user_id)
            return
        if text.startswith("/start"):
            self.clear_pending(user_id)
            self.show_list(user_id, bring_to_bottom=True)
            return
        if text.startswith("/cancel"):
            self.pending_family_names.discard(user_id)
            edit = self.pending_draft_edits.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.pending_notes.pop(user_id, None)
            if edit:
                self.show_draft(user_id, edit[0], edit[2])
            else:
                self.send(user_id, tr('ui_d1454191b8bd'))
            return
        if text in (tr('ui_428fc2d45eba'), tr('ui_1720591356f5'), tr('ui_f46f0095cd44'), tr('ui_a9e16bfc706e'), tr('ui_78ea31018b80'), tr('ui_58d659bf993e'), tr('ui_8c4317311ad3'), tr('ui_45b58c75117f'), '📋 Список у чаті', '📋 List in chat', *STORES) or text.startswith(("/list", "/catalog", "/history", "/app")):
            self.pending_notes.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
            self.pending_draft_edits.pop(user_id, None)
        if user_id in self.pending_draft_edits:
            if text:
                self.finish_draft_edit(user_id, text)
            else:
                self.send(user_id, tr('ui_c84b82ea081c'))
            return
        if user_id in self.pending_notes and text:
            if len(text) > 200:
                self.send(user_id, tr('ui_bf3b7ea9dd1b'))
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
            self.queue_voice(user_id,message["voice"]["file_id"],self.pending_notes.get(user_id))
            return
        if not text:
            self.send(user_id, tr('ui_a83f7bb5f025'))
            return
        if user_id in self.pending_photos:
            file_id = self.pending_photos.pop(user_id)
            self.save_photo(user_id, text, file_id)
            return
        if text in (tr('ui_78ea31018b80'), tr('ui_58d659bf993e'), "/app"):
            self.show_web_app(user_id)
        elif text in STORES or text in (tr('ui_428fc2d45eba'), tr('ui_45b58c75117f'), '📋 Список у чаті', '📋 List in chat'):
            self.show_list(user_id, bring_to_bottom=True)
        elif text in (tr('ui_a9e16bfc706e'), tr('ui_8c4317311ad3')):
            self.send(user_id, tr('ui_3ed585b1d128'),
                      reply_markup=buttons([(tr('ui_816689e7ff0a'), "list:all")]))
        elif text == tr('ui_1720591356f5') or text.startswith("/catalog"):
            self.show_catalog(user_id)
        elif text == tr('ui_f46f0095cd44') or text.startswith("/history"):
            self.show_history(user_id)
        elif text.startswith("/list"):
            self.show_list(user_id, bring_to_bottom=True)
        elif text.startswith("/add "):
            self.make_draft(user_id, text[5:])
        elif text.startswith("/"):
            self.send(user_id, tr('ui_9711fa721bfc'))
        else:
            self.make_draft(user_id, text)

    def make_draft(self, user_id: int, raw: str) -> None:
        items = self.store.resolved_items(raw)
        if not items:
            self.send(user_id, tr('ui_ed4dbaec7704'))
            return
        draft_items = []
        for name, note in items:
            existing = self.store.product_by_name(name)
            draft_items.append({"key": uuid.uuid4().hex[:8], "name": name,
                                "note": (tr('ui_b0c5ef5f2ea3') + note if note in STORES else note) or (existing["note"] if existing else ""),
                                "category": existing["category"] if existing else infer_category(name)})
        self.pending_draft_edits.pop(user_id, None)
        draft_id = self.store.save_draft(user_id, draft_items)
        self.show_draft(user_id, draft_id)

    def show_draft(self, user_id: int, draft_id: int, panel_id=None, editing=False) -> None:
        items = self.store.draft(user_id, draft_id)
        if items is None:
            self.panel(user_id, tr('ui_ccdb1698f91f'), buttons([(tr('ui_13a3f958c2ad'), "list:all")]), panel_id)
            return
        lines = [f"{tr('ui_85fd92fd6b66')}{len(items)}{tr('ui_1df015513d95')}"]
        for index, item in enumerate(items, 1):
            existing=self.store.product_by_name(item['name'])
            active=existing and any(row['id']==existing['id'] for row in self.store.needs())
            lines.append(f"{index}. {item['name']} · {CATEGORIES[item['category']]}" + (tr('ui_17e79ca873f8') if active else '') + (f"\n   📝 {item['note']}" if item['note'] else ""))
        controls = []
        if editing:
            lines.append(tr('ui_4908e89b0c6b'))
            controls += [[(item["name"][:35], f"ditem:{draft_id}:{item['key']}")] for item in items]
        if items:
            controls.append([(tr('ui_b2db6721d657'), f"confirm:{draft_id}"), (tr('ui_646edfb78b75'), f"dedit:{draft_id}")])
        else:
            lines.append(tr('ui_364563cf6a1f'))
        controls.append([(tr('ui_816689e7ff0a'), f"cancel:{draft_id}")])
        self.panel(user_id, "\n".join(lines)[:3900], buttons(*controls), panel_id)

    def show_draft_item(self, user_id, draft_id, key, panel_id):
        items = self.store.draft(user_id, draft_id)
        item = next((item for item in items or [] if item["key"] == key), None)
        if item is None:
            self.show_draft(user_id, draft_id, panel_id, editing=True)
            return
        self.panel(user_id, f"✏️ {item['name']}\n{CATEGORIES[item['category']]}{tr('ui_2be7f9402c08')}{item['note'] or '—'}", buttons(
            [(tr('ui_8d2855b10253'), f"dname:{draft_id}:{key}"), (tr('ui_1bc4bea6f13d'), f"dnote:{draft_id}:{key}")],
            [(tr('ui_b6150e14a981'), f"dcats:{draft_id}:{key}"), (tr('ui_2bc919726f86'), f"ddel:{draft_id}:{key}")],
            [(tr('ui_554dca2bdb83'), f"dedit:{draft_id}")]), panel_id)

    def finish_draft_edit(self, user_id, text):
        draft_id, key, panel_id, field = self.pending_draft_edits[user_id]
        limit = 120 if field == "name" else 200
        if len(text) > limit:
            self.send(user_id, f"{tr('ui_5a347316dd36')}{limit}{tr('ui_a61e898f8b7e')}")
            return
        self.store.change_draft(user_id, draft_id, key, {field: "" if field == "note" and text == "-" else text.strip()})
        self.pending_draft_edits.pop(user_id, None)
        self.show_draft_item(user_id, draft_id, key, panel_id)

    def queue_voice(self,user_id,file_id,note_product_id=None):
        if not self.voice_limits.allow(user_id) or not self.voice_admission.acquire(user_id):
            self.send(user_id, 'Voice queue is busy. Try again in a minute.' if language.get() == 'en' else 'Голосова черга зайнята. Спробуй за хвилину.')
            return
        started=threading.Event()
        finished=threading.Event()
        guard=threading.Lock()
        expected_family=self.family_context.get()
        worker_context=copy_context()
        notice_context=copy_context()

        def ready():
            with guard:
                finished.set()
            timer.cancel()

        def notice():
            with guard:
                if finished.is_set() or self.families.family(user_id)!=expected_family:
                    return
                try:
                    key='ui_8ac40e2be49b' if started.is_set() else 'ui_cb8057ef0a78'
                    self.send(user_id,tr(key))
                except TelegramError:
                    LOG.warning('Could not send delayed voice status')

        timer=threading.Timer(5,lambda:notice_context.run(notice))
        timer.daemon=True

        def worker():
            started.set()
            try:
                self.process_voice(user_id,file_id,note_product_id,on_transcribed=ready)
            finally:
                ready()
                self.voice_admission.release(user_id)

        try:
            self.voice_pool.submit(worker_context.run,worker)
        except Exception:
            ready()
            self.voice_admission.release(user_id)
            raise
        try:
            timer.start()
        except RuntimeError:
            # Admission belongs to the submitted worker, even if notice startup fails.
            ready()
            LOG.warning('Could not start delayed voice status timer')

    def process_voice(self, user_id: int, file_id: str, note_product_id: int | None = None, *, on_transcribed=None) -> None:
        started=time.monotonic()
        successful=False
        selected_language=language.get()
        expected_family=self.family_context.get()
        if self.families.family(user_id)!=expected_family:
            self.send(user_id,tr('ui_d026c0b5a708'))
            return
        if not self.bind_user(user_id):
            return
        language.set(selected_language)
        try:
            vocabulary = [row["name"] for row in self.store.catalog(limit=12)] if note_product_id is None else []
            transcript = transcribe(self.telegram, file_id, self.whisper_cli, self.whisper_model, language_code=language.get(), vocabulary=vocabulary, shopping_context=note_product_id is None)
            if on_transcribed:
                on_transcribed()
            with self.families.lock:
                if self.families.family(user_id)!=expected_family:
                    self.send(user_id,tr('ui_207f65cb77d5'))
                    return
                if not transcript:
                    self.send(user_id, tr('ui_25719b4e1c5d'))
                    return
                successful=True
                if note_product_id is not None:
                    # A delayed transcription must not replace a cancelled or edited note.
                    if self.pending_notes.get(user_id) != note_product_id:
                        return
                    if len(transcript) > 200:
                        self.send(user_id, tr('ui_0ce74f1a0cc2'))
                        return
                    self.store.set_note(note_product_id, transcript)
                    self.pending_notes.pop(user_id, None)
                    self.send(user_id, f"{tr('ui_f5d190cbc687')}{transcript}")
                    self.show_item(user_id, note_product_id, self.note_panels.pop(user_id, None))
                    self.refresh_views()
                    return
                self.send(user_id, f"{tr('ui_94b5a7bd2400')}{transcript}")
                self.make_draft(user_id, transcript)
        except (SpeechError, TelegramError) as exc:
            if on_transcribed:
                on_transcribed()
            self.send(user_id, f"{exc}{tr('ui_61a76168c7db')}")
        except Exception:
            if on_transcribed:
                on_transcribed()
            LOG.exception("Voice processing failed for user %s", user_id)
            self.send(user_id, tr('ui_7d5933174b7f'))

        finally:
            self.analytics.record('voice_done' if successful else 'voice_error',{'id':user_id},status='ok' if successful else 'error',duration_ms=int((time.monotonic()-started)*1000))

    def handle_photo(self, user_id: int, message: dict) -> None:
        file_id = message["photo"][-1]["file_id"]
        caption = (message.get("caption") or "").strip()
        if caption:
            self.save_photo(user_id, caption, file_id)
        else:
            self.pending_photos[user_id] = file_id
            self.send(user_id, tr('ui_2b3e19929f86'))

    def save_photo(self, user_id: int, raw_name: str, file_id: str) -> None:
        if not self.photo_limits.allow(user_id):
            self.send(user_id, 'Too many photos. Try again later.' if language.get() == 'en' else 'Забагато фото. Спробуй пізніше.')
            return
        items = parse_items(raw_name, split_conjunctions=False)
        if len(items) != 1:
            self.send(user_id, tr('ui_a651e125c241'))
            return
        name, preferred = items[0]
        destination = self.media_dir / f"{uuid.uuid4().hex}.jpg"
        try:
            self.telegram.download(file_id, destination, limit=5_000_000)
        except TelegramError as exc:
            self.send(user_id, f"{tr('ui_051af2751ef5')}{exc}")
            return
        product_id = self.store.ensure_product(name, preferred)
        self.store.set_photo(product_id, file_id, str(destination))
        added = self.store.add_need(product_id, user_id)
        self.send(user_id,
            f"{tr('ui_54a2c8dccf6a')}{name}{tr('ui_3fa58feabda5')}" +
            (tr('ui_ce35ddc7dd31') if added else tr('ui_8326f110c62b')))
        self.refresh_views()

    def list_content(self, store_name: str = "") -> tuple[str, dict]:
        rows = self.store.needs()
        order = list(CATEGORIES)
        rows = sorted(rows, key=lambda row: (order.index(row["category"]) if row["category"] in order else len(order), row["name"].casefold()))
        lines = [tr('ui_2e7599dba763')]
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
            controls = [(row["name"][:28], f"item:{row['id']}"), (tr('ui_a573634f69eb'), f"buy:{row['id']}:all")]
            if row["photo_file_id"]:
                controls.append(("📷", f"photo:{row['id']}"))
            keyboard.append(controls)
        if not rows:
            lines.append(tr('ui_2ae6a665289d'))
            keyboard.append([(tr('ui_3d14fa5a5b38'), "add")])
        if len(rows) > shown:
            lines.append(f"{tr('ui_b21c9aac6065')}{shown}{tr('ui_e2b3417bc1de')}{len(rows)}{tr('ui_dd922ebd0935')}")
        keyboard.append([(tr('ui_e303bf93e660'), "list:all"), (tr('ui_1720591356f5'), "catalog:0")])
        markup = buttons(*keyboard)
        url = os.getenv('SHOPPING_WEB_URL', '')
        if url.startswith('https://'):
            markup['inline_keyboard'].insert(0, [{'text': '🛒 Shopping' if language.get() == 'en' else '🛒 Покупки', 'web_app': {'url': url}}])
        return "\n".join(lines), markup

    def show_list(self, user_id: int, store_name: str = "", message_id: int | None = None, *, bring_to_bottom=False) -> None:
        store_name = "all"
        content, markup = self.list_content()
        if message_id is None:
            existing = next((view for view in self.store.views() if view['user_id'] == user_id and view['store'] == store_name), None)
            if existing:
                message_id = existing['message_id']
        if message_id is not None and not bring_to_bottom:
            try:
                self.telegram.call("editMessageText", chat_id=user_id, message_id=message_id,
                                   text=content, reply_markup=markup)
                self.store.set_view(user_id, store_name, message_id)
                return
            except TelegramError as exc:
                if "message is not modified" in str(exc).lower():
                    self.store.set_view(user_id, store_name, message_id)
                    return
                if not any(reason in str(exc).lower() for reason in ('message to edit not found', "message can't be edited", 'message_id_invalid')):
                    LOG.warning('List panel edit failed; preserving existing message')
                    return
        result = self.send(user_id, content, reply_markup=markup)
        if message_id is not None:
            self.remove_obsolete_panel(user_id, message_id)
        self.store.set_view(user_id, store_name, result["message_id"])

    def refresh_views(self) -> None:
        """Keep each person's latest store lists aligned after shared changes."""
        original_language = language.get()
        for view in self.store.views():
            if self.families.family(view['user_id'])!=self.family_context.get():
                continue
            language.set(self.families.preference(view["user_id"]) or "uk")
            content, markup = self.list_content(view["store"])
            try:
                self.telegram.call("editMessageText", chat_id=view["user_id"],
                                   message_id=view["message_id"], text=content, reply_markup=markup)
            except TelegramError as exc:
                if "message is not modified" not in str(exc).lower():
                    LOG.warning("Could not refresh shopping list: %s", exc)

        language.set(original_language)

    def show_catalog(self, user_id: int, offset: int = 0, message_id: int | None = None) -> None:
        count = self.store.catalog_count()
        rows = self.store.catalog(offset)
        lines = [f"{tr('ui_c974d4138a36')}{count}{tr('ui_06228fbc4c5c')}{offset // 10 + 1}/{max(1, (count + 9) // 10)}", tr('ui_39f5a80bbeaa')]
        keyboard = [[(f"{r['name'][:36]}{' ✅' if r['active'] else ''}", f"item:{r['id']}")] for r in rows]
        pages = []
        if offset > 0:
            pages.append((tr('ui_0ea5d3b0ea95'), f"catalog:{max(0, offset - 10)}"))
        if offset + 10 < count:
            pages.append((tr('ui_3c05029a0f2a'), f"catalog:{offset + 10}"))
        if pages:
            keyboard.append(pages)
        if not rows:
            lines.append(tr('ui_fcb9bd9b2fa9'))
        keyboard.append([(tr('ui_4dfffe931b00'), "list:all")])
        self.panel(user_id, "\n".join(lines), buttons(*keyboard), message_id)

    def show_item(self, user_id: int, product_id: int, message_id: int | None = None) -> None:
        product = self.store.product(product_id)
        if not product:
            self.send(user_id, tr('ui_8823ca72a6bd'))
            return
        active = any(row["id"] == product_id for row in self.store.needs())
        text = f"{product['name']}\n{CATEGORIES.get(product['category'], CATEGORIES['other'])}"
        text += tr('ui_fe6c2bdb348e') if active else tr('ui_76967b28c5e3')
        if product["note"]:
            text += f"\n\n📝 {product['note']}"
        rows = [[(tr('ui_a573634f69eb'), f"buy:{product_id}:all")] if active else [(tr('ui_21a6c881ff8c'), f"readd:{product_id}")]]
        rows.append([(tr('ui_675da4a00bf6') if product["note"] else tr('ui_d125eb4a052d'), f"note:{product_id}")])
        if product["note"]:
            rows[-1].append((tr('ui_2bc919726f86'), f"clearnote:{product_id}"))
        if product["photo_file_id"]:
            rows.append([(tr('ui_fa12e275c8fb'), f"photo:{product_id}")])
        else:
            text += tr('ui_2e00db9e6c39')
        rows.append([(tr('ui_61a63f8e97e3'), f"categories:{product_id}")])
        rows.append([(tr('ui_4dfffe931b00'), "list:all"), (tr('ui_1720591356f5'), "catalog:0")])
        self.panel(user_id, text, buttons(*rows), message_id)

    def show_history(self, user_id: int) -> None:
        events = self.store.recent_history()
        if not events:
            self.send(user_id, tr('ui_f6e3f4b9e568'))
            return
        lines = [tr('ui_dd633808533d')]
        verbs = {"added": tr('ui_529befd33c06'), "bought": tr('ui_d49c62c688ba'), "restored": tr('ui_719296f626b8')}
        for event in events:
            local = datetime.fromisoformat(event["happened_at"]).astimezone(ZoneInfo("Europe/Lisbon"))
            suffix = f"{tr('ui_906385c193d8')}{event['store']}" if event["store"] else ""
            if event["undone"]:
                suffix += tr('ui_aafc9ef7302d')
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
        original_language=language.get()
        for partner in partners:
            language.set(self.families.preference(partner['user_id']) or 'uk')
            if items:
                shown = [name[:70] + ("…" if len(name) > 70 else "") for name in items[:40]]
                text = f"{actor}{tr('ui_1c99972f606a')}" + "\n".join(f"✅ {name}" for name in shown)
                if len(items) > 40:
                    text += f"{tr('ui_820f672ef935')}{len(items) - 40}{tr('ui_f07b2d5ca38f')}"
            else:
                text = f"{actor}{tr('ui_6c75f0a9b94a')}"
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

        language.set(original_language)

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
                self.send(user_id,tr('ui_c3255f2e1b92'),reply_markup=self.menu())
                self.show_family(user_id)
                self.show_web_app(user_id)
            else:
                errors={'owner_required':tr('ui_006b7c354b8a'),'transfer_forbidden':tr('ui_25e3420c9774'),'stale':tr('ui_ec20e7b8a7be')}
                self.send(user_id,errors.get(status,tr('ui_5d077df0d079')))
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
            self.send(user_id,tr('ui_1d0f050417a2') if revoked else tr('ui_386162c4df78'))
            self.show_family(user_id)
        elif data=='family:rename':
            self.clear_pending(user_id)
            self.pending_family_names.add(user_id)
            self.send(user_id,tr('ui_7d13c11f08e7'))
        elif data=='family:owners':
            if current['owner_id']!=user_id:
                self.send(user_id,tr('ui_04ac9baa9fd2'))
                return
            rows=[[(row['name'],'family:owner:'+str(row['user_id']))] for row in self.families.members(current['id']) if row['user_id']!=user_id]
            rows.append([(tr('ui_816689e7ff0a'),'family:show')])
            self.panel(user_id,tr('ui_7d5c1d952487'),buttons(*rows),message_id)
        elif data.startswith('family:owner:'):
            target=int(data.split(':',2)[2])
            if current['owner_id']==user_id and self.families.family(target)==current['id']:
                self.panel(user_id,tr('ui_5df60533ebdd')+self.store.member_name(target)+tr('ui_56611209bb82'),buttons([(tr('ui_df56e2b9b10b'),'family:owner-confirm:'+str(target))],[(tr('ui_816689e7ff0a'),'family:show')]),message_id)
        elif data.startswith('family:owner-confirm:'):
            success=self.families.transfer_owner(user_id,int(data.split(':',2)[2]))
            self.send(user_id,tr('ui_06c3ca87d83f') if success else tr('ui_83e7aa0588c2'))
            self.show_family(user_id)
        elif data in ('family:delete','family:leave'):
            deleting=data=='family:delete'
            if deleting and current['owner_id']!=user_id:
                self.send(user_id,tr('ui_b8944434f42a'))
                return
            people=self.families.members(current['id'])
            if not deleting and current['owner_id']==user_id and len(people)>1:
                self.send(user_id,tr('ui_f93c126bf4aa'))
                self.show_family(user_id)
                return
            description=(f"{tr('ui_caf54d9f01fc')}{current['name']}{tr('ui_8b81b838d587')}{len(people)}{tr('ui_cb39b2d52302')}{self.store.catalog_count()}{tr('ui_54f6af08aa14')}" if deleting else tr('ui_14d8fa71987c')+(tr('ui_e275e07e3d75') if len(people)==1 else tr('ui_fc25565fecaa')))
            action='family:delete-confirm:' if deleting else 'family:leave-confirm:'
            self.panel(user_id,description,buttons([(tr('ui_649ac2cc1c8c'),action+current['id'])],[(tr('ui_816689e7ff0a'),'family:show')]),message_id)
        elif data.startswith(('family:delete-confirm:','family:leave-confirm:')):
            if data.split(':',2)[2]!=current['id']:
                self.send(user_id,tr('ui_4942d160189f'))
                return
            status=self.families.delete(user_id) if data.startswith('family:delete-confirm:') else self.families.leave(user_id)
            if status is True or status=='left':
                self.clear_pending(user_id)
                self.bind_user(user_id)
                self.send(user_id,tr('ui_06917a88edee'),reply_markup=buttons([(tr('ui_fa354ddf77af'),'family:create'),(tr('ui_cc3a50c1e3fb'),'family:joinhelp')]))
            else:
                self.send(user_id,tr('ui_cf0f99edcfc0'))

    def handle_callback(self, query: dict) -> None:
        user = query.get("from", {})
        user_id = user.get("id")
        message = query.get("message") or {}
        if not user_id or message.get("chat", {}).get("type") != "private":
            return
        self.analytics.record("bot_callback",user)
        callback_id = query.get("id")
        if query.get('data', '').startswith('help:'):
            self.bind_user(user_id)
            parts = query['data'].split(':')
            if len(parts) == 4 and parts[3].isdigit():
                self.show_help(user_id, parts[1], parts[2], int(parts[3]), message)
            self.telegram.call('answerCallbackQuery', callback_query_id=callback_id)
            return
        if query.get('data', '').startswith('support:'):
            self.bind_user(user_id)
            parts = query['data'].split(':')
            if len(parts) != 3:
                return
            action, token = parts[1:]
            try:
                if action == 'cancel':
                    if not self.support.cancel(user_id, token):
                        raise ValueError('Звернення застаріло. Відкрийте /support ще раз.')
                    self.send(user_id, tr('Звернення скасовано.'), reply_markup=self.menu())
                elif action == 'send':
                    family = self.families.family(user_id)
                    count = len(self.families.members(family)) if family else 0
                    ticket = self.support.submit(user, token, {'language': language.get(), 'family_id': family, 'family_member_count': count})
                    self.send(user_id, tr('Звернення збережено. Номер: #') + str(ticket) + tr('. Власник бота зможе переглянути його в підтримці.'), reply_markup=self.menu())
            except ValueError as exc:
                self.send(user_id, tr(str(exc)))
            finally:
                self.telegram.call('answerCallbackQuery', callback_query_id=callback_id)
            return
        if query.get('data','').startswith('language:'):
            chosen=query['data'].split(':',1)[1]
            if chosen not in ('uk','en'):
                return
            self.families.set_language(user_id,chosen)
            self.bind_user(user_id)
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            start=self.families.pending_start(user_id)
            self.clear_pending(user_id)
            self.send(user_id,'Language: English' if chosen=='en' else 'Мова: українська',reply_markup=self.menu())
            self.handle_message({'from':user,'chat':message['chat'],'text':start or '/start'})
            return

        registered = self.bind_user(user_id)
        if query.get('data')=='family:joinhelp':
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            self.send(user_id,tr('ui_9efeebf17901'))
            return
        if query.get('data') in ('family:create', 'family:solo', 'family:shared'):
            self.telegram.call('answerCallbackQuery', callback_query_id=callback_id)
            if query['data'] == 'family:create':
                self.show_usage_choice(user_id)
            else:
                self.start_list(user_id, user.get('first_name') or tr('ui_9e0a513bdc07'), query['data'].split(':')[1])
            return
        if query.get('data','').startswith(('family:accept:','family:join:')):
            route=self.families.message_family(user_id,message.get('message_id'))
            if route and route!=(self.families.family(user_id) or 'none'):
                self.telegram.call('answerCallbackQuery',callback_query_id=callback_id,text=tr('ui_ec20e7b8a7be'),show_alert=True)
                return
            self.handle_family_action(user_id,user.get('first_name') or tr('ui_9e0a513bdc07'),query['data'],message.get('message_id'))
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            return
        if not registered:
            self.telegram.call("answerCallbackQuery", callback_query_id=callback_id,
                               text=tr('ui_5f728e9a36d5'), show_alert=True)
            return
        data=query.get('data','')
        message_family=self.families.message_family(user_id,message.get('message_id'))
        if data not in ('family:show','family:invite') and ((message_family and message_family!=self.families.family(user_id)) or (not message_family and len(self.families.choices(user_id))>1)):
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id,text=tr('ui_a226357373e4'),show_alert=True)
            return
        if data.startswith('family:'):
            self.handle_family_action(user_id,user.get('first_name') or self.store.member_name(user_id),data,message.get('message_id'))
            self.telegram.call('answerCallbackQuery',callback_query_id=callback_id)
            return
        data = query.get("data", "")
        answer = tr('ui_ef05d57959cf')
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
                self.panel(user_id, tr('ui_aea2f162e25b'),
                           buttons([(tr('ui_4dfffe931b00'), "list:all")]), panel_id)
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
                    answer = tr('ui_30f4e78b3230')
                elif action in {"dname", "dnote"}:
                    self.pending_notes.pop(user_id, None)
                    field = "name" if action == "dname" else "note"
                    self.pending_draft_edits[user_id] = (draft_id, key, panel_id, field)
                    markup = buttons([(tr('ui_816689e7ff0a'), f"ditem:{draft_id}:{key}")])
                    hint = ""
                    if field == "name":
                        markup["inline_keyboard"].insert(0, [{"text": tr("📋 Скопіювати назву"), "copy_text": {"text": item["name"]}}])
                        hint = "\n" + tr("Скопіюйте назву кнопкою нижче, вставте в поле повідомлення та відредагуйте.")
                    self.panel(user_id, f"✏️ {item['name']}{tr('ui_87a032f4ad8a')}{(tr('ui_54b55e2783f0') if field == 'name' else tr('ui_304a5e5d8b69'))}{hint}{tr('ui_292193705cc1')}", markup, panel_id)

                elif action == "dcats":
                    choices = [[(label, f"dcat:{draft_id}:{key}:{category}")] for category, label in CATEGORIES.items()]
                    choices.append([(tr('ui_0ea5d3b0ea95'), f"ditem:{draft_id}:{key}")])
                    self.panel(user_id, tr('ui_a8d4e8dbbdc1'), buttons(*choices), panel_id)
                elif action == "ddel":
                    self.store.change_draft(user_id, draft_id, key, remove=True)
                    self.show_draft(user_id, draft_id, panel_id, editing=True)
                elif action == "dcat" and len(parts) == 4:
                    self.store.change_draft(user_id, draft_id, key, {"category": parts[3]})
                    self.show_draft_item(user_id, draft_id, key, panel_id)
            elif action == "confirm" and len(parts) == 2:
                items = self.store.take_draft(user_id, int(parts[1]))
                if items is None:
                    answer = tr('ui_7db7dd991015')
                else:
                    added = 0
                    for item in items:
                        product_id = self.store.ensure_product(item["name"])
                        self.store.set_note(product_id, item["note"])
                        self.store.set_category(product_id, item["category"])
                        added += self.store.add_need(product_id, user_id)
                    self.analytics.record("products_added",{"id":user_id},value=added)
                    self.panel(user_id, f"{tr('ui_34d3477683e3')}{added}{tr('ui_08e3e9dd9f8c')}{len(items) - added}.",
                               buttons([(tr('ui_80f83082d444'), "list:all")]), panel_id)
                    if items:
                        self.refresh_views()
            elif action == "cancel" and len(parts) == 2:
                self.store.cancel_draft(user_id, int(parts[1]))
                answer = tr('ui_db28b6f53d1f')
                self.panel(user_id, tr('ui_d01a578fa19a'), buttons([(tr('ui_4dfffe931b00'), "list:all")]), panel_id)
            elif action == "buy" and len(parts) == 3:
                product_id, store_name = int(parts[1]), ""
                product = self.store.product(product_id)
                bought, batch_id, event_id = self.store.purchase(product_id, user_id, store_name)
                if bought:
                    self.analytics.record("purchase",{"id":user_id})
                    answer = f"{tr('ui_b729d2e8c2e3')}{product['name']}"[:180]
                    self.purchase_feedback[user_id] = self.panel(user_id,
                        f"{tr('ui_40a72cd566c7')}{product['name']}",
                        buttons([(tr('ui_d3b948f6dd1d'), f"undo:{event_id}:{batch_id}")]),
                        self.purchase_feedback.get(user_id))
                    self.show_list(user_id, message_id=panel_id)
                    try:
                        self.notify_partner(batch_id)
                    except TelegramError as exc:
                        LOG.warning("Purchase saved; notification failed: %s", exc)
                    self.refresh_views()
                else:
                    answer = tr('ui_7b21cb83167e')
                    self.show_list(user_id, store_name, message.get("message_id"))
            elif action == "undo" and len(parts) == 3:
                product_id = self.store.undo_purchase(int(parts[1]), user_id)
                if product_id is None:
                    answer = tr('ui_0b40caf51cf2')
                else:
                    try:
                        self.notify_partner(int(parts[2]))
                    except TelegramError as exc:
                        LOG.warning("Undo saved; notification failed: %s", exc)
                    self.panel(user_id, f"{tr('ui_92c34004480d')}{self.store.product(product_id)['name']}",
                               buttons([(tr('ui_4dfffe931b00'), "list:all")]), panel_id)
                    self.refresh_views()
            elif action == "photo" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product and product["photo_file_id"]:
                    self.telegram.call("sendPhoto", chat_id=user_id, photo=product["photo_file_id"],
                                       caption=product["name"])
                else:
                    answer = tr('ui_16aff7a8a36c')
            elif action == "catalog" and len(parts) == 2:
                self.show_catalog(user_id, max(0, int(parts[1])), panel_id)
            elif action == "item" and len(parts) == 2:
                self.show_item(user_id, int(parts[1]), panel_id)
            elif action == "readd" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product:
                    added = self.store.add_need(product["id"], user_id)
                    answer = tr('ui_1a2c42fd8298') if added else tr('ui_10ddc680bffb')
                    self.show_item(user_id, product["id"], panel_id)
                    if added:
                        self.refresh_views()
                else:
                    answer = tr('ui_5383e75496a0')
            elif action == "categories" and len(parts) == 2:
                product_id = int(parts[1])
                if self.store.product(product_id):
                    choices = [[(label, f"setcategory:{product_id}:{key}")] for key, label in CATEGORIES.items()]
                    choices.append([(tr('ui_96c3acb549fc'), f"item:{product_id}")])
                    self.panel(user_id, f"{tr('ui_1e4504a64734')}{self.store.product(product_id)['name']}", buttons(*choices), panel_id)
            elif action == "setcategory" and len(parts) == 3:
                self.store.set_category(int(parts[1]), parts[2])
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            elif action == "note" and len(parts) == 2:
                product_id = int(parts[1])
                if self.store.product(product_id):
                    self.pending_notes[user_id] = product_id
                    self.note_panels[user_id] = self.panel(user_id, f"{tr('ui_f692d923d3a6')}{self.store.product(product_id)['name']}{tr('ui_6df0af796887')}",
                               buttons([(tr('ui_816689e7ff0a'), f"item:{product_id}")]), panel_id)
            elif action == "clearnote" and len(parts) == 2:
                self.store.set_note(int(parts[1]), "")
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            elif action == "setstore" and len(parts) == 3:
                self.store.set_note(int(parts[1]), tr('ui_b0c5ef5f2ea3') + STORE_CODES[parts[2]])
                self.show_item(user_id, int(parts[1]), panel_id)
                self.refresh_views()
            else:
                answer = tr('ui_fe2e2d2b67af')
        except TelegramError as exc:
            LOG.warning("Callback Telegram error for user %s: %s", user_id, exc)
            answer = tr('ui_94f482bc49a6')
        except (ValueError, KeyError, IndexError):
            self.analytics.record("bot_error",user,status="error")
            LOG.exception("Callback failed for user %s", user_id)
            answer = tr('ui_94f482bc49a6')
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
                    allowed_updates=["message", "callback_query", "guest_message"],
                )
                self.last_poll_at = time.monotonic()
                for update in updates:
                    try:
                        self.handle_update(update)
                    except Exception:
                        self.analytics.record("bot_error",(update.get("message") or update.get("callback_query") or {}).get("from"),status="error")
                        LOG.exception("Failed update %s", update.get("update_id"))
                    offset = update["update_id"] + 1
                    self.legacy_store.set_offset(offset)
            except TelegramError as exc:
                self.analytics.record("poll_error",status="error")
                LOG.warning("Telegram polling error: %s", exc)
                time.sleep(5)


def main() -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    LOG.info('Starting shopping bot')
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
            bot.telegram.call("setChatMenuButton", menu_button={"type": "web_app", "text": tr('ui_5dfb415e92a1'), "web_app": {"url": web_url}})
        except TelegramError:
            LOG.warning("Could not configure Mini App menu button")
    bot.run()


if __name__ == "__main__":
    main()
