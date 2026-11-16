#!/usr/bin/env python3
"""Pilot check before a long run: why runs failed, and how close generation calls came to their caps.

Reads run_bench outputs only (no gold, no grading). The 5-call methods split the same total
output budget into ~20% per call, so they hit the cap earlier than direct/rag, and one truncated
call fails the whole run. If that happens, the comparison would measure the per-call budget, not
the method: raise --total-output-tokens for ALL methods (overnight.sh: TOTAL=...), never for one.
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

CATEGORIES = (
    ("truncated", ("잘렸습니다",)),
    ("quote_not_in_input", ("인용은 원문",)),
    ("usage_id", ("주어진 용례에 없는 번호",)),
    ("schema", ("필드", "배열 길이", "문자열 형식", "허용되지 않은", "비어 있습니다", "유보 상태", "해석 제안", "중복 키")),
    ("json", ("JSON",)),
)


def category(error):
    for name, keys in CATEGORIES:
        if any(k in error for k in keys):
            return name
    return "other"


def summarize(rows, near=0.9):
    groups = defaultdict(lambda: {"runs": 0, "status": Counter(), "reasons": Counter(), "examples": [],
                                  "calls": defaultdict(list), "routes": Counter(), "probes": 0, "unreadable": 0,
                                  "to_rewrite": 0, "rewritten": 0})
    for r in rows:
        result = r["result"]
        g = groups[(result["model_config"]["model"], result["model_config"]["temperature"], r["method"])]
        g["runs"] += 1
        g["status"][r["status"]] += 1
        if r["status"] != "completed":
            reason = category(result.get("error") or "") if r["status"] == "failed" else r["status"]
            g["reasons"][reason] += 1
            if len(g["examples"]) < 2:
                g["examples"].append((result.get("error") or "")[:120])
        # In -> out: a proposed answer that names an expression should come back as a rewritten comment.
        analysis = result.get("analysis") or {}
        if r["status"] == "completed" and analysis.get("status") == "proposed" and analysis.get("expressions"):
            g["to_rewrite"] += 1
            g["rewritten"] += bool((result.get("rewrite") or {}).get("text"))
        if r["method"] == "routed" and result.get("routing"):
            g["routes"][result["routing"].get("route", "none")] += 1
        for call in result.get("calls", []):
            if call.get("stage") == "probe":
                g["probes"] += 1
                g["unreadable"] += call.get("p_yes") is None
            else:
                g["calls"][call["stage"]].append(call)
    report = []
    for (model, temperature, method), g in sorted(groups.items()):
        stages = {}
        for stage, calls in g["calls"].items():
            tokens = [c["completion_tokens"] for c in calls if isinstance(c.get("completion_tokens"), int)]
            stages[stage] = {
                "calls": len(calls), "invalid": sum(not c["valid"] for c in calls),
                "truncated": sum("잘렸습니다" in (c.get("error") or "") for c in calls),
                "cap": sorted({c["max_tokens"] for c in calls}),
                "completion_median": statistics.median(tokens) if tokens else None,
                "completion_max": max(tokens) if tokens else None,
                "near_cap_share": round(sum(isinstance(c.get("completion_tokens"), int)
                                            and c["completion_tokens"] >= near * c["max_tokens"] for c in calls)
                                        / len(calls), 3)}
        report.append({"model": model, "temperature": temperature, "method": method, "runs": g["runs"],
                       "completed": g["status"]["completed"], "failure_reasons": dict(g["reasons"]),
                       "examples": g["examples"], "stages": stages, "routes": dict(g["routes"]),
                       "probes": g["probes"], "probes_unreadable": g["unreadable"],
                       "rewrite": {"proposed_with_expression": g["to_rewrite"], "rewritten": g["rewritten"]},
                       "truncated_run_share": round(g["reasons"]["truncated"] / g["runs"], 3)})
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+")
    p.add_argument("--near", type=float, default=0.9, help="share of the cap counted as near the cap")
    p.add_argument("--max-truncated", type=float, default=0.1, help="truncated-run share that calls for a larger TOTAL")
    args = p.parse_args(argv)
    rows = [json.loads(s) for name in args.runs for s in Path(name).read_text(encoding="utf-8").splitlines() if s.strip()]
    report = summarize(rows, args.near)
    for e in report:
        w = e["rewrite"]
        print(f"{e['model']:<26} t={e['temperature']:<4} {e['method']:<10} 완료 {e['completed']}/{e['runs']} "
              f"실패이유 {e['failure_reasons'] or '-'} 치환 {w['rewritten']}/{w['proposed_with_expression']}")
        for stage, s in sorted(e["stages"].items()):
            print(f"    {stage:<12} 호출 {s['calls']:<4} 무효 {s['invalid']:<3} 잘림 {s['truncated']:<3} 상한 {s['cap']} "
                  f"출력토큰 중앙값 {s['completion_median']} 최대 {s['completion_max']} 상한근접 {s['near_cap_share']}")
        if e["probes"]:
            print(f"    탐침 {e['probes']}회 중 확률을 못 읽은 것 {e['probes_unreadable']}회, 경로 {e['routes']}")
        for example in e["examples"]:
            print(f"    예: {example}")
    worst = max(report, key=lambda e: e["truncated_run_share"], default=None)
    if worst and worst["truncated_run_share"] > args.max_truncated:
        print(f"판정: 예산 부족. {worst['method']}의 {worst['truncated_run_share']:.0%}가 출력 잘림으로 실패했다. "
              "모든 방식의 출력 예산을 함께 올린다(예: TOTAL=5120 bash eval/overnight.sh 0).")
    else:
        print("판정: 출력 잘림은 기준 이하다. 기본 예산으로 진행한다. 다른 실패 이유는 위 표를 본다.")
    return report


if __name__ == "__main__":
    main()
