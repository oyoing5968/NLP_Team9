# NLP_Team9 · TraceTalk

`design` 브랜치에는 **TraceTalk 전체 코드·데이터·문서**와 수정한 웹 화면,
함수별 한국어 주석을 포함합니다. 프로젝트 본체는 [`tracetalk/`](tracetalk/)입니다.

웹 화면, 분석 엔진, 사전·용례·근거 글, 수집기, 실행 스크립트, 테스트와 평가 자료를 함께 공유합니다.

## 내려받고 화면 확인

Python 3.9 이상에서 다음 명령을 실행합니다.

```bash
git clone --branch design --single-branch https://github.com/oyoing5968/NLP_Team9.git
cd NLP_Team9/tracetalk
python tests/serve_frontier_fixture.py
```

ZIP으로 받은 경우 압축을 풀고 `tests/` 폴더가 있는 `tracetalk/`에서 마지막 명령을 실행하세요.
macOS에서는 `python` 대신 `python3`를 사용할 수 있습니다.
브라우저에서 <http://localhost:8765>를 엽니다. 종료는 실행한 터미널에서 `Ctrl+C`입니다.

이 실행 방식은 **화면 확인용 테스트 응답**을 사용합니다. 실제 모델의 해석이나 성능을 나타내지 않습니다.

## 화면과 문구 수정 위치

| 파일 | 역할 |
|---|---|
| [`index.html`](tracetalk/tracetalk/web/static/index.html) | 화면 구조, 제목, 버튼, 기본 안내 |
| [`workspace.css`](tracetalk/tracetalk/web/static/workspace.css) | 좌우 배치, 색상, 글꼴, 반응형 스타일 |
| [`app.js`](tracetalk/tracetalk/web/static/app.js) | 결과 카드, 상태 안내, 검토 과정과 화면 동작 |
| [`review.html`](tracetalk/tracetalk/web/static/review.html), [`review.js`](tracetalk/tracetalk/web/static/review.js) | 수집한 표현의 검수 화면 |

웹 폴더에는 서버 코드도 있습니다. 자세한 구조는 [웹 안내](tracetalk/tracetalk/web/README.md)를 참고하세요.

## 실제 모델 실행

[프로젝트 사용법](tracetalk/README.md)과 [모델 안내](tracetalk/model/README.md)를 참고하세요.
약 2.7GB의 모델 가중치 두 조각은 기존 `.gitignore` 설정에 따라 Git에 포함하지 않습니다.
이 저장소를 받는 것만으로 모델 파일까지 내려받아지지는 않습니다. 실제 모델을 실행하려면
별도로 전달받은 두 조각을 `tracetalk/release/`에 넣거나 모델 안내에 따라 준비해야 합니다.

실행 결과(`runs/`), 설치물·캐시, 실행 중 쌓이는 검수 기록 등도 기존 제외 설정을 따릅니다.

## 확인

프로젝트 폴더(`tracetalk/`)에서 다음 명령으로 화면 동작과 서버를 확인할 수 있습니다.

```bash
node tests/check_frontier_ui.cjs
python -m unittest discover -s tests -p test_frontier.py
```

Node.js는 첫 번째 화면 동작 검사에만 필요합니다. 전체 테스트와 macOS 전용 검사는
[테스트 안내](tracetalk/tests/README.md)를 참고하세요.
