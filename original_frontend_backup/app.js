
let DATA;
let state = { reservations: [], cases: [
  {case_id:"CASE9001", customer_id:"C1001", customer_name:"Jessica Turner", case_type:"Reservation Modification Request", status:"New", resolution:"Awaiting action"}
], audit: [] };

async function init(){
  DATA = await fetch('data.json').then(r=>r.json());
  state.reservations = JSON.parse(JSON.stringify(DATA.reservations));
  renderContacts(); renderReservations(); renderCases();
}
init();

document.querySelectorAll('.nav').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('.nav').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.view).classList.add('active');
    const titles = {
      assistant:["GenAI Reservation Assistant","SuiteCRM-style concept demonstrating read, reason, retrieve, approve, and write-back."],
      contacts:["CRM Contacts","Synthetic customer records used by the agent."],
      reservations:["Reservations","Operational reservation records used by the agent."],
      cases:["CRM Cases","Cases created or updated by AI tools after approval."],
      policies:["Policies / RAG","Business policy retrieval used to ground agent responses."],
      metrics:["Before vs After","How you can present baseline and GenAI-assisted performance."],
      architecture:["Architecture","How the prototype maps to your Part A implementation."]
    };
    document.getElementById('viewTitle').textContent=titles[btn.dataset.view][0];
    document.getElementById('viewSubtitle').textContent=titles[btn.dataset.view][1];
  });
});

document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>document.getElementById('promptBox').value=c.dataset.prompt));
document.getElementById('runBtn').addEventListener('click', runWorkflow);
document.getElementById('policyBtn').addEventListener('click', ()=>{
  const q=document.getElementById('policySearch').value.trim();
  const p=retrievePolicy(q);
  document.getElementById('policyResult').innerHTML = p ? `<b>${p.id} — ${p.title}</b><br>${p.text}` : "No relevant policy found. Escalate instead of inventing an answer.";
});

function renderContacts(){
  const t=document.getElementById('contactsTable');
  t.innerHTML='<thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>City</th></tr></thead><tbody>'+
    DATA.customers.map(c=>`<tr><td>${c.customer_id}</td><td>${c.full_name}</td><td>${c.email}</td><td>${c.phone}</td><td>${c.city}</td></tr>`).join('')+'</tbody>';
}
function renderReservations(){
  const t=document.getElementById('reservationsTable');
  t.innerHTML='<thead><tr><th>Reservation</th><th>Customer</th><th>Hotel</th><th>Check-in</th><th>Check-out</th><th>Room</th><th>Status</th></tr></thead><tbody>'+
    state.reservations.map(r=>{
      const c=DATA.customers.find(x=>x.customer_id===r.customer_id);
      return `<tr><td>${r.reservation_id}</td><td>${c?.full_name||r.customer_id}</td><td>${r.hotel_name}</td><td>${r.check_in}</td><td>${r.check_out}</td><td>${r.room_type}</td><td><span class="badge good">${r.status}</span></td></tr>`
    }).join('')+'</tbody>';
}
function renderCases(){
  const body=document.getElementById('casesBody');
  body.innerHTML=state.cases.map(c=>`<tr><td>${c.case_id}</td><td>${c.customer_name}</td><td>${c.case_type}</td><td><span class="badge ${c.status==='Closed'?'good':'warn'}">${c.status}</span></td><td>${c.resolution}</td></tr>`).join('');
}
function renderAudit(){
  const body=document.getElementById('auditBody');
  if(!state.audit.length){body.innerHTML='<tr><td colspan="4" class="muted">No write operations yet.</td></tr>';return}
  body.innerHTML=state.audit.map(a=>`<tr><td>${a.time}</td><td>${a.action}</td><td>${a.record}</td><td>${a.result}</td></tr>`).join('');
}
function retrievePolicy(q){
  const words=q.toLowerCase().split(/\W+/).filter(Boolean);
  let scored=DATA.policies.map(p=>({p, score:p.keywords.reduce((s,k)=>s+(q.toLowerCase().includes(k)?3:0),0)+words.reduce((s,w)=>s+(p.text.toLowerCase().includes(w)?1:0),0)}));
  scored.sort((a,b)=>b.score-a.score);
  return scored[0]?.score>0?scored[0].p:null;
}
function tool(name, detail){return `<div class="tool"><span class="check">✓</span><div><b>${name}</b><br><span class="muted">${detail}</span></div></div>`}
function preview(customer,res,loyalty){
  return [
    ["Customer",`${customer.full_name} (${customer.customer_id})`],
    ["Email",customer.email],
    ["Reservation",res.reservation_id],
    ["Hotel",res.hotel_name],
    ["Dates",`${res.check_in} → ${res.check_out}`],
    ["Room",res.room_type],
    ["Loyalty",`${loyalty?.tier||"None"} • ${loyalty?.points||0} pts`],
    ["Status",res.status]
  ].map(x=>`<div class="kv"><b>${x[0]}</b><span>${x[1]}</span></div>`).join('');
}

function runWorkflow(){
  const q=document.getElementById('promptBox').value.trim();
  const lower=q.toLowerCase();
  const timeline=document.getElementById('toolTimeline');
  const response=document.getElementById('assistantResponse');
  const approval=document.getElementById('approvalArea');
  const rec=document.getElementById('recordPreview');
  approval.innerHTML=''; timeline.innerHTML=''; response.classList.remove('muted'); rec.classList.remove('muted');

  if(lower.includes("john smith")){
    const matches=DATA.customers.filter(c=>c.full_name==="John Smith");
    timeline.innerHTML=tool("search_customer(name='John Smith')",`${matches.length} matching CRM contacts found.`)+tool("verification_policy()", "Duplicate-name rule retrieved.");
    response.innerHTML=`I found <b>two customers named John Smith</b>. I will not guess which record is correct. Please provide the reservation number or email address before any reservation information is changed.`;
    rec.innerHTML=matches.map(c=>`<div class="kv"><b>${c.customer_id}</b><span>${c.full_name} • ${c.email}</span></div>`).join('');
    return;
  }

  if(lower.includes("gold") || lower.includes("benefit") || lower.includes("late checkout")){
    const c=DATA.customers.find(c=>c.full_name==="Jessica Turner");
    const l=DATA.loyalty.find(x=>x.customer_id===c.customer_id);
    const p=retrievePolicy("Gold late checkout upgrade loyalty");
    timeline.innerHTML=tool("get_customer()",`Retrieved ${c.full_name}.`)+tool("get_loyalty_status()",`${l.tier}, ${l.points.toLocaleString()} points.`)+tool("retrieve_policy()",`${p.id}: ${p.title}.`);
    response.innerHTML=`Jessica Turner is a <b>${l.tier}</b> member. Based on the retrieved policy, Gold members receive priority support, a complimentary room upgrade when available, and late checkout up to <b>2:00 PM when available</b>.`;
    rec.innerHTML=`<div class="kv"><b>Customer</b><span>${c.full_name}</span></div><div class="kv"><b>Tier</b><span>${l.tier}</span></div><div class="kv"><b>Points</b><span>${l.points.toLocaleString()}</span></div><div class="kv"><b>Policy</b><span>${p.id}</span></div>`;
    return;
  }

  const c=DATA.customers.find(c=>c.full_name==="Jessica Turner");
  const r=state.reservations.find(r=>r.customer_id===c.customer_id);
  const l=DATA.loyalty.find(x=>x.customer_id===c.customer_id);
  const p=retrievePolicy("modify reservation dates room availability");
  const key=`${r.hotel_name}|2026-11-10|2026-11-13|${r.room_type}`;
  const avail=DATA.availability[key] ?? 0;
  timeline.innerHTML=
      tool("get_customer()",`Retrieved ${c.full_name} from CRM.`)+
      tool("get_reservation()",`Retrieved ${r.reservation_id}.`)+
      tool("get_loyalty_status()",`${l.tier}, ${l.points.toLocaleString()} points.`)+
      tool("retrieve_policy()",`${p.id}: ${p.title}.`)+
      tool("check_room_availability()",`${r.room_type}: ${avail} rooms available for requested stay.`);

  rec.innerHTML=preview(c,r,l);

  if(avail===0){
    const altQ=DATA.availability[`${r.hotel_name}|2026-11-10|2026-11-13|Deluxe Queen`] || 0;
    const altE=DATA.availability[`${r.hotel_name}|2026-11-10|2026-11-13|Executive King`] || 0;
    response.innerHTML=`The requested <b>${r.room_type}</b> is unavailable for Nov 10–13. I will not modify the reservation automatically.<br><br>Available alternatives: <b>Deluxe Queen (${altQ})</b> or <b>Executive King (${altE})</b>. Select an alternative and approve the write-back.`;
    approval.innerHTML=`<div class="approval">
      <button class="primary" onclick="approveChange('Deluxe Queen')">Approve Deluxe Queen</button>
      <button class="secondary" onclick="approveChange('Executive King')">Approve Executive King</button>
      <button class="secondary danger" onclick="cancelChange()">Do not change</button>
    </div>`;
  }
}

function approveChange(room){
  const r=state.reservations.find(r=>r.customer_id==="C1001");
  const old=`${r.check_in}→${r.check_out}, ${r.room_type}`;
  r.check_in="2026-11-10"; r.check_out="2026-11-13"; r.room_type=room; r.status="Modified";
  const caseObj=state.cases.find(c=>c.customer_id==="C1001");
  caseObj.status="Closed"; caseObj.resolution=`Reservation ${r.reservation_id} moved to Nov 10–13, ${room}, after staff approval.`;
  state.audit.unshift({time:new Date().toLocaleTimeString(),action:"update_reservation()",record:r.reservation_id,result:`${old} → 2026-11-10→2026-11-13, ${room}`});
  state.audit.unshift({time:new Date().toLocaleTimeString(),action:"update_crm_case()",record:caseObj.case_id,result:"Status set to Closed; resolution written"});
  renderReservations(); renderCases(); renderAudit();
  document.getElementById('assistantResponse').innerHTML=`<b>Write-back complete.</b> Reservation ${r.reservation_id} is now Nov 10–13 in a ${room}. CRM case ${caseObj.case_id} was updated and closed.`;
  document.getElementById('recordPreview').innerHTML=preview(DATA.customers.find(c=>c.customer_id==="C1001"),r,DATA.loyalty.find(l=>l.customer_id==="C1001"));
  document.getElementById('approvalArea').innerHTML='';
  document.getElementById('toolTimeline').innerHTML += tool("update_reservation()",`Reservation ${r.reservation_id} updated after explicit approval.`)+tool("update_crm_case()",`Case ${caseObj.case_id} resolution written and closed.`);
}
function cancelChange(){
  document.getElementById('assistantResponse').innerHTML="No changes were made. The reservation remains unchanged.";
  document.getElementById('approvalArea').innerHTML='';
}
