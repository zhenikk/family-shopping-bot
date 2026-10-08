'use strict';
const tg=window.Telegram?.WebApp,$=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const english=new URLSearchParams(location.search).get('lang')==='en';
const date=value=>value?new Date(value*1000).toLocaleString(english?'en-GB':'uk-UA',{timeZone:'Europe/Lisbon',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
const labels={bot_start:'Запуск бота',bot_message:'Повідомлення боту',bot_photo:'Фото в боті',bot_callback:'Натискання кнопки',voice_queued:'Голосове в черзі',voice_done:'Голосове розпізнано',voice_error:'Помилка розпізнавання',web_session:'Вхід у Mini App',web_add:'Додавання в Mini App',web_buy:'Позначення покупки',web_edit:'Редагування товару',web_undo:'Скасування покупки',web_family:'Керування сім’єю',language:'Зміна мови',products_added:'Товари додано',purchase:'Товар куплено',bot_error:'Помилка бота',web_error:'Помилка Mini App',poll_error:'Помилка з’єднання з Telegram'};
let offset=0,userFilter=null,cursor=null,refreshing=false;
if(tg){tg.ready();tg.expand();}
async function api(path){const response=await fetch(path,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Не вдалося завантажити дані.');return result;}
function graph(data){
 const days=Number($('days').value),active=new Map(data.daily_active.map(r=>[r.day,r.count])),rows=[];
 for(let i=days-1;i>=0;i--){const day=new Date(data.generated*1000-i*86400000).toISOString().slice(0,10);rows.push({day,count:active.get(day)||0});}
 const peak=Math.max(0,...rows.map(r=>r.count)),max=Math.max(1,peak),height=130,step=940/days;
 const bars=rows.map((r,i)=>{const h=r.count/max*height;return '<rect x="'+(i*step+2)+'" y="'+(height-h+10)+'" width="'+Math.max(1,step-4)+'" height="'+h+'" rx="3"><title>'+r.day+': '+r.count+'</title></rect>';}).join('');
 $('chart').innerHTML='<svg viewBox="0 0 940 178" role="img" aria-label="Щоденна активність"><line x1="0" y1="140" x2="940" y2="140"/>'+bars+'<text x="0" y="166">'+rows[0].day+'</text><text x="470" y="166" text-anchor="middle">'+peak+' · максимум за день</text><text x="940" y="166" text-anchor="end">'+rows.at(-1).day+'</text></svg>';
}
async function stats(){
 const data=await api('/api/admin/stats?days='+$('days').value);
 const metrics=[['Користувачі',data.users,'Зареєстровані в журналі'],['Активні сьогодні',data.active['1'],'За останні 24 години'],['Активні за тиждень',data.active['7'],'За останні 7 днів'],['Сім’ї',data.families,data.members+' учасників']];
 $('metrics').innerHTML=metrics.map(([label,value,hint])=>'<div class="metric"><strong>'+value.toLocaleString()+'</strong><span>'+label+'</span><small>'+escape(hint)+'</small></div>').join('');graph(data);
 const totals=[['Нові за тиждень',data.new_7d],['Входи у Mini App',data.totals.web_session||0],['Голосові розпізнано',data.totals.voice_done||0],['Покупок відмічено',data.totals.purchase||0],['Помилки за 24 години',data.errors_24h]];
 $('totals').innerHTML=totals.map(([label,count])=>'<span><strong>'+count.toLocaleString()+'</strong>'+label+'</span>').join('');
 $('retention').textContent='Збір подій розпочато: '+date(data.started)+'. Детальний журнал зберігається '+data.retention_days+' днів, сумарні лічильники — надалі. Історичні входи не відновлюються. Сесія Mini App: один вхід на 30 хвилин. Час подій — Europe/Lisbon. Тексти повідомлень, голосові, фото та токени не записуються.';
}
async function users(){
 const result=await api('/api/admin/users?offset='+offset+'&q='+encodeURIComponent($('query').value));
 $('users').innerHTML=result.items.length?result.items.map(u=>'<tr><td><button data-user="'+u.user_id+'">'+escape(u.name||u.user_id)+'</button><small>'+escape(u.username?'@'+u.username:'')+' · '+u.user_id+'</small></td><td data-label="Перша поява">'+date(u.first_seen)+'</td><td data-label="Остання активність">'+date(u.last_seen)+'</td><td>'+(u.family_id?escape(u.family_id.slice(0,8)):'—')+'<small>'+escape(u.language||'—')+'</small></td></tr>').join(''):'<tr><td colspan="4">Користувачів не знайдено</td></tr>';
 $('users-prev').disabled=offset===0;$('users-next').disabled=!result.has_more;$('users-page').textContent=result.items.length?(offset+1)+'–'+(offset+result.items.length):'0';
 document.querySelectorAll('[data-user]').forEach(b=>b.onclick=()=>{userFilter=b.dataset.user;cursor=null;$('event-filter').hidden=false;$('event-filter').innerHTML='Telegram ID: '+userFilter+' <button id="clear-user">Усі користувачі</button>';$('clear-user').onclick=()=>{userFilter=null;$('event-filter').hidden=true;cursor=null;events().catch(e=>$('status').textContent=e.message);};events().catch(e=>$('status').textContent=e.message);});
}
async function events(append=false){
 const query=new URLSearchParams();if(cursor&&append)query.set('before',cursor);if(userFilter)query.set('user',userFilter);if($('errors').checked)query.set('errors','1');
 const result=await api('/api/admin/events?'+query);
 const html=result.items.map(e=>'<article class="event '+(e.status==='error'?'error':'')+'"><time>'+date(e.occurred)+'</time><div><strong>'+escape(labels[e.kind]||e.kind)+'</strong><small>'+(e.value!==1?'× '+e.value:'')+(e.duration_ms!=null?' · '+(e.duration_ms/1000).toFixed(1)+' s':'')+'</small></div><div class="actor">'+escape(e.name||'Система')+'<small>'+(e.user_id||'—')+'</small></div></article>').join('');
 if(append)$('events').insertAdjacentHTML('beforeend',html);else $('events').innerHTML=html||'<p>Подій поки немає</p>';cursor=result.next;$('events-more').hidden=!result.has_more;
}
async function refresh(){
 if(refreshing)return;refreshing=true;$('refresh').disabled=true;
 try{await Promise.all([stats(),users(),events()]);$('dashboard').hidden=false;$('denied').hidden=true;$('status').textContent='Оновлено: '+date(Date.now()/1000);}
 catch(error){$('status').textContent=error.message;if($('dashboard').hidden)$('denied').hidden=false;}
 finally{refreshing=false;$('refresh').disabled=false;}
}
$('refresh').onclick=refresh;$('days').onchange=()=>stats().catch(e=>$('status').textContent=e.message);
$('user-search').onsubmit=e=>{e.preventDefault();offset=0;users().catch(e=>$('status').textContent=e.message);};
$('users-prev').onclick=()=>{offset=Math.max(0,offset-50);users().catch(e=>$('status').textContent=e.message);};
$('users-next').onclick=()=>{offset+=50;users().catch(e=>$('status').textContent=e.message);};
$('errors').onchange=()=>{cursor=null;events().catch(e=>$('status').textContent=e.message);};
$('events-more').onclick=async()=>{const button=$('events-more');button.disabled=true;try{await events(true);}catch(e){$('status').textContent=e.message;}finally{button.disabled=false;}};
async function start(){
 try{const preferences=await api('/api/preferences');if(preferences.language&&(preferences.language==='en')!==english){const url=new URL(location.href);url.searchParams.set('lang',preferences.language);location.replace(url.href);return;}
 if(!preferences.admin){$('denied').hidden=false;$('status').textContent='Адмінка доступна лише власнику.';return;}await refresh();}
 catch(error){$('denied').hidden=false;$('status').textContent='Відкрийте /admin у боті.';}
}start();
