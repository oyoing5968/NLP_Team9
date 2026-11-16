#!/usr/bin/env python3
"""0.8 development step: pick MAD's judge role by the rule written down before the run (docs/DESIGN.md):
v10 when its with_answer correct >= v9's + 3 and its none abstentions >= v9's - 3, else v9. Reads the run_pick
outputs of both roles, prints the counts, writes the chosen role (one word) to --out. Overwrites nothing.

    python3 eval/pick_judge.py --runs dev_v9.jsonl dev_v10.jsonl --out judge.txt
"""
import argparse
import json
from collections import Counter
from pathlib import Path

GAIN, LOSS = 3, 3


def counts(rows):
    c = Counter()
    for r in rows:
        if r["method"] != "mad":
            continue
        key = (r["judge"], r["variant"])
        c[key + ("n",)] += 1
        c[key + ("correct",)] += r["correct"]
        c[key + ("abstained",)] += r["abstained"]
    return c


def choose(c):
    gain = c[("v10", "with_answer", "correct")] - c[("v9", "with_answer", "correct")]
    loss = c[("v9", "none", "abstained")] - c[("v10", "none", "abstained")]
    return ("v10" if gain >= GAIN and loss <= LOSS else "v9"), gain, loss


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        p.error(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    c = counts([json.loads(s) for name in args.runs for s in Path(name).read_text(encoding="utf-8").splitlines()
                if s.strip()])
    if not all(c[(j, v, "n")] for j in ("v9", "v10") for v in ("with_answer", "none")):
        p.error("v9와 v10의 with_answer·none 결과가 모두 있어야 합니다.")
    for j in ("v9", "v10"):
        print(f"   {j:<4} with_answer 정답 {c[(j, 'with_answer', 'correct')]}/{c[(j, 'with_answer', 'n')]} · "
              f"none 보류 {c[(j, 'none', 'abstained')]}/{c[(j, 'none', 'n')]}")
    judge, gain, loss = choose(c)
    print(f"== 판정 역할: {judge} (with_answer 정답 {gain:+d}, 기준 +{GAIN} 이상 · none 보류 {-loss:+d}, 기준 -{LOSS} 이상)")
    out.write_text(judge + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
