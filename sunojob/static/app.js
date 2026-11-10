const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="sunojob-token"]').content;
let ownerLinkKey=null,emailPreview=null,emailConfigured=false,emailSender=null;
let emailRecipientKey=null,emailRecipientsTouched=false;
let current=null,busy=false,recorder=null,stream=null,chunks=[],timer=null,audioUrl=null,audioContext=null,playback=false,acquiring=false;
const states={draft:'Draft · Review the details',awaiting_readback:'Readback ready · Listen before confirming',awaiting_reply:'Readback finished · Record your confirmation or correction',needs_correction:'Please explain what should change',updating:'Processing correction',customer_confirmed:'Customer confirmed this version · Owner review pending',both_confirmed:'Both parties approved this version · Shared record ready',owner_changes_requested:'Owner requested changes · Customer review needed'};
function notice(message,kind=''){$('notice').textContent=message;$('notice').className='notice '+kind;}
function indiaTime(value){const date=new Date(value);if(Number.isNaN(date.getTime()))return 'Time unavailable';return new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'medium',hour12:true}).format(date)+' IST';}
function requestError(data,fallback='Request failed.'){
  if(typeof data?.detail==='string')return data.detail;
  if(Array.isArray(data?.detail))return data.detail.map(error=>{
    const field=(error.loc||[]).filter(part=>!['body','query','path'].includes(part)).join(' ');
    return (field?field.replaceAll('_',' ')+': ':'')+(error.msg||'Check this field.');
  }).join(' ')||fallback;
  return fallback;
}
function emailNotice(message,kind=''){$('email-notice').hidden=false;$('email-notice').textContent=message;$('email-notice').className='notice '+kind;}
function emailRecipients(){
  const result={},errors=[];
  for(const [id,key,label] of [['customer-email','customer_email','Customer email'],['owner-email','owner_email','Owner email']]){
    const value=$(id).value.trim();$(id).value=value;result[key]=value;
    if(!value)errors.push(label+' is required.');
    else if(value.length>254||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))errors.push(label+': enter a plain email address, such as name@example.com.');
  }
  if(errors.length)throw Error(errors.join(' '));return result;
}
function emailTask(message,action){return task(message,async()=>{
  emailNotice(message,'busy');
  try{await action();emailNotice($('notice').textContent,$('notice').className.includes('error')?'error':'');}
  catch(error){emailNotice(error.message,'error');throw error;}
});}
function controls(){
  const recording=!!recorder;
  $('record').disabled=busy||playback||acquiring||current?.state==='updating';
  $('upload').disabled=busy||playback||recording||acquiring;
  $('readback').disabled=busy||playback||recording||acquiring||!current||!!current.pending_text||['customer_confirmed','both_confirmed','owner_changes_requested'].includes(current.state);
  $('submit-text').disabled=busy||playback||recording||acquiring;
  $('language').disabled=busy||recording||acquiring||!!current;
  $('start-over').disabled=busy||recording||acquiring;$('recent').disabled=busy||recording||acquiring;
  if(!recording)$('record-label').textContent=current?(current.state==='awaiting_reply'?'Record reply':'Record correction'):'Record request';
  $('submit-text').textContent=current?'Apply correction':'Create draft from text';
  $('record-help').textContent=recording?'Recording… automatically stops after 24 seconds.':acquiring?'Waiting for microphone access…':'Up to 25 seconds. Microphone access stays off until you start.';
  for(const id of ['owner-link','refresh-review','receipt-html','receipt-json','email-drafts','email-jobs-refresh'])$(id).disabled=busy||playback||recording||acquiring;
  $('owner-link').disabled=$('owner-link').disabled||current?.state!=='customer_confirmed';
  const blocked=busy||playback||recording||acquiring;
  $('email-preview').disabled=blocked||!emailConfigured||current?.state!=='both_confirmed';
  $('send-emails').disabled=blocked||!emailPreview||emailPreview.state!=='prepared'||!$('email-reviewed').checked;
  for(const id of ['customer-email','owner-email'])$(id).disabled=blocked;
  $('email-reviewed').disabled=blocked||!emailPreview||emailPreview.state!=='prepared';
}
async function api(path,body){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-SunoJob-Token':token},body:body===undefined?undefined:JSON.stringify(body)});
  let data;try{data=await response.json();}catch{throw Error('Server returned an unreadable response.');}
  if(!response.ok)throw Error(requestError(data));return data;
}
async function task(message,action){
  if(busy)return;busy=true;controls();notice(message,'busy');
  try{await action();await recent();}
  catch(error){notice(error.message,'error');if(current){try{render(await api('/api/sessions/'+current.id));}catch{}}}
  finally{busy=false;controls();}
}
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function readable(item){
  if(item.kind==='task'&&item.subject==='lunch_boxes'&&item.value==='prepare')return 'Prepare lunch boxes';
  if(item.kind==='quantity'&&item.subject==='lunch_boxes')return item.value+' lunch boxes';
  if(item.kind==='prohibition'&&item.subject==='onion'&&item.value==='exclude')return 'Do not add onion';
  if(item.kind==='permission_required'&&item.subject==='menu_change'&&item.value==='ask_first')return 'Ask before changing the menu';
  return item.subject.replaceAll('_',' ')+': '+item.value;
}
function clearAudio(){$('player').pause();$('player').removeAttribute('src');$('player').hidden=true;playback=false;audioContext=null;if(audioUrl){URL.revokeObjectURL(audioUrl);audioUrl=null;}$('readback-caption').hidden=true;}
function resetEmailPreview(){emailPreview=null;$('email-preview-panel').hidden=true;$('email-reviewed').checked=false;}
function render(session){
  if(!current||current.id!==session.id||current.version!==session.version||current.state!==session.state){$('receipt-history-panel').hidden=true;$('receipt-history').replaceChildren();}
  const recipientKey=session.id+':'+session.version;
  if(emailRecipientKey!==recipientKey){emailRecipientKey=recipientKey;emailRecipientsTouched=false;$('customer-email').value='';$('owner-email').value='';$('email-jobs').replaceChildren();$('email-history-panel').hidden=true;$('email-notice').hidden=true;}
  if(!current||current.id!==session.id||current.version!==session.version||session.state!=='both_confirmed')resetEmailPreview();
  if(!current||current.id!==session.id||current.version!==session.version||current.readback?.id!==session.readback?.id||['customer_confirmed','both_confirmed'].includes(session.state))clearAudio();
  current=session;localStorage.setItem('sunojob-session',session.id);$('language').value=session.language;
  $('empty').hidden=true;$('card-content').hidden=false;$('version').textContent='Version '+session.version;
  $('state').textContent=states[session.state]||session.state;$('state').className='state-banner'+(['customer_confirmed','both_confirmed'].includes(session.state)?' confirmed':'');
  const event=session.last_activity;
  let explanation='';
  if(session.pending_text){
    explanation=(event?.kind==='correction_failed'?'The latest correction could not be processed. ':'A correction is pending. ')+
      'Review the text in the correction box, then choose Apply correction. Current confirmation is blocked until the correction is applied and the revised version is reviewed.';
    $('text-entry').open=true;
  }else if(session.state==='needs_correction')explanation='The current readback was not confirmed. Explain what should change, or generate a fresh readback if the card is already correct.';
  if(explanation&&event?.at)explanation+=' Last recorded action: '+event.kind.replaceAll('_',' ')+' · '+indiaTime(event.at)+'.';
  $('state-reason').textContent=explanation;$('state-reason').hidden=!explanation;
  $('instructions').replaceChildren();
  for(const item of session.card.extraction.instructions){const card=node('div','');card.className='instruction';card.dataset.kind=item.kind;
    card.append(node('small',item.kind.replaceAll('_',' ')),node('strong',readable(item)));
    for(const evidence of item.evidence)card.append(node('blockquote','“'+evidence.quote+'”'));$('instructions').append(card);}
  const linkKey=session.id+':'+session.version;
  if(ownerLinkKey!==linkKey){$('owner-url').value='';$('open-owner').hidden=true;ownerLinkKey=linkKey;}
  $('owner-review').hidden=!session.customer_confirmation;
  $('owner-note').textContent=session.owner_change_request?'Owner requests: '+session.owner_change_request.text:'';
  $('owner-summary').textContent=session.owner_confirmation?'Owner '+session.owner_confirmation.name+' approved version '+session.version+'. Display name is unverified.':'Owner acceptance is separate from the customer’s voice confirmation.';
  $('receipt-panel').hidden=session.state!=='both_confirmed';
  if(session.owner_change_request)$('text').placeholder='Explain the instructions you want after reviewing the owner’s request.';
  $('questions').replaceChildren(...session.card.extraction.questions.map(q=>node('p','Please clarify: '+q.text)));
  $('sources').replaceChildren();for(const turn of session.card.sources)$('sources').append(node('strong',turn.id+' · '+turn.speaker),node('p',turn.text));
  for(const change of session.card.extraction.corrections)$('sources').append(node('p','Correction: '+change.before+' → '+change.after));controls();
  if(session.state==='needs_correction'&&session.pending_text&&!$('text').value)$('text').value=session.pending_text;
  loadEmailJobs(session.id).catch(()=>{if(current?.id===session.id&&current?.version===session.version){$('email-history-panel').hidden=false;$('email-history-note').textContent='Saved email history could not be loaded. Press Refresh email results to try again.';}});
  loadReceiptHistory(session.id).catch(()=>{if(current?.id===session.id&&current?.version===session.version&&current?.state===session.state){$('receipt-history-panel').hidden=false;$('receipt-history').replaceChildren(node('p','Saved snapshots could not be loaded. Refresh this request to try again.'));}});
}
async function recent(){const saved=await api('/api/sessions');$('recent').replaceChildren(node('option','Choose a request'));$('recent').firstChild.value='';for(const s of saved){const option=node('option',s.id.slice(0,8)+' · v'+s.version+' · '+s.state.replaceAll('_',' '));option.value=s.id;$('recent').append(option);}if(current){if(!saved.some(s=>s.id===current.id)){const option=node('option','Current request · v'+current.version+' · '+current.state.replaceAll('_',' '));option.value=current.id;$('recent').append(option);}$('recent').value=current.id;}}
function context(){return current?{id:current.id,version:current.version,state:current.state,readback:current.readback}:null;}
function fileBase64(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});}
async function sendAudio(blob,captured){await task('Transcribing and checking your words…',async()=>{
  const audio=await fileBase64(blob);let result;
  if(!captured){result=await api('/api/sessions/voice',{audio,language:$('language').value});render(result);}
  else if(captured.state==='awaiting_reply'&&captured.readback){result=await api('/api/sessions/'+captured.id+'/reply-voice',{audio,version:captured.version,readback_id:captured.readback.id});render(result.session);}
  else{result=await api('/api/sessions/'+captured.id+'/correct-voice',{audio,version:captured.version});render(result.session);}
  notice(result.reply_transcript?'You said: '+result.reply_transcript:'Draft ready. Check the card, then generate the spoken readback.');
});}
$('record').onclick=async()=>{
  if(recorder){recorder.stop();return;}acquiring=true;controls();
  try{
    if(!navigator.mediaDevices||!window.MediaRecorder)throw Error('Microphone recording is unavailable. Use an audio upload or typed request.');
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const types=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/webm'];const type=types.find(t=>MediaRecorder.isTypeSupported(t));
    const captured=context();const active=new MediaRecorder(stream,type?{mimeType:type}:undefined);recorder=active;chunks=[];let failed=false;
    active.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    active.onstop=()=>{clearTimeout(timer);recorder=null;stream.getTracks().forEach(t=>t.stop());$('record').classList.remove('recording');controls();if(!failed)sendAudio(new Blob(chunks,{type:active.mimeType}),captured);};
    active.onerror=()=>{failed=true;clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());recorder=null;$('record').classList.remove('recording');notice('Recording failed. Please try again.','error');controls();};
    active.start();$('record').classList.add('recording');$('record-label').textContent='Stop recording';$('record-help').textContent='Recording… automatically stops after 24 seconds.';notice('Listening. Tap Stop when finished.');timer=setTimeout(()=>recorder?.stop(),24000);
  }catch(error){notice(error.message,'error');stream?.getTracks().forEach(t=>t.stop());}
  finally{acquiring=false;controls();}
};
$('upload').onchange=async e=>{const file=e.target.files[0];if(file)await sendAudio(file,context());e.target.value='';};
$('submit-text').onclick=()=>task('Preparing the draft…',async()=>{const text=$('text').value.trim();if(!text)throw Error('Enter a request or correction.');
  const result=current?await api('/api/sessions/'+current.id+'/correct-text',{text,version:current.version}):await api('/api/sessions/text',{text,language:$('language').value});render(result);$('text').value='';notice('Draft ready. Review and listen before confirming.');});
$('readback').onclick=()=>task('Generating the spoken readback…',async()=>{
  const result=await api('/api/sessions/'+current.id+'/readback',{version:current.version});render(result.session);clearAudio();
  const bytes=Uint8Array.from(atob(result.audio),c=>c.charCodeAt(0));audioUrl=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
  audioContext={id:current.id,version:current.version,readback_id:current.readback.id};
  $('player').src=audioUrl;$('player').hidden=false;$('spoken-text').textContent=result.text;$('readback-caption').hidden=false;notice('Press Play and listen to the full readback. Replay using this player.');
});
$('player').onplay=()=>{if(recorder||busy){$('player').pause();return;}playback=true;controls();};
$('player').onpause=()=>{playback=false;controls();};
$('player').onended=()=>{playback=false;const captured=audioContext?{...audioContext}:null;if(!captured)return;
  if(current?.state==='awaiting_reply'&&current.readback?.id===captured.readback_id){controls();return;}
  task('Finishing the readback…',async()=>{render(await api('/api/sessions/'+captured.id+'/readback-complete',{version:captured.version,readback_id:captured.readback_id}));notice('Now record “I confirm” / “అవును”, or describe your correction.');});
};
$('start-over').onclick=()=>{clearAudio();resetEmailPreview();emailRecipientKey=null;emailRecipientsTouched=false;$('customer-email').value='';$('owner-email').value='';$('email-jobs').replaceChildren();$('email-notice').hidden=true;current=null;localStorage.removeItem('sunojob-session');$('recent').value='';$('card-content').hidden=true;$('empty').hidden=false;$('version').textContent='No draft yet';$('text').value='';$('text-entry').open=false;controls();notice('Ready for a new request. Saved requests remain available.');};
$('recent').onchange=()=>{const id=$('recent').value;if(id)task('Loading saved request…',async()=>{render(await api('/api/sessions/'+id));notice('Saved request loaded. Generate a readback if you need to review it.');});};
async function saveDownload(path,body){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-SunoJob-Token':token},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok){let error;try{error=await response.json();}catch{}throw Error(requestError(error,'Download failed.'));}
  const file=await response.blob();const url=URL.createObjectURL(file);const a=document.createElement('a');
  a.href=url;a.download=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]||'SunoJob-record';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('owner-link').onclick=()=>task('Preparing owner review…',async()=>{
  const result=await api('/api/sessions/'+current.id+'/owner-link',{version:current.version});
  const url=location.origin+result.path;$('owner-url').value=url;$('open-owner').href=url;$('open-owner').hidden=false;
  notice('Owner link ready for this laptop. It expires in 24 hours; creating another link replaces it.');
});
$('refresh-review').onclick=()=>task('Refreshing review status…',async()=>{render(await api('/api/sessions/'+current.id));notice('Review status refreshed.');});
for(const kind of ['html','json'])$('receipt-'+kind).onclick=()=>task('Preparing shared record…',async()=>{
  await saveDownload('/api/sessions/'+current.id+'/receipt?version='+current.version+'&kind='+kind);notice('Shared record downloaded. Both parties receive the same saved snapshot.');
});
$('email-drafts').onclick=()=>emailTask('Preparing unsent email drafts…',async()=>{
  await saveDownload('/api/sessions/'+current.id+'/email-drafts',{version:current.version,...emailRecipients()});
  notice('Downloaded two unsent email drafts with identical attachments. Review and send using your email account. No messages have been sent.');
});
window.addEventListener('focus',()=>{if(current&&!busy&&!recorder&&!acquiring&&!playback)task('Refreshing review status…',async()=>{render(await api('/api/sessions/'+current.id));notice('Review status refreshed.');});});
const mailStates={prepared:'Preview only — not sent',reserved:'Waiting for submission',submitting:'Submission in progress',accepted_by_smtp:'Accepted by SMTP — inbox delivery not verified',rejected:'Rejected by SMTP',failed_before_submission:'Failed before submission',unknown:'Unknown outcome — automatic resend blocked',not_attempted:'Not attempted'};
async function loadReceiptHistory(sid){
  const version=current?.version,state=current?.state;
  const snapshots=await api('/api/sessions/'+sid+'/receipts');
  if(current?.id!==sid||current?.version!==version||current?.state!==state)return;
  $('receipt-history-panel').hidden=!snapshots.length;$('receipt-history').replaceChildren();
  for(const snapshot of snapshots){
    const row=node('div','');row.className='saved-snapshot';
    row.append(node('strong','Approved snapshot · Version '+snapshot.version),node('p',indiaTime(snapshot.issued_at)+' · '+(snapshot.is_current_approval?'Matches the current approved version':'Historical record · does not approve current work')));
    for(const kind of ['html','json']){const button=node('button',kind==='html'?'Download saved HTML':'Download saved JSON');button.className='secondary';button.onclick=()=>task('Downloading a saved approval snapshot…',async()=>{
      await saveDownload('/api/sessions/'+sid+'/receipts/'+snapshot.version+'?kind='+kind);
      notice('Saved approval snapshot downloaded. Current approvals and corrections were not changed.');
    });row.append(button);}
    $('receipt-history').append(row);
  }
}
function mailTarget(target){return target.role[0].toUpperCase()+target.role.slice(1)+' → '+target.address+': '+(mailStates[target.status]||target.status)+(target.detail&&target.status!=='accepted_by_smtp'?' · '+target.detail:'');}
function renderMailPreview(job){
  emailPreview=job;$('email-preview-panel').hidden=false;$('email-reviewed').checked=false;$('email-preview-content').replaceChildren();
  const box=$('email-preview-content');box.append(node('p','From: '+job.sender),node('p','Subject: '+job.subject),node('p','Version '+job.version+' · Record '+job.receipt_id));
  for(const target of job.targets)box.append(node('p',mailTarget(target)));
  const details=node('details','');details.append(node('summary','Attachment details and integrity references'));
  for(const attachment of job.attachments)details.append(node('p',attachment.filename+' · '+attachment.bytes+' bytes · SHA-256 '+attachment.sha256));box.append(details);
  box.append(node('p',job.state==='prepared'?'Preview expires: '+indiaTime(job.expires_at):'Submission recorded: '+indiaTime(job.finished_at||job.created_at)));controls();
}
async function loadEmailJobs(sid){const version=current?.version;const jobs=await api('/api/sessions/'+sid+'/email-jobs');if(current?.id!==sid||current?.version!==version)return;
  $('email-history-panel').hidden=false;
  const submissions=jobs.filter(job=>job.state!=='prepared'),previews=jobs.filter(job=>job.state==='prepared');
  $('email-history-note').textContent=submissions.length?'Recent saved submissions for this request. Earlier results remain visible while a correction is pending. SMTP acceptance does not verify inbox delivery.':previews.length?'Only unsent previews are shown in the recent history. A preview does not send an email.':'No email preview or submission is saved for this request. Approval alone does not send an email.';
  const saved=jobs.find(job=>job.version===version);
  if(saved&&!emailRecipientsTouched&&!$('customer-email').value&&!$('owner-email').value){
    for(const [id,role] of [['customer-email','customer'],['owner-email','owner']])$(id).value=saved.targets.find(target=>target.role===role)?.address||'';
    if($('email-notice').hidden)emailNotice('Last saved recipient addresses restored. Review them before preparing another email.');
  }
  const labels={complete:'Both copies accepted by mail server',complete_with_errors:'Check recipient results',prepared:'Preview saved · not sent',sending:'Sending',interrupted:'Submission interrupted'};
  function mailJob(job){const item=node('div','');item.className='email-result';item.append(node('strong','Version '+job.version+' · '+(labels[job.state]||job.state)+' · '+indiaTime(job.finished_at||job.created_at)));
    if(job.sender)item.append(node('p','Sender: '+job.sender));
    if(job.version!==current.version||current.state!=='both_confirmed')item.append(node('p','Earlier approval snapshot · this result does not approve or send the current pending request.'));
    for(const target of job.targets)item.append(node('p',mailTarget(target)));return item;}
  $('email-jobs').replaceChildren();for(const job of submissions)$('email-jobs').append(mailJob(job));
  if(previews.length){const details=node('details','');details.append(node('summary','Saved email previews · '+previews.length+' · not sent'));for(const job of previews)details.append(mailJob(job));$('email-jobs').append(details);}
}
for(const id of ['customer-email','owner-email'])$(id).addEventListener('input',()=>{emailRecipientsTouched=true;resetEmailPreview();$('email-notice').hidden=true;controls();});
$('email-reviewed').onchange=controls;
$('email-preview').onclick=()=>emailTask('Preparing email preview; nothing is sent…',async()=>{
  const job=await api('/api/sessions/'+current.id+'/email-preview',{version:current.version,...emailRecipients()});renderMailPreview(job);await loadEmailJobs(current.id);notice('Preview ready. Review the addresses and attachments, then choose Send to both now.');
});
$('send-emails').onclick=()=>emailTask('Submitting the two copies once. Please wait for the recipient results…',async()=>{
  const sid=current.id;const job=await api('/api/sessions/'+sid+'/send-emails',{preview_id:emailPreview.id,reviewed_recipients:$('email-reviewed').checked});renderMailPreview(job);await loadEmailJobs(sid);
  notice(job.state==='complete'?'Both copies were accepted by SMTP. Check the actual inboxes; inbox delivery is not verified.':'Check each recipient result below. No automatic retries were made.',job.state==='complete'?'':'error');
});
$('email-jobs-refresh').onclick=()=>task('Refreshing email results…',async()=>{try{await loadEmailJobs(current.id);notice('Email submission results refreshed.');}catch(error){$('email-history-note').textContent='Saved email history could not be loaded. Try refreshing again.';throw error;}});
(async()=>{try{const status=await api('/api/status');emailConfigured=status.email_delivery==='smtp_configured';emailSender=status.email_sender;
$('email-config').textContent=emailConfigured?'Email enabled · Sender: '+emailSender+'. Saved submission results appear below.':'Direct email is not configured. You can download drafts, or enable email when starting the local server.';
$('connection').textContent=status.mode==='live'?'Gnani voice · Live services':'Offline test services';await recent();const saved=localStorage.getItem('sunojob-session');if(saved){try{render(await api('/api/sessions/'+saved));await recent();}catch{localStorage.removeItem('sunojob-session');}}controls();}catch(error){notice(error.message,'error');}})();
