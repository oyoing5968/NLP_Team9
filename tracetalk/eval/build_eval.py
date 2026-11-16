#!/usr/bin/env python3
"""Build eval_v1 inputs and provisional gold from the downloaded public data.

Sources (see data/eval/external/SOURCES.md):
- KoCulture-Descriptions: meaning of each slang/meme title (gold, provisional).
- KoCulture-Dialogues: chat lines that use the title (input comment).
- KoNeoBench task4: usage sentence (input) and definition (gold), public eval only.
  (Lee et al., "KoNeoBench", arXiv:2609.19916, Findings of EMNLP 2026; news neologisms 2020-2024,
  expert-curated definitions. Only abbreviations and blends are used: the word must be decomposed.)
- A small set of plain sentences written for this project (no slang).

Families are split by a hash of the normalized title, so a title never appears
in two splits. Gold files stay separate from inputs; inference sees text only.

Hash buckets (0-9): 0-5 train, 6-7 validation, 8-9 test. Buckets 6 and 8 are put in
the evaluation lexicon ("registered"); 7 and 9 are left out ("unregistered"), so the
router and MAD can be measured on expressions the lexicon does not know. Student
training only ever sees train families. The demo lexicon holds every family.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data/eval/external"

PLAIN = [
    "내일 오전 열 시에 회의실에서 팀 회의가 있습니다.",
    "비가 와서 우산을 챙겨 나왔어요.",
    "점심으로 김치찌개를 먹었는데 조금 짰다.",
    "도서관은 주말에 오후 다섯 시까지 운영합니다.",
    "동생이 이번 학기에 기숙사로 들어갔다.",
    "감기 기운이 있어서 오늘은 일찍 자려고 해.",
    "버스가 늦게 와서 수업에 오 분 늦었다.",
    "엄마가 보내 준 반찬을 냉장고에 넣어 두었다.",
    "과제 제출 기한이 금요일 자정으로 연장되었습니다.",
    "주말에 친구와 한강에서 자전거를 탔다.",
    "새로 산 노트북 배터리가 생각보다 오래간다.",
    "회의 자료는 공유 폴더에 올려 두었습니다.",
]
PLAIN_MEANING = "신조어나 밈이 없는 평범한 문장이다. 문자 그대로의 뜻으로 읽으면 되며 expressions는 비어 있어야 한다."


def key(text):
    return "".join(text.split())


def bucket(family):
    return int(hashlib.sha256(key(family).encode("utf-8")).hexdigest(), 16) % 10


def split_of(family):
    b = bucket(family)
    return "train" if b < 6 else "validation" if b < 8 else "test"


def registered(family):
    return bucket(family) not in (7, 9)


def short_meaning(content, limit=220):
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind("다."), cut.rfind(". "))
    return cut[:end + (2 if cut[end:end + 2] == "다." else 1)] if end > 40 else cut + "…"


def pick(items, salt):
    return min(items, key=lambda s: hashlib.sha256((salt + s).encode("utf-8")).hexdigest())


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, rows):
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# KoNeoBench word formation -> stratum, so summaries split abbreviations from blends.
FORMATION = {"축약": "kn_abbreviation", "혼성": "kn_blend"}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(ROOT / "data/eval/eval_v1"))
    p.add_argument("--koneo-count", type=int, default=100)
    p.add_argument("--external", default=str(EXT))
    p.add_argument("--lexicon-out", default=str(ROOT / "data/db/lexicon"))
    args = p.parse_args(argv)
    ext = Path(args.external)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)

    desc = read_jsonl(ext / "koculture/KoCulture-Descriptions.jsonl")
    dial = read_jsonl(ext / "koculture/KoCulture-Dialogues.jsonl")
    meaning = {}
    for row in desc:
        meaning.setdefault(key(row["title"]), row)
    usages = {}
    for row in dial:
        title, answer = row["title"].strip(), (row.get("answer") or "").strip()
        if not answer or len(answer) > 300:
            continue
        if title in answer or key(title) in key(answer):
            usages.setdefault(key(title), []).append(answer)

    inputs = {"train": [], "validation": [], "test": []}
    gold = {"train": [], "validation": [], "test": []}
    families = {"train": [], "validation": [], "test": []}
    lexicon_eval, lexicon_demo, lexicon_teacher = [], [], []
    for k in sorted(meaning):
        row = meaning[k]
        split = split_of(row["title"])
        families[split].append(row["title"])
        entry = {"id": "lx-" + hashlib.sha256(k.encode("utf-8")).hexdigest()[:10], "expression": row["title"].strip(),
                 "variants": [], "meaning": short_meaning(row["content"]), "family": "kc:" + k,
                 "source": "KoCulture-Descriptions/" + row.get("source", ""), "license": "CC BY-NC-SA 4.0"}
        lexicon_demo.append(entry)
        if registered(row["title"]):
            lexicon_eval.append(entry)
        # Teacher traces on train inputs use only train families (no validation/test meaning may enter
        # a training prompt). Buckets 0-2 stay out so the routed traces also contain MAD runs.
        if bucket(row["title"]) in (3, 4, 5):
            lexicon_teacher.append(entry)
        if k not in usages:
            continue
        if split == "train":
            ranked = sorted(usages[k], key=lambda s: hashlib.sha256(("train:" + s).encode("utf-8")).hexdigest())
            texts = list(dict.fromkeys(ranked))[:3]
        else:
            texts = [pick(usages[k], "eval_v1:")]
        for n, text in enumerate(texts):
            suffix = "" if split != "train" else f"-{n}"
            case_id = ("kt-" if split == "train" else "kc-") + hashlib.sha256(k.encode("utf-8")).hexdigest()[:10] + suffix
            inputs[split].append({"id": case_id, "text": text, "family": "kc:" + k, "split": split})
            stratum = "train" if split == "train" else "registered" if registered(row["title"]) else "unregistered"
            gold[split].append({"case_id": case_id, "family": "kc:" + k, "stratum": stratum,
                                "expression": row["title"], "reference_meaning": row["content"],
                                "source": "KoCulture-Descriptions/" + row.get("source", ""),
                                "source_date": row.get("date", ""), "license": "CC BY-NC-SA 4.0",
                                "review_status": "provisional_public_data_not_team_reviewed"})

    for i, text in enumerate(PLAIN, 1):
        split = "validation" if i % 2 else "test"
        case_id = f"plain-{i:02d}"
        inputs[split].append({"id": case_id, "text": text, "family": case_id, "split": split})
        gold[split].append({"case_id": case_id, "family": case_id, "stratum": "plain",
                            "expression": "", "reference_meaning": PLAIN_MEANING,
                            "source": "written for TraceTalk eval_v1", "source_date": "2026-10-26",
                            "license": "team", "review_status": "provisional_author_written"})

    koculture_keys = set(meaning)
    koneo_rows = []
    with (ext / "koneobench/Task4_with_ex.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            head = row["색인표제어"].strip()
            # The source marks the target word with ¶ and {}; strip the marks so detection is not given away.
            usage = (row["용례"] or "").replace("¶", "").replace("{", "").replace("}", "").strip()
            if row["단어 형성법"] not in ("축약", "혼성") or not usage or len(usage) > 600:
                continue
            if key(head) in koculture_keys or key(head) not in key(usage):
                continue
            koneo_rows.append({**row, "_usage": usage})
    koneo_rows.sort(key=lambda r: hashlib.sha256(("koneo:" + key(r["색인표제어"])).encode("utf-8")).hexdigest())
    koneo_inputs, koneo_gold = [], []
    for row in koneo_rows[:args.koneo_count]:
        head = row["색인표제어"].strip()
        case_id = "kn-" + hashlib.sha256(key(head).encode("utf-8")).hexdigest()[:10]
        koneo_inputs.append({"id": case_id, "text": row["_usage"], "family": "kn:" + key(head), "split": "test"})
        koneo_gold.append({"case_id": case_id, "family": "kn:" + key(head), "stratum": FORMATION[row["단어 형성법"]],
                           "expression": head, "reference_meaning": row["뜻풀이"].strip(),
                           "source": "KoNeoBench task4 (commit d251cd9a)", "source_date": row["최초 출현 연도"],
                           "license": "unknown; eval only, do not redistribute",
                           "review_status": "expert_reviewed_by_source"})

    write_jsonl(out / "train_inputs.jsonl", inputs["train"])
    write_jsonl(out / "train_gold.jsonl", gold["train"])
    write_jsonl(out / "val_inputs.jsonl", inputs["validation"])
    write_jsonl(out / "val_gold.jsonl", gold["validation"])
    write_jsonl(out / "test_inputs.jsonl", inputs["test"])
    write_jsonl(out / "test_gold.jsonl", gold["test"])
    write_jsonl(out / "koneo_inputs.jsonl", koneo_inputs)
    write_jsonl(out / "koneo_gold.jsonl", koneo_gold)
    (out / "families.json").write_text(json.dumps(families, ensure_ascii=False, indent=1), encoding="utf-8")
    lex_dir = Path(args.lexicon_out)
    lex_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(lex_dir / "lexicon_eval_v1.jsonl", lexicon_eval)
    write_jsonl(lex_dir / "lexicon_demo_v1.jsonl", lexicon_demo)
    write_jsonl(lex_dir / "lexicon_teacher_v1.jsonl", lexicon_teacher)
    count = lambda split, name: sum(g["stratum"] == name for g in gold[split])
    summary = {"train_cases": len(inputs["train"]),
               "validation_cases": len(inputs["validation"]), "test_cases": len(inputs["test"]),
               "validation_strata": {n: count("validation", n) for n in ("registered", "unregistered", "plain")},
               "test_strata": {n: count("test", n) for n in ("registered", "unregistered", "plain")},
               "lexicon_eval_entries": len(lexicon_eval), "lexicon_demo_entries": len(lexicon_demo),
               "lexicon_teacher_entries": len(lexicon_teacher),
               "koneo_cases": len(koneo_inputs),
               "families": {s: len(v) for s, v in families.items()},
               "koculture_titles_with_usage": sum(k in usages for k in meaning)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
