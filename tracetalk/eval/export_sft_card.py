#!/usr/bin/env python3
"""v9.5 (11-04): teacher result cards on TRAIN inputs -> chat SFT data for student v2 (the card's own roles).

Student v1 learned the 0.6 prompts (export_sft.py); the v9 card roles - detection, deciding among DB candidates,
easy words, the plain-language sentence - it never saw, and its own easy words sank the v9.4 sentences. This
exports the teacher's card calls the student will meet at runtime, from cards the judge passed whole:
the target's meaning "correct" AND the sentence "yes", card completed. From such a card:
- every valid detect / single / propose / review / judge call (a MAD judge twice: selection is what MAD rests on),
- the easy-words rewrite only when its words are the ones the card kept,
- the sentence call only when its sentence is the card's sentence written by the model (not a rejected attempt).
No probes: in a card only the target's own sense has a gold label, and positives alone teach "yes".
Refused: any record outside the train split. Families split again into sft_train / sft_val for the loss.

    python3 eval/export_sft_card.py --runs runs/v9.5/teacher_train/train.jsonl \\
        --graded runs/v9.5/teacher_train/graded_train.jsonl --gold data/eval/eval_v1/train_gold.jsonl --out data/sft_v2
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

STAGES = ("detect", "single", "propose", "review", "judge")


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def card_examples(result):
    """(examples, counts) for one accepted card: the calls whose outputs the card kept."""
    card = result["card"]
    kept_easy = {it.get("easy", "") for it in card["items"] if it.get("status") != "failed"}
    out, counts = [], Counter()
    for call in result.get("calls", []):
        if call.get("stage") == "probe" or not call.get("valid"):
            continue
        stage, analysis = call["stage"], call.get("analysis") or {}
        if stage == "easy" and analysis.get("easy") not in kept_easy:
            continue
        if stage == "sentence" and not (card.get("sentence_by") == "model" and analysis.get("sentence") == card["sentence"]):
            continue
        if stage not in STAGES + ("easy", "sentence"):
            continue
        example = {"messages": call["messages"] + [{"role": "assistant", "content": call["raw"]}], "stage": stage}
        out.append(example)
        counts[stage] += 1
        if stage == "judge":
            out.append(example)
            counts["judge_extra"] += 1
    return out, counts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--graded", nargs="+", required=True)
    p.add_argument("--gold", required=True, help="data/eval/eval_v1/train_gold.jsonl")
    p.add_argument("--out", required=True)
    p.add_argument("--val-share", type=int, default=8, help="percent of families held out for loss")
    args = p.parse_args(argv)
    out = Path(args.out)
    gold = {g["case_id"]: g for g in read_jsonl(args.gold)}
    if any(g.get("stratum") != "train" for g in gold.values()):
        raise SystemExit("--gold는 train 정답 파일이어야 합니다.")
    graded = {(r["case_id"], r["seed"], r["method"], r["model"]): r for name in args.graded for r in read_jsonl(name)}
    examples, stats = [], Counter()
    for record in (r for name in args.runs for r in read_jsonl(name)):
        if record.get("split") != "train" or record["case_id"] not in gold:
            raise SystemExit(f"train split 밖의 기록은 학습에 쓰지 않습니다: {record['case_id']}")
        result = record["result"]
        stats["cards"] += 1
        g = graded.get((record["case_id"], record["seed"], record["method"], result["model_config"]["model"]))
        if g is None:
            stats["skipped_missing_grade"] += 1
            continue
        if not (record["method"] == "card" and result.get("status") == "completed" and result.get("card")
                and g["verdict"] == "correct" and g.get("sentence") == "yes"):
            continue
        stats["cards_accepted"] += 1
        rows, counts = card_examples(result)
        stats.update(counts)
        meta = {"case_id": record["case_id"], "family": record["family"], "teacher": result["model_config"]["model"],
                "protocol": result.get("protocol"), "label_from": "teacher_card_graded_correct"}
        examples.extend({"messages": r["messages"], "meta": {**meta, "stage": r["stage"]}} for r in rows)
    held = lambda family: int(hashlib.sha256(("sft:" + family).encode()).hexdigest(), 16) % 100 < args.val_share
    splits = {"sft_train": [e for e in examples if not held(e["meta"]["family"])],
              "sft_val": [e for e in examples if held(e["meta"]["family"])]}
    out.mkdir(parents=True, exist_ok=False)
    for name, rows in splits.items():
        with (out / f"{name}.jsonl").open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats.update({name: len(rows) for name, rows in splits.items()})
    (out / "stats.json").write_text(json.dumps(dict(stats), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(dict(stats), ensure_ascii=False))
    return dict(stats)


if __name__ == "__main__":
    main()
