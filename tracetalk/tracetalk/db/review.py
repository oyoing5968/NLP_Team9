"""Review bench (0.9, docs/DESIGN.md): what the crawler and the collector found waits here until a person has read it
against its source. Crawler precision on unseen posts was 48-76% (docs/CRAWLER.md), so nothing found on the web
reaches the DB by itself: a person approves or corrects a meaning, and only then one "검수됨" row goes to the live DB,
which the next card reads without a restart.

Two append-only files under data/db/live (local, never shared):
    review_queue.jsonl  {key, expression, meaning, usages, source, url, evidence: [{text, url}], tool, added_at}
    review_log.jsonl    {at, action: approve|reject, keys, expression, meaning, ...}
A word is listed once with every meaning proposed for it, and leaves the list when all of those have a decision; a new
meaning from a later post brings it back. The collector's words (candidates.jsonl) join the list as they come, with
the comments they were seen in; a meaning only when it was read from a fetched post, with the passages (a guess from the
comment alone is not offered as a meaning to approve).
"""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from tracetalk.crawl import extract as crawl
from tracetalk.db.lexicon import compact, jamo
from tracetalk.db.usage import candidate_rows, stem  # noqa: F401  (candidate_rows: the collector's row format)

try:
    from rapidfuzz.distance import Levenshtein
except ImportError:
    Levenshtein = None

QUEUE, LOG = "review_queue.jsonl", "review_log.jsonl"
QUOTE = 160  # letters kept on each side of the word in a source quote
MAX_QUOTES = 3
ACTIONS = ("approve", "reject")


def row_key(expression, meaning):
    return hashlib.sha256(f"{compact(expression)}|{compact(meaning)}".encode("utf-8")).hexdigest()[:16]


def _read(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()] if Path(path).exists() else []


def _bigrams(text):
    key = compact(text)
    return {key[i:i + 2] for i in range(len(key) - 1)}


def _cut(text, at, size):
    start, end = max(0, at - QUOTE), at + size + QUOTE
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def quotes(blocks, expression, meaning="", url=""):
    """The source's own sentences for the reviewer: the block closest to the proposed meaning (a post often explains a
    word under a heading without naming it again), then those naming the word, one that says what something means first.
    Closeness only orders what is shown: it does not tell an invented meaning from a right one (docs/CRAWLER.md v3)."""
    key = compact(expression)
    main = crawl.main_blocks(blocks)
    want = _bigrams(meaning)
    closest = max((b for b in main if b["kind"] == "p" and len(b["text"]) >= 12),
                  key=lambda b: len(want & _bigrams(b["text"])), default=None) if want else None
    named = [b["text"] for b in main if key in compact(b["text"]) and len(b["text"]) >= 12]
    named.sort(key=lambda t: not crawl.STRONG.search(t))
    order = list(dict.fromkeys(([closest["text"]] if closest else []) + named))
    out = []
    for text in order[:MAX_QUOTES]:
        at = text.find(expression)
        out.append({"text": _cut(text, at if at >= 0 else 0, len(expression)), "url": url})
    return out


def from_sheet(sheet, pages=None, manifest=None, when=""):
    """Queue rows from a crawler sheet (update_db.COLUMNS). pages: the folder of the fetched posts, so each word carries
    the sentences of the post that defined it. manifest: the fetch record (address -> file); the extract report beside
    the sheet names the address each page gave for itself."""
    with open(sheet, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    files = {}
    if manifest and Path(manifest).exists():
        for r in _read(manifest):
            if r.get("status") == "ok":
                files[r["final_url"]] = r["file"]
                files[r["url"]] = r["file"]
    for r in _read(Path(sheet).parent / "report.jsonl"):
        if r.get("url") and r.get("page"):
            files[r["url"]] = r["page"]
    usages, out, read = {}, [], {}
    for r in rows:
        if r["kind"] == "용례" and (r.get("usage") or "").strip():
            usages.setdefault(compact(r["expression"]), []).append(r["usage"].strip())
    for r in rows:
        if r["kind"] != "뜻" or not (r.get("meaning") or "").strip():
            continue
        url = (r.get("source") or "").split(" · ")[0].strip()
        evidence = []
        name = files.get(url)
        if pages and name and (Path(pages) / name).is_file():
            page = read.setdefault(name, crawl.read_page(Path(pages) / name))
            evidence = quotes(page["blocks"], r["expression"], r["meaning"], url)
        out.append({"key": row_key(r["expression"], r["meaning"]), "expression": r["expression"].strip(),
                    "meaning": r["meaning"].strip(), "usages": usages.get(compact(r["expression"]), [])[:3],
                    "source": (r.get("source") or "").strip(), "url": url, "evidence": evidence, "tool": "크롤러",
                    "added_at": when})
    return out


def add(live, rows):
    """Append rows the queue does not have yet; how many were new."""
    path = Path(live) / QUEUE
    have = {r["key"] for r in _read(path)}
    new = [r for r in rows if r["key"] not in have]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in {r["key"]: r for r in new}.values())
    return len({r["key"] for r in new})


def _collected(live, known):
    """The collector's words as queue rows: seen in comments, no meaning. Keyed by word, so a decision on the word holds."""
    rows = [r for r in _read(Path(live) / "candidates.jsonl") if r.get("choice") != "L" and r.get("status") != "failed"]
    by = {}
    for r in rows:
        word = stem(r.get("headword") or r["expression"])
        if len(word) >= 2 and word not in known and str(r.get("text", "")).strip():
            by.setdefault(word, []).append(r)
    out = []
    for word, rs in by.items():
        texts = list(dict.fromkeys(r["text"] for r in rs))
        written = Counter(r["expression"] for r in rs).most_common(1)[0][0]
        read = next((r for r in rs if r.get("post_meaning")), None)  # what the card read in the fetched posts, with the passages
        posts = (read or {}).get("posts") or []
        out.append({"key": row_key(word, read["post_meaning"] if read else ""), "expression": written if compact(written) == word else word,
                    "meaning": read["post_meaning"] if read else "", "usages": texts[:3],
                    "source": " · ".join(p["url"] for p in posts[:2]) + " · 글 읽기" if posts else f"수집기: 댓글 {len(texts)}개에서 만남",
                    "url": posts[0]["url"] if posts else "", "tool": "글 읽기" if posts else "수집기",
                    "evidence": [{"text": p["text"], "url": p["url"]} for p in posts] or [{"text": t, "url": ""} for t in texts[:MAX_QUOTES]],
                    "added_at": max((r.get("at") or "") for r in rs)})
    return out


def similar_words(expression, forms, most=3):
    """DB forms one jamo edit away (a typo or a variant of something the DB has); none when rapidfuzz is missing."""
    key = compact(expression)
    if Levenshtein is None or len(key) < 3:
        return []
    target = jamo(key)
    near = [f for f in forms if f != key and abs(len(f) - len(key)) <= 1 and Levenshtein.distance(jamo(f), target) <= 1]
    return sorted(near)[:most]


def listing(live, lexicon):
    """The words waiting for a person, those with more sources first: {items: [{expression, proposals, usages, in_db,
    similar, keys}], waiting, approved, rejected}."""
    decided = _read(Path(live) / LOG)
    done = {k for d in decided for k in d["keys"]}
    known = {}
    forms = set()
    for e in lexicon:
        for form in [e["expression"], *e.get("variants", [])]:
            forms.add(compact(form))
            known.setdefault(compact(form), []).append({"meaning": e["meaning"], "review": e.get("review", "검수됨"),
                                                        "source": e.get("source", "")})
    groups = {}
    for r in _read(Path(live) / QUEUE) + _collected(live, set(known) | {stem(k) for k in known}):
        if r["key"] not in done:
            groups.setdefault(compact(r["expression"]), []).append(r)
    items = []
    for word, rows in groups.items():
        proposals = [{"key": r["key"], "meaning": r["meaning"], "source": r["source"], "url": r["url"],
                      "tool": r["tool"], "evidence": r["evidence"], "added_at": r["added_at"]} for r in rows]
        items.append({"expression": rows[0]["expression"], "proposals": proposals, "keys": [r["key"] for r in rows],
                      "usages": list(dict.fromkeys(u for r in rows for u in r["usages"]))[:4],
                      "sources": len({r["url"] or r["source"] for r in rows}), "in_db": known.get(word, []),
                      "similar": similar_words(word, forms)})
    items.sort(key=lambda i: (-i["sources"], not i["in_db"], i["expression"]))
    return {"items": items, "waiting": len(items), "approved": sum(d["action"] == "approve" for d in decided),
            "rejected": sum(d["action"] == "reject" for d in decided)}


def decide(live, body, now=None):
    """One decision from the bench. approve: the (possibly corrected) meaning goes in as 검수됨 with its sentences as
    usages, through update_db's own checks; reject: only logged. ValueError says what is wrong; nothing is half-written."""
    from tracetalk.db import update as update_db  # the DB's one writer (a top-level tool; imports tracetalk.mad.card, not the server)
    from tracetalk.db.lexicon import load_lexicon
    from tracetalk.db.usage import load_usages
    live = Path(live)
    action, keys = body.get("action"), body.get("keys")
    if action not in ACTIONS or not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
        raise ValueError("action(approve·reject)과 keys가 필요합니다.")
    queue = {r["key"]: r for r in _read(live / QUEUE)}
    fields = {k: body.get(k, "") for k in ("expression", "meaning", "easy", "origin", "pos", "source")}
    if not all(isinstance(v, str) for v in fields.values()):
        raise ValueError("표현·뜻·쉬운 말·유래·품사·출처는 문자열입니다.")
    variants, usages = body.get("variants", []), body.get("usages", [])
    if not (isinstance(variants, list) and isinstance(usages, list) and all(isinstance(v, str) for v in variants + usages)):
        raise ValueError("variants와 usages는 문자열 목록입니다.")
    when = now or datetime.now().astimezone().isoformat(timespec="seconds")
    expression = fields["expression"].strip()
    record = {"at": when, "action": action, "keys": keys, "expression": expression}
    if action == "approve":
        source = fields["source"].strip() or next((queue[k]["source"] for k in keys if k in queue), "")
        entry_id = "live-r-" + hashlib.sha256(f"{expression}|{when}|{keys}".encode()).hexdigest()[:10]
        entry = update_db.entry_row(entry_id, when, expression, variants, fields["meaning"], source + " · 사람 검수",
                                    origin=fields["origin"], pos=fields["pos"], easy=fields["easy"], review="검수됨")
        kept = [u.strip() for u in usages if u.strip()]
        usage = (update_db.usage_row("live-u-" + entry_id[7:], when, expression, variants, kept, source,
                                     note="사람이 검수 때 고른 용례") if kept else None)
        update_db.append(live / "entries.jsonl", entry, load_lexicon)
        if usage:
            update_db.append(live / "usages.jsonl", usage, lambda path: load_usages([path], missing_ok=False))
        record.update(meaning=entry["meaning"], entry=entry_id)
    live.mkdir(parents=True, exist_ok=True)
    with (live / LOG).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
