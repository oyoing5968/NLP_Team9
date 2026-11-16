"""0.8 (11-05, after fresh_v1): a DB sense nobody has reviewed goes to MAD, a word the DB lacks is judged by MAD, the
debate is kept for the card, the analyzer's unknown nouns are candidates on the Mac, and the collector turns what the
cards met into a team sheet. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.mad.card import CardAnalyzer, entries_from_request, entries_from_store, review_of
from tracetalk.db.usage import LiveStore, candidate_rows, stem
from frontier_fixture import FixtureClient
from tracetalk.mad import card as card_module

def setUpModule():  # these tests are about the 0.7-0.8 routes, still selectable (card.CARD decide="roles", unknown="mad")
    card_module.CARD.update(decide="roles", unknown="mad", pick=False)


def tearDownModule():
    card_module.CARD.update(decide="witness", unknown="read", pick=True)


KC = {"id": "lx-1", "expression": "꿀팁", "variants": [], "meaning": "알아 두면 쓸모 있는 정보", "family": "kc:꿀팁",
      "source": "KoCulture", "license": "test"}
LIVE = {"id": "live-e-1", "expression": "두쫀쿠", "variants": [], "meaning": "두바이 쫀득 쿠키", "family": "live:두쫀쿠",
        "source": "팀", "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00"}


def analyzer(lexicon, client=None, **config):
    client = client or FixtureClient()
    client.probe = lambda payload: 0.9  # every DB sense "fits": the fresh_v1 probe said yes to wrong senses too
    return client, CardAnalyzer(client, lexicon=lexicon, usages=[], config=config or None)


def stages(client):
    return [r.get("stage") for r in client.requests]


class ReviewTests(unittest.TestCase):
    def test_review_status_of_a_row(self):
        self.assertEqual(review_of(KC), "검수됨")
        self.assertEqual(review_of(LIVE), "검수 전")
        self.assertEqual(review_of({**LIVE, "review": "검수됨"}), "검수됨")
        rows = {r["expression"]: r for r in entries_from_store([KC, LIVE], [])}
        self.assertEqual((rows["꿀팁"]["senses"][0]["review"], rows["두쫀쿠"]["senses"][0]["review"]), ("검수됨", "검수 전"))
        team = entries_from_request([{"expression": "두쫀쿠", "senses": [{"meaning": "디저트", "review": "검수 전"}]},
                                     {"expression": "꿀팁", "senses": [{"meaning": "정보"}]}])
        self.assertEqual([r["senses"][0]["review"] for r in team], ["검수 전", "검수됨"])
        with self.assertRaises(ValueError):
            entries_from_request([{"expression": "두쫀쿠", "senses": [{"meaning": "디저트", "review": "아마도"}]}])


class GateTests(unittest.TestCase):
    def test_an_unreviewed_sense_goes_to_mad_even_when_the_probe_calls_it_a_fit(self):
        client, a = analyzer([LIVE])
        item = a.run(text="편의점에 두쫀쿠 들어왔대", mode="card")["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["mad_reason"], item["unreviewed"]), ("mad", "unreviewed", ["C1"]))
        self.assertEqual(item["candidates"][0]["review"], "검수 전")
        self.assertIn("judge", stages(client))
        sides = [d["side"] for d in item["detail"]["debate"]]
        self.assertEqual(sides, ["가설 1", "가설 2"])  # one_sense=check sets a side against it (tests/test_v081.py)
        self.assertEqual(item["detail"]["debate"][0]["objections"], ["테스트용 반례 없음"])

    def test_the_old_gate_a_reviewed_sense_and_the_single_mode_take_the_short_way(self):
        for lexicon, config, mode in (([LIVE], {"gate": "probe"}, "card"), ([KC], {}, "card"), ([LIVE], {}, "card_single")):
            client, a = analyzer(lexicon, **config)
            text = "편의점에 두쫀쿠 들어왔대" if lexicon == [LIVE] else "이거 완전 꿀팁이다"
            item = a.run(text=text, mode=mode)["card"]["items"][0]
            self.assertEqual((item["decided_by"], item["mad_reason"]), ("single", None), (config, mode))
            self.assertNotIn("judge", stages(client))


class UnknownWordTests(unittest.TestCase):
    def test_a_word_the_db_lacks_is_judged_by_mad_between_a_new_word_and_a_standard_word(self):
        client, a = analyzer([])
        client.detect = lambda text: ["뇽뇽"]
        item = a.run(text="뇽뇽 맛있다", mode="card")["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["mad_reason"], item["basis"], item["estimate"]),
                         ("mad", "unknown", "model", True))
        roles = [r["role"] for r in client.requests if r.get("stage") == "propose"]
        self.assertTrue(any("신조어 쪽" in r for r in roles) and any("반대 쪽" in r for r in roles))
        judge = next(r for r in client.requests if r.get("stage") == "judge")
        self.assertIn("팀 DB에 없는 표현", judge["role"])
        self.assertEqual([d["side"] for d in item["detail"]["debate"]], ["신조어 쪽", "반대 쪽"])
        self.assertEqual(item["detail"]["judge_role"], "unknown")

    def test_judged_a_standard_word_it_leaves_the_card(self):
        client, a = analyzer([])
        client.detect = lambda text: ["이쑤시개"]
        client.hook = lambda payload, data: data.update(choice="L") if payload.get("stage") == "judge" else None
        result = a.run(text="이쑤시개 좀 갖다 줄래?", mode="card")
        self.assertTrue(result["card"]["plain"])
        self.assertEqual(result["detection"]["ordinary_words"], ["이쑤시개"])

    def test_one_decision_mode_and_the_old_setting_keep_the_single_guess(self):
        for mode, config in (("card_single", {}), ("card", {"unknown": "guess"})):
            client, a = analyzer([], **config)
            client.detect = lambda text: ["뇽뇽"]
            item = a.run(text="뇽뇽 맛있다", mode=mode)["card"]["items"][0]
            self.assertEqual((item["decided_by"], item["mad_reason"]), ("guess", None))
            self.assertNotIn("judge", stages(client))


class JudgeRoleTests(unittest.TestCase):
    def test_the_v10_judge_role_is_used_when_set(self):
        for judge, words in (("v9", "어느 후보도 맞지 않으면"), ("v10", "상대 시험이 깨뜨리지 못한 후보가 하나면")):
            client = FixtureClient()
            out = CardAnalyzer(client, config={"judge": judge}).pick("두쫀쿠 품절", "두쫀쿠", ["디저트", "가수"], "mad")
            self.assertEqual(out["status"], "completed")
            role = next(r["role"] for r in client.requests if r.get("stage") == "judge")
            self.assertIn(words, role)


class Unknown:
    """A stand-in retriever: exact matching only, and one noun the analyzer 'does not know'."""
    stages = ("exact",)

    def __init__(self, spans):
        self.spans = spans

    def hits(self, text, entries):
        from tracetalk.mad.card import find
        return find(text, entries)

    def evidence(self, group, text, limit):
        from tracetalk.db.usage import evidence
        return evidence(group, text, limit)

    def unknown_words(self, text):
        return [{"start": text.find(s), "end": text.find(s) + len(s), "span": s} for s in self.spans]


class AnalyzerUnknownTests(unittest.TestCase):
    def test_a_noun_the_analyzer_does_not_know_is_analyzed_when_the_model_missed_it(self):
        client = FixtureClient()
        a = CardAnalyzer(client, lexicon=[], usages=[], retriever=Unknown(["엠비스찬"]))
        result = a.run(text="걔는 엠비스찬이야", mode="card")
        self.assertEqual(result["detection"]["unknown_to_analyzer"], ["엠비스찬"])
        self.assertEqual(result["detection"]["model_spans"], [])
        self.assertEqual(result["card"]["items"][0]["expression"], "엠비스찬")
        client = FixtureClient()
        client.detect = lambda text: ["엠비스찬이야"]  # the model's span covers it: not added twice
        a = CardAnalyzer(client, lexicon=[], usages=[], retriever=Unknown(["엠비스찬"]))
        self.assertEqual(a.run(text="걔는 엠비스찬이야", mode="card")["detection"]["unknown_to_analyzer"], [])
        a = CardAnalyzer(FixtureClient(), lexicon=[], usages=[], retriever=Unknown(["엠비스찬"]), config={"oov": False})
        self.assertTrue(a.run(text="걔는 엠비스찬이야", mode="card")["card"]["plain"])


class CollectorTests(unittest.TestCase):
    def card(self, text, items, ordinary=(), at="2026-11-05T10:00:00+00:00"):
        return {"request": {"text": text}, "input_sha256": "x", "created_at": at,
                "card": {"items": items}, "detection": {"ordinary_words": list(ordinary)}}

    def item(self, expression, choice="N", status="proposed", headword=None, meaning="추정한 뜻"):
        return {"expression": expression, "headword": headword, "choice": choice, "status": status, "meaning": meaning,
                "easy": "쉬운 말", "decided_by": "mad", "mad_reason": "unknown"}

    def test_rows_from_a_card_and_the_grouped_queue(self):
        rows = candidate_rows(self.card("걔 테토남이네", [self.item("테토남이네"), self.item("꿀팁", "C1", headword="꿀팁")],
                                        ordinary=["이쑤시개"]))
        self.assertEqual([(r["expression"], r["choice"]) for r in rows], [("테토남이네", "N"), ("이쑤시개", "L")])
        rows += candidate_rows(self.card("완전 테토남이야", [self.item("테토남이야", status="uncertain", meaning="")]))
        rows += candidate_rows(self.card("밤티네", [self.item("밤티", headword="밤티")]))  # a known word, a new meaning
        rows += [r for _ in range(3) for r in candidate_rows(self.card("광고 문구 쩔템", [self.item("쩔템")]))]
        listed = {q["expression"]: q for q in update_db.queue_rows(rows, known=["꿀팁"])}
        self.assertEqual(sorted(listed), ["밤티", "쩔템", "테토남"])  # 이쑤시개: always a standard word
        self.assertEqual((listed["테토남"]["comments"], listed["테토남"]["verdicts"]), (2, {"신조어": 1, "모름": 1}))
        self.assertEqual(listed["테토남"]["meaning"], "추정한 뜻")
        self.assertTrue(listed["밤티"]["new_sense"])
        self.assertEqual(listed["쩔템"]["hints"], ["같은 문장만 되풀이됨", "하루에만 몰림"])
        self.assertEqual([stem(w) for w in ("테토남이네", "잼민이", "아우라 파밍")], ["테토남", "잼민이", "아우라파밍"])

    def test_the_store_collects_and_the_queue_sheet_imports_once_filled(self):
        with tempfile.TemporaryDirectory() as temp:
            live = Path(temp) / "live"
            store = LiveStore([], [], candidates_path=live / "candidates.jsonl")
            self.assertEqual(store.collect(self.card("걔 엠비스찬이야", [self.item("엠비스찬")])), 1)
            sheet = Path(temp) / "queue.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                update_db.main(["--live", str(live), "queue", "--lexicon", "--out", str(sheet)])
                with self.assertRaises(ValueError):  # never overwritten
                    update_db.main(["--live", str(live), "queue", "--lexicon", "--out", str(sheet)])
            with sheet.open(encoding="utf-8") as handle:
                lines = list(csv.DictReader(handle))
            self.assertEqual([(l["kind"], l["expression"]) for l in lines], [("뜻", "엠비스찬"), ("용례", "엠비스찬")])
            self.assertIn("검수 전", lines[0]["source"])
            with contextlib.redirect_stdout(io.StringIO()):
                update_db.main(["--live", str(live), "import", str(sheet), "--reviewed"])
            row = json.loads((live / "entries.jsonl").read_text(encoding="utf-8"))
            self.assertEqual((row["expression"], row["review"]), ("엠비스찬", "검수됨"))


class UpdateReviewTests(unittest.TestCase):
    def test_new_rows_are_unreviewed_unless_marked(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base = ["--live", temp, "add-entry", "--expression", "두쫀쿠", "--meaning", "두바이 쫀득 쿠키", "--source", "팀"]
            self.assertEqual(update_db.main(base)["review"], "검수 전")
            self.assertEqual(update_db.main(base + ["--reviewed"])["review"], "검수됨")


if __name__ == "__main__":
    unittest.main()
