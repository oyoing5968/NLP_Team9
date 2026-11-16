#!/usr/bin/env python3
"""KoNeoBench evaluation sets for 0.7 (v9). EVALUATION ONLY: never training data, never the demo DB, never in a
kit for others (data/eval_koneo/ is excluded from every bundle). Prints counts only, never KoNeoBench text.

K1 "DB 업데이트 전/후" (slide 5: LLMs misread the newest words): Task 4 words, stratified by first-seen year.
   k1_inputs.jsonl / k1_gold.jsonl     the word's own news sentence as the comment; gold = its definition
   k1_lexicon_after.jsonl             the same words as DB rows (meaning, origin = 원어) for the "after" run
K2 "모호성 판단" (slide 7: MAD compares candidates and decides): the DB returned five near entries for a word -
   the right one, two whose headwords look most alike, two from the same semantic category - in shuffled order;
   which meaning fits the sentence? In the "none" variant the right one is missing and the answer is to abstain.
   Task 1's own distractors are words without definitions in KoNeoBench (2 of 1,785 confusing distractors are
   headwords), so the candidates are other KoNeoBench definitions instead.
   k2_items.jsonl                     id, text, expression, meanings, answer (C1..C5 or N), variant, year,
                                      near_ids (the two look-alike headwords' candidates)
K1 and K2 use different words. Only words whose headword occurs in its sentence as written are used, and
none that the evaluation DB (KoCulture lexicon + usages) already has. K2 candidate meanings are all distinct.
Rows alternate by year, so a prefix (--limit N) is balanced across 2020-2024.

    python3 eval/build_koneo_eval.py --out data/eval_koneo
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracetalk.db.lexicon import compact, load_lexicon  # noqa: E402
from tracetalk.db.usage import load_usages  # noqa: E402

SRC = ROOT / "data/eval/external/koneobench"
NOTE = "KoNeoBench (bcmilab/ko-neobench d251cd9a) - 평가 전용, 재배포·학습 금지"


def load(name):
    with (SRC / name).open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def bigrams(text):
    text = compact(text)
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    p.add_argument("--k1-per-year", type=int, default=40)
    p.add_argument("--k2-per-year", type=int, default=40, help="with the answer among the candidates")
    p.add_argument("--k2-none-per-year", type=int, default=20, help="the answer removed: abstaining is right")
    p.add_argument("--seed", type=int, default=1103)
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(args.seed)

    task4, task1 = load("Task4_with_ex.csv"), load("Task1_type_1.csv")
    # Words the evaluation DB (KoCulture lexicon + usages) already has would not be "before the update".
    known = {compact(f) for e in load_lexicon(ROOT / "data/db/lexicon/lexicon_eval_v1.jsonl") for f in [e["expression"], *e["variants"]]}
    known |= {compact(f) for g in load_usages([ROOT / "data/db/usage/usages_eval_v1.jsonl"])
              for f in [g["expression"], *g["variants"]]}
    skipped = Counter()
    surface = {compact(r["뜻풀이"]): r["정답 (표제어)"] for r in task1}
    category = {compact(r["뜻풀이"]): r["의미범주"] for r in task1}
    words = []
    for r in task4:
        head, sentence = r["색인표제어"].strip(), r["용례"].strip()
        if not head or not sentence or compact(head) not in compact(sentence):
            continue
        key = compact(r["뜻풀이"])
        if compact(head) in known or compact(surface.get(key, "")) in known:
            skipped["평가 DB에 이미 있음"] += 1
            continue
        words.append({"key": hashlib.sha256(("kn:" + head + key).encode()).hexdigest()[:10], "head": head,
                      "sentence": sentence, "meaning": r["뜻풀이"].strip(), "origin": r["원어"].strip(),
                      "formation": r["단어 형성법"].strip(), "year": r["최초 출현 연도"].strip(),
                      "surface": surface.get(key, ""), "category": category.get(key, "")})
    by_year = defaultdict(list)
    for w in words:
        by_year[w["year"]].append(w)
    k1, k2, k2_none = [], [], []
    for year in sorted(by_year):
        pool = by_year[year][:]
        rng.shuffle(pool)
        k1 += pool[:args.k1_per_year]
        k2 += pool[args.k1_per_year:args.k1_per_year + args.k2_per_year]
        start = args.k1_per_year + args.k2_per_year
        k2_none += pool[start:start + args.k2_none_per_year]
    # Years take turns, so the first N rows (run_bench --limit, run_pick --limit) cover every year evenly.
    turn = lambda rows: sorted(rows, key=lambda w: ([x for x in rows if x["year"] == w["year"]].index(w), w["year"]))
    k1, k2, k2_none = turn(k1), turn(k2), turn(k2_none)

    with (out / "k1_inputs.jsonl").open("x", encoding="utf-8") as inputs, \
            (out / "k1_gold.jsonl").open("x", encoding="utf-8") as gold, \
            (out / "k1_lexicon_after.jsonl").open("x", encoding="utf-8") as lexicon:
        for w in k1:
            case = "kn1-" + w["key"]
            inputs.write(json.dumps({"id": case, "text": w["sentence"], "family": "kn:" + w["key"],
                                     "split": "diagnostic"}, ensure_ascii=False) + "\n")
            gold.write(json.dumps({"case_id": case, "family": "kn:" + w["key"], "stratum": "y" + w["year"],
                                   "expression": w["head"], "reference_meaning": w["meaning"],
                                   "formation": w["formation"], "source": NOTE, "source_date": w["year"],
                                   "license": "평가 전용", "review_status": "KoNeoBench expert lexicographic review"},
                                  ensure_ascii=False) + "\n")
            variants = [w["surface"]] if w["surface"] and compact(w["surface"]) != compact(w["head"]) \
                and compact(w["surface"]) in compact(w["sentence"]) else []
            lexicon.write(json.dumps({"id": "kn-" + w["key"], "expression": w["head"], "variants": variants,
                                      "meaning": w["meaning"], "family": "kn:" + w["key"], "source": NOTE,
                                      "license": "평가 전용", "origin": w["origin"], "pos": ""},
                                     ensure_ascii=False) + "\n")

    others = [w for w in words if w not in k1]
    by_category = defaultdict(list)
    for w in others:
        by_category[w["category"]].append(w)
    counts = Counter()
    with (out / "k2_items.jsonl").open("x", encoding="utf-8") as handle:
        for variant, items in (("with_answer", k2), ("none", k2_none)):
            for w in items:
                # Every candidate meaning differs from the answer's and from each other (11-03 review: two
                # headwords can share one definition, which made a "none" item secretly answerable).
                taken = {compact(w["meaning"])}
                fresh = lambda o: o is not w and compact(o["head"]) != compact(w["head"]) and compact(o["meaning"]) not in taken
                near = []
                for o in sorted(others, key=lambda o: (-len(bigrams(o["head"]) & bigrams(w["head"])) /
                                                       len(bigrams(o["head"]) | bigrams(w["head"])), o["key"])):
                    if len(near) == 2:
                        break
                    if fresh(o):
                        near.append(o)
                        taken.add(compact(o["meaning"]))
                picks = near[:]
                same = [o for o in by_category[w["category"]] if fresh(o)]
                for o in rng.sample(same, len(same)):
                    if len(picks) == 4:
                        break
                    if fresh(o):
                        picks.append(o)
                        taken.add(compact(o["meaning"]))
                while len(picks) < 4:  # small category: fill from anywhere
                    o = rng.choice(others)
                    if fresh(o):
                        picks.append(o)
                        taken.add(compact(o["meaning"]))
                candidates = picks + ([w] if variant == "with_answer" else [])
                rng.shuffle(candidates)
                answer = f"C{candidates.index(w) + 1}" if variant == "with_answer" else "N"
                handle.write(json.dumps({"id": f"kn2-{variant[0]}-{w['key']}", "text": w["sentence"],
                                         "expression": w["head"], "meanings": [c["meaning"] for c in candidates],
                                         "answer": answer, "variant": variant, "year": w["year"],
                                         "near_ids": [f"C{candidates.index(o) + 1}" for o in near]},
                                        ensure_ascii=False) + "\n")
                counts[(variant, w["year"])] += 1
    print(json.dumps({"words_usable": len(words), "of": len(task4), "skipped": dict(skipped), "k1": len(k1),
                      "k1_years": dict(Counter(w["year"] for w in k1)),
                      "k2": {f"{v}/{y}": n for (v, y), n in sorted(counts.items())},
                      "k1_with_surface_variant": sum(1 for w in k1 if w["surface"] and compact(w["surface"]) != compact(w["head"])),
                      "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
