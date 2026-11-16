#!/usr/bin/env python3
"""Copy an installed Ollama model out as GGUF blob file(s) + a Modelfile for another machine.

The Modelfile keeps the exact TEMPLATE / PARAMETER lines of the installed model, so the
Mac runs the same chat template that was benchmarked on the training GPU. Only the FROM
paths change to the copied files. A SHA-256 manifest is written next to them.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, help="installed Ollama model name, e.g. tracetalk-student-v1")
    p.add_argument("--ollama", default="ollama", help="the ollama binary (on PATH by default)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    text = subprocess.run([args.ollama, "show", "--modelfile", args.name], capture_output=True, text=True,
                          check=True).stdout
    stem = args.name.replace(":", "-").replace("/", "-")
    lines, files = [], {}
    for line in text.splitlines():
        if line.startswith("FROM ") and Path(line[5:].strip()).is_file():
            source = Path(line[5:].strip())
            target = f"{stem}.gguf" if not files else f"{stem}.part{len(files)}.gguf"
            shutil.copy2(source, out / target)
            files[target] = sha256(out / target)
            line = f"FROM ./{target}"
        lines.append(line)
    if not files:
        raise SystemExit("Modelfile에서 복사할 FROM 파일을 찾지 못했습니다:\n" + text[:500])
    (out / "Modelfile").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {"model": args.name, "files": files, "modelfile_sha256": sha256(out / "Modelfile")}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest))
    return manifest


if __name__ == "__main__":
    main()
