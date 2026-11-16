#!/usr/bin/env bash
# v13 시연 대비: data/demo/showcase_v13.jsonl(발표자료 예시 5문장 + 시연 장면 7문장)을 시연 화면(demo.sh)과 같은 DB·근거 글·카드 설정으로
# 한 번 돌려 둔다. 결과는 runs/v13/showcase/에 쌓이고(덮어쓰지 않음), 시연 때 모델이 느리거나 멈추면
# `bash mac/demo.sh --prepared <파일>`로 같은 문장을 그 카드로 보여 준다(화면에 '미리 계산한 결과'와 계산 시각이 나옴).
# Needs mac/serve.sh running.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="runs/v13/showcase/showcase_$(date +%m%d_%H%M).jsonl"
mkdir -p "$(dirname "$OUT")"
[ -e "$OUT" ] && { echo "== $OUT 이미 있음 (1분 뒤 다시)"; exit 1; }
EASY=(); for f in data/db/lexicon/easy_draft_v4.jsonl data/db/lexicon/easy_draft_v2.jsonl data/db/lexicon/easy_draft_v1.jsonl; do [ -s "$f" ] && { EASY=(--easy-draft "$f"); break; }; done
bash mac/run.sh python eval/run_bench.py --model tracetalk-student-v1 --base-url http://127.0.0.1:11435 \
    --inputs data/demo/showcase_v13.jsonl --methods card --seeds 42 --workers 1 --parallel-items 1 --retriever auto \
    --corpus data/db/live/corpus.jsonl --lexicon data/db/lexicon/lexicon_demo_v1.jsonl data/db/live/entries.jsonl \
    --usages data/db/usage/usages_demo_v1.jsonl data/db/live/usages.jsonl ${EASY[@]+"${EASY[@]}"} --output "$OUT"
bash mac/run.sh python eval/card_report.py --runs "$OUT" --examples 12
echo "== 시연 대비 파일: $OUT"
echo "   시연: bash mac/demo.sh --prepared $OUT"
