"use strict";
// ID에 해당하는 화면 요소를 찾아 반환한다.
const $ = id => document.getElementById(id);
const storageKey = "tracetalk-frontier-job";
const ROUTES = {plain:"평문 판정", lexicon:"사전 근거 풀이", disambiguate:"사전 후보 판별", mad:"MAD 토론", usage_mad:"용례 MAD"};
let job = null, cursor = 0, result = null, polling = false, timer = null;
try { job = sessionStorage.getItem(storageKey); } catch (_) {}
// 새로고침 뒤에도 분석에 다시 연결할 수 있도록 작업 ID를 저장하거나 지운다.
function remember(value) { try { value ? sessionStorage.setItem(storageKey,value) : sessionStorage.removeItem(storageKey); } catch (_) {} }
// 분석 중에는 입력을 잠그고, 실행·취소 버튼의 표시와 활성 상태를 바꾼다.
function busy(value) {
  $("submit").disabled=value; $("text").disabled=value; $("mode").disabled=value;
  $("cancel").disabled=!value; $("cancel").hidden=!value;
  $("submit").textContent=value ? "해석 중…" : "해석하기";
}
const tabNames=["meaning","evidence","review"];
// 선택한 결과 탭만 표시하고 접근성 속성과 선택적 키보드 포커스를 갱신한다.
function selectTab(name, focus=false) {
  for (const tab of tabNames) {
    const active=tab === name, button=$(tab+"-tab");
    button.setAttribute("aria-selected",String(active)); button.tabIndex=active ? 0 : -1;
    $(tab+"-panel").hidden=!active;
  }
  if (focus) $(name+"-tab").focus();
}
// 각 탭에 마우스 클릭과 키보드 탐색 동작을 연결한다.
tabNames.forEach((name,index)=>{
  $(name+"-tab").addEventListener("click",()=>selectTab(name));
  // 좌우 방향키와 Home·End 키로 탭을 이동한다.
  $(name+"-tab").addEventListener("keydown",event=>{
    let next;
    if (event.key === "ArrowRight") next=(index+1)%tabNames.length;
    if (event.key === "ArrowLeft") next=(index+tabNames.length-1)%tabNames.length;
    if (event.key === "Home") next=0;
    if (event.key === "End") next=tabNames.length-1;
    if (next !== undefined) { event.preventDefault(); selectTab(tabNames[next],true); }
  });
});
// 미리 계산한 결과인지, 입력이 바뀌어 이전 문장의 결과인지 안내한다.
function updateResultNotice() {
  const notices=[];
  if (result?.prepared) notices.push("미리 계산한 결과 · "+result.prepared.made_at+" · 실시간 분석 아님");
  if (result?.request?.text && result.request.text !== $("text").value)
    notices.push("원문이 변경되었습니다. 현재 결과는 이전 문장의 해석입니다.");
  $("result-notice").textContent=notices.join(" / "); $("result-notice").hidden=!notices.length;
}
$("text").addEventListener("input",updateResultNotice);
// 새 분석을 시작할 때 이전 결과와 진행 기록을 비우고 대기 화면을 표시한다.
function resetPresentation() {
  for (const id of ["card-input","input-view","card-detect","detect","card-search","card-mad","card-easy","search","evidence-items","expression-tokens","events"])
    $(id).replaceChildren();
  for (const id of ["result","card-result","download","found-expressions","analysis-stages","result-notice"]) $(id).hidden=true;
  $("empty-result").hidden=false; $("evidence-empty").hidden=false; $("review-empty").hidden=false;
  fill("empty-result",[el("h2","해석 중"),el("p","결과가 준비되면 여기에 표시됩니다.")]);
  selectTab("meaning");
}
// 탐지한 표현을 작은 표시 요소로 나열하고, 없으면 빈 상태를 안내한다.
function showExpressions(expressions) {
  $("found-expressions").hidden=false;
  fill("expression-tokens",expressions.length ? expressions.map(text=>el("span",text,"expression-token")) : [el("span","찾은 표현 없음","note")]);
}
// JSON API를 호출한다. 본문이 있으면 POST를 보내고, 12초 초과나 서버 오류를 전달한다.
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(),12000);
  try {
    const options = {signal:controller.signal};
    if (body !== undefined) Object.assign(options,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const response = await fetch(path,options);
    const data = await response.json();
    if (!response.ok) { const error=new Error(data.error || "요청 오류"); error.status=response.status; throw error; }
    return data;
  } finally { clearTimeout(timeout); }
}
// 태그와 클래스로 요소를 만든다. 모델 응답은 textContent로 넣어 HTML로 실행되지 않게 한다.
function el(tag, text, cls) { const node=document.createElement(tag); if (text !== undefined) node.textContent=text; if (cls) node.className=cls; return node; }
// 지정한 화면 영역의 내용을 전달받은 노드들로 교체한다.
function fill(id, nodes) { $(id).replaceChildren(...nodes); }
// 문자열 배열을 글머리표 목록 요소로 변환한다.
function list(items) { const ul=el("ul"); for (const item of items) ul.appendChild(el("li",item)); return ul; }
// 지정한 구간을 강조한 노드 배열을 만든다. 서버의 코드 포인트 인덱스에 맞춰 문자를 나눈다.
function marked(text, spans, quote=false) {
  const chars=[...text], parts=[]; let at=0;
  for (const [start,end] of [...spans].sort((a,b)=>a[0]-b[0])) {
    if (start < at) continue;
    if (start > at) parts.push(el("span",chars.slice(at,start).join("")));
    const piece=chars.slice(start,end).join("");
    parts.push(el("mark",quote ? "‘"+piece+"’" : piece)); at=end;
  }
  if (at < chars.length) parts.push(el("span",chars.slice(at).join("")));
  return parts;
}
// 원문에서 표현이 나타나는 모든 위치를 찾아 코드 포인트 기준의 시작·끝 구간을 반환한다.
function findAll(text, needle) {
  const spans=[]; if (!needle) return spans;
  for (let pos=text.indexOf(needle); pos >= 0; pos=text.indexOf(needle,pos+needle.length)) {
    const start=[...text.slice(0,pos)].length; spans.push([start,start+[...needle].length]);
  }
  return spans;
}
// 서버의 진행 이벤트를 읽어 분석 단계, 모델 응답, 오류를 검토 기록에 추가한다.
function showEvent(event) {
  $("review-empty").hidden=true;
  if (event.type === "call_started") {
    const names={probe:"표현과 사전 후보 확인 중",propose:"의미 가설 생성 중",review:"가설의 모순 검토 중",self_review:"해석 재검토 중",final:"결과 정리 중",
      detect:"신조어·유행어 찾는 중",single:"표현의 뜻 정하는 중",judge:"후보 판정 중",sentence:"쉬운 말로 다시 쓰는 중",
      easy:"쉬운 표현 다시 고르는 중",choose:"보기 가운데 고르는 중",read:"표현을 가리고 문맥 읽는 중",pick:"신조어 부분 고르는 중",post:"근거 글 읽는 중"};
    $("status").textContent=names[event.stage] || "분석 중";
  }
  if (event.type !== "call_finished") return;
  const call=event.call, item=el("div",undefined,"event");
  const lines=[call.id+" · "+({probe:"예/아니오 탐침",propose:"가설 생성",review:"비판과 수정",self_review:"자기 검토",final:"최종 판정",
    detect:"표현 탐지",single:"뜻 정하기 (한 번)",judge:"후보 판정",sentence:"문장 해석",easy:"쉬운 표현 다시 쓰기",
    choose:"보기 판정",read:"표현을 가린 문맥 읽기",pick:"신조어 부분 하나 고르기",post:"근거 글 읽기"}[call.stage] || call.stage)];
  const value=call.analysis;
  if (call.stage === "choose") {
    lines.push(call.probs ? "보기 확률: "+Object.entries(call.probs).map(([k,v])=>k+"번 "+v.toFixed(2)).join(" / ") : (call.error || "확률을 읽지 못함"));
  } else if (call.stage === "probe") {
    // 탐침 응답은 분석문이 아닌 긍정 확률이며, 질문한 항목은 요청 메시지에 들어 있다.
    let asked={}; try { asked=JSON.parse(call.messages?.[1]?.content || "{}"); } catch (_) {}
    const target=call.role === "sense" ? "사전 후보 '"+asked.expression+"' = "+asked.candidate_meaning
      : call.role === "usage" ? "'"+asked.expression+"'이(가) 수집된 용례와 같은 뜻으로 쓰였는가" : "신조어·밈이 들어 있는가";
    lines.push(target+" → "+(typeof call.p_yes === "number" ? "예일 확률 "+call.p_yes.toFixed(2) : (call.error || "확률을 읽지 못함")));
  } else if (value) {
    if (value.decomposition) lines.push("표현 해체: "+value.decomposition);
    if (value.meaning || value.revised_meaning || value.interpretation) lines.push(value.meaning || value.revised_meaning || value.interpretation);
    if (value.replacements?.length) lines.push("쉬운 말: "+value.replacements.map(r=>r.expression+" → "+r.easy).join(" / "));
    if (value.assumptions?.length) lines.push("가정: "+value.assumptions.join(" / "));
    if (value.synthetic_dialogue?.length) lines.push("가상 대화 (합성):\n"+value.synthetic_dialogue.join("\n"));
    if (value.contrast) lines.push("대조 문장 (합성): "+value.contrast.text+"\n예상 변화: "+value.contrast.expected_change);
    if (value.objections?.length) lines.push("검토: "+value.objections.join(" / "));
    const checks=value.usage_checks || value.peer_usage_checks;
    if (checks?.length) lines.push((value.peer_usage_checks ? "상대 가설을 용례에 대입: " : "용례 대입: ")+checks.map(c=>c.id+" "+({yes:"맞음",no:"안 맞음",unclear:"불분명"}[c.fits] || c.fits)).join(" / "));
    if (value.supporting_usages?.length) lines.push("판정 근거 용례: "+value.supporting_usages.join(", "));
    // 카드 분석에서 반환한 표현 탐지, 후보 검증, 수정 선택, 문장 해석을 표시한다.
    if (call.stage === "detect") lines.push("찾은 표현: "+(value.expressions.join(" · ") || "없음"));
    if (value.choice) lines.push("고른 후보: "+value.choice+(value.easy ? " · 쉬운 표현: "+value.easy : ""));
    if (value.candidate_checks?.length) lines.push("후보 시험: "+value.candidate_checks.map(c=>c.id+" "+({yes:"맞음",no:"안 맞음",unclear:"불분명"}[c.fits] || c.fits)).join(" / "));
    if (value.revised_choice) lines.push("상대 선택은 "+({yes:"맞음",no:"틀림",unclear:"불분명"}[value.peer_choice_holds] || value.peer_choice_holds)+" · 수정한 선택: "+value.revised_choice);
    if (value.sentence) lines.push("문장 해석: "+value.sentence);
  } else lines.push(call.error || "응답을 해석하지 못했습니다.");
  item.textContent=lines.join("\n"); $("events").appendChild(item);
}
// 사전·용례 검색 결과와 MAD 토론으로 넘어간 이유를 설명하는 화면 노드들을 만든다.
function searchStep(value) {
  const routing=value.routing || {}, nodes=[];
  if (value.route === "reviewed_cache") return [el("p","팀이 검수해 저장한 해석에서 바로 가져왔습니다.")];
  const tau=routing.router?.tau_sense;
  const accepted=(routing.candidates || []).filter(c=>typeof c.p_yes === "number" && c.p_yes >= tau);
  if (routing.usage_lines?.length) {
    // 용례 MAD 경로와 route 필드가 없는 용례 비교 방식도 함께 처리한다.
    const cited=value.analysis?.supporting_usages || [];
    const debated=routing.route === "usage_mad" || value.method === "usage_mad";
    nodes.push(el("p",(routing.route === "usage_mad" ? "사전에는 아직 뜻이 없어, " : "")+"수집된 용례 "+routing.usage_lines.length+"개를 근거로 "
      +(debated ? "MAD 토론을 했습니다. 두 가설이 용례를 반씩 보고 세운 뒤, 서로 보지 못한 용례에 대입해 검증했습니다."
                : "한 번에 풀이했습니다 (비교 방식).")));
    nodes.push(list((routing.usage_lines || []).map(u=>u.id+(cited.includes(u.id) ? " (판정 근거)" : "")+" · "+u.text
      +" — "+u.source+", "+u.added_at)));
    nodes.push(el("p","용례 출처: "+[...new Set((routing.usage_lines || []).map(u=>u.note))].join(" / "),"note"));
  } else if (routing.route === "lexicon" || routing.route === "disambiguate") {
    nodes.push(el("p","사전에서 이 문장에 맞는 항목을 찾았습니다 (팀 검수 전 자료)."));
    nodes.push(list(accepted.map(c=>c.expression+" — "+c.meaning+" · 맞을 확률 "+c.p_yes.toFixed(2)+" · "+c.source
      +(c.added_at ? " · DB 추가 "+c.added_at : ""))));
    for (const entry of value.examples || []) {
      nodes.push(el("p","예시 대화 · "+entry.expression+" (출처 "+entry.source+", "+entry.note+")","note"));
      nodes.push(list(entry.lines));
    }
  } else if (routing.route === "mad") {
    nodes.push(el("p","사전에 이 문장과 맞는 항목이 없어 MAD 토론으로 넘어갔습니다. 두 가설을 세우고 서로 비판한 뒤 판정합니다."));
    const rejected=(routing.candidates || []).map(c=>c.expression+(typeof c.p_yes === "number" ? " ("+c.p_yes.toFixed(2)+")" : ""));
    if (rejected.length) nodes.push(el("p","맞지 않는다고 본 검색 후보: "+rejected.join(", "),"note"));
    const dialogue=(value.calls || []).filter(c=>c.stage === "propose" && c.analysis?.synthetic_dialogue?.length)
      .flatMap(c=>c.analysis.synthetic_dialogue).slice(0,3);
    if (dialogue.length) { nodes.push(el("p","가상 대화 (합성 자료, 실제 용례 아님)","note")); nodes.push(list(dialogue)); }
  } else if (routing.route === "plain") {
    nodes.push(el("p","탐침이 신조어가 없을 가능성이 높다고 보아 문자 그대로 풀이했습니다."));
  } else if (routing.candidates?.length) {
    nodes.push(el("p","사전 검색 후보를 그대로 모델에 함께 주었습니다 (비교 방식)."));
    nodes.push(list(routing.candidates.map(c=>c.expression+" — "+c.meaning)));
  } else nodes.push(el("p","이 비교 방식은 사전 검색을 쓰지 않습니다."));
  return nodes;
}
// 결과 카드에 표시할 의미 해석의 근거 유형을 한국어 이름으로 매핑한다.
const BASIS={db:"DB 뜻", usage:"용례로 추정한 뜻 (사전에 아직 없음)", literal:"표준어 낱말로 쓰임", model:"DB에 없음 · 모델 추정", post:"글에서 읽은 뜻 (검수 전)", mention:"근거 글에 언급만 있음", context:"낱말 뜻은 근거 없음 · 문맥으로 해석"};
// 토론 기록에 표시할 에이전트별 근거 역할이다.
const AGENT={A:"에이전트 A · DB 근거",B:"에이전트 B · 근거 글",C:"에이전트 C · 가린 문맥",D:"에이전트 D · 반대 근거",E:"에이전트 E · 검증"};
// 토론 발언 한 건을 주장·반박·수정·유보 등의 행동에 맞는 한국어 문장으로 바꾼다.
function turnLine(t) {
  // 확률을 정수 백분율로 표시하고, 값이 없으면 대시로 표시한다.
  const pct=p=>typeof p === "number" ? Math.round(p*100)+"%" : "-", who=AGENT[t.agent] || t.agent;
  if (t.act === "claim") return who+" 주장: "+t.meaning;
  if (t.act === "agree") return who+": 에이전트 A와 다른 근거로 같은 뜻에 이름 (서로 받침)";
  if (t.act === "read") return who+" 읽기 (낱말을 가리고 앞뒤만): "+t.situation+(t.meaning ? " → 이 자리의 뜻: "+t.meaning : "");
  if (t.act === "keep") return who+" 방어: “"+t.quote+"”";
  if (t.act === "revise") return who+" 수정: "+t.meaning+(t.quote ? " · “"+t.quote+"”" : "");
  if (t.act === "withdraw") return who+" 물러남: "+(t.why || "")+(t.quote ? " (낸 인용 “"+t.quote+"”)" : "");
  if (t.act === "accept") return who+": 받아들임"+(t.by === "rule" ? " (글이 적어 둔 풀이를 규칙으로 확인)" : " (받침 "+pct(t.p)+")")
    +(t.quote && t.by !== "rule" ? " — 근거 문장 “"+t.quote+"”" : "");
  if (t.act === "object") return who+(t.agent === "E" ? " 반박: 근거 글에서 그 뜻을 말하는 문장을 찾지 못함 (받침 "+pct(t.p)+")" : " 반박: 글자 그대로 쓴 문장일 수 있다 (글자 그대로 쪽 "+pct(t.p)+")");
  if (t.act === "hedge") return who+": "+(t.why || "받치는 문장을 찾지 못함")+" → 이 뜻은 확인 필요로만 보임";
  if (t.act === "defend") return who+" 방어: 댓글의 단서 “"+t.cue+"”";
  if (t.act === "concede") return who+" 인정: 그 뜻으로 쓴 단서가 없다"+(t.why ? " ("+t.why+")" : "");
  if (t.act === "recheck") return who+" 다시 물음: 단서를 보고 나서 글자 그대로 쪽 "+pct(t.p);
  return who+": "+t.act;
}
const DECIDED={single:"한 번에 판단", mad:"후보 비교 토론 (MAD)", guess:"추정", witness:"MAD: 근거별 가설 비교", read:"문맥 읽기"};
// 카드의 mad_reason 값을 MAD 토론을 실행한 이유로 풀어 쓴다.
const MAD_REASON={candidates:"MAD: DB 후보 비교", unreviewed:"MAD: 검수 전 DB 뜻을 검증", unknown:"MAD: DB에 없는 말 판정", usages:"MAD: 쌓인 문장으로 뜻 추정"};
// 선택 코드를 읽기 쉬운 이름으로 바꾸고, 검수 전인 사전 후보에는 상태를 덧붙인다.
const CHOICE=(c,item)=>c === "N" ? "새 뜻" : c === "L" ? "표준어 그대로" : c === "R1" ? "글에서 읽은 뜻" : c+((item.candidates || []).find(x=>x.id === c)?.review === "검수 전" ? " (검수 전)" : "");
// 양측의 주장·반론·수정과 최종 판정을 접이식 영역으로 만든다. 토론이 없으면 null을 반환한다.
function debateBox(item) {
  const d=item.detail?.debate; if (!d?.length) return null;
  const box=el("details"); box.appendChild(el("summary","MAD 토론 보기 · 두 쪽 주장 → 서로 반론 → 판정"));
  for (const side of d) {
    box.appendChild(el("h3",side.side+" · "+CHOICE(side.choice,item)));
    box.appendChild(el("p","주장: "+side.meaning));
    if (side.clues?.length) box.appendChild(el("p","원문 단서: "+side.clues.join(" / "),"note"));
    box.appendChild(el("p","상대의 반론: "+(side.objections || []).join(" / ")+(side.holds ? " (상대 판단: "+side.holds+")" : "")));
    box.appendChild(el("p","반론을 듣고: "+CHOICE(side.revised.choice,item)+" · "+side.revised.meaning,"note"));
  }
  box.appendChild(el("h3","판정 · "+CHOICE(item.choice,item)+(item.status === "uncertain" ? " (보류)" : "")));
  if (item.uncertainty) box.appendChild(el("p",item.uncertainty,"note"));
  return box;
}
// 근거별 가설과 판정 확률을 접이식 영역으로 만든다. 판정 점수가 없으면 null을 반환한다.
function witnessBox(item) {
  const d=item.detail; if (!d?.scores) return null;
  const box=el("details"); box.appendChild(el("summary","MAD 보기 · 가설마다 근거와 판정 확률 ("+(d.second_reading || d.second_scores ? "4B와 다른 모델이 함께 답함" : "같은 4B 모델이 근거를 달리해 답함")+")"));
  // 해당 후보의 판정 확률이 있을 때만 백분율 설명을 덧붙인다.
  const share=id=>typeof d.scores[id] === "number" ? " · 판정 "+Math.round(d.scores[id]*100)+"%" : "";
  for (const c of item.candidates || []) box.appendChild(el("p","DB 뜻 "+c.id+(c.review === "검수 전" ? " [검수 전]" : "")+": "+c.meaning+share(c.id)
    +(d.closeness && typeof d.closeness[c.id] === "number" ? " · 가린 문맥과 닮음 "+d.closeness[c.id].toFixed(2) : "")));
  if (d.read) box.appendChild(el("p",(d.read.from === "posts" ? "글에서 읽은 뜻" : "쌓인 문장에서 읽은 뜻")+": "+d.read.meaning+share("R1")+(d.supported ? " · DB 뜻과 같은 말" : "")));
  box.appendChild(el("p","표준어 뜻 그대로이거나 이름"+share("L")));
  box.appendChild(el("p","이 가운데 맞는 뜻 없음"+share("N")));
  if (d.reading?.situation) box.appendChild(el("p","표현을 가리고 읽은 문장 상황: "+d.reading.situation,"note"));
  if (d.second_reading) box.appendChild(el("p","다른 모델("+d.second_reading.model+")이 같은 글에서 읽은 뜻: "+d.second_reading.meaning+(typeof d.second_reading.closeness === "number" ? " · 두 읽기 닮음 "+d.second_reading.closeness.toFixed(2) : ""),"note"));
  if (d.objection) box.appendChild(el("p","DB 뜻을 보여 주고 물었을 때 모델의 답: 맞지 않음 · "+d.objection,"note"));
  // 제안한 뜻과 글자 그대로의 뜻을 비교한 반대 근거를 함께 표시한다.
  if (typeof d.contrast === "number") box.appendChild(el("p","반대 근거(이 뜻 대 글자 그대로, 두 쪽만 비교): 글자 그대로 쪽 "+Math.round(d.contrast*100)+"%","note"));
  return box;
}
// 출처 URL에서 호스트 이름을 추출하고, 추출할 수 없으면 원래 값을 반환한다.
const host=url=>(String(url).match(/^https?:\/\/([^/]+)/) || [])[1] || url;
// 표현별 사전 후보 수, 근거 글 출처, 관련 용례를 한 줄로 요약한다.
function searchLine(item) {
  const c=item.candidates || [], posts=item.posts || [];
  return item.expression+" · "+[c.length ? "DB 뜻 "+c.length+"개"+(c.some(x=>x.review === "검수 전") ? " (검수 전 포함)" : "") : "DB에 없음",
    posts.length ? "근거 글 "+posts.length+"개 ("+posts.map(p=>host(p.url)+(p.date ? " "+p.date : "")).join(", ")+")" : "근거 글 없음",
    item.related_usage ? "관련 용례: "+item.related_usage.text : "등록된 용례 없음"].join(" · ");
}
// 표현별 검토 과정에 에이전트의 근거, 토론 기록, 최종 결정과 확인 필요 상태를 표시한다.
function madView(item) {
  const d=item.detail || {};
  if (item.basis === "mention" || item.basis === "context") {  // 낱말 뜻의 근거가 없어도 문맥 읽기 기록은 표시한다.
    const box=el("div",undefined,"mad");
    box.appendChild(el("p",item.expression+" · 에이전트끼리 근거를 따져 물었습니다 (같은 4B 모델)","eyebrow"));
    for (const t of d.exchange || []) box.appendChild(el("p",turnLine(t)));
    box.appendChild(el("p","최종 결정: "+(item.basis === "context" ? "낱말 뜻은 근거 없음 · 문맥으로 짐작한 해석: "+item.meaning : "뜻 모름 · 근거 글에 언급만 있음")));
    return box;
  }
  if (!d.scores) return el("p",item.expression+" · "+(item.decided_by === "read" ? "DB와 근거 글에 없는 말이라 판정하지 않았습니다 (뜻 모름)." : item.decided_by === "mad" ? "후보 비교 토론으로 결정했습니다. 근거 탭에서 토론 기록을 확인할 수 있습니다." : "에이전트 비교 없이 결정: "+(DECIDED[item.decided_by] || item.decided_by)),"note");
  // 후보별 판정 확률을 백분율로 바꾸고, 점수가 없으면 대시로 표시한다.
  const share=id=>typeof d.scores[id] === "number" ? Math.round(d.scores[id]*100)+"%" : "-";
  const box=el("div",undefined,"mad");
  box.appendChild(el("p",item.expression+" · 에이전트마다 다른 근거를 받아 가설을 세우고, 판정이 문장에 맞는 가설을 고릅니다 (같은 4B 모델)","eyebrow"));
  for (const c of item.candidates || []) box.appendChild(el("p","에이전트 A · DB 근거 "+c.id+(c.review === "검수 전" ? " [검수 전]" : "")+": "+c.meaning+" → 판정 "+share(c.id)));
  if (d.read) box.appendChild(el("p","에이전트 B · 근거 글"+(d.read.from === "posts" ? "" : "(쌓인 문장)")+": "+d.read.meaning
    +(item.post_quote ? " · 글이 적은 풀이 “"+item.post_quote+"”" : "")+" → "+(d.supported ? "DB 뜻과 같은 말" : "판정 "+share("R1"))));
  if (d.reading?.situation) box.appendChild(el("p","에이전트 C · 표현을 가리고 읽은 문장 상황: "+d.reading.situation));
  if (typeof d.contrast === "number") box.appendChild(el("p","에이전트 D · 반대 근거: 고른 뜻과 '글자 그대로'만 놓고 다시 물음 → 글자 그대로 쪽 "+Math.round(d.contrast*100)+"%"));
  if (d.exchange?.length) {  // v16 토론
    box.appendChild(el("p","토론 · 반박받은 에이전트가 자기 근거를 인용해 답하거나 물러남","eyebrow"));
    for (const t of d.exchange) box.appendChild(el("p",turnLine(t)));
  }
  box.appendChild(el("p","표준어 뜻 그대로 → 판정 "+share("L")+" · 맞는 뜻 없음 → 판정 "+share("N"),"note"));
  box.appendChild(el("p","최종 결정: "+(item.check_needed ? "뜻 확인 필요 · " : item.status === "uncertain" ? "유보 · " : "")+CHOICE(item.choice,item)+(item.meaning ? " · "+item.meaning : "")));
  return box;
}
// 표현의 쉬운 말과 조건부 해석을 한 줄로 만들고, 근거가 없으면 생성하지 않은 이유를 안내한다.
function easyLine(item) {
  if (item.decided_by === "read" || item.basis === "mention") return item.expression+" · 뜻을 몰라 쉬운 표현을 만들지 않았습니다.";
  if (item.basis === "context") return item.expression+" · 낱말 뜻의 근거가 없어 쉬운 표현을 만들지 않았습니다.";
  // 뜻 확인이 필요한 항목은 사전의 쉬운 말을 확정하지 않고 조건부로 보여 준다.
  if (!item.easy && item.easy_if) return item.expression+" → "+item.easy_if+" (뜻 확인 필요 · 이 뜻이 맞다면)";
  return item.expression+" → "+(item.easy || (item.choice === "L" ? "표준어 그대로" : "쉬운 표현 없음"));
}
// 뜻과 쉬운 표현 탭에 보여 줄 요약 카드를 만들고, 실패·추정·유보 상태를 구분한다.
function summaryItem(item) {
  const box=el("article",undefined,"term-result"), heading=el("div",undefined,"term-heading");
  heading.appendChild(el("h2",item.headword || item.expression));
  const label=item.status === "failed" ? "해석 실패" : item.basis === "mention" || item.decided_by === "read" ? "뜻 모름"
    : item.basis === "context" ? "문맥 추정 · 확인 필요" : item.check_needed ? "뜻 확인 필요"
    : item.status === "uncertain" ? "해석 유보" : item.estimate || item.basis === "model" ? "추정한 뜻" : "해석 제안";
  heading.appendChild(el("span",label,"result-badge")); box.appendChild(heading);
  if (item.status === "failed") { box.appendChild(el("p",item.error || "이 표현은 해석하지 못했습니다.","warn")); return box; }
  if (item.meaning) box.appendChild(el("p",item.meaning,"definition"));
  if (item.easy || item.easy_if) {
    const conditional=item.check_needed || !item.easy;
    box.appendChild(el("p",(conditional ? "이 뜻이 맞다면 · " : "쉬운 표현 · ")+(item.easy || item.easy_if)
      +((item.easy_source || item.easy_if_source) === "draft" ? " (검수 전)" : ""),"easy-word"));
  }
  if (item.uncertainty) box.appendChild(el("p",item.uncertainty,"note"));
  else if (item.basis === "context" || item.basis === "model") box.appendChild(el("p","낱말 뜻을 뒷받침하는 근거가 없어 확인이 필요합니다.","note"));
  if (item.related_usage) {
    const usage=el("blockquote",item.related_usage.text,"usage-preview");
    usage.appendChild(el("cite",item.related_usage.source || "관련 용례")); box.appendChild(usage);
  }
  return box;
}
// 근거 탭의 상세 카드를 만들어 뜻·출처·용례·불확실성·토론 결과를 표시한다.
function itemCard(item) {
  const box=el("div",undefined,"card");
  box.appendChild(el("h2",item.expression+(item.headword && item.headword !== item.expression ? " ("+item.headword+")" : "")));
  if (item.status === "failed") { box.appendChild(el("p","이 표현은 해석하지 못했습니다: "+item.error)); return box; }
  // 근거가 부족한 뜻은 추정 또는 확인 필요 상태로 표시하여 확정된 뜻과 구분한다.
  box.appendChild(el("p",(item.basis === "mention" ? "뜻 모름" : item.basis === "context" ? "문맥으로 해석 · 확인 필요" : item.check_needed ? "뜻 확인 필요" : item.decided_by === "read" ? "뜻 모름 · DB와 근거 글에 없는 말" : item.status === "uncertain" ? "해석 유보 · 가능한 뜻" : item.estimate ? "추정한 뜻 (DB 근거 없음)" : "의미 해석 제안")
    +" · "+(BASIS[item.basis] || item.basis)
    +" · "+(MAD_REASON[item.mad_reason] || DECIDED[item.decided_by] || item.decided_by),"eyebrow"));
  const dl=el("dl");
  // 값이 있는 항목만 제목과 설명의 쌍으로 상세 목록에 추가한다.
  const row=(name,value)=>{ if (!value) return; dl.appendChild(el("dt",name)); dl.appendChild(el("dd",value)); };
  row(item.basis === "context" ? "문맥으로 짐작한 뜻 (근거 없음)" : item.check_needed ? "유력한 뜻 (확인 필요)" : "문맥상 의미",item.meaning);
  row("문장 상황 (이 말을 가리고 읽음)",item.reading);
  row("쉬운 표현",item.easy && item.easy+(item.easy_source === "draft" ? " (교사 초안 · 검수 전)" : ""));
  row("쉬운 표현 (이 뜻이 맞다면)",item.easy_if && item.easy_if+(item.easy_if_source === "draft" ? " (교사 초안 · 검수 전)" : ""));
  const usage=item.related_usage;
  row("관련 용례",usage ? usage.text+" ("+usage.source+(usage.added_at ? ", "+usage.added_at : "")+")" : "등록된 용례 없음");
  if (item.db_meaning !== item.meaning) row("DB 뜻",item.db_meaning);
  row("DB 출처",item.db_source && item.db_source+(item.db_review ? " ["+item.db_review+"]" : "")+(item.db_added_at ? " · DB에 넣은 때 "+item.db_added_at.slice(0,10) : ""));
  row("유래",item.origin && item.origin+(item.origin_from === "posts" ? " (근거 글)" : "")); row("품사",item.pos);
  if (item.post_meaning && item.post_meaning !== item.meaning) row("글에서 읽은 뜻",item.post_meaning);
  row("근거 문장",item.post_quote && "“"+item.post_quote+"”"+(item.post_how === "stated" ? " (글이 적어 둔 풀이)" : ""));
  for (const post of item.posts || []) row("근거 글",post.text+" ("+post.url+(post.date ? ", "+post.date : "")+")");
  if (item.alternatives?.length) row("다른 해석",item.alternatives.join(" / "));
  if (item.status === "uncertain" || item.estimate || item.basis === "model")
    row(item.decided_by === "read" || item.basis === "mention" || item.basis === "context" ? "상태" : "불확실성",item.uncertainty || "DB에 이 뜻이 없어 모델이 문맥과 용례로 추정했습니다.");
  if (item.basis === "model" && item.status === "proposed") row("문장 해석","근거 없는 추정이라 문장 해석에는 넣지 않고 원문 그대로 두었습니다.");
  if (item.candidates?.length) row("DB 후보",item.candidates.map(c=>c.id+" "+c.meaning+(c.review === "검수 전" ? " [검수 전]" : "")+(typeof c.p_yes === "number" ? " (맞을 확률 "+c.p_yes.toFixed(2)+")" : "")).join(" / "));
  if (item.decided_by === "mad") row("토론 경과",item.detail.proposer_choices.map(c=>CHOICE(c,item)).join(" · ")+" → 반론 뒤 "+item.detail.revised_choices.map(c=>CHOICE(c,item)).join(" · ")+" → 판정 "+CHOICE(item.choice,item));
  box.appendChild(dl);
  if (item.detail?.scores) row("판정 확률",Object.entries(item.detail.scores).map(([k,v])=>CHOICE(k,item)+" "+Math.round(v*100)+"%").join(" · "));
  const debate=debateBox(item); if (debate) box.appendChild(debate);
  const witnesses=witnessBox(item); if (witnesses) box.appendChild(witnesses);
  return box;
}
// 카드 형식의 분석 결과를 원문 강조, 표현 목록, 해석·근거·검토 과정 영역에 나누어 표시한다.
function showCard(value) {
  const card=value.card, text=value.request?.text ?? $("text").value, done=card.items.filter(i=>i.status !== "failed");
  $("result").hidden=true; $("card-result").hidden=false;
  $("empty-result").hidden=true; $("evidence-empty").hidden=true; $("review-empty").hidden=true; $("analysis-stages").hidden=false;
  showExpressions(card.items.map(i=>i.expression));
  fill("card-input",marked(text,done.map(i=>[i.start,i.end])));
  const d=value.detection || {};
  fill("card-detect",[...(value.prepared ? [el("p","미리 계산한 결과입니다. 지금 모델이 분석한 것이 아닙니다 ("
      +value.prepared.made_at+" 계산, "+value.prepared.model+").","note")] : []),
    el("p",card.maybe_slang ? "신조어나 밈이 있을 수 있지만 어느 표현인지 특정하지 못했습니다(문장 전체가 밈일 수 있습니다). DB에 들어오면 찾습니다."
      : card.plain ? "신조어·유행어를 찾지 않았습니다 (평문)." : "찾은 표현: "+card.items.map(i=>i.expression).join(" · ")),
    ...(card.skipped?.length ? [el("p","한 번에 3개까지만 분석합니다. 분석하지 못한 표현: "+card.skipped.join(" · "),"warn")] : []),
    ...(card.unexplained?.length ? [el("p","DB와 근거 글에 없는 낱말(뜻 모름, 수집 목록에 적음): "+card.unexplained.join(" · "),"note")] : []),
    el("p","DB에서 찾음: "+((d.db_hits || []).map(h=>h.span+(h.span !== h.expression ? "("+h.expression+")" : "")).join(", ") || "없음")
      +" · 모델이 찾음: "+((d.model_spans || []).join(", ") || "없음")
      +(d.unknown_to_analyzer?.length ? " · 형태소 분석기가 모르는 낱말: "+d.unknown_to_analyzer.join(", ") : "")
      +(d.ordinary_words?.length ? " · 표준어로 판정해 뺌: "+d.ordinary_words.join(", ") : "")
      +(typeof d.p_has_slang === "number" ? " · 신조어가 들어 있을 확률 "+d.p_has_slang.toFixed(2) : ""),"note")]);
  $("card-sentence").textContent=card.sentence
    ? card.sentence+(card.sentence_by === "system" ? " (모델이 표현을 바꾸지 못해 시스템이 그 낱말만 쉬운 말로 바꿈)" : "")
      +(card.items.some(i=>i.estimate && i.status === "proposed" && i.basis !== "model") ? " (용례로 추정한 뜻이 들어간 문장)" : "")
      +(card.kept_estimates?.length ? " (근거 없는 추정 "+card.kept_estimates.join("·")+"은(는) 원문 그대로)" : "")
    : card.sentence_if ? "뜻 확인 필요 · 이 뜻이 맞다면: "+card.sentence_if
    : "문장 해석 없음: "+(card.sentence_problems || []).join(" / ");
  const shown=card.items.filter(i=>i.status !== "failed");
  fill("card-search",shown.length ? shown.map(i=>el("p",searchLine(i))) : [el("p","찾은 표현이 없어 검색하지 않았습니다.","note")]);
  fill("card-mad",shown.length ? shown.map(madView) : [el("p","판정할 표현이 없습니다.","note")]);
  fill("card-easy",[...shown.map(i=>el("p",easyLine(i))), ...(card.sentence ? [el("p","문장 해석: "+card.sentence,"sentence")] : []),
    ...(card.sentence_if ? [el("p","뜻 확인 필요 · 이 뜻이 맞다면: "+card.sentence_if,"sentence")] : [])]);
  fill("card-items",card.items.map(summaryItem));
  fill("evidence-items",card.items.length ? card.items.map(itemCard) : [el("p","찾은 표현이 없어 별도 근거가 없습니다.","note")]);
}
// 분석 결과를 저장하고 형식에 맞춰 표시한다. 완료되지 않은 결과에는 안내 화면을 보여 준다.
function showResult(value) {
  result=value; $("download").hidden=!value;
  updateResultNotice();
  if (value?.card && (value.status === "completed" || value.status === "partial")) return showCard(value);
  if (!value?.analysis || value.status !== "completed") {
    fill("empty-result",[el("h2","해석 결과 없음"),el("p","왼쪽에서 상태를 확인하고 다시 해석할 수 있습니다.")]);
    return;
  }
  $("card-result").hidden=true;
  $("empty-result").hidden=true; $("evidence-empty").hidden=true; $("review-empty").hidden=true; $("analysis-stages").hidden=false;
  const a=value.analysis, text=value.request?.text ?? $("text").value, rewrite=value.rewrite || {};
  showExpressions(a.expressions);
  const expressionSpans=a.expressions.flatMap(e=>findAll(text,e));
  $("result").hidden=false;
  fill("input-view", marked(text, expressionSpans));
  const probe=value.routing?.p_has_slang;
  fill("detect", [el("p", a.expressions.length ? "탐지된 표현: "+a.expressions.join(" · ") : "신조어·밈 표현을 찾지 않았습니다 (평문)."),
    ...(typeof probe === "number" ? [el("p","신조어가 들어 있을 확률(탐침) "+probe.toFixed(2),"note")] : [])]);
  fill("search", searchStep(value));
  const via=value.routing?.route ? " · "+(ROUTES[value.routing.route] || value.routing.route) : "";
  $("badge").textContent=(value.route === "reviewed_cache" ? "검수된 저장 해석" : a.status === "uncertain" ? "해석 유보 · 가능한 의미" : "의미 해석 제안")+via;
  $("expressions").textContent=a.expressions.length ? a.expressions.join(" · ") : "없음 (문장 전체 풀이)";
  $("meaning").textContent=a.interpretation;
  // 제안된 해석에만 바꾼 문장이 있으며, 쉬운 표현으로 치환한 구간을 강조한다.
  if (rewrite.text) fill("rewrite", marked(rewrite.text, rewrite.spans.map(s=>[s.new_start,s.new_end]), true));
  else $("rewrite").textContent=a.status === "uncertain" ? "해석을 유보해 문장을 바꾸지 않았습니다." : "바꿀 표현이 없습니다.";
  $("easy").textContent=(rewrite.spans || []).map(s=>s.expression+" → "+s.easy).join(" / ") || "-";
  const first=(value.examples || [])[0];
  $("example").textContent=first ? first.lines[0]+" ("+first.source+", "+first.note+")" : "등록된 용례 없음";
  $("nuance").textContent=a.nuance; $("uncertainty").textContent=a.uncertainty;
  $("alternatives").replaceChildren(...a.alternatives.map(alternative=>el("li",alternative)));
}
// 실행 중인 작업의 새 이벤트를 주기적으로 조회하고, 완료·실패·연결 끊김에 맞게 화면을 갱신한다.
async function poll() {
  if (!job || polling) return;
  polling=true; $("resume").hidden=true;
  try {
    const state=await api("/api/jobs/"+encodeURIComponent(job)+"?after="+cursor);
    for (const event of state.events) showEvent(event);
    cursor=state.next_cursor;
    if (state.status === "running") timer=setTimeout(poll,700);
    else {
      showResult(state.result);
      const ready=state.result?.prepared;
      $("status").textContent=ready ? "미리 계산한 결과 (실시간 분석 아님) · "+ready.made_at+" 계산, 당시 "+ready.seconds_then+"초"
        : state.status === "completed" ? "분석 완료 · "+state.result.elapsed_seconds+"초"
        : state.status === "partial" ? "일부 표현은 해석하지 못했습니다 · "+state.result.elapsed_seconds+"초" : (state.error || "분석이 종료되었습니다.");
      job=null; remember(null); busy(false); showStore();
    }
  } catch (error) {
    if (error.status === 404) { job=null; remember(null); busy(false); showResult(null); $("status").textContent="서버에서 작업을 찾을 수 없습니다. 새 분석을 시작하세요."; }
    else { $("status").textContent="연결을 확인하지 못했습니다. 분석이 계속 실행 중일 수 있습니다."; $("resume").hidden=false; }
  } finally { polling=false; }
}
// 입력을 검사해 분석을 시작하고 작업 ID를 저장한다. 요청 응답을 놓치면 실행 중인 작업을 확인한다.
$("form").addEventListener("submit",async event=>{
  event.preventDefault(); if (job) return;
  if (!$("text").value.trim()) { $("status").textContent="해석할 문장을 입력하세요."; $("text").focus(); return; }
  busy(true); result=null; cursor=0; resetPresentation();
  $("status").textContent="분석 요청 중";
  try { const created=await api("/api/analyze",{text:$("text").value,mode:$("mode").value}); job=created.job_id; remember(job); await poll(); }
  catch (error) {
    // 응답을 받지 못했더라도 분석 요청 자체는 서버에 도착했을 수 있다.
    try { const health=await api("/api/health"); if (health.active_job) { job=health.active_job; remember(job); await poll(); return; } } catch (_) {}
    busy(false); $("status").textContent="분석 요청 확인 실패: "+error.message;
    showResult(null);
  }
});
// 현재 분석의 취소를 요청하고 서버가 반환하는 종료 상태를 다시 조회한다.
$("cancel").addEventListener("click",async()=>{
  if (!job) return;
  try { const response=await api("/api/jobs/"+encodeURIComponent(job)+"/cancel",{}); $("status").textContent=response.cancel_requested ? "중지를 요청했습니다. 현재 모델 호출이 반환되면 종료됩니다." : "종료 상태를 확인합니다."; await poll(); }
  catch (error) { $("status").textContent=error.message; $("resume").hidden=false; }
});
// 예약된 조회를 취소하고 즉시 작업 상태 확인을 재개한다.
$("resume").addEventListener("click",()=>{ clearTimeout(timer); return poll(); });
// 현재 분석 결과를 JSON 파일로 내려받고 임시 다운로드 URL을 해제한다.
$("download").addEventListener("click",()=>{
  if (!result) return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:"application/json"}));
  const link=document.createElement("a"); link.href=url; link.download="tracetalk-analysis.json"; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
// 페이지를 열면 모델 연결 상태를 표시하고, 테스트용 모델이면 별도로 안내한다.
api("/api/health").then(health=>{
  $("model").textContent=health.model+" · "+health.message;
  if (/fixture/i.test(health.model || "")) {
    $("environment-note").textContent="화면 테스트용 · 실제 모델 분석 아님"; $("environment-note").hidden=false;
  }
}).catch(()=>{ $("model").textContent="모델 연결을 확인하세요."; });
// DB의 사전·용례·근거 글 수와 최근 수집·추가 현황을 조회하여 표시한다.
function showStore() {
  api("/api/store").then(store=>{
    if (store.error) { $("store").textContent="DB: "+store.error; return; }
    const latest=(store.latest || []).slice(0,3).map(a=>a.expression+"("+a.kind+", "+a.added_at+")");
    $("store").textContent="DB: 사전 "+store.lexicon_entries+"개 · 용례 "+store.usage_groups+"개 표현 "+store.usage_lines+"문장"
      +(store.posts ? " · 근거 글 "+store.posts+"개"+(store.posts_newest ? "(가장 최근 "+store.posts_newest+")" : "") : "")
      +(store.update && store.update.checked ? " · 새 글 확인 "+String(store.update.checked).slice(5,16).replace("T"," ")
        +(store.update.ok === false ? " 실패" : " (새 글 "+(store.update.new_posts || 0)+"개)") : "")
      +(latest.length ? " · 최근 추가 "+latest.join(", ") : "");
  }).catch(()=>{ $("store").textContent="DB 상태를 읽지 못했습니다."; });
}
showStore();
// 검수 화면에서 전달한 문장을 입력란에 채운다. 실제 분석은 사용자가 버튼을 눌러 시작한다.
try { const given=new URLSearchParams(location.search).get("text"); if (given) $("text").value=given.slice(0,2000); } catch (_) {}
if (job) { busy(true); $("status").textContent="이전 분석에 다시 연결합니다."; poll(); }
