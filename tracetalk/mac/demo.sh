#!/usr/bin/env bash
# The demo screen on this Mac: http://localhost:8765, result card with the DB retriever (morph, typos, related usages).
# Needs mac/serve.sh running with tracetalk-student-v1 and bge-m3. Ctrl-C stops it.
# v9.5: the teacher's easy-word drafts (eval/draft_easy.py), when that file is here, are marked on the card.
cd "$(dirname "$0")/.."
EASY=(); for f in data/db/lexicon/easy_draft_v4.jsonl data/db/lexicon/easy_draft_v2.jsonl data/db/lexicon/easy_draft_v1.jsonl; do [ -s "$f" ] && { EASY=(--easy-draft "$f"); break; }; done
exec bash mac/run.sh python -m tracetalk.web.run --model tracetalk-student-v1 \
    --base-url http://127.0.0.1:11435 --retriever auto --parallel-items 1 ${EASY[@]+"${EASY[@]}"} "$@"
