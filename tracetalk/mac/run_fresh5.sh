#!/usr/bin/env bash
# TraceTalk 0.10 / v13 on this Mac (docs/DESIGN.md, bars written before the run): fresh_v5, the newest words of the trusted newsletters,
# measured once, one request at a time, inside the sandbox. Needs mac/serve.sh running and the power cable.
#   full     v13 card with the fetched posts (data/db/live/corpus.jsonl)   (about 10 minutes)
#   single   one decision seeing the same DB and posts at once (MAD's share, reported only)
#   bash mac/run_fresh5.sh [full|single]     (default: both)
# A finished step leaves runs/<protocol>/fresh_v5/<step>.done and is skipped; an output without .done stops the script.
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL=tracetalk-student-v1; BASE=http://127.0.0.1:11435; FRESH=data/eval/fresh_v5
DRAFT=data/db/lexicon/easy_draft_v2.jsonl; LEX=data/db/lexicon/lexicon_demo_v1.jsonl; USE=data/db/usage/usages_demo_v1.jsonl
TAG="$(python3 -c 'from tracetalk import PROTOCOL; print(PROTOCOL.rsplit("-", 1)[1])')"
OUT="runs/$TAG/fresh_v5"
mkdir -p "$OUT"
(cd "$FRESH" && shasum -a 256 -c --quiet SHA256SUMS) || { echo "$FRESH 파일 지문이 만들 때와 다릅니다."; exit 2; }
POSTS=data/db/live/corpus.jsonl
step() {  # step NAME METHOD FLAGS...
    local name="$1" method="$2"; shift 2
    if [ -e "$OUT/$name.done" ]; then echo "== $name: 이미 끝남, 건너뜀"; return; fi
    if [ -e "$OUT/$name.jsonl" ]; then echo "== $name: 결과 파일은 있는데 완료 표시가 없습니다. 덮어쓰지 않고 멈춥니다."; exit 3; fi
    echo "== $name 시작 $(date '+%F %T')"
    bash mac/run.sh python eval/run_bench.py --model "$MODEL" --base-url "$BASE" --workers 1 --parallel-items 1 \
        --max-seconds 600 --inputs "$FRESH/inputs.jsonl" --methods "$method" --seeds 42 --easy-draft "$DRAFT" --retriever auto "$@" \
        --lexicon "$LEX" data/eval/fresh_v4/db/entries.jsonl --usages "$USE" data/eval/fresh_v4/db/usages.jsonl --output "$OUT/$name.jsonl"
    touch "$OUT/$name.done"
    echo "== $name 끝 $(date '+%F %T')"
}
WHAT="${1:-all}"
if [ "$WHAT" = all ] || [ "$WHAT" = full ]; then step full card --decide witness --unknown read --corpus "$POSTS"; fi
if [ "$WHAT" = all ] || [ "$WHAT" = single ]; then step single card_single --corpus "$POSTS"; fi
