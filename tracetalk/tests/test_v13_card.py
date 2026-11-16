"""v13 card rules (docs/DESIGN.md). A DB sense the judge could not settle (뜻 확인 필요) keeps the DB's easy words and the
sentence they would make, both only as "이 뜻이 맞다면" (team slide 6, 11-08). A gloss the post states in a fixed form is shown to
check rather than dropped when 'another meaning' leads the judge. A DB match the retriever made by assuming a typo is shown to
check, never settled. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import unittest

from tracetalk.mad.card import CARD, CardAnalyzer, verdict
from tracetalk.evidence.corpus import Corpus
from frontier_fixture import V011, FixtureClient
from test_mad09 import REVIEWED, SENSE, TEXT, card, shares

EASY = {**SENSE, "easy": "두바이 쿠키"}


class CheckEasyTests(unittest.TestCase):
    def test_a_checked_sense_shows_its_easy_words_and_sentence_only_as_a_conditional(self):
        client, a = card([EASY], shares({"두바이": 0.7, "표준어": 0.15, "맞지 않고": 0.15}))
        result = a.run(text=TEXT, mode="card")
        item, c = result["card"]["items"][0], result["card"]
        self.assertEqual((item["status"], item["check_needed"], item["easy"], item["easy_if"]), ("uncertain", True, "", "두바이 쿠키"))
        self.assertIsNone(c["sentence"])
        self.assertEqual(c["sentence_if"], "편의점에 두바이 쿠키 들어왔대")
        self.assertEqual(c["sentence_if_by"], "model")

    def test_a_settled_sense_has_no_conditional(self):
        client, a = card([EASY], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        result = a.run(text=TEXT, mode="card")
        item, c = result["card"]["items"][0], result["card"]
        self.assertEqual((item["status"], item["easy"], item["easy_if"]), ("proposed", "두바이 쿠키", ""))
        self.assertEqual(c["sentence"], "편의점에 두바이 쿠키 들어왔대")
        self.assertIsNone(c["sentence_if"])

    def test_another_meaning_leading_has_no_easy_words_to_assume(self):
        client, a = card([EASY], shares({"두바이": 0.1, "표준어": 0.1, "맞지 않고": 0.8}))
        result = a.run(text=TEXT, mode="card")
        item, c = result["card"]["items"][0], result["card"]
        self.assertEqual((item["choice"], item["check_needed"], item["easy_if"]), ("N", True, ""))
        self.assertIsNone(c["sentence_if"])
        self.assertFalse([x for x in result["calls"] if x["stage"] == "sentence"])

    def test_a_checked_sense_without_db_easy_words_asks_nothing_more(self):
        client, a = card([SENSE], shares({"두바이": 0.7, "표준어": 0.15, "맞지 않고": 0.15}))
        result = a.run(text=TEXT, mode="card")
        self.assertEqual(result["card"]["items"][0]["easy_if"], "")
        self.assertIsNone(result["card"]["sentence_if"])
        self.assertFalse([x for x in result["calls"] if x["stage"] == "sentence"])


POST = {"url": "https://maily.so/trendaword/posts/y", "date": "2026-10-22", "blocks": [
    {"kind": "h", "text": "26.10.22 (목) '치올'"}, {"kind": "p", "text": "DTD, 치올(치고 올라간다), 야푸 같은 줄임말이 계속 생겨나고 있다."}]}


class StatedCheckTests(unittest.TestCase):
    def test_the_rule(self):
        scores = {"R1": 0.37, "N": 0.53, "L": 0.10}
        self.assertEqual(verdict(scores, [], None, {}, CARD, "R1", False, True), ("check", "R1"))
        self.assertEqual(verdict(scores, [], None, {}, CARD, "R1", False, False), ("other", "N"))  # a summary as before
        self.assertEqual(verdict({"R1": 0.1, "N": 0.2, "L": 0.7}, [], None, {}, CARD, "R1", False, True), ("literal", "L"))

    def card(self, post_read):
        client = FixtureClient()
        client.pick = shares({"치고": 0.37, "맞지 않고": 0.53, "표준어": 0.10})
        client.post_meaning, client.pick_span = "팀의 승리", "치올"
        client.probe = lambda payload: 0.9
        a = CardAnalyzer(client, lexicon=[], usages=[], config={**V011, "post_read": post_read}, corpus=Corpus([POST]))
        return a.run(text="오늘부터 우리 팀 치올이다", mode="card")["card"]["items"][0]

    def test_a_stated_gloss_that_another_meaning_outweighs_is_shown_to_check(self):
        item = self.card("stated")
        self.assertEqual((item["status"], item["check_needed"], item["choice"], item["meaning"]), ("uncertain", True, "R1", "'치고 올라간다'의 줄임말"))
        self.assertIn("치올(치고 올라간다)", item["post_quote"])

    def test_a_summary_reading_is_still_left_out(self):
        item = self.card("summary")
        self.assertEqual((item["status"], item["choice"], item["meaning"]), ("uncertain", "N", ""))


def matched(stage):
    class Retriever:  # the DB row 두쫀쿠 found at 두쫀크, as the retriever's typo stage would
        usage_index, stages = None, ("exact", "fuzzy")

        def hits(self, text, entries):
            at = text.find("두쫀크")
            return [{"start": at, "end": at + 3, "span": "두쫀크", "entry": entries[0], "stage": stage}]

        def evidence(self, group, text, limit):
            return []
    return Retriever()


class TypoTests(unittest.TestCase):
    def test_a_match_made_by_assuming_a_typo_is_shown_to_check(self):
        client, a = card([REVIEWED], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}), retriever=matched("fuzzy"))
        item = a.run(text="편의점에 두쫀크 들어왔대", mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"], item["meaning"]), ("uncertain", True, "두바이 쫀득 쿠키"))
        self.assertIn("오타", item["uncertainty"])

    def test_the_same_share_on_an_exact_match_is_settled(self):
        client, a = card([REVIEWED], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}), retriever=matched("exact"))
        item = a.run(text="편의점에 두쫀크 들어왔대", mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"]), ("proposed", False))


class EntryPointTests(unittest.TestCase):
    def test_the_demo_entry_point_imports(self):  # 11-08: demo.sh failed on a module the tidy folder never had
        from tracetalk.web import run as run_frontier
        self.assertTrue(callable(run_frontier.main))


if __name__ == "__main__":
    unittest.main()
