#!/usr/bin/env python3
"""fresh_v5 against the commercial AI (docs/DESIGN.md, bars N1-N5 written before the run): the same 18 sentences, every answer judged
by a person with the source hidden. The answers come in at different times (TraceTalk's runs first, the commercial answers when the user
has them), so judging goes in rounds: each round's lists show only the answers no round has judged yet (same sentence, same words =
one mark), the label key stays apart, and the marks build up in data/eval/compare_v5/marks_meaning.json, marks_origin.json.

    python3 eval/fresh5_sheet.py sheet --round 1 --runs full=runs/v13/fresh_v5/full.jsonl single=runs/v13/fresh_v5/single.jsonl
        -> data/eval/compare_v5/judge_meaning_1.txt, judge_origin_1.txt, _blind_key_1.json (not for the judges)
    (judges: judge{1,2}_meaning_1.json, judge{1,2}_origin_1.json, each {no: {label: mark}}; a third on the splits: judge3_*_1.json)
    python3 eval/fresh5_sheet.py merge --round 1        -> the marks, or a list of the splits for the third judge
    python3 eval/fresh5_sheet.py apply --runs ...       -> the comparison and the bars
The commercial answers are data/eval/fresh_v5/answers_alone.txt (web off) and answers_web.txt (web on), `no | 표현 | 뜻 | 유래 | 확신 [| 주소]`.
"""
import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from fresh4_report import rows, target  # noqa: E402
from fresh4_sheet import PLAIN, card_answer, commercial  # noqa: E402
from tracetalk.db.lexicon import compact  # noqa: E402

F, D = ROOT / "data/eval/fresh_v5", ROOT / "data/eval/compare_v5"
COMMERCIAL = {"gemini": F / "answers_alone.txt", "gemini_web": F / "answers_web.txt",
              # docs/DESIGN.md 추가 시험 (11-09): Gemini with search off in AI Studio, and local models alone (eval/ask_local.py)
              "gemini_nosearch": F / "answers_nosearch.txt", "gemini_nosearch_split": F / "answers_nosearch_split.txt",
              "local_4b": F / "answers_local_4b.txt", "local_exaone": F / "answers_local_exaone.txt",
              # 0.11 (_work/v15/NOTES.md 추가 시험 3): Gemini with search off, given what TraceTalk 0.10 found for each comment
              # (eval/ask_with_db.py: the DB's rows and the posts' own text, never the 4B's reading)
              "gemini_db": F / "answers_withdb.txt",
              # 0.11 model comparison (_work/v15/compare_model.sh): Qwen3.5-4B as published (no TraceTalk training), alone
              "local_q4b": F / "answers_local_q4b.txt"}
BLANK = PLAIN + ("모름",)  # no meaning to judge: held, as in fresh_v4 (the registered rule)
RULES_MEANING = """채점 규칙 (뜻)
- 각 번호는 댓글 하나와 그 안의 표현이다. a), b) …는 그 표현이 이 댓글에서 무슨 뜻인지에 대한 답이다.
- '참조'의 뜻을 전하면 o, 아니면 x를 매긴다. 참조의 핵심(무엇을 가리키는 말인지)이 맞으면 덧붙인 말이 조금 있어도 o다.
  덧붙인 말이 뜻을 바꾸거나 틀린 사실을 담으면 x다.
- 표준어 뜻 그대로라고 답했는데 참조가 새 뜻이면 x다.
- 답이 그 댓글 속 다른 표현을 풀이하고 있으면 d를 매긴다.
- 답은 JSON 하나: {"번호": {"a": "o" 또는 "x" 또는 "d", ...}, ..., "_notes": "애매했던 것 짧게"}. 모든 번호의 모든 보기를 매긴다.
"""
RULES_ORIGIN = """채점 규칙 (유래)
- 각 번호의 '글이 말하는 유래'와 같은 출처(같은 사이트·영상·작품·사람·계정)를 대면 o, 다른 출처를 대거나 틀린 사실이면 x를 매긴다.
- 유래 칸이 비어 있어도 뜻 칸이 그 출처를 맞게 대면 o다. 유래도 뜻도 출처를 말하지 않으면(모름 포함) n을 매긴다.
- 답은 JSON 하나: {"번호": {"a": "o" 또는 "x" 또는 "n", ...}, ..., "_notes": "짧게"}. 모든 번호의 모든 보기를 매긴다.
"""
BLOCK = re.compile(r"(?ms)^#(\d+) .*?(?=^#\d+ |\Z)")


def sources(k, gold, runs):
    out = {name: commercial(path)[k["no"]] for name, path in COMMERCIAL.items() if path.exists() and k["no"] in commercial(path)}
    for name, recs in runs.items():
        if k["case_id"] in recs:
            out[name] = card_answer(recs[k["case_id"]], gold)
    return out


def load(specs):
    return {name: {r["case_id"]: r for r in rows(path)} for name, path in (s.split("=", 1) for s in specs)}


def origin_text(a):
    return f"유래: {a['origin'] or '-'} / 뜻: {a['meaning'] or '-'}"


def judged(kind):
    path = D / f"marks_{kind}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def sheets(runs, round_, seed=20261108):
    key, gold = rows(F / "key.jsonl"), {g["case_id"]: g for g in rows(F / "gold.jsonl")}
    rng = random.Random(seed + int(re.sub(r"\D", "", round_) or 0))
    done = {"meaning": judged("meaning"), "origin": judged("origin")}
    lists, blind = {"meaning": [RULES_MEANING], "origin": [RULES_ORIGIN]}, {"meaning": {}, "origin": {}}
    for k in key:
        g, src = gold[k["case_id"]], sources(k, gold[k["case_id"]], runs)
        for kind in ("meaning", "origin"):
            groups = {}
            for name, a in src.items():
                text = a["meaning"] if kind == "meaning" else origin_text(a)
                if (kind == "meaning" and a["meaning"].strip() in BLANK) or compact(text) in done[kind].get(k["case_id"], {}):
                    continue
                groups.setdefault(compact(text), text)
            if not groups:
                continue
            labels = list(groups.items()); rng.shuffle(labels)
            blind[kind][str(k["no"])] = {"case_id": k["case_id"], "labels": {chr(97 + i): c for i, (c, _) in enumerate(labels)}}
            head = (f"#{k['no']} {k['text']}\n   표현: {g['expression']} | 참조: {g['reference_meaning']}\n" if kind == "meaning"
                    else f"#{k['no']} {g['expression']} | 글이 말하는 유래: {g['origin']}\n")
            lists[kind].append(head + "".join(f"   {chr(97 + i)}) {t}\n" for i, (_, t) in enumerate(labels)))
    D.mkdir(parents=True, exist_ok=True)
    for kind in ("meaning", "origin"):
        (D / f"judge_{kind}_{round_}.txt").write_text("\n".join(lists[kind]), encoding="utf-8")
    (D / f"_blind_key_{round_}.json").write_text(json.dumps(blind, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{round_}회: 뜻 {len(lists['meaning']) - 1}문장 보기 {sum(len(v['labels']) for v in blind['meaning'].values())}개, "
          f"유래 {len(lists['origin']) - 1}문장 보기 {sum(len(v['labels']) for v in blind['origin'].values())}개 -> {D}")


def merge(round_):
    blind = json.loads((D / f"_blind_key_{round_}.json").read_text(encoding="utf-8"))
    for kind in ("meaning", "origin"):
        if not blind[kind]:
            continue
        j = [json.loads((D / f"judge{i}_{kind}_{round_}.json").read_text(encoding="utf-8")) for i in (1, 2)]
        third_path = D / f"judge3_{kind}_{round_}.json"
        third = json.loads(third_path.read_text(encoding="utf-8")) if third_path.exists() else None
        marks, split, agree, total = judged(kind), {}, 0, 0
        for no, b in blind[kind].items():
            for label, text in b["labels"].items():
                x, y = j[0][no][label], j[1][no][label]
                total += 1
                if x == y:
                    agree += 1
                    marks.setdefault(b["case_id"], {})[text] = x
                elif third is not None:
                    marks.setdefault(b["case_id"], {})[text] = third[no][label]
                else:
                    split.setdefault(no, []).append(label)
        print(f"{kind}: 두 채점자 일치 {agree}/{total}, 갈림 {sum(map(len, split.values()))}")
        if split and third is None:
            sheet = (D / f"judge_{kind}_{round_}.txt").read_text(encoding="utf-8")
            blocks = {m.group(1): m.group(0) for m in BLOCK.finditer(sheet)}
            rules = RULES_MEANING if kind == "meaning" else RULES_ORIGIN
            (D / f"judge_{kind}_{round_}_dispute.txt").write_text(
                "\n".join([rules] + [blocks[no].rstrip() + f"\n   >> 매길 보기: {', '.join(ls)}\n" for no, ls in split.items()]), encoding="utf-8")
            print("   세 번째 채점자 표 ->", D / f"judge_{kind}_{round_}_dispute.txt")
            continue
        (D / f"marks_{kind}.json").write_text(json.dumps(marks, ensure_ascii=False, indent=0), encoding="utf-8")
        print("   표시 저장 ->", D / f"marks_{kind}.json")


def apply(runs):
    key, gold = rows(F / "key.jsonl"), {g["case_id"]: g for g in rows(F / "gold.jsonl")}
    mm, om = judged("meaning"), judged("origin")
    t, unjudged = {}, Counter()
    for k in key:
        g = gold[k["case_id"]]
        for name, a in sources(k, g, runs).items():
            c = t.setdefault(name, Counter())
            mark = None if a["meaning"].strip() in BLANK else mm.get(k["case_id"], {}).get(compact(a["meaning"]))
            unjudged[name] += a["meaning"].strip() not in BLANK and mark is None
            sure = a["conf"] == "확실"
            c["n"] += 1
            c["맞음" if mark == "o" else "확정 오답" if mark == "x" and sure else "보류"] += 1
            omark = om.get(k["case_id"], {}).get(compact(origin_text(a)))
            c["유래 맞음"] += omark == "o"
            wrote = a["origin"].strip() not in BLANK and "모름" not in a["origin"]
            c["유래 적음"] += wrote
            c["유래 지어냄"] += wrote and omark == "x"
            if name in runs:
                c["찾음"] += target(runs[name][k["case_id"]], g) is not None
                c["초"] += runs[name][k["case_id"]]["result"].get("elapsed_seconds", 0)
                c["최장"] = max(c["최장"], runs[name][k["case_id"]]["result"].get("elapsed_seconds", 0))
    for name, c in t.items():
        extra = f" · 찾음 {c['찾음']}/{c['n']} · 평균 {c['초'] / c['n']:.1f}초 · 최장 {c['최장']:.0f}초" if name in runs else ""
        print(f"{name:<11} 뜻 맞음 {c['맞음']}/{c['n']} · 보류 {c['보류']} · 확정 오답 {c['확정 오답']} · 유래 맞음 {c['유래 맞음']} · 유래 적음 {c['유래 적음']}"
              f" · 그중 틀림 {c['유래 지어냄']}{extra}" + (f" · 아직 안 매긴 뜻 {unjudged[name]}" if unjudged[name] else ""))
    us, them = t.get("full"), t.get("gemini")
    if us and them:
        bars = [("N1 뜻", us["맞음"] > them["맞음"]), ("N2 확정 오답", us["확정 오답"] <= them["확정 오답"]),
                ("N3 유래", us["유래 맞음"] > them["유래 맞음"]), ("N4 지어낸 유래", us["유래 지어냄"] < them["유래 지어냄"]),
                ("N5 감지", us["찾음"] >= 14)]
        print("기준:", " · ".join(f"{n} {'넘음' if ok else '못 넘음'}" for n, ok in bars))
    elif us:
        print(f"기준: N5 감지 {'넘음' if us['찾음'] >= 14 else '못 넘음'} · N1~N4는 Gemini(웹 끔) 답을 받은 뒤")
    locals_ = [t[n] for n in ("local_4b", "local_exaone") if n in t]
    if us and locals_:  # the added comparison: the other choices on the same Mac, and Gemini with search off
        added = [("L1 뜻", all(us["맞음"] > s["맞음"] for s in locals_)), ("L2 확정 오답", all(us["확정 오답"] <= s["확정 오답"] for s in locals_))]
        if "gemini_nosearch" in t:
            added.append(("G1 검색 끈 Gemini 대비 뜻", us["맞음"] > t["gemini_nosearch"]["맞음"]))
        if "gemini_nosearch_split" in t:  # one comment per word in each question: no clue from the other comment
            added.append(("G2 검색 끈 Gemini(나눈 질문) 대비 뜻", us["맞음"] > t["gemini_nosearch_split"]["맞음"]))
        print("추가 기준:", " · ".join(f"{n} {'넘음' if ok else '못 넘음'}" for n, ok in added))
    db, alone, web = t.get("gemini_db"), t.get("gemini_nosearch"), t.get("gemini_web")
    if db and alone:  # 추가 시험 3, written before the answers came: does the DB make the same commercial model better?
        bars = [("D1 유래", db["유래 맞음"] > alone["유래 맞음"]), ("D2 지어낸 유래", db["유래 지어냄"] < alone["유래 지어냄"]),
                ("D3 뜻 잃지 않음", db["맞음"] >= alone["맞음"])]
        if web:
            bars.append(("D4 웹 검색 대비 유래", db["유래 맞음"] >= web["유래 맞음"]))
        print("DB 기준:", " · ".join(f"{n} {'넘음' if ok else '못 넘음'}" for n, ok in bars))
    return t


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("what", choices=["sheet", "merge", "apply"])
    p.add_argument("--runs", nargs="+", default=[])
    p.add_argument("--round", default="1")
    args = p.parse_args(argv)
    if args.what == "merge":
        return merge(args.round)
    runs = load(args.runs)
    return sheets(runs, args.round) if args.what == "sheet" else apply(runs)


if __name__ == "__main__":
    main()
