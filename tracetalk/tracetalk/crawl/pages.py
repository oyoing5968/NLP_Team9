#!/usr/bin/env python3
"""TraceTalk crawler (docs/CRAWLER.md): fetch the listed newsletter posts, audit every file, and keep only plain
text and a team sheet to carry to the Mac. Every path stays inside this project folder.

    python3 -m tracetalk.crawl.pages fetch --urls data/crawl/urls.txt --out _crawl/pages
    python3 -m tracetalk.crawl.pages audit --pages _crawl/pages                  (writes _crawl/pages/audit.jsonl)
    python3 -m tracetalk.crawl.pages extract --pages _crawl/pages --out _crawl/out (only pages the audit passed: sheet.csv,
                                                                         blocks.jsonl, report.jsonl, manifest, audit)
    python3 -m tracetalk.crawl.pages check-out --dir _crawl/out                    (what is carried: run on both machines)
    python3 -m tracetalk.crawl.pages discover --index data/crawl/index_pages.txt --known data/db/live/corpus.jsonl --out _crawl/new.txt
                                                                        (0.9: what is new on the listed sites' index pages)
    python3 -m tracetalk.crawl.pages llm-extract --pages _crawl/pages --out _crawl/out_llm --model tracetalk-student-v1 \
        --base-url http://127.0.0.1:11435 --temperature 0    (v3: the Mac's model reads each post; app sandbox)
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from tracetalk.crawl import audit, fetch
from tracetalk.crawl import extract as crawl
from tracetalk.db.lexicon import DEFAULT_LEXICON, load_lexicon
from tracetalk.model import add_model_arguments, config_from, make_client


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", default=str(crawl.SOURCES))
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--index", default="data/crawl/index_pages.txt")
    d.add_argument("--known", nargs="*", default=[], help="이미 받은 글: corpus.jsonl 또는 manifest.jsonl")
    d.add_argument("--out", required=True)
    d.add_argument("--each", type=int, default=10)
    f = sub.add_parser("fetch")
    f.add_argument("--urls", required=True)
    f.add_argument("--out", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--pages", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--pages", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--lexicon", nargs="*", default=[str(DEFAULT_LEXICON)])
    m = sub.add_parser("llm-extract")
    m.add_argument("--pages", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--lexicon", nargs="*", default=[str(DEFAULT_LEXICON)])
    m.add_argument("--only", nargs="*", default=None, help="only these page files (the development half)")
    m.add_argument("--reader", choices=["v3", "v4", "v5"], default="v5",
                   help="v3: one reading; v4: list, then define each (worse, 11-07); v5: v3 on smaller parts, names out")
    add_model_arguments(m)
    c = sub.add_parser("check-out")
    c.add_argument("--dir", required=True)
    args = p.parse_args(argv)
    sources = crawl.load_sources(args.sources)

    if args.command == "discover":
        out = fetch.inside_project(args.out)
        if out.exists():
            p.error(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
        known = {u for name in args.known if Path(name).exists() for r in rows(name) for u in (r.get("url"), r.get("final_url")) if u}
        new, report = fetch.discover(Path(args.index).read_text(encoding="utf-8").splitlines(), sources, known, each=args.each)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(u + "\n" for u in new), encoding="utf-8")
        print(json.dumps({"new": len(new), "report": report}, ensure_ascii=False))
        return 0
    if args.command == "fetch":
        got = fetch.fetch_all(Path(args.urls).read_text(encoding="utf-8").splitlines(), args.out, sources)
        print(json.dumps({"fetched": sum(r["status"] == "ok" for r in got), "refused": [r["why"] for r in got
                                                                                         if r["status"] != "ok"]},
                         ensure_ascii=False))
        return 0
    if args.command == "audit":
        pages = fetch.inside_project(args.pages)
        target = pages / "audit.jsonl"
        if target.exists():
            p.error(f"{target} 이(가) 이미 있습니다(덮어쓰지 않음).")
        found = [audit.audit_page(pages / r["file"], r, sources) for r in rows(pages / "manifest.jsonl")
                 if r["status"] == "ok"]
        target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in found), encoding="utf-8")
        print(json.dumps({"ok": sum(x["verdict"] == "ok" for x in found),
                          "refused": [(x["file"], x["problems"]) for x in found if x["verdict"] != "ok"]},
                         ensure_ascii=False))
        return 0
    if args.command == "llm-extract":
        import csv
        from tracetalk.db import update as update_db
        from kiwipiepy import Kiwi  # required: the ordinary-word check
        from tracetalk.crawl.extract_llm import llm_candidates, llm_candidates_v4
        pages, out = fetch.inside_project(args.pages), fetch.inside_project(args.out)
        if out.exists():
            p.error(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
        client = make_client(config_from(args))
        if not client.health().get("ready"):
            p.error("모델 서버가 준비되지 않았습니다(mac/serve.sh).")
        manifest = {r["file"]: r for r in rows(pages / "manifest.jsonl") if r["status"] == "ok"}
        ok = [x["file"] for x in rows(pages / "audit.jsonl") if x["verdict"] == "ok"
              and (args.only is None or x["file"] in args.only)]
        when = datetime.now().astimezone().isoformat(timespec="seconds")
        known = [e["expression"] for name in args.lexicon for e in load_lexicon(name)]
        kiwi, log = Kiwi(), []
        sheet, report = crawl.sheet_rows([pages / f for f in ok], known, sources, when,
                                         urls={f: manifest[f]["final_url"] for f in ok},
                                         extract=lambda page: (
                                             llm_candidates_v4(page, client, kiwi, log=log) if args.reader == "v4"
                                             else llm_candidates(page, client, kiwi, log=log, size=1800, names=True)
                                             if args.reader == "v5" else llm_candidates(page, client, kiwi, log=log)))
        kept, dropped = update_db.checked_sheet([update_db.sheet_safe(r) for r in sheet], when)
        out.mkdir(parents=True)
        with (out / "sheet.csv").open("x", encoding="utf-8", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=update_db.COLUMNS)
            w.writeheader()
            w.writerows(kept)
        (out / "report.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in report)
                                          + "".join(json.dumps({"dropped": d}, ensure_ascii=False) + "\n" for d in dropped)
                                          + "".join(json.dumps({"model": x}, ensure_ascii=False) + "\n" for x in log),
                                          encoding="utf-8")
        for name in ("manifest.jsonl", "audit.jsonl"):
            shutil.copyfile(pages / name, out / name)
        names = sorted(x.name for x in out.iterdir())
        (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n"
                                                for n in names), encoding="utf-8")
        print(json.dumps({"pages": len(ok), "words": sum(r["kind"] == "뜻" for r in kept),
                          "usages": sum(r["kind"] == "용례" for r in kept), "dropped": len(dropped),
                          "model_items": len(log), "kept_by_checks": sum(1 for x in log if x.get("kept"))},
                         ensure_ascii=False))
        return 0
    if args.command == "extract":
        from tracetalk.db import update as update_db
        pages, out = fetch.inside_project(args.pages), fetch.inside_project(args.out)
        if out.exists():
            p.error(f"{out} 이(가) 이미 있습니다(덮어쓰지 않음).")
        manifest = {r["file"]: r for r in rows(pages / "manifest.jsonl") if r["status"] == "ok"}
        ok = [x["file"] for x in rows(pages / "audit.jsonl") if x["verdict"] == "ok"]
        when = datetime.now().astimezone().isoformat(timespec="seconds")
        known = [e["expression"] for name in args.lexicon for e in load_lexicon(name)]
        sheet, report = crawl.sheet_rows([pages / f for f in ok], known, sources, when,
                                         urls={f: manifest[f]["final_url"] for f in ok})
        kept, dropped = update_db.checked_sheet([update_db.sheet_safe(r) for r in sheet], when)
        out.mkdir(parents=True)
        with (out / "sheet.csv").open("x", encoding="utf-8", newline="") as handle:
            import csv
            w = csv.DictWriter(handle, fieldnames=update_db.COLUMNS)
            w.writeheader()
            w.writerows(kept)
        (out / "blocks.jsonl").write_text("".join(json.dumps(crawl.text_blocks(pages / f, manifest[f]["final_url"]),
                                                             ensure_ascii=False) + "\n" for f in ok), encoding="utf-8")
        (out / "report.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in report)
                                          + "".join(json.dumps({"dropped": d}, ensure_ascii=False) + "\n"
                                                    for d in dropped), encoding="utf-8")
        for name in ("manifest.jsonl", "audit.jsonl"):
            shutil.copyfile(pages / name, out / name)
        names = sorted(x.name for x in out.iterdir())
        (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n"
                                                for n in names), encoding="utf-8")
        print(json.dumps({"pages": len(ok), "words": sum(r["kind"] == "뜻" for r in kept),
                          "usages": sum(r["kind"] == "용례" for r in kept), "dropped": len(dropped)},
                         ensure_ascii=False))
        return 0
    problems = audit.audit_out(args.dir, sources)
    for x in problems:
        print("   문제:", x)
    print(f"== 넘길 파일 감사: {'깨끗함' if not problems else f'문제 {len(problems)}개 → 넘기지 마세요'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
