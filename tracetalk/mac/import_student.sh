#!/usr/bin/env bash
# Register the trained student (_mac_runtime/pkg/tracetalk-student-v1, put there by mac/get_model.sh) with the Mac's Ollama.
# Every GGUF is checked against MANIFEST.json first. mac/serve.sh must be running.
set -euo pipefail
cd "$(dirname "$0")/.."
PKG=_mac_runtime/pkg/tracetalk-student-v1
python3 - "$PKG" <<'PY'
import hashlib, json, sys
from pathlib import Path
pkg = Path(sys.argv[1])
manifest = json.loads((pkg / "MANIFEST.json").read_text())
for name, want in manifest["files"].items():
    h = hashlib.sha256()
    with open(pkg / name, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    print(name, h.hexdigest()[:16], "OK" if h.hexdigest() == want else "다름")
    if h.hexdigest() != want:
        sys.exit("지문이 MANIFEST와 다릅니다. 다시 받으세요.")
PY
bash mac/run.sh ollama create tracetalk-student-v1 -f "$PKG/Modelfile"
bash mac/run.sh ollama list
