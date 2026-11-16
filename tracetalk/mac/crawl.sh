#!/usr/bin/env bash
# The crawler on this Mac (docs/CRAWLER.md): fetch the listed posts, audit every file, extract new words and
# audit what is kept - every step inside the crawl sandbox (mac/sandbox/crawl.sb: reads this folder, writes only
# _crawl/, connects out over HTTPS only and never to this computer's own services). Raw pages stay in _crawl/ (deleted
# with the folder); nothing goes into the DB here (a person checks each word on the review bench, /review).
#   bash mac/crawl.sh [주소 목록]   → _crawl/<시각>/pages (원문), _crawl/<시각>/out (표·글 블록·기록)
#   (주소 목록 기본값 data/crawl/urls.txt)
set -euo pipefail
cd "$(dirname "$0")/.."
URLS="${1:-data/crawl/urls.txt}"
D="_crawl/$(date +%m%d_%H%M)"
[ -e "$D" ] && { echo "$D 이(가) 이미 있습니다. 1분 뒤 다시 하세요."; exit 3; }
echo "== 크롤러(맥) $(date '+%F %T') · 글 $(grep -vc '^#' "$URLS")개 ($URLS) · 허용: $(grep -v '^#' data/crawl/sources.txt | tr '\n' ' ')"
C() { TT_PROFILE=crawl bash mac/run.sh python -E -s -m tracetalk.crawl.pages "$@"; }
C fetch --urls "$URLS" --out "$D/pages"
C audit --pages "$D/pages"
C extract --pages "$D/pages" --out "$D/out"
C check-out --dir "$D/out" || { echo "== 감사 실패: 표를 쓰지 마세요."; exit 6; }
echo "== 끝 $(date '+%F %T'): $D/out/sheet.csv (검수 전 후보 표)"
echo "   검수대로 보내기: bash mac/run.sh python -m tracetalk.db.update review-add $D/out/sheet.csv --pages $D/pages"
echo "   그다음 시연 화면의 /review 에서 원문과 대조해 승인합니다."
