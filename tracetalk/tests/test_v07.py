"""0.6 / PROTOCOL v7: observed usages as evidence. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import contextlib
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.mad.engine import Analyzer, caps_for
from tracetalk.db.lexicon import load_lexicon
from tracetalk.web.server import make_server, related_examples
from tracetalk.db.usage import LiveStore, evidence, load_usages, retrieve_usages
from frontier_fixture import FixtureClient

TEXT = "쟤 방금 긁힌거 같은데?"
LEXICON = [{"id": "lx-a", "expression": "팀플 버스", "variants": [], "meaning": "조별 과제 무임승차",
            "family": "kc:팀플버스", "source": "test", "license": "test"}]
ROW = {"id": "u-test", "expression": "긁히다", "variants": ["긁힌", "긁혔"], "source": "TEST", "license": "test",
       "note": "TEST FIXTURE USAGE", "added_at": "2026-10-26",
       "lines": [{"text": f"TEST 용례 {i} 긁힌 듯", "context": ""} for i in range(1, 9)]}


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def stages(client):
    return [r.get("stage", "probe:" + r.get("probe", "")) for r in client.requests]


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)  # leave nothing in the system temp folder

    def test_rows_merge_by_expression_and_drop_repeated_lines(self):
        live = {**ROW, "id": "live-1", "variants": ["긁혀"], "source": "팀 입력", "added_at": "2026-11-01T18:00:00+09:00",
                "lines": [{"text": "TEST 용례 1 긁힌 듯", "context": ""}, {"text": "TEST 새 용례 긁혀서 화남", "context": "질문"}]}
        write(self.dir / "a.jsonl", [ROW])
        write(self.dir / "b.jsonl", [live])
        groups = load_usages([self.dir / "a.jsonl", self.dir / "b.jsonl", self.dir / "missing.jsonl"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["variants"], ["긁혀", "긁혔", "긁힌"])
        self.assertEqual(len(groups[0]["lines"]), 9)
        # The team's new line is shown first and keeps its own source and time.
        lines = evidence(groups[0], TEXT, 6)
        self.assertEqual([u["id"] for u in lines], ["U1", "U2", "U3", "U4", "U5", "U6"])
        self.assertEqual((lines[0]["row"], lines[0]["source"], lines[0]["context"]), ("live-1", "팀 입력", "질문"))

    def test_the_comment_itself_is_never_its_own_evidence(self):
        row = {**ROW, "lines": [{"text": TEXT, "context": ""}, {"text": "TEST 다른 용례 긁힌", "context": ""}]}
        write(self.dir / "a.jsonl", [row])
        lines = evidence(load_usages([self.dir / "a.jsonl"])[0], TEXT)
        self.assertEqual([u["text"] for u in lines], ["TEST 다른 용례 긁힌"])

    def test_variants_find_inflected_forms_and_bad_rows_are_refused(self):
        groups = [{**ROW, "lines": []}]
        self.assertEqual(retrieve_usages(TEXT, groups)[0]["retrieval_score"], 1.0)
        self.assertEqual(retrieve_usages("비가 와서 우산을 챙겼다.", groups), [])
        # Literal only: scattered jamo trigrams ("야르" in "고양이야를") and one-letter forms never match.
        yar = [{"id": "y", "expression": "야르", "variants": ["갓"], "lines": []}]
        self.assertEqual(retrieve_usages("고양이야를 봤다 갓", yar), [])
        self.assertEqual(len(retrieve_usages("야 르 ~ 좋다", yar)), 1)
        write(self.dir / "bad.jsonl", [{**ROW, "variants": "긁힌"}])
        with self.assertRaises(ValueError):
            load_usages([self.dir / "bad.jsonl"])
        write(self.dir / "bad.jsonl", [{k: v for k, v in ROW.items() if k != "note"}])
        with self.assertRaises(ValueError):
            load_usages([self.dir / "bad.jsonl"])
        with self.assertRaises(ValueError):
            load_usages([self.dir / "nothing.jsonl"], missing_ok=False)

    def test_lexicon_accepts_added_at_but_no_other_extra_field(self):
        entry = {**LEXICON[0], "added_at": "2026-11-01T18:00:00+09:00"}
        write(self.dir / "lex.jsonl", [entry])
        self.assertEqual(load_lexicon(self.dir / "lex.jsonl")[0]["added_at"], entry["added_at"])
        write(self.dir / "lex.jsonl", [{**entry, "extra": 1}])
        with self.assertRaises(ValueError):
            load_lexicon(self.dir / "lex.jsonl")

    def test_live_store_rereads_files_only_when_they_change(self):
        lex, use = self.dir / "lex.jsonl", self.dir / "use.jsonl"
        write(lex, LEXICON)
        store = LiveStore([lex], [use])
        self.assertEqual((len(store.current()[0]), store.current()[1]), (1, []))
        time.sleep(0.01)
        write(use, [ROW])
        self.assertEqual(store.current()[1][0]["expression"], "긁히다")
        write(lex, LEXICON + [{**LEXICON[0]}])
        with self.assertRaises(ValueError):
            store.current()


class UsageMadTests(unittest.TestCase):
    def analyzer(self, probe=None, lexicon=LEXICON, rows=(ROW,), client=None):
        client = client or FixtureClient()
        if probe is not None:
            client.probe = probe
        groups = [{"id": r["id"], "expression": r["expression"], "variants": r["variants"],
                   "lines": [{**u, "row": r["id"], "source": r["source"], "license": r["license"],
                              "note": r["note"], "added_at": r["added_at"]} for u in r["lines"]]} for r in rows]
        return client, Analyzer(client, lexicon=lexicon, usages=groups)

    def test_usages_without_a_dictionary_entry_run_usage_mad(self):
        client, runner = self.analyzer(lambda p: 0.9)
        result = runner.run(text=TEXT, mode="routed")
        self.assertEqual(result["status"], "completed", result["error"])
        routing = result["routing"]
        self.assertEqual(routing["route"], "usage_mad")
        self.assertEqual(stages(client), ["probe:has_slang", "propose", "propose", "review", "review", "final"])
        given = lambda r: [u["id"] for u in r.get("observed_usages", [])]
        proposals = [r for r in client.requests if r.get("stage") == "propose"]
        # Proposers see disjoint halves; reviewers and the judge see every usage (the held-out check).
        self.assertEqual(sorted(given(proposals[0]) + given(proposals[1])), sorted(f"U{i}" for i in range(1, 7)))
        self.assertFalse(set(given(proposals[0])) & set(given(proposals[1])))
        self.assertEqual(routing["proposer_usages"], [given(proposals[0]), given(proposals[1])])
        for r in client.requests[-3:]:
            self.assertEqual(len(given(r)), 6)
        judge = client.requests[-1]["unverified_hypotheses"]["hypotheses"]
        self.assertEqual(set(judge[0]), {"label", "proposal", "tested_by_other", "revised_meaning"})
        self.assertEqual(result["analysis"]["supporting_usages"], ["U1", "U2"])
        self.assertEqual(len(routing["usage_lines"]), 6)
        self.assertEqual(routing["held_out_checked"], [True, True])
        self.assertEqual(sum(c["max_tokens"] for c in result["calls"] if c["stage"] != "probe"), 2560)

    def test_dictionary_entry_beats_usages_and_a_rejected_entry_falls_to_usages(self):
        lexicon = LEXICON + [{"id": "lx-g", "expression": "긁히다", "variants": ["긁힌"], "meaning": "TEST 뜻",
                              "family": "kc:긁히다", "source": "test", "license": "test"}]
        _, runner = self.analyzer(lambda p: 0.9, lexicon=lexicon)
        self.assertEqual(runner.run(text=TEXT, mode="routed")["routing"]["route"], "lexicon")
        # v8: no usage probe. A dictionary entry the sense probe rejects falls to usage MAD, not to bare MAD.
        client, runner = self.analyzer(lambda p: 0.9 if p["probe"] == "has_slang" else 0.1, lexicon=lexicon)
        result = runner.run(text=TEXT, mode="routed")
        self.assertEqual(result["routing"]["route"], "usage_mad")
        self.assertEqual(result["routing"]["usage_groups"][0]["lines"], 6)
        self.assertNotIn("usage", [r.get("probe") for r in client.requests])
        _, runner = self.analyzer(lambda p: 0.9 if p["probe"] == "has_slang" else 0.1, lexicon=lexicon, rows=())
        self.assertEqual(runner.run(text=TEXT, mode="routed")["routing"]["route"], "mad")

    def test_usages_come_before_the_plain_check(self):
        # A word too new for the model can look plain to it; usages that fit still win.
        _, runner = self.analyzer(lambda p: 0.05 if p["probe"] == "has_slang" else 0.9)
        self.assertEqual(runner.run(text=TEXT, mode="routed")["routing"]["route"], "usage_mad")
        _, runner = self.analyzer(lambda p: 0.05, rows=())
        self.assertEqual(runner.run(text=TEXT, mode="routed")["routing"]["route"], "plain")

    def test_a_proposed_answer_from_usages_must_cite_one(self):
        client = FixtureClient()
        client.hook = lambda payload, data: data.update(supporting_usages=[]) if "supporting_usages" in data else None
        _, runner = self.analyzer(lambda p: 0.9, client=client)
        result = runner.run(text=TEXT, mode="routed")
        self.assertEqual(result["status"], "failed")
        self.assertIn("근거 용례 번호", result["error"])
        client.hook = lambda payload, data: data.update(supporting_usages=[], status="uncertain", replacements=[]) \
            if "supporting_usages" in data else None
        _, runner = self.analyzer(lambda p: 0.9, client=client)
        self.assertEqual(runner.run(text=TEXT, mode="routed")["status"], "completed")

    def test_citing_a_usage_that_was_not_given_fails_the_call(self):
        client = FixtureClient()
        client.hook = lambda payload, data: data.update(supporting_usages=["U9"]) if "supporting_usages" in data else None
        _, runner = self.analyzer(lambda p: 0.9, client=client)
        result = runner.run(text=TEXT, mode="routed")
        self.assertEqual(result["status"], "failed")
        self.assertIn("주어진 용례에 없는 번호", result["error"])
        self.assertFalse(result["calls"][-1]["valid"])

    def test_usage_direct_and_usage_mad_share_evidence_and_fall_back_without_it(self):
        client, runner = self.analyzer()
        result = runner.run(text=TEXT, mode="usage_direct")
        self.assertEqual(stages(client), ["final"])
        self.assertEqual(len(client.requests[0]["observed_usages"]), 6)
        self.assertIn("supporting_usages", result["analysis"])
        mad_client, mad = self.analyzer()
        mad_result = mad.run(text=TEXT, mode="usage_mad")
        self.assertEqual([u["text"] for u in result["routing"]["usage_lines"]],
                         [u["text"] for u in mad_result["routing"]["usage_lines"]])
        self.assertEqual(len(mad_client.requests), 5)
        client, runner = self.analyzer(rows=())
        result = runner.run(text=TEXT, mode="usage_direct")
        self.assertEqual((result["routing"]["usage_group"], stages(client)), (None, ["final"]))
        self.assertNotIn("supporting_usages", result["analysis"])
        client, runner = self.analyzer(rows=())
        self.assertEqual(runner.run(text=TEXT, mode="usage_mad")["status"], "completed")
        self.assertNotIn("observed_usages", client.requests[0])

    def test_usage_methods_use_the_same_budgets_as_their_counterparts(self):
        self.assertEqual(caps_for("usage_direct", 5120), [5120])
        self.assertEqual(caps_for("usage_mad", 5120), caps_for("debate_v2", 5120))


class UpdateAndServerTests(unittest.TestCase):
    def setUp(self):
        self.live = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.live, True)

    def add(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return update_db.main(["--live", str(self.live), *argv])

    def test_update_appends_dated_rows_and_refuses_unusable_input(self):
        entry = self.add("add-entry", "--expression", "긁히다", "--variants", "긁힌", "긁혔", "--meaning", "TEST 뜻",
                         "--source", "TEST 출처")
        self.assertTrue(entry["id"].startswith("live-e-") and entry["added_at"][:4].isdigit())
        usage = self.add("add-usage", "--expression", "야르", "--text", "TEST 야르~ 좋다", "--text", "TEST 야르 외침",
                         "--source", "TEST 출처")
        self.assertEqual(len(usage["lines"]), 2)
        self.assertEqual(load_lexicon(self.live / "entries.jsonl")[0]["expression"], "긁히다")
        self.assertEqual(len(load_usages([self.live / "usages.jsonl"])[0]["lines"]), 2)
        for argv in (("add-usage", "--expression", "야르", "--text", "TEST 표현이 없는 문장", "--source", "x"),
                     ("add-usage", "--expression", "각", "--text", "TEST 이건 각이다", "--source", "x"),
                     ("add-entry", "--expression", " ", "--meaning", "x", "--source", "x")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.add(*argv)
        self.assertEqual(len((self.live / "usages.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(len(self.add("list")), 3)

    def test_a_running_server_uses_an_added_usage_without_restart(self):
        store = LiveStore([self.live / "entries.jsonl"], [self.live / "usages.jsonl"])
        client = FixtureClient()
        client.probe = lambda p: 0.9
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(client, port=0, output_dir=temp, store=store)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"
            def request(path, body=None):
                req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as response:
                    return json.load(response)
            def analyze():
                job = request("/api/analyze", {"text": "TEST 야르~ 맛있다", "mode": "routed"})["job_id"]
                for _ in range(200):
                    state = request("/api/jobs/" + job)
                    if state["status"] != "running":
                        return state["result"]
                    time.sleep(.01)
            try:
                self.assertEqual(analyze()["routing"]["route"], "mad")
                self.add("add-usage", "--expression", "야르", "--text", "TEST 야르~ 오늘 최고", "--text", "TEST 야르 외치고 시작",
                         "--source", "TEST 팀 입력")
                result = analyze()
                self.assertEqual(result["routing"]["route"], "usage_mad")
                block = result["examples"][0]
                self.assertEqual((block["source"], block["cited"], len(block["lines"])), ("TEST 팀 입력", ["U1", "U2"], 2))
                self.assertTrue(block["lines"][0].startswith("U1 · "))
                summary = request("/api/store")
                self.assertEqual((summary["usage_groups"], summary["latest"][0]["kind"]), (1, "용례"))
            finally:
                server.shutdown()
                server.server_close()

    def test_examples_follow_the_route(self):
        lines = [{"id": "U1", "text": "a", "source": "S1", "license": "l", "note": "n", "added_at": "2026-10-26"},
                 {"id": "U2", "text": "b", "source": "S2", "license": "l", "note": "n", "added_at": "2026-11-01T18:00:00+09:00"}]
        result = {"analysis": {"supporting_usages": ["U2"]},
                  "routing": {"route": "usage_mad", "usage_group": {"id": "g", "expression": "x"}, "usage_lines": lines}}
        blocks = related_examples(result, {})
        self.assertEqual([b["source"] for b in blocks], ["S2", "S1"])
        self.assertEqual(blocks[0]["cited"], ["U2"])
        self.assertEqual(related_examples({"routing": {"route": "mad"}}, {}), [])


if __name__ == "__main__":
    unittest.main()
