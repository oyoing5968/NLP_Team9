# TraceTalk: 근거를 보여 주는 신조어·밈 해석기

> 댓글 한 줄을 넣으면 신조어·밈을 찾아 **이 문장에서의 뜻, 쉬운 표현, 유래**를 보여 준다.
> 뜻마다 **근거**(믿을 수 있는 신조어 뉴스레터의 주소·날짜·인용 문장, 팀 DB)를 함께 보이고, 근거가 없으면 지어내서 확정하지 않는다("뜻 모름" 또는 "문맥으로 짐작 · 확인 필요").
> 노트북(맥) 안에서 인터넷 없이 돈다. 대화가 밖으로 나가지 않는다.

11조 프로젝트. 발표자료의 흐름 그대로: **문장 입력 → 신조어·유행어 탐지 → 관련 용례 검색 → 문맥 기반 의미 해석(MAD) → 쉬운 표현 및 설명.**
MAD에서는 같은 4B 모델이 근거를 달리 받은 에이전트 다섯(A DB · B 근거 글 · C 가린 문맥 · D 반대 근거 · E 검증)으로 나뉘어 서로 따지고, 판정자가 고른다.

## 왜 TraceTalk인가

| | 무엇 | 근거 |
|---|---|---|
| 1 | **대화가 밖으로 나가지 않는다.** 무료, 계정 없음, 노트북 안에서 | 모든 명령이 맥 샌드박스 안에서 돌고 바깥 인터넷은 막힌다(`bash mac/sandbox_check.sh`, 19개 시도 모두 막힘) |
| 2 | **에이전트가 근거로 서로 따진다 (MAD).** | B가 글에서 읽은 뜻을 E가 글의 문장으로 확인하고, 못 받치면 반박한다. B는 고치거나 물러나고, 받쳐지지 않는 뜻은 확정하지 않는다. D는 "글자 그대로 쓴 것 아니냐"고 반박한다. 개발 216문장: 맞음 151 → 152, 확정 오답 23 → 20 |
| 3 | **모르면 모른다고 한다.** | 새로 생긴 말 18개 시험에서 지어낸 유래 0개 (작은 AI 혼자 4~11개, 상용 AI 2개) |
| 4 | **근거와 판단 과정을 보여 준다.** | 결과 카드에 근거 글의 주소·날짜·인용 문장과 에이전트들이 주고받은 말(주장·확인·반박·물러남)이 나온다 |
| 5 | **노트북에서 도는 것 중 가장 정확하다.** | 우리가 시험한 로컬 모델 셋(4B 둘, 7.8B 하나)이 혼자 0~3개 맞힐 때 11개 |
| 6 | **우리 DB를 붙이면 상용 AI도 좋아진다.** | Gemini에 우리 DB 자료를 주자 유래 18/18, 지어낸 유래 0 (웹 검색 Gemini는 16, 2개 지어냄) |

11월에 새로 생긴 말 18개(댓글 18개), 출처를 가린 채점(채점자 둘, 갈리면 셋째):

| | 뜻 맞음 | 확신하고 틀림 | 유래 맞음 | 지어낸 유래 |
|---|---|---|---|---|
| 우리 학습 4B 혼자 | 0 | 4 | 0 | 11 |
| Qwen3.5-4B 혼자 | 1 | 4 | 0 | 4 |
| EXAONE 7.8B 혼자 (비교만) | 3 | 5 | 1 | 4 |
| **TraceTalk** (노트북, 4B + DB + MAD) | **11** | 2 | 9 | **0** |
| Gemini 3.8 Flash, 검색 끔 | 18 | 0 | 10 | 2 |
| Gemini 3.8 Flash, 웹 검색 | 18 | 0 | 16 | 2 |
| **Gemini + TraceTalk DB** (검색 끔) | **18** | **0** | **18** | **0** |

- TraceTalk 숫자는 이 시험 전에 얼려 둔 0.10의 것이다. 지금 판(0.12)은 마지막 새 시험에서 다시 잰다.
- 뜻은 상용 AI가 앞선다. TraceTalk는 상용 AI를 대신하지 않고, 상용 AI가 비워 둔 곳(근거, 지어내지 않기, 대화를 밖으로 안 보내기)을 채운다.
- 같은 4B에 같은 근거를 한 번에 주면 8개, MAD로 나눠 판단하면 11개다(확신하고 틀림 6 → 2).
- 0.12는 에이전트끼리 따지는 토론을 더했다. 개발 216문장(출처를 가린 채점)에서 맞음 151 → 152, 확정 오답 23 → 20. 개발 점수라 마지막 새 시험에서 확인한다(`docs/RESULTS.md` 5).
- 자세한 기준·결과·한계: `docs/RESULTS.md`. 답별 판정: `eval/results/*.csv`.

## 사용법

화면은 브라우저에서 보는 웹 페이지다(발표자료의 Gradio 자리). Apple silicon 맥(M1 이상, 메모리 16GB 권장, 빈 공간 15GB쯤)에서 돈다.
처음 설치에만 인터넷이 필요하고, `python3`가 없으면 먼저 `xcode-select --install`. 윈도는 화면만(모델 없이, `tests/README.md`).

```
bash mac/install.sh    # 처음 한 번 (인터넷 필요): 설치물과 모델 등록, 모두 _mac_runtime/ 한 폴더 안
bash mac/start.sh      # 켜기 (끄기: Ctrl-C)
bash mac/start.sh --auto-update    # 켜기 + 자동 업데이트: 허용 뉴스레터의 새 글을 켤 때·6시간마다·모르는 말 뒤에 받음
```

브라우저에서 **http://localhost:8765** 를 연다. 댓글을 넣으면 결과 카드가 나온다(시연 문장은 평균 10초쯤, 어려운 문장은 25초쯤).
수집기와 크롤러가 모은 새 말을 사람이 검수하는 화면은 **http://localhost:8765/review** 다.

**자동 업데이트(0.13, 기본은 꺼짐):** 질문은 노트북 안에서만 풀고, 근거 글만 밖에서 받아 온다. 모르는 말을 만나면 그 말을 보내는 대신 "새 글을
확인해 달라"는 표시만 남기고, 크롤러가 허용한 뉴스레터 4곳의 새 글을 받아 점검한 뒤 근거 글에 더한다(다음 카드부터 읽음). 새 글에서 뽑은 새 말은
검수 화면에 '검수 전'으로만 올라간다. 뉴스레터가 아직 다루지 않은 말은 업데이트해도 모르므로, 그때는 팀이 DB에 한 줄 넣는다(아래 명령, 재시작 없이 반영).

자주 쓰는 것 (모두 한 줄 명령, 자세히는 `mac/README.md`):

```
bash mac/showcase.sh                                  # 발표 예시 12문장을 미리 돌려 둔다 (runs/v13/showcase/, 켜기와 따로: serve.sh 필요)
bash mac/start.sh --prepared runs/v13/showcase/<파일>  # 시연 때 모델이 느리면: 미리 계산한 카드로 (화면에 표시됨)
bash mac/run.sh python -m tracetalk.db.update add-entry --expression <표현> --meaning "<뜻>" --easy "<쉬운 말>" --source "<출처>"
bash mac/run.sh python -m tracetalk.db.update import data/db/team_db_template.csv --dry-run   # 팀 표를 한꺼번에 (검사 먼저)
bash mac/crawl_new.sh                                 # 새 글 한 번 받기 (바깥 연결): 근거 글에 더하고 새 말 후보는 /review로
bash mac/run.sh python -m unittest discover -s tests  # 단위 시험 345개 (모델 없이, tests/README.md)
bash mac/sandbox_check.sh                             # 샌드박스가 바깥 연결을 막는지
```

`install.sh`가 하는 일: `setup.sh`(가상환경·Ollama·임베딩 모델) → `get_model.sh release`(모델 두 조각을 합치고 지문 확인) →
`import_student.sh`(모델 등록). `start.sh`는 `serve.sh`(모델 서버)와 `demo.sh`(화면 서버)를 한 번에 켠다.
설치되는 것은 모두 `_mac_runtime/` 한 폴더에 들어간다. 폴더를 지우면 흔적이 남지 않는다(`bash mac/traces.sh`로 확인).

## 폴더

```
tracetalk/          엔진 (파이썬)
├── mad/            ① 해석: 탐지 → 에이전트(A DB · B 근거 글 · C 가린 문맥 · D 반대 근거 · E 검증)의 토론 → 판정 → 결과 카드  (card.py)
├── db/             ② 신조어 DB: 사전, 검색기, 용례, 검수 대기, DB 고치는 도구  (update.py)
├── evidence/       ③ 근거 글: 뉴스레터 글에서 그 말을 다룬 대목 찾기·읽기
├── crawl/          ④ 수집기: 허용 목록 받기 → 보안 점검 → 새 말 뽑기  (pages.py)
├── web/            ⑤ 화면: 서버(run.py, server.py)와 웹 페이지(static/)
├── model.py        모델 연결 (Ollama)
└── verify.py       설치 점검
mac/                맥 실행 키트: 설치·실행·시연·샌드박스 (.sh)
eval/               평가: 시험 실행, 상용 AI 질문지, 출처를 가린 채점, results/ 결과 표
data/               db/(화면이 읽는 DB) · demo/(시연 문장) · crawl/(수집기 목록) · eval/(시험 세트, 상용 AI 답)
docs/               결과, 설계, 발표자료 수정안, 크롤러와 보안
model/              학습 모델 정보·지문 (모델 두 조각은 release/, git에서는 GitHub 릴리스)
tests/              단위 시험 (모델 없이)
```

git에 올리지 않는 것(`.gitignore`): `_mac_runtime/`(설치물·모델, `install.sh`가 만듦), `runs/`(실행 기록), `_crawl/`(받은 글 원본 페이지),
`release/`(모델 두 조각 2.7GB: git의 파일 크기 제한 때문. 과제 공유용 zip에는 들어 있음), `_work/`(개발 메모).

## 누가 어디를 고치나

| 담당 | 고치는 곳 | 먼저 읽을 것 | 고친 뒤 확인 |
|---|---|---|---|
| 화면 | `tracetalk/web/static/` (app.js, index.html, review 화면) | `tracetalk/web/README.md` (API와 카드 필드) | 모델 없이 `python3 tests/serve_frontier_fixture.py` 후 http://localhost:8765 , 시험 `test_v05.py`·`test_frontier.py` |
| DB·검색기 | `tracetalk/db/` (retriever.py 등), `data/db/` | `tracetalk/db/README.md` (DB 한 줄 형식, 검색기가 카드와 맺은 약속) | `tests/test_retriever.py`, 성능 `bash mac/run.sh python eval/retrieval_bench.py` |
| MAD | `tracetalk/mad/card.py` (설정은 맨 위 `CARD`) | `tracetalk/mad/README.md`, `docs/DESIGN.md` | `tests/test_v16.py` 등, 실제 모델로 `bash mac/showcase.sh` |
| 근거 글 | `tracetalk/evidence/` | `tracetalk/evidence/README.md` | `tests/test_corpus.py`, `test_v13.py` |
| 수집기 | `tracetalk/crawl/`, 허용 목록 `data/crawl/sources.txt` | `tracetalk/crawl/README.md`, `docs/CRAWLER.md` | `tests/test_fetch.py` (바깥 연결 없이) |
| 평가 | `eval/`, `data/eval/` | `eval/README.md`, `docs/RESULTS.md` | `tests/test_fresh*.py` |

어느 시험이 어느 부분을 지키는지는 `tests/README.md`. 화면만 고칠 때는 모델도 맥도 필요 없다(파이썬 3.9 이상, 맥 시스템 파이썬으로 확인했고 윈도는 해 보지 않음).

## 발표자료와 코드

| 발표자료 | 코드 |
|---|---|
| 신조어·유행어 탐지 | `tracetalk/mad/card.py`, `tracetalk/db/retriever.py`(형태소·오타·임베딩) |
| 관련 용례 검색 | `tracetalk/db/usage.py`, `tracetalk/evidence/corpus.py` |
| 문맥 기반 의미 해석 (MAD) | `tracetalk/mad/card.py` (에이전트 A~E의 토론과 판정) |
| 쉬운 표현 및 설명 | `tracetalk/mad/card.py`, 화면 `tracetalk/web/static/` |
| 언어 자원 축적 (기대효과) | 수집기 `tracetalk/crawl/` → 검수 화면 → `tracetalk/db/update.py` |

발표자료와 달라진 것: 에이전트를 A·B·C에서 다섯으로 늘렸다(D 반대 근거, E 검증). 에이전트는 입장을 맡아 말로 다투지 않고 근거로 따진다
(말로 다투게 하는 방식은 재 보니 나빠졌다: 92문장 68 대 75).
화면은 Gradio 대신 자체 웹 페이지다. 5쪽의 "LLM은 최신 표현을 잘못 해석"은 작은 로컬 모델에만 맞았다(`docs/SLIDES.md`).

## 한계

- 뜻 정확도는 상용 AI에 못 미친다(새 말 11 대 18).
- DB와 근거 글에 없는 말은 확정하지 못한다("뜻 모름" 또는 문맥으로 짐작한 뜻을 "확인 필요"로). 근거 글이 있어도 그 말이 글에 (거의) 그대로
  나오지 않으면 읽지 못한다.
- 4B 에이전트는 반박을 받으면 뜻을 고치기보다 물러나고, D의 반박은 늘 인정했다(개발 216문장). 토론 때문에 문장당 3초쯤 느려졌다.
- 같은 글자를 표준어로 쓴 문장을 밈으로 볼 때가 있다('그 범인은 내가 반드시 체포하겠어').
- 근거 글은 허용한 신조어 뉴스레터 네 곳(트렌드어워드, 파밍레터, 고구마팜, 위픽레터)뿐이다. 그곳에 실리기 전의 아주 새 말은 모른다
  (11-11 '오디세이': 근거 글에 없어 '뜻 모름' → 새 글을 받자 원문 인용과 함께 해석, `docs/RESULTS.md` 5-2). 자동 업데이트는 이 간격을 줄일 뿐
  없애지 못한다. 4B가 처음 쓴 쉬운 표현이 뜻과 맞는지 확인되지 않으면 문장은 바꾸지 않는다.
- 시험 문장 일부와 정답표는 AI가 정리했고 채점자도 출처를 모르는 AI다. 사람 검수는 아직 없다.
- "Gemini + DB"의 정답 유래는 DB와 같은 뉴스레터에서 왔다. 그래서 이 시험은 "출처가 확인된 자료를 주면 상용 AI가 그것을 쓰는가"를 잰 것이다.

## 라이선스

`NOTICE.md`. 처음 DB·평가 세트·학습 자료는 KoCulture(CC BY-NC-SA 4.0) 파생이라 **비상업**이다.
근거 글(`data/db/live/corpus.jsonl`)은 각 뉴스레터의 저작물이고, 과제 안에서 시연·시험에만 쓴다.
KoNeoBench는 평가에만 썼고 이 저장소에 없다. EXAONE은 비교 실험에만 썼다.
