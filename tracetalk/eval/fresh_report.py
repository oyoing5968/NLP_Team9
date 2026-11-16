#!/usr/bin/env python3
"""Fresh-word check (fresh_v1, 11-05, read-only): do words that spread in 2025-2026 work once they are in the DB, and
does MAD do its job on the cases built for it? Scored by rule against data/eval/fresh_v1/gold.jsonl, no judge model.

Card runs (eval/run_bench.py, card = MAD where the card routes to it, card_single = one decision):
  before   the demo DB without the fresh words: is the word found at all, and is a meaning shown for it ever settled
  after    the demo DB plus the fresh rows (tracetalk/db/update.py import), by case type:
     A  slang use whose sense is in the DB        right = that DB sense
     B  the same letters as an ordinary word      right = not read as slang (no item, or the literal reading L)
     C  a slang sense the DB does not have        right = not the DB sense (a new meaning N, or uncertain);
                                                  confident wrong = the DB sense, proposed
     D  the word has two senses in the DB         right = the sense of this sentence
     P  no slang at all                           right = nothing read as slang
  and which decision ran for the target (single / mad / guess) per type
  regress  the demo sentences without the fresh rows (twice: the second run is the control for run-to-run noise) and
           with them, same seed: does a fresh row get into a demo card, and do more cards change than in the control
Pick runs (eval/run_pick.py: single 1 call, vote 5, mad 5, the same candidates): with_answer and none.
The bars were written before the run (docs/DESIGN.md) and are applied here as written.

    python3 eval/fresh_report.py --gold data/eval/fresh_v1/gold.jsonl --before B.jsonl --after A.jsonl \\
        --picks P42.jsonl P43.jsonl P44.jsonl --regress-without R0.jsonl --regress-control R0b.jsonl \\
        --regress-with R1.jsonl
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

TYPES = ("A", "B", "C", "D", "P")
NAMES = {"A": "A 신조어로 씀(DB 뜻 있음)", "B": "B 같은 글자, 표준어로 씀", "C": "C DB에 없는 다른 뜻",
         "D": "D DB 뜻 둘 중 고르기", "P": "P 신조어 없음"}
A_RIGHT = 0.85      # A right, card, mean over seeds (the test split's registered-meaning bar)
B_RIGHT = 0.70      # B not read as slang, card, mean over seeds
FAILURES = 0.02     # runs not completed, all card runs


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def target(record, gold):
    """The card item for the gold expression: the item over its place in the sentence, else one with its headword."""
    text = record["result"]["request"]["text"]
    items = (record["result"].get("card") or {}).get("items") or []
    at = text.find(gold["expression"])
    end = at + len(gold["expression"])
    for it in items:
        if at >= 0 and it.get("start") is not None and it["start"] < end and at < it["end"]:
            return it
    return next((it for it in items if gold.get("headword") and it.get("headword") == gold["headword"]), None)


def outcome(record, gold):
    """One card run against its gold row -> a small dict of what the card did."""
    done = record["status"] == "completed"
    items = (record["result"].get("card") or {}).get("items") or [] if done else []
    it = target(record, gold) if done else None
    seen = "failed" if not done else "none" if it is None else "literal" if it["choice"] == "L" else (
        "uncertain" if it["status"] != "proposed" else "new" if it["choice"] == "N" else "db")
    db = seen == "db" and it.get("db_meaning") is not None
    same = db and gold.get("sense") is not None and it["db_meaning"].strip() == gold["sense"].strip()
    t = gold["type"]
    right = {"A": same, "D": same, "B": seen in ("none", "literal"), "C": seen in ("new", "uncertain"),
             "P": done and all(i.get("choice") == "L" for i in items)}[t]
    return {"done": done, "seen": seen, "right": bool(right), "decided_by": it.get("decided_by") if it else None,
            "estimate": bool(it and it.get("estimate")), "confident_wrong": t == "C" and db and same,
            "slang_items": sum(i.get("choice") != "L" for i in items)}


def spread(values):
    return f"평균 {statistics.mean(values):.1f} (범위 {min(values)}~{max(values)})" if values else "-"


def card_table(records, gold, label):
    """method -> seed -> type -> Counter; prints the table and returns it."""
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for r in records:
        g = gold[r["case_id"]]
        o = outcome(r, g)
        c = per[r["method"]][r["seed"]][g["type"]]
        c["n"] += 1
        c["right"] += o["right"]
        c["failed"] += not o["done"]
        c["seen_" + o["seen"]] += 1
        c["estimate"] += o["estimate"]
        c["confident_wrong"] += o["confident_wrong"]
        if o["decided_by"]:
            c["by_" + o["decided_by"]] += 1
    print(f"== {label}")
    for method in sorted(per):
        seeds = sorted(per[method])
        print(f"   [{method}] seed {seeds}")
        for t in TYPES:
            cs = [per[method][s][t] for s in seeds]
            if not cs[0]["n"]:
                continue
            seen = sum((Counter({k[5:]: v for k, v in c.items() if k.startswith("seen_")}) for c in cs), Counter())
            by = sum((Counter({k[3:]: v for k, v in c.items() if k.startswith("by_")}) for c in cs), Counter())
            print(f"      {NAMES[t]:<22} n={cs[0]['n']:<3} 맞음 {spread([c['right'] for c in cs])} · 결과 {dict(seen)} · "
                  f"결정 {dict(by)} · 추정 표시 {sum(c['estimate'] for c in cs)}"
                  + (f" · 확신한 오답 {sum(c['confident_wrong'] for c in cs)}" if t == "C" else ""))
    return per


def before_table(records, gold):
    """Without the fresh rows: found at all, shown as an estimate, shown as settled (never wanted)."""
    c = Counter()
    for r in records:
        g = gold[r["case_id"]]
        o = outcome(r, g)
        slang = g["type"] in ("A", "C", "D")
        c["slang_n" if slang else "plain_n"] += 1
        if slang:
            found = o["seen"] not in ("none", "literal", "failed")
            c["found"] += found
            c["estimate"] += found and o["estimate"]
            c["settled"] += found and not o["estimate"]
        elif g["type"] == "P":  # no target: any expression read as slang (11-05: only the target was counted)
            c["misread"] += o["slang_items"] > 0
        else:
            c["misread"] += o["seen"] not in ("none", "literal", "failed")
        c["failed"] += not o["done"]
    print("== DB에 넣기 전 (시연 DB만)")
    print(f"   신조어로 쓴 문장 {c['slang_n']}개: 찾음 {c['found']} · 그중 '추정' 표시 {c['estimate']} · 확정처럼 보임 {c['settled']}")
    print(f"   표준어·평문 문장 {c['plain_n']}개: 신조어로 읽음 {c['misread']} · 끝나지 않음 {c['failed']}")
    return c


def paired(records, gold, types):
    """card against card_single on the same case and seed."""
    out = {}
    for r in records:
        if gold[r["case_id"]]["type"] in types:
            out[(r["case_id"], r["seed"], r["method"])] = outcome(r, gold[r["case_id"]])
    c = Counter()
    for (case, seed, method), a in out.items():
        b = out.get((case, seed, "card_single"))
        if method != "card" or b is None:
            continue
        c["n"] += 1
        c["mad_only"] += a["right"] and not b["right"]
        c["single_only"] += b["right"] and not a["right"]
        c["mad_right"] += a["right"]
        c["single_right"] += b["right"]
        c["mad_ran"] += a["decided_by"] == "mad"
        c["mad_cw"] += a["confident_wrong"]
        c["single_cw"] += b["confident_wrong"]
    return c


def pick_table(picks):
    table = defaultdict(Counter)
    for p in picks:
        c = table[(p["method"], p["variant"])]
        c["n"] += 1
        c["correct"] += p["correct"]
        c["abstained"] += p["abstained"]
        c["near"] += p.get("near", False)
        c["failed"] += p["status"] != "completed"
    print("== 고르기만 따로 (같은 후보, 호출 수: 한 번 1 · 다수결 5 · MAD 5)")
    for (method, variant), c in sorted(table.items()):
        print(f"   {method:<7} {variant:<12} n={c['n']:<4} 정답 {c['correct']:<4} 유보 {c['abstained']:<4} "
              f"비슷한 후보에 속음 {c['near']:<3} 끝나지 않음 {c['failed']}")
    return table


def regress(without, control, with_fresh, fresh_heads):
    """Same demo sentences, same seed: without the fresh rows twice (run-to-run noise) and with them. Wanted: no fresh
    headword in any demo card, and no more changed cards than the control shows."""
    key = lambda r: (r["case_id"], r["seed"], r["method"])
    items = lambda r: (r["result"].get("card") or {}).get("items") or []
    shape = lambda r: sorted((i["expression"], i["choice"], i["status"]) for i in items(r))
    a, b, c = ({key(r): shape(r) for r in runs} for runs in (without, with_fresh, control))
    changed = sorted(k[0] for k in a if k in b and a[k] != b[k])
    noise = sorted(k[0] for k in a if k in c and a[k] != c[k])
    intruded = sorted(r["case_id"] for r in with_fresh if any(i.get("headword") in fresh_heads for i in items(r)))
    print(f"== 시연 문장 회귀 (같은 seed): 신선 행이 끼어든 카드 {intruded} · 넣고 바뀐 카드 {len(changed)} {changed} · "
          f"넣지 않고 다시 돌려도 바뀐 카드(흔들림) {len(noise)} {noise}")
    return intruded, changed, noise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", required=True)
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--picks", nargs="*", default=[])
    p.add_argument("--regress-without")
    p.add_argument("--regress-control")
    p.add_argument("--regress-with")
    args = p.parse_args(argv)
    gold = {g["case_id"]: g for g in rows(args.gold)}
    before, after = rows(args.before), rows(args.after)
    missing = sorted({r["case_id"] for r in before + after} - set(gold))
    if missing:
        p.error(f"정답표에 없는 문장: {missing}")
    print(f"== 신선 신조어 확인 (fresh_v1) · 문장 {len(gold)} · 유형 {dict(Counter(g['type'] for g in gold.values()))}")
    before_c = before_table(before, gold)
    per = card_table(after, gold, "DB에 넣은 뒤 (시연 DB + 신선 행)")
    picks = [r for name in args.picks for r in rows(name)]
    table = pick_table(picks) if picks else {}
    heads = {g["headword"] for g in gold.values() if g.get("headword")}
    reg = regress(rows(args.regress_without), rows(args.regress_control), rows(args.regress_with), heads) \
        if args.regress_without and args.regress_control and args.regress_with else None

    card = per.get("card", {})
    seeds = sorted(card)
    rate = lambda t: statistics.mean(card[s][t]["right"] / card[s][t]["n"] for s in seeds) if seeds and card[seeds[0]][t]["n"] else None
    runs = sum(card[s][t]["n"] for s in seeds for t in TYPES)
    failed = sum(card[s][t]["failed"] for s in seeds for t in TYPES)
    plain_wrong = sum(card[s]["P"]["n"] - card[s]["P"]["right"] for s in seeds)
    cd = paired(after, gold, ("C",))
    bcd = paired(after, gold, ("B", "C", "D"))
    print(f"== MAD 대 한 번(card_single), 같은 문제·seed: B·C·D {bcd['n']}쌍 중 MAD가 실제로 돈 것 {bcd['mad_ran']} · "
          f"MAD만 맞음 {bcd['mad_only']} · 한 번만 맞음 {bcd['single_only']} · 맞음 {bcd['mad_right']} 대 {bcd['single_right']}")
    print(f"   C(DB에 없는 뜻)만: 맞음 {cd['mad_right']} 대 {cd['single_right']} · 확신한 오답 {cd['mad_cw']} 대 {cd['single_cw']}")
    pick = lambda m, v, k: table.get((m, v), Counter())[k]
    a_rate, b_rate = rate("A"), rate("B")
    bars = [
        (f"① A 맞음 card 평균 {a_rate:.1%} (기준 {A_RIGHT:.0%} 이상)" if a_rate is not None else "① A 없음",
         a_rate is not None and a_rate >= A_RIGHT),
        (f"② B 표준어로 읽음 card 평균 {b_rate:.1%} (기준 {B_RIGHT:.0%} 이상)" if b_rate is not None else "② B 없음",
         b_rate is not None and b_rate >= B_RIGHT),
        (f"③ P 신조어로 읽음 {plain_wrong} (기준 0)", plain_wrong == 0),
        (f"④ 넣기 전 확정처럼 보인 뜻 {before_c['settled']} (기준 0)", before_c["settled"] == 0),
        (f"⑤ 끝나지 않은 실행 {failed}/{runs} (기준 {FAILURES:.0%} 이하)", runs > 0 and failed / runs <= FAILURES),
        (f"⑥ C: MAD 맞음 {cd['mad_right']} ≥ 한 번 {cd['single_right']}, 확신한 오답 {cd['mad_cw']} ≤ {cd['single_cw']}",
         cd["n"] > 0 and cd["mad_right"] >= cd["single_right"] and cd["mad_cw"] <= cd["single_cw"]),
        (f"⑦ 고르기 none 유보: MAD {pick('mad', 'none', 'abstained')} > 다수결 {pick('vote', 'none', 'abstained')}, "
         f"> 한 번 {pick('single', 'none', 'abstained')}",
         bool(table) and pick("mad", "none", "abstained") > max(pick("vote", "none", "abstained"),
                                                                 pick("single", "none", "abstained"))),
        (f"⑧ 고르기 with_answer 정답: MAD {pick('mad', 'with_answer', 'correct')} ≥ 한 번 "
         f"{pick('single', 'with_answer', 'correct')} − n의 10%",
         bool(table) and pick("mad", "with_answer", "correct")
         >= pick("single", "with_answer", "correct") - 0.1 * pick("mad", "with_answer", "n")),
        (f"⑨ 시연 문장: 신선 행이 끼어듦 {len(reg[0]) if reg else '-'} (기준 0), 바뀐 카드 {len(reg[1]) if reg else '-'}"
         f" ≤ 흔들림 {len(reg[2]) if reg else '-'}", reg is not None and not reg[0] and len(reg[1]) <= len(reg[2])),
    ]
    print("== 사전 기준 (docs/DESIGN.md)")
    for text, ok in bars:
        print(f"   {text} → {'통과' if ok else '미달'}")
    missed = sum(not ok for _, ok in bars)
    print(f"== 판정: {'기준 모두 통과' if not missed else f'기준 {len(bars)}개 중 {missed}개 미달'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
