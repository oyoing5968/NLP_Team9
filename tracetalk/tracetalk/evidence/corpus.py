"""근거 글 (0.9, docs/DESIGN.md): the posts the crawler fetched, kept as plain text and searched when a card meets a word.

The 4B does not know a new word, but it can read: told only the comment it got 2 of 26 new words right; given the passages of
the fetched posts that mention the word it read the meaning of about 15 of 20 (dev, 11-07). Extracting a whole DB from the
posts beforehand was much worse (precision 48-76%, docs/CRAWLER.md), and it had to guess which words mattered. So the posts
stay as evidence: one word, its passages, one question, and the card says which post it read. A post is data, never instructions.

    {"url", "date", "fetched", "blocks": [{"kind": "h"|"p", "text"}]}   one per line in data/db/live/corpus.jsonl
"""
import json
import re
from pathlib import Path

from tracetalk.crawl import extract as crawl
from tracetalk.db.lexicon import compact

MAX_PASSAGE = 520
FURNITURE = re.compile(r"구독하기|비밀번호로 로그인|문의하기|뉴스레터 구독|커피와 쪽지|메일리가 전달|보내시는 분|이미 구독|Trend A Word는|조회 \d|이미지 =|^출처|^from\.|로딩")
GREETING = re.compile(r"안녕[!,.~ ]|에디터 |다들 감기|오늘의 트렌드어워드")
DEFINING = re.compile(r"[:：]\s*\S|\(.{1,30}\)|[은는]\s|이란|라는|란\s")
QUOTES = re.compile(r"[‘'“\"「『]([^’'”\"」』\n]{2,40})[’'”\"」』]")
DATED_TITLE = re.compile(r"^\d{2}\.\d{2}\.\d{2}\s*\(.\)\s*")
USE_PART = re.compile(r"이렇게 활용|활용해 보세요|어떻게 활용|활용 방법|활용법")
# v13: a roundup's bulleted heading (🚨 체포하겠어) and what is not a word's heading in it
BULLET = re.compile(r"^\s*(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+|\d️⃣)\s*")
NOT_HEADWORD = re.compile(r"[~?/:—!,·\[\]]|OO|○○|어떤|어떻게|인사이트|활용|용례|브랜드|브랜딩|구독|다양한|궁금|모음|한 단어|Trend A Word|득이 되는|"
                          r"수확|정답|유래|원곡|모아보기|공식|레퍼토리|맥락|트렌드|모먼트|방식|요소|마케터|카피|미학|매력|포인트|들어오세요|클릭|당장|비교")
WHAT_PART = re.compile(r"\W*어떤 밈인가요\W*|\W*MEME PREVIEW.*|용례|활용")
TOPIC = re.compile(r"[’'”\"」』)]*\s*(?:은|는|이란|란|이라는|라는)\s")  # v15: right after the word, the sentence is about it


def post_of(path, url=""):
    page = crawl.read_page(path)
    blocks = [{"kind": b["kind"], "text": b["text"]} for b in crawl.main_blocks(page["blocks"]) if not FURNITURE.search(b["text"])]
    return {"url": page["url"] or url, "date": page["date"], "blocks": blocks}


HEADING_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})\s*\(.\)|위픽레터\s*(20\d{2})\.(\d{2})\.(\d{2})")


def post_date(post):
    """v15: the post's date, else the one its heading gives (a Trend A Word post carries it only in "26.11.05 (목) '낱말'", a 위픽레터
    post in "위픽레터2025.02.25"); "" when neither does (a 파밍레터 page names none). Never guessed."""
    if post.get("date"):
        return post["date"]
    for b in post["blocks"][:12]:
        m = HEADING_DATE.search(b["text"])
        if m:
            y, mo, d = (("20" + m.group(1), m.group(2), m.group(3)) if m.group(1) else m.group(4, 5, 6))
            return f"{y}-{mo}-{d}"
    return ""


def _title_names(post, key):
    """The post is about this one word: its dated heading names it (a one-word newsletter). A roundup whose title borrows a meme is not."""
    return any(DATED_TITLE.match(b["text"]) and key in compact(b["text"]) for b in post["blocks"][:12])


def _section(blocks, i):
    """What explains a heading or short line: the blocks after it up to the next heading, not the part on how brands can use it."""
    out = []
    for j in range(i + 1, min(i + 8, len(blocks))):
        b = blocks[j]
        if b["kind"] == "h" or USE_PART.search(b["text"]):
            break
        if len(b["text"]) >= 12 and not GREETING.search(b["text"]) and not WHAT_PART.fullmatch(b["text"].strip()):
            out.append(j)
    return out


def _score(block, key, about):
    text, named = block["text"], key in compact(block["text"])
    score = 0.0
    if named and crawl.STRONG.search(text):
        score += 4
    elif about and crawl.STRONG.search(text):
        score += 3  # a one-word post explains the word without naming it again
    if named and DEFINING.search(text[max(0, text.find(key[:2]) - 2):]):
        score += 1
    if block["kind"] == "p" and len(text) >= 40:
        score += 1
    use = "활용" in text
    if named and use and not USE_PART.search(text):  # v15: a sentence presenting the word as its topic ("'3일팅'은 ...") explains it even when
        # another sentence of the block says 활용 (3일팅: "2초짜리 일상 영상을 활용한 소개팅이에요. 최근 주목받은 '3일팅'은 5:5 ...")
        from tracetalk.evidence.reading import form_regex
        topics = [s for s in re.split(r"(?<=[.!?])\s+", text) if key in compact(s) and "활용" not in s
                  and any(TOPIC.match(s[m.end():]) for m in re.finditer(form_regex(key), s))]
        use = not topics
    if GREETING.search(text) or "정답은" in text or "브랜드" in text or use:
        score -= 2
    return score


def _passage(post, key, about):
    """The post's best text for this word: a heading or short line that names it with the section under it, or the blocks that explain it,
    in reading order."""
    blocks = post["blocks"]
    picks, under = {}, set()  # under: v16, the blocks that stand under a heading or short line naming the word (its section)
    for i, b in enumerate(blocks):
        named = key in compact(b["text"])
        if not named and not about:
            continue
        s = _score(b, key, about)
        if s <= 0 and not named:
            continue
        picks[i] = max(picks.get(i, -9), s)
        # v16: a heading or short line that itself says what the word is ("빤히 - 두쫀쿠 (두바이 쫀득 쿠키)") ranks with the section under
        # it. It ranked below the lines it introduced, so the passage kept them and dropped the one line with the expansion.
        says = named and DEFINING.search(b["text"][max(0, b["text"].find(key[:2]) - 2):])
        if named and b["kind"] == "h":
            for j in _section(blocks, i):
                picks[j] = max(picks.get(j, -9), 5.0)
                under.add(j)
            if says:
                picks[i] = max(picks[i], 5.0)
        elif named and len(b["text"]) < 60:  # a short line in a flat post: only what comes right after it
            for j in _section(blocks, i)[:2]:
                picks[j] = max(picks.get(j, -9), s + 0.5)
                under.add(j)
            if says:
                picks[i] = max(picks[i], s + 0.5)
    if about and max(picks.values(), default=0) < 1.5:  # v14: the word's own dated post that would not be read at all (below tau_passage)
        # because no block marks an explanation (존박 맥도날드 랩: the body writes "존박의 '맥도날드 랩'"): its paragraphs explain the word.
        # Only then: adding them where a block already explains it blurred the 4B's reading (dev fresh_v5: 산사 turned to "온라인 게임")
        for i, b in enumerate(blocks):
            t = b["text"]
            if (b["kind"] == "p" and len(t) >= 40 and not GREETING.search(t) and not USE_PART.search(t) and "브랜드" not in t
                    and "정답은" not in t):
                picks[i] = max(picks.get(i, -9), 2.0)
    if not picks:
        return None
    best = sorted(picks, key=lambda i: (-picks[i], i))[:5]
    chosen, size = [], 0
    for i in best:
        t = blocks[i]["text"]
        if size + len(t) > MAX_PASSAGE and chosen:
            continue
        chosen.append(i)
        size += len(t)
    text = " ".join(blocks[i]["text"] for i in sorted(chosen))
    if len(text) > MAX_PASSAGE:  # one long block: keep the part around the word
        at = text.find(key[:2])
        start = max(0, at - 160) if at >= 0 else 0
        text = text[start:start + MAX_PASSAGE]
    # v16, what a quote from it may lean on: about, the post is about this one word (its title names it); key, the form it was found by;
    # sections, the parts of the text that stand under a heading or short line naming the word. A sentence there explains the word
    # without naming it again (a meme roundup: "🚨 놉놉" and its lines; dev v16d gave 13 true quotes up for not naming the word)
    sections = [blocks[i]["text"] for i in sorted(chosen) if i in under or _topic(blocks[i]["text"], key)]
    return {"text": text, "score": max(picks[i] for i in chosen), "url": post["url"], "date": post_date(post), "about": about,
            "key": key, "sections": sections}


def _topic(text, key):
    """v16: the block presents the word as what it is about ("최근 주목받은 '3일팅'은 ..."), not only by name in passing ("'야르'라는
    신조어 하나로"): its other sentences go on about the word."""
    from tracetalk.evidence.reading import form_regex
    return any(re.match(r"[’'”\"」』)]*\s*(?:은|는|이란|란)\s", text[m.end():]) for m in re.finditer(form_regex(key), text))


class Corpus:
    def __init__(self, posts=()):
        self.posts = [p for p in posts if p.get("blocks")]
        self._compact = [[compact(b["text"]) for b in p["blocks"]] for p in self.posts]
        self._terms = None

    def __len__(self):
        return len(self.posts)

    def passages(self, expression, variants=(), limit=3):
        """Up to `limit` passages from different posts, the most explaining first: [{text, url, date, score}]."""
        keys = [k for k in dict.fromkeys(compact(f) for f in [expression, *variants]) if len(k) >= 2]
        out = []
        for post, texts in zip(self.posts, self._compact):
            key = next((k for k in keys if any(k in t for t in texts)), None)
            if key is None:
                continue
            found = _passage(post, key, _title_names(post, key))
            if found:
                out.append(found)
        out.sort(key=lambda p: (-p["score"], -len(p["text"])))
        seen, kept = set(), []
        for p in out:
            head = p["text"][:60]
            if head not in seen:
                seen.add(head)
                kept.append(p)
        return kept[:limit]

    def terms(self):
        """What the posts put in quotes or name in a dated heading: {compact form: as written}, three letters or more."""
        if self._terms is None:
            found = {}
            for post in self.posts:
                for b in post["blocks"]:
                    for m in QUOTES.finditer(b["text"]):
                        form = m.group(1).strip()
                        key = compact(form)
                        if 3 <= len(key) <= 36 and re.search(r"[가-힣A-Za-z]", key):
                            found.setdefault(key, form)
            self._terms = found
        return self._terms

    def headwords(self):
        """v13: what a post presents as the word it is about: the quoted word of a one-word newsletter's dated heading ('산사' in
        26.11.02 (월) '산사') and the bulleted headings of a meme roundup (🚨 체포하겠어). {compact form: as written}, two letters or
        more. A word this new is in no DB and often looks like a standard word (산사 is also a mountain temple): the card checks it."""
        if getattr(self, "_headwords", None) is None:
            found = {}
            for post in self.posts:
                title = " ".join(b["text"] for b in post["blocks"][:12] if b["kind"] == "h")
                roundup = "밈" in title
                for b in post["blocks"]:
                    if b["kind"] != "h":
                        continue
                    forms = []
                    if DATED_TITLE.match(b["text"]):
                        forms = [m.group(1).strip() for m in QUOTES.finditer(b["text"])]
                    elif roundup and BULLET.match(b["text"]):
                        forms = [re.sub(r"\s*\([^)]*\)\s*$", "", BULLET.sub("", b["text"])).strip()]
                    for form in forms:
                        key = compact(form)
                        if 2 <= len(key) <= 24 and re.search(r"[가-힣A-Za-z]", key) and not NOT_HEADWORD.search(form):
                            found.setdefault(key, form)
            self._headwords = found
        return self._headwords

    def headword_hits(self, text):
        """Where the comment names a headword on its own (not the start of a longer word): [{start, end, span}], longest first,
        not overlapping."""
        from tracetalk.evidence.reading import PARTICLE, form_regex
        hits = []
        for key, form in sorted(self.headwords().items(), key=lambda kv: -len(kv[0])):
            for m in re.finditer(form_regex(form), text):
                rest = text[m.end():]
                before = text[:m.start()]
                if (not rest or not re.match(r"[가-힣]", rest[:1]) or PARTICLE.match(rest)) and not re.search(r"[가-힣A-Za-z]$", before):
                    if all(m.end() <= h["start"] or m.start() >= h["end"] for h in hits):
                        hits.append({"start": m.start(), "end": m.end(), "span": m.group(0)})
                    break
        return sorted(hits, key=lambda h: h["start"])

    def phrase_hits(self, text, min_words=2):
        """Stretches of several words of the comment that the posts quote as a phrase (a line-long meme no word rule finds):
        [{start, end, span}], longest first and not overlapping. Spaces do not count. The card still judges each."""
        words = list(re.finditer(r"\S+", text))
        terms = self.terms()
        hits = []
        for i in range(len(words)):
            for j in range(min(len(words), i + 9), i + min_words - 1, -1):
                start, end = words[i].start(), words[j - 1].end()
                span = text[start:end]
                key = compact(re.sub(r"[.,!?~…ㅋㅎㅠㅜ]+$", "", span))
                if key in terms:
                    hits.append({"start": start, "end": start + len(span.rstrip(".,!?~…ㅋㅎㅠㅜ")), "span": span.rstrip(".,!?~…ㅋㅎㅠㅜ")})
                    break
        hits.sort(key=lambda h: -(h["end"] - h["start"]))
        kept = []
        for h in hits:
            if all(h["end"] <= k["start"] or h["start"] >= k["end"] for k in kept):
                kept.append(h)
        return sorted(kept, key=lambda h: h["start"])


def load(path):
    path = Path(path)
    if not path.exists():
        return Corpus()
    return Corpus([json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()])


def add_pages(folder, out, when=""):
    """Plain text of the pages the audit passed (audit.jsonl beside them), appended to the corpus; a post already in is left.
    Only text goes in: scripts and markup never leave the page (crawl.read_page). -> (added, skipped)."""
    folder, out = Path(folder), Path(out)
    audit = folder / "audit.jsonl"
    allowed = None
    if audit.exists():
        allowed = {r["file"] for r in map(json.loads, audit.read_text(encoding="utf-8").splitlines()) if r.get("verdict") == "ok"}
    have = {json.loads(s)["url"] for s in out.read_text(encoding="utf-8").splitlines() if s.strip()} if out.exists() else set()
    sources = crawl.load_sources()
    rows, skipped = [], 0
    for path in sorted(folder.glob("*.html")):
        if allowed is not None and path.name not in allowed:
            skipped += 1
            continue
        post = post_of(path)
        if not post["url"] or not crawl.allowed(post["url"], sources) or post["url"] in have or not post["blocks"]:
            skipped += 1
            continue
        have.add(post["url"])
        rows.append({**post, "fetched": when})
    if rows:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return len(rows), skipped
