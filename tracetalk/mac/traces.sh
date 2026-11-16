#!/usr/bin/env bash
# 끝낼 때 흔적 점검: 이 폴더 밖에 남았을 수 있는 것을 "있음/없음"과 크기로만 보여 준다. 지우지 않는다(지울지는 사람이 정한다).
# 이 폴더의 모든 설치물은 _mac_runtime/ 안에 있으므로 폴더를 지우면 함께 사라진다. 샌드박스 밖에서 직접 실행한다.
set -uo pipefail
check() {  # check NAME PATH
    if [ -e "$2" ]; then echo "  있음  $1: $2 ($(du -sh "$2" 2>/dev/null | cut -f1))"; else echo "  없음  $1"; fi
}
echo "== 이 폴더: $(cd "$(dirname "$0")/.." && pwd) ($(du -sh "$(dirname "$0")/.." 2>/dev/null | cut -f1), _mac_runtime 포함)"
check "Ollama 기본 폴더(이 저장소는 쓰지 않음)" "$HOME/.ollama"
check "Hugging Face 기본 캐시(이 저장소는 쓰지 않음)" "$HOME/.cache/huggingface"
check "Chroma 기본 폴더(이 저장소는 쓰지 않음)" "$HOME/.chroma"
M="$(getconf DARWIN_USER_CACHE_DIR 2>/dev/null)com.apple.metal"
if ls "$M" 2>/dev/null | grep -qi ollama; then echo "  있음  GPU 셰이더 캐시(macOS가 관리): $M 아래 ollama 항목"; else echo "  없음  GPU 셰이더 캐시의 ollama 항목"; fi
echo "== 지우는 법: 이 폴더를 통째로 지운다. 위에서 '있음'이 나온 항목은 이 저장소가 만든 것인지 확인한 뒤 직접 지운다."
