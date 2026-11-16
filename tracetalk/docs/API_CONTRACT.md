# TraceTalk UI 연결 명세 (0.4부터 판마다 더한 기록)

> **지금(0.13) 화면이 쓰는 것은 `card` 방식 하나다.** 요약과 필드 표는 `tracetalk/web/README.md`, 팀원용 안내는 `docs/TEAM_MODULE.md`. 아래는 0.4부터
> 판마다 더한 기록이라 옛 방식(routed, debate 등)은 비교 실험용으로만 남아 있다. 0.12~0.13에 더한 것은 맨 아래 절.

Python 3.9 이상의 표준 라이브러리로 실행한다(맥에서는 `mac/run.sh`가 가상환경과 샌드박스로 돌림). 개발 예: `http://localhost:8765`. UI는 분석 내용을 생성하지 않고 아래 API로 작업을 시작·조회한다. 이 명세는 `tracetalk/web/run.py` 전용이며 기존 `run.py`의 chat/target 규격과 다르다.

## 실행

```bash
python3 -m tracetalk.web.run --model YOUR_INSTALLED_OLLAMA_MODEL
```

`YOUR_INSTALLED_OLLAMA_MODEL`은 설치된 실제 이름으로 바꾼다. 0.7부터 시연 모델은 학습한 `tracetalk-student-v1`이다(`model/README.md`; 맥에서는 `bash mac/start.sh`).

UI만 연결할 때는 다음 명시적인 테스트 서버를 사용할 수 있다. 모든 응답은 TEST-FIXTURE-NOT-A-MODEL이며 의미 성능/시연 성과로 사용하지 않는다.

```bash
python3 tests/serve_frontier_fixture.py
```

프런트와 백엔드 포트가 다르면 개발 서버의 `/api` 프록시를 `http://127.0.0.1:8765`로 설정하고, upstream Host/Origin이 백엔드 origin에 맞도록 설정한다. 같은 origin에서 배포하면 프록시가 필요 없다. 무제한 CORS는 제공하지 않는다. 최종 팀 UI의 빌드 경로를 정한 후 정적 파일 서빙을 연결한다.

## 분석 시작

`POST /api/analyze`, Content-Type: application/json

```json
{"text":"쟤 방금 긁힌거 같은데?","mode":"routed"}
```

| 필드 | 기본값 / 범위 |
|---|---|
| text | 필수. 공백만 있는 입력 거부, 최대 2,000자 |
| mode | **routed(시연 기본)** / direct / rag / vote / vote_rag / debate_v2 / auto(0.4 debate) / self_review / independent / debate / no_dialogue |
| seed | 42, 0~2147483647 정수 |
| total_output_tokens | 2560, 전체 호출 출력 상한 합계. 1280~8192 정수 |
| max_seconds | 120, 5~600 정수. 호출 사이에서 검사하는 시간 예산 |

`auto`는 현재 검수된 완전 일치 댓글이 DB에 있으면 0회 호출로 반환하고, 없으면 debate 5회 호출한다. 나머지 mode는 모두 DB를 우회한다. 초기 검수 DB는 빈 배열이다.

성공 응답: HTTP 202, `{"job_id":"16자리 작업 식별자"}`. 잘못된 입력은 400, 실행 중 작업이 있으면 409이다. 동시에 한 작업만 실행한다. POST 응답 유실 시 `/api/health`의 active_job으로 진행 상태를 확인할 수 있다. 서버가 재시작되면 메모리의 작업 목록은 초기화된다.

## 진행 조회

`GET /api/jobs/{job_id}?after=0`

```json
{"id":"작업 식별자","status":"running","events":[],"next_cursor":0,"result":null,"error":null}
```

첫 조회는 after=0, 이후 반환된 next_cursor를 다음 after에 넣는다. 예: 700ms~1초 간격으로 polling. 스트리밍 토큰/SSE API는 아직 없다.

작업 status: running / completed / failed / cancelled / timed_out. 모든 terminal 상태에서 polling과 로딩 표시를 종료한다. 네트워크 오류가 났을 때는 완료로 간주하지 말고 작업 ID를 보존해 재조회한다. 404이면 서버 재시작 또는 작업 만료를 표시한다. 완료된 과거 작업은 최대 20개까지 메모리에 남는다.

events:

- call_started: call_id, stage. stage는 propose/review/self_review/final.
- call_finished: call. call에는 raw, analysis, valid, error, seed, max_tokens, prompt_tokens, completion_tokens, elapsed_seconds 등이 있다. 모델의 분석 출력이며 실제 용례가 아니다.
- analysis_finished: status, metrics.

result의 중요 필드:

| 필드 | 의미 |
|---|---|
| route | model 또는 reviewed_cache |
| status | 작업 완료 여부. completed는 의미가 정답이라는 인증이 아님 |
| analysis.status | proposed: 의미 제안 / uncertain: 정보 부족으로 유보 |
| analysis.expressions | 대상 표현. 원문 문자열만 허용. 없으면 문장 전체 풀이 |
| analysis.interpretation | 해석 또는 유보 이유를 포함한 가능한 의미 |
| analysis.replacements | 0.5.1: `[{expression, easy}]` 최대 3개. expression은 원문의 정확한 부분 문자열, easy는 그 자리에 넣을 쉬운 말(같은 활용형). 0.4의 formal_rewrite를 대신한다 |
| rewrite | 0.5.1: 시스템이 원문에 replacements를 적용한 문장. `{text, spans[{expression, easy, start, end, new_start, new_end}], skipped[]}`. proposed일 때만 text가 있고, 원문의 나머지는 바뀌지 않는다 |
| examples | 0.5.1(서버만): 탐침이 받아들인 사전 항목의 예시 대화 `[{entry_id, expression, lines, source, license, note}]`. 사람에게만 보여 주며 모델 입력·근거가 아니다 |
| analysis.nuance | 뉘앙스 설명 |
| analysis.input_quotes | 실제 입력에 존재하는 인용 |
| analysis.alternatives | 대안 해석 배열 |
| analysis.uncertainty | 남은 불확실성 설명 |
| input_spans | 원문의 인용 위치. Unicode code point 기준 [start,end) |
| calls | 실제 호출 시도·프롬프트·출력·비용 로그 |
| metrics | call_count, invalid_calls, prompt_tokens, completion_tokens, model_seconds, allocated_output_tokens |
| elapsed_seconds | 전체 작업 경과 시간 |
| review | DB 반환일 때 검수자·검수시각·만료시각, 그 외 null |

JavaScript 문자열 인덱스는 UTF-16이므로 이모지가 있으면 그대로 slice(start,end)하지 않는다. `[...originalText].slice(start,end).join('')`와 같이 code point 배열을 사용한다. 모델의 텍스트는 textContent로 렌더링한다.

가상 대화는 `calls[].analysis.synthetic_dialogue`이며 화면에 반드시 합성 자료임을 표시한다. `contrast` 역시 합성 대조 문장과 예상 변화다. confidence 확률은 제공하지 않는다. proposed와 검수된 DB 반환을 같은 확정 배지로 표시하지 않는다.

## 중지와 준비 상태

- `POST /api/jobs/{job_id}/cancel`, body `{}` → `{"cancel_requested":true}`. 진행 중 모델 요청이 반환된 뒤 중지한다. 즉시 중지를 보장하지 않는다.
- `GET /api/health` → connected, ready, model, provider, message, active_job. ready는 모델 목록에 이름이 있는지 확인하는 상태이며 품질이나 GPU 가속 여부를 인증하지 않는다.
- `GET /api/config` → version, protocol, modes, model, default_request.

최종 실행 로그는 `runs/frontier-*.json`에 저장된다. 로그에는 입력 댓글과 프롬프트가 포함된다. UI의 다운로드 버튼은 동일 실행 기록을 사용자 파일로 저장한다.

응답 JSON 예시는 고정 응답 서버 `python3 tests/serve_frontier_fixture.py`로 받아 본다(옛 예시 파일 `data/frontier_api_examples.json`은 이 저장소에 없다).


0.4.1 추가: 호출별 `ollama_timings_ns`는 서버가 제공한 total_duration/load_duration/prompt_eval_duration/eval_duration을 보존합니다. 나노초 단위이며 미제공 값은 null입니다. 실제 실행 검증은 `mac/README.md`(설치·켜기)와 `tracetalk/verify.py`를 참고하세요.

## 0.5 추가 (10-31 정리, 0.5.1 출력 규격 v4)

- 팀 슬라이드의 다섯 단계와 응답 필드:
  1. 문장 입력: `request.text`. 탐지 표현의 위치는 `analysis.expressions`를 원문에서 찾아 강조한다(코드 포인트 기준).
  2. 신조어·유행어 탐지: `analysis.expressions`, `routing.p_has_slang`(탐침의 예 확률).
  3. 사전·예시 검색: `routing.candidates[]`(id, expression, meaning, source, retrieval_score, p_yes)와 `examples`. MAD 경로이면 사전 항목이 없다는 안내와 `calls[].analysis.synthetic_dialogue`(합성 자료로 표시).
  4. 문맥 기반 의미 해석: `analysis.interpretation`, 경로 배지(`routing.route`).
  5. 결과: 탐지 표현, 문맥상 의미(interpretation), 쉬운 말로 바꾼 문장(`rewrite.text`, 바뀐 부분 = spans의 new_start~new_end), 쉬운 표현(`rewrite.spans`의 expression → easy), 관련 예시(`examples[0].lines[0]`), 뉘앙스, 다른 해석, 불확실성.
- `routing.route`: plain(평문 판정, 1회) / lexicon(사전 근거 풀이, 1회) / disambiguate(사전 후보 판별, 1회) / mad(증거 비대칭 토론, 5회). `routing.router.tau_sense` 이상인 후보가 탐침이 받아들인 사전 항목이다.
- 서버 실행: `python3 -m tracetalk.web.run --model 모델이름 [--lexicon 시연사전 최신사전 ...] [--examples 예시파일 ...]`. 기본 사전은 `data/db/lexicon/lexicon_demo_v1.jsonl`(495항목), 기본 예시는 `data/db/lexicon/examples_demo_v1.jsonl`(297항목, KoCulture-Dialogues, LLM 초안·사람 검수, 실제 관측 아님).
- 이벤트 stage `probe`: `analysis`가 null이고 `role`(has_slang 또는 sense)과 `p_yes`를 가진다. 묻는 항목은 `messages[1].content`의 JSON(expression, candidate_meaning)에 있다.
- 사전 후보·예시 대화는 팀 검수 전 자료다. 화면에서 검수된 답과 같은 확정 배지로 표시하지 않는다.
- UI 개발용 고정 응답 서버: `python3 tests/serve_frontier_fixture.py`(전부 MAD 경로) 또는 `--sense-yes`(사전 근거 풀이 경로). 모든 응답이 TEST-FIXTURE-NOT-A-MODEL이다. (옛 응답 예시 파일은 이 저장소에 없다.)
- 화면 동작 시험(브라우저 렌더링 아님): 맥 `/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc tests/check_frontier_ui_jsc.js`, node가 있으면 `node tests/check_frontier_ui.cjs`. `python3 -m unittest`가 있는 쪽을 자동으로 돌린다.

## 0.6 추가 (11-01, PROTOCOL single-comment-20261101-v7: 관측 용례와 DB 업데이트)

- 경로(`routing.route`) 순서: lexicon / disambiguate(사전에 뜻이 있음) → **usage_mad**(뜻은 없고 수집된 용례가 있음, 5회) → plain → mad(근거 없는 해체 토론). 용례가 평문 판정보다 먼저다: 너무 새로운 말은 모델에게 평범한 문장처럼 보일 수 있다.
- usage_mad 응답: `routing.usage_group`(id, expression, retrieval_score), `routing.usage_lines[]`(id U1.., text, context, row, source, license, note, added_at), `routing.usage_groups[]`(검색된 후보, 첫째를 씀), `routing.proposer_usages`(두 제안자가 본 용례 번호; 서로 겹치지 않음). `analysis.supporting_usages`: 판정자가 근거로 든 용례 번호(주어진 번호만 허용, 아니면 그 호출은 실패).
- 이벤트: 탐침 `role` = has_slang / sense (v7의 usage 탐침은 v8에서 뺐다: 글자 그대로 일치하는 용례가 있으면 바로 usage_mad). 제안 `analysis.usage_checks[]`(id, fits = yes/no/unclear, note), 비판 `analysis.peer_usage_checks[]`(상대 가설을 용례에 대입한 결과).
- `examples[]`(관련 용례): usage_mad이면 모델이 실제로 읽은 용례를 출처별로 묶고 판정 근거를 앞에 둔다. 각 묶음 `{entry_id, expression, lines: ["U2 · 문장", ...], source, license, note, added_at, cited: ["U2"]}`. 사전 경로이면 0.5와 같다.
- 사전 후보에 `added_at`이 있으면 tracetalk/db/update.py로 추가된 항목이다(화면: "DB 추가 시각").
- `GET /api/store`: `{lexicon_entries, usage_groups, usage_lines, latest: [{kind: 뜻|용례, expression, added_at, source}]}`. 서버는 사전·용례 파일이 바뀌면 다음 분석부터 다시 읽는다(재시작 불필요).
- 비교 방식 추가: `usage_direct`(같은 용례를 한 번에), `usage_mad`(항상 용례 MAD). 용례가 없으면 각각 direct / 해체 MAD로 대신하고 `routing.usage_group = null`.
- 서버 실행: `python3 -m tracetalk.web.run --model 모델이름 [--lexicon ...] [--usages ...] [--live data/db/live]`. 기본 용례는 `data/db/usage/usages_demo_v1.jsonl`(308표현 3,341문장, KoCulture-Dialogues: LLM 초안·사람 검수, 실제 SNS 관측 아님), 여기에 `data/db/live/entries.jsonl`·`usages.jsonl`(tracetalk/db/update.py)이 더해진다.
- 고정 응답 서버: `python3 tests/serve_frontier_fixture.py --usage-yes`(용례 MAD 경로). 모든 응답이 TEST-FIXTURE-NOT-A-MODEL이다. (옛 응답 예시 파일은 이 저장소에 없다.)

## 0.7 추가 (11-03, PROTOCOL single-comment-20261103-v9: 팀 발표자료 6쪽 결과 카드)

- 새 방식 `card`(기본 권장)·`card_single`(토론 없이 한 번에, 비교용). `POST /api/analyze {"text", "mode": "card", "seed"?, "max_seconds"?(기본 300)}`로 화면 작업을 만들고, 진행 조회는 0.4와 같다. 작업 상태는 카드 상태와 같다: completed / partial(일부 표현 실패) / failed / timed_out / cancelled.
- 팀 모듈용 `POST /api/interpret {"text", "db"?: [팀 DB 행], "seed"?, "max_seconds"?}` → 카드 결과를 바로 돌려준다(응답까지 기다림, 요청 200KB 이내, 다른 분석 중이면 409). 파이썬에서는 `tracetalk.mad.card.interpret(text, db=None, model=..., base_url=...)`. 자세한 안내와 Gradio 예시: `docs/TEAM_MODULE.md`.
- 팀 DB 행: `{"expression", "variants"?: [], "senses"?: [{"meaning", "origin"?, "pos"?, "source"?, "added_at"?}], "usages"?: [{"text", "context"?, "source"?, "added_at"?}]}` (20행, 행마다 뜻 8개·용례 12개 이하). `db`가 없으면 로컬 DB(data/db/lexicon + data/db/usage + data/db/live).
- 결과: `card = {plain, sentence(문장 해석, null 가능), sentence_problems[], items[]}`. v13(11-08 밤): `items[].easy_if`·`easy_if_source`·`easy_if_slot`(뜻 확인 필요인 DB 뜻의 쉬운 표현, 화면에는 '이 뜻이 맞다면'으로만; 없으면 빈 문자열), `card.sentence_if`·`sentence_if_by`·`sentence_if_problems[]`(그 쉬운 표현을 넣은 문장, null 가능). `easy`와 `sentence`는 그대로 확정된 뜻만 담는다. 오타 단계로 맞춘 DB 행은 확정하지 않는다(`items[].detail.typo` = DB 표제어). 글이 적은 풀이가 '다른 뜻'에 밀리면 `choice`가 R1인 확인 필요 항목이 된다. v13: `items[].post_quote`(근거 글에서 인용한 풀이 문장, 없으면 빈 문자열), `items[].post_how`(stated = 글이 정해진 꼴로 적은 풀이, summary = 4B가 글을 읽은 것, 빈 문자열 = 글을 읽지 않음). 0.9: `items[].post_meaning`, `items[].posts[{text, url, date}]`(읽은 근거 글, 둘까지), `items[].check_needed`(뜻 확인 필요), `items[].origin_from`(db / posts). `items[]` = `{expression, start, end(코드 포인트), headword, meaning(문맥상 의미), easy(쉬운 표현), origin(유래), pos(품사), db_meaning, related_usage{id, text, source, added_at, note}, status(proposed/uncertain/failed), basis(db/usage/literal/model), decided_by(single/mad/guess), choice, candidates[{id, meaning, origin, pos, source, p_yes}], alternatives[], uncertainty, supporting_usages[], clues[], usage_lines, detail, flagged_by_model}`. 실패한 표현은 `{expression, status: "failed", error}`만 있다. `detection = {db_hits[{span, expression}], model_spans[], model_note, dropped_model_spans, model_failed, p_has_slang, ordinary_words[](v9.1: 일반 낱말로 판단해 뺀 DB 표현)}`. 0.7.4: 화면 작업 결과의 `prepared{from, made_at, seconds_then, model, protocol}`(tracetalk/web/run.py --prepared로 미리 계산한 카드; 있으면 실시간이 아님을 화면에 표시), 이벤트 `{type: "prepared"}`, `detection.p_has_slang`은 `--no-slang-probe`이면 null. 0.7.3: 팀 DB 행에 `senses[].easy`(사람이 정한 쉬운 표현; 골라진 뜻이면 카드가 그대로 씀, `items[].detail.easy_from = "db"`)와 `match{span, start, end, stage, score}`(검색기가 찾은 자리) 허용. `detection.db_hits[].stage`(exact/morph/fuzzy/검색기 단계), `detection.retriever`(쓴 검색 단계, 없으면 null). v9.3: `card.sentence_by` = model / system(모델이 표현을 두 번 다 그대로 둬서 시스템이 그 낱말만 바꿈) / unchanged(평문) / null; `detection.long_model_spans`(건너뛴 4어절 넘는 모델 탐지 구절 수); `items[].detail.easy_fit` = {p: [판별 확률…], rewritten}. v9.2: 다시 묻는 요청의 `unverified_hypotheses.previous_problem`에 첫 답의 문제가 들어간다. v9.1: 쉬운 말을 다시 물어도 쓸 수 없으면 `easy`는 빈 문자열이고 `detail.easy_rejected`에 이유가 있다. `analysis`는 null이다(0.6 방식만 씀).
- 이벤트 stage(카드): `probe`(has_slang, sense), `detect`(analysis.expressions), `single`, `propose`(choice, candidate_checks, usage_checks?), `review`(peer_choice_holds, revised_choice, objections, peer_usage_checks?), `judge`, `sentence`(analysis.sentence). 후보 id: C1.. = DB 뜻, L = 표준어 낱말로 쓰임, N = 맞는 후보 없음(새 뜻).
- 화면: 기본 방식이 결과 카드다. 표현마다 근거 배지(DB 뜻 / 용례로 세운 뜻 / 표준어 낱말 / DB에 없음 · 모델 추정)와 결정 방식(한 번 / 후보 비교 토론 / 추정)을 표시하고, 추정은 확정처럼 보이지 않게 한다.
- 화면 동작 시험에 카드 경우를 추가했다(`tests/check_frontier_ui_jsc.js` 6번).
- v9.5(11-04): `items[]`에 `easy_source`(`team` 팀이 정한 쉬운 말 / `draft` 교사 초안·검수 전 / `model` 모델이 쓴 것 / 빈 값; v9.6 초안이면 `easy_slot` = 명사·꾸밈말·서술어·감탄·문장)와 `estimate`(true = DB 뜻 근거 없이 용례·문맥으로 추정한 뜻)를 추가. 화면은 `draft`면 "(교사 초안 · 검수 전)", `estimate`면 "추정한 뜻 (DB 근거 없음)"으로 표시한다.
- v9.6(11-04): `card.kept_estimates[]` = 근거 없는 추정(근거 `model`)이라 문장 해석에 넣지 않고 원문 그대로 둔 표현. 그런 표현만 있는 카드는 `sentence = null`이고 `sentence_problems`에 이유가 있다.

## 0.12~0.13 추가 (11-10~11)

- `items[].detail.exchange`: 에이전트들이 주고받은 차례 `[{agent: A~E, act: claim·read·agree·accept·object·revise·withdraw·hedge·defend·concede·recheck, ...}]`.
  E가 받아들이면 `quote`(근거 글의 문장)와 `p`(받침). 화면 문구는 `tracetalk/web/static/app.js`의 `turnLine`.
- `items[].basis`에 `context`(근거 없이 C가 문맥으로 짐작, 확정하지 않음)와 `mention`(근거 글에 언급만, 뜻 모름)이 더해졌다.
- 0.13: 낱말만 넣으면 `items[].detail.bare = true`(문맥이 없어 신조어인지 보통 낱말인지 가릴 수 없음, 확인 필요). 4B가 처음부터 쓴 쉬운 표현이
  확인되지 않으면 `items[].easy`는 빈 문자열이고 `detail.easy_fit.blanked`에 버린 말, `card.sentence`는 null(이유는 `sentence_problems`).
- 0.13: `GET /api/store`에 `posts_newest`(가장 최근 근거 글 날짜), `update`(마지막 새 글 확인 `{checked, ok, new_posts, review}`, 없으면 null).

