#!/usr/bin/env python3
"""상용 AI + TraceTalk DB (0.11): the question sheet that gives a commercial model, under every comment, what TraceTalk found for it -
the DB's own rows (meaning, review state, source) and the fetched posts' own text (newsletter, date, address) - never the 4B's reading
of them. The rules and the answer line are those of the sheet without it (ask_alone.txt), so the same blind judging applies
(eval/fresh5_sheet.py, system "gemini_db").

What a comment gets is what one TraceTalk run found for it (its card items): with the run frozen before the test (fresh_v5: 0.10,
runs/v13/fresh_v5/full.jsonl) the material is blind to the test as well.
    python3 eval/ask_with_db.py --set fresh_v5 --run runs/v13/fresh_v5/full.jsonl --out data/eval/fresh_v5/ask_withdb.txt
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracetalk.evidence.corpus import load, post_date  # noqa: E402

NEWSLETTERS = (("maily.so/trendaword", "Trend A Word"), ("maily.so/farmingletter", "파밍레터"), ("gogumafarm.kr", "고구마팜"),
               ("letter.wepick.kr", "위픽레터"))
MAX_QUOTE = 400
LEAD = ("아래는 인터넷 댓글 {n}개입니다. 각 댓글 아래 [DB]는 신조어 DB(TraceTalk)가 그 댓글에서 찾아 준 자료입니다"
        "(DB 풀이, 뉴스레터 원문 발췌와 그 날짜·주소). 자료를 참고해 각 댓글에 나오는 신조어·유행어·밈 표현을 풀이해 주세요.")
EXTRA_RULE = "- [DB] 자료는 자동으로 찾은 것이라 댓글과 관계없는 것도 섞일 수 있습니다. 댓글과 맞지 않으면 따르지 마세요."


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def newsletter(url):
    return next((name for key, name in NEWSLETTERS if key in url), "뉴스레터")


def material(items, dates):
    """The [DB] lines of one comment: each DB row once, each post passage once, in the card's order."""
    lines, seen = [], set()
    for it in items:
        word = it.get("expression") or it.get("span") or ""
        if it.get("basis") == "db" and it.get("db_meaning") and ("db", word) not in seen:
            seen.add(("db", word))
            source = f", 출처 {it['db_source']}" if str(it.get("db_source", "")).startswith("http") else ""
            lines.append(f"   [DB] {word} · DB 풀이({it.get('db_review') or '검수 상태 없음'}{source}): “{it['db_meaning']}”")
        for p in it.get("posts") or []:
            key = (p["url"], p["text"][:80])
            if key in seen:
                continue
            seen.add(key)
            text = re.sub(r"\s+", " ", p["text"]).strip()
            text = text if len(text) <= MAX_QUOTE else text[:MAX_QUOTE].rstrip() + "…"
            date = p.get("date") or dates.get(p["url"], "")
            lines.append(f"   [DB] {word} · 뉴스레터 원문({newsletter(p['url'])}, {date or '날짜 없음'}, {p['url']}): “{text}”")
    return lines or ["   [DB] 이 댓글에서 찾은 자료 없음"]


def sheet(set_dir, run, alone):
    head = Path(alone).read_text(encoding="utf-8").split("\n\n")[0].splitlines()
    key = rows(Path(set_dir) / "key.jsonl")
    cards = {r["case_id"]: ((r.get("result") or {}).get("card") or {}).get("items") or [] for r in rows(run)}
    dates = {p["url"]: post_date(p) for p in load(ROOT / "data/db/live/corpus.jsonl").posts}
    rules = [line for line in head[1:] if not line.startswith("- 웹 검색")]
    out = [LEAD.format(n=len(key))] + rules + [EXTRA_RULE, "- 웹 검색은 쓰지 마세요.", ""]
    for k in key:
        out.append(f"{k['no']}. {k['text']}")
        out.extend(material(cards.get(k["case_id"], []), dates))
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--set", default="fresh_v5")
    p.add_argument("--run", default=str(ROOT / "runs/v13/fresh_v5/full.jsonl"))
    p.add_argument("--alone", help="the sheet without the DB (default: data/SET/ask_alone.txt)")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    d = ROOT / "data" / "eval" / args.set
    text = sheet(d, args.run, args.alone or d / "ask_alone.txt")
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"{args.out}: 댓글 {text.count(chr(10) + '   [DB]') and len(rows(d / 'key.jsonl'))}개, [DB] 줄 {text.count('[DB]') - 1}개, {len(text)}자")


if __name__ == "__main__":
    main()
