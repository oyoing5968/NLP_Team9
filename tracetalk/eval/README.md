# 평가 도구

모두 `bash mac/run.sh python eval/<파일>.py ...`로 돈다. 결과 표는 `eval/results/`, 시험 세트는 `data/`에 있다.

## 지금 쓰는 것

| 파일 | 하는 일 |
|---|---|
| `run_bench.py` | TraceTalk를 시험 문장에 돌린다 (모든 시험·시연 대비의 실행기) |
| `card_report.py` | 실행 결과 요약: 카드가 어떻게 나왔는지 (`mac/showcase.sh`가 부름) |
| `ask_local.py` | 로컬 모델 혼자 상용 AI와 같은 질문지에 답하게 한다 (비교군) |
| `ask_with_db.py` | 상용 AI + TraceTalk DB 질문지: 댓글마다 TraceTalk가 찾은 DB 풀이와 근거 글 발췌를 붙인다 |
| `fresh5_sheet.py` | 새로 생긴 말 18개 시험(fresh_v5)의 출처를 가린 채점표와 집계 |
| `fresh4_sheet.py`, `fresh4_more.py`, `fresh4_report.py` | 118문장 시험(fresh_v4)의 채점표와 집계 |
| `build_fresh.py` | 새 말 시험 세트 만들기 (fresh_v1~v5를 만든 도구) |
| `post_bench.py` | 근거 글이 새 말에 닿는가 (모델 없이) |
| `retrieval_bench.py` | DB 검색기가 댓글에서 맞는 DB 줄을 찾는가 (모델 없이) |
| `show_demo.py` | 시연 문장의 입력 → 출력을 사람이 읽기 좋게 |
| `gguf_audit.py`, `export_ollama_model.py` | 모델 파일 머리말 점검, 모델 내보내기 |

## 학습과 DB 만들기 (한 번 한 것)

| 파일 | 하는 일 |
|---|---|
| `build_eval.py` | KoCulture 원자료(`data/eval/external`) → 평가 세트 `data/eval/eval_v1` |
| `build_usages.py`, `build_examples.py` | 처음 DB의 용례·관련 예시 |
| `draft_easy.py` | DB 뜻에 쉬운 표현 초안 (팀이 쓴 표현이 우선) |
| `export_sft.py`, `export_sft_card.py`, `train_lora.py` | 학습 자료 만들기와 LoRA 학습 (GPU 한 장에서 한 번) |
| `grade.py` | LLM 채점기: `run_bench.py`의 실행 기록을 따로 둔 정답과 대조 (지난 시험) |

## 지난 시험 기록 (결과 재현용)

`fresh_report.py`(fresh_v1) · `fresh2_report.py` · `fresh3_report.py` · `test_report.py`(11-05 시험) · `compare_report.py`(상용 AI 첫 비교) ·
`audit_outputs.py` · `failures.py` · `headroom.py` · `quote_misses.py` · `calibrate.py`·`probe_view.py`(0.5 라우터) · `pick_judge.py`·`build_pick_dev.py`(0.8 판정자 고르기) ·
`run_pick.py`·`build_koneo_eval.py`(KoNeoBench, 평가 전용: 데이터는 이 저장소에 없음)

지금 쓰는 도구 일부가 이 파일들의 함수를 가져다 쓰므로 함께 둔다.
