from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .categories import CATEGORIES, infer_category
from .speech import SpeechError, transcribe
from .store import STORES, Store, parse_items
from .telegram import Telegram, TelegramError

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
        self.store = store
        self.invite_code = invite_code
        self.media_dir = media_dir
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.whisper_cli = whisper_cli
        self.whisper_model = whisper_model
        self.pending_photos: dict[int, str] = {}
        self.pending_notes: dict[int, int] = {}
        self.note_panels: dict[int, int] = {}
        self.purchase_feedback: dict[int, int] = {}
        self.voice_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-voice")

    def send(self, chat_id: int, text: str, **kwargs):
        return self.telegram.call("sendMessage", chat_id=chat_id, text=text, **kwargs)

    def panel(self, user_id: int, text: str, markup: dict, message_id: int | None = None) -> int:
        if message_id is not None:
            self.store.forget_view(user_id, message_id)
            try:
                self.telegram.call("editMessageText", chat_id=user_id, message_id=message_id,
                                   text=text, reply_markup=markup)
                return message_id
            except TelegramError as exc:
                if "message is not modified" in str(exc).lower():
                    return message_id
        return self.send(user_id, text, reply_markup=markup)["message_id"]

    def menu(self) -> dict:
        return {
            "keyboard": [
                [{"text": "🛒 Список"}],
                [{"text": "➕ Додати"}, {"text": "📚 Каталог"}, {"text": "🕘 Історія"}],
            ],
            "input_field_placeholder": "Товари через кому або голосом",
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def handle_update(self, update: dict) -> None:
        if "message" in update:
            self.handle_message(update["message"])
        elif "callback_query" in update:
            self.handle_callback(update["callback_query"])

    def handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        user = message.get("from", {})
        if chat.get("type") != "private" or not user.get("id"):
            return
        user_id = int(user["id"])
        text = (message.get("text") or "").strip()

        if text.startswith("/whoami"):
            self.send(user_id, f"Ваш Telegram ID: {user_id}")
            return
        if text.startswith("/join"):
            supplied = text.partition(" ")[2].strip()
            if not supplied or not hmac.compare_digest(supplied, self.invite_code):
                self.send(user_id, "Неправильний код. Надішліть /join КОД.")
                return
            status = self.store.join(user_id, user.get("first_name") or "Учасник")
            if status == "full":
                self.send(user_id, "У цій сім'ї вже є двоє учасників.")
            else:
                self.send(user_id, "Готово! Ваш список покупок спільний для вас двох.", reply_markup=self.menu())
            return
        if not self.store.is_member(user_id):
            self.send(user_id, "Це приватний сімейний бот. Для доступу надішліть /join КОД.")
            return
        if text.startswith("/start") or text.startswith("/help"):
            self.send(user_id,
                "Надішліть товари через кому або голосом. Фото надсилайте з назвою товару. "
                "Нотатку можна додати так: картопля :: купити в Mercadona. "
                "Або відкрийте картку товару та натисніть «Нотатка».",
                reply_markup=self.menu())
            return
        if text.startswith("/cancel"):
            self.pending_photos.pop(user_id, None)
            self.pending_notes.pop(user_id, None)
            self.send(user_id, "Дію скасовано.")
            return
        if text in ("🛒 Список", "📚 Каталог", "🕘 Історія", "➕ Додати", *STORES) or text.startswith(("/list", "/catalog", "/history")):
            self.pending_notes.pop(user_id, None)
            self.pending_photos.pop(user_id, None)
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
            self.send(user_id, "Розпізнаю голосове повідомлення локально…")
            self.voice_pool.submit(self.process_voice, user_id, message["voice"]["file_id"],
                                   self.pending_notes.get(user_id))
            return
        if not text:
            self.send(user_id, "Надішліть список текстом, голосове або фото товару з підписом.")
            return
        if user_id in self.pending_photos:
            file_id = self.pending_photos.pop(user_id)
            self.save_photo(user_id, text, file_id)
            return
        if text in STORES or text == "🛒 Список":
            self.show_list(user_id)
        elif text == "➕ Додати":
            self.send(user_id, "Надішліть товари через кому, наприклад: молоко, яйця, картопля :: купити в Mercadona. Можна також голосом.")
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
        draft_id = self.store.save_draft(user_id, items)
        lines = ["Додати до спільного списку?"]
        for name, selected_store in items:
            existing = self.store.product_by_name(name)
            note = selected_store if selected_store is not None else (existing["note"] if existing else "")
            if selected_store in STORES:
                note = "Купити в " + selected_store
            category = existing["category"] if existing else infer_category(name)
            lines.append(f"• {name} · {CATEGORIES[category]}" + (f" — {note}" if note else ""))
        self.send(user_id, "\n".join(lines), reply_markup=buttons(
            [("✅ Додати все", f"confirm:{draft_id}"), ("Скасувати", f"cancel:{draft_id}")]
        ))

    def process_voice(self, user_id: int, file_id: str, note_product_id: int | None = None) -> None:
        try:
            transcript = transcribe(self.telegram, file_id, self.whisper_cli, self.whisper_model)
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
        batch = self.store.batch(batch_id)
        if not batch:
            return
        partner = self.store.other_member(batch["actor_id"])
        if not partner:
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
        if batch["notification_id"]:
            try:
                self.telegram.call("editMessageText", chat_id=partner["user_id"],
                                   message_id=batch["notification_id"], text=text)
                return
            except TelegramError as exc:
                if "message is not modified" in str(exc).lower():
                    return
                LOG.warning("Could not edit purchase notification: %s", exc)
        result = self.send(partner["user_id"], text)
        self.store.set_batch_notification(batch_id, result["message_id"])

    def handle_callback(self, query: dict) -> None:
        user = query.get("from", {})
        user_id = user.get("id")
        message = query.get("message") or {}
        if not user_id or message.get("chat", {}).get("type") != "private":
            return
        callback_id = query.get("id")
        if not self.store.is_member(user_id):
            self.telegram.call("answerCallbackQuery", callback_query_id=callback_id,
                               text="Спочатку надішліть /join КОД.", show_alert=True)
            return
        data = query.get("data", "")
        answer = "Готово"
        try:
            parts = data.split(":")
            action = parts[0]
            if action in {"list", "catalog", "item", "categories", "buy", "readd", "add"}:
                self.pending_notes.pop(user_id, None)
            panel_id = message.get("message_id")
            if panel_id == self.purchase_feedback.get(user_id) and action != "undo":
                self.purchase_feedback.pop(user_id, None)
            if action == "add":
                self.panel(user_id, "➕ Надішліть товари через кому або голосове українською.\nНаприклад: молоко, яйця, хліб.\nБот покаже список для підтвердження.",
                           buttons([("🛒 До списку", "list:all")]), panel_id)
            elif action == "list" and len(parts) == 2:
                self.show_list(user_id, message_id=message.get("message_id"))
            elif action == "confirm" and len(parts) == 2:
                items = self.store.take_draft(user_id, int(parts[1]))
                if items is None:
                    answer = "Цей список уже оброблено"
                else:
                    added = 0
                    for name, preferred in items:
                        product_id = self.store.ensure_product(name, preferred)
                        added += self.store.add_need(product_id, user_id)
                    self.panel(user_id, f"✅ Додано: {added}. Уже у списку: {len(items) - added}.",
                               buttons([("🛒 Відкрити список", "list:all")]), panel_id)
                    if added:
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
        offset = self.store.get_offset()
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
                    self.store.set_offset(offset)
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
        Path(os.getenv("WHISPER_MODEL", "./whisper.cpp/models/ggml-base.bin")),
    )
    bot.run()


if __name__ == "__main__":
    main()
