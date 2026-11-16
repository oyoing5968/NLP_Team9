#!/usr/bin/env python3
"""Summarize graded runs: accuracy per method, and pool/majority over K samples.

pool@K  = share of cases where at least one of K samples is correct.
maj@K   = share of cases where more than half of K samples are correct
          (a lower bound on plurality voting over free-text answers).
headroom = pool@K - maj@K: what a selector that beats voting could recover.
Failures and judge errors count as not correct. "partial" is reported apart.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def rate(n, d):
    return round(n / d, 4) if d else None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["model"], row["config_sha"], row["method"])].append(row)
    report = []
    for (model, sha, method), group in sorted(groups.items()):
        by_case = defaultdict(list)
        for row in group:
            by_case[row["case_id"]].append(row)
        seeds = sorted({row["seed"] for row in group})
        k = len(seeds)
        strata = defaultdict(lambda: {"cases": 0, "correct_samples": 0, "samples": 0, "pool": 0, "maj": 0,
                                      "partial_samples": 0, "literal_misread": 0, "failed": 0})
        for case_id, samples in by_case.items():
            for name in ("all", samples[0]["stratum"]):
                s = strata[name]
                s["cases"] += 1
                correct = sum(r["verdict"] == "correct" for r in samples)
                s["correct_samples"] += correct
                s["samples"] += len(samples)
                s["partial_samples"] += sum(r["verdict"] == "partial" for r in samples)
                s["literal_misread"] += sum(r.get("literal_misread") == "yes" for r in samples)
                s["failed"] += sum(r["verdict"] in ("failed", "judge_error") for r in samples)
                s["pool"] += correct >= 1
                s["maj"] += correct * 2 > len(samples)
        entry = {"model": model, "config_sha": sha, "method": method, "seeds": k,
                 "temperature": group[0].get("temperature"),
                 "incomplete_cases": sum(len(v) != k for v in by_case.values()),
                 "median_seconds": sorted(r["elapsed_seconds"] for r in group)[len(group) // 2],
                 "completion_tokens_mean": rate(sum(r["completion_tokens"] or 0 for r in group), len(group)),
                 "strata": {}}
        for name, s in strata.items():
            entry["strata"][name] = {
                "cases": s["cases"], "accuracy": rate(s["correct_samples"], s["samples"]),
                "partial_rate": rate(s["partial_samples"], s["samples"]),
                "literal_misread_rate": rate(s["literal_misread"], s["samples"]),
                "failure_rate": rate(s["failed"], s["samples"]),
                **({"pool_at_k": rate(s["pool"], s["cases"]), "maj_at_k": rate(s["maj"], s["cases"]),
                    "headroom": rate(s["pool"] - s["maj"], s["cases"])} if k > 1 else {})}
        report.append(entry)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("graded", nargs="+")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    rows = [r for name in args.graded for r in read_jsonl(name)]
    report = summarize(rows)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump({"note": "자동 채점(LLM 판정) 기반 잠정 수치. 팀 표본 검수 전.", "groups": report},
                  handle, ensure_ascii=False, indent=2)
    for e in report:
        a = e["strata"]["all"]
        extra = f" pool@{e['seeds']}={a['pool_at_k']} maj@{e['seeds']}={a['maj_at_k']} headroom={a['headroom']}" \
            if e["seeds"] > 1 else ""
        # Per-stratum accuracy on the same line: MAD is judged on unregistered / decomposition strata.
        layers = " ".join(f"{name}={s['accuracy']}(n={s['cases']})" for name, s in sorted(e["strata"].items())
                          if name != "all")
        print(f"{e['model']:<28} {e['method']:<12} n={a['cases']:<4} acc={a['accuracy']} "
              f"literal={a['literal_misread_rate']} fail={a['failure_rate']}{extra} "
              f"med_s={e['median_seconds']} | {layers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
