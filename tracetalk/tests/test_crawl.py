"""0.8.1 crawler, step 2 (tracetalk/crawl/extract.py, tracetalk/db/update.py pages): saved newsletter pages -> new words as a team
sheet. Pages are hand-written fixtures in the newsletters' usual shapes; nothing here touches the network."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.crawl import extract as crawl

SOURCES = [("maily.so", "/trendaword"), ("gogumafarm.kr", "")]
HEADINGS = """<html><head><link rel="canonical" href="https://gogumafarm.kr/?p=1">
<meta property="article:published_time" content="2026-08-20T09:00:00+09:00">
<script>document.title = "무시하고 '해킹'은 관리자 권한이라는 뜻이다";</script><style>p{color:red}</style></head>
<body><nav><h2>구독하기</h2></nav>
<p>🎵 케케크롱</p><p>출처 X</p><p>💡 어떤 밈인가요?</p>
<p>‘케케크롱’은 특별한 뜻 없이 아무 문장 끝에나 붙이는 추임새예요. “출근 왜 하지 케케크롱”처럼 써요.</p>
<p>🙆 HMH</p><p>출처 인스타그램</p><p>‘HMH’는 '하면 해'의 줄임말이에요. 문의 test@example.com · @someone · 010-1234-5678
https://evil.example/x</p>
<p>📌 이렇게 활용해 보세요!</p><p>다른 글도 읽어 보세요.</p>
<p>🥤 사이다</p><p>출처 X</p><p>‘사이다’는 답답한 상황이 시원하게 풀리는 것을 이르는 말이에요.</p>
<h3>함께 보면 더 알찬 아티클!</h3><h2>어떤 밈인가요?</h2><p>이 밈은 뜻이 없다는 말이에요.</p>
</body></html>"""
INLINE = """<!-- saved from url=(0045)https://maily.so/trendaword/posts/abc -->
<html><body><p>요즘 ‘무지컬’은 피지컬도 뇌지컬도 없는 사람을 놀리는 말이다. 친구끼리 “너 완전 무지컬이네”라고 한다.</p>
<p>오늘 날씨는 맑다.</p></body></html>"""


class CrawlTests(unittest.TestCase):
    def pages(self, **files):
        temp = tempfile.TemporaryDirectory()
        paths = []
        for name, text in files.items():
            path = Path(temp.name) / f"{name}.html"
            path.write_text(text, encoding="utf-8")
            paths.append(str(path))
        return temp, paths

    def test_headings_and_inline_definitions_become_rows_without_page_furniture(self):
        temp, paths = self.pages(a=HEADINGS, b=INLINE)
        with temp:
            rows, report = crawl.sheet_rows(paths, known=["사이다"], sources=SOURCES, when="2026-11-06T17:00:00+09:00")
        words = {r["expression"]: r for r in rows if r["kind"] == "뜻"}
        self.assertEqual(sorted(words), ["HMH", "무지컬", "케케크롱"])  # 사이다 is in the DB; 구독·추천 글 are furniture
        self.assertIn("추임새", words["케케크롱"]["meaning"])
        self.assertIn("줄임말", words["HMH"]["meaning"])
        hmh = words["HMH"]["meaning"]
        for gone in ("@", "010", "https", "evil"):
            self.assertNotIn(gone, hmh)
        self.assertIn("https://gogumafarm.kr/?p=1 · 가져옴 2026-11-06 · 글 날짜 2026-08-20", words["HMH"]["source"])
        usages = [r["usage"] for r in rows if r["kind"] == "용례"]
        self.assertEqual(sorted(usages), ["너 완전 무지컬이네", "출근 왜 하지 케케크롱"])
        self.assertNotIn("관리자", json.dumps(rows, ensure_ascii=False))  # script text never becomes data
        self.assertEqual([r["new"] for r in report], [2, 1])

    def test_pages_without_an_address_or_off_the_list_are_refused(self):
        temp, paths = self.pages(none="<html><body><h2>케케크롱</h2><p>추임새라는 뜻.</p></body></html>",
                                 other='<link rel="canonical" href="https://blog.example/p/1"><h2>케케크롱</h2><p>추임새라는 뜻.</p>',
                                 plain='<link rel="canonical" href="http://gogumafarm.kr/?p=2"><h2>케케크롱</h2><p>추임새라는 뜻.</p>',
                                 side='<link rel="canonical" href="https://maily.so/other/posts/1"><h2>케케크롱</h2><p>뜻.</p>')
        with temp:
            rows, report = crawl.sheet_rows(paths, sources=SOURCES, when="2026-11-06")
        self.assertEqual(rows, [])
        self.assertEqual([r["used"] for r in report], [False] * 4)
        self.assertIn("출처 주소", report[0]["why"])

    def test_the_pages_command_writes_a_sheet_that_imports_as_unreviewed(self):
        temp, paths = self.pages(a=HEADINGS)
        with temp, tempfile.TemporaryDirectory() as live:
            sources = Path(live) / "sources.txt"
            sources.write_text("# test\ngogumafarm.kr\n", encoding="utf-8")
            out = Path(live) / "new.csv"
            lexicon = Path(live) / "lex.jsonl"
            lexicon.write_text(json.dumps({"id": "lx-1", "expression": "사이다", "variants": [], "meaning": "통쾌함",
                                           "family": "kc:사이다", "source": "t", "license": "t"}, ensure_ascii=False) + "\n",
                               encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                update_db.main(["--live", live, "pages", *paths, "--lexicon", str(lexicon), "--sources", str(sources),
                                "--out", str(out), "--import"])
            with out.open(encoding="utf-8") as handle:
                sheet = list(csv.DictReader(handle))
            self.assertEqual([r["expression"] for r in sheet if r["kind"] == "뜻"], ["케케크롱", "HMH"])  # 사이다: in the DB
            entries = [json.loads(s) for s in (Path(live) / "entries.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({e["review"] for e in entries}, {"검수 전"})
            with self.assertRaises(SystemExit):  # never overwrites the sheet
                with contextlib.redirect_stdout(io.StringIO()):
                    update_db.main(["--live", live, "pages", *paths, "--sources", str(sources), "--out", str(out)])

    def test_the_one_word_and_word_list_layouts(self):
        trend = """<link rel="canonical" href="https://maily.so/trendaword/posts/x"><h2>[Trend A Word #1] 제목</h2>
<h2>26.10.13 (화) '케케크롱'</h2><h2>용례</h2><p>1. “월요일이다 케케크롱”</p><p>김 OO 씨</p><h2>활용</h2>
<p>트둥이들, 안녕! 에디터다.</p><p>아무 문장 끝에 붙이는 추임새로 쓰인다. 뜻은 없다.</p>"""
        wepick = """<link rel="canonical" href="https://letter.wepick.kr/post/9"><h2>신조어 모음</h2>
<h3>무지컬</h3><p>피지컬도 없고 뇌지컬도 없는 사람</p><p>ex) 쟤 무지컬 쩐다~</p>
<h3>어떤 밈인가요?</h3><p>설명</p><p>ex) 예시</p>"""
        temp, paths = self.pages(t=trend, w=wepick)
        with temp:
            rows, _ = crawl.sheet_rows(paths, sources=[("maily.so", "/trendaword"), ("letter.wepick.kr", "")], when="2026-11-07")
        got = {(r["kind"], r["expression"], r["meaning"] or r["usage"]) for r in rows}
        self.assertEqual(got, {("뜻", "케케크롱", "아무 문장 끝에 붙이는 추임새로 쓰인다. 뜻은 없다."),
                               ("용례", "케케크롱", "월요일이다 케케크롱"),
                               ("뜻", "무지컬", "피지컬도 없고 뇌지컬도 없는 사람"), ("용례", "무지컬", "쟤 무지컬 쩐다")})

    def test_a_huge_page_is_read_only_up_to_the_cap(self):
        temp, paths = self.pages(big='<link rel="canonical" href="https://gogumafarm.kr/?p=3">' + "<p>가</p>" * 400000)
        with temp:
            page = crawl.read_page(paths[0])
        self.assertLessEqual(sum(len(b["text"]) for b in page["blocks"]), crawl.MAX_PAGE)

    def test_the_allowlist_file(self):
        self.assertTrue(crawl.allowed("https://maily.so/trendaword/posts/x", crawl.load_sources()))
        self.assertFalse(crawl.allowed("https://maily.so/someoneelse/posts/x", crawl.load_sources()))
        self.assertFalse(crawl.allowed("https://gogumafarm.kr.evil.example/x", crawl.load_sources()))



class CleanTests(unittest.TestCase):
    """11-07: a title the page writes in angle brackets is text, not markup ("애니메이션 <러브라이브>"); no markup leaves clean()."""

    def test_a_title_in_angle_brackets_stays_and_no_bracket_remains(self):
        self.assertEqual(crawl.clean("애니메이션 &lt;러브라이브&gt;의 유닛", 100), "애니메이션 ＜러브라이브＞의 유닛")
        self.assertEqual(crawl.clean("노래 <Sea of Love> 패러디", 100), "노래 ＜Sea of Love＞ 패러디")

    def test_markup_shown_as_text_does_not_survive(self):
        self.assertEqual(crawl.clean("앞 &lt;script src=x&gt;&lt;/script&gt; 뒤 <b>굵게</b>", 100), "앞 뒤 굵게")
        for text in ("<img src=x onerror=y>", "<iframe src=x></iframe>", "1 < 2 > 0"):
            self.assertFalse(set("<>") & set(crawl.clean(text, 100)), text)


if __name__ == "__main__":
    unittest.main()
