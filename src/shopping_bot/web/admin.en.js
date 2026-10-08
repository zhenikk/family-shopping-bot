'use strict';
const tg=window.Telegram?.WebApp,$=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const english=new URLSearchParams(location.search).get('lang')==='en';
const date=value=>value?new Date(value*1000).toLocaleString(english?'en-GB':'uk-UA',{timeZone:'Europe/Lisbon',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
const labels={bot_start:'Bot opened',bot_message:'Message to bot',bot_photo:'Photo sent to bot',bot_callback:'Button pressed',voice_queued:'Voice queued',voice_done:'Voice transcribed',voice_error:'Transcription error',web_session:'Mini App session',web_add:'Added via Mini App',web_buy:'Purchase action',web_edit:'Product edited',web_undo:'Purchase undone',web_family:'Family action',language:'Language changed',products_added:'Products added',purchase:'Product bought',bot_error:'Bot error',web_error:'Mini App error',poll_error:'Telegram connection error'};
let offset=0,userFilter=null,cursor=null,refreshing=false;
if(tg){tg.ready();tg.expand();}
async function api(path){const response=await fetch(path,{headers:{Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Не вдалося завантажити дані.');return result;}
function graph(data){
 const days=Number($('days').value),active=new Map(data.daily_active.map(r=>[r.day,r.count])),rows=[];
 for(let i=days-1;i>=0;i--){const day=new Date(data.generated*1000-i*86400000).toISOString().slice(0,10);rows.push({day,count:active.get(day)||0});}
 const peak=Math.max(0,...rows.map(r=>r.count)),max=Math.max(1,peak),height=170,step=940/days;
 const bars=rows.map((r,i)=>{const h=r.count/max*height;return '<rect x="'+(i*step+2)+'" y="'+(height-h+10)+'" width="'+Math.max(1,step-4)+'" height="'+h+'" rx="3"><title>'+r.day+': '+r.count+'</title></rect>';}).join('');
 $('chart').innerHTML='<svg viewBox="0 0 940 218" role="img" aria-label="Daily activity"><line x1="0" y1="180" x2="940" y2="180"/>'+bars+'<text x="0" y="206">'+rows[0].day+'</text><text x="470" y="206" text-anchor="middle">'+peak+' · maximum per day</text><text x="940" y="206" text-anchor="end">'+rows.at(-1).day+'</text></svg>';
}
async function stats(){
 const data=await api('/api/admin/stats?days='+$('days').value);
 const metrics=[['Users',data.users,'Tracked users'],['Active today',data.active['1'],'In the last 24 hours'],['Weekly active',data.active['7'],'In the last 7 days'],['Families',data.families,data.members+' members']];
 $('metrics').innerHTML=metrics.map(([label,value,hint])=>'<div class="metric"><strong>'+value.toLocaleString()+'</strong><span>'+label+'</span><small>'+escape(hint)+'</small></div>').join('');graph(data);
 const totals=[['New this week',data.new_7d],['Mini App sessions',data.totals.web_session||0],['Voice messages transcribed',data.totals.voice_done||0],['Purchases recorded',data.totals.purchase||0],['Errors in 24 hours',data.errors_24h]];
 $('totals').innerHTML=totals.map(([label,count])=>'<span><strong>'+count.toLocaleString()+'</strong>'+label+'</span>').join('');
 $('retention').textContent='Tracking started: '+date(data.started)+'. Detailed events are kept for '+data.retention_days+' days; cumulative counters remain. Historical visits are unavailable. Mini App session: one per 30 minutes. Event times: Europe/Lisbon. Message text, voice recordings, photos and tokens are not stored.';
}
async function users(){
 const result=await api('/api/admin/users?offset='+offset+'&q='+encodeURIComponent($('query').value));
 $('users').innerHTML=result.items.length?result.items.map(u=>'<tr><td><button data-user="'+u.user_id+'">'+escape(u.name||u.user_id)+'</button><small>'+escape(u.username?'@'+u.username:'')+' · '+u.user_id+'</small></td><td>'+date(u.first_seen)+'</td><td>'+date(u.last_seen)+'</td><td>'+(u.family_id?escape(u.family_id.slice(0,8)):'—')+'<small>'+escape(u.language||'—')+'</small></td></tr>').join(''):'<tr><td colspan="4">No users found</td></tr>';
 $('users-prev').disabled=offset===0;$('users-next').disabled=!result.has_more;$('users-page').textContent=result.items.length?(offset+1)+'–'+(offset+result.items.length):'0';
 document.querySelectorAll('[data-user]').forEach(b=>b.onclick=()=>{userFilter=b.dataset.user;cursor=null;$('event-filter').hidden=false;$('event-filter').innerHTML='Telegram ID: '+userFilter+' <button id="clear-user">All users</button>';$('clear-user').onclick=()=>{userFilter=null;$('event-filter').hidden=true;cursor=null;events().catch(e=>$('status').textContent=e.message);};events().catch(e=>$('status').textContent=e.message);});
}
async function events(append=false){
 const query=new URLSearchParams();if(cursor&&append)query.set('before',cursor);if(userFilter)query.set('user',userFilter);if($('errors').checked)query.set('errors','1');
 const result=await api('/api/admin/events?'+query);
 const html=result.items.map(e=>'<article class="event '+(e.status==='error'?'error':'')+'"><time>'+date(e.occurred)+'</time><div><strong>'+escape(labels[e.kind]||e.kind)+'</strong><small>'+(e.value!==1?'× '+e.value:'')+(e.duration_ms!=null?' · '+(e.duration_ms/1000).toFixed(1)+' s':'')+'</small></div><div class="actor">'+escape(e.name||'System')+'<small>'+(e.user_id||'—')+'</small></div></article>').join('');
 if(append)$('events').insertAdjacentHTML('beforeend',html);else $('events').innerHTML=html||'<p>No events yet</p>';cursor=result.next;$('events-more').hidden=!result.has_more;
}
async function refresh(){
 if(refreshing)return;refreshing=true;$('refresh').disabled=true;
 try{await Promise.all([stats(),users(),events()]);$('dashboard').hidden=false;$('denied').hidden=true;$('status').textContent='Updated: '+date(Date.now()/1000);}
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
 if(!preferences.admin){$('denied').hidden=false;$('status').textContent='Owner access only.';return;}await refresh();}
 catch(error){$('denied').hidden=false;$('status').textContent='Open /admin in the bot.';}
}start();
