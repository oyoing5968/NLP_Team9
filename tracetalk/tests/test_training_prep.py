"""SFT export and threshold calibration tests. Model outputs are TEST-FIXTURE-NOT-A-MODEL."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import calibrate  # noqa: E402
import export_ollama_model  # noqa: E402
import export_sft  # noqa: E402
import failures  # noqa: E402
from tracetalk.mad.benchmark import record_for  # noqa: E402
from tracetalk.mad.engine import Analyzer  # noqa: E402
from frontier_fixture import FixtureClient  # noqa: E402

LEXICON = [
    {"id": "lx-1", "expression": "팀플 버스", "variants": [], "meaning": "조별 과제 무임승차를 태워 줌",
     "family": "kc:팀플버스", "source": "t", "license": "t"},
    {"id": "lx-2", "expression": "버스 운전", "variants": [], "meaning": "실력자가 팀을 이끎",
     "family": "kc:버스운전", "source": "t", "license": "t"},
]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


class TrainingPrepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        write_jsonl(self.dir / "lex.jsonl", LEXICON)
        self.cases = [{"id": "t1", "text": "오늘은 팀플 버스 운전까지 했네.", "family": "kc:팀플버스", "split": "train"},
                      {"id": "t2", "text": "어제 팀플 버스 또 탔음", "family": "kc:팀플버스", "split": "train"}]
        write_jsonl(self.dir / "gold.jsonl", [{"case_id": c["id"], "family": c["family"], "stratum": "train",
                                               "expression": "팀플 버스", "reference_meaning": "x"} for c in self.cases])

    def tearDown(self):
        self.temp.cleanup()

    def routed_records(self, probe, cases=None):
        rows = []
        for case in cases or self.cases:
            client = FixtureClient()
            client.probe = probe
            result = Analyzer(client, lexicon=LEXICON).run(text=case["text"], mode="routed")
            rows.append(record_for(case, 42, "routed", result))
        return rows

    def test_export_keeps_correct_runs_and_labels_probes_from_gold(self):
        records = self.routed_records(lambda p: 0.1 if p["probe"] == "sense" else 0.9)
        write_jsonl(self.dir / "runs.jsonl", records)
        model = records[0]["result"]["model_config"]["model"]
        write_jsonl(self.dir / "graded.jsonl", [
            {"case_id": "t1", "seed": 42, "method": "routed", "model": model, "verdict": "correct"},
            {"case_id": "t2", "seed": 42, "method": "routed", "model": model, "verdict": "wrong"}])
        with contextlib.redirect_stdout(io.StringIO()):
            stats = export_sft.main(["--runs", str(self.dir / "runs.jsonl"), "--graded", str(self.dir / "graded.jsonl"),
                                     "--gold", str(self.dir / "gold.jsonl"), "--lexicon", str(self.dir / "lex.jsonl"),
                                     "--out", str(self.dir / "sft"), "--val-share", "0"])
        self.assertEqual(stats["runs_correct"], 1)
        self.assertEqual(stats["generation"], 5)
        self.assertEqual(stats["judge_extra"], 1)
        rows = [json.loads(s) for s in (self.dir / "sft/sft_train.jsonl").read_text().splitlines()]
        probes = [r for r in rows if r["meta"]["stage"] == "probe"]
        labels = {(json.loads(r["messages"][1]["content"])["expression"], r["messages"][-1]["content"]) for r in probes}
        self.assertEqual(labels, {("팀플 버스", "yes"), ("버스 운전", "no")})
        self.assertTrue(all(r["meta"]["label_from"] == "gold" for r in probes))
        self.assertTrue(all(r["messages"][-1]["role"] == "assistant" for r in rows))

    def test_export_refuses_non_train_records(self):
        case = {**self.cases[0], "split": "validation"}
        write_jsonl(self.dir / "runs.jsonl", self.routed_records(lambda p: 0.1, [case]))
        write_jsonl(self.dir / "graded.jsonl", [])
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            export_sft.main(["--runs", str(self.dir / "runs.jsonl"), "--graded", str(self.dir / "graded.jsonl"),
                             "--gold", str(self.dir / "gold.jsonl"), "--lexicon", str(self.dir / "lex.jsonl"),
                             "--out", str(self.dir / "sft")])

    def test_calibration_picks_lowest_threshold_meeting_precision(self):
        cases = [{**c, "split": "validation"} for c in self.cases]
        records = self.routed_records(lambda p: {"팀플 버스": 0.8, "버스 운전": 0.45}.get(p.get("expression"), 0.9), cases)
        write_jsonl(self.dir / "runs.jsonl", records)
        with contextlib.redirect_stdout(io.StringIO()):
            report = calibrate.main(["--runs", str(self.dir / "runs.jsonl"), "--gold", str(self.dir / "gold.jsonl"),
                                     "--lexicon", str(self.dir / "lex.jsonl"), "--output", str(self.dir / "cal.json")])
        self.assertEqual(report["sense_positive"], 2)
        self.assertEqual(report["tau_sense"], 0.5)
        self.assertTrue(report["tau_sense_meets_target"])

    def test_ollama_export_copies_blob_and_keeps_template(self):
        blob = self.dir / "sha256-abc"
        blob.write_bytes(b"GGUF-TEST-FIXTURE")
        fake = self.dir / "ollama"
        fake.write_text("#!/bin/sh\nprintf '# Modelfile\\nFROM %s\\nTEMPLATE \"{{ .Prompt }}\"\\nPARAMETER stop <|im_end|>\\n' "
                        f"'{blob}'\n", encoding="utf-8")
        fake.chmod(0o755)
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = export_ollama_model.main(["--name", "tt:v1", "--ollama", str(fake), "--out", str(self.dir / "pkg")])
        modelfile = (self.dir / "pkg/Modelfile").read_text()
        self.assertIn("FROM ./tt-v1.gguf", modelfile)
        self.assertIn('TEMPLATE "{{ .Prompt }}"', modelfile)
        self.assertEqual((self.dir / "pkg/tt-v1.gguf").read_bytes(), b"GGUF-TEST-FIXTURE")
        self.assertEqual(list(manifest["files"]), ["tt-v1.gguf"])

    def test_failure_check_separates_truncation_from_other_failures(self):
        class Truncating(FixtureClient):
            def generate(self, messages, schema, seed, max_tokens):
                output = super().generate(messages, schema, seed, max_tokens)
                if json.loads(messages[-1]["content"])["stage"] == "propose":
                    output.update(finish_reason="length", completion_tokens=max_tokens)
                return output
        case = self.cases[0]
        rows = [record_for(case, 42, m, Analyzer(c, lexicon=LEXICON).run(text=case["text"], mode=m))
                for m, c in (("direct", FixtureClient()), ("debate_v2", Truncating()))]
        report = {e["method"]: e for e in failures.summarize(rows)}
        self.assertEqual(report["direct"]["completed"], 1)
        self.assertEqual(report["debate_v2"]["failure_reasons"], {"truncated": 1})
        self.assertEqual(report["debate_v2"]["truncated_run_share"], 1.0)
        self.assertEqual(report["debate_v2"]["stages"]["propose"]["near_cap_share"], 1.0)
        self.assertEqual(report["direct"]["stages"]["final"]["cap"], [2560])
        self.assertEqual(report["direct"]["rewrite"], {"proposed_with_expression": 1, "rewritten": 1})
        self.assertEqual(report["debate_v2"]["rewrite"], {"proposed_with_expression": 0, "rewritten": 0})
        routed = failures.summarize(self.routed_records(lambda payload: None))[0]
        self.assertEqual(routed["probes_unreadable"], routed["probes"])
        self.assertEqual(routed["routes"], {"mad": 2})


if __name__ == "__main__":
    unittest.main()
