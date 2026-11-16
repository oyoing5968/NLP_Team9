#!/usr/bin/env python3
"""Pick items on the validation split (the development set): which judge role MAD uses in 0.8 (docs/DESIGN.md).

Every validation word with a reference meaning (registered and unregistered), its comment, the reference meaning as
the answer, and K2-style candidates from the evaluation DB (eval/build_fresh.py pick_items): with_answer and none.
Once; overwrites nothing.

    python3 eval/build_pick_dev.py      -> data/eval/dev_pick/pick_items.jsonl, SHA256SUMS
"""
import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from build_fresh import jl, pick_items  # noqa: E402
from tracetalk.mad.card import strip_han  # noqa: E402
from tracetalk.db.lexicon import compact, load_lexicon  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", default=str(ROOT / "data/eval/eval_v1/val_gold.jsonl"))
    p.add_argument("--inputs", default=str(ROOT / "data/eval/eval_v1/val_inputs.jsonl"))
    p.add_argument("--lexicon", default=str(ROOT / "data/db/lexicon/lexicon_eval_v1.jsonl"))
    p.add_argument("--out", default=str(ROOT / "data/eval/dev_pick"))
    p.add_argument("--seed", type=int, default=20261105)
    args = p.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        p.error(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    texts = {i["id"]: i["text"] for i in jl(args.inputs)}
    lexicon = load_lexicon(args.lexicon, missing_ok=False)
    own = {}
    for e in lexicon:
        own.setdefault(compact(e["expression"]), []).append(strip_han(e["meaning"]))
    words = [{"id": g["case_id"], "text": texts[g["case_id"]], "head": g["expression"],
              "answer": strip_han(g["reference_meaning"]),
              "own": own.get(compact(g["expression"]), []) + [strip_han(g["reference_meaning"])], "year": g["stratum"]}
             for g in jl(args.gold) if g["stratum"] in ("registered", "unregistered")]
    others = [{"head": e["expression"], "meaning": strip_han(e["meaning"])} for e in lexicon]
    items = pick_items(words, others, random.Random(args.seed), "dev")
    out.mkdir(parents=True)
    path = out / "pick_items.jsonl"
    path.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    (out / "SHA256SUMS").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  pick_items.jsonl\n",
                                    encoding="utf-8")
    print(json.dumps({"words": len(words), "items": dict(Counter(i["variant"] for i in items)),
                      "strata": dict(Counter(w["year"] for w in words))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
