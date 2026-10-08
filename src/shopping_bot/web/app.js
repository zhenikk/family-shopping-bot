'use strict';
const tg = window.Telegram?.WebApp;
const demo = new URLSearchParams(location.search).get('demo') === '1';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let familyView=null;
$('family').onclick=()=>openFamily();
function inviteToken(value){const match=String(value).match(/(?:start=invite_|^)([A-Za-z0-9_-]{32})(?:$|[&#])/);return match?match[1]:'';}
async function openFamily(){
 showDialog('family-dialog');$('family-members').textContent='Завантажуємо…';
 try{familyView=demo?{family_id:'demo',name:'Наша сім’я',self_id:1,owner_id:1,members:[{id:1,name:'Олена',self:true,owner:true},{id:2,name:'Іван'}],invites:[],product_count:6}:await api('/api/family');renderFamily();}
 catch(error){$('family-members').textContent=error.message;}
}
function joinForm(){return '<form id="family-join-form"><label>Запрошення<input id="family-invite-input" type="text" placeholder="Вставте посилання" required autocomplete="off"></label><button class="secondary full" type="submit">Перевірити запрошення</button></form>';}
function wireJoin(){const form=$('family-join-form');if(form)form.onsubmit=async event=>{event.preventDefault();const token=inviteToken($('family-invite-input').value.trim());if(!token){toast('Вставте повне посилання запрошення.');return;}try{await previewInvite(token);}catch(error){toast(error.message);}};}
function renderFamily(){
 const data=familyView;$('family-dialog').querySelector('h2').textContent=data.name||'Ваша сім’я';
 if(!data.family_id){$('family-members').innerHTML='<p class="hint">Створіть спільний список або приєднайтеся до близьких.</p><button id="family-create" class="primary full">Створити сім’ю</button>'+joinForm();$('family-create').onclick=()=>familyAction('/api/family/create',{});wireJoin();return;}
 const owner=data.owner_id===data.self_id;
 $('family-members').innerHTML=data.members.map(member=>`<div class="history-row"><strong>${escape(member.name)}</strong><small>${member.self?'Ви · ':''}${member.owner?'Засновник':'Учасник'}</small></div>`).join('')+
 '<div class="family-controls"><button id="family-invite" class="primary full">Запросити учасника</button><div id="family-new-link"></div>'+joinForm()+
 `<form id="family-name-form"><label>Назва сім’ї<input id="family-name" value="${escape(data.name)}" maxlength="60" required></label><button class="secondary full" type="submit">Зберегти назву</button></form>`+
 (data.invites.length?'<h3>Активні запрошення</h3>'+data.invites.map(invite=>`<div class="history-row"><small>${escape(new Date(invite.created_at).toLocaleString('uk-UA'))}</small><button class="text-button" data-revoke="${escape(invite.token)}">Скасувати запрошення</button></div>`).join(''):'')+
 (owner&&data.members.length>1?`<label>Передати роль засновника<select id="family-owner">${data.members.filter(m=>!m.self).map(m=>`<option value="${m.id}">${escape(m.name)}</option>`).join('')}</select></label><button id="family-owner-transfer" class="secondary full">Передати роль</button>`:'')+
 '<button id="family-leave" class="secondary full">Вийти із сім’ї</button>'+(owner?'<button id="family-delete" class="text-button danger">Видалити сім’ю</button>':'')+'</div>';
 wireJoin();
 $('family-name-form').onsubmit=event=>{event.preventDefault();familyAction('/api/family/rename',{name:$('family-name').value});};
 $('family-invite').onclick=async()=>{try{if(demo){toast('У демонстрації запрошення не створюються.');return;}const result=await api('/api/family/invite',{});$('family-new-link').innerHTML=`<label>Одноразове посилання<input id="family-link" readonly value="${escape(result.url)}"></label><button id="family-copy" class="secondary full">Копіювати</button><button id="family-new-revoke" class="text-button">Скасувати запрошення</button><p class="hint">До використання або скасування. Лише для одного приєднання.</p>`;$('family-new-revoke').onclick=()=>familyAction('/api/family/revoke',{token:result.token});$('family-copy').onclick=async()=>{try{await navigator.clipboard.writeText(result.url);toast('Посилання скопійовано');}catch{$('family-link').select();toast('Посилання виділено — скопіюйте його.');}};}catch(error){toast(error.message);}};
 document.querySelectorAll('[data-revoke]').forEach(button=>button.onclick=()=>askFamily('Скасувати це запрошення?',()=>familyAction('/api/family/revoke',{token:button.dataset.revoke})));
 $('family-leave').onclick=()=>{if(owner&&data.members.length>1){toast('Спочатку передайте роль засновника іншому учаснику.');return;}askFamily('Вийти із сім’ї?'+(data.members.length===1?' Ви єдиний учасник, тому сім’ю та її список буде видалено.':' Спільні дані залишаться іншим учасникам.'),()=>familyAction('/api/family/leave',{confirm:true}));};
 if($('family-delete'))$('family-delete').onclick=()=>askFamily(`Видалити «${data.name}» для всіх? Учасників: ${data.members.length}, товарів: ${data.product_count}. Список стане недоступним. Резервні копії можуть містити попередні дані.`,()=>familyAction('/api/family/delete',{confirm:true}));
 if($('family-owner-transfer'))$('family-owner-transfer').onclick=()=>{const id=Number($('family-owner').value),member=data.members.find(m=>m.id===id);askFamily(`Передати роль засновника учаснику «${member.name}»? Він зможе видаляти сім’ю.`,()=>familyAction('/api/family/owner',{user_id:id,confirm:true}));};
}
function askFamily(text,action){$('family-members').innerHTML=`<p class="family-confirm">${escape(text)}</p><div class="sheet-actions"><button id="family-confirm" class="primary">Підтвердити</button><button id="family-cancel" class="secondary">Скасувати</button></div>`;$('family-cancel').onclick=renderFamily;$('family-confirm').onclick=async()=>{const button=$('family-confirm');button.disabled=true;try{await action();}catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}};}
async function familyAction(path,data){if(demo){toast('У демонстрації зміни не зберігаються.');renderFamily();return;}try{await api(path,data);toast('Готово');await load();await openFamily();}catch(error){toast(error.message);await openFamily();}}
async function previewInvite(token){
 if(demo){toast('Запрошення доступні в боті.');return;}
 const preview=await api('/api/family/preview',{token});
 if(preview.already){toast('Ви вже в цій сім’ї.');await openFamily();return;}
 $('family-dialog').querySelector('h2').textContent='Приєднання до сім’ї';
 let text=`${preview.inviter} запрошує до «${preview.name}».`;
 if(preview.owner_required){$('family-members').innerHTML=`<p>${escape(text)}</p><p class="hint">Перед переходом передайте роль засновника іншому учаснику.</p><button id="family-preview-back" class="secondary full">Керувати своєю сім’єю</button>`;$('family-preview-back').onclick=renderFamily;return;}
 if(preview.delete_previous)text+=' Попередня сім’я буде видалена після успішного переходу. Перенести активний список із фото, нотатками й категоріями? Каталог куплених товарів та історія не переносяться.';
 else if(preview.source_family)text+=' Ви вийдете з поточної сім’ї; її дані залишаться учасникам.';
 $('family-members').innerHTML=`<p class="family-confirm">${escape(text)}</p>`+(preview.can_transfer?'<button id="family-accept-transfer" class="primary full">Перенести список й приєднатися</button>':'')+'<button id="family-accept" class="secondary full">'+(preview.can_transfer?'Не переносити й приєднатися':'Приєднатися')+'</button><button id="family-preview-back" class="text-button">Скасувати</button>';
 const accept=transfer=>familyAction('/api/family/accept',{token,source_family:preview.source_family,transfer,confirm:true});
 $('family-accept').onclick=()=>accept(false);if($('family-accept-transfer'))$('family-accept-transfer').onclick=()=>accept(true);$('family-preview-back').onclick=renderFamily;
}
let state = {products: [], categories: {}, history: []}, tab = 'shopping', filter = '', selected = null, draftText = null, lastEvent = null;
let signature = '', loading = false, reloadNeeded = false, revision = 0, toastTimer;
const pending = new Set(), operations = new Map(), photos = new Map();
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
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
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'tma '+(tg?.initData||''),...(state.family_id?{'X-Shopping-Family':state.family_id}:{}),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  const result=await response.json(); if(!response.ok) throw new Error(result.error||'Не вдалося виконати дію.'); return result;
}
async function load(quiet=false){
  if(loading){reloadNeeded=true;return;} loading=true; const startedRevision=revision;
  try{const next=demo?structuredClone(demoData):await api('/api/state');if(startedRevision!==revision){reloadNeeded=true;return;}if(state.family_id&&next.family_id!==state.family_id){closeDialogs();operations.clear();pending.clear();photos.clear();selected=null;lastEvent=null;revision++;toast('Сім’ю переключено');}if(next.language&&next.language!==currentLanguage){location.replace(languageURL(next.language));return;}const nextSignature=JSON.stringify(next);for(const [id,op] of operations){const product=next.products.find(p=>p.id===id);if(product)product.active=op.phase==='hidden'?op.action==='readd':op.previousActive;}state=next;if(nextSignature!==signature){signature=nextSignature;render();} $('connection').textContent=demo?'● Перегляд дизайну':'● Спільний список';}
  catch(error){$('connection').textContent='○ Немає зв’язку';if(!signature){$('subtitle').textContent='Ваші дані захищені';$('content').innerHTML=`<div class="empty"><div class="symbol">↗</div><h2>Відкрийте через Telegram</h2><p>${escape(error.message)}</p><button class="primary" id="retry">Спробувати ще раз</button></div>`;$('retry').onclick=()=>load();}else if(!quiet)toast(error.message);}
  finally{loading=false;if(reloadNeeded){reloadNeeded=false;queueMicrotask(()=>load(true));}}
}
function visible(){const term=$('search').value.trim().toLocaleLowerCase('uk');return state.products.filter(p=>(tab==='catalog'||p.active)&&(!filter||p.category===filter)&&(!term||(p.name+' '+p.note).toLocaleLowerCase('uk').includes(term)));}
function row(p){const emoji=(state.categories[p.category]||'📦').split(' ')[0];const buying=operations.get(p.id)?.action==='buy';return `<article class="product-row ${buying?'is-buying':''}" data-product="${p.id}"><button class="product-open" data-open="${p.id}" aria-label="Відкрити ${escape(p.name)}"><span class="thumb">${p.photo?`<img data-photo="${p.id}" alt="Упаковка ${escape(p.name)}">`:escape(emoji)}</span><span class="product-copy"><strong>${escape(p.name)}</strong>${p.note?`<small>${escape(p.note)}</small>`:''}</span></button>${tab==='catalog'&&p.active?'<span class="in-list">У списку</span>':`<button class="product-check ${tab==='catalog'?'add-again':''}" data-action="${p.id}" aria-label="${tab==='catalog'?'Додати до списку':'Куплено'}: ${escape(p.name)}" ${pending.has(p.id)?'disabled':''} aria-pressed="${buying}">${tab==='catalog'?'＋':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17 19 7"/></svg>'}</button>`}</article>`;}
function render(){
  if(state.onboarding){$('title').textContent='Наші покупки';$('subtitle').textContent='Один список для вашої сім’ї';document.querySelector('.tools').hidden=true;$('filters').hidden=true;$('content').innerHTML='<div class="empty"><h2>Почнімо зі сім’ї</h2><p>Створіть сім’ю або прийміть запрошення близьких.</p><button id="onboarding-family" class="primary">Створити або приєднатися</button></div>';$('onboarding-family').onclick=()=>openFamily();return;}

  photoObserver.disconnect();
  const previousRects = new Map([...document.querySelectorAll('[data-product]')].map(node=>[node.dataset.product,node.getBoundingClientRect()]));
  $('title').textContent={shopping:'Покупки',catalog:'Наші товари',history:'Історія'}[tab];
  const count=state.products.filter(p=>p.active).length;
  $('subtitle').textContent=tab==='shopping'?`${count} у списку · спільний для сім’ї`:tab==='catalog'?`${state.products.length} збережено · фото й нотатки залишаються`:'Хто купив і коли';
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
  if(!rows.length){const searching=$('search').value||filter;const complete=!searching&&tab==='shopping';$('content').innerHTML=`<div class="empty"><div class="symbol">${searching?'⌕':complete?'✓':'＋'}</div><h2>${searching?'Товарів не знайдено':complete?'Усе куплено':'Ваш каталог ще порожній'}</h2><p>${searching?'Змініть пошук або оберіть іншу категорію.':complete?'Фото й нотатки збережені. Можна швидко додати товари знову.':'Додайте перші товари — вони залишаться тут для наступних покупок.'}</p><div class="empty-actions"><button class="primary" id="empty-add">Додати товари</button>${complete&&state.products.length?'<button class="secondary" id="empty-again">Купити знову</button>':''}</div></div>`;$('empty-add').onclick=openAdd;if($('empty-again'))$('empty-again').onclick=()=>switchTab('catalog');return;}
  $('content').innerHTML=Object.keys(state.categories).map(key=>{const group=rows.filter(p=>p.category===key);return group.length?`<section class="group"><h2>${escape(state.categories[key])}<span>${group.length}</span></h2><div class="products">${group.map(row).join('')}</div></section>`:'';}).join('');
  document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openProduct(Number(b.dataset.open)));
  document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>mutateProduct(Number(b.dataset.action),tab==='catalog'?'readd':'buy'));
  hydratePhotos();
  if(!reducedMotion.matches){
    document.querySelectorAll('[data-product]').forEach(node=>{
      const before=previousRects.get(node.dataset.product);
      if(before){const delta=before.top-node.getBoundingClientRect().top;if(Math.abs(delta)>1)node.animate([{transform:`translateY(${delta}px)`},{transform:'translateY(0)'}],{duration:240,easing:'cubic-bezier(.2,.8,.2,1)'});}
    });
  }
}
async function photoURL(id){if(photos.has(id))return photos.get(id);const promise=(async()=>{const response=await fetch('/api/photo/'+id,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});if(!response.ok)throw new Error('Фото недоступне');return URL.createObjectURL(await response.blob());})();photos.set(id,promise);try{return await promise;}catch(error){photos.delete(id);throw error;}}
const photoObserver = new IntersectionObserver(entries=>{
  for(const entry of entries){if(entry.isIntersecting){photoObserver.unobserve(entry.target);loadPhoto(entry.target);}}
},{rootMargin:'150px'});
async function loadPhoto(img){try{img.src=await photoURL(Number(img.dataset.photo));}catch{img.parentElement.textContent='📷';}}
function hydratePhotos(){document.querySelectorAll('[data-photo]').forEach(img=>{if(!img.src)photoObserver.observe(img);});}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());tg?.BackButton?.hide();}
function showDialog(id){closeDialogs();$(id).showModal();tg?.BackButton?.show();}
function openProduct(id){selected=state.products.find(p=>p.id===id);if(!selected)return;$('product-name').textContent=selected.name;$('product-status').textContent=selected.active?'У списку покупок':'Збережено для наступних покупок';$('note').value=selected.note;$('category').innerHTML=Object.entries(state.categories).map(([key,label])=>`<option value="${key}">${escape(label)}</option>`).join('');$('category').value=selected.category;$('product-action').textContent=selected.active?'Куплено':'До списку';$('product-photo').innerHTML=selected.photo?`<img class="detail-photo" data-photo="${selected.id}" alt="Упаковка ${escape(selected.name)}">`:'';$('photo-hint').hidden=selected.photo;showDialog('product-dialog');hydratePhotos();}
function openAdd(){draftText=null;$('items').value='';$('draft').hidden=true;$('add-submit').textContent='Перевірити список';showDialog('add-dialog');}
async function purchaseMotion(id, op){
  if(!reducedMotion.matches){
    await wait(200);
    if(operations.get(id)!==op)return;
    const node=document.querySelector(`[data-product="${id}"]`);
    if(node){await node.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:'translateX(18px)'}],{duration:150,easing:'ease-in',fill:'forwards'}).finished.catch(()=>{});}
  }
  if(operations.get(id)!==op)return;
  op.phase='hidden';
  const product=state.products.find(p=>p.id===id);
  if(product)product.active=false;
  render();
}
async function mutateProduct(id,action){
  if(pending.has(id))return;
  const product=state.products.find(p=>p.id===id);
  if(!product)return;
  const op={action,phase:action==='buy'?'checking':'hidden',previousActive:product.active};
  revision++;operations.set(id,op);pending.add(id);
  if(action==='readd')product.active=true;
  render();
  closeDialogs();
  tg?.HapticFeedback?.impactOccurred?.('light');
  const motion=action==='buy'?purchaseMotion(id,op):Promise.resolve();
  try{
    let result;
    if(demo){demoData.products.find(p=>p.id===id).active=action==='readd';result={bought:action==='buy',event_id:id};}
    else result=await api('/api/'+action,{id});
    await motion;
    if(action==='buy'&&result.bought){lastEvent=result.event_id;toast('Куплено. Прибрали зі спільного списку.',true);}
    else toast(action==='readd'?'Додано до спільного списку':'Товар уже куплено');
    if(action==='buy')product.active=false;
  }catch(error){
    operations.delete(id);
    const current=state.products.find(p=>p.id===id);
    if(current)current.active=op.previousActive;
    toast('Не підтверджено: '+error.message);
    tg?.HapticFeedback?.notificationOccurred?.('error');
  }finally{
    revision++;operations.delete(id);pending.delete(id);render();
    // Reconcile in the background; a second round-trip never blocks the tap.
    load(true);
  }
}
$('product-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{if(demo){Object.assign(demoData.products.find(p=>p.id===selected.id),{note:$('note').value,category:$('category').value});}else await api('/api/edit',{id:selected.id,note:$('note').value,category:$('category').value});closeDialogs();toast('Зміни збережено');await load();}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('product-action').onclick=()=>mutateProduct(selected.id,selected.active?'buy':'readd');
$('items').oninput=()=>{draftText=null;$('draft').hidden=true;$('add-submit').textContent='Перевірити список';};
$('add-form').onsubmit=async event=>{event.preventDefault();const button=$('add-submit');button.disabled=true;try{const raw=$('items').value.trim();if(!raw)return;if(draftText!==raw){const result=demo?{items:raw.split(/[,\n]/).filter(Boolean).map(name=>({name:name.trim(),note:'',category:'other'}))}:await api('/api/draft',{text:raw});if(!result.items.length){toast('Напишіть назви товарів');return;}$('draft').innerHTML='<strong>Додати до спільного списку?</strong>'+result.items.map(p=>`<p>${escape(p.name)}${p.active?' · Уже в списку':''}<br><small class="muted">${escape(state.categories[p.category])}${p.note?' · '+escape(p.note):''}</small></p>`).join('');$('draft').hidden=false;draftText=raw;button.textContent='Додати все · '+result.items.length;}else{if(demo){raw.split(/[,\n]/).filter(Boolean).forEach((name,i)=>demoData.products.push({id:Date.now()+i,name:name.trim(),note:'',category:'other',active:true,photo:false}));}else await api('/api/add',{text:raw});closeDialogs();tab='shopping';filter='';$('search').value='';toast('Товари додано');await load();}}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('undo').onclick=async()=>{if(!lastEvent)return;const eventId=lastEvent;lastEvent=null;$('undo').disabled=true;try{if(demo){const product=demoData.products.find(p=>p.id===eventId);if(product)product.active=true;}else{const result=await api('/api/undo',{event_id:eventId});if(!result.restored){toast('Цю покупку вже скасовано');return;}}toast('Повернуто до списку');await load();}catch(error){lastEvent=eventId;toast(error.message,true);}finally{$('undo').disabled=false;}};
$('refresh').onclick=()=>load();$('add').onclick=openAdd;$('search').oninput=render;
$('filters').onclick=event=>{const button=event.target.closest('[data-filter]');if(button){filter=button.dataset.filter;render();}};
function switchTab(next){const changed=tab!==next;tab=next;filter='';$('search').value='';render();if(changed){const button=document.querySelector(`nav button[data-tab="${tab}"]`);button.classList.remove('tab-entering');void button.offsetWidth;button.classList.add('tab-entering');setTimeout(()=>button.classList.remove('tab-entering'),250);}}
document.querySelectorAll('nav button').forEach(button=>button.onclick=()=>switchTab(button.dataset.tab));
document.querySelectorAll('.close').forEach(button=>button.onclick=closeDialogs);
document.querySelectorAll('dialog').forEach(dialog=>{dialog.addEventListener('close',()=>{if(!document.querySelector('dialog[open]'))tg?.BackButton?.hide();});dialog.onclick=event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeDialogs();}};});
$('voice').onclick=()=>{if(tg?.initData)tg.close();else toast('Надішліть голосове в особистий чат із ботом.');};
const currentLanguage=new URLSearchParams(location.search).get('lang')==='en'?'en':'uk';
$('language').value=currentLanguage;
function languageURL(value){const url=new URL(location.href);url.searchParams.set('lang',value);return url.href;}
$('language').onchange=async()=>{const select=$('language');select.disabled=true;try{if(!demo)await api('/api/language',{language:select.value});location.replace(languageURL(select.value));}catch(error){select.value=currentLanguage;toast(error.message);select.disabled=false;}};
async function initializeLanguage(){if(demo){$('demo-banner').hidden=false;return load();}try{const preferences=await api('/api/preferences');if(preferences.admin){const link=document.createElement('button');link.textContent='📊 Admin';link.className='secondary';link.onclick=()=>location.assign('/admin?lang='+currentLanguage);$('family').after(link);}if(preferences.language&&preferences.language!==currentLanguage){location.replace(languageURL(preferences.language));return;}if(!preferences.language){$('language').value='';$('subtitle').textContent='Оберіть мову / Choose your language';$('content').innerHTML='<div class="empty"><h2>Оберіть мову / Choose your language</h2><p>Українська або English — оберіть у меню 🌐</p></div>';return;}await api('/api/session',{});await load();}catch{await load();}}
initializeLanguage();setInterval(()=>{if(!document.hidden&&signature)load(true);},5000);
