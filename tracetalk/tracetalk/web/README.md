# 화면 (web)

댓글을 넣으면 결과 카드를 보여 주는 웹 페이지와, 그 페이지에 결과를 주는 작은 서버.

| 파일 | 하는 일 |
|---|---|
| `static/index.html`, `static/app.js`, `static/workspace.css` | 좌우 비교 화면. 왼쪽 원문 입력, 오른쪽 뜻과 쉬운 표현 / 근거 / 검토 과정 탭. 올리브 그레이와 피치 색상, 760px 이하에서는 세로 배치 |
| `static/styles.css` | 화면 공통 기본 스타일. 검수대 스타일도 포함 |
| `static/review.html`, `static/review.js` | 수집기가 모은 새 말을 사람이 검수하는 화면 (`/review`) |
| `server.py` | HTTP 서버: 화면 파일과 `/api/*`. 이 컴퓨터에서 온 요청만 받는다 |
| `run.py` | 서버를 켜는 명령(모델·DB·근거 글을 붙여서). 보통은 `bash mac/start.sh`로 켠다 |

## 모델 없이 화면만 고치기 (맥·윈도우 모두, 설치 없음)

```
python tests/serve_frontier_fixture.py
```

브라우저에서 http://localhost:8765. 파이썬 3.9 이상만 있으면 된다. 가짜 모델(TEST-FIXTURE)이 정해진 답을 주므로 뜻은 의미가 없고,
화면 모양·문구·배치·흐름을 고칠 때 쓴다. 실제 모델로 보려면 Apple silicon 맥에서 `bash mac/install.sh` 뒤 `bash mac/start.sh`.

## 화면과 서버가 주고받는 것

| 요청 | 하는 일 |
|---|---|
| `GET /api/health` | 모델 연결 상태 |
| `POST /api/analyze` `{"text": "...", "mode": "card"}` → `{"job_id"}` | 분석 시작 (`mode`는 `card` 또는 비교용 `card_single`) |
| `GET /api/jobs/<id>?after=<cursor>` | 진행 이벤트와 끝난 결과 |
| `POST /api/jobs/<id>/cancel` | 중지 |
| `POST /api/interpret` `{"text": "..."}` | 기다렸다가 결과 카드를 한 번에 (다른 프로그램이 붙을 때) |
| `GET /api/store`, `/api/config`, `/api/review` | DB 상태, 설정, 검수 대기열 (`POST /api/review`로 검수 결정). 0.13: `/api/store`에 `posts_newest`(가장 최근 근거 글 날짜)와 `update`(마지막 새 글 확인: `checked`, `ok`, `new_posts`, `review`) |

결과 카드는 표현마다 항목(item) 하나다. 화면이 쓰는 주요 필드:

| 필드 | 뜻 |
|---|---|
| `expression`, `meaning`, `easy`, `origin` | 표현, 이 문장에서의 뜻, 쉬운 표현, 유래 |
| `basis` | 뜻의 근거: `db` DB 뜻 · `post` 근거 글에서 읽음 · `usage` 쌓인 용례 · `context` 근거 없이 문맥으로 해석 · `mention` 근거 글에 언급만 · `model` 근거 없음 · `literal` 표준어 |
| `status`, `check_needed`, `uncertainty` | 확정(`proposed`) 또는 유보(`uncertain`), 뜻 확인 필요, 그 이유 |
| `posts`, `post_quote` | 근거 글(`text`, `url`, `date`), 뜻을 받치는 문장 |
| `alternatives` | 다른 해석(문맥으로 읽은 뜻, 글자 그대로 등) |
| `detail.scores` | 판정 확률(보기마다) |
| `detail.exchange` | MAD 토론 기록: `[{"agent": "A"·"B"·"C"·"D"·"E", "act": "claim"·"read"·"accept"·"object"·"revise"·"withdraw"·"hedge"·"defend"·"concede"·"recheck"·"agree", ...}]`. 화면 문구는 `app.js`의 `turnLine` |

더 자세한 규격: `docs/API_CONTRACT.md`, `docs/TEAM_MODULE.md`.

## 시험

- `tests/check_frontier_ui.cjs`(node), `tests/check_frontier_ui_jsc.js`(맥 JavaScriptCore): `app.js`를 가짜 DOM에 올려 화면 동작을 확인한다.
  `tests/test_v05.py`의 `UIHarnessTests`가 둘을 돌린다.
- 화면을 바꾸면 위 두 파일의 기대값도 함께 맞춘다.

## 고칠 때 지킬 것

- 모델이 쓴 글자는 `textContent`로만 넣는다(HTML로 해석하지 않음).
- 확인 필요(`check_needed`)나 근거 없음(`context`, `model`)인 뜻을 확정처럼 보이게 하지 않는다.
