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
from .store import DEFAULT_STORE, STORES, Store, parse_items
from .telegram import Telegram, TelegramError

LOG = logging.getLogger("shopping_bot")
STORE_CODES = {"M": "Mercadona", "L": "Lidl", "A": "Auchan"}
CODE_FOR_STORE = {name: code for code, name in STORE_CODES.items()}


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
        self.voice_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-voice")

    def send(self, chat_id: int, text: str, **kwargs):
        return self.telegram.call("sendMessage", chat_id=chat_id, text=text, **kwargs)

    def menu(self) -> dict:
        return {
            "keyboard": [
                [{"text": "Mercadona"}, {"text": "Lidl"}, {"text": "Auchan"}],
                [{"text": "➕ Додати"}, {"text": "📚 Каталог"}, {"text": "🕘 Історія"}],
            ],
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
                "Оберіть магазин кнопкою. Надішліть назви товарів через кому або голосовий список. "
                "Фото товару надсилайте з його назвою в підписі. Новий товар за замовчуванням належить Mercadona. "
                "Для іншого магазину напишіть, наприклад: хліб @Lidl.",
                reply_markup=self.menu())
            return
        if text.startswith("/cancel"):
            self.pending_photos.pop(user_id, None)
            self.send(user_id, "Дію скасовано.")
            return
        if message.get("photo"):
            self.handle_photo(user_id, message)
            return
        if message.get("voice"):
            self.send(user_id, "Розпізнаю голосове повідомлення локально…")
            self.voice_pool.submit(self.process_voice, user_id, message["voice"]["file_id"])
            return
        if not text:
            self.send(user_id, "Надішліть список текстом, голосове або фото товару з підписом.")
            return
        if user_id in self.pending_photos:
            file_id = self.pending_photos.pop(user_id)
            self.save_photo(user_id, text, file_id)
            return
        if text in STORES:
            self.show_list(user_id, text)
        elif text == "➕ Додати":
            self.send(user_id, "Надішліть товари через кому, наприклад: молоко, яйця, хліб @Lidl. Можна також голосом.")
        elif text == "📚 Каталог" or text.startswith("/catalog"):
            self.show_catalog(user_id)
        elif text == "🕘 Історія" or text.startswith("/history"):
            self.show_history(user_id)
        elif text.startswith("/list"):
            requested = text.partition(" ")[2].strip()
            self.show_list(user_id, requested if requested in STORES else DEFAULT_STORE)
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
            preferred = selected_store or (existing["preferred_store"] if existing else DEFAULT_STORE)
            category = existing["category"] if existing else infer_category(name)
            lines.append(f"• {name} — {preferred} · {CATEGORIES.get(category, CATEGORIES["other"])}")
        self.send(user_id, "\n".join(lines), reply_markup=buttons(
            [("✅ Додати все", f"confirm:{draft_id}"), ("Скасувати", f"cancel:{draft_id}")]
        ))

    def process_voice(self, user_id: int, file_id: str) -> None:
        try:
            transcript = transcribe(self.telegram, file_id, self.whisper_cli, self.whisper_model)
            if not transcript:
                self.send(user_id, "Не вдалося почути назви товарів. Спробуйте коротший список.")
                return
            self.send(user_id, f"Почув: {transcript}")
            self.make_draft(user_id, transcript)
        except (SpeechError, TelegramError) as exc:
            self.send(user_id, f"{exc}. Список можна надіслати текстом.")
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
            self.send(user_id, "Для фото потрібна одна назва товару, наприклад: молоко @Mercadona.")
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

    def list_content(self, store_name: str) -> tuple[str, dict]:
        rows = self.store.needs_for_store(store_name)
        own = [r for r in rows if r["preferred_store"] == store_name]
        elsewhere = [r for r in rows if r["preferred_store"] != store_name]
        lines = [f"🛒 {store_name} — спільний список"]
        keyboard = []
        for title, group in (("Улюблений магазин тут", own), ("Також можна купити тут", elsewhere)):
            if not group:
                continue
            lines.append(f"\n{title}:")
            order = list(CATEGORIES)
            group = sorted(group, key=lambda row: (order.index(row["category"]) if row["category"] in order else len(order), row["name"].casefold()))
            previous_category = None
            for row in group:
                if len(keyboard) >= 40:
                    break
                if row["category"] != previous_category:
                    lines.append(CATEGORIES.get(row["category"], CATEGORIES["other"]))
                    previous_category = row["category"]
                suffix = " 📷" if row["photo_file_id"] else ""
                shown_name = row["name"][:70] + ("…" if len(row["name"]) > 70 else "")
                lines.append(f"• {shown_name}{suffix}")
                controls = [(f"✅ {row['name'][:28]}", f"buy:{row['id']}:{CODE_FOR_STORE[store_name]}")]
                if row["photo_file_id"]:
                    controls.append(("📷", f"photo:{row['id']}"))
                keyboard.append(controls)
        if not rows:
            lines.append("Список порожній. Надішліть назви товарів або голосове повідомлення.")
        if len(rows) > 40:
            lines.append("\nПоказано перші 40 товарів. Куплені зникатимуть, решта з'являться далі.")
        keyboard.append([("🔄 Оновити", f"list:{CODE_FOR_STORE[store_name]}")])
        return "\n".join(lines), buttons(*keyboard)

    def show_list(self, user_id: int, store_name: str, message_id: int | None = None) -> None:
        content, markup = self.list_content(store_name)
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

    def show_catalog(self, user_id: int, offset: int = 0) -> None:
        count = self.store.catalog_count()
        rows = self.store.catalog(offset)
        lines = [f"📚 Каталог товарів ({count})", "Оберіть товар, щоб побачити фото й налаштування."]
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
        self.send(user_id, "\n".join(lines), reply_markup=buttons(*keyboard))

    def show_item(self, user_id: int, product_id: int) -> None:
        product = self.store.product(product_id)
        if not product:
            self.send(user_id, "Товар не знайдено.")
            return
        text = f"{product['name']}\nУлюблений магазин: {product['preferred_store']}\nКатегорія: {CATEGORIES.get(product['category'], CATEGORIES['other'])}"
        self.send(user_id, text, reply_markup=buttons(
            [("➕ До списку", f"readd:{product_id}")],
            [(f"⭐ {store}", f"setstore:{product_id}:{CODE_FOR_STORE[store]}") for store in STORES],
            [("📷 Показати фото", f"photo:{product_id}")],
            [("🗂 Змінити категорію", f"categories:{product_id}")],
        ))

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
            text = f"{actor} купив(ла) у {batch['store']}:\n" + "\n".join(f"✅ {name}" for name in shown)
            if len(items) > 40:
                text += f"\n…і ще {len(items) - 40} товарів. Усі є в історії."
        else:
            text = f"{actor} скасував(ла) покупки у {batch['store']}."
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
            if action == "list" and len(parts) == 2:
                self.show_list(user_id, STORE_CODES[parts[1]], message.get("message_id"))
            elif action == "confirm" and len(parts) == 2:
                items = self.store.take_draft(user_id, int(parts[1]))
                if items is None:
                    answer = "Цей список уже оброблено"
                else:
                    added = 0
                    for name, preferred in items:
                        product_id = self.store.ensure_product(name, preferred)
                        added += self.store.add_need(product_id, user_id)
                    self.send(user_id, f"Додано {added} товарів. Уже були в списку: {len(items) - added}.")
                    if added:
                        self.refresh_views()
            elif action == "cancel" and len(parts) == 2:
                self.store.cancel_draft(user_id, int(parts[1]))
                answer = "Скасовано"
            elif action == "buy" and len(parts) == 3:
                product_id, store_name = int(parts[1]), STORE_CODES[parts[2]]
                product = self.store.product(product_id)
                bought, batch_id, event_id = self.store.purchase(product_id, user_id, store_name)
                if bought:
                    self.send(user_id, f"Куплено: {product['name']}", reply_markup=buttons(
                        [("↩️ Скасувати покупку", f"undo:{event_id}:{batch_id}")]
                    ))
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
                    self.send(user_id, f"Повернуто до списку: {self.store.product(product_id)['name']}")
                    self.refresh_views()
            elif action == "photo" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product and product["photo_file_id"]:
                    self.telegram.call("sendPhoto", chat_id=user_id, photo=product["photo_file_id"],
                                       caption=product["name"])
                else:
                    answer = "Фото ще немає"
            elif action == "catalog" and len(parts) == 2:
                self.show_catalog(user_id, max(0, int(parts[1])))
            elif action == "item" and len(parts) == 2:
                self.show_item(user_id, int(parts[1]))
            elif action == "readd" and len(parts) == 2:
                product = self.store.product(int(parts[1]))
                if product:
                    added = self.store.add_need(product["id"], user_id)
                    answer = "Додано" if added else "Уже у списку"
                    if added:
                        self.refresh_views()
                else:
                    answer = "Товар не знайдено"
            elif action == "categories" and len(parts) == 2:
                product_id = int(parts[1])
                if self.store.product(product_id):
                    self.send(user_id, "Оберіть категорію:", reply_markup=buttons(*[
                        [(label, f"setcategory:{product_id}:{key}")] for key, label in CATEGORIES.items()
                    ]))
            elif action == "setcategory" and len(parts) == 3:
                self.store.set_category(int(parts[1]), parts[2])
                self.show_item(user_id, int(parts[1]))
                self.refresh_views()
            elif action == "setstore" and len(parts) == 3:
                self.store.set_store(int(parts[1]), STORE_CODES[parts[2]])
                self.show_item(user_id, int(parts[1]))
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
