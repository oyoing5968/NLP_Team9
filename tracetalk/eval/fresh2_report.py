#!/usr/bin/env python3
"""fresh_v2 (0.8, read-only): the new card (unreviewed DB senses and words the DB lacks go to MAD) against the old
card (0.7) and one decision, on words that spread in 2025-2026, with the bars written before the run
(docs/DESIGN.md). Types A B C D P are scored by rule as in eval/fresh_report.py; U (a word in no DB) also
with the judge model's meaning verdicts (eval/grade.py on the U records only).

    python3 eval/fresh2_report.py --gold data/eval/fresh_v2/gold.jsonl --new after_new.jsonl --old after_old.jsonl \\
        --graded-new graded_u_new.jsonl --graded-old graded_u_old.jsonl --picks pick_*.jsonl \\
        --regress-without R0.jsonl --regress-control R1.jsonl --regress-with R2.jsonl --judge-file judge.txt
    python3 eval/fresh2_report.py --gold data/eval/fresh_v2/gold.jsonl --select U --source after_new.jsonl --to u_new.jsonl
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracetalk.db import update as update_db  # noqa: E402
from fresh_report import outcome, pick_table, regress, rows, spread, target  # noqa: E402
from tracetalk.db.lexicon import compact, load_lexicon  # noqa: E402
from tracetalk.db.usage import candidate_rows, stem  # noqa: E402

TYPES = ("A", "B", "C", "D", "P", "U")
NAMES = {"A": "A 신조어, 검수 전 맞는 뜻", "B": "B 같은 글자, 표준어", "C": "C 틀린 뜻 행(검수 전)", "D": "D DB 뜻 둘",
         "P": "P 신조어 없음", "U": "U DB에 없는 말"}
WAYS = ("새 카드", "옛 카드", "한 번")
A_RIGHT, B_RIGHT, D_RIGHT, C_MAD, U_FIND, QUEUE_U, FAILURES = 0.85, 0.70, 0.75, 0.90, 0.10, 0.80, 0.02


def way(record, old):
    return "옛 카드" if old else "새 카드" if record["method"] == "card" else "한 번"


def unknown_outcome(record, gold, verdict):
    """U: the card's item for a word the DB does not have, with the judge's meaning verdict (None if not graded)."""
    done = record["status"] == "completed"
    it = target(record, gold) if done else None
    ordinary = (record["result"].get("detection") or {}).get("ordinary_words") or []
    found = it is not None and it.get("choice") != "L" and it.get("status") != "failed"
    return {"done": done, "found": found, "settled": found and not it.get("estimate"),
            "uncertain": found and it.get("status") == "uncertain",
            "shown_wrong": found and it.get("status") == "proposed" and verdict in ("wrong", "partial"),
            "shown_right": found and it.get("status") == "proposed" and verdict == "correct",
            "standard": not found and any(compact(gold["expression"]) in compact(w) or compact(w) in compact(gold["expression"])
                                          for w in ordinary),
            "mad": bool(it and it.get("decided_by") == "mad")}


def tables(records, gold, verdicts):
    """way -> seed -> type -> Counter."""
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for old, r in records:
        g = gold[r["case_id"]]
        c = per[way(r, old)][r["seed"]][g["type"]]
        c["n"] += 1
        c["seconds"] += r["result"].get("elapsed_seconds") or 0
        if g["type"] == "U":
            u = unknown_outcome(r, g, verdicts.get((old, r["case_id"], r["seed"], r["method"])))
            c.update({k: int(v) for k, v in u.items()})
            c["failed"] += not u["done"]
            continue
        o = outcome(r, g)
        c["right"] += o["right"]
        c["failed"] += not o["done"]
        c["confident_wrong"] += o["confident_wrong"]
        c["mad"] += o["decided_by"] == "mad"
        c["slang_items"] += o["slang_items"] > 0
    return per


def show(per):
    for w in WAYS:
        if w not in per:
            continue
        seeds = sorted(per[w])
        print(f"   [{w}] seed {seeds}")
        for t in TYPES:
            cs = [per[w][s][t] for s in seeds]
            if not cs[0]["n"]:
                continue
            secs = sum(c["seconds"] for c in cs) / max(1, sum(c["n"] for c in cs))
            if t == "U":
                tot = sum(cs, Counter())
                print(f"      {NAMES[t]:<20} n={cs[0]['n']:<3} 찾음 {tot['found']} · 확정처럼 {tot['settled']} · 모름(보류) "
                      f"{tot['uncertain']} · 뜻 맞게 보여 줌 {tot['shown_right']} · 틀린 뜻 보여 줌 {tot['shown_wrong']} · "
                      f"표준어로 뺌 {tot['standard']} · MAD {tot['mad']} · 카드 {secs:.0f}초")
            else:
                print(f"      {NAMES[t]:<20} n={cs[0]['n']:<3} 맞음 {spread([c['right'] for c in cs])} · MAD {sum(c['mad'] for c in cs)}"
                      + (f" · 틀린 뜻 확정 {sum(c['confident_wrong'] for c in cs)}" if t == "C" else "")
                      + f" · 카드 {secs:.0f}초")


def collector(records, gold, known):
    """The new card's queue (tracetalk/db/update.py queue): U words found in it, and entries that came from P or B sentences."""
    by_text = {}
    for old, r in records:
        if not old and r["method"] == "card":
            by_text[r["result"]["request"]["text"]] = gold[r["case_id"]]["type"]
    cands = [row for old, r in records if not old and r["method"] == "card" for row in candidate_rows(r["result"])]
    listed = update_db.queue_rows(cands, known)
    u_words = {stem(g["headword"]) for g in gold.values() if g["type"] == "U"}
    in_queue = {stem(q["expression"]) for q in listed} & u_words
    plain = {stem(r.get("headword") or r["expression"]) for r in cands
             if by_text.get(r["text"]) in ("P", "B") and r["choice"] != "L"}  # every comment, not the 3 shown
    from_plain = [q["expression"] for q in listed if stem(q["expression"]) in plain]
    return listed, u_words, in_queue, from_plain


def select(args):
    gold = {g["case_id"]: g for g in rows(args.gold)}
    out = Path(args.to)
    if out.exists():
        raise SystemExit(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    kept = [s for s in Path(args.source).read_text(encoding="utf-8").splitlines()
            if s.strip() and gold[json.loads(s)["case_id"]]["type"] == args.select]
    out.write_text("".join(s + "\n" for s in kept), encoding="utf-8")
    print(f"{args.select} 기록 {len(kept)}개 → {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", required=True)
    p.add_argument("--select")
    p.add_argument("--source")
    p.add_argument("--to")
    p.add_argument("--new")
    p.add_argument("--old")
    p.add_argument("--graded-new")
    p.add_argument("--graded-old")
    p.add_argument("--picks", nargs="*", default=[])
    p.add_argument("--regress-without")
    p.add_argument("--regress-control")
    p.add_argument("--regress-with")
    p.add_argument("--lexicon", nargs="*", default=[], help="known words for the queue (demo DB + fresh rows)")
    p.add_argument("--judge-file")
    args = p.parse_args(argv)
    if args.select:
        return select(args)
    gold = {g["case_id"]: g for g in rows(args.gold)}
    records = [(False, r) for r in rows(args.new)] + [(True, r) for r in rows(args.old)]
    verdicts = {}
    for old, name in ((False, args.graded_new), (True, args.graded_old)):
        for g in rows(name) if name else []:
            verdicts[(old, g["case_id"], g["seed"], g["method"])] = g["verdict"]
    judge = Path(args.judge_file).read_text(encoding="utf-8").strip() if args.judge_file else "?"
    print(f"== fresh_v2 · 문장 {len(gold)} · 유형 {dict(Counter(g['type'] for g in gold.values()))} · 새 카드 판정 역할 {judge}")
    per = tables(records, gold, verdicts)
    show(per)
    table = pick_table([r for name in args.picks for r in rows(name)]) if args.picks else {}
    reg = regress(rows(args.regress_without), rows(args.regress_control), rows(args.regress_with),
                  {g["headword"] for g in gold.values() if g.get("headword")}) \
        if args.regress_without and args.regress_control and args.regress_with else None
    known = [e["expression"] for name in args.lexicon for e in load_lexicon(name)]
    listed, u_words, in_queue, from_plain = collector(records, gold, known)
    print(f"== 수집 표 (새 카드): 후보 {len(listed)}개 · U 낱말 {len(in_queue)}/{len(u_words)} 들어감 · P·B 문장에서 온 후보 {from_plain}")
    for q in listed[:12]:
        print(f"      {q['expression']}: 댓글 {q['comments']} · {q['verdicts']}{' · 새 뜻 후보' if q['new_sense'] else ''}"
              f"{' · 확인할 것 ' + ', '.join(q['hints']) if q['hints'] else ''}")

    new, old = per.get("새 카드", {}), per.get("옛 카드", {})
    seeds = sorted(new)
    rate = lambda t: statistics.mean(new[s][t]["right"] / new[s][t]["n"] for s in seeds) if seeds and new[seeds[0]][t]["n"] else None
    total = lambda tbl, t, k: sum(tbl[s][t][k] for s in tbl)
    runs = sum(new[s][t]["n"] for s in seeds for t in TYPES)
    failed = sum(new[s][t]["failed"] for s in seeds for t in TYPES)
    c_n, c_mad = total(new, "C", "n"), total(new, "C", "mad")
    cw_new, cw_old = total(new, "C", "confident_wrong"), total(old, "C", "confident_wrong")
    u_n_new, u_n_old = total(new, "U", "n"), total(old, "U", "n")
    find_new = total(new, "U", "found") / u_n_new if u_n_new else 0
    find_old = total(old, "U", "found") / u_n_old if u_n_old else 0
    pick = lambda m, v, k: table.get((m, v), Counter())[k]
    a, b, d = rate("A"), rate("B"), rate("D")
    fmt = lambda x: f"{x:.1%}" if x is not None else "-"
    bars = [
        (f"① A 맞음 평균 {fmt(a)} (기준 {A_RIGHT:.0%} 이상)", a is not None and a >= A_RIGHT),
        (f"② B 표준어로 읽음 평균 {fmt(b)} (기준 {B_RIGHT:.0%} 이상)", b is not None and b >= B_RIGHT),
        (f"③ C에서 MAD가 돈 비율 {c_mad}/{c_n} (기준 {C_MAD:.0%} 이상), 틀린 뜻 확정 {cw_new} ≤ 옛 카드 {cw_old}의 절반",
         c_n > 0 and c_mad / c_n >= C_MAD and cw_new <= cw_old / 2),
        (f"④ D 맞음 평균 {fmt(d)} (기준 {D_RIGHT:.0%} 이상)", d is not None and d >= D_RIGHT),
        (f"⑤ P 신조어로 읽음 {total(new, 'P', 'slang_items')} (기준 0)", total(new, "P", "n") > 0 and total(new, "P", "slang_items") == 0),
        (f"⑥ U 확정처럼 {total(new, 'U', 'settled')} (기준 0) · 틀린 뜻 보여 줌 {total(new, 'U', 'shown_wrong')} < 옛 카드 "
         f"{total(old, 'U', 'shown_wrong')} · 찾음 {find_new:.0%} ≥ 옛 카드 {find_old:.0%} − {U_FIND:.0%}p",
         u_n_new > 0 and total(new, "U", "settled") == 0 and total(new, "U", "shown_wrong") < total(old, "U", "shown_wrong")
         and find_new >= find_old - U_FIND),
        (f"⑦ 수집 표에 U 낱말 {len(in_queue)}/{len(u_words)} (기준 {QUEUE_U:.0%} 이상), P·B에서 온 후보 {len(from_plain)} (기준 0)",
         bool(u_words) and len(in_queue) / len(u_words) >= QUEUE_U and not from_plain),
        (f"⑧ 고르기 none 보류 MAD {pick('mad', 'none', 'abstained')} > 다수결 {pick('vote', 'none', 'abstained')}, > 한 번 "
         f"{pick('single', 'none', 'abstained')} · with_answer MAD {pick('mad', 'with_answer', 'correct')} ≥ 한 번 "
         f"{pick('single', 'with_answer', 'correct')} − n의 10%",
         bool(table) and pick("mad", "none", "abstained") > max(pick("vote", "none", "abstained"), pick("single", "none", "abstained"))
         and pick("mad", "with_answer", "correct") >= pick("single", "with_answer", "correct") - 0.1 * pick("mad", "with_answer", "n")),
        (f"⑨ 시연 문장: 신선 행 끼어듦 {len(reg[0]) if reg else '-'} (기준 0), 바뀐 카드 {len(reg[1]) if reg else '-'} ≤ 흔들림 "
         f"{len(reg[2]) if reg else '-'}", reg is not None and not reg[0] and len(reg[1]) <= len(reg[2])),
        (f"⑩ 끝나지 않은 실행 {failed}/{runs} (기준 {FAILURES:.0%} 이하)", runs > 0 and failed / runs <= FAILURES),
    ]
    print("== 사전 기준 (docs/DESIGN.md)")
    for text, ok in bars:
        print(f"   {text} → {'통과' if ok else '미달'}")
    missed = sum(not ok for _, ok in bars)
    print(f"== 판정: {'기준 모두 통과' if not missed else f'기준 {len(bars)}개 중 {missed}개 미달'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
