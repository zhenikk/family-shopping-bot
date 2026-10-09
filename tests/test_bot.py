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

    def download(self, file_id, destination, **kwargs):
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
    def test_guest_text_creates_private_draft_without_disclosing_items(self):
        self.bot.handle_update({"guest_message": message(1, "@test_shopping_bot додай молоко, хліб", guest_query_id="g1")})
        answers = [params for method, params in self.telegram.calls if method == "answerGuestQuery"]
        self.assertEqual(len(answers), 1)
        self.assertNotIn("Молоко", str(answers))
        self.assertFalse(self.store.needs())
        self.assertTrue(any(method == "sendMessage" and params["chat_id"] == 1 for method, params in self.telegram.calls))
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM drafts WHERE actor_id=1").fetchone()[0], 1)

    def test_guest_text_reply_creates_draft_from_referenced_text(self):
        guest = message(1, "@test_shopping_bot", guest_query_id="text-reply", reply_to_message=message(2, "молоко, яйця, хліб"))
        self.bot.handle_update({"guest_message": guest})
        with self.store.db() as db:
            row = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(len(self.store.draft(1, row[0])), 3)

    def test_guest_voice_reply_uses_caller_and_existing_queue(self):
        guest = message(1, "@test_shopping_bot", guest_query_id="g2", reply_to_message=message(2, voice={"file_id":"voice-2"}))
        with patch.object(self.bot, "queue_voice") as queue:
            self.bot.handle_update({"guest_message": guest})
            queue.assert_called_once_with(1, "voice-2",message_id=None)

    def test_guest_direct_voice_reply_is_supported(self):
        with patch.object(self.bot, "queue_voice") as queue:
            self.bot.handle_update({"guest_message": message(1, guest_query_id="g3", voice={"file_id":"voice-1"})})
            queue.assert_called_once_with(1, "voice-1",message_id=None)

    def test_unregistered_guest_does_not_create_family_or_queue_voice(self):
        with patch.object(self.bot, "queue_voice") as queue:
            self.bot.handle_update({"guest_message": message(99, guest_query_id="g4", voice={"file_id":"voice"})})
            queue.assert_not_called()
        self.assertIsNone(self.bot.families.family(99))
        self.assertEqual(self.telegram.calls[-1][0], "answerGuestQuery")

    def test_help_preserves_pending_invite_and_does_not_create_family(self):
        self.bot.families.pending_start(99, '/start invite_pending')
        self.bot.handle_message(message(99, '/help'))
        self.assertIsNone(self.bot.families.family(99))
        self.assertEqual(self.bot.families.pending_start(99), '/start invite_pending')
        self.assertIn('1/6', self.telegram.calls[-1][1]['text'])

    def test_help_photos_navigation_and_invalid_callbacks(self):
        with patch.dict('os.environ', {'SHOPPING_WEB_URL':'https://example.com'}):
            self.bot.show_help(1, 'en', 'j', 2)
            method, payload = self.telegram.calls[-1]
            self.assertEqual(method, 'sendPhoto')
            self.assertEqual(payload['photo'], 'https://example.com/help/en-j-2.png?v=unknown')
            query = callback(1, 'help:uk:j:3')
            query['message']['photo'] = [{}]
            self.bot.handle_callback(query)
            self.assertTrue(any(method == 'editMessageMedia' for method, _ in self.telegram.calls))
            self.assertTrue(any(method == 'deleteMessage' and params['message_id'] == 50 for method, params in self.telegram.calls))
            before = len(self.telegram.calls)
            self.bot.handle_callback(callback(1, 'help:fr:x:999'))
            self.assertEqual(len(self.telegram.calls), before + 1)
        import json
        content = json.loads(Path(__file__).parents[1].joinpath('src/shopping_bot/help.json').read_text())
        for lang in content.values():
            for items in lang['steps'].values():
                for item in items:
                    self.assertLess(sum(len(item[k]) for k in ('title','body','tip')) + 50, 1024)

    def test_help_reuses_one_text_panel_for_reopen_and_steps(self):
        with patch.dict('os.environ', {'SHOPPING_WEB_URL':''}):
            self.telegram.calls.clear()
            self.bot.handle_message(message(1, '/help'))
            self.bot.handle_message(message(1, '/help'))
            self.bot.handle_callback(callback(1, 'help:uk:c:1', self.telegram.next_message_id))
            self.assertEqual(sum(method == 'sendMessage' for method, _ in self.telegram.calls), 1)
            self.assertTrue(any(method == 'editMessageText' for method, _ in self.telegram.calls))

    def test_list_reopen_reuses_existing_message(self):
        self.telegram.calls.clear()
        self.bot.show_list(1)
        self.bot.show_list(1)
        self.assertEqual(sum(method == 'sendMessage' for method, _ in self.telegram.calls), 1)

    def test_help_anchor_survives_restart_and_photo_failure_stays_text(self):
        from shopping_bot.families import Families
        from shopping_bot.telegram import TelegramError
        original = self.telegram.call
        def unavailable(method, **params):
            if method == 'sendPhoto':
                raise TelegramError('wrong file identifier/HTTP URL specified')
            return original(method, **params)
        with patch.dict('os.environ', {'SHOPPING_WEB_URL':'https://example.com'}), patch.object(self.telegram, 'call', side_effect=unavailable):
            self.telegram.calls.clear()
            self.bot.handle_message(message(1, '/help'))
            self.bot.families = Families(self.store, self.root / 'photos')
            self.bot.handle_callback(callback(1, 'help:en:j:2'))
            self.assertEqual(sum(method == 'sendMessage' for method, _ in self.telegram.calls), 1)
            self.assertEqual(self.telegram.calls[-2][0], 'editMessageText')

    def test_help_transient_edit_error_does_not_create_duplicate(self):
        from shopping_bot.telegram import TelegramError
        with patch.dict('os.environ', {'SHOPPING_WEB_URL':''}):
            self.bot.handle_message(message(1, '/help'))
            self.telegram.calls.clear()
            original = self.telegram.call
            def failing(method, **params):
                if method == 'editMessageText':
                    raise TelegramError('Too Many Requests: retry after 1')
                return original(method, **params)
            with patch.object(self.telegram, 'call', side_effect=failing):
                self.bot.handle_callback(callback(1, 'help:uk:c:1'))
            self.assertFalse(any(method.startswith('send') for method, _ in self.telegram.calls))

    def test_returning_user_start_and_help_skip_onboarding(self):
        self.bot.families.set_language(1, 'en')
        self.telegram.calls.clear()
        self.bot.handle_message(message(1, '/start'))
        self.assertFalse(any('Choose your language' in str(params) for _, params in self.telegram.calls))
        self.assertTrue(any('buy:' in str(params) or 'list:all' in str(params) for _, params in self.telegram.calls))
        with patch.dict('os.environ', {'SHOPPING_WEB_URL':''}):
            self.bot.handle_message(message(1, '/help'))
        self.assertIn('4/6', self.telegram.calls[-1][1]['text'])
        self.bot.handle_message(message(1, '/language'))
        self.assertIn('Choose your language', self.telegram.calls[-1][1]['text'])

    def test_existing_family_without_language_preference_is_not_new_user(self):
        with self.bot.families.db() as db:
            db.execute('DELETE FROM preferences WHERE user_id=1')
        self.telegram.calls.clear()
        self.bot.handle_message(message(1, '/start'))
        self.assertFalse(any('Choose your language' in str(params) for _, params in self.telegram.calls))
        self.assertEqual(self.bot.families.preference(1), 'uk')

    def test_list_chat_button_brings_list_to_bottom_and_removes_old_panel(self):
        self.bot.handle_message(message(1, '📋 Список у чаті'))
        previous = self.telegram.next_message_id
        self.telegram.calls.clear()
        self.bot.handle_message(message(1, '📋 Список у чаті'))
        sends = [params for method, params in self.telegram.calls if method == 'sendMessage']
        self.assertEqual(len(sends), 1, 'Explicit list opening must show a visible response below the user request')
        self.assertTrue(any(method == 'deleteMessage' and params['message_id'] == previous for method, params in self.telegram.calls))
        self.assertEqual(self.store.views()[0]['message_id'], self.telegram.next_message_id)

    def test_old_ukrainian_list_button_after_switching_to_english(self):
        self.bot.families.set_language(1, 'en')
        self.bot.handle_message(message(1, '📋 Список у чаті'))
        self.assertIn('list:all', str(self.telegram.calls[-1][1]['reply_markup']))
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM drafts WHERE actor_id=1").fetchone()[0], 0)

    def test_solo_and_shared_start_choices_and_later_invite(self):
        self.bot.families.set_language(55, 'en')
        self.bot.handle_message(message(55, '/start'))
        choice = next(params for method, params in reversed(self.telegram.calls) if method == 'sendMessage' and 'family:solo' in str(params))
        self.assertIn('Just for me', str(choice))
        self.bot.handle_callback(callback(55, 'family:solo'))
        own = self.bot.families.details(55)
        self.assertEqual(own['name'], 'My shopping')
        self.assertEqual(len(self.bot.families.members(own['id'])), 1)
        self.assertFalse(self.bot.families.invites(55))
        self.bot.handle_message(message(55, 'milk'))
        self.assertIn('Add to the list?', self.telegram.calls[-1][1]['text'])
        token = self.bot.families.create_invite(55)
        self.assertEqual(self.bot.families.accept_invite(56, 'Friend', token), 'joined')
        self.assertEqual(self.bot.families.family(56), own['id'])
        self.assertNotEqual(own['id'], self.bot.families.family(1))
        self.bot.handle_callback(callback(55, 'family:shared'))
        self.assertEqual(self.bot.families.details(55)['name'], 'My shopping')
        self.bot.handle_callback(callback(57, 'family:shared'))
        self.assertEqual(len(self.bot.families.members(self.bot.families.family(57))), 1)

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
        self.assertEqual([name for name, _ in items], ["Картопля", "Картопля фрі", "Помідори", "Картопля молода"])
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

    def test_support_report_requires_confirmation_and_never_adds_products(self):
        from shopping_bot.support import Support
        self.bot.handle_update({'message': message(1, '/support')})
        self.bot.handle_update({'message': message(1, 'Не бачу список дружини після приєднання')})
        draft = self.bot.support.draft(1)
        self.assertEqual(self.bot.support.tickets()['items'], [])
        self.assertEqual(self.store.catalog_count(), 0)
        self.assertEqual(Support(self.bot.families).draft(1)['token'], draft['token'])
        self.bot.handle_update({'callback_query': callback(1, 'support:send:' + draft['token'])})
        ticket = self.bot.support.tickets()['items'][0]
        self.assertEqual(ticket['text'], 'Не бачу список дружини після приєднання')
        self.assertEqual(ticket['metadata']['family_member_count'], 2)
        self.assertIsNone(self.bot.support.draft(1))
        self.bot.handle_update({'callback_query': callback(1, 'support:send:' + draft['token'])})
        self.assertEqual(len(self.bot.support.tickets()['items']), 1)
        self.assertEqual(self.store.catalog_count(), 0)

    def test_support_stale_confirmation_and_other_user_cannot_submit(self):
        self.bot.handle_message(message(1, '/support'))
        self.bot.handle_message(message(1, 'Перший опис проблеми'))
        old = self.bot.support.draft(1)['token']
        self.bot.handle_message(message(1, 'Виправлений опис проблеми'))
        latest = self.bot.support.draft(1)['token']
        for actor, token in ((1, old), (2, latest)):
            self.bot.handle_callback(callback(actor, 'support:send:' + token))
            self.assertEqual(self.bot.support.tickets()['items'], [])
        self.bot.handle_callback(callback(1, 'support:send:' + latest))
        self.assertEqual(self.bot.support.tickets()['items'][0]['text'], 'Виправлений опис проблеми')

    def test_support_cancel_and_switching_menu_restore_normal_shopping_input(self):
        self.bot.handle_message(message(1, '/support'))
        self.bot.handle_message(message(1, '/cancel'))
        self.assertIsNone(self.bot.support.draft(1))
        self.bot.handle_message(message(1, '/support'))
        self.bot.handle_message(message(1, '/family'))
        self.assertIsNone(self.bot.support.draft(1))
        self.bot.handle_message(message(1, 'Молоко'))
        with self.store.db() as db:
            draft_id = db.execute('SELECT id FROM drafts WHERE actor_id=1').fetchone()[0]
        self.assertEqual(self.store.draft(1, draft_id)[0]['name'], 'Молоко')
        self.assertEqual(self.bot.support.tickets()['items'], [])

    def test_support_available_without_family_in_english_and_enforces_daily_limit(self):
        self.bot.families.set_language(55, 'en')
        self.bot.handle_message(message(55, '/support'))
        self.assertIn('Describe the problem', self.telegram.calls[-1][1]['text'])
        self.bot.handle_message(message(55, voice={'file_id': 'not-a-shopping-voice'}))
        self.assertIn('as text', self.telegram.calls[-1][1]['text'])
        self.assertIsNone(self.bot.families.family(55))
        for _ in range(5):
            self.bot.support.begin(55)
            draft = self.bot.support.describe(55, 'Cannot open the shopping list')
            self.bot.support.submit({'id':55}, draft['token'], {'language':'en'})
        self.bot.support.begin(55)
        draft = self.bot.support.describe(55, 'Another bug in the shopping list')
        with self.assertRaises(ValueError):
            self.bot.support.submit({'id':55}, draft['token'], {})
        self.assertEqual(len(self.bot.support.tickets()['items']), 5)

    def test_join_is_private_and_has_no_member_cap(self):
        self.bot.handle_message(message(3, "/join this-is-a-secret-code"))
        self.assertTrue(self.store.is_member(3))
        self.bot.handle_message({"from": {"id": 4}, "chat": {"id": -10, "type": "group"}, "text": "/join this-is-a-secret-code"})
        self.assertFalse(self.store.is_member(4))
        self.assertEqual(len(self.store.recent_history()), 0)

    def test_family_onboarding_invitation_and_persisted_routing(self):
        self.bot.handle_callback(callback(3, "family:shared"))
        family = self.bot.families.family(3)
        self.assertNotEqual(family, "legacy")
        invite = self.bot.families.invite(3)
        self.bot.handle_message(message(4, "/start invite_" + invite))
        self.assertIsNone(self.bot.families.family(4))
        self.bot.handle_callback(callback(4,"family:accept:0:"+invite))
        self.assertEqual(self.bot.families.family(4), family)
        self.bot.handle_message(message(5, "/start invite_invalid"))
        self.assertIsNone(self.bot.families.family(5))
        self.bot.handle_message(message(1, "/start invite_" + invite))
        self.assertEqual(self.bot.families.family(1), "legacy")
        from shopping_bot.families import Families
        reopened = Families(self.store, self.root / "photos")
        self.assertEqual(reopened.family(4), family)
        self.assertTrue(reopened.resources(family)[0].is_member(4))

    def test_existing_empty_family_can_confirm_invitation_and_share_products(self):
        self.bot.families.enroll(3, "Recipient")
        self.bot.families.enroll(4, "Owner")
        target = self.bot.families.family(4)
        store, _ = self.bot.families.resources(target)
        product = store.ensure_product("молоко")
        store.add_need(product, 4)
        invite = self.bot.families.invite(4)
        old_family = self.bot.families.family(3)
        self.telegram.calls.clear()
        self.bot.handle_message(message(3, "/start invite_" + invite))
        self.assertEqual(self.bot.families.family(3), old_family)
        actions = [button['callback_data'] for method, params in self.telegram.calls if method=='sendMessage' for row in params.get('reply_markup',{}).get('inline_keyboard',[]) for button in row if 'callback_data' in button]
        self.assertIn('family:accept:0:' + invite, actions)
        self.bot.handle_callback(callback(3, 'family:accept:0:' + invite))
        self.assertEqual(self.bot.families.family(3), target)
        self.assertEqual(self.bot.store.needs()[0]['name'], 'Молоко')
        self.assertCountEqual([row['user_id'] for row in self.bot.store.members()], [4,3])
        self.bot.families.route_message(3,800,old_family)
        self.bot.handle_callback(callback(3,f'buy:{product}:all',message_id=800))
        self.assertEqual(len(store.needs()),1)
        self.assertEqual(len(self.bot.families.choices(3)),1)

    def test_invite_keeps_existing_products_and_delete_requires_owner(self):
        old,_=self.bot.families.enroll(3,'Recipient')
        original,_=self.bot.families.resources(old)
        product=original.ensure_product('яйця')
        original.add_need(product,3)
        target,_=self.bot.families.enroll(4,'Owner')
        invite=self.bot.families.invite(4)
        self.assertEqual(self.bot.families.accept_invite(3,'Recipient',invite),'joined')
        self.assertEqual(original.needs()[0]['name'],'Яйця')
        self.assertFalse(self.bot.families.delete(3))
        self.assertTrue(self.bot.families.rename(4,'Спільні покупки'))
        self.assertTrue(self.bot.families.rename(3,'Нова назва'))
        self.assertTrue(self.bot.families.delete(4))
        self.assertIsNone(self.bot.families.family(4))
        self.assertIsNone(self.bot.families.family(3))
        self.assertIsNone(self.bot.families.invited_family(invite))
        from shopping_bot.families import Families
        reopened=Families(self.store,self.root/'photos')
        self.assertIsNone(reopened.family(4))
        self.assertIsNone(reopened.family(3))

    def test_deleted_legacy_family_does_not_return_after_restart(self):
        self.assertTrue(self.bot.families.delete(1))
        from shopping_bot.families import Families
        reopened=Families(self.store,self.root/'photos')
        self.assertIsNone(reopened.family(1))
        self.assertIsNone(reopened.family(2))

    def test_transfer_active_list_preserves_target_fields_and_copies_photos(self):
        source,_=self.bot.families.enroll(3,'Source')
        destination,_=self.bot.families.enroll(4,'Destination')
        old,media=self.bot.families.resources(source)
        target,target_media=self.bot.families.resources(destination)
        milk=old.ensure_product('молоко','source note')
        photo=media/'milk.jpg';photo.write_bytes(b'milk photo')
        old.set_photo(milk,'milk-id',str(photo));old.add_need(milk,3)
        potato=old.ensure_product('картошка','source potato note');old.add_need(potato,3)
        bought=old.ensure_product('кава');old.add_need(bought,3);old.purchase(bought,3,'')
        existing=target.ensure_product('картопля','target note')
        target_photo=target_media/'potato.jpg';target_photo.write_bytes(b'target photo')
        target.set_photo(existing,'target-id',str(target_photo));target.add_need(existing,4)
        invite=self.bot.families.create_invite(4)
        self.assertEqual(self.bot.families.accept_invite(3,'Source',invite,transfer=True,expected_family=source),'joined')
        self.assertEqual({row['name'] for row in target.needs()},{'Молоко','Картопля'})
        self.assertEqual(target.product(existing)['note'],'target note')
        self.assertEqual(target.product(existing)['photo_path'],str(target_photo))
        imported=target.product_by_name('молоко')
        self.assertEqual(imported['note'],'source note')
        self.assertTrue(Path(imported['photo_path']).is_relative_to(target_media))
        self.assertEqual(Path(imported['photo_path']).read_bytes(),b'milk photo')
        self.assertEqual(imported['category'],old.product(milk)['category'])
        self.assertIsNone(target.product_by_name('кава'))
        self.assertFalse(any(row['action']=='bought' for row in target.recent_history()))
        self.assertEqual(len(self.bot.families.choices(3)),1)

    def test_failed_photo_transfer_keeps_source_and_token_reusable(self):
        source,_=self.bot.families.enroll(3,'Source')
        destination,_=self.bot.families.enroll(4,'Destination')
        old,media=self.bot.families.resources(source)
        target,_=self.bot.families.resources(destination)
        product=old.ensure_product('молоко');old.add_need(product,3)
        photo=media/'photo.jpg';photo.write_bytes(b'photo');old.set_photo(product,'id',str(photo))
        invite=self.bot.families.create_invite(4)
        with patch('shopping_bot.families.shutil.copyfile',side_effect=OSError('copy failed')):
            with self.assertRaises(OSError):
                self.bot.families.accept_invite(3,'Source',invite,transfer=True)
        self.assertEqual(self.bot.families.family(3),source)
        self.assertEqual(target.needs(),[])
        self.assertIsNotNone(self.bot.families.invite_info(invite,3))
        self.assertEqual(len(old.needs()),1)
        self.assertEqual(self.bot.families.accept_invite(3,'Source',invite,transfer=True),'joined')

    def test_one_use_invite_race_revoke_and_own_link(self):
        from concurrent.futures import ThreadPoolExecutor
        self.bot.families.enroll(3,'Owner')
        invite=self.bot.families.create_invite(3)
        self.assertEqual(self.bot.families.accept_invite(3,'Owner',invite),'already')
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda user:self.bot.families.accept_invite(user,'Guest',invite),(4,5)))
        self.assertCountEqual(statuses,['joined','invalid'])
        joined=4 if statuses[0]=='joined' else 5
        self.assertEqual(self.bot.families.accept_invite(joined,'Guest',invite),'already')
        another=self.bot.families.create_invite(joined)
        self.assertFalse(self.bot.families.revoke_invite(6,another))
        self.assertTrue(self.bot.families.revoke_invite(3,another))
        self.assertEqual(self.bot.families.accept_invite(6,'Guest',another),'invalid')

    def test_shared_family_leave_requires_owner_transfer_and_keeps_others_data(self):
        source,_=self.bot.families.enroll(3,'Owner')
        self.bot.families.enroll(4,'Member',self.bot.families.create_invite(3))
        destination,_=self.bot.families.enroll(5,'Destination')
        old,_=self.bot.families.resources(source)
        product=old.ensure_product('молоко');old.add_need(product,3)
        token=self.bot.families.create_invite(5)
        self.assertEqual(self.bot.families.leave(3),'owner_required')
        self.assertEqual(self.bot.families.accept_invite(3,'Owner',token),'owner_required')
        self.assertTrue(self.bot.families.transfer_owner(3,4))
        self.assertEqual(self.bot.families.accept_invite(3,'Owner',token,transfer=True),'transfer_forbidden')
        self.assertEqual(self.bot.families.accept_invite(3,'Owner',token),'joined')
        self.assertEqual(self.bot.families.family(4),source)
        self.assertEqual(len(old.needs()),1)
        self.assertEqual([row['user_id'] for row in self.bot.families.members(source)],[4])
        self.assertEqual(self.bot.families.details(4)['owner_id'],4)

    def test_notifications_go_only_to_all_members_of_current_family(self):
        self.bot.families.enroll(3, "Friend")
        invite = self.bot.families.invite(3)
        for user in (4, 5):
            invite=self.bot.families.create_invite(3)
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
        self.assertEqual(restored_store.needs()[0]["name"], "Яйця")
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

    def test_recognition_suggests_unique_typos_and_preserves_qualifiers(self):
        from shopping_bot.product_names import canonical_name, suggested_name
        self.assertEqual(canonical_name('iPhone яблука'), 'IPhone яблука')
        self.assertEqual(canonical_name('Nutella'), 'Nutella')
        self.assertEqual(self.store.resolved_items('помідорі, помідори, томати'), [('Помідори',None)])
        self.assertEqual(suggested_name('картопля фрі'), 'Картопля фрі')
        self.assertEqual(suggested_name('молоко безлактозне'), 'Молоко безлактозне')
        self.assertEqual(suggested_name('абвгде', ['Абвгдж','Абвгдз']), 'Абвгде')
        self.assertNotEqual(self.store.ensure_product('молоко'),self.store.ensure_product('молоко безлактозне'))

    def test_duplicate_migration_keeps_history_photos_and_notes(self):
        potato=self.store.ensure_product('картопля');self.store.add_need(potato,1)
        with self.store.db() as db:
            duplicate=db.execute("INSERT INTO products(name,normalized,preferred_store,created_at,category,note,photo_path,photo_file_id) VALUES ('картошка','картошка','Mercadona','2026','vegetables','важлива нотатка','/photo.jpg','photo')").lastrowid
            db.execute("INSERT INTO needs VALUES (?,2,'2026')",(duplicate,))
            db.execute("INSERT INTO events(product_id,actor_id,action,happened_at) VALUES (?,2,'added','2026')",(duplicate,))
        migrated=Store(self.store.path)
        self.assertEqual(migrated.catalog_count(),1)
        self.assertEqual(len(migrated.needs()),1)
        card=migrated.product(potato)
        self.assertEqual((card['name'],card['note'],card['photo_path']),('Картопля','важлива нотатка','/photo.jpg'))
        with migrated.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events WHERE product_id=?',(potato,)).fetchone()[0],2)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(Store(self.store.path).catalog_count(),1)

    def test_first_start_language_preserves_invitation_and_personal_settings(self):
        token=self.bot.families.create_invite(1)
        self.bot.handle_message(message(10,'/start invite_'+token))
        self.assertIsNone(self.bot.families.family(10))
        self.assertIn('Choose your language',self.telegram.calls[-1][1]['text'])
        self.bot.handle_callback(callback(10,'language:en'))
        self.assertEqual(self.bot.families.preference(10),'en')
        self.assertIn('Join',str(self.telegram.calls[-1][1]['reply_markup']))
        self.bot.handle_callback(callback(10,'family:accept:0:'+token))
        self.assertEqual(self.bot.families.family(10),self.bot.families.family(1))
        self.assertEqual(self.bot.families.preference(1),'uk')
        self.bot.handle_message(message(10,'milk, eggs and bread'))
        text=self.telegram.calls[-1][1]['text']
        self.assertIn('Add to the list?',text)
        self.assertIn('Dairy and eggs',text)
        self.assertIn('Milk',text)
        self.assertEqual(self.store.resolved_items('milk, молоко'),[('Milk',None)])
        product=self.store.ensure_product('молоко');self.store.set_note(product,'Не перекладати Milk')
        self.bot.show_item(10,product)
        self.assertIn('Молоко',self.telegram.calls[-1][1]['text'])
        self.assertIn('Не перекладати Milk',self.telegram.calls[-1][1]['text'])
        self.bot.handle_message(message(1,'/start'))
        self.assertEqual(self.bot.families.preference(10),'en')

    def test_voice_queue_limit_releases_after_failed_worker(self):
        workers = []
        with patch.object(self.bot.voice_pool, 'submit', side_effect=lambda fn, *args: workers.append(lambda: fn(*args))), patch('shopping_bot.app.threading.Timer'):
            self.bot.queue_voice(1, 'one')
            self.bot.queue_voice(1, 'two')
            self.bot.queue_voice(1, 'three')
            self.assertEqual(len(workers), 2)
            self.assertIn('черга зайнята', self.telegram.calls[-1][1]['text'])
            with patch.object(self.bot, 'process_voice', side_effect=RuntimeError('worker failed')):
                with self.assertRaises(RuntimeError):
                    workers.pop(0)()
            self.bot.queue_voice(1, 'four')
            self.assertEqual(len(workers), 2)
            with patch.object(self.bot, 'process_voice'):
                for worker in workers:
                    worker()
            self.assertEqual(self.bot.voice_admission.users, {})

    def test_voice_status_only_after_five_seconds_and_never_after_completion(self):
        timers=[];workers=[]
        class Timer:
            def __init__(self,delay,callback):
                self.delay=delay;self.callback=callback;self.cancelled=False;timers.append(self)
            def start(self):pass
            def cancel(self):self.cancelled=True
        def submit(fn,*args):workers.append(lambda:fn(*args))
        self.telegram.calls.clear()
        with patch('shopping_bot.app.threading.Timer',Timer),patch.object(self.bot.voice_pool,'submit',side_effect=submit):
            self.bot.handle_message(message(1,voice={'file_id':'fast'}))
            self.assertFalse(any(method=='sendMessage' for method,_ in self.telegram.calls))
            self.assertEqual(timers[0].delay,5)
            with patch('shopping_bot.app.transcribe',return_value='молоко'):
                workers.pop(0)()
            self.assertTrue(timers[0].cancelled)
            before=len(self.telegram.calls);timers[0].callback()
            self.assertEqual(len(self.telegram.calls),before)

            self.bot.handle_message(message(1,voice={'file_id':'queued'}))
            timers[-1].callback()
            self.assertIn('Голосове в черзі',self.telegram.calls[-1][1]['text'])
            with patch('shopping_bot.app.transcribe',return_value='яйця'):
                workers.pop(0)()

            self.bot.handle_message(message(1,voice={'file_id':'slow'}))
            def slow(*args,**kwargs):
                timers[-1].callback()
                self.assertIn('Розпізнаю голосове',self.telegram.calls[-1][1]['text'])
                return 'хліб'
            with patch('shopping_bot.app.transcribe',side_effect=slow):
                workers.pop(0)()
            before=len(self.telegram.calls);timers[-1].callback()
            self.assertEqual(len(self.telegram.calls),before)

    def test_voice_language_passed_to_whisper_and_scoped_to_each_user(self):
        self.bot.families.set_language(1,'en');self.bot.bind_user(1)
        with patch('shopping_bot.app.transcribe',return_value='milk, eggs') as recognize:
            self.bot.process_voice(1,'voice')
            self.assertEqual(recognize.call_args.kwargs['language_code'],'en')
        self.bot.bind_user(2)
        with patch('shopping_bot.app.transcribe',return_value='молоко') as recognize:
            self.bot.process_voice(2,'voice')
            self.assertEqual(recognize.call_args.kwargs['language_code'],'uk')
        from shopping_bot.i18n import language
        language.set('uk')

    def test_notifications_follow_recipient_language_and_keep_product_names(self):
        self.bot.families.set_language(2,'en')
        product=self.store.ensure_product('молоко');self.store.add_need(product,1)
        bought,batch,event=self.store.purchase(product,1,'')
        self.assertTrue(bought)
        self.bot.bind_user(1);self.telegram.calls.clear()
        self.bot.notify_partner(batch)
        sent=[params for method,params in self.telegram.calls if method=='sendMessage' and params['chat_id']==2]
        self.assertIn(' bought:',sent[-1]['text'])
        self.assertIn('Молоко',sent[-1]['text'])
        self.assertEqual(self.bot.families.preference(1),'uk')

    def test_translation_catalog_has_no_untranslated_bot_templates(self):
        from shopping_bot.i18n import language,tr,MESSAGES
        previous=language.set('en')
        try:
            for key in MESSAGES:
                self.assertFalse(any('а'<=c.lower()<='я' or c.lower() in 'іїєґ' for c in tr(key)),MESSAGES[key])
        finally:language.reset(previous)

    def test_voice_style_short_list_parser(self):
        self.assertEqual(parse_items("Молоко, яйця; хліб @Lidl. Кава"), [
            ("Молоко", None), ("Яйця", None), ("Хліб", "Lidl"), ("Кава", None),
        ])
        self.assertEqual(parse_items("Сьогодні треба купити яйця, молоко і хліб"), [
            ("Яйця", None), ("Молоко", None), ("Хліб", None),
        ])
        self.assertEqual(parse_items("Кава і вершки", split_conjunctions=False), [("Кава і вершки", None)])

    def test_off_dictionary_and_bounded_speech_context(self):
        from shopping_bot.categories import food_dictionary
        from shopping_bot.speech import shopping_prompt
        self.assertGreater(len(food_dictionary()), 10000)
        self.assertEqual(infer_category("Pineapples"), "produce")
        self.assertEqual(infer_category("невідома особлива річ"), "other")
        self.assertLessEqual(len(shopping_prompt("uk", ["x" * 60] * 100)), 480)
        self.assertIn("Milk", shopping_prompt("en"))

    def test_draft_name_edit_offers_clipboard_button(self):
        self.bot.make_draft(1, "Буряк")
        with self.store.db() as db:
            draft_id = db.execute("SELECT id FROM drafts WHERE actor_id=1").fetchone()[0]
        item = self.store.draft(1, draft_id)[0]
        self.bot.handle_callback(callback(1, f"dname:{draft_id}:{item['key']}"))
        panels = [p for _,p in self.telegram.calls if "reply_markup" in p]
        self.assertTrue(any(button.get("copy_text", {}).get("text") == "Буряк"
                            for p in panels for row in p["reply_markup"].get("inline_keyboard", []) for button in row))

    def test_conversational_shopping_request_filters_chatter(self):
        raw = "Женя, як пидеш в Меркадону, купи будь ласка буряк і фасоль біленько в маленькій упаковці. Манівини дуже треба. Дякую."
        items = parse_items(raw)
        self.assertEqual([name for name, _ in items], ["Буряк", "Квасоля біла", "Манівини"])
        self.assertIn("маленькій упаковці", items[1][1])
        self.assertTrue(all("Mercadona" in note for _, note in items))
        self.assertEqual(parse_items("Please buy milk and bread. Thank you."), [("Milk", None), ("Bread", None)])
        self.assertEqual(parse_items("Молоко без лактози, картопля фрі, незнайомий товар"), [("Молоко без лактози", None), ("Картопля фрі", None), ("Незнайомий товар", None)])

    def test_expanded_categories_and_specific_context(self):
        cases = {"Зубна паста":"care", "Мʼясо":"meat", "Авокади":"produce",
                 "Буряк":"produce", "Горішки":"snacks", "Снекі льоша":"snacks",
                 "Олія":"spices", "Макарони":"pantry", "Корм для кота":"pets",
                 "Моторна олива":"auto", "Автошампунь":"auto", "Лампочка":"home",
                 "Картопля":"produce", "Картопля фрі":"frozen",
                 "Frozen broccoli":"frozen", "Dog food":"pets", "Engine oil":"auto"}
        for name, category in cases.items():
            with self.subTest(name=name):
                self.assertEqual(infer_category(name), category)

    def test_taxonomy_migration_preserves_product_data_and_runs_once(self):
        product = self.store.ensure_product("Зубна паста")
        self.store.add_need(product, 1)
        self.store.set_note(product, "улюблена")
        with self.store.db() as db:
            db.execute("UPDATE products SET category='pantry' WHERE id=?", (product,))
            db.execute("DELETE FROM meta WHERE key='category_taxonomy_v2'")
        migrated = Store(self.store.path)
        self.assertEqual(migrated.product_by_name("Зубна паста")["category"], "care")
        self.assertEqual(migrated.product_by_name("Зубна паста")["note"], "улюблена")
        self.assertEqual(migrated.needs()[0]["id"], product)
        migrated.set_category(product, "other")
        reopened = Store(self.store.path)
        self.assertEqual(reopened.product_by_name("Зубна паста")["category"], "other")

    def test_categories_group_list_and_preserve_manual_choice(self):
        for name, expected in [("картоплю", "produce"), ("Мандарини", "produce"),
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
        self.assertIn("🥬 Овочі та фрукти\n• Картопля", content)
        self.assertIn("• Мандарини", content)
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
        self.assertEqual(row["category"], "produce")
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
