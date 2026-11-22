/* Street Fix report chat: guided public reporting with rules-based triage.
   Posts each report to /api/cases/ (intake.views.create_report). */
(function(){
/* BACKEND CONNECTION
   window.STREETFIX_API not set -> demo mode: nothing is sent, the reference is made up in the browser.
   window.STREETFIX_API = ""    -> page is served by the backend (e.g. Django): POSTs to /api/cases/
   window.STREETFIX_API = "http://localhost:8000" -> backend on another address (needs CORS on the backend) */
const API_BASE=(typeof window.STREETFIX_API==="string")?window.STREETFIX_API.replace(/\/$/,""):null;
function getCookie(n){const m=document.cookie.match(new RegExp("(?:^|; )"+n+"=([^;]*)"));return m?decodeURIComponent(m[1]):null}
/* Categories, sub-issues and urgency hold translation keys; data sent to the backend is always English. */
const CATS={
  pothole:{key:"c_pothole",team:"tm_highways",def:"High"},flytip:{key:"c_flytip",team:"tm_cleansing",def:"Medium"},
  light:{key:"c_light",team:"tm_lighting",def:"Medium"},graffiti:{key:"c_graffiti",team:"tm_cleansing",def:"Low"},
  sign:{key:"c_sign",team:"tm_highways",def:"Medium"},parks:{key:"c_parks",team:"tm_parks",def:"Medium"},
  drain:{key:"c_drain",team:"tm_highways",def:"High"},other:{key:"c_other",team:"tm_triage",def:"Medium"}
};
const SUBS={
  pothole:{q:"sq_pothole",opts:[{k:"po_small"},{k:"po_large",raise:"High"},{k:"po_several",raise:"High"},{k:"po_pave",raise:"High"},{k:"po_sunk"}]},
  flytip:{q:"sq_flytip",opts:[{k:"ft_bags"},{k:"ft_furn"},{k:"ft_rubble"},{k:"ft_tyres"},{k:"ft_haz",raise:"Urgent"},{k:"ft_block",raise:"High"}]},
  light:{q:"sq_light",opts:[{k:"li_out"},{k:"li_flick"},{k:"li_day",raise:"Low"},{k:"li_wires",raise:"Urgent"},{k:"li_lean",raise:"Urgent"},{k:"li_door",raise:"Urgent"}]},
  graffiti:{q:"sq_graffiti",opts:[{k:"gr_wall"},{k:"gr_stop"},{k:"gr_sign",raise:"High"},{k:"gr_off",raise:"High"}]},
  sign:{q:"sq_sign",opts:[{k:"sg_bent"},{k:"sg_missing"},{k:"sg_read"},{k:"sg_fallen",raise:"High"},{k:"sg_junction",raise:"High"}]}
};
const KEYWORDS={
  pothole:[/pot ?holes?/,/hole in (the )?road/,/crater/,/road surface/,/cracked (road|tarmac)/,/sunken/],
  flytip:[/fly.?tip/,/dump(ed|ing)/,/rubbish/,/mattress/,/sofa/,/bin bags?/,/waste/,/tyres?/,/litter/],
  light:[/street ?lights?/,/lamp ?post/,/\blamp\b/,/light (is |has )?(out|off|broken|gone)/,/flicker/],
  graffiti:[/graffiti/,/spray ?paint/,/tagg(ed|ing)/],
  sign:[/\bsigns?\b/,/signpost/,/bollard/],
  parks:[/\btrees?\b/,/branch/,/\bpark\b/,/playground/,/bench/,/grass/,/hedge/],
  drain:[/drain/,/flood/,/gully/,/standing water/]
};
const HAZARD=[
  {re:/injur|hurt|\bfell\b|tripped|accident/,why:"mentions someone hurt or an accident",to:"Urgent"},
  {re:/exposed (wire|cable)|live wire|sparking|electric/,why:"mentions exposed electrics",to:"Urgent"},
  {re:/needle|syringe|asbestos|chemical|gas smell|fire|burning/,why:"mentions a hazardous material",to:"Urgent"},
  {re:/manhole|open hole|uncovered/,why:"mentions an open or uncovered hole",to:"Urgent"},
  {re:/fallen tree|fallen branch|tree down|branch(es)? (has |have )?fallen/,why:"mentions a fallen tree or branch",to:"Urgent"},
  {re:/school|child|kids|pram|wheelchair|elderly|disabled|blind/,why:"could affect children or vulnerable people",to:"High"},
  {re:/blocking|blocked (the )?(road|path|pavement)|can'?t (get|pass)|main road|junction|crossing|bus stop/,why:"blocks or affects a road, path or crossing",to:"High"}
];
const ORDER=["Low","Medium","High","Urgent"];
const SLA={Urgent:{ackH:1,resD:1},High:{ackH:4,resD:3},Medium:{ackD:1,resD:10},Low:{ackD:2,resD:20}};
const URG=[{id:"Urgent",k:"u_Urgent",h:"uh_Urgent"},{id:"High",k:"u_High",h:"uh_High"},{id:"Medium",k:"u_Medium"},{id:"Low",k:"u_Low"},{id:null,k:"u_unsure"}];
const METHODS=[["Email","m_email"],["Text message","m_text"],["Phone call","m_call"]];
const EXISTING=[
  {ref:"SF-2026-0412",cat:"pothole",out:"B15",days:2,note:"Deep pothole by the bus stop"},
  {ref:"SF-2026-0418",cat:"flytip",out:"B11",days:1,note:"Mattress and bin bags dumped in an alley"},
  {ref:"SF-2026-0405",cat:"light",out:"B29",days:4,note:"Two streetlights out on a residential street"}
];
const LANGS=[["English","en","English"],["Polski","pl","Polish"],["اردو (Urdu)","ur","Urdu"],["ਪੰਜਾਬੀ (Punjabi)","pa","Punjabi"],["العربية (Arabic)","ar","Arabic"],["Română","ro","Romanian"]];
const LOCALE={en:"en-GB",pl:"pl-PL",ur:"ur-PK",pa:"pa-IN",ar:"ar-u-nu-latn",ro:"ro-RO"};
const RTL=["ur","ar"];
const STAGE_OF={welcome:0,language:0,intro:0,category:0,otherText:0,awaitConfirm:0,subissue:0,description:0,postcode:1,landmark:1,photo:2,urgency:3,dup:3,
  updates:4,method:4,email:4,phone:4,name:4,review:5,editMenu:5,refAsk:6,done:6};

let lang="en";
function t(k,v){let s=(L[lang]&&L[lang][k])||L.en[k]||k;if(v)for(const x in v)s=s.split("{"+x+"}").join(v[x]);return s}
const en=k=>L.en[k];

const $=s=>document.querySelector(s);
const log=$("#log"),msg=$("#msg"),err=$("#err"),photoBtn=$("#photoBtn"),fileInput=$("#fileInput"),chat=$(".chat");
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;

let C,current,editing,reference;
function fresh(){C={category:null,categorySource:null,subKey:null,subissue:"",subRaise:null,otherText:"",description:"",postcode:"",outward:"",postcodeKnown:null,landmark:"",
  photo:null,photoName:"",urgency:undefined,wantsUpdates:null,contactMethod:"",email:"",phone:"",name:"",language:"",languageLabel:"",
  duplicateOf:null,possibleDuplicate:null,nearby:null,wantsReference:null,submittedAt:null};editing=false;reference=null;lang="en";applyLang();}

function scroll(){log.scrollTop=log.scrollHeight}
function addRow(cls,html){const r=document.createElement("div");r.className="rc-row rc-"+cls;r.innerHTML=html;log.appendChild(r);scroll();return r}
function user(text,extra){addRow("user",`<div class="rc-bubble">${extra||""}${text?`<p>${esc(text)}</p>`:""}</div>`)}
let queue=Promise.resolve();
function bot(html,opts={}){
  queue=queue.then(()=>new Promise(res=>{
    const tp=addRow("bot",`<div class="rc-bubble rc-typing" aria-hidden="true"><i></i><i></i><i></i></div>`);
    setTimeout(()=>{tp.remove();
      const r=addRow("bot",`<span class="rc-meta">${esc(t("who"))}</span><div class="rc-bubble">${html}</div>`);
      if(opts.chips){const c=document.createElement("div");c.className="rc-chips";
        opts.chips.forEach(ch=>{const b=document.createElement("button");b.type="button";b.className="sf-button rc-chip "+(ch.cls==="primary"?"sf-button":ch.cls==="quiet"?"sf-button--secondary rc-quiet":"sf-button--secondary");
          b.innerHTML=esc(ch.label)+(ch.hint?`<span class="rc-meta rc-block">${esc(ch.hint)}</span>`:"");
          b.addEventListener("click",()=>{if(!ch.keep)c.classList.add("done");ch.on()});c.appendChild(b)});
        r.appendChild(c);}
      scroll();res();},reduced?0:450);
  }));
  return queue;
}
const p=s=>`<p>${esc(s)}</p>`, note=s=>`<p class="rc-meta">${esc(s)}</p>`;
function clearChips(){log.querySelectorAll(".rc-chips").forEach(c=>c.classList.add("done"))}
function setInput(key,{type="off",mode="text",photo=false}={}){
  const label=t(key);$("#msgLabel").textContent=label;msg.placeholder=label;msg.setAttribute("inputmode",mode);
  msg.setAttribute("autocomplete",type);photoBtn.disabled=!photo;err.textContent="";
}
const skip=(key,to,fn)=>({label:t(key),cls:"quiet",on:()=>{user(t(key));fn&&fn();next(to)}});
function applyLang(){
  chat.setAttribute("lang",lang);chat.dir=RTL.includes(lang)?"rtl":"ltr";
  $("#chatTitle").textContent=t("title");$("#sub").textContent=t("sub");$("#sendBtn").textContent=t("send");photoBtn.setAttribute("aria-label",t("add_photo"));
}

function classify(text){const s=text.toLowerCase();let best=null,score=0;
  for(const [k,res] of Object.entries(KEYWORDS)){const n=res.filter(r=>r.test(s)).length;if(n>score){score=n;best=k}}return best}
function addWorking(d,days){const x=new Date(d);let n=days;while(n>0){x.setDate(x.getDate()+1);if(x.getDay()%6!==0)n--}return x}
const urgLabel=(id,english)=>{const u=URG.find(x=>x.id===id);return english?en(u.k):t(u.k)};
function triage(){
  const reasons=[];if(!C.category)return null;
  const cat=CATS[C.category];let pr;
  if(C.urgency){pr=C.urgency;reasons.push(`Reporter chose "${urgLabel(C.urgency,true)}"`)}
  else if(C.urgency===null){pr=cat.def;reasons.push("Reporter wasn't sure, so the usual priority for this issue was used")}
  else pr=cat.def;
  if(ORDER.indexOf(cat.def)>ORDER.indexOf(pr)){pr=cat.def;reasons.push(`${en(cat.key)} is ${cat.def} priority by default`)}
  if(C.subRaise&&ORDER.indexOf(C.subRaise)>ORDER.indexOf(pr)){pr=C.subRaise;reasons.push(`Raised to ${pr}: "${C.subissue}"`)}
  const text=[C.otherText,C.subissue,C.description,C.landmark].join(" ").toLowerCase();
  HAZARD.forEach(h=>{if(h.re.test(text)&&ORDER.indexOf(h.to)>ORDER.indexOf(pr)){pr=h.to;reasons.push(`Raised to ${h.to}: the description ${h.why}`)}});
  const now=C.submittedAt?new Date(C.submittedAt):new Date(),s=SLA[pr];
  const ackDue=s.ackH?new Date(now.getTime()+s.ackH*3600e3):addWorking(now,s.ackD);
  return {category:C.category,teamKey:cat.team,priority:pr,reasons,ackDue,resolveDue:addWorking(now,s.resD)};
}

/* Is there an open job that may be the same problem? Demo mode uses sample cases;
   connected mode asks the server for open work of the same type nearby. */
async function checkDuplicate(){
  if(!C.outward)return null;
  if(API_BASE===null){const e=EXISTING.find(x=>x.cat===C.category&&x.out===C.outward);return e?{ref:e.ref}:null}
  try{
    const q=new URLSearchParams({category:C.category,postcode:C.postcode});
    const r=await fetch(API_BASE+"/api/cases/nearby/?"+q,{credentials:"same-origin"});
    if(!r.ok)return null;
    const j=await r.json();return j.match?{ref:j.match.reference}:null;
  }catch(e){return null}
}
/* Priority as a UIkit label: danger/warning colours come from the theme. */
const PRIORITY_LABEL={Urgent:"sf-priority--danger",High:"sf-priority--warning",Medium:"",Low:"rc-label-low"};
const priorityLabel=(pr,text)=>`<span class="sf-priority ${PRIORITY_LABEL[pr]}">${esc(text)}</span>`;
const subText=()=>C.subKey?t(C.subKey):C.subissue;

/* ---------- steps, in the order a customer meets them ---------- */
const steps={
  welcome(){go("language")},
  language(){
    setInput("ph_choose");$("#msgLabel").textContent=msg.placeholder="Choose a language, or type another";
    bot(`<p lang="en">Which language would you like to use?</p><p lang="pl">Wybierz język</p><p lang="ur" dir="rtl">اپنی زبان منتخب کریں</p><p lang="pa">ਆਪਣੀ ਭਾਸ਼ਾ ਚੁਣੋ</p><p lang="ar" dir="rtl">اختر لغتك</p><p lang="ro">Alegeți limba</p><p class="ai-note">You can also type another language.</p>`,
      {chips:LANGS.map(([label,code,name])=>({label,on:()=>{user(label);setLang(code,name,label)}}))});
  },
  intro(){
    if(lang!=="en")bot(note(t("ai_trans")));
    else if(C.language&&C.language!=="English")bot(note(`This chat will continue in English. We'll try to send your updates in ${C.language}.`));
    bot(p(t("hi")));
    bot(p(t("auto"))+`<div class="sf-alert sf-alert--danger" role="note">${esc(t("emerg"))}</div>`);
    go("category");
  },
  /* 1. Problem */
  category(){
    setInput("ph_cat");
    const opts=["pothole","flytip","light","graffiti","sign"].map(k=>({label:t(CATS[k].key),on:()=>{user(t(CATS[k].key));setCat(k,"Chosen by reporter");next("subissue")}}));
    opts.push({label:t("something_else"),cls:"quiet",on:()=>{user(t("something_else"));go("otherText")}});
    bot(p(t("q_cat")),{chips:opts});
  },
  otherText(){setInput("ph_other");bot(p(t("q_other")))},
  subissue(){
    const sub=SUBS[C.category];if(!sub){next(C.otherText?"postcode":"description");return}
    setInput("ph_sub");
    bot(p(t(sub.q)),{chips:sub.opts.map(o=>({label:t(o.k),on:()=>{user(t(o.k));C.subKey=o.k;C.subissue=en(o.k);C.subRaise=o.raise||null;next("description")}}))
      .concat([{label:t("something_else"),cls:"quiet",on:()=>{user(t("something_else"));bot(p(t("tell_more")));setInput("ph_seen")}}])});
  },
  description(){setInput("ph_desc");bot(p(t("q_desc")),{chips:[skip("no_all","postcode")]})},
  /* 2. Location */
  postcode(){
    setInput("ph_pc",{type:"postal-code"});
    bot(p(t("q_pc")),{chips:[{label:t("no_pc"),cls:"quiet",on:()=>{user(t("no_pc"));C.postcode="";C.outward="";C.postcodeKnown=false;go("landmark")}}]});
  },
  landmark(){
    if(C.postcodeKnown===false){setInput("ph_lm_req",{type:"street-address"});bot(p(t("q_lm_req"))+note(t("lm_eg")))}
    else{setInput("ph_lm_opt",{type:"street-address"});bot(p(t("q_lm_opt")),{chips:[skip("skip","photo")]})}
  },
  /* 3. Photo */
  photo(){
    setInput("ph_photo",{photo:true});
    bot(p(t("q_photo")),{chips:[{label:t("add_photo"),cls:"primary",keep:true,on:()=>fileInput.click()},skip("skip","urgency")]});
  },
  /* 4. Urgency */
  urgency(){
    setInput("ph_choose");
    bot(p(t("q_urg")),{chips:URG.map(u=>({label:t(u.k),hint:u.h?t(u.h):"",on:()=>{user(t(u.k));C.urgency=u.id;
      if(editing){next("updates");return}checkDuplicate().then(d=>{C.nearby=d;if(d)go("dup");else next("updates")})}}))});
  },
  dup(){
    const d=C.nearby;if(!d){next("updates");return}
    setInput("ph_choose");
    bot(p(t("dup_q",{area:C.outward,ref:d.ref})),{chips:[
      {label:t("yes_same"),on:()=>{user(t("yes_same"));C.duplicateOf=d.ref;C.possibleDuplicate=null;bot(p(t("dup_linked")));next("updates")}},
      {label:t("no_diff"),on:()=>{user(t("no_diff"));C.duplicateOf=null;C.possibleDuplicate=null;next("updates")}},
      {label:t("not_sure"),cls:"quiet",on:()=>{user(t("not_sure"));C.duplicateOf=null;C.possibleDuplicate=d.ref;bot(p(t("dup_check")));next("updates")}}]});
  },
  /* 5. Updates (optional) */
  updates(){
    setInput("ph_choose");
    bot(p(t("q_upd")),{chips:[
      {label:t("yes_upd"),on:()=>{user(t("yes_upd"));C.wantsUpdates=true;go("method")}},
      {label:t("no_thanks"),cls:"quiet",on:()=>{user(t("no_thanks"));Object.assign(C,{wantsUpdates:false,contactMethod:"",email:"",phone:"",name:""});
        bot(p(t("no_upd_ok")));go("review")}}]});
  },
  method(){
    setInput("ph_choose");
    bot(p(t("q_method")),{chips:METHODS.map(([v,k])=>({label:t(k),on:()=>{user(t(k));C.contactMethod=v;if(v==="Email"){C.phone="";go("email")}else{C.email="";go("phone")}}}))});
  },
  email(){setInput("ph_email",{type:"email",mode:"email"});bot(p(t("q_email")))},
  phone(){setInput("ph_phone",{type:"tel",mode:"tel"});bot(p(t("q_phone")))},
  name(){setInput("ph_name",{type:"given-name"});bot(p(t("q_name")),{chips:[skip("skip","review",()=>{C.name=""})]})},
  /* 6. Check and send */
  review(){
    editing=false;setInput("ph_choose");
    const m=METHODS.find(x=>x[0]===C.contactMethod);
    const rows=[["r_problem",t(CATS[C.category].key)+(C.otherText?` (“${C.otherText}”)`:"")],["r_what",subText()],["r_details",C.description],
      ["r_where",[C.postcode,C.landmark].filter(Boolean).join(", ")||t("not_given")],["r_photo",C.photo?t("added"):t("none")],["r_urg",urgLabel(C.urgency??null)],
      ["r_upd",C.wantsUpdates?`${t(m[1])}: ${C.email||C.phone}`:t("no_updates")],["r_name",C.name],["r_lang",C.languageLabel]];
    bot(p(t("review_intro"))+`<dl class="rc-summary">${rows.filter(r=>r[1]).map(([k,v])=>`<dt>${esc(t(k))}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`+note(t(C.wantsUpdates?"consent_yes":"consent_no")),
      {chips:[{label:t("send_report"),cls:"primary",on:submit},{label:t("change"),cls:"quiet",on:()=>{user(t("change"));go("editMenu")}}]});
  },
  editMenu(){
    setInput("ph_edit");
    const f=[["r_lang","language"],["r_problem","category"],["r_details","description"],["st1","postcode"],["r_photo","photo"],["r_urg","urgency"],["e_upd","updates"]];
    bot(p(t("q_change")),{chips:f.map(([k,s])=>({label:t(k),on:()=>{user(t(k));editing=true;
      if(s==="photo")C.photo=null;if(s==="category"){C.subKey=null;C.subissue="";C.subRaise=null;C.otherText=""}
      if(s==="postcode"){C.landmark="";C.duplicateOf=null;C.possibleDuplicate=null}go(s)}}))
      .concat([skip("e_back","review")])});
  },
  refAsk(){
    setInput("ph_choose");
    bot(p(t("sent_to",{team:t(CATS[C.category].team)})+(C.duplicateOf?" "+t("added_case",{ref:C.duplicateOf}):""))+p(t("q_ref")),{chips:[
      {label:t("yes_ref"),on:()=>{user(t("yes_ref"));C.wantsReference=true;go("done")}},
      {label:t("no_thanks"),cls:"quiet",on:()=>{user(t("no_thanks"));C.wantsReference=false;go("done")}}]});
  },
  done(){
    setInput("ph_sent");
    const tr=triage(),fmt=d=>d.toLocaleString(LOCALE[lang],{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
    const how={"Email":"n3_email","Text message":"n3_text","Phone call":"n3_call"}[C.contactMethod];
    bot(`${C.wantsReference?p(t("ref_is"))+`<p class="rc-ref" dir="ltr">${reference}</p>`+note(t("ref_keep")):p(t("no_problem"))}
      <dl class="rc-summary">
        <dt>${esc(t("d_priority"))}</dt><dd>${priorityLabel(tr.priority,t("p_"+tr.priority))} <span class="rc-meta">${esc(t("ai_pri"))}</span></dd>
        <dt>${esc(t("d_look"))}</dt><dd><bdi>${esc(fmt(tr.ackDue))}</bdi> (${esc(t("ack_"+tr.priority))})</dd>
        <dt>${esc(t("d_fix"))}</dt><dd>${esc(t("fix_"+tr.priority))}</dd>
      </dl>
      <p class="rc-next-title">${esc(t("next_h"))}</p>
      <ol class="rc-next-list"><li>${esc(t("n1"))}</li><li>${esc(t("n2"))}</li><li>${esc(t(C.wantsUpdates?how:"n3_none"))}</li></ol>`+(API_BASE===null?note(t("proto")):""),
      {chips:[{label:t("another"),on:()=>{log.innerHTML="";fresh();go("welcome")}}]});
  }
};
function setCat(k,src){C.category=k;C.categorySource=src}
function setLang(code,name,label){lang=code;C.language=name;C.languageLabel=label;applyLang();go(editing?"review":"intro")}
function go(id){current=id;render();steps[id]()}
const FLOW_INTERNAL=["otherText","subissue","landmark","dup","method","email","phone","name"];
function next(id){if(!editing||FLOW_INTERNAL.includes(id))go(id);else go("review")}

/* ---------- typed answers ---------- */
const validators={
  postcode(v){const m=v.toUpperCase().replace(/\s+/g,"").match(/^([A-Z]{1,2}\d[A-Z\d]?)(\d[A-Z]{2})$/);
    if(!m)return "err_pc";C.postcode=m[1]+" "+m[2];C.outward=m[1];C.postcodeKnown=true;},
  name(v){if(v.length<1)return "err_name";C.name=v.slice(0,60)},
  email(v){if(!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v))return "err_email";C.email=v},
  phone(v){const d=v.replace(/[\s()-]/g,"");if(!/^(?:\+44|0)\d{9,10}$/.test(d))return "err_phone";C.phone=v},
  landmark(v){if(v.length<4)return "err_lm";C.landmark=v.slice(0,200)}
};
const AFTER={postcode:"landmark",landmark:"photo",email:"name",phone:"name",name:"review"};
function onText(v){
  err.textContent="";
  switch(current){
    case "language":clearChips();user(v);{const m=LANGS.find(l=>l[0].toLowerCase().includes(v.toLowerCase())||l[2].toLowerCase()===v.toLowerCase());
      if(m)setLang(m[1],m[2],m[0]);else setLang("en",v.slice(0,40),v.slice(0,40));}return;
    case "category":case "otherText":{
      clearChips();user(v);C.otherText=v.slice(0,300);const m=classify(v);
      if(m){current="awaitConfirm";bot(p(t("ai_cat",{cat:t(CATS[m].key)}))+note(t("ai_sugg")),{chips:[
        {label:t("yes_right"),on:()=>{user(t("yes_right"));setCat(m,"AI-suggested, confirmed by reporter");next("subissue")}},
        {label:t("no"),cls:"quiet",on:()=>{user(t("no"));setCat("other","Needs a person to categorise");bot(p(t("desk_no")));next("postcode")}}]});}
      else{setCat("other","Needs a person to categorise");bot(p(t("desk_unmatched")));next("postcode")}
      return}
    case "subissue":clearChips();user(v);C.subKey=null;C.subissue=v.slice(0,200);C.subRaise=null;next("description");return;
    case "description":clearChips();user(v);C.description=v.slice(0,600);next("postcode");return;
    case "postcode":case "landmark":case "name":case "email":case "phone":{
      const e=validators[current](v);if(e){err.textContent=t(e);msg.focus();return}
      clearChips();user(current==="postcode"?C.postcode:v);next(AFTER[current]);return}
    default:err.textContent=t("err_choose");
  }
}
$("#composer").addEventListener("submit",e=>{e.preventDefault();const v=msg.value.trim();if(!v)return;msg.value="";onText(v)});

photoBtn.addEventListener("click",()=>fileInput.click());
/* Photos are shrunk in the browser (max 1600 px, JPEG) so a report stays well under hosting limits
   such as Vercel's 4.5 MB request size, and sends quickly on mobile data. */
function shrinkPhoto(file,maxSide=1600,maxBytes=1200000){
  return new Promise((resolve,reject)=>{
    const url=URL.createObjectURL(file),img=new Image();
    img.onload=()=>{
      const scale=Math.min(1,maxSide/Math.max(img.naturalWidth,img.naturalHeight));
      const c=document.createElement("canvas");c.width=Math.round(img.naturalWidth*scale);c.height=Math.round(img.naturalHeight*scale);
      const g=c.getContext("2d");g.fillStyle="#fff";g.fillRect(0,0,c.width,c.height);g.drawImage(img,0,0,c.width,c.height);
      URL.revokeObjectURL(url);
      let q=0.82,out=c.toDataURL("image/jpeg",q);
      while(out.length*0.75>maxBytes&&q>0.4){q-=0.1;out=c.toDataURL("image/jpeg",q)}
      resolve(out);
    };
    img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("unreadable image"))};
    img.src=url;
  });
}
fileInput.addEventListener("change",async()=>{
  const f=fileInput.files[0];fileInput.value="";if(!f)return;
  if(!f.type.startsWith("image/")){err.textContent=t("err_file");return}
  if(f.size>40*1024*1024){err.textContent=t("err_big");return}
  let data;try{data=await shrinkPhoto(f)}catch(e){err.textContent=t("err_file");return}
  C.photo=data;C.photoName=f.name;clearChips();
  user("",`<img src="${data}" alt="">`);bot(p(t("thanks_photo")));next("urgency");
});

async function submit(){
  user(t("send_report"));C.submittedAt=new Date().toISOString();
  if(API_BASE===null){reference="SF-2026-"+String(Math.floor(1000+Math.random()*8999));go("refAsk");return}
  const body=payload(triage());body.case.photo=C.photo||null;body.case.status="New – awaiting triage";
  try{
    const r=await fetch(API_BASE+"/api/cases/",{method:"POST",credentials:"same-origin",
      headers:{"Content-Type":"application/json","X-CSRFToken":getCookie("csrftoken")||""},body:JSON.stringify(body)});
    if(!r.ok)throw new Error("HTTP "+r.status);
    reference=(await r.json()).reference;go("refAsk");
  }catch(e){console.error("Street Fix: sending failed",e);C.submittedAt=null;bot(p(t("err_send")));go("review")}
}

/* ---------- staff side panel (always English) ---------- */
function render(){
  const st=STAGE_OF[current]??0;
  const shown=Math.min(st,5);
  $("#progress").innerHTML=`<div class="rc-progress-label rc-meta"><span>${esc(t("st"+shown))}</span><span dir="ltr">${shown+1} / 6</span></div>`+
    `<progress class="sf-progress" value="${st>5?6:shown}" max="6" aria-label="${esc(t("st"+shown))}"></progress>`;
  if(!$("#casePanel"))return; /* staff panel is only on the page for signed-in staff */
  const rows=[["Language",C.language],["Problem",C.category?en(CATS[C.category].key):""],["What exactly",C.subissue],["Details",C.description||C.otherText],
    ["Postcode",C.postcode||(C.postcodeKnown===false?"Not known":"")],["Location",C.landmark],["Photo",C.photo?C.photoName||"Added":""],
    ["Urgency",C.urgency===undefined?"":urgLabel(C.urgency,true)],["Updates",C.wantsUpdates===null?"":C.wantsUpdates?C.contactMethod:"No"],
    ["Contact",C.email||C.phone],["Name",C.name],["Reference",C.wantsReference===null?"":C.wantsReference?"Wanted":"Not wanted"]];
  $("#fields").innerHTML=rows.map(([k,v])=>`<li class="rc-field"><span class="${v?"rc-field-complete":"rc-muted"}" aria-hidden="true">${v?"✓":"–"}</span><span class="rc-muted">${k}</span><span>${v?esc(v):"<span class='rc-muted'>—</span>"}</span></li>`).join("");
  const tr=triage(),tri=$("#triage");
  if(!tr){tri.innerHTML=`<p class="rc-meta ">Triage appears once the problem is known.</p>`}
  else tri.innerHTML=`
    <div><div class="rc-lbl">Category</div>${esc(en(CATS[C.category].key))}${C.subissue?` · ${esc(C.subissue)}`:""}<div class="rc-meta">${esc(C.categorySource||"")}</div></div>
    <div><div class="rc-lbl">Route to</div>${esc(en(tr.teamKey))}${C.duplicateOf?" (linked case)":""}</div>
    <div><div class="rc-lbl">Suggested priority</div>${priorityLabel(tr.priority,tr.priority)}${tr.reasons.length?`<ul class="rc-reasons">${tr.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`:""}</div>
    <div><div class="rc-lbl">SLA</div>Acknowledge ${en("ack_"+tr.priority)}, resolve within ${en("fix_"+tr.priority)}</div>
    ${C.duplicateOf||C.possibleDuplicate?`<div><div class="rc-lbl">Duplicate check</div>${C.duplicateOf?"Linked to "+C.duplicateOf:"Possible duplicate of "+C.possibleDuplicate+", to check"}</div>`:""}
    ${C.postcodeKnown===false?`<div><div class="rc-lbl">Location check</div>No postcode. Officer to confirm the location from the description.</div>`:""}
    ${lang!=="en"?`<div><div class="rc-lbl">Language</div>Reporter used the ${esc(C.language)} chat. Any typed text may need translating.</div>`:""}
    <div><div class="rc-lbl">Status</div>${reference?"Submitted, awaiting triage officer approval":"Draft"}</div>`;
  $("#json").textContent=JSON.stringify(payload(tr),null,2);
}
function payload(tr){
  return {case:{reference:reference,reference_shown_to_reporter:C.wantsReference,
    title:C.category?en(CATS[C.category].key)+(C.subissue?" – "+C.subissue:""):null,
    category:tr?tr.category:null,sub_issue:C.subissue||null,category_source:C.categorySource,
    description:[C.otherText,C.description].filter(Boolean).join(" | ")||null,chat_language:C.language||null,
    priority_suggested:tr?tr.priority:null,priority_reasons:tr?tr.reasons:[],priority_confirmed:null,reporter_urgency:C.urgency??null,
    status:reference?"New – awaiting triage":"Draft",
    location:{postcode:C.postcode||null,postcode_known:C.postcodeKnown,description:C.landmark||null,latitude:null,longitude:null},
    date_reported:C.submittedAt,assigned_team:tr?en(tr.teamKey):null,assigned_officer:null,
    sla_ack_due:tr&&reference?tr.ackDue.toISOString():null,sla_resolve_due:tr&&reference?tr.resolveDue.toISOString():null,
    duplicate_of:C.duplicateOf,possible_duplicate_of:C.possibleDuplicate,has_photo:!!C.photo,
    ai_used:(C.categorySource&&C.categorySource.startsWith("AI")?["category_suggestion"]:[]).concat(["priority_suggestion"],lang!=="en"?["chat_translation"]:[])},
    reporter:C.wantsUpdates?{name:C.name||null,email:C.email||null,phone:C.phone||null,preferred_contact:C.contactMethod,preferred_language:C.language||null,wants_updates:true}
      :{wants_updates:C.wantsUpdates,preferred_language:C.language||null}};
}
$("#copyJson")?.addEventListener("click",()=>{const txt=$("#json").textContent;
  navigator.clipboard.writeText(txt).then(()=>{$("#copyJson").textContent="Copied"},()=>{const s=getSelection(),r=document.createRange();r.selectNodeContents($("#json"));s.removeAllRanges();s.addRange(r);$("#copyJson").textContent="Selected, press Ctrl+C"})});


fresh();go("welcome");
})();
