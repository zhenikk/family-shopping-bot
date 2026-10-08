import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from shopping_bot.app import ShoppingBot
from shopping_bot.store import Store
from shopping_bot.webserver import AccessError, make_server, validate_init_data
from test_bot import FakeTelegram

TOKEN = "test-token-not-a-real-secret"


def signed_data(user_id=1, date=None):
    fields = {"auth_date": str(int(time.time()) if date is None else date),
              "user": json.dumps({"id": user_id, "first_name": "Test"})}
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    message = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class MiniAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / "shopping.sqlite3")
        self.store.join(1, "Anna")
        self.store.join(2, "Ivan")
        self.bot = ShoppingBot(FakeTelegram(), self.store, "private-family-code", root / "photos", root / "whisper", root / "model")
        self.server = make_server(self.bot, TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.bot.voice_pool.shutdown()
        self.temp.cleanup()

    def request(self, path, data=None, user=1, auth=True, family=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Authorization": "tma " + signed_data(user)} if auth else {}
        if data is not None and self.bot.families.family(user):
            headers['X-Shopping-Family']=family or self.bot.families.family(user)
        if data is not None:
            headers["Content-Type"] = "application/json"
        conn.request("GET" if data is None else "POST", path, body=None if data is None else json.dumps(data), headers=headers)
        response = conn.getresponse()
        body = response.read()
        status = response.status
        conn.close()
        return status, body

    def test_personal_language_preferences_onboarding_and_english_api(self):
        status,body=self.request('/api/preferences',user=55)
        self.assertEqual((status,json.loads(body)['language']),(200,None))
        status,body=self.request('/api/language',{'language':'en'},user=55)
        self.assertEqual(status,200)
        self.assertIsNone(self.bot.families.family(55))
        status,body=self.request('/api/state',user=55)
        self.assertEqual(json.loads(body)['language'],'en')
        self.assertIn('Vegetables',json.loads(body)['categories']['vegetables'])
        self.assertEqual(self.request('/api/language',{'language':'de'},user=55)[0],400)
        self.assertEqual(self.request('/api/language',{'language':'en'},user=55,auth=False)[0],401)
        self.request('/api/language',{'language':'en'},user=1)
        self.assertEqual(self.bot.families.preference(2),'uk')
        self.request('/api/add',{'text':'milk, eggs and bread'},user=1)
        status,body=self.request('/api/state',user=1)
        self.assertEqual({p['name'] for p in json.loads(body)['products']},{'Milk','Eggs','Bread'})
        self.request('/api/add',{'text':'молоко'},user=2)
        self.assertEqual(self.store.catalog_count(),3)
        status,body=self.request('/?lang=en',auth=False)
        self.assertEqual(status,200)
        self.assertIn(b'lang="en"',body)
        self.assertIn(b'Our groceries',body)
        status,body=self.request('/app.js?lang=en',auth=False)
        self.assertEqual(status,200)
        self.assertIn(b'Add to the shared list?',body)

    def test_signature_tamper_expiry_and_duplicate_fields(self):
        good = signed_data(date=10000)
        self.assertEqual(validate_init_data(good, TOKEN, now=10010), 1)
        for bad, now in [(good.replace("10000", "10001"), 10010), (good, 14000),
                         (good + "&auth_date=10000", 10010), (good, 9900)]:
            with self.assertRaises(AccessError):
                validate_init_data(bad, TOKEN, now=now)

    def test_complete_family_management_api_and_onboarding(self):
        self.assertEqual(self.request('/api/family',user=3,auth=False)[0],401)
        self.assertIsNone(json.loads(self.request('/api/family',user=3)[1])['family_id'])
        self.assertEqual(self.request('/api/family/create',{},user=3)[0],200)
        family=self.bot.families.family(3)
        self.assertEqual(self.request('/api/family/rename',{'name':'Дім'},user=3)[0],200)
        invite=json.loads(self.request('/api/family/invite',{},user=3)[1])
        preview=json.loads(self.request('/api/family/preview',{'token':invite['token']},user=4)[1])
        self.assertEqual(preview['name'],'Дім')
        self.assertFalse(preview['can_transfer'])
        self.assertEqual(self.request('/api/family/accept',{'token':invite['token'],'confirm':True,'source_family':None},user=4)[0],200)
        self.assertEqual(self.bot.families.family(4),family)
        self.assertEqual(self.request('/api/family/preview',{'token':invite['token']},user=5)[0],410)
        self.assertEqual(self.request('/api/family/rename',{'name':'Наш дім'},user=4)[0],200)
        self.assertEqual(self.request('/api/family/delete',{'confirm':True},user=4)[0],403)
        self.assertEqual(self.request('/api/family/leave',{'confirm':True},user=3)[0],403)
        self.assertEqual(self.request('/api/family/owner',{'user_id':4,'confirm':True},user=3)[0],200)
        self.assertEqual(self.request('/api/family/leave',{'confirm':True},user=3)[0],200)
        members=json.loads(self.request('/api/family',user=4)[1])['members']
        self.assertEqual([row['id'] for row in members],[4])
        self.assertEqual(self.request('/api/family/delete',{'confirm':False},user=4)[0],400)
        self.assertEqual(self.request('/api/family/delete',{'confirm':True},user=4)[0],200)
        self.assertTrue(json.loads(self.request('/api/state',user=4)[1])['onboarding'])

    def test_api_transition_preserves_target_and_requires_explicit_transfer(self):
        self.bot.families.enroll(3,'Source')
        source=self.bot.families.family(3)
        old,_=self.bot.families.resources(source)
        product=old.ensure_product('картопля');old.add_need(product,3)
        self.bot.families.enroll(4,'Destination')
        invite=self.bot.families.create_invite(4)
        preview=json.loads(self.request('/api/family/preview',{'token':invite},user=3)[1])
        self.assertTrue(preview['can_transfer'])
        self.assertTrue(preview['delete_previous'])
        self.assertEqual(self.request('/api/family/accept',{'token':invite,'source_family':source,'transfer':True,'confirm':False},user=3)[0],400)
        self.assertEqual(self.bot.families.family(3),source)
        self.assertEqual(self.request('/api/family/accept',{'token':invite,'source_family':source,'transfer':True,'confirm':True},user=3)[0],200)
        current=json.loads(self.request('/api/state',user=3)[1])
        self.assertEqual(current['products'][0]['name'],'Картопля')
        self.assertEqual(current['family_id'],self.bot.families.family(4))

    def test_switched_family_rejects_stale_miniapp_mutation(self):
        old,_=self.bot.families.enroll(3,'Recipient')
        target,_=self.bot.families.enroll(4,'Owner')
        store,_=self.bot.families.resources(target)
        product=store.ensure_product('яйця')
        store.add_need(product,4)
        self.bot.families.accept_invite(3,'Recipient',self.bot.families.invite(4))
        status,_=self.request('/api/buy',{'id':product},user=3,family=old)
        self.assertEqual(status,409)
        self.assertEqual(len(store.needs()),1)
        self.assertEqual(self.request('/api/buy',{'id':product},user=3)[0],200)

    def test_private_data_and_photos_require_family_authorization(self):
        product = self.store.ensure_product("молоко")
        photo = self.bot.media_dir / "photo.jpg"
        photo.write_bytes(b"private photo")
        self.store.set_photo(product, "private-telegram-id", str(photo))
        for route in ("/api/state", f"/api/photo/{product}"):
            self.assertEqual(self.request(route, auth=False)[0], 401)
            if route=="/api/state":
                onboarding=json.loads(self.request(route,user=3)[1])
                self.assertTrue(onboarding["onboarding"])
                self.assertEqual(onboarding["products"],[])
            else:
                self.assertEqual(self.request(route, user=3)[0], 401)
        status, data = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn(b"private-telegram-id", data)
        self.assertNotIn(str(photo).encode(), data)
        self.assertEqual(self.request(f"/api/photo/{product}")[1], b"private photo")
        self.assertEqual(self.request("/")[0], 200)

    def test_families_isolate_overlapping_ids_photos_mutations_and_sync(self):
        legacy = self.store.ensure_product("молоко")
        self.store.add_need(legacy, 1)
        self.bot.families.enroll(3, "Friend")
        self.bot.families.enroll(4, "Partner", self.bot.families.invite(3))
        legacy_family=json.loads(self.request('/api/family', user=1)[1])
        friend_family=json.loads(self.request('/api/family', user=3)[1])
        self.assertEqual([member['name'] for member in legacy_family['members']], ['Anna', 'Ivan'])
        self.assertEqual([member['name'] for member in friend_family['members']], ['Friend', 'Partner'])
        self.assertEqual([member['self'] for member in friend_family['members']], [True, False])
        self.assertEqual(self.request('/api/family', auth=False)[0],401)
        self.assertEqual(self.request("/api/add", {"text": "хліб"}, user=3)[0], 200)
        family_store, media = self.bot.families.resources(self.bot.families.family(3))
        friend = family_store.product_by_name("хліб")
        self.assertEqual(friend["id"], legacy)  # IDs deliberately overlap.
        photo = media / "friend.jpg"
        photo.write_bytes(b"friend photo")
        family_store.set_photo(friend["id"], "id", str(photo))
        self.assertEqual(self.request(f"/api/photo/{legacy}", user=1)[0], 404)
        self.assertEqual(self.request(f"/api/photo/{friend['id']}", user=4)[1], b"friend photo")
        with ThreadPoolExecutor(max_workers=2) as pool:
            states = list(pool.map(lambda user: json.loads(self.request("/api/state", user=user)[1]), [1, 3]))
        self.assertEqual([state["products"][0]["name"] for state in states], ["Молоко", "Хліб"])
        self.request("/api/edit", {"id": friend["id"], "note": "friend only", "category": "other"}, user=3)
        result = json.loads(self.request("/api/buy", {"id": friend["id"]}, user=3)[1])
        self.assertTrue(result["bought"])
        self.assertEqual(len(self.store.needs()), 1)
        self.assertEqual(self.store.product(legacy)["note"], "")
        self.assertEqual(len(self.store.recent_history()), 1)
        deadline = time.time() + 2
        while time.time() < deadline and not any(method == "sendMessage" and params.get("chat_id") == 4 for method, params in self.bot.telegram.calls):
            time.sleep(.01)
        recipients = [params["chat_id"] for method, params in self.bot.telegram.calls if method == "sendMessage"]
        self.assertEqual(recipients, [4])
        # A foreign family cannot undo a purchase whose event ID is absent there.
        self.assertFalse(json.loads(self.request("/api/undo", {"event_id": result["event_id"]}, user=1)[1])["restored"])

    def test_shared_add_edit_purchase_undo_and_atomic_validation(self):
        self.assertEqual(self.request("/api/draft", {"text": "картопля :: Mercadona"})[0], 200)
        self.assertEqual(self.store.needs(), [])
        self.request("/api/add", {"text": "картопля :: Mercadona"})
        product = self.store.product_by_name("картопля")
        state = json.loads(self.request("/api/state", user=2)[1])
        self.assertTrue(state["products"][0]["active"])
        bad = self.request("/api/edit", {"id": product["id"], "note": "changed", "category": "bad"})
        self.assertEqual(bad[0], 400)
        self.assertEqual(self.store.product(product["id"])["note"], "Купити в Mercadona")
        self.request("/api/edit", {"id": product["id"], "note": "велика пачка", "category": "vegetables"}, user=2)
        self.assertEqual(self.store.product(product["id"])["note"], "велика пачка")
        result = json.loads(self.request("/api/buy", {"id": product["id"]})[1])
        self.assertTrue(result["bought"])
        self.assertEqual(self.store.needs(), [])
        wrong_actor = json.loads(self.request("/api/undo", {"event_id": result["event_id"]}, user=2)[1])
        self.assertFalse(wrong_actor["restored"])
        restored = json.loads(self.request("/api/undo", {"event_id": result["event_id"]})[1])
        self.assertTrue(restored["restored"])
        self.assertEqual(len(self.store.needs()), 1)

    def test_simultaneous_purchases_commit_once(self):
        product = self.store.ensure_product("яйця")
        self.store.add_need(product, 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda user: json.loads(self.request("/api/buy", {"id": product}, user=user)[1]), [1, 2]))
        self.assertEqual(sum(result["bought"] for result in results), 1)
        self.assertEqual(len([row for row in self.store.recent_history() if row["action"] == "bought"]), 1)

    def test_parallel_products_keep_one_partner_notification(self):
        products = [self.store.ensure_product(name) for name in ("молоко", "яйця")]
        for product in products:
            self.store.add_need(product, 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda product: self.request("/api/buy", {"id": product}), products))
        self.assertTrue(all(status == 200 for status, body in results))
        self.server.sync_pool.submit(lambda: None).result(timeout=5)
        sent = [params for method, params in self.bot.telegram.calls if method == "sendMessage" and params["chat_id"] == 2]
        self.assertEqual(len(sent), 1)
        edits = [params for method, params in self.bot.telegram.calls if method == "editMessageText" and params["chat_id"] == 2]
        self.assertTrue(edits)
        self.assertIn("Молоко", edits[-1]["text"])
        self.assertIn("Яйця", edits[-1]["text"])

    def test_purchase_response_does_not_wait_for_telegram(self):
        product = self.store.ensure_product("молоко")
        self.store.add_need(product, 1)
        called = threading.Event()
        def slow_telegram(batch):
            called.set()
            time.sleep(1)
        with patch.object(self.bot, "notify_partner", side_effect=slow_telegram):
            started = time.monotonic()
            status, body = self.request("/api/buy", {"id": product})
            elapsed = time.monotonic() - started
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["bought"])
            self.assertTrue(called.wait(1))
            self.assertLess(elapsed, 0.4, "API waits for Telegram instead of returning the saved purchase")
            print(f"Purchase response with 1s Telegram delay: {elapsed * 1000:.1f}ms")
