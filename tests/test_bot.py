from contextlib import closing
import sqlite3
import tempfile
import tarfile
import unittest
from unittest.mock import patch
from pathlib import Path

from shopping_bot.categories import infer_category
from shopping_bot.app import ShoppingBot
from shopping_bot.backup import backup
from shopping_bot.store import Store, parse_items


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.next_message_id = 100

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "getMe":
            return {"username": "test_shopping_bot"}
        if method in ("sendMessage", "sendPhoto"):
            self.next_message_id += 1
            return {"message_id": self.next_message_id}
        return True

    def download(self, file_id, destination):
        destination.write_bytes(b"fake image bytes")


def message(user_id, text=None, **extra):
    value = {
        "from": {"id": user_id, "first_name": "Anna" if user_id == 1 else "Ivan"},
        "chat": {"id": user_id, "type": "private"},
    }
    if text is not None:
        value["text"] = text
    value.update(extra)
    return value


def callback(user_id, data, message_id=50):
    return {
        "id": f"callback-{user_id}-{data}",
        "from": {"id": user_id},
        "data": data,
        "message": {"chat": {"id": user_id, "type": "private"}, "message_id": message_id},
    }


class ShoppingBotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "shopping.sqlite3")
        self.telegram = FakeTelegram()
        self.bot = ShoppingBot(
            self.telegram, self.store, "this-is-a-secret-code", self.root / "photos",
            self.root / "whisper-cli", self.root / "ggml-base.bin",
        )
        self.bot.handle_message(message(1, "/join this-is-a-secret-code"))
        self.bot.handle_message(message(2, "/join this-is-a-secret-code"))

    def tearDown(self):
        self.bot.voice_pool.shutdown(wait=True)
        self.temp.cleanup()

    def test_edit_draft_before_confirmation_and_ignore_stale_removal(self):
        self.bot.make_draft(1, "Молоко, Хліб")
        with self.store.db() as db:
            draft_id = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()[0]
        milk, bread = self.store.draft(1, draft_id)
        self.bot.handle_callback(callback(2, f"ddel:{draft_id}:{milk['key']}"))
        self.assertEqual(len(self.store.draft(1, draft_id)), 2)
        self.bot.handle_callback(callback(1, f"dname:{draft_id}:{milk['key']}"))
        self.bot.handle_message(message(1, "Кефір"))
        self.bot.handle_callback(callback(1, f"dnote:{draft_id}:{milk['key']}"))
        self.bot.handle_message(message(1, "Жовта упаковка"))
        self.bot.handle_callback(callback(1, f"dcat:{draft_id}:{milk['key']}:dairy"))
        self.bot.handle_callback(callback(1, f"ddel:{draft_id}:{bread['key']}"))
        self.bot.handle_callback(callback(1, f"ddel:{draft_id}:{bread['key']}"))
        self.assertEqual(len(self.store.draft(1, draft_id)), 1)
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}"))
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}"))
        self.assertEqual(len(self.store.needs()), 1)
        product = self.store.product_by_name("Кефір")
        self.assertEqual(product["note"], "Жовта упаковка")
        self.assertEqual(product["category"], "dairy")

    def test_voice_list_uses_editable_confirmation(self):
        with patch("shopping_bot.app.transcribe", return_value="Молоко, яйця"):
            self.bot.process_voice(1, "voice-list")
        with self.store.db() as db:
            draft_id = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()[0]
        items = self.store.draft(1, draft_id)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["category"], "dairy")
        self.assertFalse(self.store.needs())
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}"))
        self.assertEqual(len(self.store.needs()), 2)

    def test_legacy_draft_remains_confirmable(self):
        draft_id = self.store.save_draft(1, [("Картопля", "Lidl")])
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}"))
        self.assertEqual(self.store.product_by_name("Картопля")["note"], "Купити в Lidl")

    def test_aliases_deduplicate_without_merging_distinct_products(self):
        items = parse_items("картошка, картопля, фріха, картопля фрі, помідори, томати, картопля молода")
        self.assertEqual([name for name, _ in items], ["картопля", "картопля фрі", "помідори", "картопля молода"])
        potato = self.store.ensure_product("картошка")
        self.store.set_photo(potato, "photo", "saved.jpg")
        self.store.set_note(potato, "Жовта упаковка")
        self.store.add_need(potato, 1)
        self.assertEqual(self.store.ensure_product("картопля"), potato)
        self.assertFalse(self.store.add_need(potato, 2))
        self.assertEqual(self.store.product(potato)["photo_file_id"], "photo")
        self.assertEqual(self.store.product(potato)["note"], "Жовта упаковка")
        self.assertNotEqual(self.store.ensure_product("фріха"), potato)
        self.assertNotEqual(self.store.ensure_product("картопля молода"), potato)

    def test_legacy_alias_card_is_reused_without_deleting_it(self):
        potato = self.store.ensure_product("картопля")
        with self.store.db() as db:
            db.execute("UPDATE products SET name='картошка', normalized='картошка' WHERE id=?", (potato,))
        self.assertEqual(self.store.ensure_product("картопля"), potato)
        self.assertEqual(self.store.product_by_name("картоплю")["id"], potato)
        self.assertEqual(self.store.product(potato)["name"], "картошка")

    def test_join_is_private_and_has_no_member_cap(self):
        self.bot.handle_message(message(3, "/join this-is-a-secret-code"))
        self.assertTrue(self.store.is_member(3))
        self.bot.handle_message({"from": {"id": 4}, "chat": {"id": -10, "type": "group"}, "text": "/join this-is-a-secret-code"})
        self.assertFalse(self.store.is_member(4))
        self.assertEqual(len(self.store.recent_history()), 0)

    def test_family_onboarding_invitation_and_persisted_routing(self):
        self.bot.handle_message(message(3, "/create"))
        family = self.bot.families.family(3)
        self.assertNotEqual(family, "legacy")
        invite = self.bot.families.invite(3)
        self.bot.handle_message(message(4, "/start invite_" + invite))
        self.assertEqual(self.bot.families.family(4), family)
        self.bot.handle_message(message(5, "/start invite_invalid"))
        self.assertIsNone(self.bot.families.family(5))
        self.bot.handle_message(message(1, "/start invite_" + invite))
        self.assertEqual(self.bot.families.family(1), "legacy")
        from shopping_bot.families import Families
        reopened = Families(self.store, self.root / "photos")
        self.assertEqual(reopened.family(4), family)
        self.assertTrue(reopened.resources(family)[0].is_member(4))

    def test_notifications_go_only_to_all_members_of_current_family(self):
        self.bot.families.enroll(3, "Friend")
        invite = self.bot.families.invite(3)
        for user in (4, 5):
            self.bot.families.enroll(user, "Partner", invite)
        self.bot.bind_user(3)
        product = self.bot.store.ensure_product("хліб")
        self.bot.store.add_need(product, 3)
        bought, batch, _ = self.bot.store.purchase(product, 3, "")
        self.telegram.calls.clear()
        self.bot.notify_partner(batch)
        recipients = [params["chat_id"] for method, params in self.telegram.calls if method == "sendMessage"]
        self.assertEqual(recipients, [4, 5])
        self.bot.notify_partner(batch)
        edits = [params["chat_id"] for method, params in self.telegram.calls if method == "editMessageText"]
        self.assertEqual(edits, [4, 5])

    def test_backup_restores_family_registry_data_and_photos(self):
        from shopping_bot.families import Families
        family, _ = self.bot.families.enroll(3, "Friend")
        store, media = self.bot.families.resources(family)
        product = store.ensure_product("яйця")
        store.add_need(product, 3)
        (media / "egg.jpg").write_bytes(b"photo")
        archive = backup(self.root, self.root / "backups")
        restored = self.root / "restored"
        restored.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(restored, filter="data")
        registry = Families(Store(restored / "shopping.sqlite3"), restored / "photos")
        self.assertEqual(registry.family(1), "legacy")
        self.assertEqual(registry.family(3), family)
        restored_store, restored_media = registry.resources(family)
        self.assertEqual(restored_store.needs()[0]["name"], "яйця")
        self.assertEqual((restored_media / "egg.jpg").read_bytes(), b"photo")

    def test_shared_list_purchase_batch_and_undo(self):
        self.bot.handle_message(message(1, "Молоко, Хліб @Lidl"))
        self.assertEqual(self.store.needs_for_store("Lidl"), [])
        with self.store.db() as db:
            draft_id = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()[0]
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}"))
        milk = self.store.product_by_name("молоко")
        bread = self.store.product_by_name("хліб")
        self.assertEqual(milk["preferred_store"], "Mercadona")
        self.assertEqual(bread["note"], "Купити в Lidl")
        self.assertEqual([r["name"] for r in self.store.needs_for_store("Lidl")], ["Молоко", "Хліб"])

        self.bot.handle_callback(callback(1, f"buy:{bread['id']}:L"))
        first_notice = [p for method, p in self.telegram.calls if method == "sendMessage" and p["chat_id"] == 2 and "купив" in p["text"]]
        self.assertEqual(len(first_notice), 1)
        self.bot.handle_callback(callback(1, f"buy:{milk['id']}:L"))
        edited_notice = [p for method, p in self.telegram.calls if method == "editMessageText" and p.get("chat_id") == 2]
        self.assertEqual(len(edited_notice), 1)
        self.assertIn("Хліб", edited_notice[0]["text"])
        self.assertIn("Молоко", edited_notice[0]["text"])
        self.assertEqual(self.store.needs_for_store("Lidl"), [])

        # A stale button in the other chat cannot buy the same item twice.
        self.bot.handle_callback(callback(2, f"buy:{milk['id']}:L"))
        bought = [e for e in self.store.recent_history() if e["action"] == "bought"]
        self.assertEqual(len(bought), 2)
        bread_event = next(e for e in bought if e["product_id"] == bread["id"])
        self.bot.handle_callback(callback(1, f"undo:{bread_event['id']}:{bread_event['batch_id']}"))
        self.assertEqual([r["name"] for r in self.store.needs_for_store("Lidl")], ["Хліб"])

    def test_photo_is_saved_on_reusable_product(self):
        self.bot.handle_message(message(1, caption="Кава @Auchan", photo=[{"file_id": "small"}, {"file_id": "large"}]))
        coffee = self.store.product_by_name("кава")
        self.assertEqual(coffee["note"], "Купити в Auchan")
        self.assertEqual(coffee["photo_file_id"], "large")
        self.assertTrue(Path(coffee["photo_path"]).is_file())
        self.bot.handle_callback(callback(2, f"photo:{coffee['id']}"))
        self.assertTrue(any(method == "sendPhoto" and params["chat_id"] == 2 for method, params in self.telegram.calls))
        self.bot.handle_callback(callback(1, f"buy:{coffee['id']}:A"))
        self.assertEqual(self.store.needs_for_store("Auchan"), [])
        self.bot.handle_callback(callback(2, f"readd:{coffee['id']}"))
        self.assertEqual(len(self.store.needs_for_store("Auchan")), 1)
        self.assertEqual(self.store.product(coffee["id"])["photo_file_id"], "large")

    def test_voice_style_short_list_parser(self):
        self.assertEqual(parse_items("Молоко, яйця; хліб @Lidl. Кава"), [
            ("Молоко", None), ("яйця", None), ("хліб", "Lidl"), ("Кава", None),
        ])
        self.assertEqual(parse_items("Сьогодні треба купити яйця, молоко і хліб"), [
            ("яйця", None), ("молоко", None), ("хліб", None),
        ])
        self.assertEqual(parse_items("Кава і вершки", split_conjunctions=False), [("Кава і вершки", None)])

    def test_categories_group_list_and_preserve_manual_choice(self):
        for name, expected in [("картоплю", "vegetables"), ("Мандарини", "fruit"),
                               ("кондиціонер для білизни", "cleaning"),
                               ("кондиціонер для волосся", "care"),
                               ("Leite Hacendado", "dairy"), ("невідома пачка", "other"),
                               ("шоколадне морозиво", "frozen"), ("кава з молоком", "drinks")]:
            self.assertEqual(infer_category(name), expected)
        potato = self.store.ensure_product("картопля")
        fruit = self.store.ensure_product("мандарини")
        self.store.add_need(potato, 1)
        self.store.add_need(fruit, 2)
        content, _ = self.bot.list_content("Mercadona")
        self.assertIn("🥕 Овочі\n• картопля", content)
        self.assertIn("🍊 Фрукти\n• мандарини", content)
        self.bot.handle_callback(callback(2, f"setcategory:{potato}:other"))
        self.store.ensure_product("картопля")
        self.assertEqual(self.store.product(potato)["category"], "other")
        reopened = Store(self.store.path)
        self.assertEqual(reopened.product(potato)["category"], "other")

    def test_unified_list_notes_and_persistent_edit(self):
        self.bot.handle_message(message(1, "картопля :: купити в Mercadona, молоко"))
        with self.store.db() as db:
            draft = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()[0]
        self.bot.handle_callback(callback(1, f"confirm:{draft}"))
        potato = self.store.product_by_name("картопля")
        milk = self.store.product_by_name("молоко")
        self.assertEqual(potato["note"], "купити в Mercadona")
        self.assertEqual(milk["note"], "")
        self.assertEqual(self.bot.list_content("Lidl"), self.bot.list_content("Mercadona"))
        text, markup = self.bot.list_content()
        self.assertIn("купити в Mercadona", text)
        self.assertNotIn("Улюблений магазин", text)
        self.assertEqual(self.bot.menu()["keyboard"][0], [{"text": "🛍 Покупки"}])
        self.bot.handle_callback(callback(2, f"note:{potato['id']}"))
        self.bot.handle_message(message(2, "велика пачка, жовта упаковка"))
        self.store.ensure_product("картопля")
        self.assertEqual(self.store.product(potato["id"])["note"], "велика пачка, жовта упаковка")
        self.bot.handle_callback(callback(1, f"buy:{potato['id']}:all"))
        self.assertEqual([row["id"] for row in self.store.needs()], [milk["id"]])
        self.bot.handle_callback(callback(1, f"clearnote:{potato['id']}"))
        self.assertEqual(self.store.product(potato["id"])["note"], "")

    def test_voice_note_saves_to_product_without_creating_draft(self):
        product_id = self.store.ensure_product("чіпси")
        self.bot.handle_callback(callback(1, f"note:{product_id}"))
        with patch("shopping_bot.app.transcribe", return_value="Купити в Mercadona."), \
             patch.object(self.bot.voice_pool, "submit", side_effect=lambda fn, *args: fn(*args)):
            self.bot.handle_message(message(1, voice={"file_id": "voice-note"}))
        self.assertEqual(self.store.product(product_id)["note"], "Купити в Mercadona.")
        self.assertNotIn(1, self.bot.pending_notes)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 0)
        self.assertEqual(self.store.catalog_count(), 1)

    def test_cancelled_or_long_voice_note_does_not_change_product(self):
        product_id = self.store.ensure_product("чіпси")
        self.bot.handle_callback(callback(1, f"note:{product_id}"))
        with patch("shopping_bot.app.transcribe", return_value="а" * 201):
            self.bot.process_voice(1, "voice-note", product_id)
        self.assertEqual(self.bot.pending_notes[1], product_id)
        self.bot.handle_message(message(1, "/cancel"))
        with patch("shopping_bot.app.transcribe", return_value="Купити в Lidl"):
            self.bot.process_voice(1, "voice-note", product_id)
        self.assertEqual(self.store.product(product_id)["note"], "")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 0)

    def test_panel_navigation_does_not_overwrite_card_with_list(self):
        product_id = self.store.ensure_product("молоко")
        self.store.add_need(product_id, 1)
        self.bot.show_list(1)
        view_id = self.store.views()[0]["message_id"]
        before = len([c for c in self.telegram.calls if c[0] == "sendMessage"])
        self.bot.handle_callback(callback(1, f"item:{product_id}", view_id))
        self.assertEqual(self.store.views(), [])
        self.bot.handle_callback(callback(1, f"categories:{product_id}", view_id))
        self.bot.handle_callback(callback(1, f"setcategory:{product_id}:other", view_id))
        after = len([c for c in self.telegram.calls if c[0] == "sendMessage"])
        self.assertEqual(before, after)
        edits = [p for m, p in self.telegram.calls if m == "editMessageText"]
        self.assertIn("Додати нотатку", str(edits[-1]["reply_markup"]))
        self.bot.handle_callback(callback(1, f"note:{product_id}", view_id))
        self.bot.handle_message(message(1, "📚 Каталог"))
        self.assertNotIn(1, self.bot.pending_notes)
        self.assertEqual(self.store.product(product_id)["note"], "")

    def test_purchase_feedback_is_one_message_and_draft_is_retired(self):
        self.bot.make_draft(1, "молоко, яйця")
        with self.store.db() as db:
            draft_id = db.execute("SELECT id FROM drafts").fetchone()[0]
        self.bot.handle_callback(callback(1, f"confirm:{draft_id}", 80))
        retired = [p for m, p in self.telegram.calls if m == "editMessageText" and p["message_id"] == 80]
        self.assertNotIn("confirm:", str(retired[-1]["reply_markup"]))
        for row in self.store.needs():
            self.bot.handle_callback(callback(1, f"buy:{row['id']}:all", 80))
        notices = [p for m, p in self.telegram.calls if m == "sendMessage" and p["chat_id"] == 1 and "Остання покупка" in p["text"]]
        self.assertEqual(len(notices), 1)
        feedback_id = self.bot.purchase_feedback[1]
        self.assertTrue(any(m == "editMessageText" and p["message_id"] == feedback_id for m, p in self.telegram.calls))

    def test_mini_app_uses_authenticated_inline_launch(self):
        with patch.dict("os.environ", {"SHOPPING_WEB_URL": "https://shopping.example"}):
            self.assertNotIn("web_app", str(self.bot.menu()))
            self.bot.handle_message(message(1, "/app"))
            markup = self.telegram.calls[-1][1]["reply_markup"]
            self.assertEqual(markup["inline_keyboard"][0][0]["web_app"]["url"], "https://shopping.example")

    def test_category_migration_preserves_existing_products(self):
        old_path = self.root / "old.sqlite3"
        with closing(sqlite3.connect(old_path)) as db, db:
            db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                       "normalized TEXT UNIQUE, preferred_store TEXT, photo_file_id TEXT, "
                       "photo_path TEXT, created_at TEXT)")
            db.execute("INSERT INTO products VALUES (7, 'мандарини', 'мандарини', 'Lidl', 'photo', NULL, 'old')")
        migrated = Store(old_path)
        row = migrated.product(7)
        self.assertEqual(row["category"], "fruit")
        self.assertEqual(row["photo_file_id"], "photo")
        self.assertEqual(row["preferred_store"], "Lidl")

    def test_backup_contains_consistent_db_and_product_photo(self):
        self.bot.handle_message(message(1, caption="Кава", photo=[{"file_id": "photo"}]))
        archive = backup(self.root, self.root / "separate-backup-disk")
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertIn("shopping.sqlite3", names)
            self.assertTrue(any(name.startswith("photos/") and name.endswith(".jpg") for name in names))


if __name__ == "__main__":
    unittest.main()
