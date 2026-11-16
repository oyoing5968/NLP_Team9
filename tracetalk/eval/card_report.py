#!/usr/bin/env python3
"""Summary of 0.7 card runs (read-only): how cards were made and, with graded files, how good they were.

Per model x method x file:
  status       completed / partial (an expression failed) / failed / timed_out
  items        expressions per card; decided_by (single / mad / guess); basis (db / usage / literal / model)
  sentence     cards with a plain-language sentence, and why the others have none
  calls        average calls per card; retried calls by reason (Han/Kana, unknown candidate, empty, cut off, form)
With --graded (grade.py --rubric koneo for KoNeoBench):
  meaning      correct / partial among all runs (failures stay in the denominator)
  sentence ok  judge said the sentence is natural and keeps the meaning
  end to end   meaning correct AND (sentence ok, or a plain comment left as it is)
  6-3-1        KoNeoBench-style definition score (re-implemented rubric, local judge: indicative only)
  wrong shown  v9.5: wrong or partial meanings shown as settled (a DB or literal basis) vs marked as estimates
Examples are printed only for files whose name has no "kn"/"koneo": KoNeoBench text is never printed.

    python3 eval/card_report.py --runs runs/v9/*.jsonl --graded runs/v9/graded_*.jsonl
"""
import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def reason(error):
    error = error or ""
    for key, label in (("한국어가 아닌", "한자·가나"), ("주어지지 않은 후보", "없는 후보"), ("비어 있습니다", "빈 칸"),
                       ("잘렸습니다", "잘림"), ("근거 용례", "근거 용례 없음"), ("용례에 없는 번호", "없는 용례"),
                       ("쉬운 표현이 필요", "쉬운 표현 없음"), ("쉬운 표현", "쉬운 표현 검사")):
        if key in error:
            return label
    return "형식" if error else "-"


def private(name):
    return any(tag in Path(name).name for tag in ("kn", "koneo"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--graded", nargs="*", default=[])
    p.add_argument("--examples", type=int, default=3)
    args = p.parse_args(argv)
    graded = {}
    for name in args.graded:
        for g in rows(name):
            graded[(g["case_id"], g["seed"], g["method"], g["model"])] = g
    for name in args.runs:
        groups = defaultdict(list)
        for r in rows(name):
            if r["method"].startswith("card"):
                groups[(r["result"]["model_config"]["model"], r["method"])].append(r)
        for (model, method), records in sorted(groups.items()):
            status, decided, basis, item_status, why_no_sentence, retried, by, easy_src = (Counter() for _ in range(8))
            easy_rewritten, ordinary, long_spans = 0, 0, 0
            n_items, n_calls, dropped, sentences, plain = [], [], 0, 0, 0
            for r in records:
                res = r["result"]
                status[r["status"]] += 1
                n_calls.append(res["metrics"]["call_count"])
                for c in res.get("calls", []):
                    if c.get("stage") != "probe" and not c["valid"]:
                        retried[reason(c.get("error"))] += 1
                    dropped += (c.get("analysis") or {}).get("dropped_clues", 0)
                card = res.get("card")
                if not card:
                    continue
                plain += card["plain"]
                n_items.append(len(card["items"]))
                by[card.get("sentence_by")] += 1
                ordinary += len((res.get("detection") or {}).get("ordinary_words", []))
                long_spans += (res.get("detection") or {}).get("long_model_spans", 0)
                for it in card["items"]:
                    item_status[it["status"]] += 1
                    if it["status"] != "failed":
                        decided[it["decided_by"]] += 1
                        basis[it["basis"]] += 1
                        easy_rewritten += bool((it.get("detail") or {}).get("easy_fit", {}).get("rewritten"))
                        if it.get("easy", "").strip():
                            easy_src[it.get("easy_source", "-")] += 1
                if card["sentence"]:
                    sentences += 1
                else:
                    for problem in card["sentence_problems"] or ["(이유 없음)"]:
                        # the quoted expression is hidden (KoNeoBench words stay out); "'…'가 풀리지 않고" stays readable
                        why_no_sentence[re.sub(r"'[^']*'", "'…'", problem)[:24]] += 1
            print(f"== {Path(name).name} · {model} · {method}: n={len(records)} 상태 {dict(status)}")
            print(f"    표현 수/카드 평균 {statistics.mean(n_items) if n_items else 0:.2f} · 평문 카드 {plain} · "
                  f"결정 {dict(decided)} · 근거 {dict(basis)} · 표현 상태 {dict(item_status)}")
            print(f"    문장 해석 있음 {sentences}/{len(records)} · 없는 이유 {dict(why_no_sentence.most_common(4))}")
            print(f"    호출/카드 평균 {statistics.mean(n_calls) if n_calls else 0:.1f} · 다시 물은 호출 {dict(retried)} · "
                  f"원문에 없어 버린 단서 {dropped}")
            print(f"    문장을 쓴 쪽 {dict(by)} · 쉬운 말 다시 씀 {easy_rewritten} · 일반 낱말로 뺌 {ordinary} · "
                  f"긴 탐지 구절 건너뜀 {long_spans} · 쉬운 말 출처 {dict(easy_src)}")
            joined = [graded.get((r["case_id"], r["seed"], r["method"], model)) for r in records]
            joined = [g for g in joined if g]
            if joined:
                by = defaultdict(Counter)
                rubric = defaultdict(list)
                for g in joined:
                    for key in ("all", g["stratum"]):
                        c = by[key]
                        c["n"] += 1
                        c["correct"] += g["verdict"] == "correct"
                        c["partial"] += g["verdict"] == "partial"
                        c["sentence"] += g.get("sentence") == "yes"
                        c["e2e"] += g["verdict"] == "correct" and (g.get("sentence") == "yes" or g["stratum"] == "plain")
                        if (g.get("rubric") or {}).get("total") is not None:
                            rubric[key].append(g["rubric"]["total"])
                wrong = [g for g in joined if g["verdict"] in ("wrong", "partial")]
                settled = sum(g.get("basis") in ("db", "literal") for g in wrong)
                marked = sum(g.get("basis") in ("usage", "model") for g in wrong)
                print(f"    틀린·부분 뜻 {len(wrong)} 가운데 확정처럼 보인 것 {settled} · 추정 표시 {marked} · "
                      f"표현 못 찾음 {len(wrong) - settled - marked}")
                for key in ["all"] + sorted(k for k in by if k != "all"):
                    c = by[key]
                    extra = f" · 6-3-1 평균 {statistics.mean(rubric[key]):.2f}/10 (n={len(rubric[key])})" if rubric[key] else ""
                    print(f"    [{key:<12}] n={c['n']:<4} 뜻 정답 {c['correct']:<4}({c['correct'] / c['n']:.3f}) 부분 {c['partial']:<3} "
                          f"문장 OK {c['sentence']:<4} 끝까지 OK {c['e2e']:<4}({c['e2e'] / c['n']:.3f}){extra}")
            if private(name) or not args.examples:
                continue
            for r in [r for r in records if r["result"].get("card")][:args.examples]:
                card = r["result"]["card"]
                print(f"    예) {r['result']['request']['text'][:70]}")
                for it in card["items"]:
                    if it["status"] == "failed":
                        print(f"        {it['expression']}: 실패 · {it['error'][:80]}")
                    else:
                        print(f"        {it['expression']} [{it['decided_by']}/{it['basis']}/{it['status']}] "
                              f"{it['meaning'][:60]} → {it['easy']}{' (초안)' if it.get('easy_source') == 'draft' else ''}")
                print(f"        문장 해석: {card['sentence']}")
    return 0


if __name__ == "__main__":
    main()
