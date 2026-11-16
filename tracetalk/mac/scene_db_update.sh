#!/usr/bin/env bash
# Demo 7 as a scene on this Mac: a word only we use (중도런), before and after one DB row. Before, no DB row: the card
# should mark its guess as an estimate (or find nothing). Then tracetalk/db/update.py add-entry, timed. After: the same sentence
# reads the DB row. The team coined the word, so the row goes in as reviewed (11-08: unreviewed, the 4B judge gave it 0.55
# and the card said 뜻 확인 필요). The row goes to a scratch live DB in _mac_runtime/tmp, so data/db/live stays as it is.
# Needs mac/serve.sh running. Output stays inside _mac_runtime/logs.
set -euo pipefail
cd "$(dirname "$0")/.."
STAMP="$(date +%m%d_%H%M)"; LIVE="_mac_runtime/tmp/scene_live_$STAMP"; OUT="_mac_runtime/logs/scene_$STAMP"
[ -e "$OUT" ] && { echo "== $OUT 이(가) 이미 있습니다(같은 분에 두 번). 1분 뒤 다시 하세요."; exit 1; }
mkdir -p "$OUT"
grep '"demo-07"' data/demo/demo_inputs.jsonl > "$OUT/input.jsonl"
EASY=(); for f in data/db/lexicon/easy_draft_v4.jsonl data/db/lexicon/easy_draft_v2.jsonl data/db/lexicon/easy_draft_v1.jsonl; do [ -s "$f" ] && { EASY=(--easy-draft "$f"); break; }; done
card() {  # card OUTPUT LEXICON...
    local out="$1"; shift
    bash mac/run.sh python eval/run_bench.py --model tracetalk-student-v1 --base-url http://127.0.0.1:11435 \
        --inputs "$OUT/input.jsonl" --methods card --lexicon "$@" --usages data/db/usage/usages_demo_v1.jsonl \
        --retriever auto --workers 1 --parallel-items 1 --no-slang-probe ${EASY[@]+"${EASY[@]}"} --output "$out"
}
echo "== 1. DB에 없을 때 $(date '+%F %T')"
card "$OUT/before.jsonl" data/db/lexicon/lexicon_demo_v1.jsonl
echo "== 2. DB에 한 줄 넣기"
T0=$(date +%s)
bash mac/run.sh python -m tracetalk.db.update --live "$LIVE" add-entry --expression 중도런 \
    --meaning "시험 기간에 중앙도서관 자리를 잡으려고 아침 일찍 뛰어가는 것" --easy "도서관 자리 잡기" --pos 명사 \
    --origin "중앙도서관(중도) + run(런)" --source "TraceTalk 팀이 시연용으로 지은 말 (2026-11-05)" --reviewed  # 팀이 지은 말: 팀이 확인한 뜻
echo "   넣는 데 $(( $(date +%s) - T0 ))초 (재학습 없음)"
echo "== 3. 한 줄 넣은 뒤 $(date '+%F %T')"
card "$OUT/after.jsonl" data/db/lexicon/lexicon_demo_v1.jsonl "$LIVE/entries.jsonl"
echo "== 전/후 카드"
for f in before after; do  # one file per call: card_report merges runs by case_id
    echo "-- $f"; bash mac/run.sh python eval/card_report.py --runs "$OUT/$f.jsonl" --examples 1 | sed -n "/예)/,\$p"
done
echo "== 끝: $OUT"
