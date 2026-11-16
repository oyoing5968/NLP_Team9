#!/usr/bin/env bash
# 켜기 (v16): 모델 서버(serve.sh)를 뒤에서, 화면 서버(demo.sh)를 앞에서 켠다. 브라우저에서 http://localhost:8765. Ctrl-C 한 번에 모두 꺼진다.
#   bash mac/start.sh
#   bash mac/start.sh --prepared runs/v13/showcase/<파일>     (시연 때 모델이 느리면: 미리 계산한 카드로)
#   bash mac/start.sh --auto-update [시간]                     (v18: 허용 뉴스레터의 새 글을 켤 때·N시간마다(기본 6)·모르는 말 뒤에 받음, 기본은 꺼짐)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p runs
ARGS=(); AUTO=""
while [ $# -gt 0 ]; do
    case "$1" in
        --auto-update) AUTO=6; if [[ "${2:-}" =~ ^[0-9]+$ ]]; then AUTO="$2"; shift; fi ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done
PIDS=()
trap 'for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null || true; done' EXIT
if curl -s -o /dev/null http://127.0.0.1:11435/api/version; then
    echo "== 모델 서버가 이미 켜져 있습니다"
else
    bash mac/serve.sh > runs/serve.log 2>&1 &
    PIDS+=($!)
    curl -s --retry 30 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:11435/api/version \
        || { echo "모델 서버가 뜨지 않았습니다: runs/serve.log"; exit 1; }
fi
if [ -n "$AUTO" ]; then
    bash mac/auto_update.sh "$AUTO" >> runs/auto_update.log 2>&1 &
    PIDS+=($!)
    echo "== 자동 업데이트 켬: 켤 때, ${AUTO}시간마다, 모르는 말을 만난 뒤(30분에 한 번까지) 새 글 확인 (기록 runs/auto_update.log)"
fi
echo "== 브라우저에서 http://localhost:8765 를 여세요 (끄기: Ctrl-C)"
bash mac/demo.sh ${ARGS[@]+"${ARGS[@]}"}
