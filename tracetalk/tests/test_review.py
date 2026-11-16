"""0.9 review bench: crawler and collector words wait for a person; only an approval writes to the live DB, as 검수됨,
and the next read of the store has it. No model is involved. Source text below is written for this test."""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.db import review
from tracetalk.mad.card import entries_from_store
from tracetalk.db.lexicon import load_lexicon
from tracetalk.db.usage import LiveStore

COLUMNS = update_db.COLUMNS
URL = "https://maily.so/trendaword/posts/test"
PAGE = """<html><head><link rel="canonical" href="https://maily.so/trendaword/posts/test"></head><body>
<h2>요즘 뜨는 말</h2><p>회크닉은 포장한 회를 야외에서 즐기는 것을 뜻하는 말입니다.</p><p>오늘 회크닉 어때?</p></body></html>"""


def sheet(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


class BenchTests(unittest.TestCase):
    def setUp(self):
        os.makedirs("runs/tmp", exist_ok=True)  # a fresh clone has no runs/ (.gitignore)
        self.tmp = tempfile.TemporaryDirectory(dir="runs/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.live = self.dir / "live"
        self.live.mkdir()
        (self.dir / "pages").mkdir()
        (self.dir / "pages/a.html").write_text(PAGE, encoding="utf-8")
        (self.dir / "manifest.jsonl").write_text(json.dumps({"url": URL, "final_url": URL, "status": "ok", "file": "a.html"}) + "\n", encoding="utf-8")
        self.sheet = self.dir / "sheet.csv"
        sheet(self.sheet, [{"kind": "뜻", "expression": "회크닉", "meaning": "회를 야외에서 먹는 것", "source": f"{URL} · 가져옴 2026-11-07 · 크롤러(검수 전)"},
                           {"kind": "용례", "expression": "회크닉", "usage": "오늘 회크닉 어때?", "source": f"{URL} · 크롤러(검수 전)"}])

    def queue(self):
        rows = review.from_sheet(self.sheet, self.dir / "pages", self.dir / "manifest.jsonl", "2026-11-07T19:00:00+09:00")
        return review.add(self.live, rows)

    def test_a_crawled_word_waits_with_the_sentences_of_its_source_and_nothing_enters_the_db(self):
        self.assertEqual(self.queue(), 1)
        self.assertEqual(self.queue(), 0)  # the same row again is not new
        listed = review.listing(self.live, [])
        self.assertEqual(listed["waiting"], 1)
        item = listed["items"][0]
        self.assertEqual(item["expression"], "회크닉")
        self.assertIn("뜻하는 말", item["proposals"][0]["evidence"][0]["text"])  # the defining sentence comes first
        self.assertEqual(item["usages"], ["오늘 회크닉 어때?"])
        self.assertFalse((self.live / "entries.jsonl").exists())

    def test_approving_a_corrected_meaning_writes_one_reviewed_row_the_next_card_reads(self):
        self.queue()
        store = LiveStore([self.live / "entries.jsonl"], [self.live / "usages.jsonl"])
        self.assertEqual(store.current()[0], [])
        item = review.listing(self.live, [])["items"][0]
        out = review.decide(self.live, {"action": "approve", "keys": item["keys"], "expression": "회크닉",
                                        "meaning": "회와 피크닉을 합친 말. 포장한 회를 야외에서 먹는 것.", "easy": "회 소풍",
                                        "source": item["proposals"][0]["source"], "usages": item["usages"]})
        lexicon, usages = store.current()
        self.assertEqual(lexicon[0]["review"], "검수됨")
        self.assertIn("합친 말", lexicon[0]["meaning"])
        self.assertIn("사람 검수", lexicon[0]["source"])
        self.assertEqual(usages[0]["lines"][0]["text"], "오늘 회크닉 어때?")
        self.assertEqual(entries_from_store(lexicon, usages)[0]["senses"][0]["review"], "검수됨")
        self.assertEqual(out["action"], "approve")
        self.assertEqual(review.listing(self.live, lexicon)["waiting"], 0)  # decided: it left the list
        self.assertEqual(review.listing(self.live, lexicon)["approved"], 1)

    def test_rejecting_writes_nothing_to_the_db_and_a_new_meaning_comes_back(self):
        self.queue()
        item = review.listing(self.live, [])["items"][0]
        review.decide(self.live, {"action": "reject", "keys": item["keys"], "expression": "회크닉"})
        self.assertFalse((self.live / "entries.jsonl").exists())
        self.assertEqual(review.listing(self.live, [])["waiting"], 0)
        self.assertEqual(self.queue(), 0)
        review.add(self.live, [{**review.from_sheet(self.sheet)[0], "key": review.row_key("회크닉", "다른 뜻"), "meaning": "다른 뜻"}])
        self.assertEqual(review.listing(self.live, [])["waiting"], 1)

    def test_a_bad_approval_changes_nothing(self):
        self.queue()
        item = review.listing(self.live, [])["items"][0]
        for body in ({"action": "approve", "keys": item["keys"], "expression": "회크닉", "meaning": "", "source": "x"},
                     {"action": "approve", "keys": item["keys"], "expression": "회크닉", "meaning": "뜻", "source": "x", "usages": ["이 문장에는 그 말이 없음"]},
                     {"action": "delete", "keys": item["keys"]}, {"action": "approve", "keys": []}):
            with self.assertRaises(ValueError):
                review.decide(self.live, body)
        self.assertFalse((self.live / "entries.jsonl").exists())
        self.assertEqual(review.listing(self.live, [])["waiting"], 1)

    def test_the_collector_joins_the_list_without_offering_a_guess_as_a_meaning(self):
        rows = [{"expression": "무지컬", "headword": None, "text": t, "choice": "N", "status": "proposed", "meaning": "모델의 추측",
                 "easy": "", "decided_by": "mad", "mad_reason": "unknown", "at": "2026-11-07T10:00:00+09:00", "input_sha256": ""}
                for t in ("나 완전 무지컬임", "너 무지컬이네")]
        rows.append({**rows[0], "expression": "표준어말", "choice": "L"})
        (self.live / "candidates.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        listed = review.listing(self.live, [])
        self.assertEqual([i["expression"] for i in listed["items"]], ["무지컬"])
        self.assertEqual(listed["items"][0]["proposals"][0]["meaning"], "")
        self.assertEqual(len(listed["items"][0]["usages"]), 2)
        known = [{"expression": "무지컬", "variants": [], "meaning": "뜻", "source": "팀"}]
        self.assertEqual(review.listing(self.live, known)["waiting"], 0)  # the DB has it now

    def test_a_word_the_db_has_is_listed_with_what_the_db_says(self):
        self.queue()
        known = [{"expression": "회크닉", "variants": [], "meaning": "옛 뜻", "source": "팀", "review": "검수 전"}]
        item = review.listing(self.live, known)["items"][0]
        self.assertEqual(item["in_db"][0]["meaning"], "옛 뜻")

    def test_the_command_line_adds_a_sheet_to_the_bench(self):
        out = update_db.main(["--live", str(self.live), "review-add", str(self.sheet), "--pages", str(self.dir / "pages")])
        self.assertEqual((out["read"], out["new"], out["with_source_text"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
