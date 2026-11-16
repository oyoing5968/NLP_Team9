#!/usr/bin/env bash
# Try to get out of the TraceTalk sandbox (mac/sandbox/*.sb) and show that each try is refused. Touches only this
# folder: every "outside" target is the folder's own parent (research) or the system temp folder, and the network
# tries go to a documentation-only address (192.0.2.1, never routed) and to unused local ports.
#   bash mac/sandbox_check.sh          → "== 샌드박스: 시도 N개 모두 기대대로" at the end
set -euo pipefail
cd "$(dirname "$0")/.."
PARENT="$(dirname "$(pwd -P)")"
probe() {  # probe PROFILE EXPECT NAME PYTHON
    local profile="$1" expect="$2" name="$3" code="$4" got
    got="$(TT_PROFILE="$profile" bash mac/run.sh python -I -c "$code" 2>/dev/null | tail -1 || true)"
    [ "$got" = "$expect" ] && echo "   통과 [$profile] $name: $got" || { echo "   실패 [$profile] $name: 기대 $expect, 실제 ${got:-출력 없음}"; FAILED=1; }
    COUNT=$((COUNT + 1))
}
TRY='
def t(f):
    try:
        f(); print("됨")
    except PermissionError:
        print("막힘")
    except OSError as e:
        print("막힘" if e.errno == 1 else "됨(" + type(e).__name__ + ")")
'
COUNT=0; FAILED=0
for p in app crawl; do
    probe $p 됨 "이 폴더 읽기" "$TRY
t(lambda: open('docs/DESIGN.md', encoding='utf-8').read())"
    probe $p 막힘 "상위 폴더 목록" "$TRY
import os; t(lambda: os.listdir('$PARENT'))"
    probe $p 막힘 "상위 폴더에 쓰기" "$TRY
t(lambda: open('$PARENT/tt_sandbox_check.txt', 'w').write('x'))"
    probe $p 막힘 "시스템 임시 폴더에 쓰기" "$TRY
t(lambda: open('/private/tmp/tt_sandbox_check.txt', 'w').write('x'))"
done
probe app 됨 "이 폴더에 쓰기" "$TRY
import os; t(lambda: (open('_mac_runtime/tmp/tt_check.txt', 'w').write('x'), os.remove('_mac_runtime/tmp/tt_check.txt')))"
probe crawl 막힘 "DB 폴더에 쓰기" "$TRY
t(lambda: open('data/tt_check.txt', 'w').write('x'))"
probe crawl 됨 "받은 원문 폴더에 쓰기" "$TRY
import os; t(lambda: (open('_crawl/tt_check.txt', 'w').write('x'), os.remove('_crawl/tt_check.txt')))"
probe app 막힘 "바깥 인터넷" "$TRY
import socket; t(lambda: socket.create_connection(('192.0.2.1', 443), 2))"
probe app "됨(ConnectionRefusedError)" "이 컴퓨터 안(빈 포트)" "$TRY
import socket; t(lambda: socket.create_connection(('127.0.0.1', 9), 2))"
probe crawl 막힘 "이 컴퓨터 안(화면·Ollama)" "$TRY
import socket; t(lambda: socket.create_connection(('127.0.0.1', 11435), 2))"
probe ollama 막힘 "Ollama 쪽 바깥 인터넷" "$TRY
import socket; t(lambda: socket.create_connection(('192.0.2.1', 443), 2))"
probe crawl 막힘 "https 아닌 바깥(80번)" "$TRY
import socket; t(lambda: socket.create_connection(('192.0.2.1', 80), 2))"
# 11-09: the name lookup itself (the Mac's resolver would send the name out): only the crawler may ask
for p in app ollama; do
    probe $p 막힘 "바깥 주소 묻기(DNS)" "$TRY
import socket; t(lambda: socket.socket(socket.AF_UNIX).connect('/private/var/run/mDNSResponder'))"
done
probe crawl 됨 "크롤러의 주소 묻기(허용 목록 사이트용)" "$TRY
import socket; t(lambda: socket.socket(socket.AF_UNIX).connect('/private/var/run/mDNSResponder'))"
ls "$PARENT/tt_sandbox_check.txt" /private/tmp/tt_sandbox_check.txt >/dev/null 2>&1 && { echo "   실패: 바깥에 시험 파일이 생겼습니다"; FAILED=1; }
[ "$FAILED" = 0 ] && echo "== 샌드박스: 시도 ${COUNT}개 모두 기대대로" || { echo "== 샌드박스: 기대와 다른 것이 있습니다(위 '실패')"; exit 1; }
