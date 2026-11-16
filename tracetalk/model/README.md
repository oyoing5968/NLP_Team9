# 학습 모델: tracetalk-student-v1

| 항목 | 내용 |
|---|---|
| 기반 모델 | Qwen3.5-4B, 대화용 후처리 모델 (https://huggingface.co/Qwen/Qwen3.5-4B, Apache 2.0). 학습 명령에 기반 지정이 없어 `train_lora.py`의 기본값이 쓰였다. GGUF 머리말의 `general.base_model`이 Qwen3.5-4B-Base인 것은 Qwen3.5-4B 설명서가 자기 상위 모델을 그렇게 적었기 때문 |
| 학습 | LoRA(rank 16, alpha 32) 지도 학습 후 합침, GPU 한 장에서 한 번 (`eval/train_lora.py`) |
| 학습 자료 | KoCulture(CC BY-NC-SA 4.0) 학습 분할의 문장에 대해 더 큰 교사 모델이 쓴 답 가운데 채점을 통과한 것 (`eval/export_sft.py`) |
| 형식 | GGUF, Q4_K_M, 2,708,804,544 바이트 |
| 실행 | Ollama (`Modelfile`: 기반 모델의 채팅 형식 그대로) |
| sha256 | `c91c239d51159757e8f538cc887c78dab73b46d740efd272b2accd529f97df87` |

**라이선스:** 기반 모델은 Apache 2.0이지만, 학습 자료가 KoCulture(CC BY-NC-SA 4.0)라 이 모델도 **비상업, 출처 표시, 같은 조건 공유**로 다룬다.

## 받는 법

파일이 커서(2.7GB) git에 넣지 않았다(GitHub은 파일 하나 100MB, 릴리스 첨부는 2GB까지). 두 조각으로 나눠, 과제 공유용 zip에는 맨 위 `release/`에
넣었고 git 저장소에서는 GitHub 릴리스에 올린다(아래 '올리는 법'). zip으로 받았으면 `bash mac/install.sh`가 `release/`의 조각으로 아래 과정을 한 번에 한다.

| 릴리스 첨부 | 크기 | sha256 |
|---|---|---|
| `tracetalk-student-v1.gguf.part-aa` | 1,468,006,400 바이트 | `2c3903e27d6892b7726e58e748a1bae6e4f3b3c0f2aff80b147d6bf8ced88a16` |
| `tracetalk-student-v1.gguf.part-ab` | 1,240,798,144 바이트 | `9ffb2957ba822d554807ce2af1b3ee7f6160e4c27f5f61aa5e9f145574772cc5` |

```
# git으로 받은 경우: 두 조각을 한 폴더에 내려받은 뒤
bash mac/get_model.sh ~/Downloads     # 조각 지문 확인 → 합치기 → 전체 지문 확인 → _mac_runtime/pkg/tracetalk-student-v1/
bash mac/serve.sh                      # 터미널 1
bash mac/import_student.sh             # 터미널 2: MANIFEST 지문 확인 후 Ollama에 등록
```

macOS가 아니면: 두 조각을 `cat tracetalk-student-v1.gguf.part-aa tracetalk-student-v1.gguf.part-ab > tracetalk-student-v1.gguf`로 합치고
`sha256sum`으로 위 값과 대조한 뒤, `Modelfile`이 있는 폴더에서 `ollama create tracetalk-student-v1 -f Modelfile`.

## 올리는 법 (저장소 관리자)

조각은 프로젝트 맨 위의 `release/`에 있다(.gitignore라 git에는 올라가지 않음). GitHub 저장소의 Releases → Draft a new release → 두 파일을 첨부 → Publish.
`model/SHA256SUMS`에 조각과 전체 지문이 있다.
