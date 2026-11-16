"""fresh_v4 report (eval/fresh4_report.py): every card is right, withheld or settled and wrong; a meaning that is not a DB row waits
for a person's judgement. Records below are written for this test. TEST-FIXTURE-NOT-A-MODEL."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import fresh4_report as R  # noqa: E402

GOLD = {"A": {"case_id": "a", "type": "A", "expression": "회크닉", "headword": "회크닉", "sense": "회 소풍"},
        "B": {"case_id": "b", "type": "B", "expression": "야차", "headword": "야차", "sense": None},
        "C": {"case_id": "c", "type": "C", "expression": "생존입니다", "headword": "생존입니다", "sense": "틀린 뜻", "note": "실제: x"},
        "U": {"case_id": "u", "type": "U", "expression": "거꾸", "headword": "거꾸", "sense": None, "reference_meaning": "거울 꾸미기"},
        "P": {"case_id": "p", "type": "P", "expression": "", "headword": None, "sense": None}}


def rec(case, items, text="오늘 회크닉 야차 생존입니다 거꾸 간다", **card):
    return {"case_id": case, "status": "completed", "result": {"request": {"text": text}, "elapsed_seconds": 10, "card": {"items": items, "skipped": [], "sentence": "s", **card}}}


def item(expr, **kw):
    start = "오늘 회크닉 야차 생존입니다 거꾸 간다".find(expr)
    return {"expression": expr, "start": start, "end": start + len(expr), "headword": expr, "status": "proposed", "choice": "C1", "basis": "db",
            "db_meaning": None, "estimate": False, "candidates": [{"id": "C1"}], **kw}


class JudgeTests(unittest.TestCase):
    def outcome(self, t, items, hand=None):
        return R.judge(rec(GOLD[t]["case_id"], items), GOLD[t], hand)["outcome"]

    def test_a_db_sense(self):
        self.assertEqual(self.outcome("A", [item("회크닉", db_meaning="회 소풍")]), "맞음")
        self.assertEqual(self.outcome("A", [item("회크닉", db_meaning="다른 뜻")]), "확정 오답")
        self.assertEqual(self.outcome("A", [item("회크닉", status="uncertain", db_meaning="회 소풍", check_needed=True)]), "보류")
        self.assertEqual(self.outcome("A", []), "보류")

    def test_a_meaning_read_from_the_posts_waits_for_a_person(self):
        read = item("회크닉", basis="post", choice="R1")
        self.assertEqual(self.outcome("A", [read]), "판정 대기")
        self.assertEqual(self.outcome("A", [read], "o"), "맞음")
        self.assertEqual(self.outcome("A", [read], "x"), "확정 오답")

    def test_the_standard_use(self):
        self.assertEqual(self.outcome("B", []), "맞음")
        self.assertEqual(self.outcome("B", [item("야차", choice="L", basis="literal")]), "맞음")
        self.assertEqual(self.outcome("B", [item("야차", db_meaning="차 마시기")]), "확정 오답")
        self.assertEqual(self.outcome("B", [item("야차", status="uncertain", check_needed=True)]), "보류")

    def test_a_wrong_row(self):
        self.assertEqual(self.outcome("C", [item("생존입니다", db_meaning="틀린 뜻")]), "확정 오답")
        self.assertEqual(self.outcome("C", [item("생존입니다", status="uncertain", check_needed=True)]), "맞음")
        self.assertEqual(self.outcome("C", [item("생존입니다", basis="post", choice="R1")], "o"), "맞음")
        self.assertEqual(self.outcome("C", [item("생존입니다", basis="post", choice="R1")], "x"), "확정 오답")

    def test_a_new_word(self):
        self.assertEqual(self.outcome("U", []), "보류")
        self.assertEqual(self.outcome("U", [item("거꾸", basis="post", choice="R1")], "o"), "맞음")
        self.assertEqual(self.outcome("U", [item("거꾸", basis="model", choice="N", estimate=True)], "x"), "보류")  # shown as an estimate

    def test_a_plain_comment(self):
        self.assertEqual(self.outcome("P", []), "맞음")
        self.assertEqual(self.outcome("P", [item("거꾸", basis="model", choice="N", estimate=True)]), "보류")
        self.assertEqual(self.outcome("P", [item("거꾸", db_meaning="x")]), "확정 오답")

    def test_a_card_counts_for_the_origin_only_when_it_names_it(self):
        gold = {**GOLD["A"], "origin_keywords": ["유노윤호", "Thank U"]}
        card = lambda **kw: R.judge(rec("a", [item("회크닉", db_meaning="회 소풍", **kw)]), gold)["origin_right"]
        self.assertTrue(card(origin="유노윤호 노래 가사"))
        self.assertTrue(card(meaning="thank u 가사에서 온 말"))
        self.assertFalse(card(origin="노래 가사"))

    def test_the_table_lists_what_waits_for_a_person(self):
        gold = {g["case_id"]: g for g in GOLD.values()}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            per, every, waiting = R.table("full", [rec("u", [item("거꾸", basis="post", choice="R1", meaning="거울 꾸미기")])], gold, {})
        self.assertEqual([w[0] for w in waiting], ["u"])
        self.assertEqual(per["U"]["판정 대기"], 1)


if __name__ == "__main__":
    unittest.main()
