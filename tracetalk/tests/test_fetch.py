"""0.8.1 crawler, step 1 and the audits (tracetalk/crawl/fetch.py, tracetalk/crawl/audit.py, tracetalk/crawl/pages.py): no network here -
the fetcher's opener and the name lookup are stand-ins. What must hold: only listed https addresses, no private
address, redirects only within the list, robots.txt obeyed, size and type caps, files only inside the project, every
fetched file audited, and only plain text and a clean sheet carried to the Mac."""
import contextlib
import hashlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path

from tracetalk.crawl import pages as crawl_pages
from tracetalk.db import update as update_db
from tracetalk.crawl import audit, fetch
from tracetalk.crawl import extract as crawl
from tracetalk.db.lexicon import ROOT

SOURCES = [("gogumafarm.kr", ""), ("maily.so", "/trendaword")]
PAGE = ('<html><head><link rel="canonical" href="https://gogumafarm.kr/?p=1"></head><body><script>steal()</script>'
        '<p>🎵 케케크롱</p><p>출처 X</p><p onclick="x()">‘케케크롱’은 특별한 뜻 없이 아무 문장 끝에나 붙이는 추임새예요.</p>'
        '</body></html>').encode()


def opener(pages):
    """A stand-in for HTTPS: {url: (status, headers, body)}; anything else is a 404."""
    calls = []

    def open_(url):
        calls.append(url)
        return pages.get(url, (404, {}, b""))
    open_.calls = calls
    return open_


def project_temp():
    """A scratch folder physically inside the project (runs/ is ignored by git; _mac_runtime may still be a link to
    another folder before the move, and the fetcher rightly refuses that)."""
    (ROOT / "runs" / "tmp").mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=ROOT / "runs" / "tmp")


class FetchTests(unittest.TestCase):
    def test_only_listed_https_pages_are_fetched_and_recorded(self):
        o = opener({"https://gogumafarm.kr/?p=1": (200, {"content-type": "text/html; charset=utf-8"}, PAGE),
                    "https://gogumafarm.kr/robots.txt": (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /wp-admin/\n"),
                    "https://gogumafarm.kr/wp-admin/x": (200, {"content-type": "text/html"}, b"<p>admin</p>")})
        urls = ["https://gogumafarm.kr/?p=1", "http://gogumafarm.kr/?p=1", "https://evil.example/x",
                "https://maily.so/other/posts/1", "https://gogumafarm.kr/wp-admin/x", "# a comment"]
        with project_temp() as temp:
            got = fetch.fetch_all(urls, Path(temp) / "pages", SOURCES, o, sleep=lambda s: None)
            ok = [r for r in got if r["status"] == "ok"]
            self.assertEqual([r["url"] for r in ok], ["https://gogumafarm.kr/?p=1"])
            self.assertEqual(ok[0]["sha256"], hashlib.sha256(PAGE).hexdigest())
            self.assertTrue((Path(temp) / "pages" / ok[0]["file"]).is_file())
            whys = " ".join(r.get("why", "") for r in got)
            self.assertIn("robots.txt", whys)
            self.assertEqual(len(got), 5)
        self.assertNotIn("https://evil.example/x", o.calls)  # refused before any connection

    def test_redirects_types_sizes(self):
        big = (200, {"content-type": "text/html"}, b"x" * (crawl.MAX_PAGE + 1))
        o = opener({"https://gogumafarm.kr/a": (302, {"location": "https://evil.example/"}, b""),
                    "https://gogumafarm.kr/b": (301, {"location": "/c"}, b""),
                    "https://gogumafarm.kr/c": (200, {"content-type": "text/html"}, PAGE),
                    "https://gogumafarm.kr/d": (200, {"content-type": "application/octet-stream"}, b"MZ..."),
                    "https://gogumafarm.kr/e": big})
        with self.assertRaises(fetch.Refused):
            fetch.get("https://gogumafarm.kr/a", SOURCES, o)
        self.assertEqual(fetch.get("https://gogumafarm.kr/b", SOURCES, o)[0], "https://gogumafarm.kr/c")
        for u in ("https://gogumafarm.kr/d", "https://gogumafarm.kr/e"):
            with self.assertRaises(fetch.Refused):
                fetch.get(u, SOURCES, o)

    def test_private_addresses_and_folders_outside_the_project_are_refused(self):
        fake = lambda addr: (lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))])
        for addr in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "0.0.0.0", "224.0.0.1"):
            with self.assertRaises(fetch.Refused):
                fetch.public_address("gogumafarm.kr", resolve=fake(addr))
        self.assertEqual(fetch.public_address("gogumafarm.kr", resolve=fake("8.8.8.8")), "8.8.8.8")
        for outside in (ROOT.parent / "x", Path("/private/tmp/x"), ROOT / ".." / "x"):
            with self.assertRaises(fetch.Refused):
                fetch.inside_project(outside)


class AuditTests(unittest.TestCase):
    def write(self, temp, name, body, url="https://gogumafarm.kr/?p=1"):
        (Path(temp) / name).write_bytes(body)
        return {"url": url, "final_url": url, "file": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    def test_a_page_is_checked_against_its_record(self):
        with project_temp() as temp:
            good = audit.audit_page(Path(temp) / "a.html", self.write(temp, "a.html", PAGE), SOURCES)
            self.assertEqual(good["verdict"], "ok")
            self.assertEqual((good["counts"]["script"], good["counts"]["on_handler"]), (1, 1))
            row = self.write(temp, "b.html", PAGE)
            (Path(temp) / "b.html").write_bytes(PAGE + b"<p>changed</p>")
            self.assertIn("지문이 기록과 다름", audit.audit_page(Path(temp) / "b.html", row, SOURCES)["problems"])
            exe = audit.audit_page(Path(temp) / "c.html", self.write(temp, "c.html", b"MZ\x90\x00binary"), SOURCES)
            self.assertEqual(exe["verdict"], "refused")
            other = self.write(temp, "d.html", PAGE.replace(b"https://gogumafarm.kr/?p=1", b"https://evil.example/p"))
            self.assertEqual(audit.audit_page(Path(temp) / "d.html", other, SOURCES)["verdict"], "refused")

    def test_what_is_carried_must_be_plain_and_formula_free(self):
        with project_temp() as temp:
            d = Path(temp)
            (d / "sheet.csv").write_text(",".join(audit.SHEET) + "\n"
                                         + "뜻,케케크롱,,=HYPERLINK(\"x\"),,,,,,https://gogumafarm.kr/?p=1 · 크롤러\n", encoding="utf-8")
            (d / "blocks.jsonl").write_text(json.dumps({"file": "a.html", "url": "https://gogumafarm.kr/?p=1", "date": "",
                                                        "blocks": [{"kind": "p", "text": "추임새"}]}) + "\n", encoding="utf-8")
            (d / "page.html").write_bytes(PAGE)
            problems = audit.audit_out(d, SOURCES)
            self.assertTrue(any("수식" in p for p in problems))
            self.assertTrue(any("page.html" in p for p in problems))
        self.assertEqual(update_db.sheet_safe({"meaning": "=HYPERLINK(\"x\")", "usage": "-1 출근"}),
                         {"meaning": "HYPERLINK(\"x\")", "usage": "1 출근"})


class PipelineTests(unittest.TestCase):
    def test_fetch_audit_extract_check(self):
        o = opener({"https://gogumafarm.kr/?p=1": (200, {"content-type": "text/html"}, PAGE)})
        with project_temp() as temp:
            urls = Path(temp) / "urls.txt"
            urls.write_text("https://gogumafarm.kr/?p=1\n", encoding="utf-8")
            pages, out = Path(temp) / "pages", Path(temp) / "out"
            fetch.fetch_all(urls.read_text().splitlines(), pages, SOURCES, o, sleep=lambda s: None)
            src = Path(temp) / "sources.txt"
            src.write_text("gogumafarm.kr\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                crawl_pages.main(["--sources", str(src), "audit", "--pages", str(pages)])
                crawl_pages.main(["--sources", str(src), "extract", "--pages", str(pages), "--out", str(out)])
                code = crawl_pages.main(["--sources", str(src), "check-out", "--dir", str(out)])
            self.assertEqual(code, 0, printed.getvalue())
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["SHA256SUMS", "audit.jsonl", "blocks.jsonl", "manifest.jsonl", "report.jsonl", "sheet.csv"])
            self.assertIn("케케크롱", (out / "sheet.csv").read_text(encoding="utf-8"))
            carried = (out / "blocks.jsonl").read_text(encoding="utf-8") + (out / "sheet.csv").read_text(encoding="utf-8")
            for gone in ("steal", "<script", "onclick", "<h2"):
                self.assertNotIn(gone, carried)


class DiscoverTests(unittest.TestCase):
    SOURCES = [("gogumafarm.kr", ""), ("maily.so", "/trendaword"), ("letter.wepick.kr", "")]
    MAILY = (b'<a href="/trendaword/posts/abc123">a</a><a href="/trendaword/posts/old1">b</a><a href="/trendaword/about">c</a>'
             b'<a href="https://evil.example/trendaword/posts/x">d</a><a href="/farmingletter/posts/zzz">e</a>')
    GOGUMA = (b'<a href="https://gogumafarm.kr/%eb%82%98-%ea%b3%a0%ea%b5%ac%eb%a7%88%ed%8c%9c/">a</a>'
              b'<a href="https://gogumafarm.kr/category/meme/">b</a><a href="https://gogumafarm.kr/wp-login.php">c</a>')

    def test_only_new_posts_of_the_listed_sites_are_named_and_nothing_else_is_fetched(self):
        calls = []

        def open_(url):
            calls.append(url)
            pages = {"https://maily.so/trendaword": self.MAILY, "https://gogumafarm.kr/": self.GOGUMA}
            if url in pages:
                return 200, {"content-type": "text/html"}, pages[url]
            return 404, {}, b""
        new, report = fetch.discover(["https://maily.so/trendaword", "https://gogumafarm.kr/", "https://evil.example/", "# 주석"], self.SOURCES,
                                     known=["https://maily.so/trendaword/posts/old1"], opener=open_, sleep=lambda s: None)
        self.assertEqual(new, ["https://maily.so/trendaword/posts/abc123", "https://gogumafarm.kr/%eb%82%98-%ea%b3%a0%ea%b5%ac%eb%a7%88%ed%8c%9c/"])
        self.assertEqual({urlsplit_host(u) for u in calls}, {"maily.so", "gogumafarm.kr"})
        self.assertFalse([u for u in calls if "posts" in u or "evil" in u])
        self.assertIn("why", report[2])

    def test_robots_are_obeyed_for_an_index(self):
        def open_(url):
            if url.endswith("robots.txt"):
                return 200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /\n"
            raise AssertionError("fetched past robots.txt")
        new, report = fetch.discover(["https://letter.wepick.kr/"], self.SOURCES, opener=open_, sleep=lambda s: None)
        self.assertEqual(new, [])
        self.assertIn("robots", report[0]["why"])


def urlsplit_host(url):
    from urllib.parse import urlsplit
    return urlsplit(url).hostname


if __name__ == "__main__":
    unittest.main()
