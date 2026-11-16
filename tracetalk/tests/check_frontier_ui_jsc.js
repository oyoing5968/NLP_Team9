// DOM behavior harness for macOS JavaScriptCore (no node needed), run from the project root:
//   /System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc tests/check_frontier_ui_jsc.js
// Fake DOM only: no browser rendering, no real model. Same app.js as the browser loads.
class Element {
  constructor(id){this.id=id;this.children=[];this.listeners={};this.value='';this._text='';this.disabled=false;this.hidden=false;this.className='';this.tag='';}
  // As in a browser, setting textContent removes the children and replaceChildren clears the text.
  get textContent(){return this._text;}
  set textContent(v){this._text=String(v);this.children=[];}
  appendChild(n){this.children.push(n);}
  replaceChildren(...nodes){this._text='';this.children=nodes;}
  addEventListener(type,fn){this.listeners[type]=fn;}
  dispatch(type){return this.listeners[type]?.({preventDefault(){}});}
  click(){return this.dispatch('click');}
  setAttribute(name,value){this[name]=value;}
  focus(){this.focused=true;}
  set innerHTML(_){throw new Error('Untrusted HTML rendering');}
  text(){return this.textContent+this.children.map(c=>c.text()).join('');}
}
// Every id the page asks for exists, created on first use (by the page or by this harness).
const nodes=new Proxy({},{get:(t,id)=>t[id]||(t[id]=new Element(id))});
var document={getElementById:id=>nodes[id],createElement:tag=>{const e=new Element();e.tag=tag;return e;}};
var AbortController=class{constructor(){this.signal={};}abort(){}};
var Blob=class{};var URL={createObjectURL:()=>'',revokeObjectURL(){}};
var storage=new Map();
var sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
// The page only re-polls while a job is running; every fixture state here is already finished.
var setTimeout=()=>0, clearTimeout=()=>{};
let state=null;
var fetch=async(path,options={})=>{
  if(path==='/api/health')return {ok:true,json:async()=>({model:'TEST-FIXTURE-NOT-A-MODEL',message:'TEST'})};
  if(path==='/api/analyze')return {ok:true,json:async()=>({job_id:'fixture'})};
  if(path.startsWith('/api/jobs/'))return {ok:true,json:async()=>state};
  if(path==='/api/store')return {ok:true,json:async()=>({lexicon_entries:495,usage_groups:309,usage_lines:3343,
    latest:[{kind:'용례',expression:'야르',added_at:'2026-11-01T18:00:00+09:00',source:'TEST'}]})};
  throw new Error('Unexpected path '+path);
};
function assert(ok,message){if(!ok)throw new Error('ASSERT '+message);}
load('tracetalk/web/static/app.js');
const done=(result,events=[])=>({status:'completed',events,next_cursor:events.length,result});
const marks=id=>nodes[id].children.filter(c=>c.tag==='mark').map(c=>c.textContent);
(async()=>{
  // 1. Lexicon route: highlight in the input, accepted candidate only, example lines, in-place rewrite.
  const text='쟤 방금 긁힌거 같은데?';
  nodes.text.value=text;nodes.mode.value='routed';
  state=done({status:'completed',route:'model',elapsed_seconds:.01,request:{text},
    analysis:{status:'proposed',expressions:['긁힌'],interpretation:'<img src=x onerror=alert(1)>',replacements:[{expression:'긁힌',easy:'쉬운말A'}],nuance:'N',uncertainty:'U',alternatives:['ALT']},
    rewrite:{text:'쟤 방금 쉬운말A거 같은데?',spans:[{expression:'긁힌',easy:'쉬운말A',start:5,end:7,new_start:5,new_end:9}],skipped:[]},
    routing:{route:'lexicon',p_has_slang:0.93,router:{tau_sense:0.6},candidates:[{expression:'긁히다',meaning:'M',source:'S',p_yes:0.8},{expression:'보',meaning:'X',source:'S',p_yes:0.2}]},
    examples:[{expression:'긁히다',lines:['예시1','예시2'],source:'KoCulture-Dialogues',note:'실제 관측 아님'}]},
    [{type:'call_finished',call:{id:'C1',stage:'probe',role:'has_slang',p_yes:0.93,messages:[{},{content:'{}'}]}}]);
  await nodes.form.dispatch('submit');
  assert(/분석 완료/.test(nodes.status.textContent),'status: '+nodes.status.textContent);
  assert(nodes.meaning.textContent==='<img src=x onerror=alert(1)>','literal text');
  assert(marks('input-view').join()==='긁힌','input highlight '+marks('input-view'));
  assert(nodes['input-view'].text()===text,'input kept');
  assert(marks('rewrite').join()==='‘쉬운말A’' && nodes.rewrite.text()==='쟤 방금 ‘쉬운말A’거 같은데?','rewrite');
  assert(nodes.easy.textContent==='긁힌 → 쉬운말A','easy');
  assert(/예시1/.test(nodes.example.textContent) && /실제 관측 아님/.test(nodes.example.textContent),'example');
  assert(/사전 근거 풀이/.test(nodes.badge.textContent),'badge');
  const search=nodes.search.text();
  assert(/긁히다 — M/.test(search) && !/보 — X/.test(search) && /예시2/.test(search),'search '+search);
  assert(/0.93/.test(nodes.detect.text()),'probe');
  assert(/예일 확률 0.93/.test(nodes.events.children[0].textContent),'probe event');
  // 2. MAD route with an emoji before the expression: spans are code points, not UTF-16 units.
  const text2='😀 야르~ 맛있다';nodes.text.value=text2;
  state=done({status:'completed',route:'model',elapsed_seconds:.01,request:{text:text2},
    analysis:{status:'proposed',expressions:['야르~'],interpretation:'I',replacements:[{expression:'야르~',easy:'B'}],nuance:'N',uncertainty:'U',alternatives:[]},
    rewrite:{text:'😀 B 맛있다',spans:[{expression:'야르~',easy:'B',start:2,end:5,new_start:2,new_end:3}],skipped:[]},
    routing:{route:'mad',p_has_slang:0.9,router:{tau_sense:0.6},candidates:[]},
    calls:[{stage:'propose',analysis:{synthetic_dialogue:['A: 합성1','B: 합성2']}}]});
  await nodes.form.dispatch('submit');
  assert(marks('input-view').join()==='야르~','emoji input highlight '+marks('input-view'));
  assert(marks('rewrite').join()==='‘B’' && nodes.rewrite.text()==='😀 ‘B’ 맛있다','emoji rewrite');
  assert(/MAD 토론/.test(nodes.search.text()) && /합성 자료/.test(nodes.search.text()) && /A: 합성1/.test(nodes.search.text()),'mad search');
  assert(nodes.example.textContent==='등록된 용례 없음','no example');
  // 3. Uncertain answer: no rewritten sentence is shown.
  state=done({status:'completed',route:'model',elapsed_seconds:.01,request:{text:text2},
    analysis:{status:'uncertain',expressions:['야르~'],interpretation:'I',replacements:[{expression:'야르~',easy:'B'}],nuance:'N',uncertainty:'U',alternatives:['A1','A2']},
    rewrite:{text:null,spans:[],skipped:[]},routing:{route:'mad',router:{tau_sense:0.6},candidates:[]}});
  await nodes.form.dispatch('submit');
  assert(/유보/.test(nodes.badge.textContent) && /유보해/.test(nodes.rewrite.textContent) && nodes.rewrite.children.length===0,'uncertain');
  assert(nodes.alternatives.children.length===2,'alternatives');
  // 4. Comparison method without routing, then a failed run keeps the form usable.
  state=done({status:'completed',route:'model',elapsed_seconds:.01,request:{text:'평범한 문장'},
    analysis:{status:'proposed',expressions:[],interpretation:'P',replacements:[],nuance:'',uncertainty:'',alternatives:[]},rewrite:{text:null,spans:[],skipped:[]}});
  await nodes.form.dispatch('submit');
  assert(/검색을 쓰지 않습니다/.test(nodes.search.text()) && /바꿀 표현이 없습니다/.test(nodes.rewrite.textContent),'direct');
  // 5. Usage MAD (v7): the usages the model read, the judge's citations, their source and time; DB status.
  const text5='야르~ 맛있다';nodes.text.value=text5;
  const used=[{id:'U1',text:'TEST 야르~ 오늘 최고',source:'TEST 팀 입력',note:'팀이 넣은 용례, 검수 전',added_at:'2026-11-01T18:00:00+09:00'},
              {id:'U2',text:'TEST 야르 외치고 시작',source:'TEST 팀 입력',note:'팀이 넣은 용례, 검수 전',added_at:'2026-11-01T18:00:00+09:00'}];
  state=done({status:'completed',route:'model',elapsed_seconds:.01,request:{text:text5},
    analysis:{status:'proposed',expressions:['야르~'],interpretation:'I5',replacements:[{expression:'야르~',easy:'E5'}],nuance:'N',uncertainty:'U',alternatives:[],supporting_usages:['U2']},
    rewrite:{text:'E5 맛있다',spans:[{expression:'야르~',easy:'E5',start:0,end:3,new_start:0,new_end:2}],skipped:[]},
    routing:{route:'usage_mad',p_has_slang:0.2,router:{tau_sense:0.6},candidates:[],usage_lines:used,usage_group:{id:'g',expression:'야르'}},
    examples:[{expression:'야르',lines:['U2 · TEST 야르 외치고 시작','U1 · TEST 야르~ 오늘 최고'],source:'TEST 팀 입력',note:'팀이 넣은 용례, 검수 전',cited:['U2']}]},
    [{type:'call_finished',call:{id:'C2',stage:'probe',role:'usage',p_yes:0.81,messages:[{},{content:JSON.stringify({expression:'야르'})}]}},
     {type:'call_finished',call:{id:'C3',stage:'review',analysis:{objections:['O'],peer_usage_checks:[{id:'U1',fits:'no',note:'x'}],revised_meaning:'R'}}}]);
  await nodes.form.dispatch('submit');
  const search5=nodes.search.text();
  assert(/용례 MAD/.test(nodes.badge.textContent),'usage badge '+nodes.badge.textContent);
  assert(/용례 2개/.test(search5) && /U2 \(판정 근거\) · TEST 야르 외치고 시작/.test(search5) && /2026-11-01T18:00/.test(search5),'usage search '+search5);
  assert(/^U2 · TEST 야르 외치고 시작 \(TEST 팀 입력/.test(nodes.example.textContent),'usage example '+nodes.example.textContent);
  assert(/수집된 용례와 같은 뜻/.test(nodes.events.children[0].textContent) && /U1 안 맞음/.test(nodes.events.children[1].textContent),'usage events');
  assert(/용례 309개 표현/.test(nodes.store.textContent) && /야르\(용례/.test(nodes.store.textContent),'store '+nodes.store.textContent);
  // 5b. usage_direct comparison: no route, but the usages it read are still listed.
  state=done({status:'completed',route:'model',method:'usage_direct',elapsed_seconds:.01,request:{text:text5},
    analysis:{status:'proposed',expressions:['야르~'],interpretation:'I',replacements:[],nuance:'N',uncertainty:'U',alternatives:[],supporting_usages:['U1']},
    rewrite:{text:null,spans:[],skipped:[]},routing:{usage_group:{id:'g',expression:'야르'},usage_lines:used}});
  await nodes.form.dispatch('submit');
  assert(/용례 2개를 근거로 한 번에/.test(nodes.search.text()) && /U1 \(판정 근거\)/.test(nodes.search.text()),'usage_direct '+nodes.search.text());
  // 6. v9 result card: every expression, code-point highlights, origin/pos, related usage, MAD trail, the plain sentence.
  const text6='야르~ 😀 쟤 방금 긁힌거 같은데?';nodes.text.value=text6;nodes.mode.value='card';
  state=done({status:'partial',route:'card',method:'card',elapsed_seconds:.01,request:{text:text6},
    detection:{db_hits:[{span:'긁힌',expression:'긁히다'}],model_spans:['야르~'],p_has_slang:0.93},
    card:{plain:false,sentence:'와 😀 쟤 방금 발끈한 거 같은데?',sentence_problems:[],items:[
      {expression:'야르~',start:0,end:3,headword:null,decided_by:'guess',basis:'model',status:'uncertain',choice:'N',
       meaning:'<b>감탄</b>',easy:'와',origin:'',pos:'',db_meaning:null,related_usage:null,alternatives:[],uncertainty:'U6',candidates:[],detail:{}},
      {expression:'긁힌',start:11,end:13,headword:'긁히다',decided_by:'mad',basis:'db',status:'proposed',choice:'C1',
       meaning:'M6',easy:'발끈한',origin:'O6',pos:'동사',db_meaning:'D6',related_usage:{id:'U1',text:'하 개긁힌다',source:'팀',added_at:'2026-11-03'},
       alternatives:[],uncertainty:'',candidates:[{id:'C1',meaning:'D6',p_yes:0.41,review:'검수 전'}],mad_reason:'unreviewed',detail:{proposer_choices:['C1','L'],revised_choices:['C1','C1'],debate:[{side:'가설 1',choice:'C1',meaning:'H1',clues:['Q1'],objections:['X1'],holds:'yes',revised:{choice:'C1',meaning:'R1'}},{side:'가설 2',choice:'L',meaning:'H2',clues:[],objections:['X2'],holds:'no',revised:{choice:'C1',meaning:'R2'}}]}},
      {expression:'방금',status:'failed',error:'E6'}]}},
    [{type:'call_finished',call:{id:'C1',stage:'detect',analysis:{expressions:['야르~'],note:'n'}}},
     {type:'call_finished',call:{id:'C9',stage:'review',analysis:{objections:['O'],peer_choice_holds:'no',revised_choice:'C1',revised_meaning:'R',clues:[]}}}]);
  state.status='partial';  // the server's job status is the card's status
  await nodes.form.dispatch('submit');
  assert(nodes['card-result'].hidden===false && nodes.result.hidden===true,'card shown');
  assert(JSON.stringify(marks('card-input'))===JSON.stringify(['야르~','긁힌']),'card marks '+marks('card-input'));
  assert(nodes['card-sentence'].textContent==='와 😀 쟤 방금 발끈한 거 같은데?','card sentence');
  const items6=nodes['evidence-items'].children.map(c=>c.text());
  assert(/DB에 없음 · 모델 추정/.test(items6[0]) && /<b>감탄<\/b>/.test(items6[0]) && !/db\/update/.test(items6[0]),'guess item '+items6[0]);
  assert(/MAD: 검수 전 DB 뜻을 검증/.test(items6[1]) && /O6/.test(items6[1]) && /동사/.test(items6[1]) && /하 개긁힌다 \(팀, 2026-11-03\)/.test(items6[1])
    && /C1 \(검수 전\) · 표준어 그대로 → 반론 뒤 C1 \(검수 전\) · C1 \(검수 전\) → 판정 C1 \(검수 전\)/.test(items6[1])
    && /MAD: 검수 전 DB 뜻을 검증/.test(items6[1]) && /D6 \[검수 전\]/.test(items6[1])
    && /MAD 토론 보기/.test(items6[1]) && /주장: H1/.test(items6[1]) && /상대의 반론: X2 \(상대 판단: no\)/.test(items6[1])
    && /반론을 듣고: C1 \(검수 전\) · R2/.test(items6[1]),'mad item '+items6[1]);
  assert(/해석하지 못했습니다: E6/.test(items6[2]),'failed item');
  assert(/일부 표현은 해석하지 못했습니다/.test(nodes.status.textContent),'partial status');
  assert(/찾은 표현: 야르~/.test(nodes.events.children[0].textContent) && /상대 선택은 틀림 · 수정한 선택: C1/.test(nodes.events.children[1].textContent),'card events');
  assert(/DB에서 찾음: 긁힌\(긁히다\)/.test(nodes['card-detect'].text()) && /0\.93/.test(nodes['card-detect'].text()),'card detect');
  state.result.card.sentence_by='system';  // v9.3: the system swapped the words the model kept
  await nodes.form.dispatch('submit');
  assert(/시스템이 그 낱말만 쉬운 말로 바꿈/.test(nodes['card-sentence'].textContent),'system sentence '+nodes['card-sentence'].textContent);
  // v9.5: a drafted easy word is marked; a meaning with no DB sense is an estimate, and so is the sentence built on it
  state.result.card.items[1].easy_source='draft';
  Object.assign(state.result.card.items[0],{status:'proposed',estimate:true,uncertainty:''});
  await nodes.form.dispatch('submit');
  const items95=nodes['evidence-items'].children.map(c=>c.text());
  assert(/발끈한 \(교사 초안 · 검수 전\)/.test(items95[1]),'draft easy '+items95[1]);
  assert(/추정한 뜻 \(DB 근거 없음\)/.test(items95[0]) && /모델이 문맥과 용례로 추정/.test(items95[0]),'estimate item '+items95[0]);
  assert(!/추정한 뜻이 들어간 문장/.test(nodes['card-sentence'].textContent),'a guess (basis model) is not in the sentence');
  assert(/근거 없는 추정이라 문장 해석에는 넣지 않고/.test(items95[0]),'guess kept note '+items95[0]);
  state.result.card.kept_estimates=['야르~']; state.result.card.items[0].basis='usage';
  await nodes.form.dispatch('submit');
  assert(/용례로 추정한 뜻이 들어간 문장/.test(nodes['card-sentence'].textContent) && /근거 없는 추정 야르~은\(는\) 원문 그대로/.test(nodes['card-sentence'].textContent),'estimate sentence '+nodes['card-sentence'].textContent);
  state.result.prepared={from:'mac_demo.jsonl',made_at:'2026-11-03T18:30+09:00',seconds_then:44.9,model:'M',protocol:'P'};
  state.status='completed';
  await nodes.form.dispatch('submit');
  assert(/미리 계산한 결과 \(실시간 분석 아님\)/.test(nodes.status.textContent) && /당시 44\.9초/.test(nodes.status.textContent),'prepared status '+nodes.status.textContent);
  assert(/지금 모델이 분석한 것이 아닙니다/.test(nodes['card-detect'].text()),'prepared note');
  delete state.result.prepared; state.status='partial';
  state={status:'failed',error:'TEST model failure',events:[],next_cursor:0,result:{status:'failed'}};
  await nodes.form.dispatch('submit');
  assert(/TEST model failure/.test(nodes.status.textContent) && nodes.submit.disabled===false,'failure');
  assert(storage.size===0,'storage cleared');
  // 0.9: a DB sense not clear enough says so, shows where it comes from and the shares; what past the cap is listed.
  state=done({status:'completed',route:'card',method:'card',elapsed_seconds:.01,request:{text:text6},
    detection:{db_hits:[],model_spans:[],p_has_slang:0.93},
    card:{plain:false,sentence:null,sentence_problems:['S'],sentence_if:'야르~ 😀 쟤 방금 발끈한 거 같은데?',skipped:['잠수 탔다'],items:[
      {expression:'긁힌',start:11,end:13,headword:'긁히다',decided_by:'witness',basis:'db',status:'uncertain',choice:'C1',check_needed:true,reading:'상황R',
       meaning:'유력M',easy:'',easy_if:'발끈하다',easy_if_source:'team',origin:'',pos:'',db_meaning:'D7',db_source:'https://x.test',db_review:'검수 전',db_added_at:'2026-11-07T10:00:00+09:00',related_usage:null,
       post_meaning:'글M',posts:[{text:'글 조각P',url:'https://maily.so/p',date:'2026-10-22'}],
       alternatives:['모델이 문맥에서 읽은 뜻: A7'],uncertainty:'뜻 확인이 필요합니다.',candidates:[{id:'C1',meaning:'D7',p_yes:0.62,review:'검수 전'}],
       detail:{scores:{C1:0.62,R1:0.2,L:0.1,N:0.08},read:{meaning:'글M',from:'posts'},reading:{situation:'상황R'},closeness:{C1:0.71}}},
      {expression:'야르',start:0,end:2,headword:null,decided_by:'read',basis:'model',status:'uncertain',choice:'N',estimate:true,reading:'',
       meaning:'',easy:'',origin:'',pos:'',db_meaning:null,related_usage:null,alternatives:[],uncertainty:'DB에 없는 말입니다.',candidates:[],detail:{}}]}},
    [{type:'call_finished',call:{id:'C1',stage:'choose',role:'readings',probs:{'1':0.6,'2':0.4},messages:[{},{content:'{}'}]}}]);
  await nodes.form.dispatch('submit');
  const items7=nodes['evidence-items'].children.map(c=>c.text());
  assert(/뜻 확인 필요/.test(nodes['card-items'].text()) && /이 뜻이 맞다면/.test(nodes['card-items'].text()),'summary preserves conditional meaning');
  nodes.text.value+=' 변경';await nodes.text.dispatch('input');assert(!nodes['result-notice'].hidden,'stale result is labelled');
  assert(/뜻 확인 필요/.test(items7[0]) && /유력한 뜻 \(확인 필요\)/.test(items7[0]) && /유력M/.test(items7[0]) && /D7/.test(items7[0])
    && /https:\/\/x.test \[검수 전\] · DB에 넣은 때 2026-11-07/.test(items7[0]) && /상황R/.test(items7[0]) && /C1 \(검수 전\) 62%/.test(items7[0]),'check item '+items7[0]);
  assert(/글에서 읽은 뜻글M/.test(items7[0]) && /글 조각P \(https:\/\/maily.so\/p, 2026-10-22\)/.test(items7[0]) && /MAD 보기/.test(items7[0])
    && /글에서 읽은 뜻: 글M · 판정 20%/.test(items7[0]) && /가린 문맥과 닮음 0.71/.test(items7[0]) && /글에서 읽은 뜻 20%/.test(items7[0]),'post evidence '+items7[0]);
  assert(/뜻 모름 · DB와 근거 글에 없는 말/.test(items7[1]) && /상태DB에 없는 말입니다/.test(items7[1]) && !/문맥상 의미/.test(items7[1]) && !/문장 해석/.test(items7[1]),'read item '+items7[1]);
  assert(/분석하지 못한 표현: 잠수 탔다/.test(nodes['card-detect'].text()),'skipped');
  // v13: the slide's five steps: what the search found, the agents and the verdict, the easy words
  const mad7=nodes['card-mad'].text();
  assert(/긁힌 · DB 뜻 1개 \(검수 전 포함\) · 근거 글 1개 \(maily.so 2026-10-22\) · 등록된 용례 없음/.test(nodes['card-search'].text()),'search step '+nodes['card-search'].text());
  assert(/에이전트 A · DB 근거 C1 \[검수 전\]: D7 → 판정 62%/.test(mad7) && /에이전트 B · 근거 글: 글M → 판정 20%/.test(mad7)
    && /에이전트 C · 표현을 가리고 읽은 문장 상황: 상황R/.test(mad7) && /최종 결정: 뜻 확인 필요 · C1 \(검수 전\) · 유력M/.test(mad7)
    && /야르 · DB와 근거 글에 없는 말이라 판정하지 않았습니다/.test(mad7),'mad step '+mad7);
  assert(/야르 · 뜻을 몰라 쉬운 표현을 만들지 않았습니다/.test(nodes['card-easy'].text()),'easy step '+nodes['card-easy'].text());
  // v13: a sense to check shows the DB's easy words and their sentence only as "이 뜻이 맞다면"
  assert(/긁힌 → 발끈하다 \(뜻 확인 필요 · 이 뜻이 맞다면\)/.test(nodes['card-easy'].text())
    && /뜻 확인 필요 · 이 뜻이 맞다면: 야르~ 😀 쟤 방금 발끈한 거 같은데\?/.test(nodes['card-easy'].text()),'conditional easy '+nodes['card-easy'].text());
  assert(nodes['card-sentence'].textContent==='뜻 확인 필요 · 이 뜻이 맞다면: 야르~ 😀 쟤 방금 발끈한 거 같은데?','conditional sentence '+nodes['card-sentence'].textContent);
  assert(/쉬운 표현 \(이 뜻이 맞다면\)발끈하다/.test(items7[0]) && !/쉬운 표현발끈하다/.test(items7[0]),'conditional easy row '+items7[0]);
  assert(/보기 확률: 1번 0.60/.test(nodes.events.text()),'choose event');
  // 0.9: reads like slang, nothing named
  state=done({status:'completed',route:'card',method:'card',elapsed_seconds:.01,request:{text:text6},detection:{db_hits:[],model_spans:[],p_has_slang:0.9},
    card:{plain:true,maybe_slang:true,sentence:text6,sentence_problems:[],skipped:[],items:[]}});
  await nodes.form.dispatch('submit');
  assert(/특정하지 못했습니다/.test(nodes['card-detect'].text()),'maybe slang');
  print('JSC DOM harness passed: lexicon/MAD/uncertain/direct/usage MAD/card/failure, code-point highlights, literal text, DB status. No browser rendering.');
})().catch(error=>print('JSC DOM harness FAILED: '+error.message));
