#!/usr/bin/env python3
"""Turn graded teacher runs on TRAIN inputs into chat SFT data for the student.

Kept:
- every valid generation call (propose / review / final) of a run whose final answer the
  judge graded "correct" — the student learns the same prompts it will see at runtime;
  MAD judge calls are written twice, because selection is the step MAD depends on;
- every sense-probe call, labelled yes/no from GOLD (candidate family == gold family),
  not from the teacher's own probability.
Refused: any record outside the train split. Families are split again into sft_train /
sft_val so loss is watched on families the student never trains on.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--graded", nargs="+", required=True)
    p.add_argument("--gold", required=True, help="data/eval/eval_v1/train_gold.jsonl")
    p.add_argument("--lexicon", required=True, help="the lexicon the teacher runs used")
    p.add_argument("--out", required=True)
    p.add_argument("--val-share", type=int, default=8, help="percent of families held out for loss")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    gold = {g["case_id"]: g for g in read_jsonl(args.gold)}
    family_of = {e["id"]: e["family"] for e in read_jsonl(args.lexicon)}
    verdict = {}
    for row in (r for name in args.graded for r in read_jsonl(name)):
        verdict[(row["case_id"], row["seed"], row["method"], row["model"])] = row["verdict"]
    examples, stats = [], {"runs": 0, "runs_correct": 0, "generation": 0, "judge_extra": 0,
                           "probe_yes": 0, "probe_no": 0, "skipped_missing_grade": 0}
    for record in (r for name in args.runs for r in read_jsonl(name)):
        if record["split"] != "train" or record["case_id"] not in gold:
            raise SystemExit(f"train split 밖의 기록은 학습에 쓰지 않습니다: {record['case_id']}")
        result = record["result"]
        model = result["model_config"]["model"]
        stats["runs"] += 1
        key = (record["case_id"], record["seed"], record["method"], model)
        if key not in verdict:
            stats["skipped_missing_grade"] += 1
            continue
        meta = {"case_id": record["case_id"], "family": record["family"], "teacher": model,
                "method": record["method"], "route": (result.get("routing") or {}).get("route")}
        for call in result.get("calls", []):
            if call["stage"] == "probe" and call["role"] == "sense":
                payload = json.loads(call["messages"][-1]["content"])
                candidates = (result.get("routing") or {}).get("candidates", [])
                match = [c for c in candidates if c["expression"] == payload.get("expression")]
                if not match or match[0]["id"] not in family_of:
                    continue
                answer = "yes" if family_of[match[0]["id"]] == gold[record["case_id"]]["family"] else "no"
                stats["probe_" + answer] += 1
                examples.append({"messages": call["messages"] + [{"role": "assistant", "content": answer}],
                                 "meta": {**meta, "stage": "probe", "label_from": "gold"}})
        if verdict[key] != "correct":
            continue
        stats["runs_correct"] += 1
        for call in result.get("calls", []):
            if call["stage"] == "probe" or not call["valid"]:
                continue
            example = {"messages": call["messages"] + [{"role": "assistant", "content": call["raw"]}],
                       "meta": {**meta, "stage": call["stage"], "label_from": "teacher_graded_correct"}}
            examples.append(example)
            stats["generation"] += 1
            # Usage probes (v7) are not exported: only "this is the case's own word" is known from gold, and
            # a probe trained on positives alone would learn to say yes.
            if call["stage"] == "final" and meta["route"] in ("mad", "usage_mad"):
                examples.append(example)
                stats["judge_extra"] += 1
    held = lambda family: int(hashlib.sha256(("sft:" + family).encode()).hexdigest(), 16) % 100 < args.val_share
    splits = {"sft_train": [e for e in examples if not held(e["meta"]["family"])],
              "sft_val": [e for e in examples if held(e["meta"]["family"])]}
    for name, rows in splits.items():
        with (out / f"{name}.jsonl").open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats.update({name: len(rows) for name, rows in splits.items()})
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    main()
