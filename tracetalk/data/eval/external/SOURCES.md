# 외부 자료 출처 · 내려받은 날 2026-10-26

이 폴더의 파일은 공개 자료 원본과 그 변환본이다. 수정하지 않는다. 평가·학습용 파생 파일은 `eval/build_eval.py`가 `data/eval/eval_v1/`에 만든다.

| 파일 | 출처 | 라이선스 | 비고 |
|---|---|---|---|
| koculture/KoCulture-Descriptions.parquet / .jsonl | https://huggingface.co/datasets/huggingface-KREW/KoCulture-Descriptions | CC BY-NC-SA 4.0 | 503행. title·content(뜻·유래)·date·category·source. 나무위키·트렌드어워드 원자료를 LLM이 초안 작성, KREW 참여자가 검수. 비상업·동일조건·출처 표시 의무 |
| koculture/KoCulture-Dialogues.parquet / .jsonl | https://huggingface.co/datasets/huggingface-KREW/KoCulture-Dialogues | CC BY-NC-SA 4.0 | 10,356행. title·question·answer. 대화 자체가 LLM 초안 + 사람 검수이므로 실제 SNS 관측 용례가 아니다 |
| koneobench/*.csv | https://github.com/bcmilab/ko-neobench (commit d251cd9ab3ba2ca90cba434979deead637af4161, 2026-10-08) | 저장소에 데이터 라이선스 명시 없음 | 2020–2024 국립국어원 신어 조사 기반 1,785개. 뉴스 신어 위주. 논문: Lee et al., "KoNeoBench: A Curated Evaluation Dataset for LLM Understanding of Korean Neologisms", arXiv:2609.19916 (2026-09-17), Findings of EMNLP 2026 (논문의 CC BY 4.0은 논문 라이선스이고 데이터 라이선스는 아님). **평가에만 사용, 재배포·학습 금지** |

jsonl은 parquet와 같은 내용을 Hugging Face datasets-server rows API로 받은 것이다(이 맥에 pyarrow가 없어서). parquet SHA-256:

- KoCulture-Descriptions: 97571fcec70d97ef23bc3e42cc2fc2aabe8c91d43aa24837c3aa9dc1dc1b9f5b
- KoCulture-Dialogues: f5ab0fb93f67bfd6e8899ec9632eaaa7ac6dc32764c7caa56c74a688cdce98f6

KoCulture의 뜻풀이는 이 프로젝트 팀이 검수한 정답이 아니다. eval_v1의 gold에는 `review_status`로 그 사실을 남긴다.
