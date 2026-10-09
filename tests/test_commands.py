import unittest
from shopping_bot.commands import register_commands
from test_bot import FakeTelegram


class CommandsTests(unittest.TestCase):
    def test_shortcuts_registered_in_all_private_chat_languages(self):
        telegram = FakeTelegram()
        register_commands(telegram)
        self.assertEqual(len(telegram.calls), 3)
        for method, params in telegram.calls:
            self.assertEqual(method, 'setMyCommands')
            self.assertEqual(params['scope'], {'type': 'all_private_chats'})
            commands = {item['command'] for item in params['commands']}
            self.assertTrue({'shopping', 'shoppingoff'} <= commands)
            self.assertNotIn('shoppingaudio', commands)
            self.assertTrue(all(' ' not in name for name in commands))
