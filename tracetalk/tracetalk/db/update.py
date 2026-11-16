#!/usr/bin/env python3
"""Add a meaning or observed usages of a fresh expression to the live DB (data/db/live).

This is the update a fresh word needs: no retraining, one command, active at once in a running
tracetalk/web/run.py (it rereads the files when they change). Every row records the clock time it was added
and where it came from. Rows are only ever appended here; to retract one, a person deletes that line.

    python3 -m tracetalk.db.update add-entry --expression 긁히다 --meaning "..." --easy "발끈하다" --origin "..." --pos 동사 --source "..."
    python3 -m tracetalk.db.update add-usage --expression 야르 --text "야르~ 오늘 치킨 미쳤다" --text "..." --source "..."
    python3 -m tracetalk.db.update import data/db/team_db_template.csv --dry-run     (the team's sheet: checked first, all or none)
    python3 -m tracetalk.db.update list
    python3 -m tracetalk.db.update add-entry ... --reviewed            (0.8: a row a person has checked; others are "검수 전")
    python3 -m tracetalk.db.update queue --out queue.csv               (0.8 collector: what the cards met that the DB lacks,
                                                              as a team sheet to fill in, check and import --reviewed)
    python3 -m tracetalk.db.update pages _crawl/<시각>/pages/*.html --out new.csv [--import]
                                                             (0.8.1 crawler, docs/CRAWLER.md: saved newsletter
                                                              pages from the allowlist -> new words as a team sheet;
                                                              --import puts them in at once as "검수 전")
    python3 -m tracetalk.db.update corpus-add _crawl/<시각>/pages      (0.9: the posts' plain text becomes evidence the card reads, the moment
                                                              it is added; only pages the audit passed, tracetalk/evidence/corpus.py)
    python3 -m tracetalk.db.update review-add _crawl/<시각>/out/sheet.csv --pages _crawl/<시각>/pages
                                                             (0.9: the sheet goes to the review bench at /review, where
                                                              a person reads each word against its source and approves)
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from tracetalk.crawl import extract as crawl
from tracetalk.db import review
from tracetalk.evidence import corpus
from tracetalk.mad.card import easy_problem, form_patterns
from tracetalk.db.lexicon import DEFAULT_LEXICON, compact, load_lexicon

try:
    import fcntl
except ImportError:  # Windows: no lock; run one update at a time there
    fcntl = None
from tracetalk.db.usage import LIVE_DIR, candidate_rows, load_usages, stem


def append(path, row, check):
    """Append one row, then reload the whole file so a bad row never stays unnoticed.

    The lock keeps two updates at once from undoing each other's row when one of them is rolled back.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".update.lock").open("w") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        before = path.read_bytes() if path.exists() else b""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            check(path)
        except ValueError:
            path.write_bytes(before)
            raise


COLUMNS = ("kind", "expression", "variants", "meaning", "easy", "origin", "pos", "usage", "context", "source")


def variant_problem(expression, variants):
    """11-06: the sheet's variants column is split on spaces, so a spaced variant ("불미스러운 일이 일어났어요")
    became short pieces ("일이") that occur in ordinary comments. A variant of two letters or less for an expression
    of four letters or more is refused; spaces never need writing, the card ignores them."""
    short = [v for v in variants if len(compact(v)) <= 2 and len(compact(expression)) >= 4]
    return (f"변형 {short}이(가) 너무 짧습니다. 변형 칸은 띄어쓰기로 나뉩니다: 띄어 쓴 변형은 붙여 쓰세요"
            f"(카드는 띄어쓰기를 무시합니다)." if short else None)


def entry_row(row_id, when, expression, variants, meaning, source, license="팀 입력", origin="", pos="", easy="",
              review="검수 전"):
    """One meaning row for entries.jsonl; ValueError says what is wrong."""
    if not expression or len(expression) > 120 or not source.strip():
        raise ValueError("표현(120자 이내)과 출처가 필요합니다.")
    if variant_problem(expression, variants):
        raise ValueError(variant_problem(expression, variants))
    if not meaning.strip() or len(meaning) > 300:
        raise ValueError("뜻은 300자 이내로 적으세요.")
    if easy.strip():  # the card shows these words in the comment's place: short, and not the expression again
        problem = easy_problem(expression, easy.strip())
        if problem or len(easy.strip()) > 40:
            raise ValueError(f"쉬운 표현을 확인하세요: {problem or '40자 이내'}")
    return {"id": row_id, "expression": expression, "variants": variants, "meaning": meaning.strip(),
            "family": "live:" + compact(expression), "source": source.strip(), "license": license, "added_at": when,
            "review": review,  # 0.8: the card sends a sense nobody has checked to MAD
            **{k: v.strip() for k, v in (("origin", origin), ("pos", pos), ("easy", easy)) if v.strip()}}


def usage_row(row_id, when, expression, variants, texts, source, license="팀 입력", context="",
              note="팀이 넣은 용례, 검수 전"):
    """One usage row for usages.jsonl; ValueError says what is wrong."""
    if not expression or len(expression) > 120 or not source.strip():
        raise ValueError("표현(120자 이내)과 출처가 필요합니다.")
    if variant_problem(expression, variants):
        raise ValueError(variant_problem(expression, variants))
    forms = [compact(f) for f in [expression, *variants]]
    if not any(len(f) >= 2 for f in forms):
        raise ValueError("용례는 두 글자 이상인 표현(또는 변형)으로만 찾습니다. 한 글자 표현에는 두 글자 이상 변형을 함께 주세요.")
    for text in texts:
        # 0.7: an inflected verb counts too (긁히다 -> "하 개긁힌다"), the way the card finds it in a comment.
        inflected = any(re.search(pat, text) for pat in form_patterns(expression, variants))
        if not text.strip() or len(text) > 300 or not (inflected or any(f and f in compact(text) for f in forms)):
            raise ValueError(f"용례 문장(300자 이내)에 표현이나 변형이 들어 있어야 합니다: {text}")
    return {"id": row_id, "expression": expression, "variants": variants,
            "lines": [{"text": t.strip(), "context": context.strip()} for t in texts],
            "source": source.strip(), "license": license, "note": note, "added_at": when}


def sheet_rows(path, live, when, review="검수 전"):
    """The team's sheet (UTF-8 CSV, Excel's BOM is fine) as rows; every line is checked before anything is written."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"첫 줄(열 이름)이 양식과 다릅니다: {','.join(COLUMNS)}")
        out = []
        for n, line in enumerate(reader, start=2):
            kind = (line["kind"] or "").strip()
            expression = (line["expression"] or "").strip()
            if not expression and not kind:
                continue  # an empty line in the sheet
            variants = (line["variants"] or "").split()
            row_id = "live-s-" + hashlib.sha256(f"{path}|{n}|{expression}|{when}".encode()).hexdigest()[:10]
            try:
                if kind in ("entry", "뜻"):
                    out.append(("entries.jsonl", entry_row(row_id, when, expression, variants, line["meaning"] or "",
                                                           line["source"] or "", origin=line["origin"] or "",
                                                           pos=line["pos"] or "", easy=line["easy"] or "",
                                                           review=review)))
                elif kind in ("usage", "용례"):
                    out.append(("usages.jsonl", usage_row(row_id, when, expression, variants, [line["usage"] or ""],
                                                          line["source"] or "", context=line["context"] or "")))
                else:
                    raise ValueError("kind는 entry(뜻) 또는 usage(용례)입니다.")
            except ValueError as exc:
                raise ValueError(f"{n}번째 줄: {exc}") from None
    return out


def sheet_safe(row):
    """A sheet row a spreadsheet will not run: a cell may not start with = + - @ tab or return (formula injection;
    meanings come from web pages and model output)."""
    return {k: re.sub(r"^[=+\-@\t\r]+", "", v).lstrip() if isinstance(v, str) else v for k, v in row.items()}


def checked_sheet(rows, when):
    """(kept, dropped): sheet rows import would accept, checked one by one; a meaning row import refuses is dropped
    with its usages, not the whole sheet."""
    kept, dropped, bad = [], [], set()
    for r in rows:  # a row import would refuse is left out here (with its usages), not the whole page
        try:
            if r["kind"] == "뜻":
                entry_row("check", when, r["expression"], [], r["meaning"], r["source"])
            elif r["expression"] not in bad:
                usage_row("check", when, r["expression"], [], [r["usage"]], r["source"])
        except ValueError as exc:
            dropped.append({"expression": r["expression"], "kind": r["kind"], "why": str(exc)})
            if r["kind"] == "뜻":
                bad.add(r["expression"])
            continue
        if r["expression"] not in bad:
            kept.append(sheet_safe(r))
    return kept, dropped


def pages_command(args, live):
    """0.8.1 crawler: saved pages -> a team sheet of new words (checked row by row as import would), then, with
    --import, the same sheet through import (검수 전)."""
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    known = [e["expression"] for name in [*args.lexicon, live / "entries.jsonl"] for e in load_lexicon(name)]
    rows, report = crawl.sheet_rows(args.pages, known, crawl.load_sources(args.sources), when, args.cap)
    kept, dropped = checked_sheet([sheet_safe(r) for r in rows], when)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(kept)
    print(crawl.report_json(report))
    for d in dropped:
        print(json.dumps({"dropped": d}, ensure_ascii=False))
    print(json.dumps({"sheet": str(out), "words": sum(r["kind"] == "뜻" for r in kept),
                      "usages": sum(r["kind"] == "용례" for r in kept), "dropped": len(dropped)}, ensure_ascii=False))
    if args.do_import and kept:
        return main(["--live", str(live), "import", str(out)])
    return kept


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", default=str(LIVE_DIR))
    sub = p.add_subparsers(dest="command", required=True)
    entry = sub.add_parser("add-entry", help="뜻 추가: 사전 경로(lexicon)로 바로 풀이됩니다.")
    usage = sub.add_parser("add-usage", help="용례 추가: 뜻이 아직 없을 때 용례 MAD의 근거가 됩니다.")
    for q in (entry, usage):
        q.add_argument("--expression", required=True)
        q.add_argument("--variants", nargs="*", default=[], help="활용형·띄어쓰기 변형(예: 긁힌 긁혔)")
        q.add_argument("--source", required=True, help="출처(누가, 어디서 확인했는지)")
        q.add_argument("--license", default="팀 입력")
    entry.add_argument("--meaning", required=True)
    entry.add_argument("--origin", default="", help="유래(선택, 0.7 결과 카드에 표시)")
    entry.add_argument("--pos", default="", help="품사(선택, 예: 동사·명사·감탄사)")
    entry.add_argument("--easy", default="", help="쉬운 표현(선택): 이 뜻이 골라지면 결과 카드가 모델 대신 이 말을 씀")
    usage.add_argument("--text", action="append", required=True, help="용례 문장(여러 번 줄 수 있음)")
    usage.add_argument("--context", default="", help="그 문장이 답한 앞 말(선택)")
    usage.add_argument("--note", default="팀이 넣은 용례, 검수 전")
    sheet = sub.add_parser("import", help="팀 입력 표(CSV, data/db/team_db_template.csv 양식)를 한 번에 넣습니다.")
    sheet.add_argument("csv")
    sheet.add_argument("--dry-run", action="store_true", help="검사만 하고 넣지 않습니다.")
    for q in (entry, sheet):
        q.add_argument("--reviewed", action="store_true", help="사람이 확인한 뜻(검수됨). 없으면 검수 전: 카드가 MAD로 검증")
    sub.add_parser("list", help="이 폴더에 추가된 항목을 최신순으로 봅니다.")
    collect = sub.add_parser("queue", help="수집기: 카드가 만난 DB에 없는 표현을 팀 표(검수용)로 모읍니다.")
    collect.add_argument("--runs", nargs="*", default=[], help="run_bench 결과 파일(없으면 이 폴더의 candidates.jsonl)")
    collect.add_argument("--lexicon", nargs="*", default=[str(DEFAULT_LEXICON)], help="이미 뜻이 있는 낱말은 뺌")
    collect.add_argument("--out", required=True)
    pages = sub.add_parser("pages", help="크롤러: 저장한 뉴스레터 페이지에서 새 낱말을 뽑아 팀 표로 냅니다(검수 전).")
    pages.add_argument("pages", nargs="+", help="브라우저로 저장한 HTML 파일(허용 목록 사이트만 씀)")
    pages.add_argument("--lexicon", nargs="*", default=[str(DEFAULT_LEXICON)], help="이미 뜻이 있는 낱말은 뺌")
    pages.add_argument("--sources", default=str(crawl.SOURCES), help="허용 목록")
    pages.add_argument("--cap", type=int, default=30, help="한 페이지에서 넣는 새 낱말 상한")
    pages.add_argument("--out", required=True, help="만들 팀 표(CSV, 덮어쓰지 않음)")
    pages.add_argument("--import", dest="do_import", action="store_true", help="표를 만든 뒤 바로 검수 전으로 넣음")
    bench = sub.add_parser("review-add", help="크롤러 표를 검수대(/review)로 보냅니다. 사람이 승인한 것만 DB에 들어갑니다.")
    bench.add_argument("sheet", help="tracetalk/crawl/pages.py가 만든 sheet.csv")
    bench.add_argument("--pages", default=None, help="그 표의 원문 글 폴더(근거 문장을 함께 보여 줌)")
    bench.add_argument("--manifest", default=None, help="글 받기 기록(기본: 표 옆의 manifest.jsonl)")
    posts = sub.add_parser("corpus-add", help="받아 둔 글을 근거 글로 넣습니다. 카드가 그 말이 나온 글을 찾아 읽습니다.")
    posts.add_argument("pages", help="tracetalk/crawl/pages.py가 받은 글 폴더(audit.jsonl이 통과시킨 글만 넣음)")
    args = p.parse_args(argv)
    live = Path(args.live)
    if args.command == "corpus-add":
        when = datetime.now().astimezone().isoformat(timespec="seconds")
        added, skipped = corpus.add_pages(args.pages, live / "corpus.jsonl", when)
        report = {"added": added, "skipped": skipped, "posts": len(corpus.load(live / "corpus.jsonl")), "file": str(live / "corpus.jsonl")}
        print(json.dumps(report, ensure_ascii=False))
        return report
    if args.command == "review-add":
        when = datetime.now().astimezone().isoformat(timespec="seconds")
        manifest = args.manifest or Path(args.sheet).parent / "manifest.jsonl"
        rows = review.from_sheet(args.sheet, args.pages, manifest, when)
        report = {"read": len(rows), "new": review.add(live, rows), "with_source_text": sum(bool(r["evidence"]) for r in rows),
                  "queue": str(live / review.QUEUE)}
        print(json.dumps(report, ensure_ascii=False))
        return report
    if args.command == "list":
        rows = [{"kind": "뜻", "added_at": "", **e} for e in load_lexicon(live / "entries.jsonl")]
        rows += [{"kind": "용례", "expression": g["expression"], "added_at": u["added_at"], "text": u["text"],
                  "source": u["source"]} for g in load_usages([live / "usages.jsonl"]) for u in g["lines"]]
        for row in sorted(rows, key=lambda r: r["added_at"], reverse=True):
            print(json.dumps(row, ensure_ascii=False))
        return rows
    if args.command == "queue":
        return queue_command(args, live)
    if args.command == "pages":
        return pages_command(args, live)
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    checked = "검수됨" if getattr(args, "reviewed", False) else "검수 전"
    if args.command == "import":
        rows = sheet_rows(args.csv, live, when, checked)
        checks = {"entries.jsonl": load_lexicon, "usages.jsonl": lambda path: load_usages([path], missing_ok=False)}
        if not args.dry_run:
            for name, row in rows:
                append(live / name, row, checks[name])
        print(json.dumps({"checked": len(rows), "written": 0 if args.dry_run else len(rows),
                          "entries": sum(n == "entries.jsonl" for n, _ in rows),
                          "usages": sum(n == "usages.jsonl" for n, _ in rows), "folder": str(live)}, ensure_ascii=False))
        return rows
    expression = args.expression.strip()
    target = live / ("entries.jsonl" if args.command == "add-entry" else "usages.jsonl")
    count = len(target.read_text(encoding="utf-8").splitlines()) if target.exists() else 0
    row_id = f"live-{args.command[4]}-" + hashlib.sha256(f"{expression}|{when}|{count}".encode()).hexdigest()[:10]
    try:
        if args.command == "add-entry":
            row = entry_row(row_id, when, expression, args.variants, args.meaning, args.source, args.license,
                            args.origin, args.pos, args.easy, checked)
        else:
            row = usage_row(row_id, when, expression, args.variants, args.text, args.source, args.license,
                            args.context, args.note)
    except ValueError as exc:
        p.error(str(exc))
    if args.command == "add-entry":
        append(target, row, load_lexicon)
    else:
        append(target, row, lambda path: load_usages([path], missing_ok=False))
    print(json.dumps({"added": row, "file": str(target)}, ensure_ascii=False))
    return row


def queue_rows(rows, known=()):
    """0.8 collector: group the cards' rows by expression. A word is listed once with how often and in how many
    different comments it came, what MAD said each time, the first meaning it proposed, and hints a person should
    look at before believing a trend (억유행): the same comment again and again, or all of it on one day."""
    known = {stem(k) for k in known}
    groups = {}
    for r in rows:
        head = r.get("headword")
        key = stem(head or r["expression"])
        if not head and key in known:  # someone has given it a meaning since
            continue
        groups.setdefault((key, bool(head)), []).append(r)
    out = []
    for (key, new_sense), rs in groups.items():
        verdicts = Counter("일반어" if r["choice"] == "L" else "모름" if r["status"] == "uncertain" else "신조어"
                           for r in rs)
        if not verdicts["신조어"] + verdicts["모름"]:
            continue  # every time a standard word
        texts = list(dict.fromkeys(r["text"] for r in rs if r["text"]))
        meanings = [r["meaning"] for r in rs if r["choice"] == "N" and r["status"] == "proposed" and r["meaning"]]
        days = {r["at"][:10] for r in rs if r.get("at")}
        hints = (["같은 문장만 되풀이됨"] if len(rs) >= 3 and len(texts) == 1 else []) + \
                (["하루에만 몰림"] if len(rs) >= 3 and len(days) == 1 else [])
        written = Counter(r.get("headword") or r["expression"] for r in rs)
        shown = next((w for w, _ in written.most_common() if compact(w) == key), key)  # 테토남, not 테토남이네
        out.append({"expression": shown, "new_sense": new_sense,
                    "seen": len(rs), "comments": len(texts), "verdicts": dict(verdicts),
                    "meaning": meanings[0] if meanings else "", "easy": next((r["easy"] for r in rs if r["easy"]), ""),
                    "texts": texts[:3], "first": min(days) if days else "", "last": max(days) if days else "",
                    "hints": hints})
    return sorted(out, key=lambda q: (-q["comments"], -q["seen"], q["expression"]))


def queue_command(args, live):
    out = Path(args.out)
    if out.exists():
        raise ValueError(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
    if args.runs:
        rows = [r for name in args.runs for line in Path(name).read_text(encoding="utf-8").splitlines() if line.strip()
                for r in candidate_rows(json.loads(line)["result"])]
    else:
        path = live / "candidates.jsonl"
        rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()] if path.exists() else []
    known = [e["expression"] for name in args.lexicon + [str(live / "entries.jsonl")] for e in load_lexicon(name)]
    listed = queue_rows(rows, known)
    with out.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        put = lambda row: writer.writerow(sheet_safe(row))  # model meanings: never a spreadsheet formula
        for q in listed:
            v = q["verdicts"]
            note = (f"수집기 {q['first']}~{q['last']} · 댓글 {q['comments']}개 · MAD 신조어 {v.get('신조어', 0)}·모름 "
                    f"{v.get('모름', 0)}·일반어 {v.get('일반어', 0)}" + (f" · 확인할 것: {', '.join(q['hints'])}" if q["hints"] else "")
                    + (" · DB 낱말의 새 뜻 후보" if q["new_sense"] else "") + " · 검수 전: 뜻을 확인·고친 뒤 import --reviewed")
            put({"kind": "뜻", "expression": q["expression"], "variants": "", "meaning": q["meaning"],
                             "easy": q["easy"], "origin": "", "pos": "", "usage": "", "context": "", "source": note})
            for text in q["texts"]:
                put({"kind": "용례", "expression": q["expression"], "variants": "", "meaning": "", "easy": "",
                                 "origin": "", "pos": "", "usage": text[:300], "context": "", "source": "수집기(카드 입력)"})
    for q in listed:
        print(json.dumps({k: q[k] for k in ("expression", "new_sense", "comments", "seen", "verdicts", "meaning", "hints")},
                         ensure_ascii=False))
    print(json.dumps({"candidates": len(listed), "rows_read": len(rows), "sheet": str(out)}, ensure_ascii=False))
    return listed


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f"추가하지 않았습니다: {exc}", file=sys.stderr)
        sys.exit(1)
