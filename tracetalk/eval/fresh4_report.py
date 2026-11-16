#!/usr/bin/env python3
"""fresh_v4 (docs/DESIGN.md, bars written before the run; read-only): one card per sentence against data/eval/fresh_v4/gold.jsonl.
Every card falls into 맞음 (right), 보류 (뜻 확인 필요 or an estimate: nothing settled) or 확정 오답 (settled and wrong), and the
stages are counted apart: found, whole span, DB row reached, sentence. A meaning that is not a DB row (read from the posts or stored
comments) is judged by hand in data/eval/fresh_v4/judged.json ({case_id: {method: "o"|"x"}}); until then the report lists it.

    python3 eval/fresh4_report.py --gold data/eval/fresh_v4/gold.jsonl --runs full=FULL.jsonl single=ONE.jsonl noposts=NP.jsonl old=OLD.jsonl
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tracetalk.db.lexicon import compact  # noqa: E402

SHOWN = "ABCDMPUR"
NAMES = {"A": "A DB 뜻 맞음", "B": "B 표준어 쓰임", "C": "C DB 뜻이 틀림(크롤러 오답)", "D": "D 뜻 둘", "M": "M 표현 여럿", "P": "P 신조어 없음", "U": "U DB에 없음",
         "R": "R 글의 실제 문구(문맥 거의 없음)"}


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def with_origins(gold, path=ROOT / "data/eval/fresh_v4r/origin_gold.jsonl"):
    """Where each word comes from, as the fetched posts say: the keywords a card must name to count (only for the sentences that use the word)."""
    origins = {r["word"]: r for r in rows(path)} if Path(path).exists() else {}
    for g in gold.values():
        found = origins.get(g.get("headword") or "")
        if found and g["type"] != "B":
            g.setdefault("origin_keywords", found["keywords"])
        if gold.get(g.get("from"), {}).get("recent"):  # an R line of a word from the recent posts (bar 15)
            g["recent"] = True
    return gold


def target(record, gold):
    text = record["result"]["request"]["text"]
    items = (record["result"].get("card") or {}).get("items") or []
    at = text.find(gold["expression"]) if gold["expression"] else -1
    end = at + len(gold["expression"])
    for it in items:
        if at >= 0 and it.get("start") is not None and it["start"] < end and at < it["end"]:
            return it
    return next((it for it in items if gold.get("headword") and it.get("headword") == gold["headword"]), None)


def judge(record, gold, hand=None):
    """{outcome: 맞음|보류|확정 오답, found, span, reached, sentence, skipped, basis}. Only an item shown as settled can be 확정 오답. A
    meaning that is not a DB row (read from the posts or stored comments, or the writer's words on a new word) is judged by hand:
    hand = "o" or "x" for this card; without a judgement it stays 판정 대기."""
    t, done = gold["type"], record["status"] == "completed"
    card = (record["result"].get("card") or {}) if done else {}
    items = card.get("items") or []
    it = target(record, gold) if done else None
    out = {"done": done, "found": it is not None, "span": False, "reached": False, "skipped": False, "basis": it.get("basis") if it else None,
           "sentence": bool(card.get("sentence")), "seconds": record["result"].get("elapsed_seconds", 0), "check": bool(it and it.get("check_needed"))}
    if it is None:
        out["skipped"] = any(compact(s) == compact(gold["expression"]) for s in card.get("skipped") or []) if gold["expression"] else False
    else:
        out["span"] = compact(gold["expression"]) in compact(it["expression"])
        out["reached"] = bool(it.get("candidates"))
    settled = bool(it) and it.get("status") == "proposed"
    db = settled and it.get("db_meaning") is not None
    same = db and gold.get("sense") is not None and it["db_meaning"].strip() == gold["sense"].strip()
    read = settled and it.get("basis") in ("post", "usage", "model") and it.get("choice") != "L"
    def by_hand():
        return "맞음" if hand == "o" else "확정 오답" if hand == "x" and not it.get("estimate") else "보류" if hand == "x" else "판정 대기"
    if not done:
        out["outcome"] = "보류"
    elif t == "P":
        wrong = [i for i in items if i.get("choice") != "L" and i.get("status") == "proposed" and not i.get("estimate")]
        loud = [i for i in items if i.get("choice") != "L"]
        out["outcome"] = "확정 오답" if wrong else "보류" if loud else "맞음"
    elif t == "B":
        out["outcome"] = ("맞음" if it is None or it.get("choice") == "L" else
                          "확정 오답" if settled and not it.get("estimate") else "보류")
    elif t == "C":  # right = the row's wrong meaning is not settled; a meaning read instead is judged by hand when there is one
        out["outcome"] = "확정 오답" if same else by_hand() if read else "맞음"
    elif t in "ADM":
        out["outcome"] = "맞음" if same else by_hand() if read else "확정 오답" if settled else "보류"
    elif t == "R":  # the word stands almost alone: a DB row is right when it is not the wrong row, anything else by hand
        out["outcome"] = by_hand() if settled and it.get("choice") != "L" else "보류"
    else:  # U: what the card reads for a word the DB lacks; nothing else counts as right
        out["outcome"] = by_hand() if read else "보류"
    named = " ".join(str(it.get(k, "")) for k in ("origin", "meaning", "post_meaning", "db_meaning")) if it else ""
    out["origin_right"] = any(k.lower() in named.lower() for k in (gold.get("origin_keywords") or []))
    return out


def table(name, records, gold, hand):
    per = {t: Counter() for t in SHOWN}
    seconds = {t: [] for t in SHOWN}
    waiting = []
    for r in records:
        g = gold[r["case_id"]]
        o = judge(r, g, hand.get(r["case_id"], {}).get(name))
        c = per[g["type"]]
        c["n"] += 1
        c[o["outcome"]] += 1
        for k in ("found", "span", "reached", "sentence", "skipped", "check"):
            c[k] += bool(o[k])
        seconds[g["type"]].append(o["seconds"])
        c["recent_n"] += bool(g.get("recent"))
        c["recent_right"] += bool(g.get("recent")) and o["outcome"] == "맞음"
        if g.get("origin_keywords"):
            c["origin_n"] += 1
            c["origin_right"] += o["origin_right"]
        if g["type"] == "U":
            kind = "nopost" if g.get("no_post") else "phrase" if g.get("note") == "구절" else "word"
            c[kind + "_n"] += 1
            c[kind + "_found"] += o["found"] and o["span"]
            c[kind + "_right"] += o["outcome"] == "맞음"
        if g["type"] == "C":
            kind = "nopost" if g.get("no_post") else "post"
            c[kind + "_n"] += 1
            c[kind + "_wrong"] += o["outcome"] == "확정 오답"
        if o["outcome"] == "판정 대기":
            it = target(r, g)
            waiting.append((r["case_id"], g["type"], g["expression"], it.get("meaning", "") if it else "", g.get("reference_meaning") or g.get("note") or g.get("sense") or ""))
    print(f"== {name} ({len(records)}장)")
    for t in SHOWN:
        c = per[t]
        if not c["n"]:
            continue
        extra = f" · 찾음 {c['found']} · 범위 다 맞음 {c['span']}" if t in "ADMU" else ""
        extra += f" · 넘쳐서 표시 {c['skipped']}" if t == "M" else ""
        extra += f" · 판정 대기 {c['판정 대기']}" if c["판정 대기"] else ""
        print(f"   {NAMES[t]:<24} n={c['n']:<3} 맞음 {c['맞음']:<3} 보류 {c['보류']:<3} 확정 오답 {c['확정 오답']:<3}{extra} · 평균 {statistics.mean(seconds[t] or [0]):.0f}초")
    u, cc = per["U"], per["C"]
    print(f"   U 나눠 보기: 글 있는 낱말 찾음 {u['word_found']}/{u['word_n']} 맞음 {u['word_right']} · 글 있는 구절 찾음 {u['phrase_found']}/{u['phrase_n']} 맞음 {u['phrase_right']}"
          f" · 글 없는 말 찾음 {u['nopost_found']}/{u['nopost_n']} 맞음 {u['nopost_right']}")
    print(f"   C 나눠 보기: 글 있는 틀린 뜻 확정 오답 {cc['post_wrong']}/{cc['post_n']} · 글 없는 틀린 뜻 확정 오답 {cc['nopost_wrong']}/{cc['nopost_n']}")
    print(f"   유래까지 맞음: {sum(c['origin_right'] for c in per.values())}/{sum(c['origin_n'] for c in per.values())}")
    every = [s for v in seconds.values() for s in v]
    settled_wrong = sum(c["확정 오답"] for c in per.values())
    right = sum(per[t]["맞음"] for t in SHOWN)
    total = sum(per[t]["n"] for t in SHOWN)
    print(f"   합 맞음 {right}/{total} = {right / max(1, total):.0%} · 보류 {sum(c['보류'] for c in per.values())} · 확정 오답 {settled_wrong} · 최신 낱말 맞음 "
          f"{sum(c['recent_right'] for c in per.values())}/{sum(c['recent_n'] for c in per.values())} · 끝나지 않음 {sum(not judge(r, gold[r['case_id']])['done'] for r in records)}"
          f" · 카드 평균 {statistics.mean(every or [0]):.0f}초 · 가장 김 {max(every or [0]):.0f}초")
    return per, every, waiting


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gold", nargs="+", default=[str(ROOT / "data/eval/fresh_v4/gold.jsonl"), str(ROOT / "data/eval/fresh_v4r/gold.jsonl")])
    p.add_argument("--runs", nargs="+", required=True, help="이름=결과파일 (예: full=runs/.../full.jsonl)")
    p.add_argument("--hand", default=str(ROOT / "data/eval/fresh_v4/judged.json"))
    args = p.parse_args(argv)
    gold = with_origins({g["case_id"]: g for path in args.gold for g in rows(path)})
    hand = json.loads(Path(args.hand).read_text(encoding="utf-8")) if Path(args.hand).exists() else {}
    out, waiting = {}, {}
    for spec in args.runs:
        name, path = spec.split("=", 1)
        per, every, wait = table(name, rows(path), gold, hand)
        out[name] = (per, every)
        waiting[name] = wait
    for name, wait in waiting.items():
        if wait:
            print(f"== 판정 대기 ({name}): {args.hand} 에 {{\"사례\": {{\"{name}\": \"o\"|\"x\"}}}}")
            for case, t, expr, meaning, ref in wait:
                print(f"   {case} {t} [{expr}] 카드: {meaning[:70]} | 참조: {ref[:60]}")
    return out


if __name__ == "__main__":
    main()
