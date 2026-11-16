// DOM behavior harness only: no browser rendering or real model inference.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
 constructor(){this.children=[];this.listeners={};this.value='';this.textContent='';this.disabled=false;this.hidden=false;}
 appendChild(n){this.children.push(n);}
 replaceChildren(...nodes){this.children=nodes;}
 addEventListener(type,fn){this.listeners[type]=fn;}
 dispatch(type){return this.listeners[type]?.({preventDefault(){}});}
 click(){return this.dispatch('click');}
 setAttribute(name,value){this[name]=value;}
 focus(){this.focused=true;}
 set innerHTML(_){throw new Error('Untrusted HTML rendering');}
}
const ids=['form','text','mode','submit','cancel','status','resume','result','badge','expressions','meaning','rewrite','nuance','uncertainty','alternatives','events','download','model','input-view','detect','search','meaning-card','easy','example','store','card-result','card-input','card-detect','card-sentence','card-items'];
const html=fs.readFileSync('tracetalk/web/static/index.html','utf8');
const nodes=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));nodes.text.value='야르';nodes.mode.value='auto';
const storage=new Map();let offline=false,failed=false,missing=false;
const analysis={status:'proposed',expressions:['야르'],interpretation:'<img src=x onerror=alert(1)>',replacements:[{expression:'야르',easy:'TEST'}],nuance:'TEST',uncertainty:'TEST',alternatives:['TEST']};
const result={status:'completed',route:'model',analysis,elapsed_seconds:.01};
async function fetch(path,options={}){
 if(path==='/api/health')return {ok:true,json:async()=>({model:'TEST-FIXTURE-NOT-A-MODEL',message:'TEST'})};
 if(path==='/api/analyze'){
  assert.deepEqual(JSON.parse(options.body),{text:'야르',mode:'auto'});
  return {ok:true,json:async()=>({job_id:'fixture'})};
 }
 if(path.startsWith('/api/jobs/')){
  if(offline)throw new Error('TEST disconnected');
  if(missing)return {ok:false,status:404,json:async()=>({error:'TEST stale job'})};
  const state=failed?{status:'failed',error:'TEST model failure',events:[],next_cursor:0,result:{status:'failed'}}:
   {status:'completed',events:[{type:'call_finished',call:{id:'C1',stage:'propose',analysis:{meaning:'TEST',synthetic_dialogue:['TEST SYNTHETIC']}}}],next_cursor:1,result};
  return {ok:true,json:async()=>state};
 }
 throw new Error('Unexpected path '+path);
}
const ctx={document:{getElementById:id=>nodes[id],createElement:()=>new Element()},fetch,AbortController,console,Blob,
 sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
 setTimeout,clearTimeout,URL:{createObjectURL:()=>'',revokeObjectURL(){}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('tracetalk/web/static/app.js','utf8'),ctx);
(async()=>{
 await nodes.form.dispatch('submit');
 assert.equal(nodes.submit.disabled,false);assert.equal(nodes.cancel.disabled,true);
 assert.match(nodes.status.textContent,/분석 완료/);assert.equal(nodes.meaning.textContent,analysis.interpretation);
 assert.equal(nodes.events.children.length,1);assert.match(nodes.events.children[0].textContent,/가상 대화 \(합성\)/);
 assert.equal(storage.size,0);
 await nodes['evidence-tab'].click();assert.equal(nodes['evidence-panel'].hidden,false);assert.equal(nodes['meaning-panel'].hidden,true);
 nodes['evidence-tab'].listeners.keydown({key:'End',preventDefault(){}});assert.equal(nodes['review-tab'].focused,true);assert.equal(nodes['review-tab']['aria-selected'],'true');
 assert.equal(nodes['environment-note'].hidden,false);
 failed=true;await nodes.form.dispatch('submit');assert.match(nodes.status.textContent,/TEST model failure/);assert.equal(nodes.submit.disabled,false);
 assert.equal(nodes['meaning-panel'].hidden,false);assert.equal(nodes['evidence-panel'].hidden,true);assert.equal(nodes['evidence-items'].children.length,0);
 failed=false;offline=true;await nodes.form.dispatch('submit');assert.equal(nodes.submit.disabled,true);assert.equal(nodes.resume.hidden,false);assert.equal(storage.size,1);
 offline=false;await nodes.resume.click();assert.equal(nodes.submit.disabled,false);assert.equal(storage.size,0);
 offline=true;await nodes.form.dispatch('submit');offline=false;missing=true;await nodes.resume.click();
 assert.equal(nodes.submit.disabled,false);assert.equal(storage.size,0);assert.match(nodes.status.textContent,/작업/);
 console.log('Frontier DOM harness passed: completion, literal text, synthetic label, failure, reconnect, stale job. No browser rendering.');
})().catch(error=>{console.error(error);process.exitCode=1;});
