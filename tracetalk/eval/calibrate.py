#!/usr/bin/env python3
"""Choose router thresholds from routed runs on VALIDATION (never test).

Sense probe: a candidate is a true match when its lexicon family equals the gold family.
tau_sense = the smallest threshold whose precision >= --target-precision (most recall at that
precision); if none reaches it, the F1-best threshold, flagged.
Slang probe: tau_plain is chosen so that no more than --max-false-plain of slang inputs
would be sent to the plain route.
"""
import argparse
import json
from pathlib import Path


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--gold", required=True)
    p.add_argument("--lexicon", required=True)
    p.add_argument("--target-precision", type=float, default=0.9)
    p.add_argument("--max-false-plain", type=float, default=0.05)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    gold = {g["case_id"]: g for g in read_jsonl(args.gold)}
    family_of = {e["id"]: e["family"] for e in read_jsonl(args.lexicon)}
    sense, slang = [], []
    for record in (r for name in args.runs for r in read_jsonl(name)):
        if record["method"] != "routed" or record["split"] == "test":
            continue
        routing = record["result"].get("routing") or {}
        g = gold[record["case_id"]]
        if routing.get("p_has_slang") is not None:
            slang.append((routing["p_has_slang"], g["stratum"] != "plain"))
        for c in routing.get("candidates", []):
            if c.get("p_yes") is not None and c["id"] in family_of:
                sense.append((c["p_yes"], family_of[c["id"]] == g["family"]))
    grid = [round(0.05 * i, 2) for i in range(1, 20)]
    table = []
    for tau in grid:
        tp = sum(p >= tau and y for p, y in sense)
        fp = sum(p >= tau and not y for p, y in sense)
        fn = sum(p < tau and y for p, y in sense)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
        table.append({"tau": tau, "precision": prec, "recall": rec, "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn})
    ok = [row for row in table if row["precision"] is not None and row["precision"] >= args.target_precision]
    chosen = min(ok, key=lambda r: r["tau"]) if ok else max(table, key=lambda r: r["f1"])
    plain_rows = []
    for tau in grid:
        slang_items = [p for p, y in slang if y]
        plain_items = [p for p, y in slang if not y]
        plain_rows.append({"tau": tau,
                           "false_plain_rate": sum(p < tau for p in slang_items) / len(slang_items) if slang_items else None,
                           "plain_recall": sum(p < tau for p in plain_items) / len(plain_items) if plain_items else None})
    ok_plain = [r for r in plain_rows if r["false_plain_rate"] is not None and r["false_plain_rate"] <= args.max_false_plain]
    tau_plain = max(ok_plain, key=lambda r: r["tau"]) if ok_plain else plain_rows[0]
    report = {"sense_pairs": len(sense), "sense_positive": sum(y for _, y in sense), "slang_items": len(slang),
              "tau_sense": chosen["tau"], "tau_sense_meets_target": bool(ok), "tau_plain": tau_plain["tau"],
              "sense_table": table, "plain_table": plain_rows,
              "note": "validation 표본이 작다(사례 수십 개). 임계값은 잠정이며 test로 다시 고르지 않는다."}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("sense_pairs", "sense_positive", "slang_items", "tau_sense",
                                              "tau_sense_meets_target", "tau_plain")}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()
