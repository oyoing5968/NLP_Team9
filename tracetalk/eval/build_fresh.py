#!/usr/bin/env python3
"""Build the fresh-word check set (fresh_v1, 11-05) from two hand-written files, once, on the Mac:

  data/eval/fresh_v1/fresh_db.csv    the fresh words' DB rows in the team sheet's columns (meanings, easy words, usages,
                                sources), put in the way the team adds words: tracetalk/db/update.py import -> data/eval/fresh_v1/db/
  data/eval/fresh_v1/cases.jsonl     the test sentences: id, text, type (A B C D P, see eval/fresh_report.py; fresh_v2
                                U = in no DB, with "meaning", its reference meaning for the judge model only;
                                fresh_v3 S = like U plus "collected", four other comments with the word, written as
                                the collector would have stored them),
                                expression (as written in the text), headword, sense (1-based, which of the
                                headword's DB senses is right for A/D or wrong for C), note

Writes inputs.jsonl, gold.jsonl (the sense as its stored meaning text), pick_items.jsonl (eval/run_pick.py, as K2:
for each word's first A sentence, with_answer = its sense + four others, none = the four others only; two of them
from the look-alike headwords, two at random from the demo DB) and SHA256SUMS. Stops on any problem; overwrites
nothing.

    python3 eval/build_fresh.py
"""
import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracetalk.mad.benchmark import read_inputs  # noqa: E402
from tracetalk.mad.card import strip_han  # noqa: E402
from tracetalk.db.lexicon import compact, load_lexicon  # noqa: E402

TYPES = {"A", "B", "C", "D", "P", "U", "S", "M"}  # U (fresh_v2): a word that never goes into the DB; meaning = its reference
# M (fresh_v4): a comment with several expressions; like A, for the one it names
SENSED = ("A", "C", "D", "M")
UNKNOWN = ("U", "S")  # S (fresh_v3): a U word whose other comments the collector stored (0.8.1 쌓기)
STACK = (2, 4)  # how many of the stored comments each S usage file holds (0 = no file)


def bigrams(text):
    text = compact(text)
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def pick_items(words, others, rng, prefix):
    """K2-style pick items (eval/run_pick.py), with_answer for every word first, then none: the answer and four
    other meanings (two from the look-alike headwords, two at random), or the four alone. words: id, text, head,
    answer, own (all the word's meanings: never a distractor), year; others: head, meaning."""
    items = []
    for variant in ("with_answer", "none"):
        for w in words:
            head, answer = w["head"], w["answer"]
            taken = {compact(m) for m in w["own"]}
            usable = lambda o: compact(o["head"]) != compact(head) and compact(o["meaning"]) not in taken
            near = []
            for o in sorted(others, key=lambda o: (-len(bigrams(o["head"]) & bigrams(head)) /
                                                   len(bigrams(o["head"]) | bigrams(head)), o["head"])):
                if len(near) == 2:
                    break
                if usable(o):
                    near.append(o)
                    taken.add(compact(o["meaning"]))
            picks = near[:]
            while len(picks) < 4:
                o = rng.choice(others)
                if usable(o):
                    picks.append(o)
                    taken.add(compact(o["meaning"]))
            candidates = picks + ([{"head": head, "meaning": answer}] if variant == "with_answer" else [])
            rng.shuffle(candidates)
            ids = [o["meaning"] for o in candidates]
            items.append({"id": f"{prefix}-{variant[0]}-{w['id']}", "text": w["text"], "expression": head,
                          "meanings": ids, "answer": f"C{ids.index(answer) + 1}" if variant == "with_answer" else "N",
                          "variant": variant, "year": w["year"],
                          "near_ids": [f"C{ids.index(o['meaning']) + 1}" for o in near]})
    return items


def jl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=str(ROOT / "data/eval/fresh_v1"))
    p.add_argument("--pool", default=str(ROOT / "data/db/lexicon/lexicon_demo_v1.jsonl"), help="distractors and the "
                   "DB the words must not already be in")
    p.add_argument("--also-not-in", nargs="*", default=[str(ROOT / "data/db/lexicon/lexicon_eval_v1.jsonl"),
                                                         str(ROOT / "data/db/lexicon/lexicon_teacher_v1.jsonl")])
    p.add_argument("--seed", type=int, default=20261105)
    p.add_argument("--pick-types", nargs="+", default=["A"], choices=["A", "D", "U"],
                   help="pick items from each word's first sentence of these types (fresh_v1: A; fresh_v2: A D U)")
    args = p.parse_args(argv)
    d = Path(args.dir)
    outs = [d / n for n in ("inputs.jsonl", "gold.jsonl", "pick_items.jsonl", "SHA256SUMS", "db", "stack")]
    if any(o.exists() for o in outs):
        p.error(f"이미 만들어진 파일이 있습니다(덮어쓰지 않음): {[o.name for o in outs if o.exists()]}")

    pool = load_lexicon(args.pool, missing_ok=False)
    known = {compact(e["expression"]) for path in [args.pool] + args.also_not_in for e in load_lexicon(path)}
    with (d / "fresh_db.csv").open(encoding="utf-8") as handle:
        sheet = list(csv.DictReader(handle))
    reviewed = d / "fresh_db_reviewed.csv"  # fresh_v4: rows a person is taken to have checked (import --reviewed)
    if reviewed.exists():
        with reviewed.open(encoding="utf-8") as handle:
            sheet += list(csv.DictReader(handle))
    heads = {r["expression"].strip() for r in sheet if r["expression"].strip()}
    clash = sorted(h for h in heads if compact(h) in known)
    if clash:
        p.error(f"이미 DB에 있는 낱말은 신선 낱말이 아닙니다: {clash}")

    subprocess.run([sys.executable, "-m", "tracetalk.db.update", "--live", str(d / "db"), "import",
                    str(d / "fresh_db.csv")], check=True, cwd=ROOT)
    if reviewed.exists():
        subprocess.run([sys.executable, "-m", "tracetalk.db.update", "--live", str(d / "db"), "import", str(reviewed),
                        "--reviewed"], check=True, cwd=ROOT)
    entries = load_lexicon(d / "db/entries.jsonl", missing_ok=False)
    senses = {}
    for e in entries:
        senses.setdefault(e["expression"], []).append(strip_han(e["meaning"]))
    usage_lines = {compact(u["text"]) for g in jl(d / "db/usages.jsonl") for u in g.get("lines", [])}

    cases = jl(d / "cases.jsonl")
    problems = []
    for c in cases:
        if c["type"] not in TYPES:
            problems.append(f"{c['id']}: 유형 {c['type']}")
        if c["type"] != "P" and c["expression"] not in c["text"]:
            problems.append(f"{c['id']}: 문장에 표현이 없음")
        if c["type"] in SENSED and not 1 <= c.get("sense", 0) <= len(senses.get(c["headword"], [])):
            problems.append(f"{c['id']}: DB 뜻 번호 {c.get('sense')} / {len(senses.get(c['headword'], []))}개")
        if compact(c["text"]) in usage_lines:
            problems.append(f"{c['id']}: 시험 문장이 DB 용례와 같음")
        if c["type"] in UNKNOWN and (not c.get("meaning", "").strip() or c["headword"] in senses
                                     or compact(c["headword"]) in known):
            problems.append(f"{c['id']}: {c['type']}는 참조 뜻이 있고 어느 DB에도 없는 낱말이어야 함")
        if c["type"] == "S":
            got = c.get("collected") or []
            if (len(got) != max(STACK) or len({compact(t) for t in got + [c["text"]]}) != len(got) + 1
                    or any(c["expression"] not in t for t in got) or any(compact(t) in usage_lines for t in got)):
                problems.append(f"{c['id']}: S는 표현이 든 서로 다른 다른 문장 {max(STACK)}개가 있어야 함")
    s_words = {compact(c["headword"]) for c in cases if c["type"] == "S"}
    if s_words & {compact(c["headword"]) for c in cases if c["type"] == "U"}:
        problems.append("S 낱말과 U 낱말이 겹침")
    if len({c["id"] for c in cases}) != len(cases):
        problems.append("id 중복")
    if problems:
        p.error("; ".join(problems))

    with (d / "inputs.jsonl").open("x", encoding="utf-8") as fi, (d / "gold.jsonl").open("x", encoding="utf-8") as fg:
        for c in cases:
            fi.write(json.dumps({"id": c["id"], "text": c["text"], "family": f"fresh:{c.get('headword') or c['id']}",
                                 "split": "diagnostic"}, ensure_ascii=False) + "\n")
            sense = senses[c["headword"]][c["sense"] - 1] if c["type"] in SENSED else None
            fg.write(json.dumps({"case_id": c["id"], "type": c["type"], "expression": c.get("expression", ""),
                                 "headword": c.get("headword"), "sense": sense, "note": c.get("note", ""),
                                 **({"recent": True} if c.get("recent") else {}), **({"no_post": True} if c.get("no_post") else {}),
                                 **({"reference_meaning": c["meaning"]} if c["type"] in UNKNOWN else {})},
                                ensure_ascii=False) + "\n")
    unknown = [c for c in cases if c["type"] in UNKNOWN]
    if unknown:  # eval/grade.py reads these (the judge sees the reference meaning, the card never does)
        with (d / "grade_gold.jsonl").open("x", encoding="utf-8") as handle:
            handle.writelines(json.dumps({"case_id": c["id"], "family": f"fresh:{c['headword']}", "stratum": "unregistered",
                                          "expression": c["expression"], "reference_meaning": c["meaning"],
                                          "source": c.get("source", ""), "license": "TraceTalk 작성",
                                          "review_status": "TraceTalk 정리, 팀 검수 전"}, ensure_ascii=False) + "\n"
                              for c in unknown)

    read_inputs(d / "inputs.jsonl")  # the bench's own check (11-05: split "fresh" stopped the run)

    stacked = [c for c in cases if c["type"] == "S"]
    stack_names = []
    if stacked:  # S: the usage files the S sentences run with, as tracetalk.db.usage.collected_groups makes them
        (d / "stack").mkdir()
        (d / "stack/inputs_s.jsonl").write_text("".join(json.dumps({"id": c["id"], "text": c["text"], "family":
                                                f"fresh:{c['headword']}", "split": "diagnostic"}, ensure_ascii=False)
                                                + "\n" for c in stacked), encoding="utf-8")
        stack_names.append("stack/inputs_s.jsonl")
        for k in STACK:
            rows = [{"id": "col-" + hashlib.sha256(compact(c["headword"]).encode("utf-8")).hexdigest()[:10],
                     "expression": c["headword"], "variants": [c["expression"]] if c["expression"] != c["headword"] else [],
                     "lines": [{"text": t, "context": ""} for t in c["collected"][:k]], "source": "수집기(카드 입력)",
                     "license": "로컬 수집", "note": "검수 전: 카드에 들어온 문장 (fresh_v3 쌓기, 직접 쓴 문장)",
                     "added_at": ""} for c in stacked]
            (d / f"stack/collected_{k}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                                                  for r in rows), encoding="utf-8")
            stack_names.append(f"stack/collected_{k}.jsonl")
        read_inputs(d / "stack/inputs_s.jsonl")

    rng = random.Random(args.seed)
    others = [{"head": e["expression"], "meaning": strip_han(e["meaning"])} for e in pool] + \
             [{"head": h, "meaning": m} for h, ms in senses.items() for m in ms]
    firsts = {}
    for c in cases:
        if c["type"] in args.pick_types and c["headword"] not in firsts:
            firsts[c["headword"]] = c
    words = [{"id": c["id"], "text": c["text"], "head": head,
              "answer": c["meaning"] if c["type"] == "U" else senses[head][c["sense"] - 1],
              "own": [c["meaning"]] if c["type"] == "U" else senses[head], "year": c.get("year", "2025")}
             for head, c in firsts.items()]
    items = pick_items(words, others, rng, "fr")
    with (d / "pick_items.jsonl").open("x", encoding="utf-8") as handle:
        handle.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in items)
    counts = Counter(i["variant"] for i in items)

    names = ["fresh_db.csv", "cases.jsonl", "inputs.jsonl", "gold.jsonl", "pick_items.jsonl", "db/entries.jsonl",
             "db/usages.jsonl"] + (["fresh_db_reviewed.csv"] if reviewed.exists() else []) + (["grade_gold.jsonl"] if unknown else []) + stack_names
    (d / "SHA256SUMS").write_text("".join(f"{hashlib.sha256((d / n).read_bytes()).hexdigest()}  {n}\n" for n in names),
                                  encoding="utf-8")
    print(json.dumps({"words": len(senses), "senses": sum(map(len, senses.values())), "cases": len(cases),
                      "types": dict(Counter(c["type"] for c in cases)), "pick_items": dict(counts)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
