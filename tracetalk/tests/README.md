# 시험 (tests)

모델 없이 돈다. 모델 자리에는 가짜 모델(`frontier_fixture.py`, 답에 TEST FIXTURE라고 적힘)이 들어가므로, 여기서는 규칙과 형식만 확인하고 뜻이 맞는지는 재지 않는다(그것은 `eval/`).

```
bash mac/run.sh python -m unittest discover -s tests          # 전부 (345개, 맥에서 20초쯤)
bash mac/run.sh python -m unittest tests.test_v16 -v          # 파일 하나
```

## 어느 파일이 어느 부분을 지키나

| 부분 | 시험 파일 |
|---|---|
| 해석 `tracetalk/mad/` (결과 카드, 에이전트, 토론, 판정) | `test_v16.py`(토론·MAD 우선·0.12 기본값·낱말만 넣었을 때), `test_mad09.py`(판정, 0.11 설정으로 고정), `test_v13_card.py`, `test_v14.py`, `test_v15.py`, `test_v09.py`, `test_v095.py`(쉬운 표현), `test_v08.py`, `test_v081.py`, `test_v05.py`(옛 비교 방식) |
| DB `tracetalk/db/` | `test_retriever.py`(검색기가 카드와 맺은 약속), `test_team_db.py`(팀 표 넣기), `test_review.py`(검수 대기), `test_v07.py`(용례) |
| 근거 글 `tracetalk/evidence/` | `test_corpus.py`(대목 고르기), `test_v13.py`(글이 적어 둔 풀이 읽기), `test_v16.py`의 두쫀쿠 대목 |
| 수집기 `tracetalk/crawl/` | `test_fetch.py`(받기·보안 점검, 바깥 연결 없이), `test_crawl.py`, `test_crawl_llm.py` |
| 자동 업데이트 `mac/auto_update.sh` | `test_v18.py`(모르는 말의 업데이트 표시, 화면의 새 글 시각, 켤 때·표시 뒤에 도는 순서; 크롤러 대신 가짜 명령) |
| 화면 `tracetalk/web/` | `test_frontier.py`(서버와 HTTP), `test_v05.py`의 `UIHarnessTests`가 `check_frontier_ui_jsc.js`(맥 JavaScriptCore)와 `check_frontier_ui.cjs`(node)를 돌린다. 검수 화면은 `check_review_ui_jsc.js`(손으로, 아래) |
| 평가 `eval/` | `test_fresh.py`~`test_fresh4.py`(채점 규칙), `test_eval_kit.py`, `test_training_prep.py`, `test_v096.py`(질문에 시험 낱말이 새지 않음) |
| 모델 연결·설치 | `test_local_verification.py`, `test_adapters.py` |

`check_frontier_ui.cjs`는 node가 있을 때만 돈다(없으면 건너뜀, 맥에서는 JavaScriptCore 쪽이 같은 것을 확인한다).
검수 화면(`/review`) 확인은 손으로 한 줄: `/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc tests/check_review_ui_jsc.js`

## 화면만 볼 때 (모델 없이)

```
python3 tests/serve_frontier_fixture.py     # http://localhost:8765 , 답은 모두 가짜(TEST FIXTURE). 실제 화면과 같이 켜려면 --port 8766
```

화면 담당이 맥·윈도 어디서든 화면을 고쳐 볼 수 있다. 가짜 답의 형식은 실제 카드와 같다(`tracetalk/web/README.md`).

## 고칠 때

- 동작을 바꾸면 그 동작을 지키는 시험을 같이 고치고, 왜 바꿨는지 시험 이름이나 주석에 남긴다.
- `test_mad09.py` 등 옛 판의 시험은 설정을 0.11로 고정(`V011`)해 옛 동작을 지킨다. 0.12 기본값은 `test_v16.py`의 `DefaultsTests`가 지킨다.
