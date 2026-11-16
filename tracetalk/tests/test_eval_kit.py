"""Eval kit pipeline tests. The Ollama-shaped backend is TEST-FIXTURE-NOT-A-MODEL."""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import build_eval  # noqa: E402
import grade  # noqa: E402
import headroom  # noqa: E402
import run_bench  # noqa: E402
from test_local_verification import OllamaFixture  # noqa: E402

# The fixture server's default listen backlog (5) drops bursts from 8 parallel workers on macOS.
import http.server  # noqa: E402
http.server.ThreadingHTTPServer.request_queue_size = 64


def with_judge(backend, verdict="correct"):
    original = backend.client.generate

    def generate(messages, schema, seed, max_tokens):
        if "verdict" in schema.get("properties", {}):
            raw = verdict if isinstance(verdict, str) and verdict.startswith("{") else \
                json.dumps({"verdict": verdict, "literal_misread": "no", "reason": "TEST FIXTURE"})
            return {"raw": raw, "prompt_tokens": 10, "completion_tokens": 5, "finish_reason": "stop"}
        return original(messages, schema, seed, max_tokens)
    backend.client.generate = generate
    return backend


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def run_main(module, argv):
    with patch.object(sys, "argv", ["prog"] + argv), contextlib.redirect_stdout(io.StringIO()):
        return module.main()


class LabKitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.inputs = self.dir / "inputs.jsonl"
        self.gold = self.dir / "gold.jsonl"
        write_jsonl(self.inputs, [
            {"id": "c1", "text": "오늘은 팀플 버스 운전까지 했네.", "family": "f1", "split": "validation"},
            {"id": "c2", "text": "비가 와서 우산을 챙겨 나왔어요.", "family": "f2", "split": "validation"}])
        write_jsonl(self.gold, [
            {"case_id": "c1", "family": "f1", "stratum": "known_slang", "expression": "팀플 버스",
             "reference_meaning": "조별 과제에서 혼자 일을 떠맡음", "source": "test", "source_date": "",
             "license": "test", "review_status": "test"},
            {"case_id": "c2", "family": "f2", "stratum": "plain", "expression": "",
             "reference_meaning": "평범한 문장", "source": "test", "source_date": "", "license": "test",
             "review_status": "test"}])

    def tearDown(self):
        self.temp.cleanup()

    def bench(self, backend, name="runs.jsonl"):
        out = self.dir / name
        base = ["--model", backend.client.config.model, "--base-url",
                f"http://127.0.0.1:{backend.server.server_port}"]
        code = run_main(run_bench, base + ["--inputs", str(self.inputs), "--methods", "direct", "debate",
                                           "--seeds", "1", "2", "--workers", "4", "--output", str(out)])
        return code, out, base

    def test_parallel_bench_grade_and_headroom_end_to_end(self):
        with with_judge(OllamaFixture()) as backend:
            code, runs, base = self.bench(backend)
            self.assertEqual(code, 0)
            records = [json.loads(s) for s in runs.read_text().splitlines()]
            self.assertEqual(len(records), 8)
            self.assertEqual(backend.calls, 2 * 2 * (1 + 5))
            self.assertTrue(all(r["status"] == "completed" for r in records))
            events = runs.with_name(runs.name + ".events.jsonl").read_text().splitlines()
            self.assertEqual(sum(json.loads(e)["type"] == "scheduled" for e in events), 8)
            graded = self.dir / "graded.jsonl"
            base[1] = "TEST-JUDGE"
            backend.client.config = backend.client.config.__class__(model="TEST-JUDGE")
            code = run_main(grade, base + ["--runs", str(runs), "--gold", str(self.gold), "--output", str(graded)])
            self.assertEqual(code, 0)
            rows = [json.loads(s) for s in graded.read_text().splitlines()]
            self.assertEqual(len(rows), 8)
            self.assertTrue(all(r["verdict"] == "correct" for r in rows))
            self.assertEqual({r["stratum"] for r in rows}, {"known_slang", "plain"})
        summary = self.dir / "headroom.json"
        self.assertEqual(run_main(headroom, [str(graded), "--output", str(summary)]), 0)
        groups = {g["method"]: g for g in json.loads(summary.read_text())["groups"]}
        self.assertEqual(groups["direct"]["seeds"], 2)
        self.assertEqual(groups["direct"]["strata"]["all"]["pool_at_k"], 1.0)
        self.assertEqual(groups["direct"]["strata"]["all"]["headroom"], 0.0)
        self.assertEqual(groups["debate"]["strata"]["all"]["accuracy"], 1.0)

    def test_outputs_are_never_overwritten(self):
        with with_judge(OllamaFixture()) as backend:
            code, runs, _ = self.bench(backend)
            self.assertEqual(code, 0)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.bench(backend)

    def test_judge_errors_and_run_failures_stay_in_denominator(self):
        with with_judge(OllamaFixture(), verdict='{"verdict":"maybe"}') as backend:
            _, runs, base = self.bench(backend)
            records = [json.loads(s) for s in runs.read_text().splitlines()]
            records[0]["status"] = "failed"
            records[0]["result"]["error"] = "TEST failure"
            write_jsonl(runs, records)
            graded = self.dir / "graded.jsonl"
            with contextlib.redirect_stderr(io.StringIO()):
                run_main(grade, base + ["--runs", str(runs), "--gold", str(self.gold), "--output", str(graded)])
            rows = [json.loads(s) for s in graded.read_text().splitlines()]
            self.assertEqual(len(rows), 8)
            self.assertEqual(sum(r["verdict"] == "failed" for r in rows), 1)
            self.assertEqual(sum(r["verdict"] == "judge_error" for r in rows), 7)
        report = headroom.summarize(rows)
        self.assertTrue(all(g["strata"]["all"]["accuracy"] == 0 for g in report))

    def test_judge_prompt_holds_gold_but_inference_prompts_do_not(self):
        with with_judge(OllamaFixture()) as backend:
            _, runs, _ = self.bench(backend)
            self.assertTrue(backend.client.requests)
            for payload in backend.client.requests:
                self.assertNotIn("조별 과제에서 혼자 일을 떠맡음", json.dumps(payload, ensure_ascii=False))
        record = json.loads(runs.read_text().splitlines()[0])
        gold = {"expression": "x", "reference_meaning": "참조 의미"}
        self.assertIn("참조 의미", grade.judge_messages(record, gold)[1]["content"])

    def test_build_eval_splits_by_family_and_keeps_gold_out_of_inputs(self):
        ext = self.dir / "ext"
        (ext / "koculture").mkdir(parents=True)
        (ext / "koneobench").mkdir()
        titles = [f"밈{i}" for i in range(40)]
        write_jsonl(ext / "koculture/KoCulture-Descriptions.jsonl",
                    [{"title": t, "content": f"{t}의 뜻", "date": "2024", "category": "meme", "source": "test"}
                     for t in titles])
        write_jsonl(ext / "koculture/KoCulture-Dialogues.jsonl",
                    [{"title": t, "question": "q", "answer": f"오늘 완전 {t} 그 자체"} for t in titles for _ in range(2)])
        with (ext / "koneobench/Task4_with_ex.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["최초 출현 연도", "색인표제어", "원어", "단어 형성법", "뜻풀이", "용례", "빈도"])
            writer.writerow(["2024", "밈1", "", "축약", "겹침", "밈1 사용", "1"])
            writer.writerow(["2024", "새말", "", "혼성", "새말의 뜻", "새말을 쓴 문장", "1"])
        out = self.dir / "eval"
        with contextlib.redirect_stdout(io.StringIO()):
            summary = build_eval.main(["--out", str(out), "--external", str(ext), "--lexicon-out", str(self.dir / "lex")])
        val = [json.loads(s) for s in (out / "val_inputs.jsonl").read_text().splitlines()]
        test = [json.loads(s) for s in (out / "test_inputs.jsonl").read_text().splitlines()]
        families = json.loads((out / "families.json").read_text())
        self.assertFalse(set(families["train"]) & set(families["validation"]))
        self.assertFalse(set(families["validation"]) & set(families["test"]))
        self.assertTrue(all(set(r) == {"id", "text", "family", "split"} for r in val + test))
        kn = [json.loads(s) for s in (out / "koneo_inputs.jsonl").read_text().splitlines()]
        self.assertEqual([r["family"] for r in kn], ["kn:새말"])
        self.assertEqual(summary["koneo_cases"], 1)
        train = [json.loads(s) for s in (out / "train_inputs.jsonl").read_text().splitlines()]
        self.assertTrue(train and all(r["split"] == "train" for r in train))
        self.assertFalse({r["family"] for r in train} & {r["family"] for r in val + test})
        lex_eval = [json.loads(s) for s in (self.dir / "lex/lexicon_eval_v1.jsonl").read_text().splitlines()]
        lex_teacher = [json.loads(s) for s in (self.dir / "lex/lexicon_teacher_v1.jsonl").read_text().splitlines()]
        train_families = {"kc:" + build_eval.key(t) for t in families["train"]}
        self.assertTrue(lex_teacher and all(e["family"] in train_families for e in lex_teacher))
        gold = [json.loads(s) for s in (out / "val_gold.jsonl").read_text().splitlines()]
        in_lexicon = {e["family"] for e in lex_eval}
        for g in gold:
            if g["stratum"] == "unregistered":
                self.assertNotIn(g["family"], in_lexicon)
            elif g["stratum"] == "registered":
                self.assertIn(g["family"], in_lexicon)


if __name__ == "__main__":
    unittest.main()
