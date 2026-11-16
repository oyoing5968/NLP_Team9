#!/usr/bin/env bash
# 자동 업데이트 (v18): bash mac/start.sh --auto-update [시간] 이 켜고 start.sh가 끝나면 같이 끝난다(시스템 예약 기능을 쓰지 않아 폴더 밖에
# 흔적이 없다). 켤 때 한 번, 그다음 N시간마다(기본 6), 그리고 화면이 모르는 말을 만난 뒤(data/db/live/update_wanted 표시, 30분에 한 번까지)
# 허용된 뉴스레터의 새 글을 받는다(mac/crawl_new.sh). 질문한 말은 어디로도 보내지 않는다: 크롤러는 목록 페이지의 새 글만 받는다.
#   bash mac/auto_update.sh [시간]          (기록은 start.sh가 runs/auto_update.log에 남김)
set -uo pipefail
cd "$(dirname "$0")/.."
HOURS="${1:-6}"
EVERY="${TT_UPDATE_EVERY:-$((HOURS * 3600))}"  # seconds between scheduled looks
GAP="${TT_UPDATE_GAP:-1800}"                     # at least this long between looks that a new word asked for
TICK="${TT_UPDATE_TICK:-60}"
FLAG="${TT_UPDATE_FLAG:-data/db/live/update_wanted}"
CMD="${TT_UPDATE_CMD:-bash mac/crawl_new.sh}"
trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM INT
last=-1
while true; do
    now=$(date +%s)
    if [ "$last" -lt 0 ] || [ $((now - last)) -ge "$EVERY" ] || { [ -e "$FLAG" ] && [ $((now - last)) -ge "$GAP" ]; }; then
        why="예약"; [ -e "$FLAG" ] && why="모르는 말"; [ "$last" -lt 0 ] && why="켤 때"
        rm -f "$FLAG"
        echo "== 새 글 확인 $(date '+%F %T') ($why)"
        bash -c "$CMD" || echo "== 실패(다음 차례에 다시 함): $?"
        last=$(date +%s)
    fi
    sleep "$TICK" & wait $!
done
