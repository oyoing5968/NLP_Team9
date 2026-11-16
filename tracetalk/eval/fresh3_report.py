#!/usr/bin/env python3
"""fresh_v3 (0.8.1, read-only): the new card (one-sense MAD with a side against the DB sense, nouns kept out of the
verb rule) against the 0.8.0 card, the old card (0.7) and one decision; and S (쌓기): the same S sentences with 0, 2
and 4 comments the collector stored. Bars written before the run (docs/DESIGN.md): ①~⑩ as fresh_v2, ⑪ ⑫ new.

    python3 eval/fresh3_report.py --gold data/eval/fresh_v3/gold.jsonl --new after_new.jsonl --mid after_080.jsonl \\
        --old after_old.jsonl --graded-new graded_u_new.jsonl --graded-old graded_u_old.jsonl \\
        --stack 2 stack_2.jsonl --stack 4 stack_4.jsonl --graded-stack 2 graded_s2.jsonl --graded-stack 4 graded_s4.jsonl \\
        --picks pick_*.jsonl \\
        --regress-without R0.jsonl --regress-control R1.jsonl --regress-with R2.jsonl --lexicon LEX... --judge-file J
    python3 eval/fresh3_report.py --gold data/eval/fresh_v3/gold.jsonl --select U S --source after_new.jsonl \\
        --method card --to u_new.jsonl
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fresh2_report import collector, unknown_outcome  # noqa: E402
from fresh_report import outcome, pick_table, regress, rows, spread  # noqa: E402
from tracetalk.db.lexicon import load_lexicon  # noqa: E402

TYPES = ("A", "B", "C", "D", "P", "U", "S")
NAMES = {"A": "A 신조어, 검수 전 맞는 뜻", "B": "B 같은 글자, 표준어", "C": "C 틀린 뜻 행(검수 전)", "D": "D DB 뜻 둘",
         "P": "P 신조어 없음", "U": "U DB에 없는 말", "S": "S 쌓기 문장(쌓인 문장 0)"}
WAYS = ("새 카드", "0.8.0 카드", "옛 카드", "한 번")
A_RIGHT, B_RIGHT, D_RIGHT, C_MAD, U_FIND, QUEUE_U, FAILURES, STACK_GAIN, A_KEEP = \
    0.85, 0.70, 0.75, 0.90, 0.10, 0.80, 0.02, 0.20, 0.10


def tables(records, gold, verdicts):
    """way -> seed -> type -> Counter; records: (way, record)."""
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for w, r in records:
        g = gold[r["case_id"]]
        c = per[w][r["seed"]][g["type"]]
        c["n"] += 1
        c["seconds"] += r["result"].get("elapsed_seconds") or 0
        for it in ((r["result"].get("card") or {}).get("items") or []):
            if it.get("decided_by") == "mad":
                c["reason_" + str(it.get("mad_reason"))] += 1
        if g["type"] in ("U", "S"):
            verdict = verdicts.get((w, r["case_id"], r["seed"]))
            u = unknown_outcome(r, g, verdict)
            c.update({k: int(v) for k, v in u.items()})
            c["failed"] += not u["done"]
            c["correct"] += verdict == "correct"
            continue
        o = outcome(r, g)
        c["right"] += o["right"]
        c["failed"] += not o["done"]
        c["confident_wrong"] += o["confident_wrong"]
        c["mad"] += o["decided_by"] == "mad"
        c["slang_items"] += o["slang_items"] > 0
    return per


def show(per, ways=WAYS):
    for w in ways:
        if w not in per:
            continue
        seeds = sorted(per[w])
        print(f"   [{w}] seed {seeds}")
        for t in TYPES:
            cs = [per[w][s][t] for s in seeds]
            if not cs[0]["n"]:
                continue
            tot = sum(cs, Counter())
            secs = tot["seconds"] / max(1, tot["n"])
            reasons = {k[7:]: v for k, v in sorted(tot.items()) if k.startswith("reason_")}
            if t in ("U", "S"):
                print(f"      {NAMES[t]:<20} n={cs[0]['n']:<3} 찾음 {tot['found']} · 확정처럼 {tot['settled']} · 모름(보류) "
                      f"{tot['uncertain']} · 뜻 맞음 {tot['correct']} (보여 줌 {tot['shown_right']}) · 틀린 뜻 보여 줌 "
                      f"{tot['shown_wrong']} · 표준어로 뺌 {tot['standard']} · MAD {reasons} · 카드 {secs:.0f}초")
            else:
                print(f"      {NAMES[t]:<20} n={cs[0]['n']:<3} 맞음 {spread([c['right'] for c in cs])} · MAD {reasons}"
                      + (f" · 틀린 뜻 확정 {tot['confident_wrong']}" if t == "C" else "") + f" · 카드 {secs:.0f}초")


def select(args):
    gold = {g["case_id"]: g for g in rows(args.gold)}
    out = Path(args.to)
    if out.exists():
        raise SystemExit(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    kept = [s for s in Path(args.source).read_text(encoding="utf-8").splitlines()
            if s.strip() and gold[json.loads(s)["case_id"]]["type"] in args.select
            and (not args.method or json.loads(s)["method"] == args.method)]
    out.write_text("".join(s + "\n" for s in kept), encoding="utf-8")
    print(f"{'·'.join(args.select)} 기록 {len(kept)}개 → {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", required=True)
    p.add_argument("--select", nargs="*")
    p.add_argument("--source")
    p.add_argument("--method")
    p.add_argument("--to")
    p.add_argument("--new")
    p.add_argument("--mid")
    p.add_argument("--old")
    p.add_argument("--graded-new", help="U and S of the new card (card and card_single)")
    p.add_argument("--graded-old", help="U of the old card")
    p.add_argument("--stack", nargs=2, action="append", default=[], metavar=("K", "RUNS"))
    p.add_argument("--graded-stack", nargs=2, action="append", default=[], metavar=("K", "GRADED"),
                   help="S runs with K stored comments, graded (eval/grade.py)")
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
    way = lambda r: "새 카드" if r["method"] == "card" else "한 번"
    records = ([(way(r), r) for r in rows(args.new)] + [("0.8.0 카드", r) for r in rows(args.mid)]
               + [("옛 카드", r) for r in rows(args.old)])
    verdicts = {}
    for name, label in ((args.graded_new, None), (args.graded_old, "옛 카드")):
        for g in rows(name) if name else []:
            verdicts[(label or ("새 카드" if g["method"] == "card" else "한 번"), g["case_id"], g["seed"])] = g["verdict"]
    judge = Path(args.judge_file).read_text(encoding="utf-8").strip() if args.judge_file else "v9"
    print(f"== fresh_v3 · 문장 {len(gold)} · 유형 {dict(Counter(g['type'] for g in gold.values()))} · 판정 역할 {judge}")
    per = tables(records, gold, verdicts)
    show(per)

    # S (쌓기): the new card's S runs with 0 (the main run), 2 and 4 stored comments
    stacks = {0: [r for w, r in records if w == "새 카드" and gold[r["case_id"]]["type"] == "S"]}
    for k, name in args.stack:
        stacks[int(k)] = rows(name)
    stack_verdicts = {}
    for k, name in args.graded_stack:
        for g in rows(name):
            stack_verdicts[(int(k), g["case_id"], g["seed"])] = g["verdict"]
    s_rate = {}
    if any(stacks.values()):
        print("== S 쌓기 (새 카드, 같은 S 문장, 수집기에 쌓인 다른 문장 수)")
        for k in sorted(stacks):
            got = stacks[k]
            vs = [(verdicts.get(("새 카드", r["case_id"], r["seed"])) if k == 0
                   else stack_verdicts.get((k, r["case_id"], r["seed"]))) for r in got]
            outs = [unknown_outcome(r, gold[r["case_id"]], v) for r, v in zip(got, vs)]
            n = len(got)
            correct = sum(v == "correct" for v in vs)
            s_rate[k] = (correct / n if n else None, sum(o["settled"] for o in outs))
            reasons = Counter(it.get("mad_reason") for r in got for it in ((r["result"].get("card") or {}).get("items") or [])
                              if it.get("decided_by") == "mad")
            secs = statistics.mean(r["result"].get("elapsed_seconds") or 0 for r in got) if got else 0
            print(f"   쌓인 문장 {k}: n={n} · 뜻 맞음 {correct} ({correct / n:.0%}) · 찾음 {sum(o['found'] for o in outs)} · "
                  f"모름 {sum(o['uncertain'] for o in outs)} · 확정처럼 {s_rate[k][1]} · 채점 안 됨 {sum(v is None for v in vs)} · "
                  f"MAD {dict(reasons)} · 카드 {secs:.0f}초" if n else f"   쌓인 문장 {k}: 없음")

    table = pick_table([r for name in args.picks for r in rows(name)]) if args.picks else {}
    if table:
        print("== 고르기 (같은 후보, 호출 수: 한 번 1 · 다수결 5 · MAD 5)")
        for (m, v), c in sorted(table.items()):
            print(f"   {m:<7} {v:<12} n={c['n']:<3} 정답 {c['correct']}   유보 {c['abstained']}")
    reg = regress(rows(args.regress_without), rows(args.regress_control), rows(args.regress_with),
                  {g["headword"] for g in gold.values() if g.get("headword")}) \
        if args.regress_without and args.regress_control and args.regress_with else None
    if reg:
        print(f"== 시연 문장 회귀: 신선 행이 끼어든 카드 {reg[0]} · 넣고 바뀐 카드 {len(reg[1])} {reg[1]} · 흔들림 {len(reg[2])} {reg[2]}")
    known = [e["expression"] for name in args.lexicon for e in load_lexicon(name)]
    listed, u_words, in_queue, from_plain = collector([(False, r) for w, r in records if w == "새 카드"], gold, known)
    print(f"== 수집 표 (새 카드): 후보 {len(listed)}개 · U 낱말 {len(in_queue)}/{len(u_words)} 들어감 · P·B 문장에서 온 후보 {from_plain}")
    for q in listed[:15]:
        print(f"      {q['expression']}: 댓글 {q['comments']} · {q['verdicts']}{' · 새 뜻 후보' if q['new_sense'] else ''}"
              f"{' · 확인할 것 ' + ', '.join(q['hints']) if q['hints'] else ''}")

    new, mid, old = (per.get(w, {}) for w in ("새 카드", "0.8.0 카드", "옛 카드"))
    rate = lambda tbl, t: (statistics.mean(tbl[s][t]["right"] / tbl[s][t]["n"] for s in tbl)
                           if tbl and tbl[sorted(tbl)[0]][t]["n"] else None)
    total = lambda tbl, t, k: sum(tbl[s][t][k] for s in tbl)
    runs = sum(new[s][t]["n"] for s in new for t in TYPES)
    failed = sum(new[s][t]["failed"] for s in new for t in TYPES)
    c_n, c_mad = total(new, "C", "n"), total(new, "C", "mad")
    cw_new, cw_old = total(new, "C", "confident_wrong"), total(old, "C", "confident_wrong")
    u_n_new, u_n_old = total(new, "U", "n"), total(old, "U", "n")
    find_new = total(new, "U", "found") / u_n_new if u_n_new else 0
    find_old = total(old, "U", "found") / u_n_old if u_n_old else 0
    pick = lambda m, v, k: table.get((m, v), Counter())[k]
    a, b, d = rate(new, "A"), rate(new, "B"), rate(new, "D")
    a_mid, b_mid = rate(mid, "A"), rate(mid, "B")
    s0, s4 = s_rate.get(0, (None, 0)), s_rate.get(4, (None, 0))
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
        (f"⑪ S 뜻 맞음: 쌓인 문장 4개 {fmt(s4[0])} − 0개 {fmt(s0[0])} (기준 +{STACK_GAIN:.0%}p 이상), 확정처럼 "
         f"{sum(v[1] for v in s_rate.values())} (기준 0)",
         s0[0] is not None and s4[0] is not None and s4[0] - s0[0] >= STACK_GAIN - 1e-9
         and sum(v[1] for v in s_rate.values()) == 0),
        (f"⑫ B 새 카드 {fmt(b)} > 0.8.0 카드 {fmt(b_mid)}, A 새 카드 {fmt(a)} ≥ 0.8.0 카드 {fmt(a_mid)} − {A_KEEP:.0%}p",
         None not in (a, b, a_mid, b_mid) and b > b_mid and a >= a_mid - A_KEEP - 1e-9),
    ]
    print("== 사전 기준 (docs/DESIGN.md)")
    for text, ok in bars:
        print(f"   {text} → {'통과' if ok else '미달'}")
    missed = sum(not ok for _, ok in bars)
    print(f"== 판정: {'기준 모두 통과' if not missed else f'기준 {len(bars)}개 중 {missed}개 미달'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
