#!/usr/bin/env bash
# Build tracetalk/_mac_runtime from nothing on an Apple-silicon Mac (this one or a teammate's), or check it.
# Everything goes into that one folder (delete the folder and nothing is left). Steps already done are skipped:
#   1. venv with pinned rapidfuzz, kiwipiepy, chromadb (pip cache inside)
#   2. Ollama single binary, checked against the release's sha256
#   3. bge-m3 embedding model (the server runs only for the pull, on 127.0.0.1)
# The trained student comes separately (model/README.md): bash mac/get_model.sh puts it into _mac_runtime/pkg, then run
# mac/import_student.sh with mac/serve.sh on. Needs the internet for the downloads only.
set -euo pipefail
cd "$(dirname "$0")/.."
RT="$PWD/_mac_runtime"
OLLAMA_VERSION=v0.40.4
OLLAMA_SHA256=a4ceae4b2aaf18df37ebcbfb56ba3a37a87838631112d66c2be07268693c8d58
PACKAGES="rapidfuzz==3.13.0 kiwipiepy==0.24.1 chromadb==1.5.9"
mkdir -p "$RT"/{pip_cache,home,cache,tmp,hf,models,chroma,pkg,logs,ollama}
[ "$(uname -s)/$(uname -m)" = "Darwin/arm64" ] || { echo "Apple-silicon Mac 전용입니다."; exit 2; }

echo "== 1. 가상환경"
if [ ! -x "$RT/venv/bin/python" ]; then python3 -m venv "$RT/venv"; fi
if "$RT/venv/bin/python" - <<'PY'
import importlib.metadata as m, sys
want = {"rapidfuzz": "3.13.0", "kiwipiepy": "0.24.1", "chromadb": "1.5.9"}
sys.exit(0 if all(m.version(k) == v for k, v in want.items()) else 1)
PY
then echo "   이미 있음"
else
    HOME="$RT/home" TMPDIR="$RT/tmp" PIP_CACHE_DIR="$RT/pip_cache" "$RT/venv/bin/pip" install -q $PACKAGES
fi
"$RT/venv/bin/python" -c "import rapidfuzz, kiwipiepy, chromadb; print('   ', rapidfuzz.__version__, kiwipiepy.__version__, chromadb.__version__)"

echo "== 2. Ollama $OLLAMA_VERSION"
if [ -x "$RT/ollama/ollama" ]; then echo "   이미 있음"
else
    curl -fsSL -o "$RT/tmp/ollama-darwin.tgz" "https://github.com/ollama/ollama/releases/download/$OLLAMA_VERSION/ollama-darwin.tgz"
    echo "$OLLAMA_SHA256  $RT/tmp/ollama-darwin.tgz" | shasum -a 256 -c -
    tar -xzf "$RT/tmp/ollama-darwin.tgz" -C "$RT/ollama" && rm "$RT/tmp/ollama-darwin.tgz"
fi
bash mac/run.sh ollama -v 2>&1 | tail -1

echo "== 3. 임베딩 모델 bge-m3"
if ls "$RT/models/manifests/registry.ollama.ai/library/bge-m3" >/dev/null 2>&1; then echo "   이미 있음"
else
    TT_NET=1 bash mac/run.sh ollama serve > "$RT/logs/setup_serve.log" 2>&1 &  # the one run allowed out (sandbox)
    SERVER=$!
    trap 'kill $SERVER 2>/dev/null || true' EXIT
    for _ in $(seq 30); do curl -s 127.0.0.1:11435/api/version >/dev/null && break; sleep 1; done
    bash mac/run.sh ollama pull bge-m3
    kill $SERVER; wait $SERVER 2>/dev/null || true
    trap - EXIT
fi
du -sh "$RT"
echo "== 끝. 학습 모델: _mac_runtime/pkg/tracetalk-student-v1 넣고 → mac/serve.sh → mac/import_student.sh"
