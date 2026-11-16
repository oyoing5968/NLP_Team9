#!/usr/bin/env python3
"""fresh_v4 (118 sentences) with answers that came after its compare_v3 judging (docs/DESIGN.md 추가 시험: local models alone):
the same blind rules, in rounds, only the answers no judging has marked yet (the compare_v3 marks are where it starts; the same
sentence with the same words keeps its mark).

    python3 eval/fresh4_more.py sheet --round 1 --answers local_4b=data/eval/compare_v3/answers_local_4b.txt local_exaone=...
        -> data/eval/compare_v3/judge_more_meaning_1.txt, judge_more_origin_1.txt, _blind_key_more_1.json (not for the judges)
    python3 eval/fresh4_more.py merge --round 1      (judge{1,2}_more_{meaning,origin}_1.json, a third on the splits)
    python3 eval/fresh4_more.py apply --answers ...
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
from fresh4_report import rows, with_origins  # noqa: E402
from fresh4_sheet import GOLD, PLAIN, commercial, orig_of  # noqa: E402
from fresh5_sheet import RULES_ORIGIN, origin_text  # noqa: E402
from tracetalk.db.lexicon import compact  # noqa: E402

D = ROOT / "data/eval/compare_v3"
BLANK = PLAIN + ("모름",)
RULES_MEANING = """채점 규칙 (뜻)
- 각 번호는 댓글 하나와 그 안의 표현이다. a), b) …는 그 표현이 이 댓글에서 무슨 뜻인지에 대한 답이다.
- '참조'의 뜻을 전하면 o, 아니면 x를 매긴다. 참조가 '/'로 여럿이면 그 가운데 하나를 전하면 o다.
- 참조가 '신조어가 아니다(표준어·이름·글자 그대로)'이면, 답이 신조어·밈의 뜻을 말하면 x, 표준어 뜻 그대로라고 말하면 o다.
- 답이 그 댓글 속 다른 표현을 풀이하고 있으면 d를 매긴다.
- 참조의 뜻을 담고 있으면 덧붙인 말이 조금 있어도 o다. 덧붙인 말이 뜻을 바꾸거나 틀린 사실을 담으면 x다.
- 답은 JSON 하나: {"번호": {"a": "o" 또는 "x" 또는 "d", ...}, ..., "_notes": "애매했던 것 짧게"}. 모든 번호의 모든 보기를 매긴다.
"""
BLOCK = re.compile(r"(?ms)^#(\d+) .*?(?=^#\d+ |\Z)")
LABEL = re.compile(r"^   ([a-z])\) (.*)$", re.M)


def gold():
    return with_origins({g["case_id"]: g for path in GOLD for g in rows(path)})


def reference(g):
    if g["type"] == "C":
        return re.sub(r"^실제:\s*", "", g["note"].split(" · ")[0])
    if g["type"] in ("B", "P"):
        return "신조어가 아니다(표준어·이름·글자 그대로)" + (f" / DB 뜻: {g['sense']}" if g.get("sense") else "")
    return g.get("reference_meaning") or g.get("sense") or g.get("note") or ""


def marks(kind):
    """{case_id: {compact(text): mark}}: the compare_v3 judging, then every round here."""
    key = {str(k["no"]): k["case_id"] for k in rows(D / "key.jsonl")}
    judged = json.loads((D / f"judged_{kind}.json").read_text(encoding="utf-8"))
    out = {}
    for block in BLOCK.finditer((D / f"judge_{kind}.txt").read_text(encoding="utf-8")):
        no = block.group(1)
        for m in LABEL.finditer(block.group(0)):
            if m.group(1) in judged.get(no, {}):
                out.setdefault(key[no], {})[compact(m.group(2))] = judged[no][m.group(1)]
    more = D / f"marks_more_{kind}.json"
    for case, by_text in (json.loads(more.read_text(encoding="utf-8")) if more.exists() else {}).items():
        out.setdefault(case, {}).update(by_text)
    return out


def answers(specs):
    return {name: commercial(path) for name, path in (s.split("=", 1) for s in specs)}


def sheet(specs, round_, seed=20261109):
    sources, g, done = answers(specs), gold(), {"meaning": marks("meaning"), "origin": marks("origin")}
    rng = random.Random(seed + int(round_))
    lists, blind = {"meaning": [RULES_MEANING], "origin": [RULES_ORIGIN]}, {"meaning": {}, "origin": {}}
    for k in rows(D / "key.jsonl"):
        c, no = g[k["case_id"]], k["no"]
        for kind in ("meaning", "origin"):
            if kind == "origin" and not c.get("origin_keywords"):
                continue
            groups = {}
            for name, by_no in sources.items():
                a = by_no.get(no)
                if not a:
                    continue
                text = a["meaning"] if kind == "meaning" else origin_text(a)
                if (kind == "meaning" and a["meaning"].strip() in BLANK) or compact(text) in done[kind].get(k["case_id"], {}):
                    continue
                groups.setdefault(compact(text), text)
            if not groups:
                continue
            labels = list(groups.items()); rng.shuffle(labels)
            blind[kind][str(no)] = {"case_id": k["case_id"], "labels": {chr(97 + i): t for i, (t, _) in enumerate(labels)}}
            head = (f"#{no} [{c['type']}] {k['text']}\n   표현: {c.get('expression') or '(없음)'} | 참조: {reference(c)}\n" if kind == "meaning"
                    else f"#{no} {c['expression']} | 글이 말하는 유래: {c.get('origin') or orig_of(c)}\n")
            lists[kind].append(head + "".join(f"   {chr(97 + i)}) {t}\n" for i, (_, t) in enumerate(labels)))
    for kind in ("meaning", "origin"):
        (D / f"judge_more_{kind}_{round_}.txt").write_text("\n".join(lists[kind]), encoding="utf-8")
    (D / f"_blind_key_more_{round_}.json").write_text(json.dumps(blind, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{round_}회: 뜻 {len(lists['meaning']) - 1}문장 보기 {sum(len(v['labels']) for v in blind['meaning'].values())}개, "
          f"유래 {len(lists['origin']) - 1}문장 보기 {sum(len(v['labels']) for v in blind['origin'].values())}개 -> {D}")


def merge(round_):
    blind = json.loads((D / f"_blind_key_more_{round_}.json").read_text(encoding="utf-8"))
    for kind in ("meaning", "origin"):
        if not blind[kind]:
            continue
        j = [json.loads((D / f"judge{i}_more_{kind}_{round_}.json").read_text(encoding="utf-8")) for i in (1, 2)]
        third_path = D / f"judge3_more_{kind}_{round_}.json"
        third = json.loads(third_path.read_text(encoding="utf-8")) if third_path.exists() else None
        path = D / f"marks_more_{kind}.json"
        new = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        split, agree, total = {}, 0, 0
        for no, b in blind[kind].items():
            for label, text in b["labels"].items():
                x, y = j[0][no][label], j[1][no][label]
                total += 1
                if x == y:
                    agree += 1
                    new.setdefault(b["case_id"], {})[text] = x
                elif third is not None:
                    new.setdefault(b["case_id"], {})[text] = third[no][label]
                else:
                    split.setdefault(no, []).append(label)
        print(f"{kind}: 두 채점자 일치 {agree}/{total}, 갈림 {sum(map(len, split.values()))}")
        if split and third is None:
            text = (D / f"judge_more_{kind}_{round_}.txt").read_text(encoding="utf-8")
            blocks = {m.group(1): m.group(0) for m in BLOCK.finditer(text)}
            rules = RULES_MEANING if kind == "meaning" else RULES_ORIGIN
            (D / f"judge_more_{kind}_{round_}_dispute.txt").write_text(
                "\n".join([rules] + [blocks[no].rstrip() + f"\n   >> 매길 보기: {', '.join(ls)}\n" for no, ls in split.items()]), encoding="utf-8")
            print("   세 번째 채점자 표 ->", D / f"judge_more_{kind}_{round_}_dispute.txt")
            continue
        path.write_text(json.dumps(new, ensure_ascii=False, indent=0), encoding="utf-8")
        print("   표시 저장 ->", path)


def apply(specs):
    sources, g, mm, om = answers(specs), gold(), marks("meaning"), marks("origin")
    t = {}
    for k in rows(D / "key.jsonl"):
        c = g[k["case_id"]]
        for name, by_no in sources.items():
            a = by_no.get(k["no"])
            if not a:
                continue
            s = t.setdefault(name, Counter())
            mark = None if a["meaning"].strip() in BLANK else mm.get(k["case_id"], {}).get(compact(a["meaning"]))
            s["미판정"] += a["meaning"].strip() not in BLANK and mark is None
            plain = a["meaning"].strip() in PLAIN or a["expr"] == "없음"
            sure = a["conf"] == "확실"
            if c["type"] in ("B", "P"):
                out = "맞음" if plain or mark == "o" else "확정 오답" if mark == "x" and sure else "보류"
            else:
                out = "맞음" if mark == "o" else "확정 오답" if mark == "x" and sure else "보류"
            s["n"] += 1
            s[out] += 1
            if c.get("origin_keywords"):
                omark = om.get(k["case_id"], {}).get(compact(origin_text(a)))
                wrote = a["origin"].strip() not in BLANK and "모름" not in a["origin"]
                s["유래 n"] += 1
                s["유래 맞음"] += omark == "o"
                s["유래 적음"] += wrote
                s["유래 지어냄"] += wrote and omark == "x"
    for name, s in t.items():
        print(f"{name:<14} 뜻 맞음 {s['맞음']}/{s['n']} · 보류 {s['보류']} · 확정 오답 {s['확정 오답']} · 유래 맞음 {s['유래 맞음']}/{s['유래 n']}"
              f" · 유래 적음 {s['유래 적음']} 그중 틀림 {s['유래 지어냄']}" + (f" · 아직 안 매긴 뜻 {s['미판정']}" if s["미판정"] else ""))
    locals_ = [s for name, s in t.items() if name.startswith("local")]
    if locals_:  # TraceTalk 0.9 on this set: 73 right, 13 confidently wrong (docs/DESIGN.md)
        print("기준: L3 뜻", "넘음" if all(73 > s["맞음"] for s in locals_) else "못 넘음",
              "· L4 확정 오답", "넘음" if all(13 <= s["확정 오답"] for s in locals_) else "못 넘음")
    return t


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("what", choices=["sheet", "merge", "apply"])
    p.add_argument("--answers", nargs="+", default=[])
    p.add_argument("--round", default="1")
    args = p.parse_args(argv)
    return merge(args.round) if args.what == "merge" else sheet(args.answers, args.round) if args.what == "sheet" else apply(args.answers)


if __name__ == "__main__":
    main()
