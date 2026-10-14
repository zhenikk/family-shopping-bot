"""Owner-approved announcements with durable per-recipient delivery claims.

Ambiguous network failures remain failed rather than being automatically retried.
"""
import secrets
import time


def preview(bot, owner, text):
    if owner not in bot.admin_ids:
        return
    if not text or len(text) > 3000:
        bot.send(owner, '/announce Текст оновлення (до 3000 символів)')
        return
    token = secrets.token_hex(12)
    with bot.families.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS announcements (token TEXT PRIMARY KEY, owner INTEGER, body TEXT, approved INTEGER DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS announcement_deliveries (token TEXT, user_id INTEGER, status TEXT, PRIMARY KEY(token,user_id))')
        db.execute('INSERT INTO announcements(token,owner,body) VALUES (?,?,?)', (token, owner, text))
        recipients = db.execute('SELECT user_id FROM users').fetchall()
        db.executemany("INSERT INTO announcement_deliveries VALUES (?,?,'pending')", [(token, row[0]) for row in recipients])
    bot.send(owner, f'Попередній перегляд · {len(recipients)} користувачів\n\n{text}', reply_markup={'inline_keyboard': [[{'text': 'Підтвердити розсилку', 'callback_data': 'announce:send:' + token}, {'text': 'Скасувати', 'callback_data': 'announce:cancel:' + token}]]})


def approve(bot, owner, action, token):
    if owner not in bot.admin_ids:
        return
    with bot.families.db() as db:
        row = db.execute('SELECT body FROM announcements WHERE token=? AND owner=? AND approved=0', (token, owner)).fetchone()
        if not row:
            return
        db.execute('UPDATE announcements SET approved=? WHERE token=?', (1 if action == 'send' else -1, token))
    if action != 'send':
        bot.send(owner, 'Розсилку скасовано.')
        return
    # Dedicated thread: do not hold family routing lock during broadcast.
    import threading
    threading.Thread(target=deliver, args=(bot, owner, token, row[0]), daemon=True).start()
    bot.send(owner, 'Розсилку підтверджено.')


def deliver(bot, owner, token, body):
    sent = failed = 0
    with bot.families.db() as db:
        users = [row[0] for row in db.execute("SELECT user_id FROM announcement_deliveries WHERE token=? AND status='pending'", (token,))]
    for user in users:
        with bot.families.db() as db:
            claimed = db.execute("UPDATE announcement_deliveries SET status='sending' WHERE token=? AND user_id=? AND status='pending'", (token, user)).rowcount
        if not claimed:
            continue
        try:
            bot.telegram.call('sendMessage', chat_id=user, text=body)
            status = 'sent'
            sent += 1
        except Exception:
            status = 'failed'
            failed += 1
        with bot.families.db() as db:
            db.execute('UPDATE announcement_deliveries SET status=? WHERE token=? AND user_id=?', (status, token, user))
        time.sleep(.12)
    bot.send(owner, f'Розсилка завершена: {sent} доставлено, {failed} помилок.')
