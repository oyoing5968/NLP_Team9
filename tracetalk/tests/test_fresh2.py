"""0.8 / fresh_v2 tools: the judge-role rule on the development picks (eval/pick_judge.py) and the report that sets
the new card against the old card and one decision (eval/fresh2_report.py)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

GOLD = [{"case_id": "a1", "type": "A", "expression": "두쫀쿠", "headword": "두쫀쿠", "sense": "두바이 쫀득 쿠키"},
        {"case_id": "c1", "type": "C", "expression": "위쑤시개", "headword": "위쑤시개", "sense": "아부꾼"},
        {"case_id": "p1", "type": "P", "expression": "", "headword": None, "sense": None},
        {"case_id": "u1", "type": "U", "expression": "엠비스찬", "headword": "엠비스찬", "sense": None,
         "reference_meaning": "MBTI를 맹신하는 사람"}]
TEXT = {"a1": "두쫀쿠 품절", "c1": "위쑤시개 먹음", "p1": "이쑤시개 줘", "u1": "걔 엠비스찬이야"}


def item(case, expression, choice, status="proposed", db_meaning=None, decided_by="mad", estimate=False, headword=None):
    start = TEXT[case].find(expression)
    return {"expression": expression, "start": start, "end": start + len(expression), "headword": headword,
            "choice": choice, "status": status, "db_meaning": db_meaning, "decided_by": decided_by, "estimate": estimate,
            "meaning": "추정 뜻", "easy": "", "mad_reason": "unknown"}


def record(case, items, method="card", seed=42, ordinary=()):
    return {"case_id": case, "seed": seed, "method": method, "status": "completed",
            "result": {"request": {"text": TEXT[case]}, "card": {"items": items}, "elapsed_seconds": 10,
                       "detection": {"ordinary_words": list(ordinary)}, "input_sha256": case}}


class PickJudgeTests(unittest.TestCase):
    def run_rule(self, v9, v10):  # (with_answer correct, none abstained) of 10 each
        import pick_judge
        rows = [{"method": "mad", "judge": j, "variant": v, "correct": i < c, "abstained": i < a}
                for j, (c, a) in (("v9", v9), ("v10", v10))
                for v, good in (("with_answer", c), ("none", a)) for i in range(10)
                for c, a in [((good, 0) if v == "with_answer" else (good, good))]]
        with tempfile.TemporaryDirectory() as temp:
            runs, out = Path(temp) / "r.jsonl", Path(temp) / "judge.txt"
            runs.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                pick_judge.main(["--runs", str(runs), "--out", str(out)])
            return out.read_text(encoding="utf-8").strip()

    def test_v10_only_when_it_gains_three_and_loses_at_most_three(self):
        self.assertEqual(self.run_rule((5, 9), (8, 6)), "v10")  # +3 right answers, -3 abstentions
        self.assertEqual(self.run_rule((5, 9), (7, 9)), "v9")   # +2
        self.assertEqual(self.run_rule((5, 9), (9, 5)), "v9")   # -4 abstentions


class Fresh2ReportTests(unittest.TestCase):
    def report(self, new, old, graded_new, graded_old):
        import fresh2_report
        with tempfile.TemporaryDirectory() as temp:
            def put(name, rows):
                path = Path(temp) / name
                path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
                return str(path)
            args = ["--gold", put("g.jsonl", GOLD), "--new", put("n.jsonl", new), "--old", put("o.jsonl", old),
                    "--graded-new", put("gn.jsonl", graded_new), "--graded-old", put("go.jsonl", graded_old)]
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                fresh2_report.main(args)
            return printed.getvalue()

    def test_new_card_against_old_card_and_the_collector(self):
        new = [record("a1", [item("a1", "두쫀쿠", "C1", db_meaning="두바이 쫀득 쿠키", headword="두쫀쿠")]),
               record("c1", [item("c1", "위쑤시개", "N", estimate=True, headword="위쑤시개")]),
               record("p1", [], ordinary=["이쑤시개"]),
               record("u1", [item("u1", "엠비스찬", "N", status="uncertain", estimate=True)])]
        old = [record("a1", [item("a1", "두쫀쿠", "C1", db_meaning="두바이 쫀득 쿠키", decided_by="single", headword="두쫀쿠")]),
               record("c1", [item("c1", "위쑤시개", "C1", db_meaning="아부꾼", decided_by="single", headword="위쑤시개")]),
               record("p1", [item("p1", "이쑤시개", "N", decided_by="guess", estimate=True)]),
               record("u1", [item("u1", "엠비스찬", "N", decided_by="guess", estimate=True)])]
        graded_old = [{"case_id": "u1", "seed": 42, "method": "card", "verdict": "wrong"}]
        printed = self.report(new, old, [{"case_id": "u1", "seed": 42, "method": "card", "verdict": "wrong"}], graded_old)
        self.assertIn("③ C에서 MAD가 돈 비율 1/1 (기준 90% 이상), 틀린 뜻 확정 0 ≤ 옛 카드 1의 절반 → 통과", printed)
        self.assertIn("⑤ P 신조어로 읽음 0 (기준 0) → 통과", printed)
        # the new card's U item is a "don't know" (uncertain): not a wrong meaning shown, though graded wrong
        self.assertIn("⑥ U 확정처럼 0 (기준 0) · 틀린 뜻 보여 줌 0 < 옛 카드 1 · 찾음 100% ≥ 옛 카드 100% − 10%p → 통과", printed)
        self.assertIn("U 낱말 1/1 들어감 · P·B 문장에서 온 후보 []", printed)
        self.assertIn("위쑤시개: 댓글 1", printed)  # the wrong DB row's word comes back as a new-sense candidate
        self.assertIn("새 뜻 후보", printed)

    def test_a_plain_misread_reaches_the_queue_and_fails_both_bars(self):
        new = [record("p1", [item("p1", "이쑤시개", "N", estimate=True)]),
               record("u1", [item("u1", "엠비스찬", "N", estimate=True)])]
        printed = self.report(new, new, [], [])
        self.assertIn("⑤ P 신조어로 읽음 1 (기준 0) → 미달", printed)
        self.assertIn("P·B에서 온 후보 1 (기준 0) → 미달", printed)

    def test_select_keeps_one_type(self):
        import fresh2_report
        with tempfile.TemporaryDirectory() as temp:
            g, src, to = Path(temp) / "g.jsonl", Path(temp) / "s.jsonl", Path(temp) / "u.jsonl"
            g.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in GOLD), encoding="utf-8")
            src.write_text("".join(json.dumps(record(c, [])) + "\n" for c in ("a1", "u1", "p1")), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                fresh2_report.main(["--gold", str(g), "--select", "U", "--source", str(src), "--to", str(to)])
            self.assertEqual([json.loads(s)["case_id"] for s in to.read_text().splitlines()], ["u1"])


if __name__ == "__main__":
    unittest.main()
