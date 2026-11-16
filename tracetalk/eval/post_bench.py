#!/usr/bin/env python3
"""Post bench (0.11): do the fetched posts reach a new word the way people write it? Offline, no model: only tracetalk/evidence/corpus.py.

For every development case whose meaning is only in the posts (U, S: never in the DB; N: fresh_v5's newest words):
  found     Corpus.passages(expression, [headword]) gives a passage the card would read (score >= tau_passage)
  right     fresh_v5 only (its gold has the post): the gold post is among them
  spotted   the comment-level finders (phrase_hits + headword_hits) mark a span over the expression in the comment
and, for the comments with no new word (P: plain, B: a DB word used in its standard sense), how many spans they mark
anyway (false spots: every one becomes a question the card has to answer).

    bash mac/run.sh python eval/post_bench.py                       (data/db/live/corpus.jsonl)
    bash mac/run.sh python eval/post_bench.py --output runs/tmp/post_bench_<날짜>.json
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracetalk.evidence.corpus import load  # noqa: E402
from tracetalk.db.lexicon import compact  # noqa: E402
from tracetalk.evidence.reading import form_regex  # noqa: E402

SETS = ("fresh_v2", "fresh_v3", "fresh_v4", "fresh_v5")
NEW = ("U", "S", "N")
PLAIN = ("P", "B")
TAU_PASSAGE = 1.5  # tracetalk/mad/card.py CARD["tau_passage"]


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def where(text, expression):
    m = re.search(form_regex(expression), text) if compact(expression) else None
    return (m.start(), m.end()) if m else None


def bench(corpus, sets=SETS):
    out, cases = {}, []
    for name in sets:
        d = ROOT / "data" / "eval" / name
        texts = {r["id"]: r["text"] for r in rows(d / "inputs.jsonl")}
        n = Counter()
        for g in rows(d / "gold.jsonl"):
            text = texts.get(g["case_id"], "")
            spots = corpus.phrase_hits(text) + corpus.headword_hits(text)
            if g["type"] in PLAIN:
                n["plain"] += 1
                n["false_spots"] += len(spots)
                if spots:
                    cases.append({"set": name, "case": g["case_id"], "type": g["type"], "false_spots": [s["span"] for s in spots]})
                continue
            if g["type"] not in NEW:
                continue
            forms = [g["expression"]] + ([g["headword"]] if g.get("headword") and g["headword"] != g["expression"] else [])
            found = [p for p in corpus.passages(forms[0], forms[1:]) if p["score"] >= TAU_PASSAGE]
            at = where(text, g["expression"])
            spotted = bool(at) and any(s["start"] < at[1] and at[0] < s["end"] for s in spots)
            right = None
            if g.get("source"):
                right = any(p["url"].rstrip("/") == g["source"].rstrip("/") for p in found)
                n["with_source"] += 1
                n["right"] += right
            n["new"] += 1
            n["found"] += bool(found)
            n["spotted"] += spotted
            cases.append({"set": name, "case": g["case_id"], "type": g["type"], "expression": g["expression"], "found": bool(found),
                          "right": right, "spotted": spotted, "urls": [p["url"] for p in found]})
        out[name] = dict(n)
    return out, cases


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--corpus", default=str(ROOT / "data/db/live/corpus.jsonl"))
    p.add_argument("--output")
    args = p.parse_args(argv)
    corpus = load(args.corpus)
    totals, cases = bench(corpus)
    print(f"근거 글 {len(corpus)}개 ({args.corpus})")
    for name, n in totals.items():
        right = f" · 맞는 글 {n.get('right', 0)}/{n['with_source']}" if n.get("with_source") else ""
        print(f"{name}: 새 말 {n.get('new', 0)}개 중 근거 글 찾음 {n.get('found', 0)} · 댓글에서 짚음 {n.get('spotted', 0)}{right}"
              f" | 새 말 없는 댓글 {n.get('plain', 0)}개에서 헛짚음 {n.get('false_spots', 0)}")
    s = Counter()
    for n in totals.values():
        s.update(n)
    print(f"합계: 새 말 {s['new']}개 중 찾음 {s['found']} · 짚음 {s['spotted']} · 맞는 글 {s['right']}/{s['with_source']} | 헛짚음 {s['false_spots']}/{s['plain']}")
    if args.output:
        Path(args.output).write_text(json.dumps({"totals": totals, "cases": cases}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("->", args.output)
    return totals, cases


if __name__ == "__main__":
    main()
