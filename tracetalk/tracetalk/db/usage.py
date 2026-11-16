"""Observed usages of an expression, and the live store the update tool writes (v7, 11-01).

A usage row is one source's lines for one expression. Lines are evidence the model may cite by
number (U1, U2, ...); they are NOT dictionary meanings and NOT team approvals. KoCulture-Dialogues
lines were drafted by an LLM and reviewed by people, so they are realistic usages, not observed
SNS posts; every line keeps its source and note so the screen can say so.

    {"id", "expression", "variants", "lines": [{"text", "context"}], "source", "license", "note", "added_at"}
"""
import hashlib
import json
from pathlib import Path

from tracetalk.db.lexicon import compact, load_easy_drafts, load_lexicon, with_easy_drafts

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USAGES = ROOT / "data/db/usage/usages_demo_v1.jsonl"
LIVE_DIR = ROOT / "data/db/live"
FIELDS = {"id", "expression", "variants", "lines", "source", "license", "note", "added_at"}


def load_usages(paths, missing_ok=True):
    """Rows from every file, merged by expression (the same word from two sources is one group)."""
    groups = {}
    for path in map(Path, paths):
        if not path.exists():
            if missing_ok:
                continue
            raise ValueError(f"용례 파일이 없습니다: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (set(row) != FIELDS or not isinstance(row["expression"], str) or not row["expression"].strip()
                    or not isinstance(row["variants"], list) or not all(isinstance(v, str) for v in row["variants"])
                    or not isinstance(row["lines"], list)
                    or not all(isinstance(row[k], str) for k in ("id", "source", "license", "note", "added_at"))):
                raise ValueError(f"용례 항목의 필드를 확인하세요: {path}")
            group = groups.setdefault(compact(row["expression"]), {
                "id": row["id"], "expression": row["expression"], "variants": [], "lines": []})
            group["variants"] = sorted(set(group["variants"]) | set(row["variants"]))
            seen = {compact(u["text"]) for u in group["lines"]}
            for item in row["lines"]:
                if (not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip()
                        or not isinstance(item.get("context", ""), str)):
                    raise ValueError(f"용례 문장을 확인하세요: {path}")
                if compact(item["text"]) not in seen:
                    seen.add(compact(item["text"]))
                    group["lines"].append({"text": item["text"], "context": item.get("context", ""),
                                           "row": row["id"], "source": row["source"], "license": row["license"],
                                           "note": row["note"], "added_at": row["added_at"]})
    return list(groups.values())


def retrieve_usages(text, groups, k=2, shortest=2):
    """Groups whose expression (or a variant) of two or more letters occurs in the comment as written
    (spaces and punctuation ignored), longest expression first.

    Literal substrings only. The lexicon's jamo-trigram score is 1.0 even when the trigrams are scattered
    ("야르" in "고양이야를"), and one-letter forms (보, 각, 갓) occur everywhere (11-01 review).
    """
    text_compact = compact(text)
    found = [g for g in groups
             if any(len(compact(f)) >= shortest and compact(f) in text_compact for f in [g["expression"], *g["variants"]])]
    found.sort(key=lambda g: (-len(compact(g["expression"])), g["id"]))
    return [{**g, "retrieval_score": 1.0} for g in found[:k]]


def evidence(group, text, limit=6):
    """Up to `limit` lines numbered U1.., the same for every method and seed. The comment itself is left out.

    Lines the team added with tracetalk/db/update.py (rows "live-...") come first: they are the update being shown.
    """
    own = compact(text)
    lines = [u for u in group["lines"] if compact(u["text"]) != own]
    lines.sort(key=lambda u: (not u["row"].startswith("live-"),
                              hashlib.sha256(("usage:" + u["text"]).encode("utf-8")).hexdigest()))
    return [{"id": f"U{i+1}", **u} for i, u in enumerate(lines[:limit])]


def for_model(lines):
    """What the model reads: number, sentence, the message it answered, and where it came from."""
    return [{"id": u["id"], "text": u["text"], "context": u["context"], "source": u["source"]} for u in lines]


class LiveStore:
    """Lexicon and usage files, reread when any of them changes, so an update needs no restart."""

    def __init__(self, lexicon_paths=(), usage_paths=(), easy_draft_paths=(), candidates_path=None):
        self.lexicon_paths, self.usage_paths = list(map(Path, lexicon_paths)), list(map(Path, usage_paths))
        self.easy_draft_paths = list(map(Path, easy_draft_paths))  # v9.5: teacher drafts, marked on the card
        self.stamp, self.lexicon, self.usages = None, [], []
        self.corpus, self.corpus_stamp = None, None
        # 0.8 collector: what the cards met that the DB does not have (tracetalk/db/update.py queue turns it into a sheet)
        self.candidates_path = Path(candidates_path) if candidates_path else None

    def posts(self):
        """0.9: the fetched posts (data/db/live/corpus.jsonl beside the collector's file), reread when the file changes."""
        path = self.candidates_path.parent / "corpus.jsonl" if self.candidates_path else None
        stamp = path.stat().st_mtime_ns if path and path.exists() else None
        if stamp != self.corpus_stamp or self.corpus is None:
            from tracetalk.evidence import corpus
            self.corpus, self.corpus_stamp = (corpus.load(path) if stamp else corpus.Corpus()), stamp
        return self.corpus

    def collect(self, result):
        """Append one row per card item the DB could not settle: a word it does not have (headword None), or a known
        word read with a meaning it does not have (choice N). Local only (data/db/live is never shared)."""
        if not self.candidates_path:
            return 0
        rows = candidate_rows(result)
        if rows:
            self.candidates_path.parent.mkdir(parents=True, exist_ok=True)
            with self.candidates_path.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            # v18: a word the card could not settle with no post behind it (not an ordinary word) asks the auto-update
            # (mac/auto_update.sh, when on) to look for new posts soon. Only this mark: the crawler fetches the allowed newsletters'
            # new posts and never sends the word anywhere.
            if any(r["choice"] != "L" and not r.get("posts") for r in rows):
                (self.candidates_path.parent / "update_wanted").touch()
        return len(rows)

    def update_state(self):
        """v18: the last look for new posts (mac/crawl_new.sh writes update_state.json beside the posts), or None."""
        path = self.candidates_path.parent / "update_state.json" if self.candidates_path else None
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None
        except ValueError:
            return None

    def current(self):
        watched = self.lexicon_paths + self.usage_paths + self.easy_draft_paths + (
            [self.candidates_path] if self.candidates_path else [])
        stamp = tuple((str(p), p.stat().st_mtime_ns if p.exists() else None) for p in watched)
        if stamp != self.stamp:
            lexicon = [e for p in self.lexicon_paths for e in load_lexicon(p)]
            if len({e["id"] for e in lexicon}) != len(lexicon):
                raise ValueError("사전 파일들 사이에 같은 id가 있습니다.")
            if self.easy_draft_paths:
                lexicon, _, _ = with_easy_drafts(lexicon, load_easy_drafts(self.easy_draft_paths, missing_ok=True))
            usages = load_usages(self.usage_paths)
            if self.candidates_path and self.candidates_path.exists():  # 0.8.1: what was collected feeds back
                rows = [json.loads(s) for s in self.candidates_path.read_text(encoding="utf-8").splitlines() if s.strip()]
                usages = merge_groups(usages, collected_groups(rows, [e["expression"] for e in lexicon]))
            self.lexicon, self.usages, self.stamp = lexicon, usages, stamp
        return self.lexicon, self.usages


# 0.8 collector: endings a span the analyzer or the model cut too long may carry (테토남이네 -> 테토남). Only endings of
# two letters or more: a word may itself end in 이 or 가 (잼민이).
ENDINGS = tuple(sorted(("이네", "이야", "이다", "이라서", "이에요", "이었음", "이었어", "이잖아", "이랑", "인데", "이지",
                        "이고", "이면", "이라", "으로", "에서", "한테", "까지", "처럼", "보다", "이네요", "이래"),
                       key=len, reverse=True))


def stem(word):
    """The word without one such ending, when two letters or more are left."""
    key = compact(word)
    for ending in ENDINGS:
        if key.endswith(ending) and len(key) - len(ending) >= 2:
            return key[:-len(ending)]
    return key


COLLECTED_MIN_TEXTS = 2


def collected_groups(rows, known=(), min_texts=COLLECTED_MIN_TEXTS):
    """0.8.1: the collector's rows as usage groups, so the next card reads them (해석하면서 쌓기). A word the DB has no
    meaning for (known: the DB's expressions), seen in at least `min_texts` different comments that the card did not
    judge standard (choice L), becomes one group of those comments. They are "검수 전" evidence the model may cite by
    number, never a meaning; the card that is reading one of them leaves it out (usage.evidence)."""
    known = {stem(k) for k in known}
    by = {}
    for r in rows:
        if r.get("choice") == "L" or r.get("status") == "failed" or not str(r.get("text", "")).strip():
            continue
        key = stem(r.get("headword") or r["expression"])
        if len(key) < 2 or key in known:
            continue
        g = by.setdefault(key, {"forms": {}, "lines": {}})
        g["forms"][r["expression"]] = g["forms"].get(r["expression"], 0) + 1
        g["lines"].setdefault(compact(r["text"]), r)
    for key in [k for k in by if k.endswith("이") and k[:-1] in by]:  # 젬민이네 -> 젬민 and 젬민이: one word
        short = by.pop(key[:-1])
        for form, n in short["forms"].items():
            by[key]["forms"][form] = by[key]["forms"].get(form, 0) + n
        for text, r in short["lines"].items():
            by[key]["lines"].setdefault(text, r)
    groups = []
    for key, g in sorted(by.items()):
        if len(g["lines"]) < min_texts:
            continue
        forms = sorted(g["forms"], key=lambda f: (compact(f) != key, -g["forms"][f], f))
        rid = "col-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
        groups.append({"id": rid, "expression": forms[0], "variants": forms[1:],
                       "lines": [{"text": r["text"], "context": "", "row": rid, "source": "수집기(카드 입력)",
                                  "license": "로컬 수집", "note": "검수 전: 카드에 들어온 문장", "added_at": r.get("at", "")}
                                 for r in g["lines"].values()]})
    return groups


def merge_groups(groups, extra):
    """Usage groups merged by expression, as load_usages merges files."""
    out = {compact(g["expression"]): {**g, "variants": list(g["variants"]), "lines": list(g["lines"])} for g in groups}
    for g in extra:
        have = out.get(compact(g["expression"]))
        if have is None:
            out[compact(g["expression"])] = g
            continue
        have["variants"] = sorted(set(have["variants"]) | set(g["variants"]))
        seen = {compact(u["text"]) for u in have["lines"]}
        have["lines"] += [u for u in g["lines"] if compact(u["text"]) not in seen]
    return list(out.values())


def candidate_rows(result, when=None):
    """0.8 collector rows from one card result (tracetalk.mad.card); also used on benchmark runs (tracetalk/db/update.py queue --runs)."""
    card = result.get("card") or {}
    text = (result.get("request") or {}).get("text", "")
    when = when or result.get("created_at", "")
    rows = []
    for it in card.get("items") or []:
        if it.get("status") == "failed" or it.get("choice") == "L":
            continue
        if it.get("headword") is None or it.get("choice") == "N":
            rows.append({"expression": it["expression"], "headword": it.get("headword"), "text": text,
                         "choice": it.get("choice"), "status": it.get("status"), "meaning": it.get("meaning", ""),
                         "easy": it.get("easy", ""), "decided_by": it.get("decided_by"),
                         "mad_reason": it.get("mad_reason"), "at": when,
                         "input_sha256": result.get("input_sha256", ""),
                         "post_meaning": it.get("post_meaning", ""), "posts": it.get("posts", [])})
    for word in card.get("unexplained") or []:  # 0.9: slang by the probe, nothing behind it, beside a word the DB knows
        rows.append({"expression": word, "headword": None, "text": text, "choice": "N", "status": "uncertain", "meaning": "", "easy": "",
                     "decided_by": "read", "mad_reason": None, "at": when, "input_sha256": result.get("input_sha256", ""), "post_meaning": "", "posts": []})
    for word in (result.get("detection") or {}).get("ordinary_words") or []:  # judged a standard word: kept as a count
        rows.append({"expression": word, "headword": None, "text": text, "choice": "L", "status": "proposed",
                     "meaning": "", "easy": "", "decided_by": None, "mad_reason": None, "at": when,
                     "input_sha256": result.get("input_sha256", "")})
    return rows
