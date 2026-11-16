#!/usr/bin/env python3
"""Where the routed probes sent each case, and with what probability (read-only, run_bench outputs).

For every routed run: its stratum (eval_v1 gold), status and route, P(slang), and the sense / usage
probes split into the case's own family versus other families. Failed runs keep their calls, so their
probes are shown too. The summary is what threshold tuning needs: own-family probabilities should sit
above tau, other-family ones below. Usage MAD runs also report whether each reviewer tested the peer's
hypothesis on usages the peer never saw (held_out_checked).

    python3 eval/probe_view.py runs/pilot_v7/val20_*.jsonl runs/pilot_v7/koneo10_*.jsonl
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from build_eval import key  # noqa: E402


def gold_strata():
    strata = {}
    for name in ("train", "val", "test", "koneo"):
        path = ROOT / f"data/eval/eval_v1/{name}_gold.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            if line.strip():
                g = json.loads(line)
                strata[g["case_id"]] = (g["stratum"], g["family"])
    return strata


def quantiles(values):
    if not values:
        return "-"
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return f"n={len(values)} 최소 {values[0]:.2f} 사분위 {pick(.25):.2f} 중앙 {statistics.median(values):.2f} 최대 {values[-1]:.2f}"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--summary", action="store_true", help="사례별 줄 없이 요약만")
    args = p.parse_args(argv)
    strata = gold_strata()
    probes, routes, held = {}, Counter(), Counter()
    for name in args.runs:
        for line in Path(name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            result = row["result"]
            routing = result.get("routing") or {}
            for check in routing.get("held_out_checked") or []:
                held[(row["method"], check)] += 1
            if row["method"] != "routed":
                continue
            stratum, family = strata.get(row["case_id"], ("?", "?"))
            route = routing.get("route") or "(실패라 기록 없음)"
            routes[(stratum, route, row["status"])] += 1
            parts = []
            for call in result.get("calls", []):
                if call["stage"] != "probe":
                    continue
                asked = json.loads(call["messages"][-1]["content"])
                p_yes = call.get("p_yes")
                if call["role"] == "has_slang":
                    parts.append(f"신조어 {p_yes if p_yes is None else round(p_yes, 2)}")
                    probes.setdefault(("has_slang", stratum), []).append(p_yes)
                    continue
                own = "kc:" + key(asked.get("expression", "")) == family
                probes.setdefault((call["role"], "자기 계열" if own else "다른 계열"), []).append(p_yes)
                parts.append(f"{'사전' if call['role'] == 'sense' else '용례'}{'*' if own else ''} "
                             f"{asked.get('expression')} {p_yes if p_yes is None else round(p_yes, 2)}")
            if not args.summary:
                print(f"{row['case_id']:<16} {stratum:<14} {row['status']:<9} {route:<12} " + " · ".join(parts))
    print("== 탐침 확률 (* = 그 사례 자기 계열; 문턱: 사전 0.6, 평문 판정은 신조어 < 0.25; v8에는 용례 탐침 없음)")
    for (role, group), values in sorted(probes.items()):
        print(f"    {role:<10} {group:<12} {quantiles([v for v in values if v is not None])}")
    print("== routed 경로", dict(sorted(routes.items(), key=str)))
    print("== 비판자가 상대가 못 본 용례를 시험했는가 (방식, 결과): 수", dict(sorted(held.items(), key=str)))


if __name__ == "__main__":
    main()
