# 자료 출처와 라이선스

| 무엇 | 출처 | 라이선스 | 이 저장소에서 |
|---|---|---|---|
| KoCulture-Descriptions, KoCulture-Dialogues | huggingface-KREW (Hugging Face) | CC BY-NC-SA 4.0 | 원본 `data/eval/external/koculture/`, 파생: 처음 DB(`data/db/lexicon`, `data/db/usage`), 평가 세트(`data/eval/eval_v1`), 학습 자료. **비상업, 출처 표시, 같은 조건 공유** |
| 학습 모델 tracetalk-student-v1 | Qwen3.5-4B(Apache 2.0, 대화용 후처리 모델) + KoCulture로 학습 | 학습 자료를 따라 비상업으로 다룸 | 두 조각 `release/` (git에는 크기 때문에 없고 과제 공유용 zip에 있음, `model/README.md`) |
| 신조어 뉴스레터 글 (트렌드어워드, 파밍레터, 고구마팜, 위픽레터) | 각 뉴스레터 | 각 뉴스레터의 저작물 | 근거 글의 글자 `data/db/live/corpus.jsonl`을 과제 안에서 시연·시험에만 쓴다. 출처 주소 `data/crawl/corpus_urls.txt`, 다시 받기 `mac/fetch_corpus.sh` |
| KoNeoBench | bcmilab/ko-neobench | 데이터 라이선스 명시 없음 | 평가에만 썼고 이 저장소에 없다(재배포·학습 금지). 결과 숫자만 |
| Gemini 답 | 사용자가 Gemini에 질문해 받은 답 | — | 비교 기록(`data/eval/compare_v*`, `data/eval/fresh_v5/answers_*.txt`) |
| bge-m3, Ollama | BAAI, Ollama | 각 배포 조건 | 저장소에 없고 `mac/setup.sh`가 받는다 |

EXAONE 3.5 7.8B(EXAONE AI Model License 1.1-NC, 연구·평가 전용)는 비교 실험에만 썼다. 이 저장소에는 모델도, 받는 스크립트도 없다.

시험 문장 일부와 정답표의 정리, 출처를 가린 채점은 AI(Claude)가 했고 팀 검수 전이다(`docs/RESULTS.md` 채점 방법).

코드의 라이선스는 팀이 정한다(정하기 전까지 저작권은 팀에 있다).
