"""fresh_v1 (11-05): eval/fresh_report.py scores card runs by rule against the gold types A-D and P, compares MAD
with one decision on the same case and seed, and applies the bars written before the run."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

GOLD = [
    {"case_id": "a1", "type": "A", "expression": "두쫀쿠", "headword": "두쫀쿠", "sense": "두바이 쫀득 쿠키"},
    {"case_id": "b1", "type": "B", "expression": "컹컹", "headword": "컹컹", "sense": None},
    {"case_id": "c1", "type": "C", "expression": "밤티", "headword": "밤티", "sense": "촌스럽다"},
    {"case_id": "p1", "type": "P", "expression": "", "headword": None, "sense": None},
]
TEXT = {"a1": "오늘 두쫀쿠 먹음", "b1": "개가 컹컹 짖었다", "c1": "그 실수 완전 밤티라 귀엽다", "p1": "점심을 먹었다"}


def item(case, choice, status="proposed", db_meaning=None, decided_by="single", estimate=False):
    expression = next(g["expression"] for g in GOLD if g["case_id"] == case)
    start = TEXT[case].find(expression)
    return {"expression": expression, "start": start, "end": start + len(expression), "headword": expression,
            "choice": choice, "status": status, "db_meaning": db_meaning, "decided_by": decided_by,
            "estimate": estimate}


def record(case, seed, method, items, status="completed"):
    return {"case_id": case, "seed": seed, "method": method, "status": status,
            "result": {"request": {"text": TEXT[case]}, "card": {"items": items}}}


def good(seed, method="card"):
    return [record("a1", seed, method, [item("a1", "C1", db_meaning="두바이 쫀득 쿠키")]),
            record("b1", seed, method, [item("b1", "L", decided_by="mad")]),
            record("c1", seed, method, [item("c1", "N", decided_by="mad", estimate=True)]),
            record("p1", seed, method, [])]


class FreshReportTests(unittest.TestCase):
    def report(self, before, after, picks=(), regress=None):
        import fresh_report
        with tempfile.TemporaryDirectory() as temp:
            def put(name, rows_):
                path = Path(temp) / name
                path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_), encoding="utf-8")
                return str(path)
            args = ["--gold", put("g.jsonl", GOLD), "--before", put("b.jsonl", before), "--after", put("a.jsonl", after)]
            if picks:
                args += ["--picks", put("p.jsonl", picks)]
            if regress:
                args += ["--regress-without", put("r0.jsonl", regress[0]), "--regress-control", put("r1.jsonl", regress[1]),
                         "--regress-with", put("r2.jsonl", regress[2])]
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                fresh_report.main(args)
            return printed.getvalue()

    def test_types_are_scored_by_rule(self):
        import fresh_report
        gold = {g["case_id"]: g for g in GOLD}
        self.assertTrue(fresh_report.outcome(good(42)[0], gold["a1"])["right"])
        self.assertTrue(fresh_report.outcome(good(42)[1], gold["b1"])["right"])  # the literal reading
        self.assertTrue(fresh_report.outcome(record("b1", 42, "card", []), gold["b1"])["right"])  # not found at all
        wrong_c = fresh_report.outcome(record("c1", 42, "card", [item("c1", "C1", db_meaning="촌스럽다")]), gold["c1"])
        self.assertEqual((wrong_c["right"], wrong_c["confident_wrong"]), (False, True))
        missed_c = fresh_report.outcome(record("c1", 42, "card", []), gold["c1"])
        self.assertEqual((missed_c["right"], missed_c["confident_wrong"]), (False, False))
        self.assertFalse(fresh_report.outcome(record("p1", 42, "card", [item("a1", "N", estimate=True)]), gold["p1"])["right"])
        failed = fresh_report.outcome(record("a1", 42, "card", [], status="failed"), gold["a1"])
        self.assertEqual((failed["done"], failed["right"]), (False, False))

    def test_a_settled_meaning_before_the_db_row_fails_bar_four(self):
        before = [record("a1", 42, "card", [item("a1", "N", decided_by="guess", estimate=True)]),
                  record("c1", 42, "card", [item("c1", "C3", db_meaning="다른 뜻")]), record("b1", 42, "card", []),
                  record("p1", 42, "card", [item("a1", "N", decided_by="guess", estimate=True)])]  # a plain misread
        printed = self.report(before, good(42) + good(42, "card_single"))
        self.assertIn("신조어로 쓴 문장 2개: 찾음 2 · 그중 '추정' 표시 1 · 확정처럼 보임 1", printed)
        self.assertIn("표준어·평문 문장 2개: 신조어로 읽음 1", printed)
        self.assertIn("④ 넣기 전 확정처럼 보인 뜻 1 (기준 0) → 미달", printed)
        self.assertIn("① A 맞음 card 평균 100.0% (기준 85% 이상) → 통과", printed)

    def test_mad_against_one_decision_on_the_same_case_and_seed(self):
        single = good(42, "card_single")
        single[2] = record("c1", 42, "card_single", [item("c1", "C1", db_meaning="촌스럽다")])  # confident wrong
        printed = self.report([], good(42) + single)
        self.assertIn("B·C·D 2쌍 중 MAD가 실제로 돈 것 2 · MAD만 맞음 1 · 한 번만 맞음 0 · 맞음 2 대 1", printed)
        self.assertIn("⑥ C: MAD 맞음 1 ≥ 한 번 0, 확신한 오답 0 ≤ 1 → 통과", printed)

    def test_pick_bars_need_mad_above_vote_and_single(self):
        picks = [{"method": m, "variant": v, "correct": c, "abstained": a, "status": "completed"}
                 for m, v, c, a in [("single", "none", 0, 0), ("vote", "none", 1, 1), ("mad", "none", 1, 1),
                                    ("single", "with_answer", 1, 0), ("vote", "with_answer", 1, 0),
                                    ("mad", "with_answer", 1, 0)]]
        printed = self.report([], good(42) + good(42, "card_single"), picks)
        self.assertIn("⑦ 고르기 none 유보: MAD 1 > 다수결 1, > 한 번 0 → 미달", printed)
        self.assertIn("⑧ 고르기 with_answer 정답: MAD 1 ≥ 한 번 1 − n의 10% → 통과", printed)

    def test_a_fresh_row_in_a_demo_card_fails_the_regression_bar(self):
        demo = lambda items: [{"case_id": "a1", "seed": 42, "method": "card", "status": "completed",
                               "result": {"request": {"text": TEXT["a1"]}, "card": {"items": items}}}]
        same = demo([])
        printed = self.report([], good(42), regress=(same, same, demo([item("a1", "C1", db_meaning="두바이 쫀득 쿠키")])))
        self.assertIn("신선 행이 끼어든 카드 ['a1']", printed)
        self.assertIn("⑨ 시연 문장: 신선 행이 끼어듦 1 (기준 0), 바뀐 카드 1 ≤ 흔들림 0 → 미달", printed)
        printed = self.report([], good(42), regress=(same, same, same))
        self.assertIn("⑨ 시연 문장: 신선 행이 끼어듦 0 (기준 0), 바뀐 카드 0 ≤ 흔들림 0 → 통과", printed)


if __name__ == "__main__":
    unittest.main()
