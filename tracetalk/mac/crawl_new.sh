#!/usr/bin/env bash
# 새 글 받기 (0.9, docs/DESIGN.md; v18 검수 후보와 확인 기록): 허용된 사이트의 목록 페이지에서 아직 안 받은 글을 찾아, 받고, 감사하고, 근거 글로
# 넣는다. 받는 단계는 크롤러 샌드박스(HTTPS만, 이 폴더의 _crawl/에만 씀), 넣는 단계는 앱 샌드박스(이 컴퓨터 안만). 모델과 화면은 그대로 두고
# 돌려도 된다(화면은 다음 카드부터 새 글을 읽는다). 새 글에서 뽑은 새 말은 검수 대기열(/review)에 '검수 전'으로만 올린다(DB에 바로 넣지 않음).
# 확인한 시각과 새 글 수는 data/db/live/update_state.json(화면의 DB 상태 줄). 자동으로 돌리기: bash mac/start.sh --auto-update
#   bash mac/crawl_new.sh [목록 페이지당 글 수, 기본 10]
set -euo pipefail
cd "$(dirname "$0")/.."
EACH="${1:-10}"
D="_crawl/new_$(date +%m%d_%H%M)"
STATE=data/db/live/update_state.json
[ -e "$D" ] && { echo "$D 이(가) 이미 있습니다. 1분 뒤 다시 하세요."; exit 3; }
C() { TT_PROFILE=crawl bash mac/run.sh python -E -s -m tracetalk.crawl.pages "$@"; }
state() { printf '{"checked": "%s", "ok": %s, "new_posts": %s, "review": %s}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" "$2" "$3" > "$STATE"; }
trap 'state false 0 0' ERR
mkdir -p "$D"
C discover --known data/db/live/corpus.jsonl --out "$D/new.txt" --each "$EACH"
[ -s "$D/new.txt" ] || { echo "== 새 글 없음"; state true 0 0; exit 0; }
C fetch --urls "$D/new.txt" --out "$D/pages"
C audit --pages "$D/pages"
ADDED=$(bash mac/run.sh python -m tracetalk.db.update corpus-add "$D/pages")
echo "$ADDED"
N=$(printf '%s\n' "$ADDED" | sed -n 's/.*"added": \([0-9][0-9]*\).*/\1/p' | tail -1)
N="${N:-0}"
R=0
if C extract --pages "$D/pages" --out "$D/out" && C check-out --dir "$D/out"; then  # new words wait for a person, never straight into the DB
    R=$(( $(grep -c . "$D/out/sheet.csv" 2>/dev/null || echo 1) - 1 ))
    if [ "$R" -gt 0 ]; then bash mac/run.sh python -m tracetalk.db.update review-add "$D/out/sheet.csv" --pages "$D/pages"; fi
else
    echo "== 새 말 뽑기는 건너뜀(오류나 감사 실패). 근거 글은 들어갔습니다."
fi
state true "$N" "$R"
echo "== 끝 $(date '+%F %T'): 새 글 ${N}개를 근거 글에 넣음(다음 카드부터 읽음), 검수 후보 ${R}개(/review)."
