'use strict';
const tg = window.Telegram?.WebApp;
const en = new URLSearchParams(location.search).get('lang') === 'en';
const $ = id => document.getElementById(id);
const text = (uk, english) => en ? english : uk;
let clearTimer;
function clearKey() { $('key').value = ''; $('key').type = 'password'; $('credentials').hidden = true; }
async function api(path, body) {
 if (!tg?.initData) throw new Error(text('Відкрийте через /shopping у боті.', 'Open via /shopping in the bot.'));
 const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Authorization': 'tma ' + tg.initData, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined, cache: 'no-store'});
 const data = await response.json();
 if (!response.ok) throw new Error(data.error || 'Request failed');
 return data;
}
async function refresh() {
 const data = await api('/api/shopping');
 $('status').textContent = text('Підключення: ', 'Connection: ') + (data.active ? text('активне', 'active') : text('вимкнене', 'disabled')) + ` · ${data.used_today}/${data.daily_limit}` + text(' сьогодні (UTC)', ' today (UTC)') + (data.active ? ' · ' + text('діє до ', 'expires ') + new Date(data.expires*1000).toLocaleDateString() : '');
}
$('intro').textContent = text('Siri, Shopping → диктування → підтвердження в Telegram.', 'Siri, Shopping → dictate → confirm in Telegram.');
$('install').textContent = text('Встановіть шаблон без секретів, потім вставте персональне значення Authorization. Імпорт на iPhone потребує першої перевірки. Не поширюйте налаштовану копію.', 'Install the secret-free template, then enter your personal Authorization value. iPhone import needs initial device validation. Do not share your configured copy.');
$('create').textContent = text('Створити / замінити й скопіювати ключ', 'Create / rotate and copy key');
$('revoke').textContent = text('Відкликати доступ', 'Revoke access');
$('reveal').textContent = text('Показати ключ', 'Show key');
$('copy').textContent = text('Скопіювати ключ і отримати файл у боті', 'Copy key and receive file in bot');
$('private').textContent = text('Показуємо один раз. Поле очиститься за 90 секунд. Ключ діє 30 днів і лише для поточного списку.', 'Shown once. This field clears after 90 seconds. The key lasts 30 days and is bound to your current list.');
$('manual-title').textContent = text('Ручне налаштування', 'Manual setup');
$('manual').textContent = text('Dictate Text: українська, зупинка після паузи. Get Contents of URL: POST, заголовок Authorization, тіло JSON, поле text → Dictated Text. Спочатку запустіть кнопкою і надайте дозволи.', 'Dictate Text: stop after pause. Get Contents of URL: POST, Authorization header, JSON body, text → Dictated Text. Run manually first to grant permissions.');
$('limits').textContent = text('Бета: 10 спроб на день, текст до 4000 символів. Загальна квота сервісу — 100 спроб на день. Невдалі завантаження теж можуть витрачати квоту. /shoppingoff вимикає доступ.', 'Beta: 10 attempts/day, text up to 4000 characters. Service-wide quota: 100 attempts/day. Failed uploads may also consume quota. /shoppingoff revokes access.');
$('endpoint').value = location.origin + '/shortcuts/text';
$('create').onclick = async () => {
 if (!confirm(text('Створити новий ключ і скопіювати? Попередній перестане працювати.', 'Create and copy a new key? The previous key will stop working.'))) return;
 $('create').disabled = true; $('create').textContent = text('Готуємо…', 'Preparing…'); $('error').textContent = '';
 clearKey();
 const pendingKey = api('/api/shopping/key', {confirm:true}).then(result => 'Bearer ' + result.key);
 // Safari needs clipboard.write to begin inside the user's click, before awaiting the network.
 let clipboard;
 try {
  if (navigator.clipboard?.write && window.ClipboardItem) {
   clipboard = navigator.clipboard.write([new ClipboardItem({'text/plain': pendingKey.then(value => new Blob([value], {type:'text/plain'}))})]).then(() => true, () => false);
  }
 } catch { clipboard = Promise.resolve(false); }
 try {
  $('key').value = await pendingKey; $('credentials').hidden = false;
  clearTimeout(clearTimer); clearTimer = setTimeout(clearKey, 90000);
  let copied = clipboard ? await clipboard : false;
  if (!clipboard) { try { await navigator.clipboard.writeText($('key').value); copied = true; } catch {} }
  $('error').textContent = copied ? text('✓ Ключ скопійовано. Надсилаємо файл у бот…', '✓ Key copied. Sending the file to the bot…') : text('Ключ створено. Натисніть «Скопіювати ключ» нижче — iOS заблокувала автоматичне копіювання.', 'Key created. Tap Copy key below; iOS blocked automatic copying.');
  if (copied) {
   await api('/api/shopping/download', {confirm:true});
   $('error').textContent = text('✓ Ключ у буфері, файл у чаті. Поверніться до бота й відкрийте вкладення.', '✓ Key copied, file in chat. Return to the bot and open the attachment.');
  }
  await refresh();
 } catch(error) { $('error').textContent = error.message; }
 finally { $('create').disabled = false; $('create').textContent = text('Створити / замінити й скопіювати ключ', 'Create / rotate and copy key'); }
};
$('revoke').onclick = async () => {
 if (!confirm(text('Відкликати доступ Shopping?', 'Revoke Shopping access?'))) return;
 try { await api('/api/shopping/revoke', {confirm:true}); clearKey(); await refresh(); }
 catch(error) { $('error').textContent = error.message; }
};
$('reveal').onclick = () => { $('key').type = $('key').type === 'password' ? 'text' : 'password'; };
$('copy').onclick = async () => {
 $('copy').disabled = true;
 try {
  await navigator.clipboard.writeText($('key').value);
  $('copy').textContent = text('✓ Ключ скопійовано', '✓ Key copied');
  await api('/api/shopping/download', {confirm:true});
  $('error').textContent = text('Ключ скопійовано, файл надіслано в бот. Поверніться до чату й відкрийте вкладення.', 'Key copied and file sent to bot. Return to chat and open the attachment.');
 } catch(error) {
  $('key').type = 'text'; $('key').select();
  $('error').textContent = text('Якщо копіювання заблоковано, скопіюйте ключ вручну. Файл можна отримати кнопкою в боті.', 'If copying is blocked, copy the key manually. Receive the file using the button in the bot.');
 } finally { $('copy').disabled = false; }
};
addEventListener('pagehide', clearKey);
tg?.ready(); tg?.expand();
tg?.setBackgroundColor?.('#f7f7fa'); tg?.setHeaderColor?.('#f7f7fa');
refresh().catch(error => { $('error').textContent = error.message; });

$('back').textContent = text('← Повернутися до бота', '← Back to bot');
function backToBot() { clearKey(); if (tg?.initData) tg.close(); else location.href = '/'; }
$('back').onclick = backToBot;
tg?.BackButton?.show(); tg?.BackButton?.onClick(backToBot);
for (const button of document.querySelectorAll('button')) {
 button.addEventListener('pointerdown', () => tg?.HapticFeedback?.impactOccurred('light'));
}
