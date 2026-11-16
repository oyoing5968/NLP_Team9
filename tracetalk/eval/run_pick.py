#!/usr/bin/env python3
"""K2 모호성 판단 (KoNeoBench, evaluation only): the DB returned these candidate meanings for a word - which one
fits the sentence, or none? Scored automatically against the known answer, no judge model.

Methods, all on the same candidates: single (1 call), vote (5 independent calls, majority, a split abstains),
mad (5 calls: two proposers with the candidates in different orders, two reviewers, a judge).
  correct    with_answer: the right candidate; none: abstained (choice N or uncertain); a failed run is wrong
  near       picked one of the two look-alike headwords' meanings (the retrieval mistake that matters)
Prints counts only; KoNeoBench text is never printed.

    python3 eval/run_pick.py --model tracetalk-student-v1 --base-url http://127.0.0.1:11500 \\
        --items data/eval_koneo/k2_items.jsonl --methods single vote mad --output runs/v9/k2.jsonl
"""
import argparse
import json
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracetalk import PROTOCOL, VERSION  # noqa: E402
from tracetalk.mad.card import CardAnalyzer  # noqa: E402
from tracetalk.model import add_model_arguments, config_from  # noqa: E402
from tracetalk.model import make_client  # noqa: E402

METHODS = ("single", "vote", "mad")


def score(item, out):
    """A failed or timed-out run is wrong, not an abstention (11-03 review: it was counted right on "none")."""
    done, choice = out["status"] == "completed", out["choice"]
    abstained = done and choice in (None, "N")
    correct = done and (choice == item["answer"] if item["answer"] != "N" else abstained)
    return {"correct": correct, "abstained": abstained, "near": done and choice in item.get("near_ids", [])}


def summary(rows):
    table = defaultdict(Counter)
    for r in rows:
        c = table[(r["model"], r["method"], r["variant"])]
        c["n"] += 1
        c["completed"] += r["status"] == "completed"
        for k in ("correct", "abstained", "near"):
            c[k] += r[k]
    for key, c in sorted(table.items()):
        print(f"    {key[0]:<22} {key[1]:<7} {key[2]:<12} n={c['n']:<4} 완료 {c['completed']:<4} 정답 {c['correct']:<4}"
              f"({c['correct'] / max(1, c['n']):.3f}) 유보 {c['abstained']:<4} 비슷한표제어 {c['near']}")


def main(argv=None):
    p = add_model_arguments(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    p.set_defaults(model=None, context_size=8192)
    p.add_argument("--items", required=True)
    p.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--judge", choices=["v9", "v10"], default="v9", help="0.8: MAD judge role (tracetalk/mad/card.py)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help="first N items of each variant")
    p.add_argument("--max-seconds", type=int, default=600)
    p.add_argument("--output", required=True)
    p.add_argument("--summary-only", nargs="*", help="print the table of existing outputs and stop")
    args = p.parse_args(argv)
    if args.summary_only is not None:
        summary([json.loads(s) for name in args.summary_only for s in Path(name).read_text(encoding="utf-8").splitlines()
                 if s.strip()])
        return 0
    if not args.model:
        p.error("--model을 명시하세요.")
    items = [json.loads(s) for s in Path(args.items).read_text(encoding="utf-8").splitlines() if s.strip()]
    if args.limit:
        kept, seen = [], Counter()
        for item in items:
            if seen[item["variant"]] < args.limit:
                kept.append(item)
                seen[item["variant"]] += 1
        items = kept
    output = Path(args.output)
    if output.exists():
        p.error("출력 파일이 이미 존재합니다. 새 경로를 지정하세요.")
    client = make_client(config_from(args))
    if not client.health().get("ready"):
        p.error("모델이 준비되지 않았습니다.")
    jobs = [(item, method) for item in items for method in args.methods]
    print(json.dumps({"items": len(items), "methods": args.methods, "jobs": len(jobs), "model": args.model,
                      "variants": dict(Counter(i["variant"] for i in items))}, ensure_ascii=False), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock, done, rows = threading.Lock(), Counter(), []

    def run(item, method):
        out = CardAnalyzer(client, config={"judge": args.judge}).pick(item["text"], item["expression"], item["meanings"],
                                                                      method, args.seed, args.max_seconds)
        row = {"id": item["id"], "method": method, "variant": item["variant"], "year": item["year"],
               "answer": item["answer"], "seed": args.seed, "judge": args.judge, "choice": out["choice"], "status": out["status"], "error": out["error"],
               "model": args.model, "version": VERSION, "protocol": PROTOCOL, **score(item, out),
               "final": out["final"], "detail": out["detail"], "calls": out["calls"], "metrics": out["metrics"],
               "elapsed_seconds": out["elapsed_seconds"]}
        with lock:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            rows.append(row)
            done["n"] += 1
            print(json.dumps({"id": item["id"], "method": method, "status": out["status"], "correct": row["correct"],
                              "progress": f"{done['n']}/{len(jobs)}"}, ensure_ascii=False), flush=True)

    with output.open("x", encoding="utf-8") as handle, ThreadPoolExecutor(args.workers) as pool:
        for future in as_completed([pool.submit(run, *job) for job in jobs]):
            future.result()
    print("== K2 모호성 판단 (모델, 방식, 변형)")
    summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
