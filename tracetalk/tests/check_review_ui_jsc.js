// The review bench page on macOS JavaScriptCore (no node, no browser), from the project root:
//   /System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc tests/check_review_ui_jsc.js
class Element {
  constructor(id){this.id=id;this.children=[];this.listeners={};this.value='';this._text='';this.disabled=false;this.className='';this.tag='';}
  get textContent(){return this._text;}
  set textContent(v){this._text=String(v);this.children=[];}
  appendChild(n){this.children.push(n);}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=nodes;}
  addEventListener(type,fn){this.listeners[type]=fn;}
  click(){return this.listeners.click?.({preventDefault(){}});}
  set innerHTML(_){throw new Error('Untrusted HTML rendering');}
  text(){return this.textContent+this.children.map(c=>c.text()).join(' ');}
  find(pred){if(pred(this))return this;for(const c of this.children){const f=c.find(pred);if(f)return f;}return null;}
  all(pred){return (pred(this)?[this]:[]).concat(...this.children.map(c=>c.all(pred)));}
}
const nodes=new Proxy({},{get:(t,id)=>t[id]||(t[id]=new Element(id))});
var document={getElementById:id=>nodes[id],createElement:tag=>{const e=new Element();e.tag=tag;return e;}};
const sent=[];
const queue={waiting:2,approved:1,rejected:0,items:[
  {expression:'회크닉',keys:['k1','k2'],sources:2,similar:['회크닉스'],usages:['오늘 회크닉 어때?'],in_db:[{meaning:'옛 뜻',review:'검수 전'}],
   proposals:[{key:'k1',meaning:'<img src=x onerror=alert(1)>',source:'https://maily.so/x · 크롤러(검수 전)',tool:'크롤러',evidence:[{text:'회크닉은 회와 피크닉을 합친 말',url:''}]},
              {key:'k2',meaning:'둘째 뜻',source:'https://gogumafarm.kr/y',tool:'크롤러',evidence:[]}]},
  {expression:'무지컬',keys:['k3'],sources:1,similar:[],usages:[],in_db:[],proposals:[{key:'k3',meaning:'',source:'수집기: 댓글 2개에서 만남',tool:'수집기',evidence:[{text:'나 완전 무지컬임',url:''}]}]}]};
var fetch=async(path,options={})=>{
  if(path==='/api/review'&&!options.method)return {ok:true,json:async()=>queue};
  if(path==='/api/review'){const body=JSON.parse(options.body);sent.push(body);
    if(body.meaning==='거절')return {ok:false,status:400,json:async()=>({error:'뜻은 300자 이내로 적으세요.'})};
    return {ok:true,json:async()=>({action:body.action})};}
  throw new Error('Unexpected path '+path);
};
function assert(ok,message){if(!ok)throw new Error('ASSERT '+message);}
load('tracetalk/web/static/review.js');
const tick=()=>new Promise(r=>r());
(async()=>{
  for(let i=0;i<8;i++)await tick();
  assert(/기다리는 말 2개/.test(nodes.status.textContent),'status '+nodes.status.textContent);
  const [first,second]=nodes.items.children;
  const page=first.text();
  assert(/옛 뜻 \[검수 전\]/.test(page),'db row');
  assert(/회크닉스/.test(page),'similar');
  assert(/서로 다른 출처 2곳/.test(page),'sources');
  assert(page.includes('<img src=x onerror=alert(1)>'),'web text stays text');
  assert(/원문 문장이 없습니다/.test(page),'no source text');
  assert(/뜻 제안 없음/.test(second.text()),'collector word offers no meaning');
  const buttons=first.all(n=>n.tag==='button');
  const area=first.find(n=>n.tag==='textarea');
  assert(area.value==='<img src=x onerror=alert(1)>','first proposal in the box');
  buttons.find(b=>b.textContent==='이 뜻 쓰기'&&b!==buttons[0]).click();
  assert(area.value==='둘째 뜻','other proposal');
  const approve=buttons.find(b=>b.textContent.startsWith('승인'));
  area.value='거절';await approve.click();for(let i=0;i<8;i++)await tick();
  assert(/300자/.test(first.text()),'refusal shown');
  assert(!approve.disabled,'can try again');
  area.value='회와 피크닉을 합친 말';await approve.click();for(let i=0;i<8;i++)await tick();
  const last=sent[sent.length-1];
  assert(last.action==='approve'&&last.keys.join()==='k1,k2'&&last.meaning==='회와 피크닉을 합친 말','approve body '+JSON.stringify(last));
  assert(last.usages.join()==='오늘 회크닉 어때?','usages');
  assert(/DB에 넣었습니다/.test(first.text()),'done');
  assert(first.find(n=>n.tag==='a').href.includes(encodeURIComponent('오늘 회크닉 어때?')),'read again link');
  await second.all(n=>n.tag==='button').find(b=>b.textContent==='버리기').click();for(let i=0;i<8;i++)await tick();
  assert(sent[sent.length-1].action==='reject','reject');
  print('JSC review bench harness passed: queue, proposals, source text, approve, refusal, reject, literal text. No browser rendering.');
})().catch(e=>{print('FAILED: '+e.message);throw e;});
