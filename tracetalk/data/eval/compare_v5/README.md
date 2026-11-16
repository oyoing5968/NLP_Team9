# fresh_v5 상용 AI 비교 (새로 생긴 말)

설계와 기준(N1~N5)은 `docs/DESIGN.md`의 "fresh_v5"에 실행 전에 적었다. 문장·정답은 `data/eval/fresh_v5/`(지문 `SHA256SUMS`).

## 답을 받는 법

- Gemini 웹 끔: 새 임시 채팅에 `data/eval/fresh_v5/ask_alone.txt`를 그대로 붙여 넣는다. 답을 `data/eval/fresh_v5/answers_alone.txt`에 그대로 저장한다.
- Gemini 웹 켬: 새 채팅에 `data/eval/fresh_v5/ask_web.txt`를 붙여 넣는다. 답을 `data/eval/fresh_v5/answers_web.txt`에 저장한다.
- 모델 이름과 날짜를 각 답 파일 첫 줄에 `# Gemini …, 2026-11-..` 꼴로 적는다(번호 줄만 읽으므로 채점에 영향 없음).
- TraceTalk: `bash mac/run_fresh5.sh` (서버 `mac/serve.sh`가 켜져 있어야 함) → `runs/v13/fresh_v5/full.jsonl`, `single.jsonl`.

## 가린 채점 (회차별, 11-08 밤에 바꿈)

답이 들어오는 때가 달라(TraceTalk 먼저, Gemini는 사용자가 받아 오면) 회차로 나눠 매긴다. 회차마다 아직 아무 회차도 매기지 않은 답만 보인다
(같은 문장의 같은 글자는 한 번만 매김). 채점 규칙 문구와 결과 규칙, 기준 N1~N5는 그대로다.

1. `python3 eval/fresh5_sheet.py sheet --round 1 --runs full=runs/v13/fresh_v5/full.jsonl single=runs/v13/fresh_v5/single.jsonl`
   → `judge_meaning_1.txt`, `judge_origin_1.txt`(채점 규칙이 맨 위에 있음), 출처 열쇠 `_blind_key_1.json`(채점자에게 주지 않음).
2. 채점자 둘이 따로 매긴다(`judge1_meaning_1.json`, `judge2_meaning_1.json`, 유래도 같음). 채점자는 표 파일만 읽고 결과 JSON만 쓴다.
3. `python3 eval/fresh5_sheet.py merge --round 1` → 갈린 표시가 있으면 `judge_*_1_dispute.txt`를 세 번째 채점자가 매기고
   (`judge3_meaning_1.json`) 다시 merge. 표시는 `marks_meaning.json`, `marks_origin.json`에 쌓인다.
4. Gemini 답이 오면 같은 명령을 `--round 2`로(같은 `--runs`와 함께) 되풀이한다.
5. `python3 eval/fresh5_sheet.py apply --runs …` → 뜻·보류·확정 오답·유래·지어낸 유래·감지·시간, 기준 N1~N5.
