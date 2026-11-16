#!/usr/bin/env python3
"""Example lines for the demo screen's "관련 예시" (slide step 3), one row per lexicon entry.

Lines come from KoCulture-Dialogues answers that contain the expression (CC BY-NC-SA 4.0).
They were drafted by an LLM and reviewed by people, so they are NOT observed SNS usage; the
screen says so. Display only: never sent to the model and never evidence for an answer.
Lines identical to any evaluation or training input are left out, so a demo never shows an
eval comment back as its own "example".

    python3 eval/build_examples.py --out data/db/lexicon/examples_demo_v1.jsonl
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from build_eval import key, read_jsonl  # noqa: E402
from tracetalk.db.lexicon import load_lexicon  # noqa: E402

NOTE = "LLM 초안 + 사람 검수 대화, 실제 SNS 관측 용례 아님"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lexicon", default=str(ROOT / "data/db/lexicon/lexicon_demo_v1.jsonl"))
    p.add_argument("--dialogues", default=str(ROOT / "data/eval/external/koculture/KoCulture-Dialogues.jsonl"))
    p.add_argument("--exclude", nargs="+", default=[str(ROOT / f"data/eval/eval_v1/{s}_inputs.jsonl")
                                                    for s in ("train", "val", "test", "koneo")])
    p.add_argument("--per-entry", type=int, default=3)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    taken = {row["text"].strip() for name in args.exclude for row in read_jsonl(Path(name))}
    lines = {}
    for row in read_jsonl(Path(args.dialogues)):
        title, answer = row["title"].strip(), (row.get("answer") or "").strip()
        # Same usage rule as build_eval: the answer must contain the title.
        if answer and len(answer) <= 300 and answer not in taken and (title in answer or key(title) in key(answer)):
            lines.setdefault(key(title), []).append(answer)
    rows = []
    for entry in load_lexicon(args.lexicon):
        found = list(dict.fromkeys(lines.get(entry["family"].removeprefix("kc:"), [])))
        if not found:
            continue
        found.sort(key=lambda s: hashlib.sha256(("examples:" + s).encode("utf-8")).hexdigest())
        rows.append({"entry_id": entry["id"], "expression": entry["expression"], "lines": found[:args.per_entry],
                     "source": "KoCulture-Dialogues (huggingface-KREW)", "license": "CC BY-NC-SA 4.0", "note": NOTE})
    out = Path(args.out)
    with out.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"entries": len(rows), "lines": sum(len(r["lines"]) for r in rows), "out": str(out)}, ensure_ascii=False))
    return rows


if __name__ == "__main__":
    main()
