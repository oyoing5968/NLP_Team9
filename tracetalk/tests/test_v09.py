"""0.7 / PROTOCOL v9: the team's result card and candidate MAD. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tracetalk.mad.card import (CardAnalyzer, card_request, easy_problem, entries_from_request, entries_from_store, find,
                           form_patterns, remains, sentence_problems, strip_han)
from tracetalk.web.server import make_server
from frontier_fixture import FixtureClient
from tracetalk.mad import card as card_module

def setUpModule():  # these tests are about the 0.7-0.8 routes, still selectable (card.CARD decide="roles", unknown="mad")
    card_module.CARD.update(decide="roles", unknown="mad", pick=False)


def tearDownModule():
    card_module.CARD.update(decide="witness", unknown="read", pick=True)


LEXICON = [{"id": "lx-1", "expression": "긁히다", "variants": [], "meaning": "상대의 말에 자극받아 발끈하다",
            "family": "kc:긁히다", "source": "test", "license": "test", "origin": "긁다의 피동", "pos": "동사"},
           {"id": "lx-2", "expression": "각", "variants": [], "meaning": "角 무엇인가 벌어질 것 같은 상황",
            "family": "kc:각", "source": "test", "license": "test"},
           {"id": "lx-3", "expression": "제조기", "variants": [], "meaning": "제조기(製造機)는 물건을 만드는 기계",
            "family": "kc:제조기", "source": "test", "license": "test"}]
USAGES = [{"id": "u-1", "expression": "야르", "variants": [], "lines": [
    {"text": f"TEST 용례 {i} 야르~", "context": "", "row": "u-1", "source": "TEST", "license": "test", "note": "",
     "added_at": "2026-11-03"} for i in range(1, 7)]}]


def stages(client):
    return [r.get("stage", "probe:" + r.get("probe", "")) for r in client.requests]


def analyzer(client=None, **config):
    client = client or FixtureClient()
    return client, CardAnalyzer(client, lexicon=LEXICON, usages=USAGES, config=config or None)


class MatchingTests(unittest.TestCase):
    def test_inflected_verbs_spaces_and_lone_letters(self):
        entries = entries_from_store(LEXICON, USAGES)
        spans = lambda text: [h["span"] for h in find(text, entries)]
        self.assertEqual(spans("쟤 방금 긁힌거 같은데?"), ["긁힌"])
        self.assertEqual(spans("완전 긁혔네"), ["긁혔"])
        self.assertEqual(spans("나 다음 주에 갈 각ㅋㅋㅋ"), ["각"])
        self.assertEqual(spans("그런 생각 한 사람?"), [])  # 각 inside 생각 is not the slang 각
        self.assertEqual(spans("야 르~ 맛있다"), ["야 르"])
        import re
        self.assertTrue(any(re.search(p, "또 발끈했어") for p in form_patterns("발끈하다")))
        self.assertFalse(any(re.search(p, "보고 싶다") for p in form_patterns("보다")))

    def test_store_rows_and_korean_only_meanings(self):
        rows = {r["expression"]: r for r in entries_from_store(LEXICON, USAGES)}
        self.assertEqual(rows["긁히다"]["senses"][0]["pos"], "동사")
        self.assertEqual(len(rows["야르"]["usage_group"]["lines"]), 6)
        self.assertEqual(strip_han(LEXICON[1]["meaning"]), "무엇인가 벌어질 것 같은 상황")
        self.assertEqual(strip_han(LEXICON[2]["meaning"]), "제조기는 물건을 만드는 기계")

    def test_team_db_rows_are_checked(self):
        rows = entries_from_request([{"expression": "긁히다", "variants": ["긁힌"],
                                      "senses": [{"meaning": "발끈하다", "origin": "", "pos": "동사", "source": "팀"}],
                                      "usages": [{"text": "하 개긁힌다", "source": "팀"}]}])
        self.assertEqual(rows[0]["usage_group"]["lines"][0]["row"], "live-db0")
        for bad in ([{"expression": ""}], [{"expression": "a", "senses": [{"meaning": 3}]}],
                    [{"expression": "a", "extra": 1}], "not a list"):
            with self.assertRaises(ValueError):
                entries_from_request(bad)
        with self.assertRaises(ValueError):
            card_request({"text": "x", "mode": "routed"})
        self.assertEqual(card_request({"text": "x"})["max_seconds"], 300)


class CardTests(unittest.TestCase):
    def test_plain_comment_needs_no_generation_but_detection(self):
        client, a = analyzer()
        result = a.run(text="점심으로 김치찌개를 먹었는데 조금 짰다.")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["card"]["plain"])
        self.assertEqual(result["card"]["sentence"], "점심으로 김치찌개를 먹었는데 조금 짰다.")
        self.assertEqual(sorted(stages(client)), ["detect", "probe:has_slang"])

    def test_one_fitting_sense_is_one_call_and_the_sentence_is_checked(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        item = result["card"]["items"][0]
        self.assertEqual((item["expression"], item["headword"], item["decided_by"], item["basis"]),
                         ("긁힌", "긁히다", "single", "db"))
        self.assertEqual((item["origin"], item["pos"], item["choice"]), ("긁다의 피동", "동사", "C1"))
        self.assertEqual(result["card"]["sentence"], "쟤 방금 쉬운 말거 같은데?")
        self.assertEqual(stages(client).count("single"), 1)
        self.assertNotIn("propose", stages(client))

    def test_doubtful_sense_goes_to_candidate_mad_with_literal_and_none(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.4
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        item = result["card"]["items"][0]
        self.assertEqual(item["decided_by"], "mad")
        self.assertEqual([s for s in stages(client) if s in ("propose", "review", "judge")],
                         ["propose", "propose", "review", "review", "judge"])
        judge = next(r for r in client.requests if r.get("stage") == "judge")
        ids = [c["id"] for c in judge["unverified_hypotheses"]["db_candidates"]]
        self.assertEqual(ids, ["C1", "L", "N"])
        self.assertEqual(len(judge["unverified_hypotheses"]["hypotheses"]), 2)

    def test_an_ordinary_word_in_the_db_is_dropped(self):
        # v9.1: a longer DB word the probes doubt is decided once (literal option included) and dropped only when read
        # literally; the 11-03 pilot dropped true new words unasked.
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.05
        client.hook = lambda payload, data: data.update(choice="L") if payload.get("stage") == "single" else None
        result = a.run(text="오늘 제조기 고장 났어", mode="card_single")
        self.assertTrue(result["card"]["plain"])
        self.assertEqual(result["detection"]["db_hits"][0]["expression"], "제조기")
        self.assertEqual(result["detection"]["ordinary_words"], ["제조기"])
        self.assertEqual(stages(client).count("single"), 1)

    def test_unknown_word_is_a_marked_guess(self):  # the 0.7 path (0.8 card: unknown="mad", test_v08)
        client, a = analyzer(unknown="guess")
        client.detect = lambda text: ["뇽뇽"]
        result = a.run(text="뇽뇽 맛있다")
        item = result["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["choice"], item["headword"]), ("guess", "model", "N", None))
        single = next(r for r in client.requests if r.get("stage") == "single")
        self.assertIn("팀 DB에 없다", single["role"])

    def test_fresh_word_with_usages_is_usage_mad_with_held_out_checks(self):
        client, a = analyzer()
        # No DB meaning: the candidates are only "literal" and "none of these" (a new meaning from the usages).
        client.hook = lambda payload, data: data.update(choice="N") if payload["stage"] == "judge" else None
        result = a.run(text="야르~ 맛있다")
        item = result["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["usage_lines"]), ("mad", "usage", 6))
        self.assertEqual(item["supporting_usages"], ["U1", "U2"])
        self.assertEqual(item["detail"]["held_out_checked"], [True, True])
        proposals = [r for r in client.requests if r.get("stage") == "propose"]
        self.assertEqual([len(p["observed_usages"]) for p in proposals], [3, 3])
        self.assertEqual(item["related_usage"]["id"], "U1")

    def test_foreign_text_and_unknown_candidates_are_asked_again_once(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        seen = []

        def hook(payload, data):
            if payload["stage"] == "single":
                seen.append(1)
                if len(seen) == 1:
                    data["meaning"] = "화가 나다 生气"
        client.hook = hook
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual(result["status"], "completed")
        singles = [c for c in result["calls"] if c["stage"] == "single"]
        self.assertEqual([c["valid"] for c in singles], [False, True])
        self.assertIn("한국어가 아닌", singles[0]["error"])

        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(choice="C9") if payload["stage"] == "single" else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        # The only expression failed, so the card is a failure (with the failed item kept for the record).
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["card"]["items"][0]["status"], "failed")

    def test_clues_not_in_the_comment_are_dropped_not_fatal(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(clues=["원문에 없는 말", "긁힌"]) if "clues" in data else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        item = result["card"]["items"][0]
        self.assertEqual(item["clues"], ["긁힌"])
        self.assertEqual(result["status"], "completed")

    def test_a_bad_sentence_is_retried_then_swapped_by_the_system_or_left_out_with_reasons(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(sentence=payload["original_text"]) if "sentence" in data else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        sentence_calls = [r for r in client.requests if r.get("stage") == "sentence"]
        self.assertEqual(len(sentence_calls), 2)
        self.assertIn("problems", sentence_calls[1]["unverified_hypotheses"])
        # v9.3: the model kept the expression twice -> the system swaps just that word, and says so.
        self.assertEqual((result["card"]["sentence"], result["card"]["sentence_by"]), ("쟤 방금 쉬운 말거 같은데?", "system"))
        # v9.4: a sentence that also changed the rest of the comment -> the system swaps the words in the comment itself.
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(sentence="긁힌 오늘 날씨가 아주 좋다요") if "sentence" in data else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual((result["card"]["sentence"], result["card"]["sentence_by"]), ("쟤 방금 쉬운 말거 같은데?", "system"))
        # Only with no usable easy words is there no sentence, with the reasons.
        client, a = analyzer()
        client.probe = lambda p: 0.9
        def hook(payload, data):
            if payload.get("stage") in ("single", "easy"):
                data["easy"] = ""
            if "sentence" in data:
                data["sentence"] = payload["original_text"]
        client.hook = hook
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual(result["card"]["items"][0]["easy"], "")
        self.assertIsNone(result["card"]["sentence"])
        self.assertIsNone(result["card"]["sentence_by"])
        self.assertTrue(any("그대로 남아" in p for p in result["card"]["sentence_problems"]))

    def test_team_db_replaces_the_local_store(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        result = a.run(text="야르~ 맛있다", db=[{"expression": "야르", "senses": [{"meaning": "감탄사", "source": "팀"}]}])
        item = result["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["usage_lines"]), ("single", "db", 0))

    def test_card_single_never_debates(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.4
        result = a.run(text="쟤 방금 긁힌거 같은데?", mode="card_single")
        self.assertEqual(result["card"]["items"][0]["decided_by"], "single")
        self.assertNotIn("propose", stages(client))


class PickTests(unittest.TestCase):
    def test_single_vote_and_mad_choose_a_given_candidate(self):
        for method, calls in (("single", 1), ("vote", 5), ("mad", 5)):
            client, a = analyzer()
            out = a.pick("이 신조어 문장", "신조어", ["뜻 하나", "뜻 둘"], method)
            self.assertEqual((out["status"], out["choice"]), ("completed", "C1"), method)
            self.assertEqual(sum(1 for c in out["calls"] if c["valid"]), calls, method)

    def test_split_vote_abstains(self):
        client, a = analyzer()
        n = []

        def hook(payload, data):
            n.append(1)
            data["choice"] = ["C1", "C2", "N", "C1", "C2"][len(n) - 1]
        client.hook = hook
        out = a.pick("이 신조어 문장", "신조어", ["뜻 하나", "뜻 둘"], "vote")
        self.assertIsNone(out["choice"])
        self.assertIn("갈렸습니다", out["final"]["uncertainty"])


class SentenceCheckTests(unittest.TestCase):
    def test_problems(self):
        items = [{"expression": "긁힌", "status": "proposed", "choice": "C1", "start": 5, "end": 7}]
        self.assertEqual(sentence_problems("쟤 방금 긁힌거 같은데?", "쟤 방금 발끈한 거 같은데?", items), [])
        self.assertTrue(sentence_problems("쟤 방금 긁힌거 같은데?", "긁힌", items))
        self.assertTrue(any("나머지" in p for p in sentence_problems("쟤 방금 긁힌거 같은데?", "오늘 날씨가 아주 좋다요", items)))


class ServerTests(unittest.TestCase):
    def test_interpret_endpoint_and_card_jobs(self):
        client = FixtureClient()
        client.probe = lambda p: 0.9
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(client, port=0, output_dir=temp, lexicon=LEXICON)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"

            def request(path, body=None):
                req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.load(response)
            try:
                card = request("/api/interpret", {"text": "쟤 방금 긁힌거 같은데?"})
                self.assertEqual((card["status"], card["card"]["items"][0]["headword"]), ("completed", "긁히다"))
                team = request("/api/interpret", {"text": "야르~ 맛있다",
                                                  "db": [{"expression": "야르", "senses": [{"meaning": "감탄사"}]}]})
                self.assertEqual(team["card"]["items"][0]["basis"], "db")
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    request("/api/interpret", {"text": "x", "db": [{"expression": ""}]})
                self.assertEqual(bad.exception.code, 400)
                job = request("/api/analyze", {"text": "쟤 방금 긁힌거 같은데?", "mode": "card"})["job_id"]
                for _ in range(300):
                    state = request("/api/jobs/" + job)
                    if state["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(state["result"]["card"]["items"][0]["expression"], "긁힌")
                self.assertIn("card", request("/api/config")["modes"])
            finally:
                server.shutdown()
                server.server_close()


class LabPipelineTests(unittest.TestCase):
    """run_bench (card) -> grade (card judge + 6-3-1) and run_pick through the Ollama-shaped HTTP fixture."""

    def test_card_bench_grade_and_pick(self):
        import contextlib
        import io
        import sys
        from pathlib import Path
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
        import grade
        import run_bench
        import run_pick
        import http.server
        from test_local_verification import OllamaFixture
        http.server.ThreadingHTTPServer.request_queue_size = 64  # parallel probes burst past the default backlog

        def run_main(module, argv):
            with patch.object(sys, "argv", ["prog"] + argv), contextlib.redirect_stdout(io.StringIO()):
                return module.main()

        def write(path, rows):
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp, OllamaFixture() as backend:
            d = Path(temp)
            write(d / "in.jsonl", [{"id": "k1", "text": "쟤 방금 긁힌거 같은데?", "family": "f1", "split": "diagnostic"}])
            write(d / "gold.jsonl", [{"case_id": "k1", "family": "f1", "stratum": "y2024", "expression": "긁히다",
                                      "reference_meaning": "발끈하다", "source": "t", "source_date": "", "license": "t",
                                      "review_status": "t"}])
            write(d / "lex.jsonl", LEXICON[:1])
            base = ["--model", backend.client.config.model, "--base-url", f"http://127.0.0.1:{backend.server.server_port}"]
            self.assertEqual(run_main(run_bench, base + ["--inputs", str(d / "in.jsonl"), "--methods", "card", "card_single",
                                                         "--lexicon", str(d / "lex.jsonl"), "--output", str(d / "runs.jsonl")]), 0)
            records = [json.loads(x) for x in (d / "runs.jsonl").read_text().splitlines()]
            self.assertEqual({r["method"]: r["result"]["card"]["items"][0]["headword"] for r in records},
                             {"card": "긁히다", "card_single": "긁히다"})
            original = backend.client.generate

            def judge(messages, schema, seed, max_tokens):
                props = schema.get("properties", {})
                if "sentence" in props and "verdict" in props:
                    raw = {"verdict": "correct", "literal_misread": "no", "sentence": "yes", "reason": "TEST"}
                elif "semantic_equivalence" in props:
                    raw = {"semantic_equivalence": 2, "coverage": 1, "pragmatic_equivalence": 2, "conciseness": 1,
                           "non_circularity": 1, "lexicographic": 1, "factuality": 1, "gold_content_words": ["발끈"],
                           "comment": "TEST"}
                else:
                    return original(messages, schema, seed, max_tokens)
                return {"raw": json.dumps(raw, ensure_ascii=False), "finish_reason": "stop"}
            backend.client.generate = judge
            self.assertEqual(run_main(grade, base + ["--runs", str(d / "runs.jsonl"), "--gold", str(d / "gold.jsonl"),
                                                     "--rubric", "koneo", "--output", str(d / "graded.jsonl")]), 0)
            rows = [json.loads(x) for x in (d / "graded.jsonl").read_text().splitlines()]
            self.assertEqual({(r["verdict"], r["sentence"], r["target_found"], r["rubric"]["total"]) for r in rows},
                             {("correct", "yes", True, 9)})
            import card_report
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                card_report.main(["--runs", str(d / "runs.jsonl"), "--graded", str(d / "graded.jsonl")])
            report = buffer.getvalue()
            self.assertIn("끝까지 OK 1", report)
            self.assertIn("6-3-1 평균 9.00/10", report)
            self.assertIn("예) 쟤 방금 긁힌거 같은데?", report)
            # The fixture judge says "correct" to everything: a card that never found the word is wrong by rule,
            # and a plain sentence (no expression) is left to the judge.
            for name, expression, want in (("miss", "갓생", {("wrong", "correct", False)}),
                                           ("plain", "", {("correct", None, False)})):
                write(d / f"gold_{name}.jsonl", [{"case_id": "k1", "family": "f1", "stratum": "y2024",
                                                  "expression": expression, "reference_meaning": "가",
                                                  "source": "t", "source_date": "", "license": "t",
                                                  "review_status": "t"}])
                self.assertEqual(run_main(grade, base + ["--runs", str(d / "runs.jsonl"), "--gold",
                                                         str(d / f"gold_{name}.jsonl"), "--output",
                                                         str(d / f"graded_{name}.jsonl")]), 0)
                rows = [json.loads(x) for x in (d / f"graded_{name}.jsonl").read_text().splitlines()]
                self.assertEqual({(r["verdict"], r.get("judge_verdict"), r["target_found"]) for r in rows}, want)
            backend.client.generate = original
            write(d / "k2.jsonl", [{"id": "kn2-w-1", "text": "갓생 산다", "expression": "갓생", "meanings": ["가", "나"],
                                    "answer": "C1", "variant": "with_answer", "year": "2024", "near_ids": ["C2"]},
                                   {"id": "kn2-n-1", "text": "갓생 산다", "expression": "갓생", "meanings": ["가", "나"],
                                    "answer": "N", "variant": "none", "year": "2024", "near_ids": ["C1"]}])
            self.assertEqual(run_main(run_pick, base + ["--items", str(d / "k2.jsonl"), "--workers", "1",
                                                        "--output", str(d / "k2out.jsonl")]), 0)
            picks = [json.loads(x) for x in (d / "k2out.jsonl").read_text().splitlines()]
            self.assertEqual(len(picks), 6)
            # The fixture always picks the first candidate: right with the answer present, wrong (and "near") without.
            self.assertEqual({(r["variant"], r["correct"], r["near"]) for r in picks},
                             {("with_answer", True, False), ("none", False, True)})


class UpdateTests(unittest.TestCase):
    def test_an_added_entry_reaches_the_card_with_origin_and_pos(self):
        import contextlib
        import io
        from pathlib import Path
        from tracetalk.db import update as update_db
        from tracetalk.db.usage import LiveStore
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            live = Path(temp)
            update_db.main(["--live", temp, "add-entry", "--expression", "긁히다", "--meaning", "TEST 발끈하다",
                            "--origin", "TEST 긁다의 피동", "--pos", "동사", "--source", "TEST 팀"])
            update_db.main(["--live", temp, "add-usage", "--expression", "긁히다", "--text", "TEST 하 개긁힌다",
                            "--source", "TEST 팀"])
            store = LiveStore([live / "entries.jsonl"], [live / "usages.jsonl"])
            lexicon, usages = store.current()
        client = FixtureClient()
        client.probe = lambda p: 0.9
        result = CardAnalyzer(client, lexicon=lexicon, usages=usages).run(text="쟤 방금 긁힌거 같은데?")
        item = result["card"]["items"][0]
        self.assertEqual((item["origin"], item["pos"], item["related_usage"]["text"]),
                         ("TEST 긁다의 피동", "동사", "TEST 하 개긁힌다"))


class InterpretTests(unittest.TestCase):
    def test_one_call_module_with_team_rows_or_the_local_store(self):
        from tracetalk.mad.card import interpret
        client = FixtureClient()
        client.probe = lambda p: 0.9
        card = interpret("쟤 방금 긁힌거 같은데?", db=[{"expression": "긁히다", "senses": [{"meaning": "발끈하다"}]}],
                         client=client)
        self.assertEqual(card["card"]["items"][0]["basis"], "db")
        local = interpret("딱 봐도 겉바속촉느낌 충만ㅋㅋ", client=FixtureClient())
        self.assertEqual(local["detection"]["db_hits"][0]["expression"], "겉바속촉")


class ReviewFixTests(unittest.TestCase):
    """11-03 independent review: spans, DB lookup, case, vote, K2 role, timeouts, the sentence check."""
    LEX = [{"id": "lx-g", "expression": "갓생", "variants": [], "meaning": "모범적이고 부지런한 삶", "family": "kc:갓생",
            "source": "test", "license": "test"},
           {"id": "lx-j", "expression": "JMT", "variants": [], "meaning": "매우 맛있음", "family": "kc:jmt",
            "source": "test", "license": "test"}] + LEXICON

    def run_card(self, text, detect=(), probe=0.9, hook=None, **request):
        client = FixtureClient()
        client.probe = lambda p: probe
        client.detect = lambda t: list(detect)
        client.hook = hook
        return client, CardAnalyzer(client, lexicon=self.LEX, usages=[]).run(text=text, **request)

    def test_the_models_longer_word_around_a_db_hit_is_analyzed_with_the_hit_as_a_candidate(self):
        _, result = self.run_card("오늘도 갓생러 모드", detect=["갓생러"])
        item = result["card"]["items"][0]
        self.assertEqual((item["expression"], item["headword"], item["db_span"], item["flagged_by_model"]),
                         ("갓생러", "갓생", "갓생", True))
        # A phrase with spaces around a hit keeps the DB word.
        _, result = self.run_card("쟤 방금 긁힌거 같은데?", detect=["긁힌거 같은데"])
        self.assertEqual(result["card"]["items"][0]["expression"], "긁힌")

    def test_model_spans_the_patterns_miss_are_looked_up_and_case_is_ignored(self):
        _, result = self.run_card("이거 완전 각이네", detect=["각이네"])
        self.assertEqual(result["card"]["items"][0]["headword"], "각")
        _, result = self.run_card("이 라면 jmt", detect=[])
        self.assertEqual(result["card"]["items"][0]["headword"], "JMT")
        import re
        self.assertTrue(any(re.search(p, "아 안됐네") for p in form_patterns("안되다")))

    def test_a_one_letter_model_span_is_not_placed_inside_a_word(self):
        _, result = self.run_card("생각해보니 다음 주에 갈 각", detect=["각"])
        item = next(i for i in result["card"]["items"] if i["headword"] == "각")
        self.assertEqual(item["start"], len("생각해보니 다음 주에 갈 "))

    def test_vote_survives_a_broken_sample_and_k2_never_offers_the_literal_option(self):
        client, a = analyzer()
        n = []

        def hook(payload, data):
            n.append(1)
            if len(n) <= 2:  # the first sample breaks twice
                data["choice"] = "C9"
        client.hook = hook
        out = a.pick("이 신조어 문장", "신조어", ["뜻 하나", "뜻 둘"], "vote")
        self.assertEqual((out["status"], out["choice"], out["detail"]["failed_votes"]), ("completed", "C1", 1))
        asked = [r for r in client.requests if r.get("stage") == "single"][-1]
        self.assertNotIn("'L'", asked["role"])
        self.assertEqual(asked["output_schema"]["properties"]["choice"]["enum"], ["C1", "C2", "N"])

    def test_running_out_of_time_keeps_the_finished_expression(self):
        from tracetalk.mad.engine import BudgetExceeded

        def hook(payload, data):
            if (payload.get("unverified_hypotheses") or {}).get("target_expression") == "각":
                raise BudgetExceeded("TEST 시간 예산")
        _, result = self.run_card("쟤 방금 긁힌거 같은데? 갈 각", detect=["각"], hook=hook)
        self.assertEqual(result["status"], "partial")
        states = {i["expression"]: i["status"] for i in result["card"]["items"]}
        self.assertEqual(states, {"긁힌": "proposed", "각": "failed"})
        self.assertTrue(next(i for i in result["card"]["items"] if i["expression"] == "각")["timed_out"])

    def test_sentence_check_ignores_words_that_merely_contain_the_expression(self):
        items = [{"expression": "각", "status": "proposed", "choice": "C1", "easy": "그럴 것 같다", "start": 12, "end": 13}]
        self.assertEqual(sentence_problems("생각해보니 다음 주에 갈 각ㅋㅋ", "생각해보니 다음 주에 갈 것 같다ㅋㅋ", items), [])
        self.assertTrue(sentence_problems("생각해보니 다음 주에 갈 각ㅋㅋ", "생각해보니 다음 주에 갈 각ㅋㅋ", items))



class PilotFixTests(unittest.TestCase):
    """11-03 v9 pilot: dropped true words, unusable easy words, a gloss in a note, unchanged sentences."""

    def test_a_doubted_longer_db_word_is_kept_when_the_decision_reads_the_db_sense(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.01
        result = a.run(text="오늘 제조기 고장 났어", mode="card_single")
        item = result["card"]["items"][0]
        self.assertEqual((item["expression"], item["choice"], item["basis"]), ("제조기", "C1", "db"))
        self.assertEqual(result["detection"]["ordinary_words"], [])

    def test_a_one_letter_db_form_the_probes_doubt_is_dropped_without_a_call(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.01
        result = a.run(text="다음 주에 갈 각", mode="card_single")
        self.assertTrue(result["card"]["plain"])
        self.assertEqual(result["detection"]["ordinary_words"], ["각"])
        self.assertNotIn("single", stages(client))

    def test_easy_words_must_replace_the_expression(self):
        self.assertIsNone(easy_problem("각", "갈 것 같다"))
        self.assertTrue(easy_problem("각", "생각대로 될 듯"))  # v9.4: a one-letter form anywhere ('시각' read "갈 시각")
        self.assertTrue(easy_problem("각", "시각"))
        self.assertTrue(easy_problem("마기꾼", "마스크빨이 큰 사람", "마기꾼일 확률 99% 마스크빨 무시 못함", ["마스크빨"]))
        self.assertIsNone(easy_problem("마기꾼", "마스크 벗으면 다른 사람", "마기꾼일 확률", ["마스크빨"]))
        self.assertTrue(easy_problem("각", "할 각이다"))
        comment = "ㄱ- 와... 그거 필터임..? 난 진짜 얼굴인 줄..."
        self.assertTrue(easy_problem("ㄱ-", "와... 그거 필터임..? 난 진짜 얼굴인 줄...", comment))
        self.assertIsNone(easy_problem("ㄱ-", "어이없네", comment))
        self.assertIsNone(easy_problem("가슴에 국밥 쏟음", "진짜 감동", "그런 선배는 진짜 가슴에 국밥 쏟음이지"))
        self.assertTrue(easy_problem("JMT", "jmt 맛"))
        self.assertIsNone(easy_problem("가슴에 국밥 쏟음", "가슴이 뜨거워짐"))

    def test_bad_easy_words_are_asked_again_then_blanked_not_failed(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(easy="긁힌 것") if payload.get("stage") == "single" else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual(result["status"], "completed")
        item = result["card"]["items"][0]
        # v9.3: blanked easy words go to the easy step, which writes new ones for the decided meaning.
        self.assertEqual((item["status"], item["easy"]), ("proposed", "고친 쉬운 말"))
        self.assertIn("표현 자체", item["detail"]["easy_rejected"])
        self.assertTrue(item["detail"]["easy_fit"]["rewritten"])
        singles = [c for c in result["calls"] if c["stage"] == "single"]
        self.assertEqual([c["valid"] for c in singles], [False, True])
        asked = [r for r in client.requests if r.get("stage") == "single"]  # v9.2: the retry says what was wrong
        self.assertNotIn("previous_problem", asked[0]["unverified_hypotheses"])
        self.assertIn("표현 자체", asked[1]["unverified_hypotheses"]["previous_problem"])
        # K2 picks never check easy words (the choice is all that is scored).
        out = CardAnalyzer(client).pick("쟤 방금 긁힌거 같은데?", "긁히다", ["가", "나"], "single", 1, 60)
        self.assertEqual(out["status"], "completed")

    def test_a_gloss_in_a_note_is_stripped_not_fatal(self):
        client, a = analyzer()
        client.detect = lambda text: ["가즈아"]
        client.hook = lambda payload, data: data.update(note="가자(行こう)의 변형") if "note" in data else None
        result = a.run(text="대박 나세요 가즈아!")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["detection"]["model_note"], "가자의 변형")
        # v9.5: 가즈아 has neither a DB sense nor usages here, so it is a guess the sentence leaves as written
        self.assertEqual((result["card"]["sentence"], result["card"]["kept_estimates"]), (None, ["가즈아"]))
        self.assertIn("근거 있는 뜻이 없어", result["card"]["sentence_problems"][0])

    def test_easy_words_that_miss_the_meaning_are_rewritten_once_and_the_better_kept(self):
        client, a = analyzer()
        client.probe = lambda p: {"easy_fit": 0.1 if p.get("easy") == "쉬운 말" else 0.8}.get(p["probe"], 0.9)
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        item = result["card"]["items"][0]
        self.assertEqual(item["easy"], "고친 쉬운 말")
        self.assertEqual(item["detail"]["easy_fit"], {"p": [0.1, 0.8], "rewritten": True})
        easy = next(r for r in client.requests if r.get("stage") == "easy")
        self.assertEqual(easy["unverified_hypotheses"]["previous_easy"], "쉬운 말")
        # A rewrite that probes no better is not taken, and a probe alone never blanks easy words.
        client, a = analyzer()
        client.probe = lambda p: 0.1 if p["probe"] == "easy_fit" else 0.9
        item = a.run(text="쟤 방금 긁힌거 같은데?")["card"]["items"][0]
        self.assertEqual((item["easy"], item["detail"]["easy_fit"]["rewritten"]), ("쉬운 말", False))

    def test_a_model_only_span_read_as_a_standard_word_is_dropped_and_clauses_are_skipped(self):  # the 0.7 path (0.8 card: unknown="mad", test_v08)
        client, a = analyzer(unknown="guess")
        client.detect = lambda text: ["개운", "스킬 막 쓰다가 자폭한 거잖아"]
        client.hook = lambda payload, data: data.update(choice="L") if payload.get("stage") == "single" else None
        result = a.run(text="그렇게 자면 개운하겠다 스킬 막 쓰다가 자폭한 거잖아")
        self.assertTrue(result["card"]["plain"])
        self.assertEqual(result["detection"]["ordinary_words"], ["개운"])
        self.assertEqual(result["detection"]["long_model_spans"], 1)
        guess = next(r for r in client.requests if r.get("stage") == "single")
        self.assertEqual([c["id"] for c in guess["unverified_hypotheses"]["db_candidates"]], ["N", "L"])

    def test_a_repeated_easy_word_or_a_dropped_clause_is_a_sentence_problem(self):
        text = "ㅇㅇ 마기꾼일 확률 99%임 ㅋㅋㅋ"
        items = [{"expression": "마기꾼", "status": "proposed", "choice": "C1", "easy": "외모가 달라 보이는 사람",
                  "start": 3, "end": 6}]
        self.assertEqual(sentence_problems(text, "ㅇㅇ 외모가 달라 보이는 사람일 확률 99%임 ㅋㅋㅋ", items), [])
        self.assertTrue(any("여러 번" in p for p in sentence_problems(
            text, "ㅇㅇ 외모가 달라 보이는 사람 외모가 달라 보이는 사람일 확률 99%임 ㅋㅋㅋ", items)))
        long = "시험 기간이 되자 족보 꿀팁을 얻으려고 공부하는 후배들은 모두 동아리방으로 몰렸다."
        items = [{"expression": "꿀팁", "status": "proposed", "choice": "N", "easy": "유용한 정보", "start": 13, "end": 15}]
        self.assertTrue(any("빠졌습니다" in p for p in sentence_problems(long, "시험 기간이 되자 동아리방으로 몰렸다.", items)))

    def test_the_literal_option_is_the_dictionary_sense_only_and_the_slang_probe_can_be_skipped(self):  # the 0.7 path (0.8 card: unknown="mad", test_v08)
        client, a = analyzer(unknown="guess")
        client.detect = lambda text: ["동결건조"]
        a.run(text="우리엄마를 동결건조해주세요")
        guess = next(r for r in client.requests if r.get("stage") == "single")
        self.assertIn("비유·밈으로 쓴 것이면 choice='N'", guess["role"])
        literal = next(c for c in guess["unverified_hypotheses"]["db_candidates"] if c["id"] == "L")
        self.assertIn("비유·밈·과장으로 쓰인 것이 아님", literal["meaning"])
        self.assertIn("probe:has_slang", stages(client))
        client, a = analyzer(slang_probe=False)
        result = a.run(text="점심으로 김치찌개를 먹었는데 조금 짰다.")
        self.assertNotIn("probe:has_slang", stages(client))
        self.assertIsNone(result["detection"]["p_has_slang"])

    def test_easy_words_with_another_expression_of_the_comment_are_asked_again(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.detect = lambda text: ["마스크빨"]
        def hook(payload, data):
            if payload.get("stage") == "single" and payload["unverified_hypotheses"]["target_expression"] == "긁힌" \
                    and "previous_problem" not in payload["unverified_hypotheses"]:
                data["easy"] = "마스크빨 난"
        client.hook = hook
        result = a.run(text="쟤 방금 긁힌거 같은데? 마스크빨 무시 못함")
        item = next(i for i in result["card"]["items"] if i["expression"] == "긁힌")
        retry = [r for r in client.requests if r.get("stage") == "single"
                 and r["unverified_hypotheses"]["target_expression"] == "긁힌"]
        self.assertIn("다른 신조어", retry[1]["unverified_hypotheses"]["previous_problem"])
        self.assertEqual(item["easy"], "쉬운 말")

    def test_kana_in_an_internal_review_is_stripped_not_fatal(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9 if p["probe"] == "has_slang" else 0.4
        client.hook = lambda payload, data: data.update(revised_meaning="가자(行こう)의 변형") if payload.get("stage") == "review" else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["card"]["items"][0]["decided_by"], "mad")
        judge = next(r for r in client.requests if r.get("stage") == "judge")
        self.assertEqual(judge["unverified_hypotheses"]["hypotheses"][0]["revised"]["meaning"], "가자의 변형")
        # A shown output (the card item) still has to be Korean and is asked again.
        client, a = analyzer()
        client.probe = lambda p: 0.9
        client.hook = lambda payload, data: data.update(easy="가자(行こう)") if payload.get("stage") == "single" else None
        result = a.run(text="쟤 방금 긁힌거 같은데?")
        self.assertEqual(result["card"]["items"][0]["status"], "failed")

    def test_the_sentence_step_gets_explicit_replacements_and_one_letter_leftovers_count(self):
        client, a = analyzer()
        client.probe = lambda p: 0.9
        a.run(text="쟤 방금 긁힌거 같은데?")
        sent = next(r for r in client.requests if r.get("stage") == "sentence")
        self.assertEqual(sent["unverified_hypotheses"]["replace"], [{"expression": "긁힌", "easy": "쉬운 말"}])
        self.assertTrue(remains("각", "오 진짜? 어떡하지 나 다음 주에 갈 각이다 ㅋㅋ", "할 것 같다"))
        self.assertFalse(remains("각", "생각해 보니 갈 것 같다", "갈 것 같다"))
        items = [{"expression": "각", "status": "proposed", "choice": "C1", "easy": "갈 것 같다", "start": 0, "end": 1}]
        self.assertIn("'갈 것 같다'로 바꿔야", sentence_problems("갈 각", "갈 각이다", items)[0])


if __name__ == "__main__":
    unittest.main()
