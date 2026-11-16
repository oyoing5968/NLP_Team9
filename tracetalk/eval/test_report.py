#!/usr/bin/env python3
"""Final test numbers (11-05, read-only): the test split, one model, card (and card_single beside it), several seeds,
graded once.

Per method, seed and stratum: meaning correct / partial, sentence ok, end to end (as card_report.py); the mean and the
range over seeds; then the success bars written down before the run (docs/DESIGN.md, 최종 시험), on card only:
  registered meaning   mean over seeds >= 85%
  failures             runs not completed <= 2% of all card runs
  plain                no plain comment read as slang
With card_single in the file: MAD (card) beside the single decision on the same cases and seeds, with no bar.
Numbers only: no sentence is printed.

    python3 eval/test_report.py --runs runs/v9.6/test_v1/test.jsonl --graded runs/v9.6/test_v1/graded_test.jsonl
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

REGISTERED_MEANING = 0.85
FAILURES = 0.02
STRATA = ("all", "registered", "unregistered", "plain")
METHODS = ("card", "card_single")
NAMES = {"card": "card (MAD, 시연 방식)", "card_single": "card_single (한 번에 고르기)"}


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def scores(g):
    meaning = g["verdict"] == "correct"
    return {"meaning": meaning, "e2e": meaning and (g.get("sentence") == "yes" or g["stratum"] == "plain")}


def count(records, graded):
    """method -> seed -> stratum -> Counter."""
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for r in records:
        g = graded[(r["case_id"], r["seed"], r["method"])]
        for key in ("all", g["stratum"]):
            c = per[r["method"]][r["seed"]][key]
            c["n"] += 1
            c["correct"] += g["verdict"] == "correct"
            c["partial"] += g["verdict"] == "partial"
            c["sentence"] += g.get("sentence") == "yes"
            c["e2e"] += scores(g)["e2e"]
            c["failed"] += r["status"] != "completed"
            c["judge_error"] += g["verdict"] == "judge_error"
            if g["verdict"] in ("wrong", "partial"):
                c["wrong"] += 1
                c["marked"] += g.get("basis") in ("usage", "model")
                c["settled"] += g.get("basis") in ("db", "literal")
    return per


def spread(values):
    return f"평균 {statistics.mean(values):.1f} (범위 {min(values)}~{max(values)})"


def show(method, by_seed):
    seeds = sorted(by_seed)
    print(f"== {NAMES[method]} · seed {seeds}")
    for seed in seeds:
        print(f"   [seed {seed}]")
        for key in STRATA:
            c = by_seed[seed][key]
            print(f"      {key:<12} n={c['n']:<3} 뜻 정답 {c['correct']:<3} 부분 {c['partial']:<3} 문장 OK {c['sentence']:<3} "
                  f"끝까지 OK {c['e2e']:<3} 실패 {c['failed']} 판정 오류 {c['judge_error']}")
    print(f"   seed {len(seeds)}번의 평균과 범위")
    for key in STRATA:
        print(f"      {key:<12} n={by_seed[seeds[0]][key]['n']:<3} 뜻 정답 {spread([by_seed[s][key]['correct'] for s in seeds])} · "
              f"문장 OK {spread([by_seed[s][key]['sentence'] for s in seeds])} · "
              f"끝까지 OK {spread([by_seed[s][key]['e2e'] for s in seeds])}")
    total = {k: sum(by_seed[s]["all"][k] for s in seeds) for k in ("wrong", "marked", "settled")}
    print(f"   틀린·부분 뜻 {total['wrong']} 가운데 '추정'으로 표시 {total['marked']} · 확정처럼 보임 {total['settled']}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", required=True)
    p.add_argument("--graded", required=True)
    args = p.parse_args(argv)
    records, graded = rows(args.runs), {(g["case_id"], g["seed"], g["method"]): g for g in rows(args.graded)}
    models = {r["result"]["model_config"]["model"] for r in records}
    methods = {r["method"] for r in records}
    if len(models) != 1 or "card" not in methods or not methods <= set(METHODS):
        p.error(f"모델 하나, card(와 card_single)만 받습니다: 모델 {sorted(models)} 방식 {sorted(methods)}")
    missing = sum((r["case_id"], r["seed"], r["method"]) not in graded for r in records)
    if missing:
        p.error(f"채점이 없는 실행이 {missing}개 있습니다.")
    per = count(records, graded)
    print(f"== 최종 시험(test split) · {models.pop()} · 실행 {len(records)} · "
          f"상태 {dict(Counter((r['method'], r['status']) for r in records))}")
    sizes = {(m, s): per[m][s]["all"]["n"] for m in per for s in per[m]}
    if len(set(sizes.values())) != 1:
        print(f"   주의: 방식·seed마다 장 수가 다릅니다 {sizes}")
    for method in METHODS:
        if method in per:
            show(method, per[method])

    card = per["card"]
    seeds = sorted(card)
    runs = sum(card[s]["all"]["n"] for s in seeds)
    registered = statistics.mean(card[s]["registered"]["correct"] / card[s]["registered"]["n"] for s in seeds)
    failed = sum(card[s]["all"]["failed"] for s in seeds)
    plain_n = sum(card[s]["plain"]["n"] for s in seeds)
    plain_misread = sum(card[s]["plain"]["wrong"] for s in seeds)  # a judge error is shown above, not counted here
    bars = [(f"① 등록어 뜻 평균 {registered:.1%} (기준 {REGISTERED_MEANING:.0%} 이상)", registered >= REGISTERED_MEANING),
            (f"② 끝나지 않은 실행 {failed}/{runs} = {failed / runs:.1%} (기준 {FAILURES:.0%} 이하)", failed / runs <= FAILURES),
            (f"③ 평문을 신조어로 읽음 {plain_misread}/{plain_n} (기준 0)", plain_n > 0 and plain_misread == 0)]
    print("== 사전 성공 기준 (card만; docs/DESIGN.md 최종 시험)")
    for text, ok in bars:
        print(f"   {text} → {'통과' if ok else '미달'}")
    missed = sum(not ok for _, ok in bars)
    print(f"== 판정: {'기준 3개 모두 통과' if not missed else f'기준 3개 중 {missed}개 미달'}")

    if "card_single" in per:  # same cases and seeds, no bar
        print("== MAD(card) 대 한 번에 고르기(card_single): 같은 문제·같은 seed 짝 비교 (기준 없음)")
        pairs = defaultdict(lambda: Counter())
        for (case, seed, method), g in graded.items():
            other = graded.get((case, seed, "card_single"))
            if method != "card" or other is None:
                continue
            a, b = scores(g), scores(other)
            for key in ("all", g["stratum"]):
                for name in ("meaning", "e2e"):
                    pairs[key][f"{name}_mad"] += a[name] and not b[name]
                    pairs[key][f"{name}_single"] += b[name] and not a[name]
        for key in STRATA:
            c = pairs[key]
            print(f"   {key:<12} 뜻: MAD만 맞음 {c['meaning_mad']} · 한 번만 맞음 {c['meaning_single']}   "
                  f"끝까지: MAD만 {c['e2e_mad']} · 한 번만 {c['e2e_single']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
