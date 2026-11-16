"""fresh_v3 tools (0.8.1): the S type in eval/build_fresh.py (a word in no DB whose other comments the collector
stored, as usage files with 2 and 4 of them) and eval/fresh3_report.py (bars ⑪ 쌓기 and ⑫ against the 0.8.0
card)."""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

SHEET = [{"kind": "뜻", "expression": "뇽뇽쿠", "variants": "", "meaning": "뇽뇽 쿠키", "easy": "쿠키", "origin": "",
          "pos": "명사", "usage": "", "context": "", "source": "https://a.example · https://b.example"},
         {"kind": "용례", "expression": "뇽뇽쿠", "variants": "", "meaning": "", "easy": "", "origin": "", "pos": "",
          "usage": "뇽뇽쿠 먹어 봄", "context": "", "source": "TraceTalk 작성 예문"}]
CASES = [{"id": "a1", "type": "A", "text": "뇽뇽쿠 또 품절", "expression": "뇽뇽쿠", "headword": "뇽뇽쿠", "sense": 1},
         {"id": "s1", "type": "S", "text": "오늘도 퀑퀑했다", "expression": "퀑퀑", "headword": "퀑퀑", "meaning": "신나게 놂",
          "collected": ["주말에 퀑퀑함", "친구랑 퀑퀑 예정", "어제 퀑퀑해서 피곤", "퀑퀑하러 감"]}]


def build(cases, sheet=SHEET):
    import build_fresh
    temp = tempfile.TemporaryDirectory()
    d = Path(temp.name)
    with (d / "fresh_db.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=list(sheet[0]))
        w.writeheader()
        w.writerows(sheet)
    (d / "cases.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            build_fresh.main(["--dir", str(d), "--pick-types", "A"])
        except SystemExit as exc:
            return temp, d, exc.code
    return temp, d, 0


class BuildTests(unittest.TestCase):
    def test_s_cases_make_stacked_usage_files(self):
        temp, d, code = build(CASES)
        with temp:
            self.assertEqual(code, 0)
            gold = {g["case_id"]: g for g in map(json.loads, (d / "gold.jsonl").read_text(encoding="utf-8").splitlines())}
            self.assertEqual((gold["s1"]["type"], gold["s1"]["reference_meaning"]), ("S", "신나게 놂"))
            graded = [json.loads(s)["case_id"] for s in (d / "grade_gold.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(graded, ["s1"])
            from tracetalk.db.usage import load_usages
            for k in (2, 4):
                groups = load_usages([d / f"stack/collected_{k}.jsonl"], missing_ok=False)
                self.assertEqual([(g["expression"], len(g["lines"])) for g in groups], [("퀑퀑", k)])
            self.assertEqual([json.loads(s)["id"] for s in (d / "stack/inputs_s.jsonl").read_text().splitlines()], ["s1"])
            sums = (d / "SHA256SUMS").read_text()
            self.assertIn("stack/collected_4.jsonl", sums)

    def test_an_s_case_needs_four_different_comments_with_the_word(self):
        bad = [CASES[0], {**CASES[1], "collected": ["주말에 퀑퀑함", "주말에 퀑퀑함", "어제 퀑퀑", "다른 말"]}]
        temp, d, code = build(bad)
        with temp:
            self.assertNotEqual(code, 0)
            self.assertFalse((d / "stack").exists())


GOLD = [{"case_id": "a1", "type": "A", "expression": "뇽뇽쿠", "headword": "뇽뇽쿠", "sense": "뇽뇽 쿠키"},
        {"case_id": "b1", "type": "B", "expression": "뇽뇽쿠", "headword": "뇽뇽쿠", "sense": None},
        {"case_id": "s1", "type": "S", "expression": "퀑퀑", "headword": "퀑퀑", "sense": None, "reference_meaning": "신나게 놂"}]
TEXT = {"a1": "뇽뇽쿠 또 품절", "b1": "뇽뇽쿠라는 노래 들음", "s1": "오늘도 퀑퀑했다"}


def rec(case, items, seed=42, method="card"):
    return {"case_id": case, "seed": seed, "method": method, "status": "completed",
            "result": {"request": {"text": TEXT[case]}, "card": {"items": items}, "elapsed_seconds": 10,
                       "detection": {"ordinary_words": []}, "input_sha256": case}}


def it(case, expression, choice, headword=None, db_meaning=None, estimate=False, reason="unreviewed"):
    start = TEXT[case].find(expression)
    return {"expression": expression, "start": start, "end": start + len(expression), "headword": headword,
            "choice": choice, "status": "proposed", "db_meaning": db_meaning, "decided_by": "mad", "estimate": estimate,
            "meaning": "뜻", "easy": "", "mad_reason": reason}


class Fresh3ReportTests(unittest.TestCase):
    def report(self, **files):
        import fresh3_report
        with tempfile.TemporaryDirectory() as temp:
            def put(name, rows):
                path = Path(temp) / name
                path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
                return str(path)
            args = ["--gold", put("g.jsonl", GOLD)]
            for key, value in files.items():
                if key in ("stack", "graded_stack"):
                    for k, rows in value:
                        args += [f"--{key.replace('_', '-')}", str(k), put(f"{key}{k}.jsonl", rows)]
                else:
                    args += [f"--{key.replace('_', '-')}", put(f"{key}.jsonl", value)]
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                fresh3_report.main(args)
            return printed.getvalue()

    def test_stacking_and_the_080_comparison(self):
        a_ok = it("a1", "뇽뇽쿠", "C1", "뇽뇽쿠", "뇽뇽 쿠키")
        s_item = it("s1", "퀑퀑", "N", estimate=True, reason="usages")
        new = [rec("a1", [a_ok]), rec("b1", [it("b1", "뇽뇽쿠", "L", "뇽뇽쿠")]), rec("s1", [it("s1", "퀑퀑", "N", estimate=True, reason="unknown")])]
        mid = [rec("a1", [a_ok]), rec("b1", [it("b1", "뇽뇽쿠", "C1", "뇽뇽쿠", "뇽뇽 쿠키")]), rec("s1", [])]
        printed = self.report(new=new, mid=mid, old=mid,
                              graded_new=[{"case_id": "s1", "seed": 42, "method": "card", "verdict": "wrong"}],
                              stack=[(2, [rec("s1", [s_item])]), (4, [rec("s1", [s_item])])],
                              graded_stack=[(2, [{"case_id": "s1", "seed": 42, "method": "card", "verdict": "partial"}]),
                                            (4, [{"case_id": "s1", "seed": 42, "method": "card", "verdict": "correct"}])])
        self.assertIn("쌓인 문장 4: n=1 · 뜻 맞음 1 (100%)", printed)
        self.assertIn("⑪ S 뜻 맞음: 쌓인 문장 4개 100.0% − 0개 0.0% (기준 +20%p 이상), 확정처럼 0 (기준 0) → 통과", printed)
        self.assertIn("⑫ B 새 카드 100.0% > 0.8.0 카드 0.0%, A 새 카드 100.0% ≥ 0.8.0 카드 100.0% − 10%p → 통과", printed)

    def test_a_settled_stacked_meaning_fails_eleven(self):
        settled = it("s1", "퀑퀑", "N", estimate=False, reason="usages")
        printed = self.report(new=[rec("s1", [])], mid=[], old=[],
                              stack=[(4, [rec("s1", [settled])])],
                              graded_stack=[(4, [{"case_id": "s1", "seed": 42, "method": "card", "verdict": "correct"}])])
        self.assertIn("확정처럼 1 (기준 0) → 미달", printed)


if __name__ == "__main__":
    unittest.main()
