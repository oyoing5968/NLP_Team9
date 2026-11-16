# 맥에서 돌리기 (Apple silicon) — 한 폴더 원칙

설치되는 모든 것(가상환경, Ollama, 모델, 임베딩 색인, 캐시)은 이 저장소의 `_mac_runtime/` 한 폴더 안에만 들어간다. 저장소 폴더를 지우면 전부 사라진다.
시스템 설치(Homebrew, 앱), `~/.ollama`, `~/.cache`는 쓰지 않는다. 메모리 16GB Apple silicon 맥 노트북에서 확인했다.

모든 명령은 `mac/run.sh`를 거친다. 이 스크립트가 HOME·캐시·설정·임시 폴더·pip·Hugging Face·Ollama 모델·Chroma 데이터를 `_mac_runtime` 안으로 돌리고,
사용 통계 전송을 끄고, macOS 샌드박스(`mac/sandbox/*.sb`) 안에서 실행한다(`docs/CRAWLER.md` 샌드박스 표).

## 처음 한 번

```
bash mac/install.sh                     # 아래 넷을 차례로, 이미 된 단계는 건너뜀 (인터넷 필요)
```

`install.sh`가 하는 일: `setup.sh`(가상환경: rapidfuzz·kiwipiepy·chromadb 버전 고정, Ollama 단일 실행 파일 sha256 확인, bge-m3) →
`get_model.sh release`(zip의 `release/`에 든 모델 두 조각 → 합치고 지문 확인 → `_mac_runtime/pkg/`, `model/README.md`) →
`serve.sh`(Ollama, 127.0.0.1:11435, 이 맥 안에서만) → `import_student.sh`(모델 지문을 MANIFEST와 대조한 뒤 Ollama에 등록).
git으로 받았으면 모델 조각을 GitHub 릴리스에서 받아 `bash mac/get_model.sh <조각 폴더>`. 근거 글을 처음부터 다시 받으려면 `bash mac/fetch_corpus.sh`
(인터넷, 약 8분; zip에는 이미 들어 있음).

## 쓰기

```
bash mac/start.sh                       # 켜기: 모델 서버 + 시연 화면 http://localhost:8765 (Ctrl-C 한 번에 모두 끔)
bash mac/start.sh --auto-update        # 켜기 + 자동 업데이트: 허용 뉴스레터의 새 글을 켤 때·6시간마다·모르는 말 뒤에 받음 (아래)
bash mac/demo.sh                        # 시연 화면만 (모델 서버 serve.sh를 따로 켠 경우)
bash mac/showcase.sh                    # 발표 예시 12문장을 미리 돌려 runs/v13/showcase/ 에 남김
bash mac/demo.sh --prepared <그 파일>    # 시연 때 모델이 느리면: 같은 문장은 미리 계산한 카드로(화면에 '미리 계산한 결과'로 표시)
bash mac/scene_db_update.sh             # 시연 장면: DB에 없는 말 → 한 줄 넣기(재학습 없음) → 같은 문장 다시 (실제 DB는 그대로)
bash mac/measure.sh                     # 시연 8문장 카드 시간
bash mac/crawl_new.sh                   # 새 글 한 번 받기: 보안 점검 → 근거 글에 더함 → 새 말 후보는 검수 대기열(/review) (인터넷)
bash mac/run_fresh5.sh                  # 새로 생긴 말 시험(fresh_v5) 다시 재기 (근거 글을 먼저 받아야 함)
bash mac/run.sh python -m unittest discover -s tests     # 단위 시험 (모델 없이 돎)
bash mac/sandbox_check.sh               # 샌드박스가 기대대로 막는지
```

## 자동 업데이트 (0.13, 기본은 꺼짐)

`bash mac/start.sh --auto-update [시간]`으로 켜면 `mac/auto_update.sh`가 화면과 함께 돈다(끄면 같이 꺼짐, 시스템 예약 기능을 쓰지 않음).

- 언제: 켤 때 한 번, 그다음 N시간마다(기본 6), 그리고 카드가 모르는 말을 만난 뒤(30분에 한 번까지).
- 무엇을: `mac/crawl_new.sh`와 같다. 허용 목록 뉴스레터 4곳의 새 글만 받아(크롤러 샌드박스, HTTPS) 점검하고 근거 글에 더한다. 화면은 다음 카드부터
  새 글을 읽는다. 새 글에서 뽑은 새 말은 `/review`에 '검수 전'으로만 올라가고 DB에는 사람이 승인해야 들어간다.
- 질문한 말은 어디로도 보내지 않는다: 모르는 말을 만나면 `data/db/live/update_wanted` 표시만 남고, 크롤러는 목록 페이지의 새 글을 받을 뿐이다.
- 기록: `runs/auto_update.log`, 마지막 확인 시각과 새 글 수는 `data/db/live/update_state.json`(화면 위쪽 DB 상태 줄에 보임).
- 뉴스레터가 아직 다루지 않은 말은 업데이트해도 모른다. 그때는 팀이 DB에 한 줄 넣는다(아래).

DB에 새 말 넣기(화면을 켠 채로 바로 반영):

```
bash mac/run.sh python -m tracetalk.db.update add-entry --expression <표현> --meaning "<뜻>" --easy "<쉬운 말>" --source "<출처>" [--reviewed]
bash mac/run.sh python -m tracetalk.db.update import data/db/team_db_template.csv --dry-run     # 팀 표를 한꺼번에 (검사 먼저)
```

## 폴더 안에 생기는 것 (`_mac_runtime/`)

| 경로 | 내용 | 출처·확인 |
|---|---|---|
| `venv/`, `pip_cache/` | Python 가상환경: rapidfuzz 3.13.0, kiwipiepy 0.24.1, chromadb 1.5.9 | PyPI |
| `ollama/` | Ollama v0.40.4 단일 실행 파일 | GitHub 릴리스, sha256 공식 값과 대조(`setup.sh`) |
| `models/` | bge-m3(임베딩, 관련 용례 검색), 등록한 학습 모델 | Ollama 저장소, 모델 지문(`model/SHA256SUMS`) |
| `pkg/tracetalk-student-v1/` | 학습 모델 GGUF + Modelfile + MANIFEST | `get_model.sh` |
| `chroma/` | 용례 임베딩 색인 | 처음 쓸 때 만들어짐 |
| `home/`, `cache/`, `tmp/`, `hf/`, `logs/` | 프로그램이 홈·캐시·임시로 쓰는 것, 실행 기록 | |

## DB 검색기 (`tracetalk/db/retriever.py`, 오프라인)

| 단계 | 하는 일 | 필요한 것 |
|---|---|---|
| exact | DB 표기·변형·동사 활용 그대로 | 없음 |
| morph | 형태소 기본형(귀여워 → 귀엽다) | kiwipiepy |
| fuzzy | 3글자 이상 표현의 자모 오타(편집 1개, 5글자부터 2개, 첫 자모 같음). 이렇게 맞춘 행은 확정하지 않음 | rapidfuzz |
| semantic | 그 표현의 용례를 지금 댓글과 가까운 순서로(관련 용례 검색). 행을 새로 붙이지는 않음 | chromadb + Ollama bge-m3 |

없는 라이브러리의 단계는 건너뛴다(다른 컴퓨터는 exact만으로도 돈다).

## 끝낼 때

1. `start.sh`(또는 `serve.sh`, `demo.sh`) 터미널에서 Ctrl-C.
2. `bash mac/traces.sh`(샌드박스 밖에서 직접): 폴더 밖에 남았을 수 있는 것을 "있음/없음"으로만 보여 준다. 지우지 않는다.
3. 저장소 폴더를 통째로 지운다(`_mac_runtime/`까지 함께 사라진다). macOS가 GPU 셰이더를 컴파일해 둔 시스템 캐시는 OS가 관리하는 것이라 이
   폴더로 돌릴 수 없다(`traces.sh`가 있음/없음을 보여 줌).
