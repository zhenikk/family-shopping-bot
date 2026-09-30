'use strict';
const tg = window.Telegram?.WebApp;
const demo = new URLSearchParams(location.search).get('demo') === '1';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let state = {products: [], categories: {}, history: []}, tab = 'shopping', filter = '', selected = null, draftText = null, lastEvent = null;
let signature = '', loading = false, toastTimer;
const pending = new Set(), photos = new Map();
const fallbackCategories = {vegetables:'🥕 Овочі',fruit:'🍊 Фрукти',dairy:'🥛 Молочне та яйця',meat:'🥩 М’ясо та риба',bakery:'🍞 Хліб та випічка',pantry:'🥫 Бакалія',drinks:'🥤 Напої',frozen:'🧊 Заморожене',cleaning:'🧽 Побутова хімія',care:'🧴 Особиста гігієна',other:'📦 Інше'};
const demoData = {categories:fallbackCategories, products:[
{id:1,name:'Молоко',note:'Улюблена упаковка, 1 л',category:'dairy',active:true,photo:false},
{id:2,name:'Яйця',note:'',category:'dairy',active:true,photo:false},
{id:3,name:'Картопля',note:'Купити в Mercadona',category:'vegetables',active:true,photo:false},
{id:4,name:'Мандарини',note:'',category:'fruit',active:true,photo:false},
{id:5,name:'Кондиціонер для білизни',note:'Такий самий, як минулого разу',category:'cleaning',active:true,photo:false},
{id:6,name:'Кава',note:'Без кофеїну',category:'drinks',active:false,photo:false}],history:[]};
function theme(){
 document.body.classList.toggle('dark', tg?.colorScheme === 'dark');
 document.documentElement.style.setProperty('--safe-top',Math.max(tg?.safeAreaInset?.top||0,tg?.contentSafeAreaInset?.top||0)+'px');
 document.documentElement.style.setProperty('--safe-bottom',Math.max(tg?.safeAreaInset?.bottom||0,tg?.contentSafeAreaInset?.bottom||0)+'px');
}
if(tg){ tg.ready(); tg.expand(); theme(); tg.onEvent('themeChanged', theme); tg.onEvent('safeAreaChanged', theme); tg.onEvent('contentSafeAreaChanged', theme); tg.BackButton?.onClick(closeDialogs); }
function toast(text, undo=false){ clearTimeout(toastTimer); $('toast').querySelector('span').textContent=text; $('undo').hidden=!undo; $('toast').hidden=false; toastTimer=setTimeout(()=>{$('toast').hidden=true;},undo?12000:4500); }
async function api(path, body){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'tma '+(tg?.initData||''),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  const result=await response.json(); if(!response.ok) throw new Error(result.error||'Не вдалося виконати дію.'); return result;
}
async function load(quiet=false){
  if(loading)return; loading=true;
  try{const next=demo?structuredClone(demoData):await api('/api/state');const nextSignature=JSON.stringify(next);state=next;if(nextSignature!==signature){signature=nextSignature;render();} $('connection').textContent=demo?'● Перегляд дизайну':'● Спільний список';}
  catch(error){$('connection').textContent='○ Немає зв’язку';if(!signature){$('subtitle').textContent='Ваші дані захищені';$('content').innerHTML=`<div class="empty"><div class="symbol">↗</div><h2>Відкрийте через Telegram</h2><p>${escape(error.message)}</p><button class="primary" id="retry">Спробувати ще раз</button></div>`;$('retry').onclick=()=>load();}else if(!quiet)toast(error.message);}
  finally{loading=false;}
}
function visible(){const term=$('search').value.trim().toLocaleLowerCase('uk');return state.products.filter(p=>(tab==='catalog'||p.active)&&(!filter||p.category===filter)&&(!term||(p.name+' '+p.note).toLocaleLowerCase('uk').includes(term)));}
function row(p){const emoji=(state.categories[p.category]||'📦').split(' ')[0];return `<article class="product-row"><button class="product-open" data-open="${p.id}" aria-label="Відкрити ${escape(p.name)}"><span class="thumb">${p.photo?`<img data-photo="${p.id}" alt="Упаковка ${escape(p.name)}">`:escape(emoji)}</span><span class="product-copy"><strong>${escape(p.name)}</strong>${p.note?`<small>${escape(p.note)}</small>`:''}</span></button>${tab==='catalog'&&p.active?'<span class="in-list">У списку</span>':`<button class="product-check ${tab==='catalog'?'add-again':''}" data-action="${p.id}" aria-label="${tab==='catalog'?'Додати до списку':'Куплено'}: ${escape(p.name)}" ${pending.has(p.id)?'disabled':''}>${tab==='catalog'?'＋':''}</button>`}</article>`;}
function render(){
  $('title').textContent={shopping:'Покупки',catalog:'Наші товари',history:'Історія'}[tab];
  const count=state.products.filter(p=>p.active).length;
  $('subtitle').textContent=tab==='shopping'?`${count} у списку · спільний для вас двох`:tab==='catalog'?`${state.products.length} збережено · фото й нотатки залишаються`:'Хто купив і коли';
  document.querySelectorAll('nav button').forEach(b=>b.dataset.tab===tab?b.setAttribute('aria-current','page'):b.removeAttribute('aria-current'));
  document.querySelector('.tools').hidden=tab==='history';
  $('filters').hidden=tab==='history';
  if(tab==='history'){
    const verbs={added:'додав(ла)',bought:'купив(ла)',restored:'повернув(ла) у список'};
    $('content').innerHTML=state.history.length?'<section class="group"><div class="products">'+state.history.map(e=>`<div class="history-row"><strong>${escape(e.product_name)}</strong><div>${escape(e.actor_name)} ${escape(verbs[e.action]||e.action)}${e.undone?' · скасовано':''}</div><small>${escape(new Date(e.happened_at).toLocaleString('uk-UA',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Lisbon'}))}</small></div>`).join('')+'</div></section>':'<div class="empty"><div class="symbol">◷</div><h2>Історія попереду</h2><p>Тут з’являться ваші додавання та покупки.</p></div>';
    return;
  }
  const available=state.products.filter(p=>tab==='catalog'||p.active);
  const keys=Object.keys(state.categories).filter(key=>available.some(p=>p.category===key));
  $('filters').innerHTML=`<button data-filter="" class="${!filter?'selected':''}" aria-pressed="${!filter}">Усе</button>`+keys.map(key=>`<button data-filter="${key}" class="${filter===key?'selected':''}" aria-pressed="${filter===key}">${escape(state.categories[key])}</button>`).join('');
  const rows=visible();
  if(!rows.length){const searching=$('search').value||filter;$('content').innerHTML=`<div class="empty"><div class="symbol">${searching?'⌕':'☑'}</div><h2>${searching?'Товарів не знайдено':'Усе купили?'}</h2><p>${searching?'Змініть пошук або оберіть іншу категорію.':'Додайте те, чого бракує вдома. Фото й нотатки збережуться для наступного разу.'}</p><button class="primary" id="empty-add">Додати товари</button></div>`;$('empty-add').onclick=openAdd;return;}
  $('content').innerHTML=Object.keys(state.categories).map(key=>{const group=rows.filter(p=>p.category===key);return group.length?`<section class="group"><h2>${escape(state.categories[key])}<span>${group.length}</span></h2><div class="products">${group.map(row).join('')}</div></section>`:'';}).join('');
  document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openProduct(Number(b.dataset.open)));
  document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>mutateProduct(Number(b.dataset.action),tab==='catalog'?'readd':'buy'));
  hydratePhotos();
}
async function photoURL(id){if(photos.has(id))return photos.get(id);const promise=(async()=>{const response=await fetch('/api/photo/'+id,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});if(!response.ok)throw new Error('Фото недоступне');return URL.createObjectURL(await response.blob());})();photos.set(id,promise);try{return await promise;}catch(error){photos.delete(id);throw error;}}
function hydratePhotos(){document.querySelectorAll('[data-photo]').forEach(async img=>{try{img.src=await photoURL(Number(img.dataset.photo));}catch{img.parentElement.textContent='📷';}});}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());tg?.BackButton?.hide();}
function showDialog(id){closeDialogs();$(id).showModal();tg?.BackButton?.show();}
function openProduct(id){selected=state.products.find(p=>p.id===id);if(!selected)return;$('product-name').textContent=selected.name;$('product-status').textContent=selected.active?'У списку покупок':'Збережено для наступних покупок';$('note').value=selected.note;$('category').innerHTML=Object.entries(state.categories).map(([key,label])=>`<option value="${key}">${escape(label)}</option>`).join('');$('category').value=selected.category;$('product-action').textContent=selected.active?'Куплено':'До списку';$('product-photo').innerHTML=selected.photo?`<img class="detail-photo" data-photo="${selected.id}" alt="Упаковка ${escape(selected.name)}">`:'';$('photo-hint').hidden=selected.photo;showDialog('product-dialog');hydratePhotos();}
function openAdd(){draftText=null;$('items').value='';$('draft').hidden=true;$('add-submit').textContent='Перевірити список';showDialog('add-dialog');}
async function mutateProduct(id,action){if(pending.has(id))return;pending.add(id);render();try{let result;if(demo){const p=demoData.products.find(p=>p.id===id);p.active=action==='readd';result={bought:action==='buy',event_id:id};}else result=await api('/api/'+action,{id});if(action==='buy'&&result.bought){lastEvent=result.event_id;toast('Куплено. Прибрали зі спільного списку.',true);tg?.HapticFeedback?.notificationOccurred('success');}else toast(action==='readd'?'Додано до спільного списку':'Товар уже куплено');closeDialogs();await load();}catch(error){toast(error.message);}finally{pending.delete(id);render();}}
$('product-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{if(demo){Object.assign(demoData.products.find(p=>p.id===selected.id),{note:$('note').value,category:$('category').value});}else await api('/api/edit',{id:selected.id,note:$('note').value,category:$('category').value});closeDialogs();toast('Зміни збережено');await load();}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('product-action').onclick=()=>mutateProduct(selected.id,selected.active?'buy':'readd');
$('items').oninput=()=>{draftText=null;$('draft').hidden=true;$('add-submit').textContent='Перевірити список';};
$('add-form').onsubmit=async event=>{event.preventDefault();const button=$('add-submit');button.disabled=true;try{const raw=$('items').value.trim();if(!raw)return;if(draftText!==raw){const result=demo?{items:raw.split(/[,\n]/).filter(Boolean).map(name=>({name:name.trim(),note:'',category:'other'}))}:await api('/api/draft',{text:raw});if(!result.items.length){toast('Напишіть назви товарів');return;}$('draft').innerHTML='<strong>Додати до спільного списку?</strong>'+result.items.map(p=>`<p>${escape(p.name)}<br><small class="muted">${escape(state.categories[p.category])}${p.note?' · '+escape(p.note):''}</small></p>`).join('');$('draft').hidden=false;draftText=raw;button.textContent='Додати все · '+result.items.length;}else{if(demo){raw.split(/[,\n]/).filter(Boolean).forEach((name,i)=>demoData.products.push({id:Date.now()+i,name:name.trim(),note:'',category:'other',active:true,photo:false}));}else await api('/api/add',{text:raw});closeDialogs();tab='shopping';filter='';$('search').value='';toast('Товари додано');await load();}}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('undo').onclick=async()=>{if(!lastEvent)return;const eventId=lastEvent;lastEvent=null;$('undo').disabled=true;try{if(demo){const product=demoData.products.find(p=>p.id===eventId);if(product)product.active=true;}else{const result=await api('/api/undo',{event_id:eventId});if(!result.restored){toast('Цю покупку вже скасовано');return;}}toast('Повернуто до списку');await load();}catch(error){lastEvent=eventId;toast(error.message,true);}finally{$('undo').disabled=false;}};
$('refresh').onclick=()=>load();$('add').onclick=openAdd;$('search').oninput=render;
$('filters').onclick=event=>{const button=event.target.closest('[data-filter]');if(button){filter=button.dataset.filter;render();}};
document.querySelectorAll('nav button').forEach(button=>button.onclick=()=>{tab=button.dataset.tab;filter='';$('search').value='';render();});
document.querySelectorAll('.close').forEach(button=>button.onclick=closeDialogs);
document.querySelectorAll('dialog').forEach(dialog=>{dialog.addEventListener('close',()=>{if(!document.querySelector('dialog[open]'))tg?.BackButton?.hide();});dialog.onclick=event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeDialogs();}};});
$('voice').onclick=()=>{if(tg?.initData)tg.close();else toast('Надішліть голосове в особистий чат із ботом.');};
if(demo){$('demo-banner').hidden=false;}load();setInterval(()=>{if(!document.hidden)load(true);},5000);
