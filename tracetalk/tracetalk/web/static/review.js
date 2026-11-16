"use strict";
// 수집한 표현을 검수하는 화면이다. 외부 글과 댓글은 textContent로 표시하여 HTML로 실행하지 않는다.
// ID에 해당하는 화면 요소를 찾아 반환한다.
const $ = id => document.getElementById(id);
// 텍스트와 클래스를 지정해 새 화면 요소를 만든다.
function el(tag, text, cls) { const node=document.createElement(tag); if (text !== undefined) node.textContent=text; if (cls) node.className=cls; return node; }
// 검수 API를 호출한다. 본문이 있으면 JSON으로 POST하고 서버 오류는 호출한 곳에 전달한다.
async function api(path, body) {
  const options = body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)};
  const response = await fetch(path,options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청 오류");
  return data;
}
// 라벨과 입력칸을 한 쌍으로 만든다. 행 수가 지정되면 여러 줄 입력칸을 사용한다.
function field(name, value, rows) {
  const label=el("label",name), input=el(rows ? "textarea" : "input");
  if (rows) input.rows=rows;
  input.value=value || "";
  label.appendChild(input);
  return [label,input];
}
// 검수할 표현의 제안 뜻·출처·용례와 수정 입력칸, 승인·버리기 버튼을 카드로 만든다.
function itemCard(item) {
  const box=el("div",undefined,"card");
  box.appendChild(el("h2",item.expression));
  box.appendChild(el("p",(item.sources > 1 ? "서로 다른 출처 "+item.sources+"곳에서 찾음 · " : "")+[...new Set(item.proposals.map(p=>p.tool))].join("·"),"eyebrow"));
  if (item.in_db?.length) box.appendChild(el("p","이미 DB에 있음: "+item.in_db.map(d=>d.meaning+" ["+d.review+"]").join(" / ")+" → 새 뜻일 때만 승인하세요.","note"));
  if (item.similar?.length) box.appendChild(el("p","DB에 비슷한 말: "+item.similar.join(", ")+" (오타나 같은 말인지 확인)","note"));
  const proposed=item.proposals.filter(p=>p.meaning);
  const [meaningLabel,meaning]=field("뜻 (고쳐서 승인할 수 있습니다)",proposed[0]?.meaning || "",3);
  for (const p of item.proposals) {
    const part=el("div");
    if (p.meaning) {
      // 제안한 뜻을 클릭하면 편집 가능한 뜻 입력칸에 복사한다.
      const use=el("button","이 뜻 쓰기"); use.type="button"; use.addEventListener("click",()=>{ meaning.value=p.meaning; });
      part.appendChild(el("p","제안: "+p.meaning)); part.appendChild(use);
    } else part.appendChild(el("p","뜻 제안 없음: 댓글에서 만난 말입니다. 뜻을 확인해 직접 적으세요.","note"));
    for (const q of p.evidence || []) part.appendChild(el("blockquote",q.text));
    if (!p.evidence?.length) part.appendChild(el("p","원문 문장이 없습니다. 출처를 직접 열어 확인하세요.","note"));
    part.appendChild(el("p","출처: "+p.source,"note"));
    box.appendChild(part);
  }
  // 용례마다 선택 상자를 만들고, 승인 시 함께 저장할 문장을 고를 수 있게 한다.
  const checks=(item.usages || []).map(text=>{
    const label=el("label"), tick=el("input"); tick.type="checkbox"; tick.checked=true; label.appendChild(tick); label.appendChild(el("span"," "+text)); return {label,tick,text};
  });
  if (checks.length) { box.appendChild(el("p","함께 넣을 용례","note")); for (const c of checks) { box.appendChild(c.label); box.appendChild(el("br")); } }
  const [easyLabel,easy]=field("쉬운 말 (선택: 문장 자리에 들어갈 짧은 표준어)","");
  const [originLabel,origin]=field("유래 (선택)","");
  const [posLabel,pos]=field("품사 (선택: 명사·동사·감탄사…)","");
  box.append(meaningLabel,easyLabel,originLabel,posLabel);
  const note=el("p","","note"), controls=el("div",undefined,"controls");
  const approve=el("button","승인: DB에 넣기"), reject=el("button","버리기");
  approve.type=reject.type="button";
  // 수정한 뜻과 선택한 용례로 승인·거절을 요청한다. 처리 중 중복 클릭을 막고 실패하면 다시 활성화한다.
  const send=async action=>{
    approve.disabled=reject.disabled=true;
    try {
      await api("/api/review",{action,keys:item.keys,expression:item.expression,meaning:meaning.value,easy:easy.value,origin:origin.value,pos:pos.value,
        source:(proposed[0]||item.proposals[0]).source,usages:checks.filter(c=>c.tick.checked).map(c=>c.text)});
      box.replaceChildren(el("h2",item.expression),el("p",action === "approve" ? "DB에 넣었습니다. 다음 분석부터 이 뜻을 씁니다." : "버렸습니다. 같은 뜻이 다시 올라오지 않습니다."));
      if (action === "approve" && checks[0]) { const again=el("a","이 문장으로 다시 해석하기"); again.href="/?text="+encodeURIComponent(checks[0].text); box.appendChild(again); }
    } catch (error) { note.textContent=error.message; approve.disabled=reject.disabled=false; }
  };
  // 두 버튼을 공통 저장 함수에 연결하고 각 검수 결정을 전달한다.
  approve.addEventListener("click",()=>send("approve"));
  reject.addEventListener("click",()=>send("reject"));
  controls.append(approve,reject); box.append(controls,note);
  return box;
}
// 페이지를 열면 검수 대기열과 누적 처리 수를 읽어 카드 목록을 표시하고 오류는 상태란에 안내한다.
api("/api/review").then(queue=>{
  $("status").textContent="기다리는 말 "+queue.waiting+"개 · 지금까지 승인 "+queue.approved+" · 버림 "+queue.rejected;
  $("items").replaceChildren(...queue.items.map(itemCard));
}).catch(error=>{ $("status").textContent=error.message; });
