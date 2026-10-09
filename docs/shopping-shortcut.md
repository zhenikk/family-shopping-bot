# Shopping — Apple Shortcuts

## Українською

1. У приватному чаті бота надішліть `/shopping`. Бот видасть URL і персональний заголовок Authorization. Повторний виклик відкликає попередній ключ.
2. На iPhone відкрийте **Команди / Shortcuts**, створіть команду `Shopping`.
3. Додайте **Записати аудіо / Record Audio**. Початок: **Одразу / Immediately**. Завершення: **Дотиком / On Tap**. Звичайної якості достатньо. Не додавайте дію диктування тексту: розпізнавання робить наш сервер.
4. Додайте **Отримати вміст URL / Get Contents of URL**. Вставте URL із бота.
5. Розгорніть параметри: **POST** → Headers → `Authorization` → значення `Bearer …` з бота. **Request Body → File → Recorded Audio**. Саме File, не Form і не JSON.
6. Спочатку запустіть команду кнопкою. Дозвольте мікрофон і доступ до домену сервера. Продиктуйте «дві пачки масла», завершіть запис дотиком.
7. У Telegram має прийти чернетка. Перевірте та підтвердьте її. Без підтвердження покупки не змінюються.
8. Тепер спробуйте «Siri, Shopping». Роботу на заблокованому екрані потрібно перевірити на конкретному пристрої; iOS може попросити розблокувати його. Можна також додати команду на головний екран або Action Button.

Не діліться командою після вставляння ключа. `/shoppingoff` відкликає доступ. Ключ дійсний 90 днів; при 401 викличте `/shopping` та замініть Authorization. 202 означає прийнято в чергу, не успішне розпізнавання. 429 — спробуйте пізніше. Аудіо — до 8 MB і 2 хвилин; короткі записи зручніші.

Готового iCloud-посилання немає: команду треба один раз створити на iPhone. Запис завершується дотиком, не автоматично після тиші. Безперервна фраза «Siri, Shopping, молоко…» не підтримується цим сценарієм.

## English

Send `/shopping` to the bot in a private chat. In Apple Shortcuts create **Shopping** with two actions:

1. **Record Audio**: start Immediately, finish On Tap, Normal quality.
2. **Get Contents of URL**: URL from the bot; POST; header Authorization with the complete `Bearer …` value; Request Body **File**, selecting **Recorded Audio**.

Run manually first and grant microphone/network permissions. Stop the recording on tap and confirm the resulting Telegram draft. Then try “Siri, Shopping”. Locked-screen behavior requires device testing. Do not share your configured shortcut. `/shoppingoff` revokes access, `/shopping` rotates the key, and credentials expire after 90 days.

## Implementation and validation

Only a SHA-256 hash of the random 256-bit per-user key is stored. The endpoint cannot read lists or mark products purchased. It accepts raw file bodies, rate-limits requests and uses the existing bounded voice queue, duration checks, transcription, extraction and confirmation workflow. Temporary files are removed after processing or rejected submissions. No credential is placed in the URL or request logs.

Automated HTTP tests cover invalid/rotated/revoked/expired keys, empty uploads and upload → draft behavior with mocked transcription. Actual Siri activation, permission prompts and recording behavior must be checked on an iPhone. No physical-device validation is claimed.

Apple reference: https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios
