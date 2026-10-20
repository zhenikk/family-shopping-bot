"""Publish the supported private-chat commands to Telegram's command picker."""
COMMANDS = [
    ('start', 'Відкрити бота', 'Open bot', 'Bot öffnen'),
    ('list', 'Список покупок у чаті', 'Shopping list in chat', 'Einkaufsliste im Chat'),
    ('catalog', 'Каталог товарів', 'Product catalog', 'Produktkatalog'),
    ('history', 'Історія покупок', 'Purchase history', 'Einkaufsverlauf'),
    ('family', 'Учасники списку', 'List members', 'Mitglieder der Liste'),
    ('shopping', 'Шорткат iOS: запис покупок голосом', 'iOS shortcut: voice shopping', 'iOS-Kurzbefehl: Einkäufe per Sprache'),
    ('shoppingoff', 'Відкликати ключ шортката', 'Revoke shortcut key', 'Kurzbefehl-Schlüssel widerrufen'),
    ('help', 'Як користуватися ботом', 'How to use the bot', 'So funktioniert der Bot'),
    ('language', 'Мова інтерфейсу', 'Interface language', 'Sprache der Oberfläche'),
    ('support', 'Повідомити про проблему', 'Report a problem', 'Problem melden'),
]


def register_commands(telegram):
    for locale in ('', 'uk', 'en', 'de'):
        telegram.call('setMyCommands', scope={'type': 'all_private_chats'}, language_code=locale,
                      commands=[{'command': command, 'description': {'uk': uk, 'de': de}.get(locale, en)}
                                for command, uk, en, de in COMMANDS])
