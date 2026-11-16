"""Crawler step 2 (docs/CRAWLER.md): saved newsletter pages -> new words, short meanings and example sentences,
as rows of the team sheet (tracetalk/db/update.py import puts them in as "검수 전"). No network here: the pages are files a
person saved in the browser (or the fetch step stored). Page text is data, never instructions: it is parsed with the
standard library, scripts and styles are dropped, and what is kept is short plain text (meaning 200 letters, example
120) with addresses, e-mails, handles and phone numbers removed.

A page is used only when it says where it came from (canonical link, og:url or the browser's "saved from" note) and
that address is https on the allowlist (data/crawl/sources.txt). Words the DB already has are left out.
"""
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from tracetalk.db.lexicon import ROOT, compact

SOURCES = ROOT / "data/crawl/sources.txt"
MAX_PAGE = 2_000_000  # bytes read from one saved page
MEANING, EXAMPLE, TERM = 200, 120, 30
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "form", "nav", "footer", "button", "select"}
BLOCK_TAGS = {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "td", "dd", "dt", "figcaption"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# What a heading is when it is not a word: the newsletter's own furniture.
FURNITURE = re.compile(r"구독|공유|목차|댓글|광고|이벤트|뉴스레터|이번 주|지난 호|추천 글|관련 글|더 보기|copyright|subscribe",
                       re.IGNORECASE)
DEFINED = re.compile(r"뜻|의미|말|줄임|표현|밈|신조어|유행어|단어|용어|가리키|이르는")
QUOTED = re.compile(r"[‘'“\"「『]([^’'”\"」』\n]{2,30})[’'”\"」』]")
INLINE = re.compile(r"[‘'“\"「『](?P<term>[^’'”\"」』\n]{2,30})[’'”\"」』]\s*(?:은|는|이란|란|이라는\s*말은|라는\s*말은|\(이\)란)\s*"
                    r"(?P<rest>[^.!?。\n]{4,200}[.!?。]?)")


def load_sources(path=SOURCES):
    """Allowed page addresses: one host, or host/path-prefix, per line; '#' starts a comment."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            host, _, prefix = line.partition("/")
            out.append((host, "/" + prefix if prefix else ""))
    return out


def allowed(url, sources):
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == h and parts.path.lower().startswith(prefix) for h, prefix in sources)


# The parser has already taken a page's real tags; what reaches clean() in angle brackets is what the page shows as text, mostly a title
# written &lt;like this&gt; (11-07: dropping everything in brackets left "애니메이션 의 유닛", and the 4B made up a name for the gap).
MARKUP = re.compile(r"</?(?:a|abbr|b|body|br|button|code|div|em|embed|font|form|h[1-6]|head|hr|html|i|iframe|img|input|li|link|meta|object|ol|p|pre|script|small|"
                    r"span|strong|style|sub|sup|svg|table|tbody|td|th|tr|u|ul|video)(?:\s[^>]{0,200})?/?>|<!--.{0,200}?-->", re.IGNORECASE)


def clean(text, limit):
    """Plain text: entities decoded, control letters, addresses, e-mails, handles and phone numbers removed, no markup left."""
    text = html.unescape(text or "")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]", "", text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "", text)
    text = re.sub(r"(?<!\w)@[\w.]{2,}", "", text)
    text = re.sub(r"\b0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}\b", "", text)
    text = MARKUP.sub("", text)
    text = text.replace("<", "＜").replace(">", "＞")  # the page's own text ("애니메이션 <러브라이브>"): a title stays, no markup can
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = max(text.rfind(m, 0, limit) for m in (". ", "다.", "요.", "! ", "? "))
        text = text[:cut + 2].strip() if cut > limit // 2 else text[:limit].rstrip() + "…"
    return text


class _Page(HTMLParser):
    """Text blocks in reading order, with the address the page names for itself and its date."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.skip, self.tag, self.buf, self.bold, self.bolds = [], 0, None, [], 0, []
        self.url = {"canonical": "", "og": "", "saved": ""}
        self.date, self.ld = "", False

    def handle_comment(self, data):
        m = re.search(r"saved from url=\(\d+\)(\S+)", data)
        if m and not self.url["saved"]:
            self.url["saved"] = m.group(1).strip()

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.url["canonical"] = self.url["canonical"] or a.get("href", "")
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop == "og:url":
                self.url["og"] = self.url["og"] or a.get("content", "")
            if prop in ("article:published_time", "date", "pubdate") and not self.date:
                self.date = a.get("content", "")[:10]
        if tag == "script" and a.get("type", "") == "application/ld+json":
            self.ld = True
        if tag in SKIP_TAGS:
            self.skip += 1
        elif not self.skip and tag in BLOCK_TAGS:
            self.flush()
            self.tag = tag
        elif tag in ("strong", "b"):
            self.bold += 1
        elif tag == "br":
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
            self.ld = False
        elif tag in ("strong", "b") and self.bold:
            self.bold -= 1
        elif not self.skip and tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if self.ld and not self.date:  # JSON-LD: only its datePublished is read
            m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', data)
            self.date = m.group(1) if m else ""
        if self.skip:
            return
        self.buf.append(data)
        if self.bold and data.strip():
            self.bolds.append(data.strip())

    def flush(self):
        text = clean("".join(self.buf), 2000)
        if text:
            self.blocks.append({"kind": "h" if self.tag in HEADINGS else "p", "text": text, "bold": self.bolds})
        self.buf, self.bolds, self.tag = [], [], None


def read_page(path):
    raw = Path(path).read_bytes()[:MAX_PAGE].decode("utf-8", errors="replace")
    page = _Page()
    page.feed(raw)
    page.close()
    page.flush()
    url = page.url["canonical"] or page.url["og"] or page.url["saved"]
    return {"url": url.strip(), "date": page.date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", page.date or "") else "",
            "blocks": page.blocks}


def term_of(heading):
    """The word a heading names: its quoted part, or the heading without numbering, emoji and labels."""
    q = QUOTED.search(heading)
    if q:
        return q.group(1).strip()
    t = re.sub(r"^\s*(?:\d+\s*[.)]|[①-⑳]|#\d+|\[[^\]]{1,10}\]|[^\w\s]+)\s*", "", heading)
    t = re.sub(r"\s*(?:\(뜻\)|뜻|의미|란\??|이란\??|:.*|\s-\s.*)$", "", t).strip(" ?!·:-")
    return t


# v2 (11-07, from the development half of the first crawl only; docs/CRAWLER.md): each allowed source has its own
# layout, and section titles, questions and the sites' own furniture are never words.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿️‍⃣]")
SECTION = re.compile(r"어떤 밈|활용|궁금|알아보|구독|로딩|위픽레터|메일리|트렌드\s*어워드|trend a word|고구마팜|파밍레터|마케터|"
                     r"마케팅|함께 보면|다른\s?글|콘텐츠|채용|커피와 쪽지|이전 |다음 |유래|요약|정리|소개|첨부|영상을|어떻게|"
                     r"최고의 밈|이번에는|출처|^용례$|^활용$|특집|레퍼토리|사용 맥락|이렇게|포인트|꿀팁|ex\)|밈키피디아", re.IGNORECASE)
QUESTION = re.compile(r"(?:까|나요|을까|일까|ㄹ까|는지)\s*[?？]?\s*$")
DEF2 = re.compile(r"(?<!따)뜻|의미|유래|밈이|밈으로|밈입|말이|말로|말입|표현|줄임말|합성어|가리키|이르는|쓰는|쓰이|사용|"
                  r"감탄사|추임새|신조어|유행어|챌린지|부르는|지칭")
# A sentence that says what a word means, not one that only mentions it ("…밈이 되었고요", "표현이 불편하고").
STRONG = re.compile(r"(?<!따)뜻(?:이다|이에요|해요|한다|하는|합니다|으로)|의미(?:를|로|한다|해요|하는|합니다)|유래(?:한|했|된)|"
                    r"(?:말|표현|밈|감탄사|추임새|줄임말|합성어|신조어|유행어)(?:이다|이에요|예요|입니다|이죠|이야|으로 쓰|로 쓰|"
                    r"이라고|으로,|로,|이고)|줄임말|합성어|가리키|이르는|쓰는 (?:말|밈|표현)|쓰이는|사용하는|추임새|감탄사")
NOT_MEANING = re.compile(r"^(?:출처|💡|📌|이미지|ex\)|👉|⬇|🔗|#)")
SENTENCE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)|(?<=요\.)")


def word_of(text):
    """A word as a site writes it in a title line: emoji, numbering, labels and a trailing gloss in brackets removed."""
    t = EMOJI.sub("", text)
    t = re.sub(r"^\s*(?:\+\)?|#|\d+\s*[.)]|[①-⑳])\s*", "", t)
    t = re.sub(r"\s*[\(（][^)）]{1,30}[\)）]\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip(" ·:-").rstrip("~?!？！ ")


def is_word(term):
    return plausible(term) and not SECTION.search(term) and not QUESTION.search(term) and len(term) <= TERM


def define(texts, term, limit=MEANING, own=False):
    """The first sentence that defines the word: it says what something means (STRONG) and names the word. own=True:
    the texts are the word's own section (a one-word post, or one meme's part of a roundup), so a defining sentence
    counts without naming it. With the next sentence when it is short."""
    key = compact(term)
    for t in texts:
        if NOT_MEANING.match(t) or len(t) < 12:
            continue
        parts = [x.strip() for x in re.split(r"(?<=[.!?。])\s+", t) if x.strip()]
        for i, sent in enumerate(parts):
            names = own or key in compact(sent)
            if STRONG.search(sent) and names and not sent.endswith("?"):
                out = sent if len(sent) >= 40 or i + 1 >= len(parts) else sent + " " + parts[i + 1]
                return clean(out, limit)
    return ""


def site_of(url):
    parts = urlsplit(url or "")
    host, path = (parts.hostname or "").lower(), parts.path.lower()
    if host == "maily.so":
        return "trendaword" if path.startswith("/trendaword") else "farmingletter" if path.startswith("/farmingletter") else ""
    if host in ("gogumafarm.kr", "www.gogumafarm.kr"):
        return "gogumafarm"
    return "wepick" if host == "letter.wepick.kr" else ""


def _trendaword(blocks):
    """One word a post: the quoted word in the dated heading ("26.10.13 (화) '낱말'"); the meaning from the text under
    '활용'; the numbered examples under '용례'. Special issues (특집·특별편) cover many things and are left out."""
    title = next((b["text"] for b in blocks if b["kind"] == "h" and "Trend A Word" in b["text"]), "")
    if re.search(r"특집|특별편|연말정산", title):
        return []
    term = next((m.group(1) for b in blocks if b["kind"] == "h"
                 for m in [re.match(r"^\d{2}\.\d{2}\.\d{2}\s*\(.\)\s*['‘\"“](.+?)['’\"”]\s*$", b["text"])] if m), "")
    if not term:
        return []
    heads = [i for i, b in enumerate(blocks) if b["kind"] == "h"]
    use = next((i for i in heads if blocks[i]["text"].strip() == "활용"), None)
    ex = next((i for i in heads if blocks[i]["text"].strip() == "용례"), None)
    meaning = define([b["text"] for b in blocks[use + 1:use + 30]], term, own=True) if use is not None else ""
    examples = []
    if ex is not None:
        for b in blocks[ex + 1:(use if use and use > ex else ex + 10)]:
            m = re.match(r"^\d+\.\s*[“\"']?(.+?)[”\"'’]?\s*$", b["text"])
            if m:
                examples.append(m.group(1))
    return [(term, meaning, examples)]


def _farmingletter(blocks):
    """Numbered items "1️⃣ 낱말: 뜻 …", and '+ 낱말' headings with the paragraph under them."""
    out = []
    for i, b in enumerate(blocks):
        m = re.match(r"^\s*(?:\d️?⃣|\d+[.)])\s*([^:：]{1,25}?)\s*[:：]\s*(.+)$", b["text"])
        if m:
            rest = m.group(2)
            meaning = re.split(r"[\"“]|(?<=[.!?])\s| 사실 | 혹시 | 예를 들어| 요즘 ", rest)[0]
            out.append((m.group(1), meaning, [q for q in QUOTED.findall(rest)]))
        elif b["kind"] == "h" and b["text"].lstrip().startswith("+"):
            term = word_of(b["text"])
            out.append((term, define([x["text"] for x in blocks[i + 1:i + 5] if x["kind"] == "p"], term), []))
    return out


def _gogumafarm(blocks):
    """A meme is a short title line with an emoji at its start or end, then a '출처' line, then the explanation
    (after '💡 어떤 밈인가요?' in the newer layout)."""
    out = []
    for i, b in enumerate(blocks[:-1]):
        t = b["text"].strip()
        if len(t) > 50 or not blocks[i + 1]["text"].startswith("출처"):
            continue
        if not (EMOJI.match(t) or EMOJI.search(t[-3:])):
            continue
        term = word_of(t)
        texts = []
        for k in range(i + 2, min(i + 8, len(blocks))):
            x = blocks[k]["text"]
            nxt = blocks[k + 1]["text"] if k + 1 < len(blocks) else ""
            if x.startswith("📌") or (len(x) <= 50 and nxt.startswith("출처") and (EMOJI.match(x) or EMOJI.search(x[-3:]))):
                break  # the "how to use" part, or the next meme
            if blocks[k]["kind"] == "p":
                texts.append(x)
        out.append((term, define(texts, term, own=True), []))
    return out


def _wepick(blocks):
    """Word lists (a heading word, its meaning, then 'ex) …'), and in single-meme posts the sentence
    "'낱말'은 … 뜻/말/밈" (the generic inline rule below)."""
    out = []
    for i, b in enumerate(blocks[:-2]):
        if b["kind"] == "h" and blocks[i + 2]["text"].startswith("ex)") and len(blocks[i + 1]["text"]) <= 80:
            examples = [x.strip(" ~") for x in blocks[i + 2]["text"][3:].split("/") if x.strip()]
            out.append((word_of(b["text"]), blocks[i + 1]["text"], examples))
    title = next((b["text"] for b in blocks if b["kind"] == "h" and not b["text"].startswith("로딩")), "")
    m = re.match(r"^(?:📢\s*)?(.+?)\s*(?:밈\s*)?(?:궁금|마케터가|,|…|\?)", title)
    if m and not out:
        term = word_of(m.group(1))
        out.append((term, define([b["text"] for b in blocks if b["kind"] == "p"][:40], term), []))
    return out


SITES = {"trendaword": _trendaword, "farmingletter": _farmingletter, "gogumafarm": _gogumafarm, "wepick": _wepick}


def plausible(term):
    key = compact(term)
    return (2 <= len(key) <= TERM and term.count(" ") <= 6 and re.search(r"[가-힣A-Za-z]", term)
            and not FURNITURE.search(term) and not re.fullmatch(r"[\d\W_]+", term))


def main_blocks(blocks):
    """The post itself: what comes before the comments, related posts or the next-issue box."""
    end = next((i for i, b in enumerate(blocks) if b["text"].startswith("댓글을 불러오는")
                or b["text"] in ("함께 보면 더 알찬 아티클!", "다가올 뉴스레터가 궁금하신가요?")), len(blocks))
    return blocks[:end]


def candidates(page):
    """[{expression, meaning, examples}] from one page: its site's own layout first, then the sentences
    "'X'는 ~ 뜻/말/밈" anywhere. A word must not be a section title, question or the site's furniture, and its
    meaning must be a defining sentence."""
    blocks = main_blocks(page["blocks"])
    found = {}

    def put(term, meaning, examples):
        term = clean(word_of(term), TERM).strip("‘’'“”\"「」『』 ")
        meaning = clean(meaning, MEANING)
        key = compact(term)
        if key in found:  # found again (its layout, then an inline sentence): only its examples are added
            for e in examples:
                e = clean(e, EXAMPLE).strip("‘’'“”\" ")
                if key in compact(e) and compact(e) != key and e not in found[key]["examples"]:
                    found[key]["examples"] = (found[key]["examples"] + [e])[:3]
            return
        if not is_word(term) or len(meaning) < 8 or NOT_MEANING.match(meaning) or meaning.endswith("?"):
            return
        same = next((k for k, v in found.items() if v["meaning"] == meaning and key in k), None)
        if same:  # "WOW 섹시 푸드" then the post's own quoted "섹시 푸드" with the same meaning: keep the short one
            del found[same]
        ex = []
        for e in examples:
            e = clean(e, EXAMPLE).strip("‘’'“”\" ")
            if key in compact(e) and compact(e) != key and e not in ex:
                ex.append(e)
        found[key] = {"expression": term, "meaning": meaning, "examples": ex[:3]}

    site = SITES.get(site_of(page.get("url", "")))
    for term, meaning, examples in (site(blocks) if site else []):
        put(term, meaning, examples)
    for i, b in enumerate(blocks):
        for m in INLINE.finditer(b["text"]):
            if STRONG.search(m.group("rest")) and not re.search(r"^\S*\s*밈으로", m.group("rest")):
                quotes = [q for x in blocks[i:i + 4] for q in QUOTED.findall(x["text"])]
                put(m.group("term"), m.group(0), quotes)
    if not site:  # a page from no known layout: headings with a defining paragraph under them
        for i, b in enumerate(blocks):
            if b["kind"] == "h":
                term = term_of(b["text"])
                put(term, define([x["text"] for x in blocks[i + 1:i + 4] if x["kind"] == "p"], term), [])
    return list(found.values())


def sheet_rows(pages, known=(), sources=None, when="", cap=30, urls=None, extract=None):
    """Team-sheet rows (update_db.COLUMNS) from saved pages, and a report of what was used, refused and left out.
    urls: {file name: address it was fetched from} (fetch manifest) for a page that does not name itself."""
    sources = load_sources() if sources is None else sources
    known = {compact(k) for k in known}
    rows, report, seen = [], [], set()
    for path in pages:
        page = read_page(path)
        name = Path(path).name
        page["url"] = page["url"] or (urls or {}).get(name, "")
        if not page["url"]:
            report.append({"page": name, "used": False, "why": "페이지가 출처 주소를 말하지 않음(canonical·og:url·saved from 없음)"})
            continue
        if not allowed(page["url"], sources):
            report.append({"page": name, "used": False, "why": f"허용 목록에 없는 주소: {urlsplit(page['url']).hostname}"})
            continue
        got = (extract or candidates)(page)
        fresh = [c for c in got if compact(c["expression"]) not in known and compact(c["expression"]) not in seen][:cap]
        stamp = f"가져옴 {when[:10]}" + (f" · 글 날짜 {page['date']}" if page["date"] else "")
        for c in fresh:
            seen.add(compact(c["expression"]))
            source = f"{page['url']} · {stamp} · 크롤러(검수 전)"
            rows.append({"kind": "뜻", "expression": c["expression"], "variants": "", "meaning": c["meaning"], "easy": "",
                         "origin": "", "pos": "", "usage": "", "context": "", "source": source})
            rows += [{"kind": "용례", "expression": c["expression"], "variants": "", "meaning": "", "easy": "", "origin": "",
                      "pos": "", "usage": e, "context": "", "source": source} for e in c["examples"]]
        report.append({"page": name, "used": True, "url": page["url"], "date": page["date"], "found": len(got),
                       "new": len(fresh), "known": sum(compact(c["expression"]) in known for c in got)})
    return rows, report


def report_json(report):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in report)


def text_blocks(path, url):
    """What of a page may leave the fetch machine: its plain text blocks (no markup, no addresses), for checking."""
    page = read_page(path)
    return {"file": Path(path).name, "url": url, "date": page["date"],
            "blocks": [{"kind": b["kind"], "text": b["text"]} for b in page["blocks"]]}
