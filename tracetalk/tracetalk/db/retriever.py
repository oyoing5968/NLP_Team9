"""Offline DB retriever (team slide "DB Retriever"; no internet): which DB rows a comment touches, where, and which
of their usages are closest to it. Recall first: the card's candidate MAD decides (K2: MAD resists look-alike rows).

Stages; a stage whose library is missing is skipped, so machines without them get the exact stage only:
  exact     DB forms, variants and inflected verbs as written (tracetalk.mad.card.find)
  morph     kiwipiepy base forms: an irregular or particle-attached word whose lemma is a headword (귀여워 -> 귀엽다)
  fuzzy     rapidfuzz on Hangul jamo: a typo of a form of three or more letters (one jamo edit; two from five
            letters), its first jamo kept; a form of several words is compared with as many words of the comment
  semantic  ChromaDB + an Ollama embedding model: a row's usages ordered by closeness to the comment ("관련 용례
            검색"); it never adds a row by itself
With morph, 0.8 also lists the words the analyzer hardly knows (unknown_words): candidates the model's detection missed,
which the card judges (new word, standard word or name, or not known).
Everything is local; on the Mac the index lives under tracetalk/_mac_runtime/chroma (mac/run.sh).
"""
import hashlib
import json
import re
import urllib.request
from pathlib import Path

from tracetalk.mad.card import find
from tracetalk.db.lexicon import compact, jamo
from tracetalk.db.usage import evidence, stem

try:
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein
except ImportError:  # other machines may not have it
    fuzz = Levenshtein = None
try:
    from kiwipiepy import Kiwi
except ImportError:
    Kiwi = None

STAGES = ("exact", "morph", "fuzzy", "semantic")
# 0.9: a word the analyzer scores very low is one it hardly knows (11-07, fresh_v1-v3: 감튀 -20.1, 케케크롱 and 냐냐냥 about
# -35 as a made-up proper noun; 거제도 -15.8, 경도 -15.6). On those 144 sentences this finds 19 of 26 new-word targets (the
# unknown-id rule alone 15) and flags 15 other words, most of them informal too (뮤비, 엽떡, 직캠, 팀플, 야르); the card decides.
RARE_WORD, MADE_UP_NAME = -19.0, -30.0
COMMON_LATIN = {"AI", "OK", "TV", "PC", "SNS", "PPT", "CEO", "DM", "MT", "OT", "KTX", "BTS", "USB", "CCTV", "ATM", "GPS"}
DEFAULT_CHROMA = Path(__file__).resolve().parents[2] / "_mac_runtime" / "chroma"  # the Mac's one folder
# A typo = one jamo edit (two from five letters). The first rule was a jamo ratio of 85, set before the bench on the
# belief that one edit in three letters scores about 87; without final consonants it is 83 (가즈아 -> 가주아), so the
# rule now says what was meant (11-03; eval/retrieval_bench.py reports both).
def typo_limit(letters):
    return 1 if letters <= 4 else 2


def available():
    """The stages this machine can run."""
    try:
        import chromadb  # noqa: F401
        semantic = True
    except ImportError:
        semantic = False
    return tuple(s for s, ok in (("exact", True), ("morph", Kiwi is not None), ("fuzzy", fuzz is not None),
                                 ("semantic", semantic)) if ok)


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


class OllamaEmbedder:
    """Embeddings from a local Ollama server (/api/embed)."""

    def __init__(self, base_url, model, timeout=60):
        self.url, self.model, self.timeout = base_url.rstrip("/") + "/api/embed", model, timeout

    def __call__(self, texts):
        body = json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())["embeddings"]


class UsageIndex:
    """Usage lines embedded once and kept in a local ChromaDB collection; the comment is embedded per request."""

    def __init__(self, path, embed, name="usages"):
        import chromadb
        from chromadb.config import Settings
        self.embed = embed
        client = (chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False)) if path
                  else chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False)))
        self.collection = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"},
                                                          embedding_function=None)

    @staticmethod
    def key(text):
        return hashlib.sha256(("usage:" + text).encode("utf-8")).hexdigest()[:24]

    def rank(self, group, text, limit):
        """Up to `limit` lines numbered U1.., closest to the comment first; team-added lines (live-) still first."""
        own = compact(text)
        lines = [u for u in group["lines"] if compact(u["text"]) != own]
        if not lines:
            return []
        keys = [self.key(u["text"]) for u in lines]
        known = set(self.collection.get(ids=keys)["ids"])
        new = [(k, u) for k, u in zip(keys, lines) if k not in known]
        if new:
            vectors = self.embed([u["text"] for _, u in new])
            self.collection.upsert(ids=[k for k, _ in new], embeddings=vectors,
                                   documents=[u["text"] for _, u in new])
        query = self.embed([text])[0]
        stored = self.collection.get(ids=keys, include=["embeddings"])
        vec = dict(zip(stored["ids"], stored["embeddings"]))
        norm = lambda v: sum(x * x for x in v) ** 0.5 or 1.0
        q = norm(query)
        score = {k: float(sum(a * b for a, b in zip(query, vec[k])) / (q * norm(vec[k]))) for k in keys}
        order = sorted(zip(keys, lines), key=lambda p: (not p[1]["row"].startswith("live-"), -score[p[0]]))
        return [{"id": f"U{i + 1}", **u, "similarity": round(score[k], 4)} for i, (k, u) in enumerate(order[:limit])]


class Retriever:
    """Hits beyond the exact patterns, and usage ranking. `stages` defaults to what this machine can run."""

    def __init__(self, stages=None, usage_index=None):
        stages = tuple(stages if stages is not None else available())
        unknown = set(stages) - set(STAGES)
        if unknown:
            raise ValueError(f"알 수 없는 검색 단계: {sorted(unknown)}")
        self.kiwi = Kiwi() if "morph" in stages and Kiwi is not None else None
        self.fuzzy = "fuzzy" in stages and fuzz is not None
        self.usage_index = usage_index if "semantic" in stages else None
        self.stages = tuple(s for s in stages if s == "exact" or (s == "morph" and self.kiwi)
                            or (s == "fuzzy" and self.fuzzy) or (s == "semantic" and self.usage_index))

    def hits(self, text, entries):
        """[{start, end, span, entry, stage, score}]: exact hits, then morph and fuzzy hits that overlap none."""
        chosen = [{**h, "stage": "exact", "score": 100} for h in find(text, entries)]
        forms = {}
        for entry in entries:
            for form in [entry["expression"], *entry["variants"]]:
                key = compact(form)
                if len(key) >= 2:
                    forms.setdefault(key, (entry, len(form.split())))
        extra = (self.morph_hits(text, forms) if self.kiwi else []) + (self.fuzzy_hits(text, forms) if self.fuzzy else [])
        for hit in sorted(extra, key=lambda h: (-h["score"], h["start"])):
            if not any(overlaps(hit, c) for c in chosen) and all(hit["entry"] is not c["entry"] for c in chosen):
                chosen.append(hit)
        return sorted(chosen, key=lambda h: h["start"])

    def unknown_words(self, text):
        """Words the analyzer hardly knows: Hangul nouns of two letters or more with its unknown-word id 2 (0.8; 11-05 on
        the Mac: 두쫀쿠, 엠비스찬, 테토남이네, 일세스코, 감다살, 중도런, 야르 had it; 이쑤시개, 할렐루야, 샤갈, 아이유, 김치찌개
        did not), and 0.9 one it made up a proper noun for, a noun or root it scores very low, or a word in capitals
        (HMH). A name the analyzer lacks comes too; the card can call it a standard word or name. An ending the unknown
        word swallowed is left out (무지컬이네 -> 무지컬)."""
        if not self.kiwi:
            return []
        out = []
        for token in self.kiwi.tokenize(text):
            form = text[token.start:token.start + token.len]
            hangul = len(form) >= 2 and re.fullmatch(r"[가-힣]+", form)
            word = (hangul and ((token.id == 2 and token.tag.startswith("NN")) or (token.tag == "NNP" and token.score <= MADE_UP_NAME)
                                or (token.tag in ("NNG", "NNP", "XR") and token.score <= RARE_WORD)))
            if word or (token.tag == "SL" and re.fullmatch(r"[A-Z]{2,}", form) and form not in COMMON_LATIN):
                size = len(stem(form)) if hangul else len(form)
                out.append({"start": token.start, "end": token.start + size, "span": form[:size]})
        return out

    def morph_hits(self, text, forms):
        out = []
        for token in self.kiwi.tokenize(text):
            if token.tag.startswith(("VV", "VA")):
                lemma = token.form + "다"
            elif token.tag.startswith(("NN", "XR")):
                lemma = token.form
            else:
                continue
            entry, words = forms.get(compact(lemma), (None, 0))
            if entry is None or words != 1:
                continue
            start, end = token.start, token.start + token.len
            while end < len(text) and re.match(r"[가-힣]", text[end]) and text[end - 1] != " ":  # the whole word
                end += 1
            out.append({"start": start, "end": end, "span": text[start:end], "entry": entry, "stage": "morph",
                        "score": 95})
        return out

    def fuzzy_hits(self, text, forms):
        """A form typed with a typo: the comment's letters from a word start, as many words as the form has,
        compared on jamo; the first jamo must agree. Score = 100 - 10 x edits."""
        letters = [(i, ch) for i, ch in enumerate(text) if ch.isalnum()]  # with where each one sits
        starts = [k for k, (i, _) in enumerate(letters) if i == 0 or not text[i - 1].isalnum()]  # a word's first letter
        out = []
        for key, (entry, n_words) in forms.items():
            if len(key) < 3 or not re.fullmatch(r"[가-힣]+", key):
                continue
            target, limit = jamo(key), typo_limit(len(key))
            best = None
            for k in starts:
                start = letters[k][0]
                for size in (len(key) - 1, len(key), len(key) + 1):
                    if size < 3 or k + size > len(letters):
                        continue
                    end = letters[k + size - 1][0] + 1
                    if len(text[start:end].split()) != n_words:
                        continue
                    cand = "".join(ch for _, ch in letters[k:k + size])
                    if cand == key or jamo(cand)[:1] != target[:1]:
                        continue
                    edits = Levenshtein.distance(jamo(cand), target)
                    if edits <= limit and (best is None or edits < best[0]):
                        best = (edits, start, end)
            if best:
                edits, start, end = best
                out.append({"start": start, "end": end, "span": text[start:end], "entry": entry, "stage": "fuzzy",
                            "score": 100 - 10 * edits})
        return out

    def evidence(self, group, text, limit):
        """Usage lines for one row: closest to the comment with the semantic stage, else tracetalk.db.usage.evidence."""
        if self.usage_index is not None:
            try:
                return self.usage_index.rank(group, text, limit)
            except Exception:  # the embedding server is down: same lines as without the stage
                pass
        return evidence(group, text, limit)

    def rows(self, text, entries, limit=20, usages=12):
        """Team-format rows (docs/TEAM_MODULE.md) for the comment, each with where and how it matched."""
        out = []
        for hit in self.hits(text, entries)[:limit]:
            entry = hit["entry"]
            group = entry.get("usage_group")
            lines = self.evidence(group, text, usages) if group else []
            out.append({"expression": entry["expression"], "variants": entry["variants"],
                        "senses": [{**{k: s.get(k, "") for k in ("meaning", "origin", "pos", "source", "added_at", "easy")},
                                    "review": s.get("review", "검수됨")} for s in entry["senses"]],
                        "usages": [{k: u.get(k, "") for k in ("text", "context", "source", "added_at")} for u in lines],
                        "match": {k: hit[k] for k in ("span", "start", "end", "stage", "score")}})
        return out


def build(base_url, embed_model="bge-m3", chroma=None, log=print):
    """The retriever with every stage this machine has; semantic needs chromadb and the embedding model served by the
    same local Ollama. Used by tracetalk/web/run.py and eval/run_bench.py with --retriever auto."""
    stages = available()
    index = None
    if "semantic" in stages:
        embed = OllamaEmbedder(base_url, embed_model)
        try:
            embed(["확인"])
            index = UsageIndex(chroma or DEFAULT_CHROMA, embed)
        except OSError as exc:
            log(f"의미 검색 끔: 임베딩 모델 {embed_model}에 연결하지 못했습니다 ({exc}).")
    retriever = Retriever(stages, usage_index=index)
    log(f"DB 검색기 단계: {', '.join(retriever.stages)}")
    return retriever
