"""v9.6 r2 (11-04 evening): no prompt holds a validation or test expression or a KoNeoBench word (easy_draft_v3's
prompt had one as its example), and the draft reviewer files classes the script decides on."""
import ast
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracetalk.db.lexicon import compact, load_easy_drafts

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
# Every file whose strings reach a model: the card and older engines, the draft script, the judge, the SFT export.
PROMPT_FILES = sorted(ROOT.glob("tracetalk/**/*.py")) + [ROOT / "eval" / f for f in ("draft_easy.py", "grade.py",
                                                                                    "export_sft_card.py")]


def literals(path):
    """String constants of a source file, docstrings left out (they are never sent)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def expressions(name):
    path = ROOT / "data" / "eval" / "eval_v1" / name
    if not path.exists():
        return None
    words = (json.loads(line)["expression"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {w for w in words if len(compact(w)) >= 2}


class PromptLeakTests(unittest.TestCase):
    def test_no_prompt_holds_a_validation_or_test_expression(self):
        held = expressions("val_gold.jsonl") | expressions("test_gold.jsonl")
        for path in PROMPT_FILES:
            text = "\n".join(literals(path))
            with self.subTest(path.name):
                self.assertEqual(sorted(w for w in held if w in text), [])

    def test_no_prompt_holds_a_koneobench_word(self):  # counts only: the words are never printed
        held = expressions("koneo_gold.jsonl")
        if held is None:
            self.skipTest("KoNeoBench는 이 폴더에 없음")
        for path in PROMPT_FILES:
            text = "\n".join(literals(path))
            with self.subTest(path.name):
                self.assertEqual(sum(w in text for w in held), 0, "KoNeoBench 표현이 프롬프트에 있음(개수만 표시)")


ENTRY = {"id": "lx-1", "expression": "꿀팁", "variants": [], "meaning": "알아 두면 쓸모 있는 정보",
         "family": "kc:꿀팁", "source": "test", "license": "test"}


class Reviewer:
    """TEST-FIXTURE-NOT-A-MODEL: drafts 유용한 정보 with a check sentence; files the first review as `first` and the
    second as `second` (meaning, sentence)."""
    def __init__(self, first, second=("같은 뜻", "자연스러움")):
        self.verdicts, self.calls = [first, second], []

    def health(self):
        return {"ready": True}

    def generate(self, messages, schema, seed, max_tokens):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        if "meaning" in schema["properties"]:
            meaning, sentence = self.verdicts.pop(0)
            data = {"meaning": meaning, "sentence": sentence, "problem": "" if sentence == "자연스러움" else "TEST 조사"}
        else:
            data = {"slot": "명사", "easy": "유용한 정보", "check": payload["usage_examples"][0].replace("꿀팁", "유용한 정보")}
        return {"raw": json.dumps(data, ensure_ascii=False), "finish_reason": "stop"}


class DraftReviewClassTests(unittest.TestCase):
    def run_draft(self, teacher):
        import draft_easy
        with tempfile.TemporaryDirectory() as temp:
            lex, exs, out = Path(temp) / "lex.jsonl", Path(temp) / "ex.jsonl", Path(temp) / "d.jsonl"
            lex.write_text(json.dumps(ENTRY, ensure_ascii=False) + "\n", encoding="utf-8")
            exs.write_text(json.dumps({"entry_id": "lx-1", "expression": "꿀팁", "lines": ["이거 완전 꿀팁이네"],
                                       "source": "TEST", "license": "test", "note": "TEST"}, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            with patch.object(draft_easy, "make_client", lambda config: teacher), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                draft_easy.main(["--model", "TEST", "--lexicon", str(lex), "--examples", str(exs), "--out", str(out)])
            self.assertEqual(len(load_easy_drafts([out])), 1 if teacher.kept else 0)  # tries is an allowed field
            return json.loads(out.read_text(encoding="utf-8")), printed.getvalue()

    def test_a_narrow_word_is_kept_and_marked(self):
        teacher = Reviewer(("좁거나 뉘앙스가 빠짐", "자연스러움"))
        teacher.kept = True
        row, printed = self.run_draft(teacher)
        self.assertEqual((row["easy"], row["review"], len(row["tries"])), ("유용한 정보", "좁거나 뉘앙스가 빠짐", 1))
        self.assertIn("뜻 판정 {'좁거나 뉘앙스가 빠짐': 1}", printed)

    def test_a_broken_check_sentence_is_rewritten_with_the_draft_and_the_reason(self):
        teacher = Reviewer(("같은 뜻", "문법이 깨짐"))
        teacher.kept = True
        row, _ = self.run_draft(teacher)
        self.assertEqual(row["review"], "같은 뜻")
        self.assertEqual(teacher.calls[2]["previous"], {"easy": "유용한 정보", "check": "이거 완전 유용한 정보이네",
                                                        "problem": "검토(문법이 깨짐): TEST 조사"})
        self.assertEqual([t.get("problem") for t in row["tries"]], ["검토(문법이 깨짐): TEST 조사", None])
        self.assertEqual(teacher.calls[0]["max_length"], 12)

    def test_two_rejections_leave_no_draft_but_every_try(self):
        teacher = Reviewer(("다른 뜻", "자연스러움"), ("같은 뜻", "뜻이 달라짐"))
        teacher.kept = False
        row, printed = self.run_draft(teacher)
        self.assertEqual((row["easy"], row["error"]), ("", "검토(뜻이 달라짐): TEST 조사"))
        self.assertEqual([t["review"] for t in row["tries"]],
                         [{"meaning": "다른 뜻", "sentence": "자연스러움"}, {"meaning": "같은 뜻", "sentence": "뜻이 달라짐"}])
        self.assertIn("실패 {'검토(뜻이 달라짐)': 1}", printed)

    def test_a_pilot_sample_is_random_over_the_whole_list_and_fixed_by_the_seed(self):
        import draft_easy
        from test_v095 import TeacherFixture
        with tempfile.TemporaryDirectory() as temp:
            lex = Path(temp) / "lex.jsonl"
            lex.write_text("".join(json.dumps({**ENTRY, "id": f"lx-{i:03d}", "expression": f"말{i:03d}"},
                                              ensure_ascii=False) + "\n" for i in range(100)), encoding="utf-8")
            picked = []
            for name in ("a", "b"):
                out = Path(temp) / f"{name}.jsonl"
                with patch.object(draft_easy, "make_client", lambda config: TeacherFixture()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    draft_easy.main(["--model", "TEST", "--lexicon", str(lex), "--sample", "10", "--out", str(out)])
                picked.append([json.loads(s)["entry_id"] for s in out.read_text(encoding="utf-8").splitlines()])
        self.assertEqual(picked[0], picked[1])
        self.assertEqual(len(set(picked[0])), 10)
        self.assertNotEqual(sorted(picked[0]), [f"lx-{i:03d}" for i in range(10)])  # not the first ten



class TestReportTests(unittest.TestCase):
    """eval/test_report.py: per-seed numbers, the mean, and the three bars written down before the test run."""
    def report(self, verdicts):  # verdicts: (seed, stratum, verdict, status[, method]) per run, in blocks of 4
        import test_report
        with tempfile.TemporaryDirectory() as temp:
            runs, graded = Path(temp) / "t.jsonl", Path(temp) / "g.jsonl"
            verdicts = [v if len(v) == 5 else (*v, "card") for v in verdicts]
            records = [{"case_id": f"c{i % 4}", "seed": seed, "method": method, "status": status,
                        "result": {"model_config": {"model": "TEST"}}}
                       for i, (seed, _, _, status, method) in enumerate(verdicts)]
            rows = [{"case_id": f"c{i % 4}", "seed": seed, "method": method, "stratum": stratum, "verdict": verdict,
                     "sentence": "yes", "basis": "usage"}
                    for i, (seed, stratum, verdict, _, method) in enumerate(verdicts)]
            runs.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            graded.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                test_report.main(["--runs", str(runs), "--graded", str(graded)])
            return printed.getvalue()

    def cards(self, seed, registered=("correct", "correct"), plain="correct", status="completed", unregistered="wrong",
              method="card"):
        return [(seed, "registered", registered[0], status, method), (seed, "registered", registered[1], "completed", method),
                (seed, "unregistered", unregistered, "completed", method), (seed, "plain", plain, "completed", method)]

    def test_the_registered_mean_is_taken_over_seeds(self):
        printed = self.report(self.cards(42) + self.cards(43, registered=("correct", "wrong")))
        self.assertIn("등록어 뜻 평균 75.0%", printed)  # (2/2 + 1/2) / 2
        self.assertIn("뜻 정답 평균 1.5 (범위 1~2)", printed)
        self.assertIn("① 등록어 뜻 평균 75.0% (기준 85% 이상) → 미달", printed)
        self.assertIn("③ 평문을 신조어로 읽음 0/2 (기준 0) → 통과", printed)
        self.assertIn("틀린·부분 뜻 3 가운데 '추정'으로 표시 3", printed)

    def test_a_failed_run_and_a_plain_misread_are_counted(self):
        printed = self.report(self.cards(42, status="failed") + self.cards(43, plain="wrong"))
        self.assertIn("② 끝나지 않은 실행 1/8 = 12.5% (기준 2% 이하) → 미달", printed)
        self.assertIn("③ 평문을 신조어로 읽음 1/2 (기준 0) → 미달", printed)
        self.assertIn("기준 3개 중 2개 미달", printed)
        self.assertIn("① 등록어 뜻 평균 100.0% (기준 85% 이상) → 통과", printed)

    def test_the_single_decision_is_shown_beside_mad_and_never_enters_the_bars(self):
        printed = self.report(self.cards(42) + self.cards(42, registered=("correct", "wrong"), unregistered="correct",
                                                          plain="wrong", status="failed", method="card_single"))
        self.assertIn("== card_single (한 번에 고르기)", printed)
        self.assertIn("기준 3개 모두 통과", printed)  # the single decision's failure and plain misread are not counted
        self.assertIn("② 끝나지 않은 실행 0/4", printed)
        self.assertIn("registered   뜻: MAD만 맞음 1 · 한 번만 맞음 0", printed)
        self.assertIn("unregistered 뜻: MAD만 맞음 0 · 한 번만 맞음 1", printed)
        self.assertIn("all          뜻: MAD만 맞음 2 · 한 번만 맞음 1", printed)


if __name__ == "__main__":
    unittest.main()
