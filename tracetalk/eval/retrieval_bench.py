#!/usr/bin/env python3
"""Retrieval bench for the DB retriever (tracetalk/db/retriever.py): does the comment reach the right DB row when the
expression is written the way people actually write it? Offline; KoCulture validation only (no KoNeoBench).

Cases are made from data/eval/eval_v1 validation: each comment whose target expression is in the eval DB and written
there as-is, with the target spot rewritten (deterministically, no randomness):
  original   as in the data
  space      a space inside the expression (the exact patterns allow spaces: a sanity row)
  vowel      one vowel changed to a look-alike in a middle letter (오또카지 -> 오또커지)
  tense      one consonant tensed or relaxed in a non-first letter (오또카지 -> 오또카찌), a common respelling
  removed    the expression replaced by "그거": the target row must NOT be found (a false-hit check)
Typo cases are split by expression length (2 letters / 3 or more): the fuzzy stage only handles 3 or more.
Reported per stage set: found (the target row, on the rewritten spot), other rows per comment, ms per comment.

    python3 eval/retrieval_bench.py --output reports/retrieval_bench_<날짜>.json
    bash mac/run.sh python eval/retrieval_bench.py --output ...   (with morph and fuzzy installed)
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracetalk.mad.card import _parts, _syllable, entries_from_store, find  # noqa: E402
from tracetalk.db.lexicon import compact, load_lexicon  # noqa: E402
from tracetalk.db.retriever import Retriever, available  # noqa: E402
from tracetalk.db.usage import load_usages  # noqa: E402

VOWEL = {1: 5, 5: 1, 0: 4, 4: 0, 8: 13, 13: 8, 18: 13, 20: 19, 2: 6, 6: 2, 12: 17, 17: 12, 9: 14, 14: 9, 11: 16,
         16: 11, 3: 7, 7: 3, 10: 15, 15: 10, 19: 20}
TENSE = {0: 1, 1: 0, 3: 4, 4: 3, 7: 8, 8: 7, 9: 10, 10: 9, 12: 13, 13: 12}
CONFIGS = (("exact",), ("exact", "morph"), ("exact", "fuzzy"), ("exact", "morph", "fuzzy"))


def rewrite(span, kind):
    """The span with one letter changed, or None when it has no letter to change that way."""
    letters = [i for i, ch in enumerate(span) if _parts(ch)]
    if len(letters) < 2:
        return None
    order = [letters[len(letters) // 2]] + [i for i in reversed(letters[1:]) if i != letters[len(letters) // 2]]
    for i in order:  # never the first letter: a typo there is rare and the fuzzy stage keeps the first jamo
        initial, medial, final = _parts(span[i])
        if kind == "vowel" and medial in VOWEL:
            return span[:i] + _syllable(initial, VOWEL[medial], final) + span[i + 1:]
        if kind == "tense" and initial in TENSE:
            return span[:i] + _syllable(TENSE[initial], medial, final) + span[i + 1:]
    return None


def cases(inputs, gold, entries):
    by_form = {compact(e["expression"]): e for e in entries}
    out = []
    for row in inputs:
        g = gold[row["id"]]
        entry = by_form.get(compact(g["expression"])) if g["expression"] else None
        if entry is None:
            continue
        hit = next(iter(find(row["text"], [entry])), None)
        if hit is None:
            continue
        span, text = hit["span"], row["text"]
        size = "2" if len(compact(span)) == 2 else "3+" if len(compact(span)) >= 3 else "1"
        variants = {"original": span, "removed": "그거"}
        letters = [c for c in span if not c.isspace()]
        if len(letters) >= 2 and not any(c.isspace() for c in span):
            variants["space"] = span[:len(span) // 2] + " " + span[len(span) // 2:]
        for kind in ("vowel", "tense"):
            new = rewrite(span, kind)
            if new:
                variants[kind] = new
        for kind, new in variants.items():
            out.append({"id": f"{row['id']}:{kind}", "case": row["id"], "kind": kind, "size": size,
                        "stratum": g["stratum"], "expression": entry["expression"],
                        "text": text[:hit["start"]] + new + text[hit["end"]:],
                        "spot": [hit["start"], hit["start"] + len(new)]})
    return out


def run(case_rows, entries, stages):
    r = Retriever(stages)
    table = defaultdict(lambda: {"n": 0, "found": 0, "other_rows": 0, "ms": 0.0})
    for c in case_rows:
        started = time.perf_counter()
        hits = r.hits(c["text"], entries)
        ms = (time.perf_counter() - started) * 1000
        target = [h for h in hits if h["entry"]["expression"] == c["expression"]
                  and h["start"] < c["spot"][1] and c["spot"][0] < h["end"]]
        key = c["kind"] if c["kind"] in ("original", "space", "removed") else f"{c['kind']}·{c['size']}글자"
        t = table[key]
        t["n"] += 1
        t["found"] += bool(target)
        t["other_rows"] += sum(1 for h in hits if h["entry"]["expression"] != c["expression"])
        t["ms"] += ms
    return {k: {**v, "ms": round(v["ms"] / max(1, v["n"]), 2)} for k, v in sorted(table.items())}, r.stages


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inputs", default="data/eval/eval_v1/val_inputs.jsonl")
    p.add_argument("--gold", default="data/eval/eval_v1/val_gold.jsonl")
    p.add_argument("--lexicon", default="data/db/lexicon/lexicon_eval_v1.jsonl")
    p.add_argument("--usages", default="data/db/usage/usages_eval_v1.jsonl")
    p.add_argument("--write-cases", help="the generated cases as jsonl, for a person to look at")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    read = lambda name: [json.loads(s) for s in Path(name).read_text(encoding="utf-8").splitlines() if s.strip()]
    entries = entries_from_store(load_lexicon(args.lexicon), load_usages([args.usages]))
    gold = {g["case_id"]: g for g in read(args.gold)}
    rows = cases(read(args.inputs), gold, entries)
    output = Path(args.output)
    if output.exists() or (args.write_cases and Path(args.write_cases).exists()):
        p.error("출력 파일이 이미 있습니다. 새 이름을 쓰세요.")
    if args.write_cases:
        Path(args.write_cases).write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in rows), encoding="utf-8")
    have = set(available())
    report = {"cases": len(rows), "comments": len({c["case"] for c in rows}), "available": sorted(have), "runs": {}}
    print(f"== 검색 시험대: 댓글 {report['comments']}개 · 사례 {len(rows)}개 · 이 기기의 단계 {sorted(have)}")
    for stages in CONFIGS:
        if not set(stages) <= have:
            print(f"   {'+'.join(stages):<20} 건너뜀(라이브러리 없음)")
            continue
        table, used = run(rows, entries, stages)
        report["runs"]["+".join(used)] = table
        print(f"   {'+'.join(used)}")
        for kind, t in table.items():
            want = "찾으면 안 됨" if kind == "removed" else "찾음"
            print(f"      {kind:<10} n={t['n']:<4} {want} {t['found']:<4} 다른 행/댓글 {t['other_rows'] / max(1, t['n']):.2f}"
                  f"  {t['ms']:.1f}ms")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
