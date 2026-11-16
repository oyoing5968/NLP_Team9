"""Offline DB retriever (tracetalk/db/retriever.py). Stages whose library is missing are skipped; on the Mac the suite also
runs under mac/run.sh (venv with rapidfuzz, kiwipiepy, chromadb) so every stage is exercised."""
import unittest
import uuid

from tracetalk.mad.card import CardAnalyzer, entries_from_request, entries_from_store, find
from tracetalk.db import retriever as R
from frontier_fixture import V011, FixtureClient

LEX = [{"id": f"lx-{i}", "expression": e, "variants": [], "meaning": m, "family": f"kc:{e}", "source": "test",
        "license": "test"} for i, (e, m) in enumerate([("오또카지", "어떡하지"), ("마기꾼", "마스크 벗으면 다른 얼굴"),
                                                       ("갓생", "부지런한 삶"), ("귀엽다", "사랑스럽다"),
                                                       ("긁히다", "자극받아 발끈하다")])]
USAGES = [{"id": "u-1", "expression": "긁히다", "variants": [], "lines": [
    {"text": t, "context": "", "row": row, "source": "TEST", "license": "test", "note": "", "added_at": ""}
    for t, row in (("롤 지고 개긁혔음", "kc-1"), ("시험 망해서 긁힘", "kc-2"), ("팀원 말에 긁혀서 발끈", "live-1"))]}]
ENTRIES = entries_from_store(LEX, USAGES)


class ExactOnlyTests(unittest.TestCase):
    def test_without_the_optional_stages_hits_are_the_exact_patterns(self):
        r = R.Retriever(stages=("exact",))
        text = "오또카지 나 다음 주에 긁힌거 같음"
        self.assertEqual(r.stages, ("exact",))
        self.assertEqual([(h["span"], h["stage"]) for h in r.hits(text, ENTRIES)],
                         [(h["span"], "exact") for h in find(text, ENTRIES)])
        self.assertEqual(r.evidence(USAGES[0], text, 6)[0]["row"], "live-1")  # the tracetalk.db.usage order
        with self.assertRaises(ValueError):
            R.Retriever(stages=("exact", "web"))

    def test_rows_are_team_rows_with_the_match_and_feed_the_card(self):
        r = R.Retriever(stages=("exact",))
        rows = r.rows("쟤 방금 긁힌거 같은데?", ENTRIES)
        self.assertEqual([(x["expression"], x["match"]["span"], x["match"]["stage"]) for x in rows],
                         [("긁히다", "긁힌", "exact")])
        self.assertEqual(rows[0]["senses"][0]["meaning"], "자극받아 발끈하다")
        self.assertEqual(entries_from_request(rows)[0]["match"]["span"], "긁힌")

    def test_a_team_rows_match_places_a_typo_the_patterns_miss(self):
        rows = [{"expression": "오또카지", "senses": [{"meaning": "어떡하지"}],
                 "match": {"span": "오또카찌", "start": 0, "end": 4, "stage": "fuzzy", "score": 87.5}}]
        client = FixtureClient()
        client.probe = lambda p: 0.9
        result = CardAnalyzer(client, config=V011).run(text="오또카찌 나 늦었어", db=rows)
        self.assertEqual([(h["span"], h["stage"]) for h in result["detection"]["db_hits"]], [("오또카찌", "fuzzy")])
        self.assertEqual(result["card"]["items"][0]["headword"], "오또카지")
        # A match that does not sit at its place in the comment is ignored.
        rows[0]["match"]["start"] = 1
        self.assertEqual(CardAnalyzer(client, config=V011).run(text="오또카찌 나 늦었어", db=rows)["detection"]["db_hits"], [])

    def test_the_card_uses_a_retrievers_hits_and_usage_order(self):
        class Stub:
            stages = ("exact", "fuzzy", "semantic")

            def hits(self, text, entries):
                entry = next(e for e in entries if e["expression"] == "긁히다")
                return [{"start": 6, "end": 8, "span": "긁켜", "entry": entry, "stage": "fuzzy", "score": 86}]

            def evidence(self, group, text, limit):
                return [{"id": "U1", **group["lines"][1], "similarity": 0.9}]
        client = FixtureClient()
        client.probe = lambda p: 0.9
        result = CardAnalyzer(client, lexicon=LEX, usages=USAGES, config=V011, retriever=Stub()).run(text="쟤 방금 너 긁켜서 화남")
        self.assertEqual(result["detection"]["retriever"], ["exact", "fuzzy", "semantic"])
        self.assertEqual(result["detection"]["db_hits"][0]["stage"], "fuzzy")
        item = result["card"]["items"][0]
        self.assertEqual((item["expression"], item["headword"], item["related_usage"]["text"]),
                         ("긁켜", "긁히다", "시험 망해서 긁힘"))


class PreparedCardTests(unittest.TestCase):
    def test_a_prepared_card_is_served_at_once_and_labeled_never_as_live(self):
        import json
        import tempfile
        import threading
        import time
        import urllib.request
        from pathlib import Path
        from tracetalk.web.server import load_prepared, make_server
        client = FixtureClient()
        client.probe = lambda p: 0.9
        result = CardAnalyzer(client, lexicon=LEX, config=V011).run(text="쟤 방금 긁힌거 같은데?")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mac_demo.jsonl"
            path.write_text(json.dumps({"case_id": "d1", "method": "card", "result": result}, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            prepared = load_prepared([path])
            self.assertEqual(list(prepared), [("card", "쟤 방금 긁힌거 같은데?")])
            server = make_server(client, port=0, output_dir=temp, lexicon=LEX)
            server.jobs.prepared = prepared
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"
            post = lambda body: json.load(urllib.request.urlopen(urllib.request.Request(
                base + "/api/analyze", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=5))
            try:
                calls = len(client.requests)
                job = post({"text": "쟤 방금 긁힌거 같은데?", "mode": "card"})["job_id"]
                for _ in range(300):
                    state = json.load(urllib.request.urlopen(base + "/api/jobs/" + job, timeout=5))
                    if state["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(len(client.requests), calls)  # no model call
                self.assertEqual(state["result"]["prepared"]["from"], "mac_demo.jsonl")
                self.assertEqual(state["events"][0]["type"], "prepared")
                # Another mode or another comment runs live.
                job = post({"text": "쟤 방금 긁힌거 같은데?", "mode": "card_single"})["job_id"]
                for _ in range(300):
                    state = json.load(urllib.request.urlopen(base + "/api/jobs/" + job, timeout=5))
                    if state["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertNotIn("prepared", state["result"])
                self.assertGreater(len(client.requests), calls)
            finally:
                server.shutdown()
                server.server_close()


@unittest.skipUnless(R.fuzz is not None, "rapidfuzz 없음")
class FuzzyTests(unittest.TestCase):
    def test_a_one_jamo_typo_of_a_three_letter_form_is_found_and_short_or_other_words_are_not(self):
        r = R.Retriever(stages=("exact", "fuzzy"))
        found = lambda text: [(h["span"], h["entry"]["expression"], h["stage"]) for h in r.hits(text, ENTRIES)]
        self.assertEqual(found("오또카찌 나 늦었어"), [("오또카찌", "오또카지", "fuzzy")])
        self.assertEqual(found("걔 완전 마가꾼이던데"), [("마가꾼", "마기꾼", "fuzzy")])
        self.assertEqual(found("오늘도 갓셍 산다"), [])  # two letters: a typo there is a different word too often
        self.assertEqual(found("어떡하지 진짜"), [])  # a standard word, not a typo of 오또카지
        self.assertEqual(found("오또카지 오또카찌"), [("오또카지", "오또카지", "exact")])  # one hit per row


@unittest.skipUnless(R.Kiwi is not None, "kiwipiepy 없음")
class MorphTests(unittest.TestCase):
    def test_an_irregular_inflection_reaches_its_headword(self):
        r = R.Retriever(stages=("exact", "morph"))
        hits = r.hits("아기 고양이 진짜 귀여워", ENTRIES)
        self.assertEqual([(h["span"], h["entry"]["expression"], h["stage"]) for h in hits], [("귀여워", "귀엽다", "morph")])


def has_chroma():
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(has_chroma(), "chromadb 없음")
class SemanticTests(unittest.TestCase):
    @staticmethod
    def embed(texts):  # TEST: a letter-count vector, so "closeness" is shared letters (not a real embedding)
        letters = sorted(set("롤지고개긁혔음시험망해서힘팀원말에발끈쟤게임화남"))
        return [[t.count(c) + 0.01 for c in letters] for t in texts]

    def test_usages_closest_to_the_comment_come_first_and_team_lines_stay_first(self):
        index = R.UsageIndex(None, self.embed, name="t" + uuid.uuid4().hex[:8])
        r = R.Retriever(stages=("exact", "semantic"), usage_index=index)
        lines = r.evidence(USAGES[0], "롤 게임 지고 긁혔다", 3)
        self.assertEqual([u["row"] for u in lines], ["live-1", "kc-1", "kc-2"])
        self.assertEqual([u["id"] for u in lines], ["U1", "U2", "U3"])
        self.assertGreater(lines[1]["similarity"], lines[2]["similarity"])
        self.assertEqual(index.collection.count(), 3)  # embedded once
        r.evidence(USAGES[0], "시험 망해서 힘들다", 3)
        self.assertEqual(index.collection.count(), 3)

    def test_a_dead_embedding_server_falls_back_to_the_plain_order(self):
        def down(texts):
            raise OSError("연결 거부(TEST)")
        r = R.Retriever(stages=("exact", "semantic"), usage_index=R.UsageIndex(None, down, name="d" + uuid.uuid4().hex[:8]))
        self.assertEqual(r.evidence(USAGES[0], "롤 지고 긁혔다", 3)[0]["row"], "live-1")


if __name__ == "__main__":
    unittest.main()
