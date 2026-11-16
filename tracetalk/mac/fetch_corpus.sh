#!/usr/bin/env bash
# 근거 글 다시 받기: 이 저장소는 뉴스레터 글 원문을 싣지 않는다(각 뉴스레터의 저작물). 시연과 시험이 읽은 글의 주소 목록만 있고,
# 이 스크립트가 같은 글을 허용 목록(data/crawl/sources.txt) 안에서만 다시 받아, 파일마다 보안 점검을 한 뒤 근거 글 파일로 만든다.
# 받기는 크롤러 샌드박스(https만, _crawl/에만 씀), 넣기는 앱 샌드박스(이 컴퓨터 안만). robots.txt를 지키고 5초에 한 글씩(96글 약 8분).
#   bash mac/fetch_corpus.sh            -> data/db/live/corpus.jsonl   (시연 화면, fresh_v5)
#   bash mac/fetch_corpus.sh fresh_v4   -> data/eval/fresh_v4/corpus.jsonl
# 글이 그 뒤 바뀌었거나 사라졌으면 처음 잰 때와 다른 근거가 된다(받은 날짜가 각 글에 남는다).
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-live}" in
    live) URLS=data/crawl/corpus_urls.txt; LIVE=data/db/live ;;
    fresh_v4) URLS=data/eval/fresh_v4/corpus_urls.txt; LIVE=data/eval/fresh_v4 ;;
    *) echo "쓰는 법: bash mac/fetch_corpus.sh [live|fresh_v4]"; exit 2 ;;
esac
[ -e "$LIVE/corpus.jsonl" ] && { echo "$LIVE/corpus.jsonl 이(가) 이미 있습니다. 덮어쓰지 않습니다(새 글만 더하려면 mac/crawl_new.sh)."; exit 3; }
D="_crawl/corpus_$(date +%m%d_%H%M)"
[ -e "$D" ] && { echo "$D 이(가) 이미 있습니다. 1분 뒤 다시 하세요."; exit 3; }
C() { TT_PROFILE=crawl bash mac/run.sh python -E -s -m tracetalk.crawl.pages "$@"; }
mkdir -p "$D"
echo "== 받기 $(date '+%F %T'): $(grep -vc '^#' "$URLS")글"
C fetch --urls "$URLS" --out "$D/pages"
C audit --pages "$D/pages"
bash mac/run.sh python -m tracetalk.db.update --live "$LIVE" corpus-add "$D/pages"
echo "== 끝 $(date '+%F %T'): $LIVE/corpus.jsonl ($(wc -l < "$LIVE/corpus.jsonl")글). 원문 HTML은 $D 에 남는다(.gitignore)."
