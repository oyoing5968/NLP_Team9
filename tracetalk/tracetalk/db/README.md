# 신조어 DB와 검색기 (db)

| 파일 | 하는 일 |
|---|---|
| `lexicon.py` | DB 한 줄 읽기와 검사, 표기 맞추기(`compact`) |
| `retriever.py` | 댓글에서 DB 낱말 찾기 4단계: `exact` 표기·변형 → `morph` 형태소 기본형(kiwipiepy) → `fuzzy` 자모 오타(RapidFuzz) → `semantic` 임베딩(bge-m3 + ChromaDB, 용례 순서) |
| `usage.py` | 용례 묶음, 팀이 더한 줄을 재시작 없이 다시 읽는 `LiveStore`, 수집기(카드가 만난 DB에 없는 말) |
| `review.py` | 수집기·크롤러가 찾은 새 말의 검수 대기열 (화면 `/review`) |
| `update.py` | DB를 고치는 유일한 도구(명령): `add-entry`, `add-usage`, `import`, `queue`, `review-add`, `corpus-add` … |

## DB 한 줄 (jsonl)

반드시: `id`, `expression`, `variants`(목록), `meaning`, `family`, `source`, `license`.
있으면: `origin`, `pos`, `easy`(팀이 정한 쉬운 표현), `review`(`검수됨` 또는 `검수 전`), `added_at`.
팀이 표로 한꺼번에 넣을 때의 양식: `data/db/team_db_template.csv` (`update.py import`가 먼저 검사하고 전부 넣거나 하나도 안 넣음).

```
bash mac/run.sh python -m tracetalk.db.update add-entry --expression <표현> --meaning "<뜻>" --easy "<쉬운 말>" --source "<출처>"
bash mac/run.sh python -m tracetalk.db.update import data/db/team_db_template.csv --dry-run
```

## 검색기가 결과 카드와 주고받는 약속 (바꿀 때 지킬 것)

결과 카드(`tracetalk/mad/card.py`)는 검색기에서 이것만 쓴다.

| 쓰는 것 | 형식 |
|---|---|
| `hits(text, entries)` | `[{"start", "end", "span", "entry", "stage", "score"}]`: 댓글 속 위치와 그 DB 줄 |
| `evidence(group, text, limit)` | 그 표현의 용례 가운데 댓글과 가까운 것 |
| `unknown_words(text)` | 형태소 분석기가 모르는 낱말(새 말 후보) |
| `usage_index.embed(texts)` | 문장 벡터 (MAD가 뜻끼리 닮은 정도를 잴 때) |
| `stages` | 켠 단계 이름 |

`tests/test_retriever.py`가 이 약속을 확인한다. 성능은 모델 없이 `bash mac/run.sh python eval/retrieval_bench.py`.

## 자료

`data/db/`: `lexicon/`(처음 DB, `lexicon_demo_v1.jsonl`이 시연용), `usage/`(용례), `live/`(팀이 더한 줄, `update.py`가 씀), `team_db_template.csv`.
`live/`에는 쓰면서 생기는 것도 있다: 수집 후보 `candidates.jsonl`, 검수 기록 `review_*.jsonl`, 자동 업데이트 표시 `update_wanted`·`update_state.json`
(0.13, 모두 git과 공유 zip에서 뺌).
처음 DB는 KoCulture(CC BY-NC-SA 4.0) 파생이라 비상업(`NOTICE.md`).

## 시험

`tests/test_retriever.py`, `test_team_db.py`, `test_review.py`, `test_v07.py`(용례), `test_v08.py`(수집기)
