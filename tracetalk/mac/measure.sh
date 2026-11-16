#!/usr/bin/env bash
# The 8 demo sentences as cards on this Mac, one request at a time, with the retriever: how long a card takes here.
# Output stays inside _mac_runtime/logs. Needs mac/serve.sh running.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="_mac_runtime/logs/mac_demo_$(date +%m%d_%H%M).jsonl"
EASY=(); for f in data/db/lexicon/easy_draft_v4.jsonl data/db/lexicon/easy_draft_v2.jsonl data/db/lexicon/easy_draft_v1.jsonl; do [ -s "$f" ] && { EASY=(--easy-draft "$f"); break; }; done  # v9.5
bash mac/run.sh python eval/run_bench.py --model tracetalk-student-v1 --base-url http://127.0.0.1:11435 \
    --inputs data/demo/demo_inputs.jsonl --methods card --lexicon data/db/lexicon/lexicon_demo_v1.jsonl \
    --usages data/db/usage/usages_demo_v1.jsonl --retriever auto --workers 1 --parallel-items 1 --no-slang-probe \
    ${EASY[@]+"${EASY[@]}"} --output "$OUT"
bash mac/run.sh python eval/card_report.py --runs "$OUT" --examples 8
python3 - "$OUT" <<'PY'
import json, statistics, sys
rows = [json.loads(s) for s in open(sys.argv[1], encoding="utf-8") if s.strip()]
t = [r["result"]["elapsed_seconds"] for r in rows]
dec, pre = [], []
for i, r in enumerate(rows, 1):  # in run order: a card late in the run slowing down = heat
    calls = r["result"]["calls"]
    for k in calls:
        n = k.get("ollama_timings_ns") or {}
        if k.get("stage") != "probe" and n.get("eval_duration") and k.get("completion_tokens"):
            dec.append(k["completion_tokens"] / (n["eval_duration"] / 1e9))
            pre.append((k.get("prompt_tokens") or 0) / max(1e-9, n.get("prompt_eval_duration", 0) / 1e9))
    print(f"   {i}. {r['result']['elapsed_seconds']:6.1f}초 · 호출 {len(calls)} | {r['result']['request']['text'][:22]}")
print(f"== 맥 카드 시간: 평균 {statistics.mean(t):.1f}초 · 가장 김 {max(t):.1f}초 · {len(t)}문장 · "
      f"생성 {statistics.median(dec):.1f}토큰/초 · 입력 처리 {statistics.median(pre):.0f}토큰/초 (중앙값)")
PY
