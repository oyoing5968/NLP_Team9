"""v18 automatic updating (mac/auto_update.sh, mac/start.sh --auto-update; docs/DESIGN.md): a word the card could not settle leaves a
mark asking for new posts soon, the screen shows how fresh the posts are, and the loop looks for new posts at the start, on its schedule
and after such a mark (never more often than the gap). The crawler itself is not run here (no network): a stand-in command is."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tracetalk.db.usage import LiveStore
from tracetalk.web.server import store_summary

ROOT = Path(__file__).resolve().parents[1]


def card(text, items, ordinary=()):
    return {"request": {"text": text}, "input_sha256": "x", "created_at": "2026-11-11T10:00:00+00:00",
            "card": {"items": items}, "detection": {"ordinary_words": list(ordinary)}}


def unknown(expression):
    return {"expression": expression, "headword": None, "choice": "N", "status": "uncertain", "meaning": "", "easy": "",
            "decided_by": "read", "mad_reason": None}


class MarkTests(unittest.TestCase):
    def test_a_word_the_card_could_not_settle_asks_for_new_posts(self):
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "live"
            store = LiveStore([], [], candidates_path=live / "candidates.jsonl")
            store.collect(card("오늘 오디세이 했다 ㅋㅋ", [unknown("오디세이")]))
            self.assertTrue((live / "update_wanted").exists())

    def test_a_word_the_posts_already_explain_does_not(self):  # 오디세이 after the crawl: read from a post, still no DB row
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "live"
            store = LiveStore([], [], candidates_path=live / "candidates.jsonl")
            item = {**unknown("오디세이"), "choice": "R1", "meaning": "오늘 디저트 세 개 이상 먹은 것", "posts": [{"url": "https://x.test"}]}
            self.assertEqual(store.collect(card("오디세이", [item])), 1)
            self.assertFalse((live / "update_wanted").exists())

    def test_an_ordinary_word_alone_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "live"
            store = LiveStore([], [], candidates_path=live / "candidates.jsonl")
            self.assertEqual(store.collect(card("호메로스의 오디세이 다 읽었다", [], ordinary=["오디세이"])), 1)
            self.assertFalse((live / "update_wanted").exists())

    def test_the_screen_shows_how_fresh_the_posts_are(self):
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "live"
            live.mkdir()
            posts = [{"url": "https://gogumafarm.kr/a", "date": "2026-11-03", "blocks": [{"text": "글"}], "fetched": "2026-11-11"},
                     # a Trend A Word post: its date only in the heading
                     {"url": "https://maily.so/trendaword/posts/b", "date": "", "blocks": [{"text": "26.11.10 (월) '오디세이'"}],
                      "fetched": "2026-11-11"}]
            (live / "corpus.jsonl").write_text("".join(json.dumps(p) + "\n" for p in posts), encoding="utf-8")
            (live / "update_state.json").write_text('{"checked": "2026-11-11T09:00:00+0900", "ok": true, "new_posts": 2, "review": 1}\n',
                                                    encoding="utf-8")
            summary = store_summary(LiveStore([], [], candidates_path=live / "candidates.jsonl"))
            self.assertEqual((summary["posts"], summary["posts_newest"]), (2, "2026-11-10"))
            self.assertEqual((summary["update"]["new_posts"], summary["update"]["ok"]), (2, True))


class LoopTests(unittest.TestCase):
    def test_at_the_start_after_a_mark_and_then_it_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            log, flag = Path(temp) / "ran.txt", Path(temp) / "update_wanted"
            env = {**os.environ, "TT_UPDATE_CMD": f"echo ran >> '{log}'", "TT_UPDATE_TICK": "1", "TT_UPDATE_EVERY": "1000",
                   "TT_UPDATE_GAP": "0", "TT_UPDATE_FLAG": str(flag)}
            loop = subprocess.Popen(["bash", str(ROOT / "mac/auto_update.sh"), "6"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                self.assertTrue(self.wait(lambda: log.exists() and log.read_text().count("ran") == 1))  # at the start
                time.sleep(1.5)
                self.assertEqual(log.read_text().count("ran"), 1)  # nothing more on its own before the schedule
                flag.touch()
                self.assertTrue(self.wait(lambda: log.read_text().count("ran") == 2))  # a word asked for new posts
                self.assertFalse(flag.exists())
            finally:
                loop.terminate()
                loop.wait(timeout=5)
                out = loop.stdout.read().decode()
                loop.stdout.close()
            self.assertIn("켤 때", out)

    def wait(self, check, seconds=6):
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.2)
        return False


if __name__ == "__main__":
    unittest.main()


class EasyWordsTests(unittest.TestCase):
    """v18: easy words the 4B wrote from nothing are checked against the meaning (오디세이 read from a post as '오늘 디저트 세 개 이상 먹은
    것' got '여행', and the sentence '오늘 완전 여행네'). One more try; still no: none, and the sentence keeps the expression."""

    def run_card(self, fit):
        from test_mad09 import POST
        from test_v16 import GLOSS, analyzer, judge
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge())
        client.quote_answers = [{"stance": "keep", "quote": GLOSS, "meaning": ""}]
        client.probe = lambda payload: fit if payload["probe"] == "easy_fit" else 0.9
        return a.run(text="오늘 회크닉 가자", mode="card")["card"]

    def test_words_that_fail_the_check_twice_are_left_out(self):
        card = self.run_card(0.3)
        item = card["items"][0]
        self.assertEqual((item["status"], item["easy"]), ("proposed", ""))
        self.assertEqual(item["detail"]["easy_fit"]["blanked"], ["고친 쉬운 말", "고친 쉬운 말"])
        self.assertIsNone(card["sentence"])
        self.assertIn("쉬운 표현을 확인하지 못해", card["sentence_problems"][0])

    def test_words_that_pass_stay(self):
        self.assertEqual(self.run_card(0.9)["items"][0]["easy"], "고친 쉬운 말")
