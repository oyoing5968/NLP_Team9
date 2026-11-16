#!/usr/bin/env python3
"""fresh_v4 against the commercial AI (docs/DESIGN.md, data/eval/compare_v3/README.md): the same 118 sentences, every answer judged by a
person with the source hidden. `sheet` writes the blinded lists and keeps the label key apart; `apply` turns the judgements into
data/eval/fresh_v4/judged.json (what fresh4_report reads for a meaning that is not a DB row) and prints the comparison, bars 13-15 included.

    python3 eval/fresh4_sheet.py sheet --runs full=FULL.jsonl single=ONE.jsonl noposts=NP.jsonl old=OLD.jsonl
        -> data/eval/compare_v3/judge_meaning.txt, judge_origin.txt, _blind_key.json
    python3 eval/fresh4_sheet.py apply --runs ...       (reads data/eval/compare_v3/judged_meaning.json, judged_origin.json: {no: {label: "o"|"x"}})
"""
import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from fresh4_report import rows, target, with_origins  # noqa: E402
from tracetalk.db.lexicon import compact  # noqa: E402

D = ROOT / "data/eval/compare_v3"
GOLD = [ROOT / "data/eval/fresh_v4/gold.jsonl", ROOT / "data/eval/fresh_v4r/gold.jsonl"]
PLAIN = ("없음", "표준어", "-", "")


def commercial(path):
    """{no: {expr, meaning, origin, conf}} from `no | 표현 | 뜻 | 유래 | 확신` lines."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+) \| (.*)$", line)
        if m:
            p = [x.strip() for x in m.group(2).split(" | ")]
            out[int(m.group(1))] = {"expr": p[0], "meaning": p[1], "origin": p[2], "conf": p[3]}
    return out


def card_answer(record, gold):
    """What a card says about the sentence's target, in the same plain form as the commercial answer."""
    if record["status"] != "completed":
        return {"expr": "", "meaning": "", "origin": "", "conf": "끝나지 않음"}
    it = target(record, gold)
    if it is None or it.get("choice") == "L":
        return {"expr": "없음" if it is None else it["expression"], "meaning": "표준어" if it else "", "origin": "", "conf": "-"}
    conf = "보류" if it["status"] != "proposed" else "추정" if it.get("estimate") else "확실"
    return {"expr": it["expression"], "meaning": it.get("meaning") or "", "origin": it.get("origin") or "", "conf": conf}


def gemini(number):
    """The commercial answers (data/eval/compare_v3/README.md): `gemini` the second no-web answer, which passed the copying check; `gemini1` the first, which did not; `gemini_web` web search on."""
    return {"gemini": commercial(D / "answers_1_alone_2.txt")[number], "gemini1": commercial(D / "answers_1_alone.txt")[number],
            "gemini_web": commercial(D / "answers_3_web.txt")[number]}


def load(specs):
    out = {}
    for spec in specs:
        name, path = spec.split("=", 1)
        out[name] = {r["case_id"]: r for r in rows(path)}
    return out


def sheets(runs, seed=20261107):
    key = rows(D / "key.jsonl")
    gold = with_origins({g["case_id"]: g for path in GOLD for g in rows(path)})
    rng = random.Random(seed)
    meaning, origin, blind = [], [], {"meaning": {}, "origin": {}}
    for k in key:
        g = gold[k["case_id"]]
        sources = gemini(k["no"])
        for name, recs in runs.items():
            if k["case_id"] in recs:
                sources[name] = card_answer(recs[k["case_id"]], g)
        reference = g.get("reference_meaning") or g.get("sense") or g.get("note") or ""
        if g["type"] == "C":  # the row in `sense` is the wrong one, on purpose; the note says what the word really means
            reference = re.sub(r"^실제:\s*", "", g["note"].split(" · ")[0])
        if g["type"] == "P" or (g["type"] == "B"):
            reference = "신조어가 아니다(표준어·이름·글자 그대로)" + (f" / DB 뜻: {g['sense']}" if g.get("sense") else "")
        groups = {}
        for name, a in sources.items():
            if a["meaning"] not in PLAIN:  # a card's "확인 필요" too: whether the meaning it shows is right is counted apart from whether it settled it
                groups.setdefault(compact(a["meaning"]), {"text": a["meaning"], "sources": []})["sources"].append(name)
        labels = list(groups.values())
        rng.shuffle(labels)
        blind["meaning"][k["no"]] = {chr(97 + i): v["sources"] for i, v in enumerate(labels)}
        if labels:
            meaning.append(f"#{k['no']} [{g['type']}] {k['text']}\n   표현: {g['expression'] or '(없음)'} | 참조: {reference}\n"
                           + "".join(f"   {chr(97 + i)}) {v['text']}\n" for i, v in enumerate(labels)))
        if g.get("origin_keywords"):
            groups = {}
            for name, a in sources.items():
                if a["origin"] not in PLAIN or a["meaning"] not in PLAIN:  # the meaning may name it too, on either side
                    text = f"유래: {a['origin'] or '-'} / 뜻: {a['meaning'] or '-'}"
                    groups.setdefault(compact(text), {"text": text, "sources": []})["sources"].append(name)
            labels = list(groups.values())
            rng.shuffle(labels)
            blind["origin"][k["no"]] = {chr(97 + i): v["sources"] for i, v in enumerate(labels)}
            if labels:
                origin.append(f"#{k['no']} {g['expression']} | 글이 말하는 유래: {g.get('origin') or orig_of(g)}\n"
                              + "".join(f"   {chr(97 + i)}) {v['text']}\n" for i, v in enumerate(labels)))
    (D / "judge_meaning.txt").write_text("\n".join(meaning), encoding="utf-8")
    (D / "judge_origin.txt").write_text("\n".join(origin), encoding="utf-8")
    (D / "_blind_key.json").write_text(json.dumps(blind, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"뜻 {len(meaning)}문장, 유래 {len(origin)}문장 -> {D}")


def orig_of(gold):
    found = {r["word"]: r for r in rows(ROOT / "data/eval/fresh_v4r/origin_gold.jsonl")}.get(gold.get("headword") or "")
    return found["origin"] if found else ""


def mark_of(answer, labels, marks):
    """The judge's mark on this answer's text; None when it gave no meaning to judge."""
    label = next((a for a, names in labels.items() if answer in names), None)
    return marks.get(label) if label else None


def apply(runs):
    key = rows(D / "key.jsonl")
    gold = with_origins({g["case_id"]: g for path in GOLD for g in rows(path)})
    blind = json.loads((D / "_blind_key.json").read_text(encoding="utf-8"))
    marks = json.loads((D / "judged_meaning.json").read_text(encoding="utf-8"))
    origin_marks = json.loads((D / "judged_origin.json").read_text(encoding="utf-8")) if (D / "judged_origin.json").exists() else {}
    hand, table, origin = {}, {}, {}
    for k in key:
        g = gold[k["case_id"]]
        no = str(k["no"])
        sources = gemini(k["no"])
        for name, recs in runs.items():
            if k["case_id"] in recs:
                sources[name] = card_answer(recs[k["case_id"]], g)
        for name, a in sources.items():
            c = table.setdefault(name, Counter())
            labels = blind["meaning"].get(no, {})
            mark = mark_of(name, labels, marks.get(no, {}))
            if not name.startswith("gemini") and mark in ("o", "x"):
                hand.setdefault(k["case_id"], {})[name] = mark
            for tag in (g["type"], "합", *(["recent"] if g.get("recent") else [])):
                c[tag, "shown_right"] += mark == "o"
            no_slang = g["type"] in "BP"
            plain = a["meaning"] in PLAIN or a["expr"] == "없음"
            sure = a["conf"] == "확실"
            if no_slang:
                outcome = "맞음" if plain or mark == "o" else "확정 오답" if sure else "보류"
            elif mark == "o":
                outcome = "맞음"
            elif mark == "x" and sure:
                outcome = "확정 오답"
            else:
                outcome = "보류"
            for tag in (g["type"], "합", *(["recent"] if g.get("recent") else [])):
                c[tag, "n"] += 1
                c[tag, outcome] += 1
            if g.get("origin_keywords"):
                said = " ".join(str(a.get(x, "")) for x in ("origin", "meaning"))
                o = origin.setdefault(name, Counter())
                o["n"] += 1
                o["규칙"] += any(w.lower() in said.lower() for w in g["origin_keywords"])
                label = next((x for x, names in blind["origin"].get(no, {}).items() if name in names), None)
                o["사람"] += origin_marks.get(no, {}).get(label) == "o"
    (ROOT / "data/eval/fresh_v4/judged.json").write_text(json.dumps(hand, ensure_ascii=False, indent=0), encoding="utf-8")
    names = list(table)
    print("유형별 맞음/보류/확정 오답 (사람이 가린 표로 판정)")
    for tag in ("A", "B", "C", "D", "M", "P", "U", "R", "recent", "합"):
        cells = []
        for name in names:
            c = table[name]
            if c[tag, "n"]:
                cells.append(f"{name} {c[tag, '맞음']}/{c[tag, 'n']}·보류 {c[tag, '보류']}·오답 {c[tag, '확정 오답']}·뜻 맞게 보임 {c[tag, 'shown_right']}")
        print(f"  {tag:<7}", "  |  ".join(cells))
    print("유래:", {name: f"규칙 {o['규칙']}/{o['n']} · 사람 판정 {o['사람']}/{o['n']}" for name, o in origin.items()})
    return table, origin


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("what", choices=["sheet", "apply"])
    p.add_argument("--runs", nargs="+", required=True)
    args = p.parse_args(argv)
    runs = load(args.runs)
    return sheets(runs) if args.what == "sheet" else apply(runs)


if __name__ == "__main__":
    main()
