import json
import re
import tempfile
import unittest
from pathlib import Path

from shopping_bot.app import ShoppingBot, count_items
from shopping_bot.categories import infer_category
from shopping_bot.commands import register_commands
from shopping_bot.purchase_intent import purchase_targets
from shopping_bot.speech import shopping_prompt
from shopping_bot.store import Store, parse_items
from test_bot import FakeTelegram, message, callback

CYRILLIC = re.compile('[Ѐ-ӿ]')
ROOT = Path(__file__).resolve().parents[1] / 'src' / 'shopping_bot'


class GermanCatalogTests(unittest.TestCase):
    def test_every_bot_template_has_a_german_translation(self):
        from shopping_bot.i18n import language, tr, MESSAGES
        english = json.loads((ROOT / 'translations.json').read_text())
        german = json.loads((ROOT / 'translations.de.json').read_text())
        self.assertEqual(sorted(set(english) - set(german)), [], 'German must not fall back to English')
        previous = language.set('de')
        try:
            for key in MESSAGES:
                self.assertIsNone(CYRILLIC.search(tr(key)), MESSAGES[key])
            source = ''.join(path.read_text() for path in ROOT.glob('*.py'))
            for literal in set(re.findall(r"tr\('([^']+)'\)", source)) | set(re.findall(r'tr\("([^"]+)"\)', source)):
                self.assertIsNone(CYRILLIC.search(tr(literal)), literal)
        finally:
            language.reset(previous)

    def test_german_counts(self):
        self.assertEqual(count_items(1, 'de'), '1 Artikel')
        self.assertEqual(count_items(5, 'de'), '5 Artikel')

    def test_commands_are_registered_in_german(self):
        telegram = FakeTelegram()
        register_commands(telegram)
        german = next(params for _, params in telegram.calls if params['language_code'] == 'de')
        descriptions = {item['command']: item['description'] for item in german['commands']}
        self.assertEqual(descriptions['list'], 'Einkaufsliste im Chat')
        self.assertIsNone(CYRILLIC.search(' '.join(descriptions.values())))

    def test_speech_prompt_is_german(self):
        self.assertIn('Milch', shopping_prompt('de'))

    def test_help_has_german_steps(self):
        help_text = json.loads((ROOT / 'help.json').read_text())
        self.assertEqual(len(help_text['de']['steps']['c']), 6)
        self.assertEqual(len(help_text['de']['steps']['j']), 6)


class GermanParsingTests(unittest.TestCase):
    def test_german_list_with_quantities_and_conjunctions(self):
        self.assertEqual(parse_items('Milch, zwei Flaschen Wasser und Brot'),
                         [('Milch', None), ('Wasser', '2 Flaschen'), ('Brot', None)])

    def test_german_greeting_request_and_thanks_are_not_products(self):
        self.assertEqual([name for name, _ in parse_items('Hallo, kauf bitte Eier und Butter. Danke!')], ['Eier', 'Butter'])
        self.assertEqual([name for name, _ in parse_items('Wir brauchen Tomaten und Gurken')], ['Tomaten', 'Gurken'])

    def test_german_negation_and_correction(self):
        self.assertEqual([name for name, _ in parse_items('Kauf keine Milch, Brot')], ['Brot'])
        self.assertEqual([name for name, _ in parse_items('Milch, nein, lieber Kefir')], ['Kefir'])

    def test_german_dietary_variant_stays_distinct(self):
        names = [name for name, _ in parse_items('Milch, laktosefreie Milch')]
        self.assertEqual(len(names), 2)

    def test_german_categories(self):
        for name, category in [('Milch', 'dairy'), ('Kartoffeln', 'produce'), ('Brot', 'bakery'),
                               ('Kaffee', 'drinks'), ('Hundefutter', 'pets'), ('Zahnpasta', 'care'),
                               ('Waschmittel', 'cleaning'), ('Hähnchen', 'meat')]:
            self.assertEqual(infer_category(name), category, name)

    def test_german_purchase_commands(self):
        self.assertEqual(purchase_targets('Milch und Eier gekauft'), 'Milch und Eier')
        self.assertEqual(purchase_targets('Ich habe Milch gekauft'), 'Milch')
        self.assertEqual(purchase_targets('Milch nicht gekauft'), '')
        self.assertIsNone(purchase_targets('kauf Milch'))


class GermanBotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / 'shopping.sqlite3')
        self.telegram = FakeTelegram()
        self.bot = ShoppingBot(self.telegram, self.store, 'this-is-a-secret-code', root / 'photos', root / 'w', root / 'm')

    def tearDown(self):
        self.bot.voice_pool.shutdown(wait=True)
        self.temp.cleanup()

    def texts(self):
        return [params.get('text', '') + str(params.get('reply_markup', '')) for _, params in self.telegram.calls]

    def test_german_onboarding_list_and_draft(self):
        self.bot.handle_message(message(70, '/start'))
        self.assertIn('Deutsch', str(self.telegram.calls[-1][1]['reply_markup']))
        prompt = self.telegram.next_message_id
        self.bot.handle_callback(callback(70, 'language:de', message_id=prompt))
        self.assertEqual(self.bot.families.preference(70), 'de')
        self.assertIn('Nur für mich', self.texts()[-1])
        self.bot.handle_callback(callback(70, 'family:solo', message_id=prompt))
        self.assertEqual(self.bot.families.details(70)['name'], 'Meine Einkäufe')
        self.telegram.calls.clear()
        self.bot.handle_message(message(70, 'Milch, zwei Flaschen Wasser und Brot'))
        draft = self.telegram.calls[-1][1]
        self.assertIn('Zur Liste hinzufügen?', draft['text'])
        self.assertIn('Milchprodukte und Eier', draft['text'])
        self.assertIn('✅ Hinzufügen 3', str(draft['reply_markup']))
        for text in self.texts():
            self.assertIsNone(CYRILLIC.search(text), text)

    def test_german_and_ukrainian_names_share_one_product(self):
        self.bot.handle_message(message(1, '/start'))
        self.bot.handle_callback(callback(1, 'language:de'))
        self.bot.handle_callback(callback(1, 'family:solo'))
        self.bot.bind_user(1)
        self.assertEqual(len(self.bot.store.resolved_items('Milch, молоко, milk')), 1)

    def test_german_help_uses_german_text(self):
        self.bot.families.set_language(71, 'de')
        self.bot.show_help(71, step=3)
        sent = self.telegram.calls[-1][1]
        self.assertIn('Sag, was du brauchst', sent.get('text') or sent.get('caption'))
