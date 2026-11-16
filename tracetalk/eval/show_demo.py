#!/usr/bin/env python3
"""Print the demo in -> out for people to read: input, route, detected expression, meaning, and the
comment rewritten with easy words (the replaced part is marked with ‘ ’). No grading: whether a
meaning is right is for a person to judge.

    python3 eval/show_demo.py runs/r2/student_demo.jsonl runs/r4/student_v1_demo.jsonl
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

ROUTES = {"plain": "평문 판정", "lexicon": "사전 근거 풀이", "disambiguate": "사전 후보 판별", "mad": "MAD 토론",
          "usage_mad": "용례 MAD"}


def marked(rewrite):
    """The rewritten comment with each replaced part wrapped in ‘ ’."""
    text, out, cursor = rewrite["text"], [], 0
    for span in rewrite["spans"]:
        out += [text[cursor:span["new_start"]], "‘", text[span["new_start"]:span["new_end"]], "’"]
        cursor = span["new_end"]
    return "".join(out + [text[cursor:]])


def describe(record):
    result = record["result"]
    route = (result.get("routing") or {}).get("route")
    head = f"{result['model_config']['model']} · {record['method']}" + (f" · {ROUTES.get(route, route)}" if route else "")
    if result["status"] != "completed":
        return [head, f"  실패: {result['status']} · {(result.get('error') or '')[:150]}"]
    a, rewrite = result["analysis"], result.get("rewrite") or {}
    lines = [head + " · " + ("의미 해석 제안" if a["status"] == "proposed" else "해석 유보"),
             "  탐지 표현: " + (" · ".join(a["expressions"]) or "없음(평문)"),
             "  문맥상 의미: " + a["interpretation"],
             "  쉬운 말로: " + (marked(rewrite) if rewrite.get("text") else "바꾼 문장 없음"),
             "  쉬운 표현: " + (" / ".join(f"{s['expression']} → {s['easy']}" for s in rewrite.get("spans", [])) or "-")]
    used = {u["id"]: u for u in (result.get("routing") or {}).get("usage_lines", [])}
    for i in a.get("supporting_usages", []):
        if i in used:
            lines.append(f"  근거 용례 {i}: {used[i]['text'][:80]} ({used[i]['source']}, {used[i]['added_at']})")
    if rewrite.get("skipped"):
        lines.append("  건너뛴 치환: " + " / ".join(f"{s['expression']}({s['reason']})" for s in rewrite["skipped"]))
    if a["status"] == "uncertain" or a["alternatives"]:
        lines.append("  불확실성: " + a["uncertainty"] + (" · 대안: " + " / ".join(a["alternatives"]) if a["alternatives"] else ""))
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    args = p.parse_args(argv)
    cases = defaultdict(list)
    for index, name in enumerate(args.runs):
        for line in Path(name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cases[record["case_id"]].append((index, record["method"], record["seed"], record))
    for case_id in sorted(cases):
        # Runs finish in parallel; order by file (before / after training), then method.
        records = [r for *_, r in sorted(cases[case_id], key=lambda item: item[:3])]
        print(f"■ {case_id} 입력: {records[0]['result']['request']['text']}")
        for record in records:
            print("\n".join("  " + line for line in describe(record)))
    return 0


if __name__ == "__main__":
    main()
