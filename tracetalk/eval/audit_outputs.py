#!/usr/bin/env python3
"""What the judge did not grade: the whole output a person sees (read-only, result files).

grade.py only asks whether the main interpretation matches the reference meaning of one target
expression. This audit checks the rest of the answer, per model x method:
  target    the gold expression is among the detected expressions (plain: nothing detected)
  foreign   Han or Kana characters in interpretation / nuance / alternatives / uncertainty / easy words
  no_easy   a proposed answer with no rewritten comment
  glue      easy words ending in a sentence ending while the comment continues right after the span
            ("멈춰서 보존해달라" + "해주세요")
  defn      easy words that read like a definition (long, or 과정·호칭·표현·의미·뜻·상태·행위·단어)
  e2e       graded correct AND target AND not foreign AND (plain or a rewrite without glue/defn)
Also: routed route x verdict, dictionary routes that used another family's entry while the target had
evidence, KoNeoBench failure reasons (counts only, KoNeoBench text is never printed), the SFT data
(stages, plain share, foreign share, flagged easy words) and the teacher's graded verdicts.

    python3 eval/audit_outputs.py lab_results/1103/extracted
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracetalk.db.lexicon import compact  # noqa: E402

FOREIGN = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
DEFN = ("과정", "호칭", "표현", "의미", "뜻", "상태", "행위", "단어")
ENDINGS = tuple("다요라까네죠음함임")
VAL = [("runs/r2/student_v05_t035.jsonl", "runs/r2/graded_val_gemma4.jsonl"),
       ("runs/r4/student_v1_methods_t035.jsonl", "runs/r4/graded_val_gemma4.jsonl")]
KONEO = [("runs/r2/student_koneo_t035.jsonl", "runs/r2/graded_koneo_gemma4.jsonl"),
         ("runs/r4/student_v1_koneo_t035.jsonl", "runs/r4/graded_koneo_gemma4.jsonl")]


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def easy_flags(text, span):
    easy, after = span["easy"].strip(), text[span["end"]:span["end"] + 1]
    flags = set()
    if after and "가" <= after <= "힣" and easy.rstrip(".!?~ ").endswith(ENDINGS):
        flags.add("glue")
    if len(easy) > max(12, 3 * len(span["expression"])) or any(w in easy for w in DEFN):
        flags.add("defn")
    return flags


def foreign(analysis, rewrite):
    parts = [analysis.get(k) or "" for k in ("interpretation", "nuance", "uncertainty")]
    parts += analysis.get("alternatives") or []
    parts += [s["easy"] for s in (rewrite or {}).get("spans", [])]
    return bool(FOREIGN.search(" ".join(parts)))


def check(record, gold):
    """Flags for one run; None fields when the run failed."""
    result = record["result"]
    out = {"completed": record["status"] == "completed"}
    if not out["completed"]:
        return out
    a, rw, text = result["analysis"], result.get("rewrite") or {}, result["request"]["text"]
    detected = [compact(e) for e in a["expressions"]]
    target = compact(gold["expression"])
    if gold["stratum"] == "plain":
        out["target"] = not detected
    else:
        out["target"] = any(target and (target in d or d in target) for d in detected if d)
    out["foreign"] = foreign(a, rw)
    flags = set()
    for span in rw.get("spans", []):
        flags |= easy_flags(text, span)
    out["glue"], out["defn"] = "glue" in flags, "defn" in flags
    out["no_easy"] = a["status"] == "proposed" and gold["stratum"] != "plain" and not rw.get("text")
    out["rewrite_ok"] = gold["stratum"] == "plain" or (bool(rw.get("text")) and not flags)
    return out


def audit_val(base, show):
    gold = {g["case_id"]: g for g in rows(ROOT / "data/eval/eval_v1/val_gold.jsonl")}
    family = {e["id"]: e["family"] for e in rows(ROOT / "data/db/lexicon/lexicon_eval_v1.jsonl")}
    print("== validation: 채점이 보지 않은 부분 (수 / n)")
    print(f"    {'model':<22} {'method':<13} {'n':>3} {'완료':>4} {'정답':>4} {'대상탐지':>6} {'외국어':>5} "
          f"{'바꾼문장없음':>8} {'어미충돌':>6} {'뜻풀이식':>6} {'끝까지OK':>7}")
    examples = defaultdict(list)
    for runs, graded in VAL:
        if not (base / runs).exists():
            print("    (없음)", runs)
            continue
        verdict = {(g["case_id"], g["seed"], g["method"], g["model"]): g["verdict"] for g in rows(base / graded)}
        table, routes, wrong_entry = defaultdict(Counter), Counter(), Counter()
        for record in rows(base / runs):
            result, g = record["result"], gold[record["case_id"]]
            model = result["model_config"]["model"]
            f = check(record, g)
            ok = verdict.get((record["case_id"], record["seed"], record["method"], model)) == "correct"
            c = table[(model, record["method"])]
            c["n"] += 1
            c["completed"] += f["completed"]
            c["correct"] += ok
            if f["completed"]:
                for k in ("target", "foreign", "no_easy", "glue", "defn"):
                    c[k] += f[k]
                e2e = ok and f["target"] and not f["foreign"] and f["rewrite_ok"]
                c["e2e"] += e2e
                for k in ("glue", "defn", "foreign"):
                    if f[k] and len(examples[k]) < show:
                        examples[k].append((model, record["method"], result["request"]["text"], result["rewrite"]))
                if ok and not e2e and len(examples["correct_but_bad"]) < show:
                    examples["correct_but_bad"].append((model, record["method"], result["request"]["text"],
                                                        result["rewrite"], f))
            if record["method"] == "routed":
                routing = result.get("routing") or {}
                route = routing.get("route") or "(실패)"
                routes[(model, g["stratum"], route, "정답" if ok else "오답/실패")] += 1
                if route in ("lexicon", "disambiguate"):
                    passed = [x for x in routing.get("candidates", []) if (x.get("p_yes") or 0) >= routing["router"]["tau_sense"]]
                    own = [x for x in routing.get("candidates", []) if family.get(x["id"]) == g["family"]]
                    if own and not any(family.get(x["id"]) == g["family"] for x in passed):
                        wrong_entry[(model, "대상 항목은 검색됐지만 탈락, 다른 항목으로 풀이")] += 1
                    elif not own and g["stratum"] != "plain":
                        wrong_entry[(model, "대상 항목 없음, 다른 항목으로 풀이" +
                                     (" (용례는 있었음)" if routing.get("usage_groups") else ""))] += 1
        for (model, method), c in sorted(table.items()):
            print(f"    {model:<22} {method:<13} {c['n']:>3} {c['completed']:>4} {c['correct']:>4} {c['target']:>6} "
                  f"{c['foreign']:>5} {c['no_easy']:>8} {c['glue']:>6} {c['defn']:>6} {c['e2e']:>7}")
        print("  routed 경로 x 층 x 판정:")
        for key, n in sorted(routes.items(), key=str):
            print("     ", *key, n)
        print("  사전 경로가 대상이 아닌 항목으로 푼 경우:", dict(wrong_entry) or "없음")
    for kind, items in examples.items():
        print(f"== 예[{kind}]")
        for item in items:
            model, method, text, rw = item[:4]
            spans = " / ".join(f"{s['expression']} → {s['easy']}" for s in (rw or {}).get("spans", []))
            print(f"    {model} {method}: {text[:60]}\n        바꾼 문장: {(rw or {}).get('text')}\n        치환: {spans}"
                  + (f"\n        표시: { {k: v for k, v in item[4].items() if v is True} }" if len(item) > 4 else ""))


def audit_koneo(base):
    print("== KoNeoBench (숫자만): 실패 이유, 외국어")
    for runs, _ in KONEO:
        if not (base / runs).exists():
            print("    (없음)", runs)
            continue
        table = defaultdict(Counter)
        for record in rows(base / runs):
            result = record["result"]
            c = table[(result["model_config"]["model"], record["method"])]
            c["n"] += 1
            if record["status"] != "completed":
                error = result.get("error") or ""
                c["실패:" + ("인용" if "인용은 원문" in error else "잘림" if "잘렸" in error else
                             "형식" if "필드" in error or "배열" in error or "문자열" in error or "JSON" in error
                             else "비어있음" if "비어" in error else "시간" if record["status"] == "timed_out"
                             else "기타")] += 1
            else:
                c["외국어"] += foreign(result["analysis"], result.get("rewrite"))
        for key, c in sorted(table.items()):
            print("   ", *key, dict(c))


def audit_sft(base, show):
    path = base / "data/sft_v1/sft_train.jsonl"
    if not path.exists():
        print("== SFT 데이터 없음")
        return
    data = rows(path)
    stages, flags, plain = Counter(), Counter(), 0
    examples = []
    for row in data:
        meta, answer = row["meta"], row["messages"][-1]["content"]
        stages[(meta["stage"], meta.get("route"))] += 1
        if meta["stage"] == "probe":
            continue
        try:
            out = json.loads(answer)
        except ValueError:
            flags["JSON 아님"] += 1
            continue
        flags["외국어"] += bool(FOREIGN.search(answer))
        if meta["stage"] == "final":
            flags["final"] += 1
            plain += not out.get("expressions")
            text = json.loads(row["messages"][1]["content"])["original_text"]
            for item in out.get("replacements", []):
                pos = text.find(item["expression"])
                if pos < 0:
                    continue
                span = {"expression": item["expression"], "easy": item["easy"], "end": pos + len(item["expression"])}
                for k in easy_flags(text, span):
                    flags["final 치환 " + k] += 1
                    if len(examples) < show:
                        examples.append((text, item["expression"], item["easy"], k))
    print(f"== SFT sft_train {len(data)}개: 단계·경로 {dict(stages)}")
    print(f"    최종 답 중 탐지 표현이 비어 있는(평문) 예: {plain} · 표시 {dict(flags)}")
    for text, expression, easy, k in examples:
        print(f"    예[{k}] {text[:50]} | {expression} → {easy}")


def audit_teacher(base):
    path = base / "runs/r3/graded_train_gemma4.jsonl"
    if path.exists():
        print("== 교사(train) 판정:", dict(Counter((g["method"], g["verdict"]) for g in rows(path))))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("base", help="풀어 둔 결과 폴더 (runs/, data/sft_v1/ 가 들어 있는 곳)")
    p.add_argument("--examples", type=int, default=4)
    args = p.parse_args(argv)
    base = Path(args.base)
    audit_val(base, args.examples)
    audit_koneo(base)
    audit_sft(base, args.examples)
    audit_teacher(base)


if __name__ == "__main__":
    main()
