const sessionId = `demo-${crypto.randomUUID()}`;
let nextRequestSimulatesFailure = false;
let currentPendingAction = null;

const titles = {
  assistant:["GenAI Reservation Assistant","FastAPI + SQLite + RAG + OpenAI tool calling with human approval."],
  contacts:["CRM Contacts","Synthetic customer records loaded from SQLite."],
  reservations:["Reservations","Operational reservation records loaded from SQLite."],
  cases:["CRM Cases","Cases written transactionally after explicit staff approval."],
  policies:["Policies / RAG","Embedding-based retrieval over the hotel policy source."],
  metrics:["Before vs After","Example targets only until you replace them with measured results."],
  architecture:["Architecture","Implemented backend, agent, data, RAG, and approval boundaries."]
};

document.querySelectorAll('.nav').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('.nav').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.view).classList.add('active');
    document.getElementById('viewTitle').textContent=titles[btn.dataset.view][0];
    document.getElementById('viewSubtitle').textContent=titles[btn.dataset.view][1];
  });
});

document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
  document.getElementById('promptBox').value=c.dataset.prompt;
  nextRequestSimulatesFailure = c.dataset.failure === "true";
}));

document.getElementById('runBtn').addEventListener('click', runWorkflow);
document.getElementById('policyBtn').addEventListener('click', searchPolicy);

function escapeHtml(value){
  return String(value ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
    .replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

async function api(path, options={}){
  const response = await fetch(path, {
    headers: {"Content-Type":"application/json", ...(options.headers||{})},
    ...options
  });
  let body = {};
  try { body = await response.json(); } catch {}
  if(!response.ok){
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

function toolRow(item){
  const status=item.status || "success";
  const icons={success:"✓",warning:"⚠",blocked:"✕",escalation:"→"};
  const labels={
    retrieve_policy:"Policy search performed",
    evidence_check:"Retrieved evidence checked",
    policy_guard:"Unsupported policy answer blocked",
    escalation:"Escalated to staff review",
    customer_verification:"Customer verification",
    identity_guard:"Ambiguous customer blocked"
  };
  const label=labels[item.name] || item.name;
  return `<div class="tool ${escapeHtml(status)}"><span class="check">${icons[status] || "✓"}</span><div><b>${escapeHtml(label)}</b><br><span class="muted">${escapeHtml(item.result_summary)}</span></div></div>`;
}

function renderAssistantResponse(data){
  const response=document.getElementById('assistantResponse');
  const blocked=data.evidence_status && data.evidence_status !== "SUPPORTED";
  if(blocked){
    response.className='response evidence-blocked';
    response.innerHTML=`<div class="evidence-heading">Insufficient Retrieved Evidence</div>
      <div>${escapeHtml(data.message)}</div>
      <div class="evidence-meta">Evidence status: <b>${escapeHtml(data.evidence_status)}</b> • Staff review required</div>`;
  }else{
    response.className='response';
    response.textContent=data.message;
  }
}

function renderPreview(preview){
  const el=document.getElementById('recordPreview');
  if(!preview || Object.keys(preview).length===0){
    el.className='record-preview muted';
    el.textContent='No record loaded.';
    return;
  }
  el.className='record-preview';
  const rows=[];
  const c=preview.customer;
  const r=preview.reservation;
  const l=preview.loyalty;
  if(c){
    rows.push(["Customer",`${c.full_name} (${c.customer_id})`],["Email",c.email]);
  }
  if(r){
    rows.push(["Reservation",r.reservation_id],["Hotel",r.hotel_name],
      ["Dates",`${r.check_in} → ${r.check_out}`],["Room",r.room_type],["Status",r.status]);
  }
  if(l) rows.push(["Loyalty",`${l.tier} • ${Number(l.points).toLocaleString()} pts`]);
  if(preview.customer_matches){
    preview.customer_matches.forEach(x=>rows.push([x.customer_id,`${x.full_name} • ${x.email}`]));
  }
  el.innerHTML=rows.map(([k,v])=>`<div class="kv"><b>${escapeHtml(k)}</b><span>${escapeHtml(v)}</span></div>`).join('');
}

function renderApproval(action){
  currentPendingAction=action;
  const area=document.getElementById('approvalArea');
  if(!action){ area.innerHTML=''; return; }

  const options=action.room_options || [];
  if(options.length){
    area.innerHTML=`<div class="approval">
      <div class="approval-note">Select an available room. Approval triggers the real SQLite transaction.</div>
      ${options.map(o=>`<button class="primary" onclick="approveAction('${escapeHtml(action.action_id)}','${escapeHtml(o.room_type)}')">Approve ${escapeHtml(o.room_type)}</button>`).join('')}
      <button class="secondary danger" onclick="rejectAction('${escapeHtml(action.action_id)}')">Reject</button>
    </div>`;
  }else{
    const room=action.changes?.room_type || "proposed room";
    area.innerHTML=`<div class="approval">
      <div class="approval-note">Operational records are still unchanged.</div>
      <button class="primary" onclick="approveAction('${escapeHtml(action.action_id)}','${escapeHtml(room)}')">Approve change</button>
      <button class="secondary danger" onclick="rejectAction('${escapeHtml(action.action_id)}')">Reject</button>
    </div>`;
  }
}

async function runWorkflow(){
  const q=document.getElementById('promptBox').value.trim();
  if(!q) return;
  const runBtn=document.getElementById('runBtn');
  const timeline=document.getElementById('toolTimeline');
  const response=document.getElementById('assistantResponse');
  runBtn.disabled=true;
  timeline.className='timeline muted';
  timeline.textContent='Running backend workflow…';
  response.className='response muted';
  response.textContent='Waiting for backend response…';
  renderApproval(null);

  try{
    const data=await api('/api/chat',{
      method:'POST',
      body:JSON.stringify({
        message:q,
        session_id:sessionId,
        simulate_failure:nextRequestSimulatesFailure
      })
    });
    nextRequestSimulatesFailure=false;
    timeline.className='timeline';
    timeline.innerHTML=data.tool_calls?.length ? data.tool_calls.map(toolRow).join('') : '<span class="muted">No tool calls were needed.</span>';
    renderAssistantResponse(data);
    document.getElementById('modeNote').textContent=
      data.mode === 'offline-test'
        ? 'Developer mode: deterministic offline workflow (no API key detected).'
        : 'Live OpenAI Responses API mode.';
    renderPreview(data.record_preview);
    renderApproval(data.requires_approval ? data.pending_action : null);
  }catch(err){
    timeline.className='timeline';
    timeline.innerHTML=`<div class="tool error"><span class="check">!</span><div><b>Workflow failed</b><br><span class="muted">${escapeHtml(err.message)}</span></div></div>`;
    response.className='response';
    response.textContent='The workflow failed. No write was claimed. Escalate or retry.';
  }finally{
    runBtn.disabled=false;
  }
}

async function approveAction(actionId, roomType){
  const area=document.getElementById('approvalArea');
  area.innerHTML='<div class="muted">Submitting explicit approval…</div>';
  try{
    const data=await api('/api/actions/approve',{
      method:'POST',
      body:JSON.stringify({action_id:actionId, selected_room_type:roomType})
    });
    document.getElementById('assistantResponse').textContent=
      `${data.message} ${data.reservation.reservation_id} is now ${data.reservation.check_in} to ${data.reservation.check_out} in ${data.reservation.room_type}. CRM case ${data.crm_case.case_id} is ${data.crm_case.status}.`;
    currentPendingAction=null;
    area.innerHTML='';
    renderPreview({reservation:data.reservation});
    await Promise.all([loadReservations(),loadCases(),loadAudit()]);
  }catch(err){
    area.innerHTML=`<div class="note">Approval failed: ${escapeHtml(err.message)} No partial success is assumed.</div>`;
  }
}

async function rejectAction(actionId){
  try{
    const data=await api('/api/actions/reject',{
      method:'POST',
      body:JSON.stringify({action_id:actionId})
    });
    currentPendingAction=null;
    document.getElementById('approvalArea').innerHTML='';
    document.getElementById('assistantResponse').textContent=data.message;
  }catch(err){
    document.getElementById('approvalArea').innerHTML=`<div class="note">${escapeHtml(err.message)}</div>`;
  }
}

async function loadContacts(){
  const rows=await api('/api/customers');
  const t=document.getElementById('contactsTable');
  t.innerHTML='<thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>City</th></tr></thead><tbody>'+
    rows.map(c=>`<tr><td>${escapeHtml(c.customer_id)}</td><td>${escapeHtml(c.full_name)}</td><td>${escapeHtml(c.email)}</td><td>${escapeHtml(c.phone)}</td><td>${escapeHtml(c.city)}</td></tr>`).join('')+
    '</tbody>';
}

async function loadReservations(){
  const rows=await api('/api/reservations');
  const t=document.getElementById('reservationsTable');
  t.innerHTML='<thead><tr><th>Reservation</th><th>Customer</th><th>Hotel</th><th>Check-in</th><th>Check-out</th><th>Room</th><th>Status</th></tr></thead><tbody>'+
    rows.map(r=>`<tr><td>${escapeHtml(r.reservation_id)}</td><td>${escapeHtml(r.customer_name)}</td><td>${escapeHtml(r.hotel_name)}</td><td>${escapeHtml(r.check_in)}</td><td>${escapeHtml(r.check_out)}</td><td>${escapeHtml(r.room_type)}</td><td><span class="badge good">${escapeHtml(r.status)}</span></td></tr>`).join('')+
    '</tbody>';
}

async function loadCases(){
  const rows=await api('/api/cases');
  const body=document.getElementById('casesBody');
  body.innerHTML=rows.map(c=>`<tr><td>${escapeHtml(c.case_id)}</td><td>${escapeHtml(c.customer_name)}</td><td>${escapeHtml(c.case_type)}</td><td><span class="badge ${c.status==='Closed'?'good':'warn'}">${escapeHtml(c.status)}</span></td><td>${escapeHtml(c.resolution)}</td></tr>`).join('');
}

async function loadAudit(){
  const rows=await api('/api/audit');
  const body=document.getElementById('auditBody');
  if(!rows.length){
    body.innerHTML='<tr><td colspan="4" class="muted">No backend writes yet.</td></tr>';
    return;
  }
  body.innerHTML=rows.map(a=>{
    let result=a.after_value || (a.success ? 'Success' : 'Failed');
    try{
      const parsed=JSON.parse(result);
      result=parsed.reservation_id
        ? `${parsed.reservation_id}: ${parsed.check_in} → ${parsed.check_out}, ${parsed.room_type}`
        : parsed.resolution || result;
    }catch{}
    return `<tr><td>${escapeHtml(a.timestamp)}</td><td>${escapeHtml(a.action)}</td><td>${escapeHtml(a.record_id)}</td><td>${escapeHtml(result)}</td></tr>`;
  }).join('');
}

async function searchPolicy(){
  const q=document.getElementById('policySearch').value.trim();
  const result=document.getElementById('policyResult');
  if(!q) return;
  result.className='policy-result muted';
  result.textContent='Retrieving…';
  try{
    const data=await api('/api/policies/search',{method:'POST',body:JSON.stringify({query:q})});
    const top=data.matches?.[0];
    const allowed=data.answer_allowed === true;
    const decision=allowed ? 'Answer allowed — evidence meets grounding threshold' : 'Answer blocked — staff review required';
    const score=top ? Number(top.similarity_score).toFixed(2) : 'n/a';

    result.className=`policy-result ${allowed ? '' : 'blocked-policy'}`;
    result.innerHTML=`<div class="policy-decision-grid">
        <div><span class="muted">Policy</span><br><b>${top ? escapeHtml(top.title) : 'No relevant policy found'}</b></div>
        <div><span class="muted">Similarity / relevance</span><br><b>${escapeHtml(score)}</b></div>
        <div><span class="muted">Evidence Status</span><br><b>${escapeHtml(data.evidence_status)}</b></div>
        <div><span class="muted">Decision</span><br><b>${escapeHtml(decision)}</b></div>
      </div>
      ${top ? `<hr><div><b>${escapeHtml(top.policy_id)} — ${escapeHtml(top.title)}</b><br>${escapeHtml(top.text)}</div>` : ''}
      <div class="evidence-meta">Required relevance threshold: ${escapeHtml(data.min_relevance_score)}</div>`;
  }catch(err){
    result.textContent=`Policy retrieval failed: ${err.message}`;
  }
}

async function init(){
  try{
    const health=await api('/api/health');
    const pill=document.getElementById('statusPill');
    pill.innerHTML=`<span class="dot"></span> Backend online • ${escapeHtml(health.mode)}`;
    if(health.mode==='offline-test') pill.classList.add('offline');
    await Promise.all([loadContacts(),loadReservations(),loadCases(),loadAudit()]);
  }catch(err){
    const pill=document.getElementById('statusPill');
    pill.classList.add('error');
    pill.textContent='Backend unavailable';
    document.getElementById('assistantResponse').textContent='Backend connection failed. Start FastAPI with: uvicorn main:app --reload';
  }
}
init();
