const $=id=>document.getElementById(id);
const sid=document.querySelector('meta[name="session-id"]').content;
const csrf=document.querySelector('meta[name="sunojob-token"]').content;
const storageKey='sunojob-owner:'+sid;
const ownerToken=location.hash.slice(1)||sessionStorage.getItem(storageKey)||'';
if(location.hash){sessionStorage.setItem(storageKey,ownerToken);history.replaceState(null,'',location.pathname);}
let current=null,busy=false;
function notice(message,error=false){$('notice').textContent=message;$('notice').className='notice'+(error?' error':'');}
function indiaTime(value){const date=new Date(value);if(Number.isNaN(date.getTime()))return 'Time unavailable';return new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'medium',hour12:true}).format(date)+' IST';}
function node(tag,text){const result=document.createElement(tag);result.textContent=text;return result;}
function readable(item){
  if(item.kind==='task'&&item.subject==='lunch_boxes'&&item.value==='prepare')return 'Prepare lunch boxes';
  if(item.kind==='quantity'&&item.subject==='lunch_boxes')return item.value+' lunch boxes';
  if(item.kind==='prohibition'&&item.subject==='onion'&&item.value==='exclude')return 'Do not add onion';
  if(item.kind==='permission_required'&&item.subject==='menu_change'&&item.value==='ask_first')return 'Ask before changing the menu';
  return item.subject.replaceAll('_',' ')+': '+item.value;
}
function controls(){
  const answered=!current||current.state!=='customer_confirmed';
  $('accept').disabled=busy||answered||!$('reviewed').checked||!$('owner-name').value.trim();
  $('request-change').disabled=busy||answered||!$('change-note').value.trim();
  for(const id of ['owner-name','reviewed','change-note','receipt-html','receipt-json'])$(id).disabled=busy||(!current);
}
async function request(path,body){
  const response=await fetch('/api/owner/'+sid+path,{method:body===undefined?'GET':'POST',headers:{'X-Owner-Token':ownerToken,...(body===undefined?{}:{'Content-Type':'application/json','X-SunoJob-Token':csrf})},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let error;try{error=await response.json();}catch{}throw Error(error?.detail||'Owner review is unavailable.');}return response;
}
function render(body){
  current=body;$('review').hidden=false;$('version').textContent='Version '+body.version;$('instructions').replaceChildren();
  for(const item of body.card.extraction.instructions){const card=node('div','');card.className='instruction';card.dataset.kind=item.kind;card.append(node('small',item.kind.replaceAll('_',' ')),node('strong',readable(item)));for(const evidence of item.evidence)card.append(node('blockquote','“'+evidence.quote+'”'));$('instructions').append(card);}
  $('sources').replaceChildren();for(const turn of body.card.sources)$('sources').append(node('strong',turn.id+' · '+turn.speaker),node('p',turn.text));
  for(const change of body.card.extraction.corrections)$('sources').append(node('p','Correction: '+change.before+' → '+change.after));
  $('customer-approval').textContent='Customer said “'+body.customer_confirmation.reply+'” for version '+body.version+' at '+indiaTime(body.customer_confirmation.at)+'. Identity unverified.';
  $('accept-form').hidden=body.state!=='customer_confirmed';$('downloads').hidden=body.state!=='both_confirmed';
  if(body.state==='both_confirmed'){$('owner-approval').textContent='Accepted by '+body.owner_confirmation.name+' at '+indiaTime(body.owner_confirmation.at)+'. Display name unverified.';notice('Both parties approved version '+body.version+'. Download the identical shared record below.');}
  else if(body.owner_change_request)notice('Change requested: '+body.owner_change_request.text+'. Ask the customer to refresh their page and resolve it.');
  else notice('Review every detail before accepting version '+body.version+'.');controls();
}
async function action(work){if(busy)return;busy=true;controls();try{await work();}catch(error){notice(error.message,true);}finally{busy=false;controls();}}
for(const id of ['owner-name','reviewed','change-note'])$(id).addEventListener('input',controls);
$('accept').onclick=()=>action(async()=>{render(await(await request('/accept',{version:current.version,name:$('owner-name').value,reviewed:$('reviewed').checked})).json());});
$('request-change').onclick=()=>action(async()=>{render(await(await request('/request-change',{version:current.version,note:$('change-note').value})).json());});
for(const kind of ['html','json'])$('receipt-'+kind).onclick=()=>action(async()=>{
  const response=await request('/receipt?version='+current.version+'&kind='+kind);const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]||'SunoJob-record';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
action(async()=>{if(!ownerToken)throw Error('Open the full owner review link created by the customer.');render(await(await request('')).json());});
