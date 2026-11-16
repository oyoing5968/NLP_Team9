"""0.5 routing, evidence-asymmetric MAD and vote tests. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import json
import unittest

from tracetalk.mad.engine import Analyzer, ROUTER, caps_for
from tracetalk.db.lexicon import compact, retrieve
from frontier_fixture import FixtureClient

TEXT = "오늘은 팀플 버스 운전까지 했네."
LEXICON = [
    {"id": "lx-a", "expression": "팀플 버스", "variants": [], "meaning": "조별 과제에서 혼자 일을 떠맡아 다른 사람을 태워 감",
     "family": "kc:팀플버스", "source": "test", "license": "test"},
    {"id": "lx-b", "expression": "버스 운전", "variants": ["버스 태우다"], "meaning": "실력자가 팀을 이끌어 이기게 함",
     "family": "kc:버스운전", "source": "test", "license": "test"},
    {"id": "lx-c", "expression": "야르", "variants": [], "meaning": "흥이 오를 때 내는 감탄",
     "family": "kc:야르", "source": "test", "license": "test"},
]


def stages(client):
    return [r.get("stage", "probe:" + r.get("probe", "")) for r in client.requests]


class RetrieverTests(unittest.TestCase):
    def test_exact_matches_rank_first_and_unrelated_entries_are_dropped(self):
        found = retrieve(TEXT, LEXICON)
        self.assertEqual([c["id"] for c in found], ["lx-a", "lx-b"])
        self.assertTrue(all(c["retrieval_score"] == 1.0 for c in found))
        self.assertEqual(retrieve("비가 와서 우산을 챙겼다.", LEXICON), [])

    def test_spacing_and_jamo_variants_still_match(self):
        self.assertEqual(retrieve("오늘 팀플버스 또 탔다", LEXICON)[0]["id"], "lx-a")
        near = retrieve("어제 버스 태웠지", LEXICON)
        self.assertEqual(near[0]["id"], "lx-b")
        self.assertLess(near[0]["retrieval_score"], 1.0)
        self.assertEqual(compact("ㄱ- 와..."), "ㄱ-와")


class RoutedTests(unittest.TestCase):
    def run_routed(self, probe, lexicon=LEXICON, text=TEXT, client=None):
        client = client or FixtureClient()
        if probe is not None:
            client.probe = probe
        result = Analyzer(client, lexicon=lexicon).run(text=text, mode="routed")
        self.assertEqual(result["status"], "completed", result["error"])
        return client, result

    def test_plain_route_uses_one_generation(self):
        client, result = self.run_routed(lambda p: 0.05, lexicon=[], text="비가 와서 우산을 챙겼다.")
        self.assertEqual(result["routing"]["route"], "plain")
        self.assertEqual(stages(client), ["probe:has_slang", "final"])
        self.assertEqual(result["metrics"]["call_count"], 2)

    def test_single_passing_sense_grounds_the_explanation(self):
        client, result = self.run_routed(lambda p: 0.9 if p.get("expression") in (None, "팀플 버스") else 0.2)
        self.assertEqual(result["routing"]["route"], "lexicon")
        final = client.requests[-1]
        self.assertEqual(final["unverified_hypotheses"]["lexicon_entry_unverified"]["expression"], "팀플 버스")
        self.assertEqual(sum(s == "final" for s in stages(client)), 1)

    def test_two_passing_senses_go_to_disambiguation(self):
        client, result = self.run_routed(lambda p: 0.9)
        self.assertEqual(result["routing"]["route"], "disambiguate")
        candidates = client.requests[-1]["unverified_hypotheses"]["lexicon_candidates_unverified"]
        self.assertEqual({c["expression"] for c in candidates}, {"팀플 버스", "버스 운전"})

    def test_no_passing_sense_runs_evidence_asymmetric_mad(self):
        client, result = self.run_routed(None)
        self.assertEqual(result["routing"]["route"], "mad")
        generated = [r for r in client.requests if "stage" in r]
        self.assertEqual([r["stage"] for r in generated], ["propose", "propose", "review", "review", "final"])
        proposals = sorted(generated[:2], key=lambda r: "lexicon_neighbors_unverified" in r["unverified_hypotheses"])
        self.assertEqual(proposals[0]["unverified_hypotheses"], {})
        neighbors = proposals[1]["unverified_hypotheses"]["lexicon_neighbors_unverified"]
        self.assertEqual([n["expression"] for n in neighbors], ["팀플 버스", "버스 운전"])
        judge = generated[-1]["unverified_hypotheses"]["hypotheses"]
        self.assertEqual([h["label"] for h in judge], ["가설 1", "가설 2"])
        self.assertNotIn("role", json.dumps(judge, ensure_ascii=False))
        self.assertEqual(sorted(result["routing"]["judge_order"]), [0, 1])

    def test_unreadable_probe_is_recorded_and_never_routes_to_plain(self):
        client, result = self.run_routed(lambda p: None, lexicon=[], text="비가 와서 우산을 챙겼다.")
        self.assertEqual(result["routing"]["route"], "mad")
        probe = [c for c in result["calls"] if c["stage"] == "probe"]
        self.assertEqual(len(probe), 1)
        self.assertFalse(probe[0]["valid"])
        self.assertIn("확률", probe[0]["error"])

    def test_client_without_probe_support_falls_back_to_mad(self):
        class NoProbe(FixtureClient):
            yes_no = None
        client, result = self.run_routed(None, client=NoProbe())
        self.assertEqual(result["routing"]["route"], "mad")
        self.assertEqual(result["metrics"]["invalid_calls"], 1 + 2)

    def test_routed_mode_still_honours_a_reviewed_exact_entry(self):
        from test_frontier import FrontierTests
        helper = FrontierTests("test_cache_requires_current_exact_human_approval")
        helper.setUp()
        entry = helper.cache_entry()
        result = Analyzer(FixtureClient(), [entry], lexicon=LEXICON).run(text=helper.text, mode="routed")
        self.assertEqual(result["route"], "reviewed_cache")
        self.assertEqual(result["metrics"]["call_count"], 0)

    def test_router_thresholds_are_recorded_with_each_result(self):
        _, result = self.run_routed(None)
        self.assertEqual(result["routing"]["router"], ROUTER)
        self.assertEqual(len(result["routing"]["candidates"]), 2)
        self.assertTrue(all("p_yes" in c for c in result["routing"]["candidates"]))


class MethodTests(unittest.TestCase):
    def test_vote_uses_four_samples_and_one_selection_with_equal_caps(self):
        client = FixtureClient()
        result = Analyzer(client).run(text=TEXT, mode="vote", total_output_tokens=2560)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([r["stage"] for r in client.requests], ["final"] * 5)
        self.assertEqual(len(client.requests[-1]["unverified_hypotheses"]["candidates"]), 4)
        self.assertTrue(all(r["unverified_hypotheses"] == {} for r in client.requests[:4]))
        self.assertEqual(caps_for("vote", 2560), [512] * 5)

    def test_rag_puts_the_router_candidates_in_one_call_without_probes(self):
        client = FixtureClient()
        result = Analyzer(client, lexicon=LEXICON).run(text=TEXT, mode="rag")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(stages(client), ["final"])
        given = client.requests[0]["unverified_hypotheses"]["lexicon_candidates_unverified"]
        expected = retrieve(TEXT, LEXICON, ROUTER["k"], ROUTER["min_retrieval"])
        self.assertEqual([g["expression"] for g in given], [c["expression"] for c in expected])
        self.assertEqual(caps_for("rag", 2560), [2560])

    def test_vote_rag_gives_every_sample_the_same_neighbors_as_debate_v2(self):
        client = FixtureClient()
        result = Analyzer(client, lexicon=LEXICON).run(text=TEXT, mode="vote_rag", total_output_tokens=2560)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(stages(client), ["final"] * 5)
        debate = Analyzer(FixtureClient(), lexicon=LEXICON).run(text=TEXT, mode="debate_v2")
        self.assertEqual(result["routing"]["lexicon_neighbors"], debate["routing"]["lexicon_neighbors"])
        given = [r["unverified_hypotheses"].get("lexicon_neighbors_unverified") for r in client.requests[:4]]
        self.assertTrue(given[0] and all(g == given[0] for g in given))
        self.assertEqual(set(client.requests[-1]["unverified_hypotheses"]), {"candidates"})
        self.assertEqual(caps_for("vote_rag", 2560), [512] * 5)

    def test_debate_v2_without_lexicon_keeps_both_proposers_on_the_comment_only(self):
        client = FixtureClient()
        result = Analyzer(client).run(text=TEXT, mode="debate_v2")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["routing"]["lexicon_neighbors"], [])
        self.assertTrue(all(r["unverified_hypotheses"] == {} for r in client.requests[:2]))

    def test_parallel_rounds_keep_unique_call_records(self):
        result = Analyzer(FixtureClient(), lexicon=LEXICON).run(text=TEXT, mode="debate_v2")
        ids = [c["id"] for c in result["calls"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 5)

    def test_one_failed_parallel_call_fails_the_run_but_keeps_both_records(self):
        client = FixtureClient()

        def hook(payload, data):
            if payload["stage"] == "propose" and payload["unverified_hypotheses"]:
                data["input_quotes"] = ["원문에 없는 인용"]
        client.hook = hook
        result = Analyzer(client, lexicon=LEXICON).run(text=TEXT, mode="debate_v2")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(sum(c["valid"] for c in result["calls"]), 1)



class OutputContractTests(unittest.TestCase):
    """v4 output: easy words replace the expression in place; the rest of the comment never changes."""

    def test_rewrite_puts_easy_words_where_the_expression_stands(self):
        from tracetalk.mad.contracts import rewrite
        text = "쟤 방금 긁힌거 같은데?"
        out = rewrite(text, {"status": "proposed", "replacements": [{"expression": "긁힌", "easy": "쉬운말A"}]})
        self.assertEqual(out["text"], "쟤 방금 쉬운말A거 같은데?")
        span = out["spans"][0]
        self.assertEqual(text[span["start"]:span["end"]], "긁힌")
        self.assertEqual(out["text"][span["new_start"]:span["new_end"]], "쉬운말A")
        self.assertEqual(out["skipped"], [])

    def test_rewrite_replaces_every_occurrence_and_reports_what_it_skips(self):
        from tracetalk.mad.contracts import rewrite
        text = "야르~ 맛있다 야르~"
        out = rewrite(text, {"status": "proposed", "replacements": [
            {"expression": "야르~", "easy": "B"}, {"expression": "르~ 맛", "easy": "C"},
            {"expression": "없는말", "easy": "D"}, {"expression": "맛있다", "easy": " "}]})
        self.assertEqual(out["text"], "B 맛있다 B")
        self.assertEqual([s["start"] for s in out["spans"]], [0, 8])
        self.assertEqual([s["reason"] for s in out["skipped"]], ["앞 치환과 겹침", "원문에 없는 표현", "쉬운 말이 비어 있음"])
        none = {"text": None, "spans": [], "skipped": []}
        self.assertEqual(rewrite(text, {"status": "proposed", "replacements": []}), none)
        self.assertEqual(rewrite(text, {"status": "uncertain", "replacements": [{"expression": "야르~", "easy": "B"}]}), none)

    def test_engine_returns_the_rewritten_comment_and_rejects_a_missing_field(self):
        from tracetalk.mad.contracts import FINAL_SCHEMA, parse
        result = Analyzer(FixtureClient(), lexicon=LEXICON).run(text=TEXT, mode="direct")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["rewrite"]["text"], "테스트용 쉬운 말" + TEXT[16:])
        missing = {k: v for k, v in result["analysis"].items() if k != "replacements"}
        with self.assertRaisesRegex(ValueError, "필드"):
            parse(json.dumps(missing, ensure_ascii=False), FINAL_SCHEMA, TEXT)


class DemoScreenTests(unittest.TestCase):
    """The demo server returns everything the slide's five steps show, over real HTTP (fixture model)."""

    def run_job(self, text, sense_yes):
        import tempfile, threading, time, urllib.request
        from tracetalk.web.server import make_server
        client = FixtureClient()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" or p.get("expression") in sense_yes else 0.1
        examples = {"lx-c": {"entry_id": "lx-c", "expression": "야르", "lines": ["예시 줄"], "source": "test",
                             "license": "test", "note": "실제 관측 아님"}}
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(client, port=0, output_dir=temp, lexicon=LEXICON, examples=examples)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def request(path, body=None):
                req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as response:
                    return json.load(response)
            try:
                self.assertEqual(request("/api/config")["default_request"]["mode"], "routed")
                job_id = request("/api/analyze", {"text": text, "mode": "routed"})["job_id"]
                for _ in range(200):
                    job = request("/api/jobs/" + job_id)
                    if job["status"] != "running":
                        return job["result"]
                    time.sleep(.01)
                self.fail("job did not finish")
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_lexicon_route_returns_accepted_entry_examples_and_the_rewrite(self):
        result = self.run_job("야르~ 맛있다", {"야르"})
        self.assertEqual(result["routing"]["route"], "lexicon")
        self.assertEqual([e["entry_id"] for e in result["examples"]], ["lx-c"])
        self.assertEqual(result["rewrite"]["text"], "테스트용 쉬운 말")
        self.assertNotIn("예시 줄", json.dumps([c["messages"] for c in result["calls"]], ensure_ascii=False))

    def test_mad_route_has_no_dictionary_examples(self):
        result = self.run_job("야르~ 맛있다", set())
        self.assertEqual(result["routing"]["route"], "mad")
        self.assertEqual(result["examples"], [])


class LexiconFileTests(unittest.TestCase):
    """A fresh lexicon is read beside the demo one; a missing or malformed file stops the server."""

    def test_missing_lexicon_and_malformed_examples_are_refused(self):
        import tempfile
        from pathlib import Path
        from tracetalk.db.lexicon import load_examples, load_lexicon
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(load_lexicon(Path(temp) / "none.jsonl"), [])
            with self.assertRaisesRegex(ValueError, "사전 파일이 없습니다"):
                load_lexicon(Path(temp) / "none.jsonl", missing_ok=False)
            fresh = Path(temp) / "fresh.jsonl"
            fresh.write_text(json.dumps(LEXICON[2], ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual([e["id"] for e in load_lexicon(fresh, missing_ok=False)], ["lx-c"])
            bad = Path(temp) / "bad.jsonl"
            bad.write_text(json.dumps({"entry_id": "lx-c", "lines": []}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "예시 파일"):
                load_examples([bad], {"lx-c"})


class UIHarnessTests(unittest.TestCase):
    """Runs the DOM harnesses that exist on this machine (macOS JavaScriptCore, node). No browser."""
    JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"

    def run_harness(self, command):
        import subprocess
        from pathlib import Path
        out = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
        self.assertIn("passed", out.stdout + out.stderr, out.stdout + out.stderr)

    def test_jsc_harness(self):
        from pathlib import Path
        if not Path(self.JSC).exists():
            self.skipTest("JavaScriptCore가 없는 기기(맥이 아님)")
        self.run_harness([self.JSC, "tests/check_frontier_ui_jsc.js"])

    def test_node_harness(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node가 없음")
        self.run_harness(["node", "tests/check_frontier_ui.cjs"])


class KoNeoBenchSetTests(unittest.TestCase):
    """The public benchmark stays outside every lexicon and the training inputs."""

    def test_koneo_cases_are_decomposition_words_unknown_to_lexicons_and_training(self):
        from pathlib import Path
        from tracetalk.db.lexicon import load_lexicon
        root = Path(__file__).resolve().parents[1]
        if not (root / "data/eval/eval_v1/koneo_gold.jsonl").exists():
            self.skipTest("KoNeoBench는 이 폴더에 없음 (평가 전용, 재배포 금지)")
        read = lambda name: [json.loads(s) for s in (root / name).read_text(encoding="utf-8").splitlines() if s.strip()]
        gold, inputs = read("data/eval/eval_v1/koneo_gold.jsonl"), read("data/eval/eval_v1/koneo_inputs.jsonl")
        self.assertEqual([g["case_id"] for g in gold], [i["id"] for i in inputs])
        self.assertEqual({g["stratum"] for g in gold}, {"kn_abbreviation", "kn_blend"})
        train = compact(" ".join(i["text"] for i in read("data/eval/eval_v1/train_inputs.jsonl")))
        known = {compact(e["expression"]) for name in ("lexicon_eval_v1", "lexicon_teacher_v1", "lexicon_demo_v1")
                 for e in load_lexicon(root / f"data/db/lexicon/{name}.jsonl")}
        for g, i in zip(gold, inputs):
            self.assertIn(compact(g["expression"]), compact(i["text"]))
            self.assertNotIn(compact(g["expression"]), known)
            self.assertNotIn(compact(g["expression"]), train)


if __name__ == "__main__":
    unittest.main()
