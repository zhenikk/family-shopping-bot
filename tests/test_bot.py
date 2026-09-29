import sqlite3
import tempfile
import tarfile
import unittest
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

    def test_join_is_limited_to_two_private_members(self):
        self.bot.handle_message(message(3, "/join this-is-a-secret-code"))
        self.assertFalse(self.store.is_member(3))
        self.bot.handle_message({"from": {"id": 3}, "chat": {"id": -10, "type": "group"}, "text": "/join this-is-a-secret-code"})
        self.assertEqual(len(self.store.recent_history()), 0)

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
        self.assertEqual(self.bot.menu()["keyboard"][0], [{"text": "🛒 Список"}])
        self.bot.handle_callback(callback(2, f"note:{potato['id']}"))
        self.bot.handle_message(message(2, "велика пачка, жовта упаковка"))
        self.store.ensure_product("картопля")
        self.assertEqual(self.store.product(potato["id"])["note"], "велика пачка, жовта упаковка")
        self.bot.handle_callback(callback(1, f"buy:{potato['id']}:all"))
        self.assertEqual([row["id"] for row in self.store.needs()], [milk["id"]])
        self.bot.handle_callback(callback(1, f"clearnote:{potato['id']}"))
        self.assertEqual(self.store.product(potato["id"])["note"], "")

    def test_category_migration_preserves_existing_products(self):
        old_path = self.root / "old.sqlite3"
        with sqlite3.connect(old_path) as db:
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
