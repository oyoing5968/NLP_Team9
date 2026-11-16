# 자료 (data)

| 폴더 | 누가 손대나 | 내용 |
|---|---|---|
| `db/` | DB 담당 | 화면과 결과 카드가 읽는 DB. 고치는 도구와 형식은 `tracetalk/db/README.md` |
| `demo/` | 발표·시연 | 시연 문장 |
| `crawl/` | 수집기 | 허용 목록, 근거 글 주소, 수집기 측정용 정답표 |
| `eval/` | 평가 | 시험 세트와 상용 AI 비교 기록. 화면은 읽지 않는다 |

## db/ (화면이 읽는 것)

| 경로 | 내용 |
|---|---|
| `lexicon/lexicon_demo_v1.jsonl` | 처음 DB 495줄: 낱말·변형·뜻·묶음·출처 (KoCulture 파생, 비상업) |
| `lexicon/examples_demo_v1.jsonl` | 낱말별 예시 문장 (결과 카드의 "예") |
| `lexicon/easy_draft_v2.jsonl` | 쉬운 표현 초안 (팀이 정한 `easy`가 있으면 그것이 먼저) |
| `lexicon/pos_v1.jsonl` | 품사가 빠진 줄의 품사 |
| `usage/usages_demo_v1.jsonl` | 용례 (검색기가 댓글과 가까운 용례를 찾는다) |
| `live/entries.jsonl`, `live/usages.jsonl` | 팀이 더한 줄. `tracetalk/db/update.py`만 쓰고, 화면은 재시작 없이 다시 읽는다 |
| `live/corpus.jsonl` | 근거 글의 글자 (뉴스레터 네 곳, 각 뉴스레터의 저작물, 과제 안에서만 쓴다). 다시 받기 `mac/fetch_corpus.sh` |
| `live/candidates.jsonl`, `live/review_*.jsonl` | 쓰면서 쌓이는 수집 후보와 검수 기록. git과 공유 zip에 넣지 않는다 |
| `live/update_wanted`, `live/update_state.json` | 자동 업데이트(0.13)의 표시와 마지막 확인 기록. git과 공유 zip에 넣지 않는다 |
| `team_db_template.csv` | 팀이 표로 한꺼번에 넣을 때의 양식 (`update.py import`) |
| `team_db_demo_draft.csv` | 시연 DB 뜻을 그 양식으로 요약한 초안 (팀 검수 전) |
| `lexicon/lexicon_eval_v1.jsonl`, `lexicon_teacher_v1.jsonl`, `usage/usages_eval_v1.jsonl`, `usages_teacher_v1.jsonl` | 평가용·학습용 DB. 화면은 쓰지 않는다. 평가 도구(`eval/`)가 쓰고, 새 시험 세트를 만들 때 이미 아는 말을 빼는 데도 쓴다 |
| `frontier_reviewed_cache.json` | 0.4~0.6 옛 비교 방식이 읽는 검수된 뜻 목록. 일부러 비워 둠 (옛 방식이 지어낸 뜻을 검수된 것으로 쓰지 않도록) |

## demo/

| 경로 | 내용 |
|---|---|
| `showcase_v13.jsonl` | 발표 예시 5문장 + 시연 장면 7문장 (`bash mac/showcase.sh`) |
| `demo_inputs.jsonl`, `deck_inputs.jsonl`, `deck_examples.csv`, `demo_db_v13.csv` | 화면 예시 문장, 발표자료 예시와 그 DB 줄 |

## eval/ (시험 세트)

| 경로 | 내용 |
|---|---|
| `fresh_v5/` | 11월에 새로 생긴 말 18개 시험 (질문지·답·정답, `build.py`) |
| `fresh_v4/`, `fresh_v4r/` | 118문장 시험과 그 유래 정답 |
| `fresh_v1/`~`fresh_v3/`, `dev_pick/` | 개발에 쓴 세트 (0.12의 토론은 v2~v4 216문장으로 골랐다) |
| `eval_v1/` | KoCulture 기반 평가 세트 |
| `compare_v1/`~`compare_v5/` | 상용 AI 비교: 질문지, 받은 답, 출처를 가린 채점 기록 (각 폴더 README) |
| `external/` | KoCulture 원자료 (CC BY-NC-SA 4.0, `external/SOURCES.md`) |

시험 세트의 `SHA256SUMS`는 만든 뒤 바뀌지 않았음을 확인하는 지문이다. 정답(`gold.jsonl`, `key.jsonl`)은 채점에만 쓰고 모델에게 주지 않는다.
