"""0.9: the fetched posts as evidence (tracetalk/evidence/corpus.py): passages for one word, phrases the posts quote, what goes in. No model.
The text below is written for this test."""
import json
import tempfile
import unittest
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.evidence import corpus

ONE_WORD = {"url": "https://maily.so/trendaword/posts/a", "date": "", "blocks": [
    {"kind": "h", "text": "[Trend A Word #1] 재밌는 제목"},
    {"kind": "h", "text": "26.10.08 (목) 'L을 가져가'"},
    {"kind": "p", "text": "트둥이들, 안녕! 에디터 심풀이다. 오늘 날씨가 춥다."},
    {"kind": "p", "text": "‘L’은 패배를 뜻하는 ‘Loss’의 줄임말로, 게임에서 패배한 상대를 놀릴 때 사용하는 표현이라고 한다."},
    {"kind": "p", "text": "오늘 점심은 김밥이었다."}]}
ROUNDUP = {"url": "https://gogumafarm.kr/b", "date": "2026-02-10", "blocks": [
    {"kind": "h", "text": "요즘 뜨는 꾸미기 열풍 총정리"},
    {"kind": "p", "text": "최근 화제를 모은 것은 ‘볼꾸(볼펜 꾸미기)’입니다. 볼펜대와 파츠를 골라 조합해요."},
    {"kind": "p", "text": "“나 왜 이 순간이 영원할 거 같지?”라고 묻는 대사도 퍼졌어요."},
    {"kind": "h", "text": "거꾸"},
    {"kind": "p", "text": "거울을 스티커로 꾸미는 유행도 번지고 있어요."}]}
HTML = """<html><head><link rel="canonical" href="https://maily.so/trendaword/posts/z"><script>alert(1)</script></head><body><h2>제목</h2>
<p>회크닉은 회와 피크닉을 합친 말입니다.</p><p>구독하기 비밀번호로 로그인 하기</p></body></html>"""


class PassageTests(unittest.TestCase):
    def setUp(self):
        self.c = corpus.Corpus([ONE_WORD, ROUNDUP])

    def test_a_word_in_a_sentence_brings_the_sentence_that_explains_it(self):
        found = self.c.passages("볼꾸")
        self.assertEqual(len(found), 1)
        self.assertIn("볼펜 꾸미기", found[0]["text"])
        self.assertEqual(found[0]["url"], ROUNDUP["url"])

    def test_a_post_about_one_word_brings_what_explains_it_without_naming_it_and_not_the_greeting(self):
        text = self.c.passages("L을 가져가")[0]["text"]
        self.assertIn("패배를 뜻하는", text)
        self.assertNotIn("안녕", text)

    def test_a_heading_with_the_word_brings_what_follows_it(self):
        self.assertIn("거울을 스티커로", self.c.passages("거꾸")[0]["text"])

    def test_a_word_no_post_mentions_has_no_passage(self):
        self.assertEqual(self.c.passages("젬민이"), [])
        self.assertEqual(self.c.passages("김"), [])  # one letter never searches

    def test_a_phrase_the_posts_quote_is_found_in_a_comment_and_a_plain_comment_finds_none(self):
        hits = self.c.phrase_hits("회의가 세 시간째인데 나 왜 이 순간이 영원할 거 같지ㅋㅋ")
        self.assertEqual([h["span"] for h in hits], ["나 왜 이 순간이 영원할 거 같지"])
        text = "회의가 세 시간째인데 나 왜 이 순간이 영원할 거 같지ㅋㅋ"
        self.assertEqual(text[hits[0]["start"]:hits[0]["end"]], hits[0]["span"])
        self.assertEqual(corpus.Corpus([ROUNDUP]).phrase_hits("오늘 점심은 김밥이었다"), [])


class AddTests(unittest.TestCase):
    def setUp(self):
        Path("runs/tmp").mkdir(parents=True, exist_ok=True)  # a fresh clone has no runs/ (.gitignore)
        self.tmp = tempfile.TemporaryDirectory(dir="runs/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.pages = self.dir / "pages"
        self.pages.mkdir()
        (self.pages / "a.html").write_text(HTML, encoding="utf-8")
        (self.pages / "b.html").write_text(HTML.replace("posts/z", "posts/y"), encoding="utf-8")

    def test_only_text_of_pages_the_audit_passed_goes_in_once(self):
        (self.pages / "audit.jsonl").write_text(json.dumps({"file": "a.html", "verdict": "ok"}) + "\n" + json.dumps({"file": "b.html", "verdict": "refused"}) + "\n", encoding="utf-8")
        out = self.dir / "live/corpus.jsonl"
        self.assertEqual(corpus.add_pages(self.pages, out, "2026-11-07"), (1, 1))
        self.assertEqual(corpus.add_pages(self.pages, out, "2026-11-07"), (0, 2))  # already in, refused
        rows = [json.loads(s) for s in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["url"], "https://maily.so/trendaword/posts/z")
        joined = json.dumps(rows, ensure_ascii=False)
        self.assertIn("회크닉", joined)
        self.assertNotIn("alert", joined)
        self.assertNotIn("비밀번호로 로그인", joined)

    def test_a_page_from_outside_the_allowlist_stays_out(self):
        (self.pages / "c.html").write_text(HTML.replace("https://maily.so/trendaword/posts/z", "https://evil.example/x"), encoding="utf-8")
        out = self.dir / "corpus.jsonl"
        added, skipped = corpus.add_pages(self.pages, out, "")
        self.assertEqual((added, skipped), (2, 1))
        self.assertNotIn("evil", out.read_text(encoding="utf-8"))

    def test_the_command_line_adds_and_the_store_rereads(self):
        from tracetalk.db.usage import LiveStore
        live = self.dir / "live"
        store = LiveStore([], [], candidates_path=live / "candidates.jsonl")
        self.assertEqual(len(store.posts()), 0)
        report = update_db.main(["--live", str(live), "corpus-add", str(self.pages)])
        self.assertEqual((report["added"], report["posts"]), (2, 2))
        self.assertEqual(len(store.posts()), 2)
        self.assertEqual(store.posts().passages("회크닉")[0]["url"][:16], "https://maily.so")


if __name__ == "__main__":
    unittest.main()
