# TraceTalk 해석 엔진 연결 안내 (LLM Part 2 → DB Retriever·UI 팀원용, 0.7에 쓰고 0.13에 맞춤)

문장 하나와, 팀 DB에서 찾은 행(선택)을 넣으면 발표자료 6쪽 결과 카드가 JSON으로 나온다. 모델은 맥북의 Ollama에서 돈다(시연 모델 `tracetalk-student-v1`, 4B, 약 2.5GB).

## 1. 부르는 법

파이썬(같은 폴더에서):

```python
from tracetalk.mad.card import interpret
card = interpret("재 방금 긁힌 것 같은데 ㅋㅋ", db=rows, model="tracetalk-student-v1")   # 모델 서버(bash mac/serve.sh, 127.0.0.1:11435)가 켜져 있어야 함
```

HTTP(이 폴더의 서버, localhost만 받음):

```
bash mac/start.sh        # 모델 서버와 이 서버를 함께 켬
POST http://127.0.0.1:8765/api/interpret   {"text": "...", "db": [...]}   →  카드 JSON
```

- 응답이 올 때까지 기다리는 요청이다. 맥에서 문장 하나에 보통 10~25초(처음 한 번은 모델을 올리느라 더 걸림).
- 한 번에 한 분석만 받는다. 다른 분석이 도는 중이면 409를 돌려준다.
- `db`를 빼면 이 폴더의 로컬 DB를 쓴다: `data/db/lexicon`, `data/db/usage`, 그리고 `tracetalk/db/update.py`로 넣은 `data/db/live`.

## 2. 넣는 것: 팀 DB 행 (`db`, 선택, 20행 이하)

```json
[{"expression": "긁히다",
  "variants": ["긁힌", "긁혔"],
  "senses": [{"meaning": "상대방의 말에 자극받아 발끈하다", "easy": "발끈한", "origin": "...", "pos": "동사", "source": "...", "added_at": "..."}],
  "usages": [{"text": "하 개긁힌다..;;", "source": "...", "added_at": "..."}],
  "match": {"span": "긁힌", "start": 3, "end": 5, "stage": "exact", "score": 100}}]
```

- `senses[].easy`(0.7.3, 선택): 사람이 정한 쉬운 표현. 이 뜻이 골라지면 카드의 쉬운 표현과 문장 해석에 모델 대신 이 말을 쓴다(모델이 지어낸 쉬운 말이 틀리던 문제를 구조적으로 막음). 표현 자체를 되풀이하지 않는 짧은 말(40자 이내).
- `match`(0.7.3, 선택): 검색기가 댓글의 어디서 찾았는지. 오타(오또카찌)처럼 글자 그대로는 없는 자리를 엔진에 알려 준다. 기준판 검색기 `tracetalk/db/retriever.py`의 `Retriever.rows(text, entries)`가 이 형식 그대로 돌려준다(검색 시험대 `eval/retrieval_bench.py`로 다른 검색기와 같은 세트로 잴 수 있음).

- `expression`만 꼭 있어야 하고, 나머지는 선택이다. 뜻이 여럿이면 `senses`에 여러 개를 넣는다(문자 그대로의 뜻은 엔진이 따로 후보로 넣는다).
- ChromaDB나 임베딩 검색으로 찾은 **후보를 넉넉히 넘겨도 된다.** 문맥에 안 맞는 행은 엔진이 탐침과 MAD로 거른다.
- 동사는 활용형을 엔진이 찾는다(긁히다 → 긁힌·긁혔). 그 밖의 표기 변형은 `variants`에 넣는다.

## 3. 나오는 것: 카드

```json
{"status": "completed",
 "card": {"plain": false,
          "sentence": "재 방금 자극받아서 발끈한 것 같은데 ㅋㅋ",
          "sentence_by": "model",
          "sentence_problems": [],
          "items": [{"expression": "긁힌", "headword": "긁히다", "start": 5, "end": 7,
                     "meaning": "...", "easy": "발끈한", "origin": "...", "pos": "동사",
                     "related_usage": {"text": "하 개긁힌다..;;", "source": "...", "added_at": "..."},
                     "status": "proposed", "basis": "db", "decided_by": "mad",
                     "alternatives": [], "uncertainty": "..."}]},
 "detection": {"db_hits": [...], "model_spans": [...], "p_has_slang": 0.93},
 "calls": [...], "elapsed_seconds": 41.2}
```

화면에 그대로 옮기면 6쪽 카드가 된다.

| 6쪽 칸 | 카드 필드 |
|---|---|
| 탐지 표현 | `items[].expression` (원문 위치는 `start`·`end`, 코드 포인트 기준) |
| 문맥상 의미 | `items[].meaning` |
| 문장 해석 | `card.sentence` |
| 쉬운 표현 | `items[].easy` |
| 관련 용례 | `items[].related_usage` |

꼭 같이 보여 줄 것:
- `status`: `proposed`(제안) 또는 `uncertain`(유보). 유보면 "가능한 뜻"으로 표시한다.
- `basis`: `db`(DB 뜻), `post`(근거 글에서 읽은 뜻, `post_quote`·`posts`와 함께), `usage`(용례로 세운 뜻), `literal`(표준어 낱말), `context`(근거 없이
  문맥으로 짐작), `mention`(근거 글에 언급만), `model`(**DB에 없음 · 뜻 모름**). `context`·`model`은 확정처럼 보이게 하지 않는다.
- `detail.exchange`(0.12): 에이전트들이 주고받은 차례. 화면 문구는 `tracetalk/web/static/app.js`의 `turnLine`을 따른다.
- `estimate`(v9.5): true면 DB 뜻 없이 용례·문맥으로 추정한 뜻이다. "추정"으로 표시한다(`usage`, `model` 근거).
- `card.kept_estimates`(v9.6): 근거 없는 추정이라 문장 해석에 넣지 않고 원문 그대로 둔 표현. 문장 옆에 그렇게 표시한다.
- `easy_source`(v9.5): `team`(팀이 정한 쉬운 말), `draft`(교사 모델 초안, **검수 전** — 그렇게 표시), `model`(모델이 쓴 것).
- `decided_by`: `single`(한 번) / `mad`(후보 비교 토론) / `guess`(추정).
- `card.sentence`가 null이면 `sentence_problems`에 이유가 있다. 화면에는 "문장 해석 없음: 이유"로 표시한다.
- `card.sentence_by`: `model`(모델이 다시 씀), `system`(모델이 두 번 다 표현을 그대로 둬서 시스템이 그 낱말만 쉬운 말로 바꿈 — 화면에 그렇게 표시), `unchanged`(평문), null(문장 없음).
- 카드 `status`가 `partial`이면 일부 표현만 실패한 것이다. 실패한 표현은 `items[].status = "failed"`와 `error`를 가진다.

## 4. Gradio에서 (예시, 이 폴더에서 실행해 보지 않음)

화면을 Gradio로 바꿀 때는 엔진을 다시 짜지 말고, 켜 둔 TraceTalk 서버(`bash mac/start.sh`)의 카드를 받아 보여 주기만 하면 된다. 그래야 근거 글,
토론, 팀이 넣은 DB, 자동 업데이트가 그대로 따라온다. **근거 문장과 에이전트 토론은 꼭 보여 준다**(TraceTalk의 셀링포인트). 필드 전체는
`tracetalk/web/README.md`.

```python
import json, os, urllib.request
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"   # Gradio의 사용 통계 전송 끄기 (gradio를 import하기 전에)
import gradio as gr

def card_of(text):  # 켜 둔 TraceTalk 서버에 묻는다 (이 컴퓨터 안, 한 번에 하나씩)
    req = urllib.request.Request("http://127.0.0.1:8765/api/interpret", json.dumps({"text": text}).encode(),
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))["card"]

def run(text):
    card = card_of(text)
    rows = [[i["expression"], i.get("meaning", ""), "확정" if i.get("status") == "proposed" and not i.get("check_needed") else "확인 필요",
             i.get("easy", ""), i.get("post_quote", ""), ((i.get("posts") or [{}])[0]).get("url", ""),
             " → ".join(f"{t['agent']} {t['act']}" for t in (i.get("detail") or {}).get("exchange", []))]
            for i in card["items"] if i.get("status") != "failed"]
    return card.get("sentence") or "문장 해석 없음: " + "; ".join(card.get("sentence_problems") or []), rows

gr.Interface(run, gr.Textbox(label="문장"),
             [gr.Textbox(label="문장 해석"),
              gr.Dataframe(headers=["표현", "문맥상 의미", "상태", "쉬운 표현", "근거 문장", "근거 글", "에이전트 토론"])]
             ).launch(server_name="127.0.0.1", share=False)  # share=True는 외부 공개 링크를 만든다: 쓰지 않는다
```

Gradio를 설치할 때는 `_mac_runtime`의 가상환경 안에 넣고(시스템에 설치하지 않음), 버전을 정해 둔다.

## 5. DB에 새 말 넣기 (시연의 "업데이트" 장면)

**팀 표로 한 번에 (0.7.3):** `data/db/team_db_template.csv` 양식(열: kind, expression, variants, meaning, easy, origin, pos, usage, context, source)에 한 줄씩 채운다. kind는 `뜻`(entry) 또는 `용례`(usage), variants는 공백으로 구분, 엑셀에서 UTF-8 CSV로 저장해도 된다. 먼저 `python3 -m tracetalk.db.update import 표.csv --dry-run`으로 검사하고 `import`로 넣는다. 한 줄이라도 틀리면 아무것도 넣지 않고 몇 번째 줄이 왜 틀렸는지 알려 준다.

**한 건씩:**

```
python3 -m tracetalk.db.update add-entry --expression 긁히다 --meaning "..." --origin "..." --pos 동사 --source "누가, 어디서 확인"
python3 -m tracetalk.db.update add-usage --expression 야르 --text "..." --text "..." --source "..."
```

- 서버를 다시 켤 필요 없이 다음 분석부터 반영된다.
- 출처는 반드시 적는다.
- KoNeoBench 자료는 평가 전용이라 이 저장소에 없다(받는 곳 `data/eval/external/SOURCES.md`, 평가 세트 만들기 `eval/build_koneo_eval.py`).
  DB에 넣지 않고 팀 공유 묶음에도 넣지 않는다.
