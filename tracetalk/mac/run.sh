#!/usr/bin/env bash
# Run one command for TraceTalk on this Mac with everything inside tracetalk/_mac_runtime: HOME, caches, config,
# temp files, pip, Hugging Face, Ollama models and keys, Chroma data. Deleting the folder leaves nothing behind.
# 0.8.1: inside the macOS sandbox (mac/sandbox/*.sb): the command can read and write only this folder and its
# runtime, and reach only this computer (the crawler: HTTPS out). TT_SANDBOX=off runs without it (not for normal use).
#   bash mac/run.sh ollama -v
#   bash mac/run.sh python -m tracetalk.web.run --model tracetalk-student-v1 --base-url http://127.0.0.1:11435
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
RT="$ROOT/_mac_runtime"
USER_HOME="$HOME"
mkdir -p "$RT"/{home,cache,tmp,hf,models,chroma,logs}
export HOME="$RT/home" XDG_CACHE_HOME="$RT/cache" XDG_CONFIG_HOME="$RT/home/.config" XDG_DATA_HOME="$RT/home/.local/share" \
    TMPDIR="$RT/tmp" PIP_CACHE_DIR="$RT/pip_cache" PYTHONPYCACHEPREFIX="$RT/cache/pycache" \
    HF_HOME="$RT/hf" HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
    ANONYMIZED_TELEMETRY=False CHROMA_DATA="$RT/chroma" \
    OLLAMA_MODELS="$RT/models" OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}" OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}" \
    OLLAMA_KEEP_ALIVE=10m OLLAMA_NOPRUNE=1 OLLAMA_NO_CLOUD=1  # 11-09: Ollama's own cloud features off too (the sandbox already stops the tries)
export PATH="$RT/venv/bin:$RT/ollama:$PATH"
cd "$ROOT"
if [ "${TT_SANDBOX:-on}" = "off" ]; then
    echo "주의: 샌드박스 없이 실행합니다(TT_SANDBOX=off)." >&2
    exec "$@"
fi
command -v sandbox-exec >/dev/null || { echo "sandbox-exec가 없는 macOS입니다. mac/README.md의 '샌드박스'를 보세요." >&2; exit 2; }
RUNTIME="$(cd "$RT" && pwd -P)"  # before the move, the link's target in the old folder
PROFILE="${TT_PROFILE:-$([ "$1" = ollama ] && echo ollama || echo app)}"
mkdir -p "$ROOT/_crawl"  # the crawler's only writable folder: inside this folder itself, never through a link
# v16: every folder above the project and its runtime, for path lookups only (names, never contents), so the folder runs
# wherever it is unpacked (~/Downloads/tracetalk or deeper). Sixteen at most; the rest of the slots repeat ROOT.
UP=()
for d in "$ROOT" "$RUNTIME"; do
    while [ "$d" != / ]; do
        d="$(dirname "$d")"; seen=0
        for u in ${UP[@]+"${UP[@]}"}; do [ "$u" = "$d" ] && seen=1; done
        [ "$seen" = 1 ] || UP+=("$d")
    done
done
[ "${#UP[@]}" -le 16 ] || echo "주의: 폴더가 너무 깊습니다(위 폴더 ${#UP[@]}개). 더 얕은 곳에 두세요." >&2
UPS=(); for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do UPS+=(-D "UP$i=${UP[$i]:-$ROOT}"); done
exec sandbox-exec -f "$ROOT/mac/sandbox/$PROFILE.sb" -D ROOT="$ROOT" -D RUNTIME="$RUNTIME" \
    -D CRAWL="$ROOT/_crawl" -D HOME_DIR="$USER_HOME" -D PARENT="$(dirname "$ROOT")" \
    -D RUNTIME_PARENT="$(dirname "$RUNTIME")" -D NET="${TT_NET:-0}" "${UPS[@]}" "$@"
