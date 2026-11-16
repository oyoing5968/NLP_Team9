# 수집기 (crawl)

허용 목록의 뉴스레터 글만 받아, 파일마다 보안 점검을 하고, 새 말 후보를 사람이 검수할 표로 만든다. 자동으로 DB에 넣지 않는다.

| 파일 | 하는 일 |
|---|---|
| `fetch.py` | 받기: 허용 목록(`data/crawl/sources.txt`)의 https 주소만. 링크를 따라가지 않고, 사설·로컬 주소는 거부, 인증서 확인 |
| `audit.py` | 받은 파일마다 점검: 기록한 크기·지문, 프로그램·압축 파일 아님, UTF-8 글자, 글의 주소가 허용 목록에 있음. 스크립트·폼은 세기만 하고 실행하지 않음 |
| `extract.py`, `extract_llm.py` | 글에서 새 말과 짧은 풀이 뽑기(규칙 / 4B) |
| `pages.py` | 명령: `fetch`, `audit`, `extract`, `discover`, `llm-extract`, `check-out` |

실행은 바깥 연결이 열린 크롤러 전용 샌드박스(`mac/sandbox/crawl.sb`)에서만: `bash mac/crawl_new.sh`, `bash mac/fetch_corpus.sh`.
`crawl_new.sh`(0.13): 새 글을 근거 글에 더하고, 새 글에서 뽑은 새 말은 검수 대기열(`/review`)에 '검수 전'으로만 올리며, 확인 시각을
`data/db/live/update_state.json`에 남긴다. 자동으로: `bash mac/start.sh --auto-update`(켤 때·6시간마다·모르는 말 뒤, `mac/README.md`).
받은 원본은 `_crawl/`(git에 올리지 않음), 근거 글의 글자는 `data/db/live/corpus.jsonl`.

규칙과 측정: `docs/CRAWLER.md`. 시험(바깥 연결 없이): `tests/test_fetch.py`, `test_crawl.py`, `test_crawl_llm.py`.
