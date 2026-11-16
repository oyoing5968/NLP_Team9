#!/usr/bin/env python3
"""Observed-usage files for PROTOCOL v7 (tracetalk/db/usage.py) from KoCulture-Dialogues, split like eval_v1.

Each family keeps up to --per-family answers that contain the expression (build_eval's usage rule),
with the message they answered as context. Lines equal to any eval_v1 input (every split, KoNeoBench
included) are left out, so no case ever sees its own comment as evidence.

- usages_eval_v1.jsonl: validation + test families, registered and unregistered alike (the router decides).
- usages_teacher_v1.jsonl: train families only, for teacher traces; no validation/test usage enters training.
- usages_demo_v1.jsonl: every family, for the Mac demo.

KoCulture-Dialogues lines were drafted by an LLM and reviewed by people (CC BY-NC-SA 4.0): realistic
usages, not observed SNS posts. Every row says so in "note". Some answers explain the word outright,
which makes those cases easier than a real first sighting; the summary counts them.

    python3 eval/build_usages.py --out data/db/usage
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from build_eval import key, read_jsonl, split_of  # noqa: E402

SOURCE = "KoCulture-Dialogues (huggingface-KREW)"
NOTE = "LLM 초안 + 사람 검수 대화, 실제 SNS 관측 용례 아님"
EXPLAINS = ("뜻이", "뜻은", "라는 뜻", "란 뜻", "의미는", "이라는 말", "라는 말")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dialogues", default=str(ROOT / "data/eval/external/koculture/KoCulture-Dialogues.jsonl"))
    p.add_argument("--exclude", nargs="+", default=[str(ROOT / f"data/eval/eval_v1/{s}_inputs.jsonl")
                                                    for s in ("train", "val", "test", "koneo")])
    p.add_argument("--per-family", type=int, default=12)
    p.add_argument("--added-at", default="2026-10-26", help="the day the source was downloaded (SOURCES.md)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    taken = {row["text"].strip() for name in args.exclude for row in read_jsonl(Path(name))}
    found = {}
    for row in read_jsonl(Path(args.dialogues)):
        title, answer = row["title"].strip(), (row.get("answer") or "").strip()
        if answer and len(answer) <= 300 and answer not in taken and (title in answer or key(title) in key(answer)):
            group = found.setdefault(key(title), {"title": title, "lines": {}})
            group["lines"].setdefault(answer, " ".join((row.get("question") or "").split())[:200])
    rows = {"eval": [], "teacher": [], "demo": []}
    for k in sorted(found):
        group = found[k]
        texts = sorted(group["lines"], key=lambda s: hashlib.sha256(("usage:" + s).encode("utf-8")).hexdigest())
        row = {"id": "u-kc-" + hashlib.sha256(k.encode("utf-8")).hexdigest()[:10], "expression": group["title"],
               "variants": [], "lines": [{"text": t, "context": group["lines"][t]} for t in texts[:args.per_family]],
               "source": SOURCE, "license": "CC BY-NC-SA 4.0", "note": NOTE, "added_at": args.added_at}
        rows["demo"].append(row)
        rows["teacher" if split_of(group["title"]) == "train" else "eval"].append(row)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, items in rows.items():
        path = out / f"usages_{name}_v1.jsonl"
        with path.open("x", encoding="utf-8") as handle:  # never overwrite an earlier build
            for row in items:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        lines = [u["text"] for r in items for u in r["lines"]]
        summary[name] = {"families": len(items), "lines": len(lines),
                         "lines_that_explain": sum(any(m in t for m in EXPLAINS) for t in lines)}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
