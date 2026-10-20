'use strict';
const tg = window.Telegram?.WebApp;
const demo = new URLSearchParams(location.search).get('demo') === '1';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let familyView=null;
$('family').onclick=()=>openFamily();
function inviteToken(value){const match=String(value).match(/(?:start=invite_|^)([A-Za-z0-9_-]{32})(?:$|[&#])/);return match?match[1]:'';}
async function openFamily(){
 showDialog('family-dialog');$('family-members').textContent='Wird geladen…';
 try{familyView=demo?{family_id:'demo',name:'Unsere Familie',self_id:1,owner_id:1,members:[{id:1,name:'Олена',self:true,owner:true},{id:2,name:'Іван'}],invites:[],product_count:6}:await api('/api/family');renderFamily();}
 catch(error){$('family-members').textContent=error.message;}
}
function joinForm(){return '<form id="family-join-form"><label>Einladung<input id="family-invite-input" type="text" placeholder="Einladungslink einfügen" required autocomplete="off"></label><button class="secondary full" type="submit">Einladung prüfen</button></form>';}
function wireJoin(){const form=$('family-join-form');if(form)form.onsubmit=async event=>{event.preventDefault();const token=inviteToken($('family-invite-input').value.trim());if(!token){toast('Füge den vollständigen Einladungslink ein.');return;}try{await previewInvite(token);}catch(error){toast(error.message);}};}
function renderFamily(){
 const data=familyView;$('family-dialog').querySelector('h2').textContent=data.name||'Deine Familie';
 if(!data.family_id){$('family-members').innerHTML='<p class="hint">Wähle, wie du startest: allein oder mit anderen. Einladungen sind freiwillig.</p><button id="family-solo" class="primary full">🙋 Nur für mich</button><button id="family-shared" class="secondary full">👥 Mit anderen</button>'+joinForm();$('family-solo').onclick=()=>familyAction('/api/family/create',{mode:'solo'});$('family-shared').onclick=()=>familyAction('/api/family/create',{mode:'shared'});wireJoin();return;}
 const owner=data.owner_id===data.self_id;
 $('family-members').innerHTML=(data.members.length===1?'<p class="hint">Das ist deine Liste. Nutze sie allein und lade andere später ein, wenn du möchtest.</p>':'')+data.members.map(member=>`<div class="history-row"><strong>${escape(member.name)}</strong><small>${member.self?'Du · ':''}${member.owner?'Gründer':'Mitglied'}</small></div>`).join('')+
 '<div class="family-controls"><button id="family-invite" class="primary full">Mitglied einladen</button><div id="family-new-link"></div>'+
 (data.invites.length?'<h3>Warten auf Annahme</h3>'+data.invites.map(invite=>`<div class="history-row"><small>${escape(new Date(invite.created_at).toLocaleString('de-DE'))}</small><button class="text-button" data-revoke="${escape(invite.token)}">Einladung widerrufen</button></div>`).join(''):'')+
 '<details class="manage"><summary>Verwalten</summary>'+
 `<form id="family-name-form"><label>Name der Liste<input id="family-name" value="${escape(data.name)}" maxlength="60" required></label><button class="secondary full" type="submit">Namen speichern</button></form>`+
 (owner&&data.members.length>1?`<label>Gründerrolle übertragen<select id="family-owner">${data.members.filter(m=>!m.self).map(m=>`<option value="${m.id}">${escape(m.name)}</option>`).join('')}</select></label><button id="family-owner-transfer" class="secondary full">Rolle übertragen</button>`:'')+
 joinForm()+
 '<button id="family-leave" class="secondary full">Familie verlassen</button>'+(owner?'<button id="family-delete" class="text-button danger">Familie löschen</button>':'')+'</details></div>';
 wireJoin();
 $('family-name-form').onsubmit=event=>{event.preventDefault();familyAction('/api/family/rename',{name:$('family-name').value});};
 $('family-invite').onclick=async()=>{try{if(demo){toast('In der Demo werden keine Einladungen erstellt.');return;}const result=await api('/api/family/invite',{});$('family-new-link').innerHTML=`<label>Einmal-Link<input id="family-link" readonly value="${escape(result.url)}"></label><button id="family-copy" class="secondary full">Kopieren</button><button id="family-new-revoke" class="text-button">Einladung widerrufen</button><p class="hint">Gültig, bis sie benutzt oder widerrufen wird. Eine Person kann beitreten.</p>`;$('family-new-revoke').onclick=()=>familyAction('/api/family/revoke',{token:result.token});$('family-copy').onclick=async()=>{try{await navigator.clipboard.writeText(result.url);toast('Link kopiert');}catch{$('family-link').select();toast('Link markiert. Bitte kopieren.');}};}catch(error){toast(error.message);}};
 document.querySelectorAll('[data-revoke]').forEach(button=>button.onclick=()=>askFamily('Diese Einladung widerrufen?',()=>familyAction('/api/family/revoke',{token:button.dataset.revoke})));
 $('family-leave').onclick=()=>{if(owner&&data.members.length>1){toast('Übertrage die Gründerrolle zuerst an ein anderes Mitglied.');return;}askFamily('Diese Familie verlassen?'+(data.members.length===1?' Du bist das einzige Mitglied, daher werden die Familie und ihre Liste gelöscht.':' Gemeinsame Daten bleiben für die anderen Mitglieder erhalten.'),()=>familyAction('/api/family/leave',{confirm:true}));};
 if($('family-delete'))$('family-delete').onclick=()=>askFamily(`„${data.name}“ für alle löschen? Mitglieder: ${data.members.length}, Produkte: ${data.product_count}. Die Liste ist danach nicht mehr verfügbar. Sicherungen können frühere Daten enthalten.`,()=>familyAction('/api/family/delete',{confirm:true}));
 if($('family-owner-transfer'))$('family-owner-transfer').onclick=()=>{const id=Number($('family-owner').value),member=data.members.find(m=>m.id===id);askFamily(`Gründerrolle übertragen an „${member.name}“? Diese Person kann dann die Familie löschen.`,()=>familyAction('/api/family/owner',{user_id:id,confirm:true}));};
}
function askFamily(text,action){$('family-members').innerHTML=`<p class="family-confirm">${escape(text)}</p><div class="sheet-actions"><button id="family-confirm" class="primary">Bestätigen</button><button id="family-cancel" class="secondary">Abbrechen</button></div>`;$('family-cancel').onclick=renderFamily;$('family-confirm').onclick=async()=>{const button=$('family-confirm');button.disabled=true;try{await action();}catch(error){toast(error.message);}finally{if(button.isConnected)button.disabled=false;}};}
async function familyAction(path,data){if(demo){toast('In der Demo werden Änderungen nicht gespeichert.');renderFamily();return;}try{await api(path,data);toast('Fertig');await load();if(path==='/api/family/create'&&data.mode==='solo'){closeDialogs();}else await openFamily();}catch(error){toast(error.message);await openFamily();}}
async function previewInvite(token){
 if(demo){toast('Einladungen gibt es im Bot.');return;}
 const preview=await api('/api/family/preview',{token});
 if(preview.already){toast('Du gehörst bereits zu dieser Familie.');await openFamily();return;}
 $('family-dialog').querySelector('h2').textContent='Einer Familie beitreten';
 let text=`${preview.inviter} lädt dich ein zu „${preview.name}».`;
 if(preview.owner_required){$('family-members').innerHTML=`<p>${escape(text)}</p><p class="hint">Übertrage die Gründerrolle, bevor du die Familie wechselst.</p><button id="family-preview-back" class="secondary full">Eigene Familie verwalten</button>`;$('family-preview-back').onclick=renderFamily;return;}
 if(preview.delete_previous)text+=' Deine bisherige Familie wird nach dem Beitritt gelöscht. Aktive Liste mit Fotos, Notizen und Kategorien übernehmen? Katalog und Verlauf werden nicht übernommen.';
 else if(preview.source_family)text+=' Du verlässt deine aktuelle Familie; ihre Daten bleiben für die anderen Mitglieder erhalten.';
 $('family-members').innerHTML=`<p class="family-confirm">${escape(text)}</p>`+(preview.can_transfer?'<button id="family-accept-transfer" class="primary full">Liste übernehmen und beitreten</button>':'')+'<button id="family-accept" class="secondary full">'+(preview.can_transfer?'Ohne Übernahme beitreten':'Beitreten')+'</button><button id="family-preview-back" class="text-button">Abbrechen</button>';
 const accept=transfer=>familyAction('/api/family/accept',{token,source_family:preview.source_family,transfer,confirm:true});
 $('family-accept').onclick=()=>accept(false);if($('family-accept-transfer'))$('family-accept-transfer').onclick=()=>accept(true);$('family-preview-back').onclick=renderFamily;
}
let state = {products: [], categories: {}, history: []}, tab = 'shopping', filter = '', selected = null, draftText = null, lastEvent = null;
let signature = '', loading = false, reloadNeeded = false, revision = 0, toastTimer;
const pending = new Set(), operations = new Map(), photos = new Map();
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const fallbackCategories = {"produce": "🥬 Obst und Gemüse", "bakery": "🍞 Brot und Backwaren", "dairy": "🥛 Milchprodukte und Eier", "meat": "🥩 Fleisch und Fisch", "pantry": "🍚 Getreide und Nudeln", "spices": "🧂 Gewürze, Soßen und Öl", "frozen": "🧊 Tiefkühl- und Fertiggerichte", "snacks": "🍫 Snacks und Süßes", "drinks": "🥤 Getränke", "cleaning": "🧽 Reinigungsmittel", "care": "🧴 Pflege und Gesundheit", "pets": "🐾 Tierbedarf", "home": "🏡 Haus und Garten", "auto": "🚗 Autozubehör", "other": "📦 Sonstiges"};
const demoData = {categories:fallbackCategories, products:[
{id:1,name:'Milch',note:'Lieblingsverpackung, 1 l',category:'dairy',active:true,photo:false},
{id:2,name:'Eier',note:'',category:'dairy',active:true,photo:false},
{id:3,name:'Kartoffeln',note:'Kaufen bei Mercadona',category:'produce',active:true,photo:false},
{id:4,name:'Mandarinen',note:'',category:'produce',active:true,photo:false},
{id:5,name:'Weichspüler',note:'Wie beim letzten Mal',category:'cleaning',active:true,photo:false},
{id:6,name:'Kaffee',note:'Entkoffeiniert',category:'drinks',active:false,photo:false}],history:[]};
function theme(){
 // Follow the user's Telegram theme: six tokens come from themeParams, the rest derive from them in CSS.
 const params=tg?.themeParams||{},root=document.documentElement.style;
 for(const [key,name] of Object.entries({bg_color:'--surface',secondary_bg_color:'--bg',text_color:'--text',hint_color:'--muted',button_color:'--accent',button_text_color:'--on-accent'})){if(params[key])root.setProperty(name,params[key]);else root.removeProperty(name);}
 // The Telegram script defines WebApp even in a plain browser; only trust its colorScheme when a real launch (initData) is present.
 document.body.classList.toggle('dark', tg?.initData?tg.colorScheme==='dark':matchMedia('(prefers-color-scheme: dark)').matches);
 document.querySelector('meta[name=theme-color]').content=params.secondary_bg_color||params.bg_color||(document.body.classList.contains('dark')?'#111216':'#f1f2f6');
 try{tg?.setHeaderColor?.(params.secondary_bg_color?'secondary_bg_color':'bg_color');tg?.setBackgroundColor?.(params.secondary_bg_color?'secondary_bg_color':'bg_color');}catch{}
 document.documentElement.style.setProperty('--safe-top',Math.max(tg?.safeAreaInset?.top||0,tg?.contentSafeAreaInset?.top||0)+'px');
 document.documentElement.style.setProperty('--safe-bottom',Math.max(tg?.safeAreaInset?.bottom||0,tg?.contentSafeAreaInset?.bottom||0)+'px');
}
theme();matchMedia('(prefers-color-scheme: dark)').addEventListener('change',theme);
if(tg){ tg.ready(); tg.expand(); tg.onEvent('themeChanged', theme); tg.onEvent('safeAreaChanged', theme); tg.onEvent('contentSafeAreaChanged', theme); tg.BackButton?.onClick(closeDialogs); }
function toast(text, undo=false){ clearTimeout(toastTimer); $('toast').querySelector('span').textContent=text; $('undo').hidden=!undo; $('toast').hidden=false; toastTimer=setTimeout(()=>{$('toast').hidden=true;},undo?12000:4500); }
async function api(path, body){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'tma '+(tg?.initData||''),...(state.family_id?{'X-Shopping-Family':state.family_id}:{}),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  const result=await response.json(); if(!response.ok) throw new Error(result.error||'Aktion konnte nicht ausgeführt werden.'); return result;
}
async function load(quiet=false){
  if(loading){reloadNeeded=true;return;} loading=true; const startedRevision=revision;
  try{const next=demo?structuredClone(demoData):await api('/api/state');if(startedRevision!==revision){reloadNeeded=true;return;}if(state.family_id&&next.family_id!==state.family_id){closeDialogs();operations.clear();pending.clear();photos.clear();selected=null;lastEvent=null;revision++;toast('Familie gewechselt');}if(next.language&&next.language!==currentLanguage){location.replace(languageURL(next.language));return;}const nextSignature=JSON.stringify(next);for(const [id,op] of operations){const product=next.products.find(p=>p.id===id);if(product)product.active=op.phase==='hidden'?op.action==='readd':op.previousActive;}state=next;if(nextSignature!==signature){signature=nextSignature;render();} $('connection').hidden=true;}
  catch(error){$('connection').hidden=false;if(!signature){$('content').innerHTML=`<div class="empty"><div class="symbol">↗</div><h2>In Telegram öffnen</h2><p>${escape(error.message)}</p><button class="primary" id="retry">Erneut versuchen</button></div>`;$('retry').onclick=()=>load();}else if(!quiet)toast(error.message);}
  finally{loading=false;if(reloadNeeded){reloadNeeded=false;queueMicrotask(()=>load(true));}}
}
function visible(){const term=$('search').value.trim().toLocaleLowerCase('de');return state.products.filter(p=>(tab==='catalog'||p.active)&&(!filter||p.category===filter)&&(!term||(p.name+' '+p.note).toLocaleLowerCase('de').includes(term)));}
function row(p){const emoji=(state.categories[p.category]||'📦').split(' ')[0];const buying=operations.get(p.id)?.action==='buy';return `<article class="product-row ${buying?'is-buying':''}" data-product="${p.id}"><button class="product-open" data-open="${p.id}" aria-label="Öffnen ${escape(p.name)}"><span class="thumb">${p.photo?`<img data-photo="${p.id}" alt="Verpackung ${escape(p.name)}">`:escape(emoji)}</span><span class="product-copy"><strong>${escape(p.name)}</strong>${p.note?`<small>${escape(p.note)}</small>`:''}</span></button>${tab==='catalog'&&p.active?'<span class="in-list">Auf der Liste</span>':`<button class="product-check ${tab==='catalog'?'add-again':''}" data-action="${p.id}" aria-label="${tab==='catalog'?'Zur Liste hinzufügen':'Gekauft'}: ${escape(p.name)}" ${pending.has(p.id)?'disabled':''} aria-pressed="${buying}">${tab==='catalog'?'＋':'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17 19 7"/></svg>'}</button>`}</article>`;}
function render(){
  $('add').hidden=!!state.onboarding||tab==='history'||tab==='more';
  if(state.onboarding){$('title').textContent='Deine Einkäufe';$('count').hidden=true;document.querySelector('.toolbar').hidden=true;$('content').innerHTML='<div class="empty"><h2>Wie möchtest du die Liste nutzen?</h2><p>Allein oder mit anderen. Starte allein und lade später jemanden ein, wenn du möchtest.</p><div class="usage-choices"><button id="onboarding-solo" class="primary">🙋 Nur für mich</button><button id="onboarding-shared" class="secondary">👥 Mit anderen</button><button id="onboarding-family" class="text-button">Ich habe eine Einladung</button></div></div>';$('onboarding-family').onclick=()=>openFamily();$('onboarding-solo').onclick=()=>familyAction('/api/family/create',{mode:'solo'});$('onboarding-shared').onclick=()=>familyAction('/api/family/create',{mode:'shared'});return;}

  photoObserver.disconnect();
  const previousRects = new Map([...document.querySelectorAll('[data-product]')].map(node=>[node.dataset.product,node.getBoundingClientRect()]));
  $('title').textContent={shopping:'Einkäufe',catalog:'Katalog',history:'Verlauf',more:'Mehr'}[tab];
  const count=state.products.filter(p=>p.active).length;
  const members=state.family_member_count||(demo?2:1);
  $('family').textContent=members===1?'👤 Meine Liste':`👥 ${members}`;
  $('count').textContent=tab==='shopping'?count:state.products.length;$('count').hidden=!(tab==='shopping'||tab==='catalog');
  document.querySelectorAll('nav button').forEach(b=>b.dataset.tab===tab?b.setAttribute('aria-current','page'):b.removeAttribute('aria-current'));
  document.querySelector('.toolbar').hidden=tab==='history'||tab==='more';
  if(tab==='more'){renderMore();return;}
  if(tab==='history'){
    const verbs={added:'hat hinzugefügt',bought:'hat gekauft',restored:'hat zurück auf die Liste gesetzt'};
    $('content').innerHTML=state.history.length?'<section class="group"><div class="products">'+state.history.map(e=>`<div class="history-row"><strong>${escape(e.product_name)}</strong><div>${escape(e.actor_name)} ${escape(verbs[e.action]||e.action)}${e.undone?' · rückgängig gemacht':''}</div><small>${escape(new Date(e.happened_at).toLocaleString('de-DE',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit',timeZone:'Europe/Lisbon'}))}</small></div>`).join('')+'</div></section>':'<div class="empty"><div class="symbol">◷</div><h2>Hier beginnt dein Verlauf</h2><p>Hier erscheinen deine Einträge und Einkäufe.</p></div>';
    return;
  }
  const available=state.products.filter(p=>tab==='catalog'||p.active);
  const keys=Object.keys(state.categories).filter(key=>available.some(p=>p.category===key));
  $('filters').innerHTML=`<button data-filter="" class="${!filter?'selected':''}" aria-pressed="${!filter}">Alle</button>`+keys.map(key=>`<button data-filter="${key}" class="${filter===key?'selected':''}" aria-pressed="${filter===key}">${escape(state.categories[key])}</button>`).join('');
  const rows=visible();
  if(!rows.length){const searching=$('search').value||filter;const complete=!searching&&tab==='shopping';$('content').innerHTML=`<div class="empty"><div class="symbol">${searching?'⌕':complete?'✓':'＋'}</div><h2>${searching?'Keine Produkte gefunden':complete?(state.products.length?'Alle gekauft':'Deine Liste ist bereit'):'Dein Katalog ist noch leer'}</h2><p>${searching?'Ändere die Suche oder wähle eine andere Kategorie.':complete?(state.products.length?'Fotos und Notizen bleiben erhalten. Produkte lassen sich schnell wieder hinzufügen.':'Füge die ersten Produkte mit der Schaltfläche unten hinzu.'):'Füge deine ersten Produkte hinzu. Sie bleiben hier für die nächsten Einkäufe.'}</p><div class="empty-actions"><button class="primary" id="empty-add">Produkte hinzufügen</button>${complete&&state.products.length?'<button class="secondary" id="empty-again">Erneut kaufen</button>':''}</div></div>`;$('empty-add').onclick=openAdd;if($('empty-again'))$('empty-again').onclick=()=>switchTab('catalog');return;}
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
async function photoURL(id){if(photos.has(id))return photos.get(id);const promise=(async()=>{const response=await fetch('/api/photo/'+id,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});if(!response.ok)throw new Error('Foto nicht verfügbar');return URL.createObjectURL(await response.blob());})();photos.set(id,promise);try{return await promise;}catch(error){photos.delete(id);throw error;}}
const photoObserver = new IntersectionObserver(entries=>{
  for(const entry of entries){if(entry.isIntersecting){photoObserver.unobserve(entry.target);loadPhoto(entry.target);}}
},{rootMargin:'150px'});
async function loadPhoto(img){try{img.src=await photoURL(Number(img.dataset.photo));}catch{img.parentElement.textContent='📷';}}
function hydratePhotos(){document.querySelectorAll('[data-photo]').forEach(img=>{if(!img.src)photoObserver.observe(img);});}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());tg?.BackButton?.hide();}
function showDialog(id){closeDialogs();$(id).showModal();tg?.BackButton?.show();}
function openProduct(id){selected=state.products.find(p=>p.id===id);if(!selected)return;$('product-name').textContent=selected.name;$('product-status').textContent=selected.active?'Auf der Einkaufsliste':'Für die nächsten Einkäufe gespeichert';$('note').value=selected.note;$('category').innerHTML=Object.entries(state.categories).map(([key,label])=>`<option value="${key}">${escape(label)}</option>`).join('');$('category').value=selected.category;$('product-action').textContent=selected.active?'Gekauft':'Zur Liste';$('product-photo').innerHTML=selected.photo?`<img class="detail-photo" data-photo="${selected.id}" alt="Verpackung ${escape(selected.name)}">`:'';$('photo-label').textContent=selected.photo?'Foto ersetzen':'Verpackungsfoto hinzufügen';$('photo-file').value='';showDialog('product-dialog');hydratePhotos();}
async function shrinkPhoto(file){
  // Phones send 3–12 MB HEIC/JPEG; re-encode to a ≤1280px JPEG so the upload fits the 5 MB limit and every client can show it.
  const bitmap=await createImageBitmap(file);const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height));
  const canvas=document.createElement('canvas');canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
  canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
  return new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.85));
}
$('photo-file').onchange=async()=>{const file=$('photo-file').files[0];if(!file||!selected)return;$('photo-upload').classList.add('busy');$('photo-label').textContent='Foto wird gespeichert…';
  try{if(demo){toast('In der Demo werden Fotos nicht gespeichert.');return;}const blob=await shrinkPhoto(file);
    const response=await fetch('/api/photo/'+selected.id,{method:'POST',headers:{Authorization:'tma '+(tg?.initData||''),'Content-Type':'image/jpeg',...(state.family_id?{'X-Shopping-Family':state.family_id}:{})},body:blob});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Foto konnte nicht hochgeladen werden');
    photos.delete(selected.id);selected.photo=true;const product=state.products.find(p=>p.id===selected.id);if(product)product.photo=true;
    $('product-photo').innerHTML=`<img class="detail-photo" data-photo="${selected.id}" alt="Verpackung ${escape(selected.name)}">`;hydratePhotos();toast('Foto gespeichert');
  }catch(error){toast(error.message);}finally{$('photo-upload').classList.remove('busy');$('photo-label').textContent=selected.photo?'Foto ersetzen':'Verpackungsfoto hinzufügen';$('photo-file').value='';}};
function openAdd(){draftText=null;$('items').value='';$('draft').hidden=true;$('add-submit').textContent='Liste prüfen';showDialog('add-dialog');}
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
    if(action==='buy'&&result.bought){lastEvent=result.event_id;toast('Gekauft. Von der Liste entfernt.',true);}
    else toast(action==='readd'?'Zur Liste hinzugefügt':'Produkt bereits gekauft');
    if(action==='buy')product.active=false;
  }catch(error){
    operations.delete(id);
    const current=state.products.find(p=>p.id===id);
    if(current)current.active=op.previousActive;
    toast('Nicht bestätigt: '+error.message);
    tg?.HapticFeedback?.notificationOccurred?.('error');
  }finally{
    revision++;operations.delete(id);pending.delete(id);render();
    // Reconcile in the background; a second round-trip never blocks the tap.
    load(true);
  }
}
$('product-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{if(demo){Object.assign(demoData.products.find(p=>p.id===selected.id),{note:$('note').value,category:$('category').value});}else await api('/api/edit',{id:selected.id,note:$('note').value,category:$('category').value});closeDialogs();toast('Änderungen gespeichert');await load();}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('product-action').onclick=()=>mutateProduct(selected.id,selected.active?'buy':'readd');
$('items').oninput=()=>{draftText=null;$('draft').hidden=true;$('add-submit').textContent='Liste prüfen';};
$('add-form').onsubmit=async event=>{event.preventDefault();const button=$('add-submit');button.disabled=true;try{const raw=$('items').value.trim();if(!raw)return;if(draftText!==raw){const result=demo?{items:raw.split(/[,\n]/).filter(Boolean).map(name=>({name:name.trim(),note:'',category:'other'}))}:await api('/api/draft',{text:raw});if(!result.items.length){toast('Gib Produktnamen ein');return;}$('draft').innerHTML='<strong>Zur Liste hinzufügen?</strong>'+result.items.map(p=>`<p>${escape(p.name)}${p.active?' · Schon auf der Liste':''}<br><small class="muted">${escape(state.categories[p.category])}${p.note?' · '+escape(p.note):''}</small></p>`).join('');$('draft').hidden=false;draftText=raw;button.textContent='Alle hinzufügen · '+result.items.length;}else{if(demo){raw.split(/[,\n]/).filter(Boolean).forEach((name,i)=>demoData.products.push({id:Date.now()+i,name:name.trim(),note:'',category:'other',active:true,photo:false}));}else await api('/api/add',{text:raw});closeDialogs();tab='shopping';filter='';$('search').value='';toast('Produkte hinzugefügt');await load();}}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('undo').onclick=async()=>{if(!lastEvent)return;const eventId=lastEvent;lastEvent=null;$('undo').disabled=true;try{if(demo){const product=demoData.products.find(p=>p.id===eventId);if(product)product.active=true;}else{const result=await api('/api/undo',{event_id:eventId});if(!result.restored){toast('Dieser Kauf wurde bereits rückgängig gemacht');return;}}toast('Zurück auf der Liste');await load();}catch(error){lastEvent=eventId;toast(error.message,true);}finally{$('undo').disabled=false;}};
$('refresh').onclick=()=>load();$('add').onclick=openAdd;$('search').oninput=render;
$('filters').onclick=event=>{const button=event.target.closest('[data-filter]');if(button){filter=button.dataset.filter;render();}};
function switchTab(next){const changed=tab!==next;tab=next;filter='';$('search').value='';render();if(changed){const button=document.querySelector(`nav button[data-tab="${tab}"]`);button.classList.remove('tab-entering');void button.offsetWidth;button.classList.add('tab-entering');setTimeout(()=>button.classList.remove('tab-entering'),250);}}
document.querySelectorAll('nav button').forEach(button=>button.onclick=()=>switchTab(button.dataset.tab));
document.querySelectorAll('.close').forEach(button=>button.onclick=closeDialogs);
document.querySelectorAll('.sheet-top').forEach(top=>{let startY=null;top.addEventListener('pointerdown',e=>{if(!e.target.closest('button'))startY=e.clientY;});top.addEventListener('pointermove',e=>{if(startY!==null&&e.clientY-startY>60){startY=null;closeDialogs();}});top.addEventListener('pointerup',()=>{startY=null;});});
document.querySelectorAll('dialog').forEach(dialog=>{dialog.addEventListener('close',()=>{if(!document.querySelector('dialog[open]'))tg?.BackButton?.hide();});dialog.onclick=event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeDialogs();}};});
$('voice').onclick=()=>{if(tg?.initData)tg.close();else toast('Sende eine Sprachnachricht im privaten Chat mit dem Bot.');};
const currentLanguage=['en','de'].includes(new URLSearchParams(location.search).get('lang'))?new URLSearchParams(location.search).get('lang'):'uk';
let isAdmin=false,helpContent=null,helpRole='c';
function languageURL(value){const url=new URL(location.href);url.searchParams.set('lang',value);return url.href;}
function languageSelect(value){return `<select id="language" aria-label="Sprache / Language"><option value="" disabled ${value?'':'selected'}>Оберіть мову / Choose language / Sprache wählen</option><option value="uk" ${value==='uk'?'selected':''}>Українська</option><option value="en" ${value==='en'?'selected':''}>English</option><option value="de" ${value==='de'?'selected':''}>Deutsch</option></select>`;}
function wireLanguage(){const select=$('language');if(!select)return;select.onchange=async()=>{select.disabled=true;try{if(!demo)await api('/api/language',{language:select.value});location.replace(languageURL(select.value));}catch(error){select.value=currentLanguage;toast(error.message);select.disabled=false;}};}
function renderMore(){
  $('content').innerHTML='<section class="group"><div class="products more-list">'+
    `<label class="more-row">🌐 <span>Sprache</span>${languageSelect(currentLanguage)}</label>`+
    '<button class="more-row" id="more-help" type="button">📖 <span>Hilfe</span><span class="chev">›</span></button>'+
    '<button class="more-row" id="more-family" type="button">👥 <span>Mitglieder</span><span class="chev">›</span></button>'+
    (isAdmin?'<button class="more-row" id="more-admin" type="button">📊 <span>Admin</span><span class="chev">›</span></button>':'')+
    '</div></section><p class="hint more-note">Hilfe im Chat: /help. Problem: /support.</p>';
  wireLanguage();$('more-help').onclick=openHelp;$('more-family').onclick=()=>openFamily();if($('more-admin'))$('more-admin').onclick=()=>location.assign('/admin?lang='+currentLanguage);
}
async function openHelp(){
  showDialog('help-dialog');
  try{helpContent=helpContent||await (await fetch('/help.json',{cache:'no-store'})).json();}catch{$('help-steps').textContent='Die Anleitung konnte nicht geladen werden. Öffne /help im Chat.';return;}
  renderHelp();
}
function renderHelp(){
  const h=helpContent[currentLanguage];$('help-creator').textContent=h.creator;$('help-invited').textContent=h.invited;
  $('help-creator').classList.toggle('selected',helpRole==='c');$('help-invited').classList.toggle('selected',helpRole==='j');
  $('help-steps').innerHTML=h.steps[helpRole].map((step,i)=>`<section class="help-step"><div class="kicker">${i+1} / 6</div><h3>${escape(step.title)}</h3><p>${escape(step.body)}</p><p class="hint">💡 ${escape(step.tip)}</p></section>`).join('');
}
$('help-creator').onclick=()=>{helpRole='c';renderHelp();};$('help-invited').onclick=()=>{helpRole='j';renderHelp();};
async function initializeLanguage(){if(demo){$('demo-banner').hidden=false;return load();}try{const preferences=await api('/api/preferences');isAdmin=!!preferences.admin;if(preferences.language&&preferences.language!==currentLanguage){location.replace(languageURL(preferences.language));return;}if(!preferences.language){document.querySelector('.toolbar').hidden=true;$('add').hidden=true;$('content').innerHTML='<div class="empty"><h2>Оберіть мову / Choose your language / Sprache wählen</h2><p class="language-choice">'+languageSelect('')+'</p></div>';wireLanguage();return;}await api('/api/session',{});await load();}catch{await load();}}
initializeLanguage();setInterval(()=>{if(!document.hidden&&signature)load(true);},5000);
