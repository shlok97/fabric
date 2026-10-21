'use strict';
let token = '', mode = 'search';
const $ = id => document.getElementById(id);
const node = (tag, value, cls) => { const e = document.createElement(tag); if(value !== undefined) e.textContent = String(value); if(cls) e.className = cls; return e; };
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
async function call(operation, args = {}) {
  const r = await fetch('/api/call', {method:'POST', headers:{'Content-Type':'application/json', 'Authorization':'Bearer '+token}, body:JSON.stringify({operation,arguments:args})});
  const data = await r.json();
  if(!r.ok) throw new Error(data.error?.message || 'Request failed.');
  return data;
}
function signout() { token=''; $('token').value=''; $('workspace').hidden=true; $('login').hidden=false; $('results').replaceChildren(); $('sources').replaceChildren(); $('metrics').hidden=true; error(''); }
$('signout').onclick = signout;
$('login-form').onsubmit = async e => { e.preventDefault(); error(''); token=$('token').value.trim(); try { const d=await call('status'); $('token').value=''; $('login').hidden=true; $('workspace').hidden=false; $('workspace-name').textContent=d.identity.workspace; $('identity-name').textContent=d.identity.name; $('tenant-name').textContent='Tenant / '+d.identity.tenant; $('sources').replaceChildren(); for(const s of d.sources){const box=node('div',s.id,'source'); box.append(node('small',s.kind+' · '+s.collection_id)); box.append(node('small', s.captured_at ? 'Snapshot '+s.captured_at : s.kind==='folder' ? 'Synced '+(s.last_success||'never') : 'Read live on request')); if(s.last_error) box.append(node('small',s.last_error)); $('sources').append(box);} }catch(err){token='';error(err.message);} };
for(const b of document.querySelectorAll('[data-tab]')) b.onclick=()=>{mode=b.dataset.tab; for(const tab of document.querySelectorAll('[data-tab]'))tab.classList.toggle('active',tab===b); $('read-form').hidden=mode!=='read'; $('search-form').hidden=mode==='read'; $('query').value=mode==='discover'?'revenue estimate':'Northstar revenue capacity';};
function render(data) {
  $('results').replaceChildren(); $('metrics').replaceChildren(); $('metrics').hidden=false;
  const r=data.receipt;
  for(const [name,value] of [['Retrieval',r.elapsed_ms+' ms'],['Evidence',r.evidence_bytes+' bytes'],['Context', '~'+r.estimated_context_tokens+' tokens'],['Local embeddings',r.local_embedding_calls],['External model calls',r.external_model_calls],['API cost','$'+r.external_model_cost_usd]]) $('metrics').append(node('span',name+' / '+value));
  if(!data.items?.length) $('results').append(node('p','No permitted evidence matched these selectors. This does not establish that the fact is absent.','empty'));
  for(const item of data.items||[]){
    const card=node('article',undefined,'card'); card.append(node('span',item.collection||item.collection_id||item.kind,'badge')); card.append(node('h3',item.title||item.descriptor||item.id));
    if(item.kind==='passage') card.append(node('div',item.text,'passage'));
    else if(item.row){const t=node('table');for(const [key,value]of Object.entries(item.row)){const tr=node('tr');tr.append(node('th',key),node('td',value===null?'Unavailable':value));t.append(tr);}card.append(t);}
    else {card.append(node('p',item.description||'Search this permitted document collection.'));if(item.unit)card.append(node('p','Unit / '+item.unit,'quiet'));if(item.operations?.includes('read')){const b=node('button','Read this descriptor');b.onclick=()=>{$('descriptor').value=item.id;document.querySelector('[data-tab="read"]').click();};card.append(b);}}
    if(item.ref){const p=node('div',undefined,'provenance');p.append(node('div','Evidence / '+item.ref)); if(item.locator)p.append(node('div',item.locator.source+' / '+item.locator.document+' · lines '+item.locator.start_line+'–'+item.locator.end_line));p.append(node('div','Version / '+item.version));p.append(node('div',item.freshness+' · '+item.observed_at));const b=node('button','Revalidate citation');b.onclick=async()=>{error('');try{render(await call('get_evidence',{ref:item.ref}));}catch(e){error(e.message);}};p.append(b);card.append(p);}
    $('results').append(card);
  }
  if(data.has_more)$('results').append(node('p','More results exist. Narrow the query or increase the bounded limit.','quiet'));
  if(data.unavailable_subjects?.length)$('results').append(node('p','Unavailable subjects / '+data.unavailable_subjects.join(', '),'quiet'));
  if(data.coverage)$('results').append(node('p',data.coverage,'quiet'));
}
async function retrieve(e,op,args){e.preventDefault();error('');const b=e.target.querySelector('button');b.disabled=true;try{render(await call(op,args));}catch(err){$('results').replaceChildren();$('metrics').hidden=true;error(err.message);}finally{b.disabled=false;}}
$('search-form').onsubmit=e=>retrieve(e,mode,mode==='search'?{query:$('query').value,strategy:$('strategy').value}:{query:$('query').value});
$('read-form').onsubmit=e=>{const args={descriptor_id:$('descriptor').value,subjects:[$('subject').value],period:$('period').value,basis:$('basis').value};if($('as-of').value)args.as_of=$('as-of').value;return retrieve(e,'read',args);};
