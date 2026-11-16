"""Local lexicon and surface retriever. No network, no embedding model.

Entries come from public data (see data/eval/external/SOURCES.md) and are NOT team-reviewed
approvals. The retriever proposes candidates; the probe and the model decide.
"""
import hashlib
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEXICON = ROOT / "data/db/lexicon/lexicon_demo_v1.jsonl"
DEFAULT_EXAMPLES = ROOT / "data/db/lexicon/examples_demo_v1.jsonl"
FIELDS = {"id", "expression", "variants", "meaning", "family", "source", "license"}
# v7: entries written by tracetalk/db/update.py carry the time they were added. v9: the team DB's origin (유래) and
# part of speech (품사), shown on the card and given to the model with the meaning.
OPTIONAL = {"added_at", "origin", "pos", "easy", "review"}  # easy: team-chosen 쉬운 표현 (0.7.3); review (0.8): 검수됨 · 검수 전
EXAMPLE_FIELDS = {"entry_id", "expression", "lines", "source", "license", "note"}


def compact(text):
    # Keep letters (Hangul jamo such as ㅋ, ㅇ are letters) and "-" for emoticons like "ㄱ-".
    return "".join(ch for ch in unicodedata.normalize("NFC", text).lower() if ch.isalnum() or ch == "-")


def jamo(text):
    # NFD splits precomposed Hangul syllables into jamo, so near-variants share trigrams.
    return unicodedata.normalize("NFD", compact(text))


def grams(text, n=3):
    return {text[i:i + n] for i in range(len(text) - n + 1)} or ({text} if text else set())


def load_lexicon(path=None, missing_ok=True):
    path = Path(path or DEFAULT_LEXICON)
    if not path.exists():
        if missing_ok:
            return []
        raise ValueError(f"사전 파일이 없습니다: {path}")
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if (not FIELDS <= set(entry) <= FIELDS | OPTIONAL
                or not all(isinstance(entry[k], str) for k in FIELDS - {"variants"} | (OPTIONAL & set(entry)))
                or not isinstance(entry["variants"], list) or not all(isinstance(v, str) for v in entry["variants"])
                or not entry["expression"].strip() or not entry["meaning"].strip()):
            raise ValueError("사전 항목의 필드를 확인하세요.")
        entries.append(entry)
    return entries



def meaning_sha(meaning):
    return hashlib.sha256(meaning.encode("utf-8")).hexdigest()[:16]


# v9.5 (11-04): easy words a teacher model drafted for DB senses that have none (eval/draft_easy.py), kept in
# their own file and never written into the lexicon. A team's own easy words always win; a draft made for an older
# meaning text is ignored. The card marks drafted easy words "교사 초안 · 검수 전". v9.6 r2: a row may carry every
# try of the draft script (`tries`) for review; the card reads only easy and slot.
EASY_DRAFT_FIELDS = {"entry_id", "expression", "meaning_sha", "easy", "source", "model", "made_at"}
EASY_DRAFT_OPTIONAL = {"error", "check", "slot", "review", "tries"}


def load_easy_drafts(paths, missing_ok=False):
    drafts = {}
    for path in paths:
        if missing_ok and not Path(path).exists():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (not EASY_DRAFT_FIELDS <= set(row) <= EASY_DRAFT_FIELDS | EASY_DRAFT_OPTIONAL
                    or not all(isinstance(row[k], str) for k in EASY_DRAFT_FIELDS)):
                raise ValueError(f"쉬운 표현 초안 파일의 필드를 확인하세요: {path}")
            if row["entry_id"] in drafts:
                raise ValueError(f"쉬운 표현 초안에 같은 항목이 두 번 있습니다: {path}")
            if row["easy"].strip():
                drafts[row["entry_id"]] = row
    return drafts


def with_easy_drafts(lexicon, drafts):
    """(entries, used, stale): entries without easy words take the draft made for their current meaning."""
    out, used, stale = [], 0, 0
    for entry in lexicon:
        draft = drafts.get(entry["id"])
        if entry.get("easy", "").strip() or draft is None:
            out.append(entry)
        elif draft["meaning_sha"] != meaning_sha(entry["meaning"]):
            out.append(entry)
            stale += 1
        else:
            out.append({**entry, "easy": draft["easy"], "easy_source": "draft", "easy_slot": draft.get("slot", "")})
            used += 1
    return out, used, stale


def load_examples(paths, entry_ids):
    """Example lines keyed by lexicon entry id: shown on the screen, never runtime model input; v9.6 the offline
    easy-word drafting (eval/draft_easy.py) reads them to see where a word stands in a sentence."""
    examples = {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if set(row) != EXAMPLE_FIELDS or not isinstance(row["lines"], list) or not row["lines"]:
                raise ValueError(f"예시 파일의 필드를 확인하세요: {path}")
            if row["entry_id"] in entry_ids:
                examples[row["entry_id"]] = row
    return examples

def score(form, text_compact, text_grams):
    key = compact(form)
    if not key:
        return 0.0
    if key in text_compact:
        return 1.0
    g = grams(jamo(form))
    return len(g & text_grams) / len(g)


def retrieve(text, entries, k=5, minimum=0.5):
    text_compact = compact(text)
    text_grams = grams(jamo(text))
    scored = []
    for entry in entries:
        best = max(score(form, text_compact, text_grams) for form in [entry["expression"], *entry["variants"]])
        if best >= minimum:
            scored.append((best, len(compact(entry["expression"])), entry))
    # Exact matches first, then longer expressions (more specific), then lexical order for stability.
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
    return [{"id": e["id"], "expression": e["expression"], "meaning": e["meaning"], "source": e["source"],
             "retrieval_score": round(s, 3), **({"added_at": e["added_at"]} if "added_at" in e else {})}
            for s, _, e in scored[:k]]
