# NLP_Team9 · TraceTalk 웹 디자인

`design` 브랜치는 **웹 폴더의 수정본을 공유**합니다. 좌우로 나눈 입력·결과 화면과
함수별 한국어 주석을 포함합니다.

공유 경로: [`tracetalk/tracetalk/web/`](tracetalk/tracetalk/web/)

## 팀 프로젝트에 반영

팀원이 가지고 있는 전체 TraceTalk 프로젝트에서 위 경로에 해당하는 `web/` 폴더에 반영하세요.
프로젝트 최상위에 `mac/`, `tests/`, `data/` 폴더가 있다면 그 안의 `tracetalk/web/`가 대상입니다.
팀원도 같은 파일을 수정했다면 차이를 비교해 합치세요.

**이 브랜치만으로 분석 서버를 실행할 수는 없습니다.** 분석 엔진, 데이터, 테스트 실행기와
모델 파일은 포함하지 않으므로 전체 프로젝트에 반영한 뒤 실행해야 합니다.

## 화면과 문구 수정 위치

| 파일 | 역할 |
|---|---|
| [`index.html`](tracetalk/tracetalk/web/static/index.html) | 화면 구조, 제목, 버튼, 기본 안내 |
| [`workspace.css`](tracetalk/tracetalk/web/static/workspace.css) | 좌우 배치, 색상, 글꼴, 반응형 스타일 |
| [`app.js`](tracetalk/tracetalk/web/static/app.js) | 결과 카드, 상태 안내, 검토 과정과 화면 동작 |
| [`review.html`](tracetalk/tracetalk/web/static/review.html), [`review.js`](tracetalk/tracetalk/web/static/review.js) | 수집한 표현의 검수 화면 |

웹 폴더에는 서버 코드도 있습니다. 자세한 구조는 [웹 안내](tracetalk/tracetalk/web/README.md)를 참고하세요.

## 전체 프로젝트에 반영한 뒤 화면 확인

Python 3.9 이상에서 `tests/` 폴더가 있는 프로젝트 최상위에서 실행합니다.

```bash
python tests/serve_frontier_fixture.py
```

macOS에서는 `python` 대신 `python3`를 사용할 수 있습니다.
브라우저에서 <http://localhost:8765>를 엽니다. 종료는 실행한 터미널에서 `Ctrl+C`입니다.
이 실행 방식은 **화면 확인용 테스트 응답**을 사용하며 실제 모델의 분석 결과가 아닙니다.
