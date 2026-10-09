'use strict';
const tg=window.Telegram?.WebApp,$=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const english=new URLSearchParams(location.search).get('lang')==='en';
const date=value=>value?new Date(value*1000).toLocaleString(english?'en-GB':'uk-UA',{timeZone:'Europe/Lisbon',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
const labels={bot_start:'Bot opened',bot_message:'Message to bot',bot_photo:'Photo sent to bot',bot_callback:'Button pressed',voice_queued:'Voice queued',voice_done:'Voice transcribed',voice_error:'Transcription error',web_session:'Mini App session',web_add:'Added via Mini App',web_buy:'Purchase action',web_edit:'Product edited',web_undo:'Purchase undone',web_family:'Family action',language:'Language changed',products_added:'Products added',purchase:'Product bought',bot_error:'Bot error',web_error:'Mini App error',poll_error:'Telegram connection error'};
let offset=0,userFilter=null,cursor=null,refreshing=false;
if(tg){tg.ready();tg.expand();}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',body:body===undefined?undefined:JSON.stringify(body),headers:{'Content-Type':'application/json',Authorization:'tma '+(tg?.initData||'')},cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Не вдалося завантажити дані.');return result;}
function graph(data){
 const days=Number($('days').value),active=new Map(data.daily_active.map(r=>[r.day,r.count])),rows=[];
 for(let i=days-1;i>=0;i--){const day=new Date(data.generated*1000-i*86400000).toISOString().slice(0,10);rows.push({day,count:active.get(day)||0});}
 const peak=Math.max(0,...rows.map(r=>r.count)),max=Math.max(1,peak),height=130,step=940/days;
 const bars=rows.map((r,i)=>{const h=r.count/max*height;return '<rect x="'+(i*step+2)+'" y="'+(height-h+10)+'" width="'+Math.max(1,step-4)+'" height="'+h+'" rx="3"><title>'+r.day+': '+r.count+'</title></rect>';}).join('');
 $('chart').innerHTML='<svg viewBox="0 0 940 178" role="img" aria-label="Daily activity"><line x1="0" y1="140" x2="940" y2="140"/>'+bars+'<text x="0" y="166">'+rows[0].day+'</text><text x="470" y="166" text-anchor="middle">'+peak+' · maximum per day</text><text x="940" y="166" text-anchor="end">'+rows.at(-1).day+'</text></svg>';
}
async function stats(){
 const data=await api('/api/admin/stats?days='+$('days').value);
 $('release').textContent='Version: '+data.release.version+' · Git: '+data.release.commit.slice(0,12);
 const selected=$('release-filter').value; $('release-filter').innerHTML='<option value="">All releases</option>'+data.releases.map(r=>'<option value="'+escape(JSON.stringify([r.version,r.commit_sha]))+'">'+escape(r.version)+' · '+escape(r.commit_sha.slice(0,12))+'</option>').join('');$('release-filter').value=selected;
 const metrics=[['Users',data.users,'Tracked users'],['Active today',data.active['1'],'In the last 24 hours'],['Weekly active',data.active['7'],'In the last 7 days'],['Families',data.families,data.members+' members']];
 const q=data.voice_queue;if(q){metrics.push(['Voice queue',q.waiting,'Active: '+q.active+' · 1 worker']);metrics.push(['Wait p95',q.wait.p95_ms===null?0:Math.round(q.wait.p95_ms/1000),'Seconds · last 512 jobs since restart']);metrics.push(['Processing p95',q.processing.p95_ms===null?0:Math.round(q.processing.p95_ms/1000),'Seconds · full voice workflow']);}
 $('metrics').innerHTML=metrics.map(([label,value,hint])=>'<div class="metric"><strong>'+value.toLocaleString()+'</strong><span>'+label+'</span><small>'+escape(hint)+'</small></div>').join('');graph(data);
 const totals=[['New this week',data.new_7d],['Mini App sessions',data.totals.web_session||0],['Voice messages transcribed',data.totals.voice_done||0],['Purchases recorded',data.totals.purchase||0],['Errors in 24 hours',data.errors_24h]];
 $('totals').innerHTML=totals.map(([label,count])=>'<span><strong>'+count.toLocaleString()+'</strong>'+label+'</span>').join('');
 $('retention').textContent='Tracking started: '+date(data.started)+'. Detailed events are kept for '+data.retention_days+' днів, сумарні лічильники — надалі. Історичні входи не відновлюються. Сесія Mini App: один вхід на 30 хвилин. Час подій — Europe/Lisbon. Message text, voice, photos and tokens are not recorded in the event journal. Confirmed support descriptions are stored separately and available for 90 days.';
}
async function users(){
 const result=await api('/api/admin/users?offset='+offset+'&q='+encodeURIComponent($('query').value));
 $('users').innerHTML=result.items.length?result.items.map(u=>'<tr><td><button data-user="'+u.user_id+'">'+escape(u.name||u.user_id)+'</button><small>'+escape(u.username?'@'+u.username:'')+' · '+u.user_id+'</small></td><td data-label="First seen">'+date(u.first_seen)+'</td><td data-label="Last active">'+date(u.last_seen)+'</td><td>'+(u.family_id?escape(u.family_id.slice(0,8)):'—')+'<small>'+escape(u.language||'—')+'</small></td></tr>').join(''):'<tr><td colspan="4">No users found</td></tr>';
 $('users-prev').disabled=offset===0;$('users-next').disabled=!result.has_more;$('users-page').textContent=result.items.length?(offset+1)+'–'+(offset+result.items.length):'0';
 document.querySelectorAll('[data-user]').forEach(b=>b.onclick=()=>{userFilter=b.dataset.user;cursor=null;$('event-filter').hidden=false;$('event-filter').innerHTML='Telegram ID: '+userFilter+' <button id="clear-user">All users</button>';$('clear-user').onclick=()=>{userFilter=null;$('event-filter').hidden=true;cursor=null;events().catch(e=>$('status').textContent=e.message);};events().catch(e=>$('status').textContent=e.message);});
}
async function events(append=false){
 const query=new URLSearchParams();if(cursor&&append)query.set('before',cursor);if(userFilter)query.set('user',userFilter);if($('errors').checked)query.set('errors','1');
 if($('release-filter').value){const [version,commit]=JSON.parse($('release-filter').value);query.set('version',version);query.set('commit',commit);}
 const result=await api('/api/admin/events?'+query);
 const html=result.items.map(e=>'<article class="event '+(e.status==='error'?'error':'')+'"><time>'+date(e.occurred)+'</time><div><strong>'+escape(labels[e.kind]||e.kind)+'</strong><small>'+escape(e.version)+' · '+escape(e.commit_sha.slice(0,12))+(e.value!==1?' · × '+e.value:'')+(e.duration_ms!=null?' · '+(e.duration_ms/1000).toFixed(1)+' s':'')+'</small></div><div class="actor">'+escape(e.name||'System')+'<small>'+(e.user_id||'—')+'</small></div></article>').join('');
 if(append)$('events').insertAdjacentHTML('beforeend',html);else $('events').innerHTML=html||'<p>No events yet</p>';cursor=result.next;$('events-more').hidden=!result.has_more;
}
let supportCursor=null;
async function supportTickets(append=false){
 const query=new URLSearchParams();if(append&&supportCursor)query.set('before',supportCursor);if($('support-resolved').checked)query.set('resolved','1');
 const result=await api('/api/admin/support?'+query);
 const html=result.items.map(t=>'<article class="support-ticket"><div class="section-head"><strong>#'+t.id+' · '+escape(t.name||t.user_id)+'</strong><small>'+date(t.created)+'</small></div><small>'+escape(t.username?'@'+t.username:'Telegram ID: '+t.user_id)+' · '+escape(t.metadata.language)+' · Version: '+escape(t.metadata.release?.version||'unknown')+' · Git: '+escape((t.metadata.release?.commit||'unknown').slice(0,12))+' · members: '+escape(t.metadata.family_member_count)+'</small><p class="support-description">'+escape(t.text)+'</p>'+(t.status==='open'?'<button class="secondary" data-resolve="'+t.id+'">Mark as resolved</button>':'<small>Resolved</small>')+'</article>').join('');
 if(append)$('support-tickets').insertAdjacentHTML('beforeend',html);else $('support-tickets').innerHTML=html||'<p>No new reports</p>';
 supportCursor=result.next;$('support-more').hidden=!result.has_more;
 document.querySelectorAll('[data-resolve]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('/api/admin/support/resolve',{id:Number(button.dataset.resolve)});await supportTickets();}catch(error){$('status').textContent=error.message;button.disabled=false;}});
}
$('support-resolved').onchange=()=>supportTickets().catch(error=>$('status').textContent=error.message);
$('support-more').onclick=()=>supportTickets(true).catch(error=>$('status').textContent=error.message);
let speechCursor=null;
async function speechBenchmarks(append=false){
 const data=await api('/api/admin/speech'+(append&&speechCursor?'?before='+encodeURIComponent(speechCursor):''));
 const seconds=value=>value===null?'—':(value/1000).toFixed(2);
 const rows=data.items.map(row=>'<tr><td>'+date(row.occurred)+'<small>'+escape(row.request_id.slice(0,8))+' · msg '+(row.message_id||'—')+' · '+row.user_id+' · '+escape(row.language)+' · '+escape(row.version)+'</small></td><td>'+seconds(row.audio_ms)+'</td><td>'+seconds(row.groq_ms)+'<small>'+escape(row.groq_status)+'</small></td><td>'+seconds(row.local_ms)+'<small>'+escape(row.local_status)+'</small></td><td>'+escape(row.winner||'—')+' · '+seconds(row.delivered_ms)+'</td><td>'+(row.agreement===null?'—':row.agreement?'✓':'≠')+'</td></tr>').join('');
 if(append)$('speech-benchmarks').insertAdjacentHTML('beforeend',rows);else $('speech-benchmarks').innerHTML=rows;
 if(data.items.length)speechCursor=data.items[data.items.length-1].occurred;
 $('speech-more').hidden=!data.has_more;
}
$('speech-more').onclick=()=>speechBenchmarks(true).catch(error=>$('status').textContent=error.message);
async function jevExperiments(){
 const data=await api('/api/admin/jev');const t=data.totals;
 $('jev-totals').textContent='Requests: '+t.requests+' · OK: '+(t.successful||0)+' · Errors: '+(t.errors||0)+' · Estimated USD: '+Number(t.estimated_usd||0).toFixed(6)+' · Unknown cost: '+(t.unknown_cost||0)+' · UTC daily cap: '+data.daily_request_cap+' · '+data.retention_days+' days';
 $('jev-experiments').innerHTML=data.items.map(row=>'<tr><td>'+date(row.occurred)+'<small>'+row.user_id+' · '+row.draft_id+'/'+escape(row.item_key)+' · '+escape(row.version)+'</small></td><td>'+escape(row.baseline)+'</td><td>'+escape(row.category||row.status)+'</td><td>'+(row.confidence===null?'—':(row.confidence*100).toFixed(1)+'%')+'</td><td>'+(row.latency_ms===null?'—':row.latency_ms+' ms')+'<small>'+(row.input_tokens===null?'—':row.input_tokens+' in / '+row.output_tokens+' out')+' · '+(row.estimated_usd===null?'—':'$'+Number(row.estimated_usd).toFixed(8))+'</small></td></tr>').join('');
}
async function refresh(){
 if(refreshing)return;refreshing=true;$('refresh').disabled=true;
 try{await Promise.all([stats(),users(),events(),supportTickets(),speechBenchmarks(),jevExperiments()]);$('dashboard').hidden=false;$('denied').hidden=true;$('status').textContent='Updated: '+date(Date.now()/1000);}
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

$('release-filter').onchange=()=>{cursor=null;events().catch(error=>$('status').textContent=error.message);};
