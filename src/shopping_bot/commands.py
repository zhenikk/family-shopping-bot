"""Publish the supported private-chat commands to Telegram's command picker."""
COMMANDS = [
    ('start', 'Відкрити бота', 'Open bot'),
    ('list', 'Список покупок у чаті', 'Shopping list in chat'),
    ('catalog', 'Каталог товарів', 'Product catalog'),
    ('history', 'Історія покупок', 'Purchase history'),
    ('family', 'Учасники списку', 'List members'),
    ('shopping', 'Шорткат iOS: диктування тексту', 'iOS shortcut: text dictation'),
    ('shoppingaudio', 'Шорткат iOS: аудіо через Whisper (тест)', 'iOS shortcut: Whisper audio (test)'),
    ('shoppingoff', 'Відкликати ключ шортката', 'Revoke shortcut key'),
    ('help', 'Як користуватися ботом', 'How to use the bot'),
]


def register_commands(telegram):
    for locale in ('', 'uk', 'en'):
        telegram.call('setMyCommands', scope={'type': 'all_private_chats'}, language_code=locale,
                      commands=[{'command': command, 'description': uk if locale == 'uk' else en}
                                for command, uk, en in COMMANDS])
