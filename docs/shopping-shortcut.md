## Updated template (0.5.17)

Shopping now uses Dictate Text (Ukrainian) and POST JSON to `/shortcuts/text`. Download the new template using `/shopping`, replace the old shortcut, and enter your personal Authorization value. Audio uploads remain supported for older shortcuts. Siri execution still requires verification on a physical iPhone.

# Shopping — public beta setup

## Українською

1. У приватному чаті бота викличте `/shopping` → **Налаштувати Shopping**.
2. У захищеному Mini App натисніть **Створити / замінити ключ**. Скопіюйте повне значення Authorization (`Bearer …`). Воно показується лише після створення; поле очищується за 90 секунд. Не надсилайте ключ у чат і не показуйте на скрінах.
3. Натисніть **Завантажити Shopping iOS Shortcut**: бот надішле підписаний **Shopping.shortcut** файловим вкладенням у чат. Поверніться до бота й відкрийте вкладення. За потреби відкрийте посилання у Safari, збережіть/відкрийте файл через Команди. Під час імпорту вставте Authorization у запит налаштування. Шаблон доступний за https://shopping.taranets.dev/Shopping.shortcut і не містить секретів.
4. Запустіть **Shopping** кнопкою, надайте дозволи на мікрофон і доступ до shopping.taranets.dev. Продиктуйте покупку, зупиніть запис дотиком. Результат прийде чернеткою в Telegram — перевірте та підтвердьте.
5. Спробуйте «Siri, Shopping». Перший імпорт, роботу Siri та запис на заблокованому екрані потрібно перевірити на конкретному iPhone. Підписання файлу не доводить його працездатність на фізичному пристрої.

Перед публічним поширенням перевірте пункти 3–5 на iPhone. Діліться лише оригінальним шаблоном, ніколи налаштованою копією.

### Відкликання й ліміти

- `/shoppingoff` або кнопка **Відкликати доступ** миттєво забороняє нові завантаження. Уже прийнятий у чергу запит може завершитися чернеткою; без підтвердження список не зміниться.
- Ключ діє 30 днів і лише для поточного списку. Після переходу в іншу сім’ю створіть новий ключ.
- Створення нового ключа відкликає попередній. Старі ключі з повідомлень у чаті автоматично відкликані під час оновлення до 0.5.13.
- Shopping: 10 спроб на користувача, 100 спроб на весь сервіс за добу UTC; до 30 секунд і 2 MB на запис. Квоти переживають перезапуск і заміну ключа. Невдалі/неповні/відхилені чергою завантаження можуть витрачати квоту. Це ліміти Shopping, не всіх AI-викликів бота.
- Ключ залишається у налаштуваннях Apple Shortcuts на вашому пристрої; система не може захистити його від людини з доступом до цього пристрою чи поширеної копії.

### Ручний резервний варіант

Створіть команду **Shopping** з діями:

1. **Record Audio**: Normal, Immediately, On Tap.
2. **Get Contents of URL**: `https://shopping.taranets.dev/shortcuts/audio`; POST; header Authorization with complete `Bearer …` value; Request Body **File → Recorded Audio**. Не Form/JSON.

202 — прийнято у чергу, не підтверджено якість розпізнавання. 401 — неправильний/відкликаний/прострочений ключ. 413 — завеликий файл. 415 — неправильний формат тіла. 429 — квота або черга; повторіть пізніше. Запис не завершується автоматично після тиші.

## English

Send `/shopping` in the bot → **Set up Shopping**. Create a personal key in the authenticated Telegram window and copy the complete Authorization value. Tap Download Shopping iOS Shortcut to receive a document in the bot chat. Return to the bot and open the attachment in Shortcuts, and enter that value when prompted during import. Never share the configured copy.

Run manually first, grant microphone/network permissions, speak and tap to stop. Confirm the draft in Telegram. Then try “Siri, Shopping”. Physical iPhone import, Siri and locked-screen behavior still need device validation before wider distribution.

Credentials last 30 days and are bound to the current list. `/shoppingoff` revokes new uploads; already queued work may finish. Quotas: 10/user and 100/service upload attempts per UTC day, 30 seconds/2 MB, preserved across restarts/rotation. These do not limit other bot entry points.

## Validation and operations

Only SHA-256 hashes of random 256-bit keys are persisted. Plaintext keys are returned only to an authenticated Telegram session after an explicit POST. Setup/API responses use no-store. HTTP logs omit payloads and credentials. The upload endpoint cannot read lists or mark purchases. Two upload slots and existing bounded voice admission limit concurrent work. Raw audio is removed after processing; /tmp is a bounded tmpfs.

HTTP tests cover key rotation/revocation/expiry, migration, invalid uploads, authenticated management, atomic quotas and draft confirmation. Mocked transcription does not measure live speech quality. Signed template rebuild: `python3 scripts/build-shopping-shortcut.py`, then `shortcuts sign --mode anyone --input /private/tmp/Shopping-unsigned.shortcut --output src/shopping_bot/web/Shopping.shortcut` on macOS.

DNS: explicit `shopping` A record at Vercel points to 185.217.124.92. The existing Caddy gateway routes this hostname to `family-shopping-bot-bot-1:8080` over the external `family-shopping-bot_default` Docker network. Gateway configuration/compose originals are backed up as `.before-shopping` on the VPS. Keep the external network attachment on gateway recreations. Other hostname routes are preserved.

This is a bounded beta integration, not a completed whole-product security audit or a distributed DDoS defence. Do not describe the service-wide Shopping request quota as a monetary ceiling for every AI provider.

## Experimental audio handoff (0.5.29)

Use `/shoppingaudio` to receive a separate signed `Shopping Audio` shortcut with a Copy key button. This rotates the previous key, just like `/shopping`. The template first continues in the Shortcuts app, records normal-quality audio until tapped, then POSTs the raw recording to `/shortcuts/audio`. Limit: 30 seconds / 2 MB. Recognition uses the current bot interface language through the existing Whisper pipeline. No Apple Dictate Text action is used. Text templates remain available through `/shopping`.

Device acceptance check: import with the copied key, run manually and grant permissions, then on an unlocked iPhone say the shortcut name using Siri’s configured language. Verify Shortcuts opens, the recording timer advances, stopping sends audio, and Telegram receives a Ukrainian draft. Siri launch, microphone handoff and locked-screen behavior are experimental until verified on an actual iPhone.
