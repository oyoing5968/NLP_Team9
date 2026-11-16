#!/usr/bin/env python3
"""Commercial-AI comparison (data/eval/compare_v1/README.md): three answer sets on the same 98 sentences, judged with the
source hidden. `sheet` writes the blinded sheet (and keeps the label key apart); `report` joins the judgements back.

    python3 eval/compare_report.py sheet          → data/eval/compare_v1/judge_sheet.txt, _blind_key.json
    python3 eval/compare_report.py report         (reads data/eval/compare_v1/judgements.json)
"""
import json, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "eval"))
from fresh_report import target  # noqa: E402
D = ROOT / "data/eval/compare_v1"
# the card runs this report read are not in the public repository (they hold passages of the newsletters)
RUNS = {"fresh_v2": ROOT / "_work/fresh2_runs_1106/runs/v10/fresh_v2/after_new.jsonl",
        "fresh_v3": ROOT / "_work/fresh3_runs_1107/runs/v11/fresh_v3/after_080.jsonl"}


def parse(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(\d+)\s*\|(.*)$", line)
        if m:
            parts = [p.strip() for p in m.group(2).split("|")]
            out[int(m.group(1))] = {"expr": parts[0], "meaning": parts[1] if len(parts) > 1 else "",
                                   "conf": parts[2] if len(parts) > 2 else ""}
    return out


def tracetalk(key):
    gold = {}
    for v in RUNS:
        gold.update({g["case_id"]: g for g in map(json.loads, open(ROOT / f"data/eval/{v}/gold.jsonl", encoding="utf-8"))})
    recs = {}
    for v, path in RUNS.items():
        for s in open(path, encoding="utf-8"):
            r = json.loads(s)
            if r["method"] == "card" and r["seed"] == 42:
                recs[r["case_id"]] = r
    out = {}
    for k in key:
        r = recs[k["case_id"]]
        it = target(r, gold[k["case_id"]]) if r["status"] == "completed" else None
        if it is None or it.get("choice") == "L":
            items = (r["result"].get("card") or {}).get("items") or []
            out[k["no"]] = {"expr": "없음" if not items else ", ".join(i["expression"] for i in items),
                            "meaning": "표준어" if it is not None else "-", "conf": "-"}
            continue
        conf = "모름" if it["status"] != "proposed" else "추정" if it.get("estimate") else "확실"
        db = f"[DB 뜻: {it['db_meaning']}] " if it.get("db_meaning") else ""
        out[k["no"]] = {"expr": it["expression"], "meaning": db + (it.get("meaning") or ""), "conf": conf}
    return out


def sheet():
    key = [json.loads(s) for s in open(D / "key.jsonl", encoding="utf-8")]
    sources = {"alone": parse(D / "answers_1_alone.txt"), "with_db": parse(D / "answers_2_with_db.txt"),
               "tracetalk": tracetalk(key)}
    rng = random.Random(20261107)
    blind, lines = {}, []
    for k in key:
        if k["type"] in "BP":
            continue
        labels = ["가", "나", "다"]
        names = list(sources)
        rng.shuffle(names)
        lines.append(f"\n#{k['no']} {k['type']} [{k['expression']}] 정답: {k['gold'][:80]}\n   문장: {k['text']}")
        for lab, name in zip(labels, names):
            a = sources[name].get(k["no"], {"expr": "(답 없음)", "meaning": "", "conf": ""})
            blind[f"{k['no']}{lab}"] = name
            lines.append(f"   {lab}) {a['expr']} | {a['meaning'][:150]} | {a['conf']}")
    (D / "judge_sheet.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (D / "_blind_key.json").write_text(json.dumps(blind, ensure_ascii=False), encoding="utf-8")
    (D / "answers_3_tracetalk.json").write_text(json.dumps(sources["tracetalk"], ensure_ascii=False, indent=0), encoding="utf-8")
    print("판정표:", sum(1 for l in lines if l.startswith("\n#")), "문장")


def rule_bp(k, a):
    """B: standard / none / a literal reading (a title) is right. P: none or standard is right. Picking a DB sense is
    wrong for both (#85 says '표준어 뜻이 아닌' inside a DB-sense answer, so '표준어' must be the whole answer)."""
    e, m = a["expr"], a["meaning"]
    if m.startswith("[DB 뜻"):
        return False
    if k["type"] == "P":
        return e in ("없음", "-") or m in ("-", "표준어")
    return e == "없음" or m in ("-", "표준어") or bool(re.match(r"곡명|코르티스의 노래 제목|드라마 제목", m))


def report():
    key = [json.loads(s) for s in open(D / "key.jsonl", encoding="utf-8")]
    sources = {"alone": parse(D / "answers_1_alone.txt"), "with_db": parse(D / "answers_2_with_db.txt"),
               "tracetalk": json.loads((D / "answers_3_tracetalk.json").read_text(encoding="utf-8"))}
    sources["tracetalk"] = {int(k): v for k, v in sources["tracetalk"].items()}
    blind = json.loads((D / "_blind_key.json").read_text(encoding="utf-8"))
    judged = json.loads((D / "judgements.json").read_text(encoding="utf-8"))
    mixed = set(judged.get("_mixed", ()))
    res = defaultdict(Counter)
    for k in key:
        for name in sources:
            a = sources[name].get(k["no"], {"expr": "", "meaning": "", "conf": ""})
            if k["type"] in "BP":
                ok = soft = rule_bp(k, a)
            else:
                lab = next(l for l in "가나다" if blind[f"{k['no']}{l}"] == name)
                ok = judged[f"{k['no']}{lab}"] == "o"
                soft = ok or f"{k['no']}{lab}" in mixed
            res[name][k["type"] + "_n"] += 1
            res[name][k["type"]] += ok
            res[name]["soft"] += soft
            if k["type"] == "C" and k["expression"] != "테무인간":  # set flaw: its wrong sense ~ the real one
                res[name]["C7_n"] += 1
                res[name]["C7"] += ok
            sure = a["conf"] == "확실"
            res[name]["sure_wrong"] += (not ok) and sure and k["type"] in "ACDUS"
            res[name][k["type"] + "_sure_wrong"] += (not ok) and sure
            res[name][k["type"] + "_unsure"] += (not ok) and a["conf"] in ("추정", "모름")
    print("== 상용 AI 비교 (98문장; B·P는 규칙, 나머지는 출처를 가린 Claude 판정)")
    names = {"alone": "Gemini 3.8 혼자", "with_db": "Gemini 3.8 + 우리 DB", "tracetalk": "TraceTalk (seed 42)"}
    for name, c in res.items():
        cells = " · ".join(f"{t} {c[t]}/{c[t + '_n']}" for t in "ABCDPUS" if c[t + "_n"])
        print(f"   {names[name]:<20} {cells} · 합 {sum(c[t] for t in 'ABCDPUS')}/98 (반반을 맞음으로 {c['soft']})"
              f" · 확실한데 틀림 {c['sure_wrong']} (A {c['A_sure_wrong']}, C {c['C_sure_wrong']}, D {c['D_sure_wrong']},"
              f" U {c['U_sure_wrong']}, S {c['S_sure_wrong']}) · 추정·모름 틀림 U {c['U_unsure']} S {c['S_unsure']}"
              f" · C(테무인간 뺌) {c['C7']}/{c['C7_n']}")
    print("   B·P 규칙 판정에 쓴 답 (B·P는 눈으로 한 번 더 본다):")
    for k in key:
        if k["type"] in "BP":
            row = " / ".join(f"{sources[n].get(k['no'], {}).get('expr', '')}:{sources[n].get(k['no'], {}).get('meaning', '')[:14]}"
                             f"={'o' if rule_bp(k, sources[n].get(k['no'], {'expr': '', 'meaning': ''})) else 'x'}"
                             for n in sources)
            print(f"   #{k['no']} {k['type']} [{k['expression']}] {row}")


if __name__ == "__main__":
    {"sheet": sheet, "report": report}[sys.argv[1]]()
