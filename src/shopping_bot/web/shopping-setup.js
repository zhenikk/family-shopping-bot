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
$('intro').textContent = text('Siri, Shopping → запис → підтвердження в Telegram.', 'Siri, Shopping → record → confirm in Telegram.');
$('install').textContent = text('Встановіть шаблон без секретів, потім вставте персональне значення Authorization. Імпорт на iPhone потребує першої перевірки. Не поширюйте налаштовану копію.', 'Install the secret-free template, then enter your personal Authorization value. iPhone import needs initial device validation. Do not share your configured copy.');
$('create').textContent = text('Створити / замінити ключ', 'Create / rotate key');
$('revoke').textContent = text('Відкликати доступ', 'Revoke access');
$('reveal').textContent = text('Показати ключ', 'Show key');
$('copy').textContent = text('Скопіювати Authorization', 'Copy Authorization');
$('private').textContent = text('Показуємо один раз. Поле очиститься за 90 секунд. Ключ діє 30 днів і лише для поточного списку.', 'Shown once. This field clears after 90 seconds. The key lasts 30 days and is bound to your current list.');
$('manual-title').textContent = text('Ручне налаштування', 'Manual setup');
$('manual').textContent = text('Record Audio: Immediately → On Tap. Get Contents of URL: POST, заголовок Authorization, тіло File → Recorded Audio. Спочатку запустіть кнопкою і надайте дозволи. Зупиняйте запис дотиком.', 'Record Audio: Immediately → On Tap. Get Contents of URL: POST, Authorization header, body File → Recorded Audio. Run manually first to grant permissions. Stop recording on tap.');
$('limits').textContent = text('Бета: 10 спроб на день, аудіо до 30 секунд і 2 MB. Загальна квота сервісу — 100 спроб на день. Невдалі завантаження теж можуть витрачати квоту. /shoppingoff вимикає доступ.', 'Beta: 10 attempts/day, up to 30 seconds and 2 MB. Service-wide quota: 100 attempts/day. Failed uploads may also consume quota. /shoppingoff revokes access.');
$('endpoint').value = location.origin + '/shortcuts/audio';
$('create').onclick = async () => {
 if (!confirm(text('Замінити ключ? Попередній перестане працювати.', 'Rotate key? The previous key will stop working.'))) return;
 $('create').disabled = true; $('create').textContent = text('Створюємо ключ…', 'Creating key…'); $('error').textContent = '';
 try { clearKey(); const result = await api('/api/shopping/key', {confirm:true}); $('key').value = 'Bearer ' + result.key; $('credentials').hidden = false; clearTimeout(clearTimer); clearTimer = setTimeout(clearKey, 90000); await refresh(); }
 catch (error) { $('error').textContent = error.message; }
 finally { $('create').disabled = false; $('create').textContent = text('Створити / замінити ключ', 'Create / rotate key'); }
};
$('revoke').onclick = async () => {
 if (!confirm(text('Відкликати доступ Shopping?', 'Revoke Shopping access?'))) return;
 try { await api('/api/shopping/revoke', {confirm:true}); clearKey(); await refresh(); }
 catch(error) { $('error').textContent = error.message; }
};
$('reveal').onclick = () => { $('key').type = $('key').type === 'password' ? 'text' : 'password'; };
$('copy').onclick = async () => {
 try { await navigator.clipboard.writeText($('key').value); $('copy').textContent = text('✓ Скопійовано', '✓ Copied'); $('error').textContent = text('Скопійовано. Вставте у Shopping; не поширюйте.', 'Copied. Paste into Shopping; do not share.'); }
 catch { $('key').type = 'text'; $('key').select(); $('error').textContent = text('Скопіюйте виділений текст вручну.', 'Copy the selected text manually.'); }
};
addEventListener('pagehide', clearKey);
tg?.ready(); tg?.expand();
refresh().catch(error => { $('error').textContent = error.message; });

$('back').textContent = text('← Повернутися до бота', '← Back to bot');
function backToBot() { clearKey(); if (tg?.initData) tg.close(); else location.href = '/'; }
$('back').onclick = backToBot;
tg?.BackButton?.show(); tg?.BackButton?.onClick(backToBot);
$('download').onclick = async () => {
 $('download').disabled = true; $('download').textContent = text('Надсилаємо файл…', 'Sending file…');
 try { await api('/api/shopping/download', {confirm:true}); $('download').textContent = text('✓ Файл у чаті бота', '✓ File sent to bot chat'); $('error').textContent = text('Поверніться до бота кнопкою вище й відкрийте вкладення Shopping.shortcut.', 'Return to the bot with the button above and open the Shopping.shortcut attachment.'); tg?.HapticFeedback?.notificationOccurred('success'); }
 catch(error) { $('error').textContent = error.message; $('download').textContent = text('Повторити надсилання файлу', 'Retry sending file'); }
 finally { $('download').disabled = false; }
};
for (const button of document.querySelectorAll('button')) {
 button.addEventListener('pointerdown', () => tg?.HapticFeedback?.impactOccurred('light'));
}
