"""0.9 (docs/DESIGN.md): a DB word is decided by one token over every rotation of the labels and, between senses, by a
reading with the word hidden; what is not clear enough says 뜻 확인 필요; a word the DB lacks gets a reading, not a debate;
detection names one part when the comment reads like slang; DB words keep their place and nothing past the cap is dropped
silently. Responses are TEST-FIXTURE-NOT-A-MODEL."""
import json
import unittest

from tracetalk.mad.card import CARD, Q_CHOOSE, Q_CONTRAST, CardAnalyzer, verdict
from frontier_fixture import V011, FixtureClient

SENSE = {"id": "live-e-1", "expression": "두쫀쿠", "variants": [], "meaning": "두바이 쫀득 쿠키", "family": "live:두쫀쿠", "source": "https://x.test/1",
         "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00", "review": "검수 전", "pos": "명사", "origin": "두+쫀+쿠"}
SECOND = {**SENSE, "id": "live-e-2", "meaning": "두꺼운 쫀득 쿠키"}
REVIEWED = {**SENSE, "id": "live-e-3", "review": "검수됨"}
TEXT = "편의점에 두쫀쿠 들어왔대"


def shares(by_meaning):
    """A judge that answers by the option's text, wherever the rotation put it."""
    def pick(payload, labels):
        probs = {n: next((p for key, p in by_meaning.items() if key in payload["options"][n]), 0.0) for n in labels}
        total = sum(probs.values()) or 1.0
        return {n: p / total for n, p in probs.items()}
    return pick


def card(lexicon, pick=None, retriever=None, **config):
    client = FixtureClient()
    if pick:
        client.pick = pick
    return client, CardAnalyzer(client, lexicon=lexicon, usages=[], config={**V011, **config}, retriever=retriever)


class VerdictTests(unittest.TestCase):
    def test_outcomes(self):
        reviews = {"C1": "검수 전", "C2": "검수됨"}
        self.assertEqual(verdict({"C1": 0.95, "L": 0.03, "N": 0.02}, ["C1"], None, reviews, CARD), ("sense", "C1"))
        self.assertEqual(verdict({"C1": 0.7, "L": 0.2, "N": 0.1}, ["C1"], None, reviews, CARD), ("check", "C1"))
        self.assertEqual(verdict({"C1": 0.2, "L": 0.7, "N": 0.1}, ["C1"], None, reviews, CARD), ("literal", "L"))
        self.assertEqual(verdict({"C1": 0.31, "L": 0.49, "N": 0.2}, ["C1"], None, reviews, CARD), ("check", "C1"))  # v13: a weak lead is checked
        self.assertEqual(verdict({"C1": 0.31, "L": 0.49, "N": 0.2}, ["C1"], None, reviews, {**CARD, "tau_literal": 0}), ("literal", "L"))  # 0.9
        self.assertEqual(verdict({"C1": 0.2, "L": 0.1, "N": 0.7}, ["C1"], None, reviews, CARD), ("other", "N"))
        self.assertEqual(verdict({}, ["C1"], None, reviews, CARD), ("check", "C1"))

    def test_a_reviewed_sense_needs_only_to_lead_and_the_reading_picks_between_senses(self):
        reviews = {"C1": "검수 전", "C2": "검수됨"}
        self.assertEqual(verdict({"C2": 0.7, "L": 0.15, "N": 0.15}, ["C2"], None, reviews, CARD), ("sense", "C2"))
        scores = {"C1": 0.5, "C2": 0.3, "L": 0.1, "N": 0.1}  # the senses together 0.8
        self.assertEqual(verdict(scores, ["C1", "C2"], None, reviews, CARD), ("check", "C1"))  # larger share, unreviewed
        self.assertEqual(verdict(scores, ["C1", "C2"], "C2", reviews, CARD), ("sense", "C2"))  # the reading's sense, reviewed


    def test_a_real_share_for_the_standard_reading_is_not_settled_even_for_a_reviewed_sense(self):
        reviews = {"C1": "검수됨"}
        self.assertEqual(verdict({"C1": 0.7, "L": 0.25, "N": 0.05}, ["C1"], None, reviews, CARD), ("check", "C1"))
        self.assertEqual(verdict({"C1": 0.7, "L": 0.15, "N": 0.15}, ["C1"], None, reviews, CARD), ("sense", "C1"))
        self.assertEqual(verdict({"R1": 0.6, "L": 0.3, "N": 0.1}, [], None, {}, CARD, "R1"), ("check", "R1"))

    def test_a_reading_that_differs_from_the_row_is_weighed_against_it(self):
        reviews = {"C1": "검수 전"}
        self.assertEqual(verdict({"C1": 0.05, "R1": 0.9, "L": 0.03, "N": 0.02}, ["C1"], None, reviews, CARD, "R1"), ("sense", "R1"))
        self.assertEqual(verdict({"C1": 0.8, "R1": 0.12, "L": 0.05, "N": 0.03}, ["C1"], None, reviews, CARD, "R1"), ("check", "C1"))
        self.assertEqual(verdict({"C1": 0.95, "L": 0.03, "N": 0.02}, ["C1"], None, reviews, CARD, None, True), ("sense", "C1"))
        self.assertEqual(verdict({"C1": 0.7, "L": 0.15, "N": 0.15}, ["C1"], None, reviews, CARD, None, True), ("sense", "C1"))


class WitnessTests(unittest.TestCase):
    def test_every_rotation_is_asked_so_no_option_holds_a_place(self):
        client, a = card([SENSE], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        result = a.run(text=TEXT, mode="card")
        asked = [(c, json.loads(c["messages"][1]["content"])) for c in result["calls"] if c["stage"] == "choose"]
        chooses = [c for c, q in asked if q["question"] == Q_CHOOSE]
        self.assertEqual(len(chooses), 3)  # the sense, standard, another meaning
        firsts = {json.loads(c["messages"][1]["content"])["options"]["1"] for c in chooses}
        self.assertEqual(len(firsts), 3)
        # v15 반대 근거: the chosen sense against the words as they are, both orders
        contrast = [q for c, q in asked if q["question"] == Q_CONTRAST]
        self.assertEqual(len(contrast), 2)
        self.assertEqual({q["options"]["1"].split(":")[0] for q in contrast}, {"밈·신조어로 쓴 뜻", "글자 그대로의 뜻"})
        item = result["card"]["items"][0]
        self.assertEqual(item["decided_by"], "witness")
        self.assertEqual((item["status"], item["choice"], item["check_needed"]), ("proposed", "C1", False))
        self.assertAlmostEqual(item["detail"]["scores"]["C1"], 0.95, places=2)
        self.assertEqual(item["candidates"][0]["p_yes"], item["detail"]["scores"]["C1"])
        for stage in ("propose", "review", "judge"):  # not the five-call debate
            self.assertFalse([c for c in result["calls"] if c["stage"] == stage])

    def test_a_share_too_small_for_an_unreviewed_sense_says_check_and_stays_out_of_the_sentence(self):
        client, a = card([SENSE], shares({"두바이": 0.7, "표준어": 0.15, "맞지 않고": 0.15}))
        result = a.run(text=TEXT, mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"], item["choice"]), ("uncertain", True, "C1"))
        self.assertEqual(item["db_meaning"], "두바이 쫀득 쿠키")
        self.assertIn("뜻 확인이 필요합니다", item["uncertainty"])
        self.assertNotIn("single", [c["stage"] for c in result["calls"]])  # no meaning is written for it
        self.assertIsNone(result["card"]["sentence"])

    def test_the_same_share_is_enough_for_a_reviewed_sense(self):
        client, a = card([REVIEWED], shares({"두바이": 0.7, "표준어": 0.15, "맞지 않고": 0.15}))
        item = a.run(text=TEXT, mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"], item["db_review"]), ("proposed", False, "검수됨"))

    def test_another_meaning_leading_shows_no_guess_and_keeps_the_db_sense_visible(self):
        client, a = card([SENSE], shares({"두바이": 0.1, "표준어": 0.1, "맞지 않고": 0.8}))
        result = a.run(text=TEXT, mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["choice"], item["status"], item["check_needed"], item["db_meaning"], item["meaning"]), ("N", "uncertain", True, None, ""))
        self.assertTrue(any("두바이" in x for x in item["alternatives"]))
        self.assertIn("뜻 확인이 필요합니다", item["uncertainty"])
        self.assertFalse([c for c in result["calls"] if c["stage"] == "read"])  # from the comment alone it would be a guess

    def test_the_standard_reading_of_a_word_nobody_flagged_leaves_the_card(self):
        client, a = card([SENSE], shares({"두바이": 0.05, "표준어": 0.9, "맞지 않고": 0.05}))
        result = a.run(text=TEXT, mode="card")
        self.assertEqual(result["card"]["items"], [])
        self.assertEqual(result["detection"]["ordinary_words"], ["두쫀쿠"])

    def test_the_reading_with_the_word_hidden_picks_between_senses(self):
        class Index:
            def embed(self, texts):  # the situation is close to the second sense
                return [[1.0, 0.0] if ("상황" in t or "두꺼운" in t) else [0.0, 1.0] for t in texts]

        class Near:
            usage_index = Index()
            stages = ("exact",)

            def hits(self, text, entries):
                from tracetalk.mad.card import find
                return find(text, entries)

            def evidence(self, group, text, limit):
                return []
        client, a = card([SENSE, {**SECOND, "review": "검수됨"}], shares({"두바이": 0.6, "두꺼운": 0.35, "표준어": 0.03, "맞지 않고": 0.02}), retriever=Near())
        item = a.run(text=TEXT, mode="card")["card"]["items"][0]
        self.assertEqual(item["choice"], "C2")
        self.assertEqual(item["detail"]["closeness"]["C2"], 1.0)
        self.assertEqual(item["detail"]["reading"]["situation"], "테스트용 상황")

    def test_a_settled_sense_shows_the_evidences_own_words_and_nothing_is_written_over_them(self):
        client, a = card([SENSE], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        result = a.run(text=TEXT, mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"], item["meaning"]), ("proposed", False, SENSE["meaning"]))
        self.assertFalse([c for c in result["calls"] if c["stage"] == "single"])
        self.assertEqual(item["easy"], "고친 쉬운 말")  # asked for the easy words alone, for this meaning
        asked = json.loads([c for c in result["calls"] if c["stage"] == "easy"][0]["messages"][1]["content"])
        self.assertEqual(asked["unverified_hypotheses"]["meaning"], SENSE["meaning"])

    def test_the_model_rejecting_a_row_nobody_reviewed_keeps_it_unsettled_and_its_words_are_only_an_alternative(self):
        client, a = card([SENSE], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        client.object_to = "수고 많으셨습니다"
        item = a.run(text=TEXT, mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"], item["meaning"]), ("uncertain", True, SENSE["meaning"]))
        self.assertIn("수고 많으셨습니다", item["alternatives"][0])
        self.assertEqual(item["detail"]["objection"], "수고 많으셨습니다")

    def test_a_reviewed_row_is_not_asked_about(self):
        client, a = card([REVIEWED], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        client.object_to = "수고 많으셨습니다"
        result = a.run(text=TEXT, mode="card")
        self.assertEqual(result["card"]["items"][0]["status"], "proposed")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "object"])

    def test_the_card_shows_where_the_sense_comes_from(self):
        client, a = card([SENSE], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        item = a.run(text=TEXT, mode="card")["card"]["items"][0]
        self.assertEqual((item["db_source"], item["db_review"], item["db_added_at"]), ("https://x.test/1", "검수 전", SENSE["added_at"]))


class UnknownTests(unittest.TestCase):
    def test_a_word_with_nothing_behind_it_gets_one_probe_and_the_card_says_it_does_not_know(self):
        client, a = card([])
        client.pick_span = "엠비스찬"
        client.probe = lambda payload: 0.9
        result = a.run(text="걔는 엠비스찬이야", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["estimate"], item["status"], item["meaning"]), ("read", "model", True, "uncertain", ""))
        self.assertIn("수집 목록", item["uncertainty"])
        self.assertFalse([c for c in result["calls"] if c["stage"] in ("propose", "review", "judge", "read", "single")])
        self.assertEqual(result["card"]["kept_estimates"], [])

    def test_a_probe_that_says_it_is_no_slang_drops_it(self):
        client, a = card([])
        client.pick_span = "위고비"
        client.probe = lambda payload: 0.95 if payload["probe"] == "has_slang" else 0.04
        result = a.run(text="병원에서 위고비 주사를 처방받았다", mode="card")
        self.assertEqual(result["card"]["items"], [])
        self.assertEqual(result["detection"]["ordinary_words"], ["위고비"])


POST = {"url": "https://maily.so/trendaword/posts/x", "date": "2026-10-22", "blocks": [
    {"kind": "h", "text": "26.10.22 (목) '회크닉'"}, {"kind": "p", "text": "회와 피크닉을 합친 말로, 수산시장에서 포장한 회를 야외에서 즐기는 것을 뜻한다."},
    {"kind": "p", "text": "“나 왜 이 순간이 영원할 거 같지”라는 대사도 유행이다."}]}
RCARD = {"id": "live-e-5", "expression": "회크닉", "variants": [], "meaning": "회사 사람들과 가는 소풍", "family": "live:회크닉", "source": "크롤러",
         "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00", "review": "검수 전"}


class Same:
    """The embedding model: texts naming the same key are close."""
    def __init__(self, *groups):
        self.groups = groups

    def embed(self, texts):
        return [[1.0 if any(k in t for k in g) else 0.0 for g in self.groups] + [0.001] for t in texts]


def retriever(index):
    class Near:
        usage_index = index
        stages = ("exact",)

        def hits(self, text, entries):
            from tracetalk.mad.card import find
            return find(text, entries)

        def evidence(self, group, text, limit):
            return []
    return Near()


class PostTests(unittest.TestCase):
    def setUp(self):
        from tracetalk.evidence.corpus import Corpus
        self.corpus = Corpus([POST])

    def analyzer(self, lexicon, pick, reading, index=None, **config):
        client = FixtureClient()
        client.pick = pick
        client.post_meaning = reading
        client.probe = lambda payload: 0.9
        return client, CardAnalyzer(client, lexicon=lexicon, usages=[], config={**V011, **config}, retriever=retriever(index) if index else None, corpus=self.corpus)

    def test_a_word_the_db_lacks_is_read_from_the_posts_and_can_go_in_the_sentence(self):
        client, a = self.analyzer([], shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), "회와 피크닉을 합친 말")
        client.pick_span = "회크닉"
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["basis"], item["choice"], item["status"], item["estimate"], item["decided_by"]), ("post", "R1", "proposed", False, "witness"))
        self.assertEqual(item["post_meaning"], "회와 피크닉을 합친 말")
        self.assertEqual(item["posts"][0]["url"], POST["url"])
        self.assertIn("수산시장", item["posts"][0]["text"])
        self.assertTrue(result["card"]["sentence"])
        asked = json.loads([c for c in result["calls"] if c["stage"] == "post"][0]["messages"][1]["content"])
        self.assertIn("수산시장", asked["passages"][0])
        self.assertNotIn("original_text", asked)  # the reading of the posts does not see the comment
        self.assertEqual((item["post_how"], item["post_quote"]), ("summary", ""))  # v13: the post states no gloss in a fixed form here

    def test_the_09_reading_sums_up_the_passages(self):
        client, a = self.analyzer([], shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), "회와 피크닉을 합친 말", post_read="summary")
        client.pick_span = "회크닉"
        result = a.run(text="오늘 회크닉 가자", mode="card")
        asked = json.loads([c for c in result["calls"] if c["stage"] == "post"][0]["messages"][1]["content"])
        self.assertIn("수산시장", asked["passages"][0])
        self.assertEqual(result["card"]["items"][0]["post_how"], "summary")

    def test_v13_a_gloss_the_post_states_is_the_meaning_and_its_sentence_goes_with_it(self):
        from tracetalk.evidence.corpus import Corpus
        post = {"url": "https://maily.so/trendaword/posts/y", "date": "2026-10-22", "blocks": [
            {"kind": "h", "text": "26.10.22 (목) '치올'"}, {"kind": "p", "text": "DTD, 치올(치고 올라간다), 야푸 같은 줄임말이 계속 생겨나고 있다."}]}
        client, a = self.analyzer([], shares({"치고": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), "팀의 승리")
        a.corpus = Corpus([post])
        client.pick_span = "치올"
        item = a.run(text="오늘부터 우리 팀 치올이다", mode="card")["card"]["items"][0]
        self.assertEqual((item["meaning"], item["post_how"]), ("'치고 올라간다'의 줄임말", "stated"))
        self.assertIn("치올(치고 올라간다)", item["post_quote"])

    def test_v13_posts_that_gloss_a_longer_word_are_not_read_for_this_one(self):
        from tracetalk.evidence.corpus import Corpus
        post = {"url": "https://maily.so/trendaword/posts/z", "date": "2026-10-22", "blocks": [
            {"kind": "h", "text": "요즘 뜨는 말"}, {"kind": "p", "text": "2️⃣ 손절미: 손절하고 싶어지는 특징 매번 지각을 하는 사람한테 쓰면 되는 용어야."}]}
        client, a = self.analyzer([], shares({"특징": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), "손절하고 싶어지는 특징")
        a.corpus = Corpus([post])
        client.pick_span = "손절"
        result = a.run(text="걔랑은 이제 손절이다", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "post"])

    def test_the_card_says_where_the_word_comes_from_as_the_posts_say(self):
        client, a = self.analyzer([], shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), "회와 피크닉을 합친 말")
        client.pick_span = "회크닉"
        client.post_origin = "수산시장 포장 회 유행"
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["origin"], item["origin_from"]), ("수산시장 포장 회 유행", "posts"))
        row = {**RCARD, "meaning": "회와 피크닉을 합친 말", "origin": "DB가 아는 유래"}  # the row's own origin comes first
        client, a = self.analyzer([row], shares({"피크닉": 0.95, "표준어": 0.03, "맞지 않고": 0.02}), "회를 야외에서 먹는 피크닉", Same(("피크닉",)))
        client.post_origin = "글의 유래"
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["origin"], item["origin_from"]), ("DB가 아는 유래", "db"))

    def test_a_post_that_does_not_explain_the_word_is_not_a_meaning(self):
        client, a = self.analyzer([], shares({"표준어": 0.5, "맞지 않고": 0.5}), "없음")
        client.pick_span = "회크닉"
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"]), ("read", "model"))

    def test_the_posts_correct_an_unreviewed_row_that_says_something_else(self):
        index = Same(("회사",), ("피크닉",))
        client, a = self.analyzer([RCARD], shares({"피크닉": 0.9, "회사": 0.06, "표준어": 0.02, "맞지 않고": 0.02}), "회와 피크닉을 합친 말", index)
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["choice"], item["basis"], item["db_meaning"], item["status"]), ("R1", "post", None, "proposed"))
        self.assertEqual(item["detail"]["scores"]["R1"], 0.9)
        self.assertEqual(item["candidates"][0]["meaning"], RCARD["meaning"])  # the row stays visible on the card

    def test_posts_that_agree_with_a_row_let_it_stand_on_a_smaller_share(self):
        row = {**RCARD, "meaning": "회와 피크닉을 합친 말"}
        index = Same(("피크닉",))
        scores = shares({"피크닉": 0.7, "표준어": 0.15, "맞지 않고": 0.15})
        client, a = self.analyzer([row], scores, "회를 야외에서 먹는 피크닉", index)
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["choice"], item["status"], item["detail"]["supported"]), ("C1", "proposed", True))
        self.assertEqual(item["db_review"], "검수 전")
        self.assertEqual(item["post_meaning"], "회를 야외에서 먹는 피크닉")
        client, a = card([row], scores)  # no posts: the same share is not enough for a row nobody reviewed
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"]), ("uncertain", True))

    def test_a_reviewed_row_is_not_sent_to_the_posts(self):
        client, a = self.analyzer([{**RCARD, "review": "검수됨"}], shares({"회사": 0.9, "표준어": 0.05, "맞지 않고": 0.05}), "회와 피크닉을 합친 말")
        result = a.run(text="오늘 회크닉 가자", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "post"])

    def test_a_phrase_the_posts_quote_is_found_and_read_whole(self):
        client, a = self.analyzer([], shares({"끝나지": 0.9, "표준어": 0.05, "맞지 않고": 0.05}), "끝나지 않을 것 같은 괴로운 순간을 비틀어 쓰는 말")
        client.pick_span = "영원할"
        result = a.run(text="회의가 세 시간째인데 나 왜 이 순간이 영원할 거 같지", mode="card")
        self.assertEqual(result["detection"]["quoted_in_posts"], ["나 왜 이 순간이 영원할 거 같지"])
        self.assertEqual([i["expression"] for i in result["card"]["items"]], ["나 왜 이 순간이 영원할 거 같지"])

    def test_the_one_call_comparison_gets_the_same_posts_at_once(self):
        client, a = self.analyzer([], shares({}), "없음")
        client.pick_span = "회크닉"
        result = a.run(text="오늘 회크닉 가자", mode="card_single")
        asked = json.loads([c for c in result["calls"] if c["stage"] == "single"][0]["messages"][1]["content"])
        self.assertIn("수산시장", asked["unverified_hypotheses"]["source_passages"][0])
        self.assertIn("source_passages", asked["role"])
        item = result["card"]["items"][0]
        self.assertEqual((item["basis"], item["estimate"]), ("post", False))  # a wrong reading counts against it as against the witnesses
        self.assertEqual(item["posts"][0]["url"], POST["url"])
        self.assertFalse([c for c in result["calls"] if c["stage"] in ("choose", "post")])

    def test_stored_comments_are_read_when_there_is_no_sense_and_no_post(self):
        group = {"id": "col-1", "expression": "중도런", "variants": [], "lines": [
            {"text": "중도런 하다가 자리 잡았다", "context": "", "row": "col-1", "source": "수집기(카드 입력)", "license": "로컬 수집", "note": "검수 전", "added_at": ""},
            {"text": "오늘도 중도런 성공", "context": "", "row": "col-1", "source": "수집기(카드 입력)", "license": "로컬 수집", "note": "검수 전", "added_at": ""}]}
        client = FixtureClient()
        client.pick = shares({"도서관": 0.95, "표준어": 0.03, "맞지 않고": 0.02})
        client.post_meaning = "도서관 자리를 잡으려고 달려가는 것"
        client.probe = lambda payload: 0.9
        a = CardAnalyzer(client, lexicon=[], usages=[group], config=V011, corpus=self.corpus)
        result = a.run(text="내일 시험이라 중도런 뛴다", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["basis"], item["estimate"], item["choice"], item["status"]), ("usage", True, "R1", "proposed"))
        asked = json.loads([c for c in result["calls"] if c["role"] == "read_usages"][0]["messages"][1]["content"])
        self.assertEqual(len(asked["sentences"]), 3)


class DetectionTests(unittest.TestCase):
    def test_a_comment_that_reads_like_slang_names_one_part_when_the_list_is_empty(self):
        client, a = card([])
        client.probe = lambda payload: 0.96
        client.pick_span = "볼꾸"
        result = a.run(text="요즘 볼꾸에 빠져서 볼펜만 샀어", mode="card")
        self.assertEqual(result["detection"]["model_spans"], ["볼꾸"])
        self.assertEqual(result["card"]["items"][0]["expression"], "볼꾸")

    def test_a_plain_comment_is_not_asked_to_pick(self):
        client, a = card([])
        client.probe = lambda payload: 0.01
        result = a.run(text="점심으로 김치볶음밥을 먹었다", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "pick"])
        self.assertTrue(result["card"]["plain"])
        self.assertFalse(result["card"]["maybe_slang"])

    def test_a_pick_of_the_whole_comment_is_no_span_and_the_card_says_it_may_be_a_meme(self):
        client, a = card([])
        client.probe = lambda payload: 0.92
        client.pick_span = "볼펜 잉크가 다 떨어졌다"
        result = a.run(text="볼펜 잉크가 다 떨어졌다", mode="card")
        self.assertEqual(result["card"]["items"], [])
        self.assertTrue(result["card"]["maybe_slang"])

    def test_the_analyzers_whole_word_replaces_a_piece_the_model_cut(self):
        class Oov:
            stages = ("exact", "morph")

            def hits(self, text, entries):
                return []

            def evidence(self, group, text, limit):
                return []

            def unknown_words(self, text):
                at = text.find("골든이여라")
                return [{"start": at, "end": at + 5, "span": "골든이여라"}]
        client, a = card([], retriever=Oov())
        client.pick_span = "골든"
        client.probe = lambda payload: 0.9
        result = a.run(text="월급 들어왔다 골든이여라~", mode="card")
        self.assertEqual([i["expression"] for i in result["card"]["items"]], ["골든이여라"])

    def test_db_words_come_first_and_past_the_cap_nothing_is_dropped_silently(self):
        class Oov:
            stages = ("exact",)

            def hits(self, text, entries):
                from tracetalk.mad.card import find
                return find(text, entries)

            def evidence(self, group, text, limit):
                return []

            def unknown_words(self, text):
                return [{"start": text.find(w), "end": text.find(w) + len(w), "span": w} for w in ("팀플", "조원", "잠수")]
        hak = {**SENSE, "id": "live-e-9", "expression": "학씨", "family": "live:학씨", "meaning": "짜증 날 때 내뱉는 말"}
        client, a = card([hak], shares({"짜증": 0.95, "표준어": 0.03, "맞지 않고": 0.02}), retriever=Oov())
        client.probe = lambda payload: 0.9
        result = a.run(text="팀플 조원이 또 잠수 탔다 학씨", mode="card")
        self.assertEqual([i["expression"] for i in result["card"]["items"]], ["학씨"])
        self.assertEqual(set(result["card"]["unexplained"]), {"팀플", "조원"})  # no result of their own, but said and collected
        self.assertEqual(result["card"]["skipped"], ["잠수"])
        self.assertFalse(result["card"]["plain"])
        from tracetalk.db.usage import candidate_rows
        self.assertEqual({r["expression"] for r in candidate_rows(result)}, {"팀플", "조원"})

    def test_with_a_db_word_in_the_comment_there_is_no_probe_and_no_list_call(self):
        client, a = card([SENSE], shares({"두바이": 0.95, "표준어": 0.03, "맞지 않고": 0.02}))
        result = a.run(text=TEXT, mode="card")
        stages = {c["stage"] for c in result["calls"]}
        self.assertFalse(stages & {"detect", "pick"})
        self.assertFalse([c for c in result["calls"] if c.get("role") == "has_slang"])
        self.assertIsNone(result["detection"]["p_has_slang"])


class SecondModelTests(unittest.TestCase):
    """0.9, different models: a second reader of the same posts, a tie-break only towards the standard reading."""

    def analyzer(self, reading, other_reading, pick, other_pick, lexicon=(), index=None):
        from tracetalk.evidence.corpus import Corpus
        client, second = FixtureClient(), FixtureClient()
        second.config = type(second.config)(model="OTHER-FIXTURE")
        client.pick, second.pick = pick, other_pick
        client.post_meaning, second.post_meaning = reading, other_reading
        client.probe = lambda payload: 0.9
        client.pick_span = "회크닉"
        return client, second, CardAnalyzer(client, lexicon=list(lexicon), usages=[], config=V011, corpus=Corpus([POST]), retriever=retriever(index or Same(("피크닉",), ("회사",))), second=second)

    def test_the_second_model_reads_the_same_posts_without_seeing_the_first_reading(self):
        client, second, a = self.analyzer("첫째 모델이 쓴 피크닉 뜻", "회를 야외에서 먹는 피크닉", shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), shares({}))
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["status"], item["meaning"], item["alternatives"]), ("proposed", "첫째 모델이 쓴 피크닉 뜻", []))
        self.assertEqual(item["detail"]["second_reading"]["model"], "OTHER-FIXTURE")
        reader = [c for c in result["calls"] if c.get("model") == "OTHER-FIXTURE" and c["stage"] == "post"][0]
        self.assertNotIn("첫째 모델이 쓴", reader["messages"][1]["content"])
        self.assertFalse(second.requests[0].get("original_text"))  # nor the comment

    def test_two_readings_that_differ_are_both_on_the_card_and_the_status_stays(self):
        client, second, a = self.analyzer("회와 피크닉을 합친 말", "회사 사람들과 가는 소풍", shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), shares({}))
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual(item["status"], "proposed")
        self.assertIn("회사 사람들과 가는 소풍", item["alternatives"][0])
        self.assertLess(item["detail"]["second_reading"]["closeness"], CARD["tau_agree"])

    def test_when_the_4b_is_unsure_the_second_model_may_only_turn_it_to_the_standard_reading(self):
        unsure = shares({"피크닉": 0.6, "표준어": 0.3, "맞지 않고": 0.1})
        client, second, a = self.analyzer("회와 피크닉을 합친 말", "회와 피크닉을 합친 말", unsure, shares({"피크닉": 0.1, "표준어": 0.8, "맞지 않고": 0.1}))
        result = a.run(text="오늘 회크닉 가자", mode="card")
        self.assertEqual(result["card"]["items"], [])  # read literally: an ordinary word
        self.assertEqual(result["detection"]["ordinary_words"], ["회크닉"])
        client, second, a = self.analyzer("회와 피크닉을 합친 말", "회와 피크닉을 합친 말", unsure, shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}))
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["status"], item["check_needed"]), ("uncertain", True))  # its yes does not settle it
        self.assertAlmostEqual(item["detail"]["second_scores"]["R1"], 0.97, places=2)

    def test_a_sure_4b_is_not_asked_again(self):
        client, second, a = self.analyzer("회와 피크닉을 합친 말", "회와 피크닉을 합친 말", shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), shares({"표준어": 1.0}))
        result = a.run(text="오늘 회크닉 가자", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "choose" and c.get("model")])
        self.assertEqual(result["card"]["items"][0]["status"], "proposed")

    def test_the_second_origin_is_used_only_when_the_first_gave_none_and_the_posts_say_it(self):
        from tracetalk.mad.card import grounded
        passages = ["회와 피크닉을 합친 말로, 수산시장에서 포장한 회를 야외에서 즐기는 것을 뜻한다."]
        self.assertTrue(grounded("수산시장에서 포장한 회", passages))
        self.assertFalse(grounded("현대 디지털 밈 문화", passages))
        self.assertFalse(grounded("'라이브러리' 수산시장 포장한 회", passages))
        client, second, a = self.analyzer("회와 피크닉을 합친 말", "회를 야외에서 먹는 피크닉", shares({"피크닉": 0.97, "표준어": 0.02, "맞지 않고": 0.01}), shares({}))
        second.post_origin = "수산시장에서 포장한 회"
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual((item["origin"], item["origin_by"]), ("수산시장에서 포장한 회", "OTHER-FIXTURE"))

    def test_without_a_second_model_nothing_changes(self):
        client, a = card([SENSE], shares({"두바이": 0.7, "표준어": 0.15, "맞지 않고": 0.15}))
        item = a.run(text=TEXT, mode="card")["card"]["items"][0]
        self.assertNotIn("second_reading", item["detail"])
        self.assertNotIn("second_scores", item["detail"])


class GatesTests(unittest.TestCase):
    def analyzer(self, posts, pick, reading, lexicon=(), origin=""):
        from tracetalk.evidence.corpus import Corpus
        client = FixtureClient()
        client.pick = pick
        client.post_meaning = reading
        client.post_origin = origin
        client.probe = lambda payload: 0.9
        return client, CardAnalyzer(client, lexicon=list(lexicon), usages=[], config=V011, corpus=Corpus(posts))

    def test_a_post_that_only_names_the_word_is_not_read(self):
        post = {"url": "https://maily.so/x", "date": "", "blocks": [{"kind": "p", "text": "1~3번 보기의 야르송, 봉구가 아닌 늑구, 게임 이름인 카멜레온 레터를 각각 확인해 보세요! 다음 호에서 만나요."}]}
        client, a = self.analyzer([post], shares({"표준어": 0.5, "맞지 않고": 0.5}), "개구리")
        client.pick_span = "늑구"
        result = a.run(text="늑구 어디 갔어", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "post"])
        self.assertEqual(result["card"]["items"][0]["decided_by"], "read")

    def test_a_name_the_posts_do_not_have_is_not_shown_as_the_origin(self):
        from tracetalk.mad.card import faithful
        passages = ["‘나니가스키’는 애니메이션 ＜러브라이브＞의 유닛 ‘AiScReam’이 부른 데뷔곡에서 시작된 밈이에요."]
        self.assertFalse(faithful("애니메이션 '라이브러리'의 유닛", passages))
        self.assertFalse(faithful("이찬혁 노래 NEON", passages))
        self.assertTrue(faithful("애니메이션 <러브라이브>의 유닛 'AiScReam'의 데뷔곡", passages))
        self.assertTrue(faithful("데뷔곡에서 시작된 밈", passages))
        post = {"url": "https://maily.so/x", "date": "", "blocks": [{"kind": "h", "text": "나니가스키"}, {"kind": "p", "text": passages[0]}]}
        client, a = self.analyzer([post], shares({"좋아": 0.9, "표준어": 0.05, "맞지 않고": 0.05}), "뭘 좋아하냐고 묻는 말", origin="애니메이션 '라이브러리'의 유닛")
        client.pick_span = "나니가스키"
        item = a.run(text="나니가스키? 초코보다 너가 더 좋아", mode="card")["card"]["items"][0]
        self.assertEqual((item["basis"], item["origin"], item["origin_from"]), ("post", "", ""))

    def test_posts_that_explain_the_neighbouring_db_word_are_not_read_for_a_piece_of_its_phrase(self):
        row = {**SENSE, "id": "live-e-8", "expression": "파워냉방", "family": "live:파워냉방", "meaning": "에어컨을 세게 틀라고 호통치는 말", "review": "검수됨"}
        post = {"url": "https://maily.so/x", "date": "", "blocks": [{"kind": "h", "text": "잔말 말고 파워냉방"}, {"kind": "p", "text": "개그맨 김용명이 '잔말 말고 파워냉방으로 틀어'라고 외치는 장면에서 나온 말이에요. 더위에 지친 사람들에게 인기입니다."}]}

        class Oov:
            stages = ("exact",)

            def hits(self, text, entries):
                from tracetalk.mad.card import find
                return find(text, entries)

            def evidence(self, group, text, limit):
                return []

            def unknown_words(self, text):
                return [{"start": text.find("잔말"), "end": text.find("잔말") + 2, "span": "잔말"}]
        client, a = self.analyzer([post], shares({"호통": 0.95, "표준어": 0.03, "맞지 않고": 0.02}), "더운 날 시원하게 틀라는 말", [row])
        a.retriever = Oov()
        result = a.run(text="35도야 잔말 말고 파워냉방", mode="card")
        self.assertEqual([(i["expression"], i["choice"]) for i in result["card"]["items"]], [("파워냉방", "C1")])
        self.assertEqual(result["card"]["unexplained"], ["잔말"])
        self.assertEqual(len([c for c in result["calls"] if c["stage"] == "post"]), 0)

    def test_a_doubled_word_in_the_sentence_is_a_problem_but_not_one_the_comment_has(self):
        from tracetalk.mad.card import doubled
        self.assertEqual(doubled("체육도 꼴찌 나 완전 완전 무지한 사람임임"), {"완전", "임"})
        self.assertEqual(doubled("35도 에어컨 에어컨 세게 틀어"), {"에어컨"})
        self.assertEqual(doubled("매끈매끈한 컵 진짜 진짜"), {"진짜"})
        self.assertEqual(doubled("문이 깜빡깜빡 열렸다"), set())


if __name__ == "__main__":
    unittest.main()
