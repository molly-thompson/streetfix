/* Public report chat: guided reporting with a rules-based first suggestion.
   Posts each report to /api/cases/ (intake.views.CreateReportView), where it waits for a person to review it. */
(function(){
/* BACKEND CONNECTION
   window.REPORT_CHAT_API not set -> demo mode: nothing is sent, the reference is made up in the browser.
   window.REPORT_CHAT_API = ""    -> page is served by the backend (e.g. Django): POSTs to /api/cases/
   window.REPORT_CHAT_API = "http://localhost:8000" -> backend on another address (needs CORS on the backend) */
const API_BASE=(typeof window.REPORT_CHAT_API==="string")?window.REPORT_CHAT_API.replace(/\/$/,""):null;
/* Deployment options from the server: whether photos and a location map are offered, and their URLs. */
/* The deployment's own name, so the assistant introduces itself as that site. */
const SITE=(typeof window.REPORT_CHAT_SITE==="string"&&window.REPORT_CHAT_SITE)||"report";
const CONFIG=(()=>{const e=document.getElementById("chat-config");return e?JSON.parse(e.textContent):{}})();
function getCookie(n){const m=document.cookie.match(new RegExp("(?:^|; )"+n+"=([^;]*)"));return m?decodeURIComponent(m[1]):null}
/* Existing translations are reused only when the configured label is unchanged. */
const CATEGORY_TRANSLATIONS={pothole:"c_pothole",flytip:"c_flytip",light:"c_light",graffiti:"c_graffiti",
  sign:"c_sign",parks:"c_parks",drain:"c_drain",other:"c_other"};
const SUBISSUE_TRANSLATIONS={
  pothole:{small:"po_small",large:"po_large",several:"po_several"},
  flytip:{bags:"ft_bags",hazardous:"ft_haz",blocking:"ft_block"},
  light:{out:"li_out",wires:"li_wires",leaning:"li_lean"}
};
const CATS=Object.fromEntries((CONFIG.issueTypes||[]).map(issue=>[`issue-${issue.id}`,{
  id:issue.id,name:issue.name,team:issue.team,def:issue.priority,
  key:CATEGORY_TRANSLATIONS[issue.translationCode],
  subissues:issue.subissues.map(sub=>({...sub,key:SUBISSUE_TRANSLATIONS[issue.translationCode]?.[sub.translationCode]})),
  keywords:issue.keywords
}]));
CATS.other={id:null,name:"Other (needs review)",key:"c_other",team:"",def:"Medium",subissues:[],keywords:[]};
const KEYWORDS={};
for(const [id,cat] of Object.entries(CATS)){
  KEYWORDS[id]=cat.keywords.flatMap(pattern=>{
    try{return [new RegExp(pattern,"i")]}
    catch(error){console.error("Invalid configured category keyword",error);return []}
  });
}
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
const SLA=CONFIG.slas||{};
const URG=[{id:"Urgent",k:"u_Urgent",h:"uh_Urgent"},{id:"High",k:"u_High",h:"uh_High"},{id:"Medium",k:"u_Medium"},{id:"Low",k:"u_Low"},{id:null,k:"u_unsure"}];
const METHODS=[["Email","m_email"],["Text message","m_text"],["Phone call","m_call"]];
const EXISTING=[
  {ref:"DEMO-0412",cat:"pothole",out:"B15",days:2,note:"Deep pothole by the bus stop"},
  {ref:"DEMO-0418",cat:"flytip",out:"B11",days:1,note:"Mattress and bin bags dumped in an alley"},
  {ref:"DEMO-0405",cat:"light",out:"B29",days:4,note:"Two streetlights out on a residential street"}
];
const LANGS=[["English","en","English"],["Polski","pl","Polish"],["اردو (Urdu)","ur","Urdu"],["ਪੰਜਾਬੀ (Punjabi)","pa","Punjabi"],["العربية (Arabic)","ar","Arabic"],["Română","ro","Romanian"]];
const LOCALE={en:"en-GB",pl:"pl-PL",ur:"ur-PK",pa:"pa-IN",ar:"ar-u-nu-latn",ro:"ro-RO"};
const RTL=["ur","ar"];
const STAGE_OF={welcome:0,language:0,intro:0,category:0,otherText:0,awaitConfirm:0,subissue:0,description:0,postcode:1,landmark:1,map:1,photo:2,urgency:3,dup:3,
  updates:4,method:4,email:4,phone:4,name:4,review:5,editMenu:5,refAsk:6,done:6};

let lang="en";
function t(k,v){let s=(CHAT_TEXT[lang]&&CHAT_TEXT[lang][k])||CHAT_TEXT.en[k]||k;if(v)for(const x in v)s=s.split("{"+x+"}").join(v[x]);return s}
const en=k=>CHAT_TEXT.en[k];
function categoryLabel(id,english=false){
  const cat=CATS[id];
  return cat.key&&en(cat.key)===cat.name?(english?en(cat.key):t(cat.key)):cat.name;
}

const $=s=>document.querySelector(s);
const log=$("#log"),msg=$("#msg"),err=$("#err"),photoBtn=$("#photoBtn"),fileInput=$("#fileInput"),chat=$(".chat");
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;

let C,current,editing,reference,mapCount=0;
function fresh(){C={category:null,categorySource:null,subKey:null,subissue:"",subRaise:null,otherText:"",description:"",postcode:"",outward:"",postcodeKnown:null,landmark:"",
  photo:null,photoName:"",photoDraft:null,photoSlot:null,lat:null,lng:null,urgency:undefined,wantsUpdates:null,contactMethod:"",email:"",phone:"",name:"",language:"",languageLabel:"",
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
        opts.chips.forEach(ch=>{const b=document.createElement("button");b.type="button";b.className="ui-button rc-chip "+(ch.cls==="primary"?"ui-button":ch.cls==="quiet"?"ui-button--secondary rc-quiet":"ui-button--secondary");
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
  if(ORDER.indexOf(cat.def)>ORDER.indexOf(pr)){pr=cat.def;reasons.push(`${categoryLabel(C.category,true)} is ${cat.def} priority by default`)}
  if(C.subRaise&&ORDER.indexOf(C.subRaise)>ORDER.indexOf(pr)){pr=C.subRaise;reasons.push(`Raised to ${pr}: "${C.subissue}"`)}
  const text=[C.otherText,C.subissue,C.description,C.landmark].join(" ").toLowerCase();
  HAZARD.forEach(h=>{if(h.re.test(text)&&ORDER.indexOf(h.to)>ORDER.indexOf(pr)){pr=h.to;reasons.push(`Raised to ${h.to}: the description ${h.why}`)}});
  const now=C.submittedAt?new Date(C.submittedAt):new Date(),s=SLA[pr];
  return {category:C.category,team:cat.team,priority:pr,reasons,
    ackDue:s?new Date(now.getTime()+s.ackH*3600e3):null,resolveDue:s?addWorking(now,s.resD):null};
}

/* Is there an open job that may be the same problem? Demo mode uses sample cases;
   connected mode asks the server for open work of the same type nearby. */
async function checkDuplicate(){
  if(!C.outward||!CATS[C.category]?.id)return null;
  if(API_BASE===null){const e=EXISTING.find(x=>x.cat===C.category&&x.out===C.outward);return e?{ref:e.ref}:null}
  try{
    const q=new URLSearchParams({issue_type_id:CATS[C.category].id,postcode:C.postcode});
    const r=await fetch(API_BASE+"/api/cases/nearby/?"+q,{credentials:"same-origin"});
    if(!r.ok)return null;
    const j=await r.json();return j.match?{ref:j.match.reference}:null;
  }catch(e){return null}
}
/* Priority labels use the configured semantic colours. */
const PRIORITY_LABEL={Urgent:"ui-priority--danger",High:"ui-priority--warning",Medium:"",Low:"rc-label-low"};
const priorityLabel=(pr,text)=>`<span class="ui-priority ${PRIORITY_LABEL[pr]}">${esc(text)}</span>`;
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
    bot(p(t("hi",{site:SITE})));
    bot(p(t("auto"))+`<div class="ui-alert ui-alert--danger" role="note">${esc(t("emerg"))}</div>`);
    go("category");
  },
  /* 1. Problem */
  category(){
    setInput("ph_cat");
    const opts=Object.keys(CATS).filter(k=>k!=="other").map(k=>({label:categoryLabel(k),on:()=>{user(categoryLabel(k));setCat(k,"Chosen by reporter");next("subissue")}}));
    opts.push({label:t("something_else"),cls:"quiet",on:()=>{user(t("something_else"));go("otherText")}});
    bot(p(t("q_cat")),{chips:opts});
  },
  otherText(){setInput("ph_other");bot(p(t("q_other")))},
  subissue(){
    const sub=CATS[C.category].subissues;if(!sub.length){next(C.otherText?"postcode":"description");return}
    setInput("ph_sub");
    bot(p(t("q_desc")),{chips:sub.map(o=>{const key=o.key&&en(o.key)===o.label?o.key:null,label=key?t(key):o.label;
      return {label,on:()=>{user(label);C.subKey=key;C.subissue=o.label;C.subRaise=o.raise||null;next("description")}}})
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
    else{setInput("ph_lm_opt",{type:"street-address"});bot(p(t("q_lm_opt")),{chips:[skip("skip","map")]})}
  },
  /* 2b. Map pin: optional, and only offered when the deployment has configured a map */
  map(){
    if(!CONFIG.map||!window.createReportMap){next("photo");return}
    setInput("ph_choose");
    const id="chat-map-"+(++mapCount),status=()=>document.getElementById(id+"-status");
    bot(p(t("q_map"))+`<div id="${id}" class="report-map" role="group" aria-label="${esc(t("map_label"))}"></div><p class="ui-help" id="${id}-status" role="status" aria-live="polite">${esc(t("map_hint"))}</p>`+note(t("map_privacy"))+note(CONFIG.map.attribution),{chips:[
      {label:t("map_use"),cls:"primary",keep:true,on:()=>{if(C.lat===null){status().textContent=t("map_need_pin");return}
        user(t("map_use"));clearChips();next("photo")}},
      skip("skip","photo")]}).then(()=>{
      const handle=window.createReportMap({element:document.getElementById(id),config:CONFIG.map,
        onSelect:(lat,lng)=>{C.lat=lat;C.lng=lng;status().textContent=t("map_pin_set");render()}});
      if(handle){handle.map.invalidateSize();if(C.lat!==null)handle.setPoint(C.lat,C.lng,false)}});
  },
  /* 3. Photo */
  photo(){
    if(!CONFIG.photos){next("urgency");return}
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
      {label:t("yes_same"),on:()=>{user(t("yes_same"));C.duplicateOf=d.ref;C.possibleDuplicate=null;bot(p(t("dup_check")));next("updates")}},
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
    const rows=[["r_problem",categoryLabel(C.category)+(C.otherText?` (“${C.otherText}”)`:"")],["r_what",subText()],["r_details",C.description],
      ["r_where",[C.postcode,C.landmark].filter(Boolean).join(", ")||t("not_given")],["r_map",C.lat===null?"":t("r_map_set")],["r_photo",C.photo?t("added"):t("none")],["r_urg",urgLabel(C.urgency??null)],
      ["r_upd",C.wantsUpdates?`${t(m[1])}: ${C.email||C.phone}`:t("no_updates")],["r_name",C.name],["r_lang",C.languageLabel]];
    bot(p(t("review_intro"))+`<dl class="rc-summary">${rows.filter(r=>r[1]).map(([k,v])=>`<dt>${esc(t(k))}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`+note(t(C.wantsUpdates?"consent_yes":"consent_no")),
      {chips:[{label:t("send_report"),cls:"primary",on:submit},{label:t("change"),cls:"quiet",on:()=>{user(t("change"));go("editMenu")}}]});
  },
  editMenu(){
    setInput("ph_edit");
    const f=[["r_lang","language"],["r_problem","category"],["r_details","description"],["st1","postcode"],["r_photo","photo"],["r_urg","urgency"],["e_upd","updates"]];
    bot(p(t("q_change")),{chips:f.map(([k,s])=>({label:t(k),on:()=>{user(t(k));editing=true;
      if(s==="photo"){C.photo=null;C.photoDraft=null;C.photoSlot=null}if(s==="category"){C.subKey=null;C.subissue="";C.subRaise=null;C.otherText=""}
      if(s==="postcode"){C.landmark="";C.duplicateOf=null;C.possibleDuplicate=null}go(s)}}))
      .concat([skip("e_back","review")])});
  },
  refAsk(){
    setInput("ph_choose");
    bot(p(t("n1"))+p(t("q_ref")),{chips:[
      {label:t("yes_ref"),on:()=>{user(t("yes_ref"));C.wantsReference=true;go("done")}},
      {label:t("no_thanks"),cls:"quiet",on:()=>{user(t("no_thanks"));C.wantsReference=false;go("done")}}]});
  },
  done(){
    setInput("ph_sent");
    const tr=triage();
    const how={"Email":"n3_email","Text message":"n3_text","Phone call":"n3_call"}[C.contactMethod];
    bot(`${C.wantsReference?p(t("ref_is"))+`<p class="rc-ref" dir="ltr">${reference}</p>`+note(t("ref_keep")):p(t("no_problem"))}
      <dl class="rc-summary">
        <dt>${esc(t("d_priority"))}</dt><dd>${priorityLabel(tr.priority,t("p_"+tr.priority))} <span class="rc-meta">${esc(t("ai_pri"))}</span></dd>
      </dl>
      <p class="rc-next-title">${esc(t("next_h"))}</p>
      <ol class="rc-next-list"><li>${esc(t("n1"))}</li><li>${esc(t("n2"))}</li><li>${esc(t(C.wantsUpdates?how:"n3_none"))}</li></ol>`+(API_BASE===null?note(t("proto")):""),
      {chips:[{label:t("another"),on:()=>{log.innerHTML="";fresh();go("welcome")}}]});
  }
};
function setCat(k,src){C.category=k;C.categorySource=src}
function setLang(code,name,label){lang=code;C.language=name;C.languageLabel=label;applyLang();go(editing?"review":"intro")}
function go(id){current=id;render();steps[id]()}
const FLOW_INTERNAL=["otherText","subissue","landmark","map","dup","method","email","phone","name"];
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
const AFTER={postcode:"landmark",landmark:"map",email:"name",phone:"name",name:"review"};
function onText(v){
  err.textContent="";
  switch(current){
    case "language":clearChips();user(v);{const m=LANGS.find(l=>l[0].toLowerCase().includes(v.toLowerCase())||l[2].toLowerCase()===v.toLowerCase());
      if(m)setLang(m[1],m[2],m[0]);else setLang("en",v.slice(0,40),v.slice(0,40));}return;
    case "category":case "otherText":{
      clearChips();user(v);C.otherText=v.slice(0,300);const m=classify(v);
      if(m){current="awaitConfirm";bot(p(t("ai_cat",{cat:categoryLabel(m)}))+note(t("ai_sugg")),{chips:[
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
const ZERO_ID="00000000-0000-0000-0000-000000000000";
const post=(url,data)=>fetch(API_BASE+url,{method:"POST",credentials:"same-origin",
  headers:{"Content-Type":"application/json","X-CSRFToken":getCookie("csrftoken")||""},body:JSON.stringify(data||{})});
/* The server reserves the photo's ID and signs the upload; the browser sends the file straight to the
   provider, then the server checks that it arrived before the report may use it. */
async function uploadPhoto(blob){
  const reserve=await post(CONFIG.photoAuthorizeUrl,{draft:C.photoDraft});
  if(!reserve.ok)throw new Error("reserve "+reserve.status);
  const grant=await reserve.json(),body=new FormData();
  for(const [k,v] of Object.entries(grant.fields))body.append(k,v);
  body.append("file",blob,"photo.jpg");
  if(!(await fetch(grant.upload_url,{method:"POST",body})).ok)throw new Error("upload");
  const verified=await post(CONFIG.photoVerifyUrl.replace(ZERO_ID,grant.draft).replace(ZERO_ID,grant.slot));
  if(!verified.ok)throw new Error("verify "+verified.status);
  C.photoDraft=grant.draft;C.photoSlot=grant.slot;
}
fileInput.addEventListener("change",async()=>{
  const f=fileInput.files[0];fileInput.value="";if(!f)return;
  if(!f.type.startsWith("image/")){err.textContent=t("err_file");return}
  if(f.size>40*1024*1024){err.textContent=t("err_big");return}
  let data;try{data=await shrinkPhoto(f)}catch(e){err.textContent=t("err_file");return}
  if(API_BASE!==null){
    try{await uploadPhoto(await (await fetch(data)).blob())}
    catch(e){console.error("Photo upload failed",e);err.textContent=t("err_upload");return}
  }
  C.photo=data;C.photoName=f.name;clearChips();
  user("",`<img src="${data}" alt="">`);bot(p(t("thanks_photo")));next("urgency");
});

async function submit(){
  user(t("send_report"));C.submittedAt=new Date().toISOString();
  if(API_BASE===null){reference=Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>"ABCDEFGHJKMNPQRSTUVWXYZ23456789"[b%31]).join("").replace(/^(.{4})/,"$1-");go("refAsk");return}
  const body=payload(triage());body.case.status="New – awaiting triage";
  try{
    const r=await post("/api/cases/",body);
    if(r.status===429){C.submittedAt=null;bot(p(t("err_limit")));go("review");return}
    if(!r.ok)throw new Error("HTTP "+r.status);
    reference=(await r.json()).reference;go("refAsk");
  }catch(e){console.error("Sending the report failed",e);C.submittedAt=null;bot(p(t("err_send")));go("review")}
}

/* ---------- staff side panel (always English) ---------- */
function render(){
  const st=STAGE_OF[current]??0;
  const shown=Math.min(st,5);
  $("#progress").innerHTML=`<div class="rc-progress-label rc-meta"><span>${esc(t("st"+shown))}</span><span dir="ltr">${shown+1} / 6</span></div>`+
    `<progress class="ui-progress" value="${st>5?6:shown}" max="6" aria-label="${esc(t("st"+shown))}"></progress>`;
  if(!$("#casePanel"))return; /* staff panel is only on the page for signed-in staff */
  const rows=[["Language",C.language],["Problem",C.category?categoryLabel(C.category,true):""],["What exactly",C.subissue],["Details",C.description||C.otherText],
    ["Postcode",C.postcode||(C.postcodeKnown===false?"Not known":"")],["Location",C.landmark],["Photo",C.photo?C.photoName||"Added":""],
    ["Urgency",C.urgency===undefined?"":urgLabel(C.urgency,true)],["Updates",C.wantsUpdates===null?"":C.wantsUpdates?C.contactMethod:"No"],
    ["Contact",C.email||C.phone],["Name",C.name],["Reference",C.wantsReference===null?"":C.wantsReference?"Wanted":"Not wanted"]];
  $("#fields").innerHTML=rows.map(([k,v])=>`<li class="rc-field"><span class="${v?"rc-field-complete":"rc-muted"}" aria-hidden="true">${v?"✓":"–"}</span><span class="rc-muted">${k}</span><span>${v?esc(v):"<span class='rc-muted'>—</span>"}</span></li>`).join("");
  const tr=triage(),tri=$("#triage");
  if(!tr){tri.innerHTML=`<p class="rc-meta ">Triage appears once the problem is known.</p>`}
  else tri.innerHTML=`
    <div><div class="rc-lbl">Category</div>${esc(categoryLabel(C.category,true))}${C.subissue?` · ${esc(C.subissue)}`:""}<div class="rc-meta">${esc(C.categorySource||"")}</div></div>
    <div><div class="rc-lbl">Suggested team</div>${esc(tr.team||"To be reviewed")}</div>
    <div><div class="rc-lbl">Suggested priority</div>${priorityLabel(tr.priority,tr.priority)}${tr.reasons.length?`<ul class="rc-reasons">${tr.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>`:""}</div>
    ${SLA[tr.priority]?`<div><div class="rc-lbl">Configured targets</div>Acknowledge within ${SLA[tr.priority].ackH} hours; resolve within ${SLA[tr.priority].resD} working days.</div>`:""}
    ${C.duplicateOf||C.possibleDuplicate?`<div><div class="rc-lbl">Duplicate check</div>Possible duplicate of ${esc(C.duplicateOf||C.possibleDuplicate)}, to check</div>`:""}
    ${C.postcodeKnown===false?`<div><div class="rc-lbl">Location check</div>No postcode. Officer to confirm the location from the description.</div>`:""}
    ${lang!=="en"?`<div><div class="rc-lbl">Language</div>Reporter used the ${esc(C.language)} chat. Any typed text may need translating.</div>`:""}
    <div><div class="rc-lbl">Status</div>${reference?"Submitted, awaiting triage officer approval":"Draft"}</div>`;
  $("#json").textContent=JSON.stringify(payload(tr),null,2);
}
function payload(tr){
  return {case:{reference:reference,reference_shown_to_reporter:C.wantsReference,
    title:C.category?categoryLabel(C.category,true)+(C.subissue?" – "+C.subissue:""):null,
    category:tr?tr.category:null,sub_issue:C.subissue||null,category_source:C.categorySource,
    issue_type_id:C.category?CATS[C.category].id:null,other_selected:C.category==="other",
    description:[C.otherText,C.description].filter(Boolean).join(" | ")||null,chat_language:C.language||null,
    priority_suggested:tr?tr.priority:null,priority_reasons:tr?tr.reasons:[],priority_confirmed:null,reporter_urgency:C.urgency??null,
    status:reference?"New – awaiting triage":"Draft",
    location:{postcode:C.postcode||null,postcode_known:C.postcodeKnown,description:C.landmark||null,latitude:C.lat,longitude:C.lng},
    date_reported:C.submittedAt,assigned_team:tr?tr.team:null,assigned_officer:null,
    sla_ack_due:tr&&reference&&tr.ackDue?tr.ackDue.toISOString():null,sla_resolve_due:tr&&reference&&tr.resolveDue?tr.resolveDue.toISOString():null,
    duplicate_of:C.duplicateOf,possible_duplicate_of:C.possibleDuplicate,has_photo:!!C.photo,photo_draft:C.photoDraft,photo_slots:C.photoSlot?[C.photoSlot]:[],
    ai_used:(C.categorySource&&C.categorySource.startsWith("AI")?["category_suggestion"]:[]).concat(["priority_suggestion"],lang!=="en"?["chat_translation"]:[])},
    reporter:C.wantsUpdates?{name:C.name||null,email:C.email||null,phone:C.phone||null,preferred_contact:C.contactMethod,preferred_language:C.language||null,wants_updates:true}
      :{wants_updates:C.wantsUpdates,preferred_language:C.language||null}};
}
$("#copyJson")?.addEventListener("click",()=>{const txt=$("#json").textContent;
  navigator.clipboard.writeText(txt).then(()=>{$("#copyJson").textContent="Copied"},()=>{const s=getSelection(),r=document.createRange();r.selectNodeContents($("#json"));s.removeAllRanges();s.addRange(r);$("#copyJson").textContent="Selected, press Ctrl+C"})});


fresh();go("welcome");
})();
