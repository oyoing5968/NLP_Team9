"""v16 토론 (docs/DESIGN.md): the agents answer each other. E asks B for the post's own sentence; B keeps it, corrects the meaning or
gives way, and a quote counts only when it stands in the posts word for word and names the word (or its post is about that one word).
D's objection is answered by the agent whose meaning was chosen, with a cue from the comment or by giving way. Off by default.
Responses are TEST-FIXTURE-NOT-A-MODEL."""
import json
import unittest

from tracetalk.evidence.corpus import Corpus
from tracetalk.mad.card import MENTION, CardAnalyzer
from frontier_fixture import FixtureClient
from test_mad09 import POST, REVIEWED

GLOSS = "회와 피크닉을 합친 말로, 수산시장에서 포장한 회를 야외에서 즐기는 것을 뜻한다."
ROUNDUP = {"url": "https://gogumafarm.kr/x", "date": "2026-06-01", "blocks": [
    {"kind": "h", "text": "요즘 뜨는 밈 모음"},
    {"kind": "p", "text": "젠지 버전은 “귀엽다”, “우와!” 같은 짧은 반응을 썼죠. 배터리 광고의 젠지 버전은 ‘야르’라는 신조어 하나로 설명을 "
                          "축약했고요. 세대별 표현 차이가 웃음 포인트예요."}]}


def judge(yes=0.9, plain=0.02, again=None, meaning_share=0.95):
    """A judge that answers by what an option says. yes: E's share for "the sentence says so" (a function of the meaning, or a number);
    plain: D's share for the words as they are, and again: after a cue is shown."""
    def pick(payload, labels):
        def p(text):
            if text.startswith("그렇다"):
                return yes(text) if callable(yes) else yes
            if text.startswith("아니다"):
                return 1 - (yes(payload["options"][next(n for n in labels if payload["options"][n].startswith("그렇다"))])
                            if callable(yes) else yes)
            if text.startswith("글자 그대로의 뜻"):
                shown = any("댓글의 단서" in v for v in payload["options"].values())
                return again if shown and again is not None else plain
            if text.startswith("밈·신조어로 쓴 뜻"):
                shown = "댓글의 단서" in text
                return 1 - (again if shown and again is not None else plain)
            if text.startswith(("표준어", "위 보기", "사전에 있는")):
                return (1 - meaning_share) / 2
            return meaning_share
        probs = {n: p(payload["options"][n]) for n in labels}
        total = sum(probs.values()) or 1.0
        return {n: v / total for n, v in probs.items()}
    return pick


def analyzer(posts, reading, span, pick, lexicon=(), **config):
    client = FixtureClient()
    client.pick, client.post_meaning, client.pick_span = pick, reading, span
    client.probe = lambda payload: 0.9
    # the tests below were written for the v16d way (B copies the sentence); SelectDebateTests use the default, E choosing
    config = {"debate": True, "debate_mode": "quote", "mad_first": False, **config}
    return client, CardAnalyzer(client, lexicon=list(lexicon), usages=[], config=config, corpus=Corpus(posts))


def acts(item):
    return [(t["agent"], t["act"]) for t in item["detail"].get("exchange", [])]


class ReadingDebateTests(unittest.TestCase):
    def test_debate_off(self):
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge())
        a.card["debate"] = False
        result = a.run(text="오늘 회크닉 가자", mode="card")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "debate"])
        self.assertNotIn("exchange", result["card"]["items"][0]["detail"])

    def test_b_quotes_the_post_and_e_accepts(self):
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge(yes=0.9))
        client.quote_answers = [{"stance": "keep", "quote": GLOSS, "meaning": ""}]
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "accept")])
        self.assertEqual((item["basis"], item["choice"], item["meaning"]), ("post", "R1", "회와 피크닉을 합친 말"))
        self.assertEqual((item["post_quote"], item["post_how"]), (GLOSS, "debated"))
        asked = json.loads([c for c in result["calls"] if c["stage"] == "debate"][0]["messages"][1]["content"])
        self.assertNotIn("original_text", asked)  # B answers from the posts, not from the comment
        verify = [json.loads(c["messages"][1]["content"]) for c in result["calls"] if c["stage"] == "choose"
                  and json.loads(c["messages"][1]["content"])["original_text"] == GLOSS]
        self.assertEqual(len(verify), 2)  # E weighs the sentence alone, both orders

    def test_a_quote_the_posts_do_not_have_is_giving_way(self):
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge())
        client.quote_answers = [{"stance": "keep", "quote": "회크닉은 회사 사람들과 가는 소풍이다.", "meaning": ""}]
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "withdraw")])
        self.assertEqual(item["detail"]["exchange"][-1]["why"], "글에 없는 문장")
        self.assertEqual((item["basis"], item["meaning"], item["easy"], item["uncertainty"]), ("mention", "", "", MENTION))
        self.assertEqual(item["posts"][0]["url"], POST["url"])  # the posts that name it are still shown

    def test_in_a_roundup_a_sentence_without_the_word_backs_nothing(self):
        client, a = analyzer([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", judge())
        client.quote_answers = [{"stance": "keep", "quote": "젠지 버전은 “귀엽다”, “우와!” 같은 짧은 반응을 썼죠.", "meaning": ""}]
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(item["detail"]["exchange"][-1]["why"], "그 말이 나오지 않는 문장")
        self.assertEqual((item["basis"], item["meaning"], item["post_meaning"]), ("mention", "", ""))

    def test_e_objects_b_corrects_and_e_accepts_the_correction(self):
        named = "배터리 광고의 젠지 버전은 ‘야르’라는 신조어 하나로 설명을 축약했고요."
        client, a = analyzer([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", judge(yes=lambda option: 0.8 if "줄여 말한" in option else 0.1))
        client.quote_answers = [{"stance": "keep", "quote": named, "meaning": ""},
                                {"stance": "revise", "quote": named, "meaning": "긴 설명을 한 단어로 줄여 말한 젠지식 신조어"}]
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "object"), ("B", "revise"), ("E", "accept")])
        self.assertEqual((item["meaning"], item["post_quote"]), ("긴 설명을 한 단어로 줄여 말한 젠지식 신조어", named))

    def test_e_objecting_twice_or_the_same_quote_again_ends_in_giving_way(self):
        named = "배터리 광고의 젠지 버전은 ‘야르’라는 신조어 하나로 설명을 축약했고요."
        client, a = analyzer([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", judge(yes=0.1))
        client.quote_answers = [{"stance": "keep", "quote": named, "meaning": ""}, {"stance": "keep", "quote": named, "meaning": ""}]
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "object"), ("B", "withdraw")])
        self.assertEqual(item["detail"]["exchange"][-1]["why"], "같은 인용을 되풀이함")
        self.assertEqual(item["basis"], "mention")

    def test_in_a_roundup_the_lines_under_the_words_heading_speak_of_it(self):  # dev v16d: 놉놉, 사고방식을 바꾸세요 given up wrongly
        post = {"url": "https://gogumafarm.kr/y", "date": "2026-06-02", "blocks": [
            {"kind": "h", "text": "이번 주 밈 모음"}, {"kind": "h", "text": "🚨 놉놉"},
            {"kind": "p", "text": "귀여운 고양이 사진과 함께 시작된 밈입니다. 단호하게 훈계하는 듯한 태도가 포인트인데요."}]}
        client, a = analyzer([post], "단호하게 안 된다고 말하는 밈", "놉놉", judge(yes=0.9))
        client.quote_answers = [{"stance": "keep", "quote": "단호하게 훈계하는 듯한 태도가 포인트인데요.", "meaning": ""}]
        item = a.run(text="놉놉 그건 안 돼", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "accept")])

    def test_a_quote_naming_the_word_in_another_spelling_counts(self):  # dev v16d: 아.나.타, 전액 현금 매입
        post = {"url": "https://gogumafarm.kr/z", "date": "2026-06-03", "blocks": [
            {"kind": "p", "text": "요즘은 가사 ‘초코민토 요리모 아.나.타!(민트초코보다 너를 더 좋아해!)’가 고백 멘트로 쓰인다고 해요."}]}
        client, a = analyzer([post], "민트초코보다 너를 더 좋아한다는 고백", "아나타", judge(yes=0.9))
        client.quote_answers = [{"stance": "keep", "quote": "초코민토 요리모 아.나.타!(민트초코보다 너를 더 좋아해!)", "meaning": ""}]
        item = a.run(text="아나타 진짜 좋아", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "accept")])

    def test_a_quote_keeps_its_han_letters(self):  # dev: 야차 quoted '야차(野茶)는 ...' and lost it when the letters were stripped
        post = {"url": "https://maily.so/trendaword/posts/z", "date": "2026-10-23", "blocks": [
            {"kind": "h", "text": "26.10.23 (금) '야차'"}, {"kind": "p", "text": "야차(野茶)는 ‘야외에서 차를 마신다’는 뜻으로, 캠핑장에서 차를 우려 마시는 것을 말한다."}]}
        client, a = analyzer([post], "야외에서 차를 마시는 것", "야차", judge(yes=0.9))
        client.quote_answers = [{"stance": "keep", "quote": "야차(野茶)는 ‘야외에서 차를 마신다’는 뜻으로", "meaning": ""}]
        item = a.run(text="주말에 야차 어때", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "keep"), ("E", "accept")])
        self.assertIn("野茶", item["post_quote"])

    def test_a_reading_that_says_what_the_db_row_says_is_not_argued(self):
        from test_mad09 import retriever

        class Same:
            def embed(self, texts):
                return [[1.0, 0.0] for _ in texts]
        row = {"id": "live-e-9", "expression": "회크닉", "variants": [], "meaning": "회와 피크닉을 합친 말", "family": "live:회크닉",
               "source": "https://x.test/9", "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00", "review": "검수 전"}  # a reviewed row is not read against the posts at all
        client = FixtureClient()
        client.pick, client.post_meaning, client.probe = judge(), "회와 피크닉을 합친 말", (lambda payload: 0.9)
        a = CardAnalyzer(client, lexicon=[row], usages=[], config={"debate": True}, corpus=Corpus([POST]), retriever=retriever(Same()))
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual(acts(item)[:3], [("C", "read"), ("B", "claim"), ("B", "agree")])  # 0.12 default: C reads first
        self.assertFalse([c for c in result["calls"] if c["stage"] == "debate" and c["role"] == "quote"])
        self.assertEqual((item["basis"], item["choice"]), ("db", "C1"))

    def test_a_gloss_the_post_states_is_accepted_by_rule_without_a_turn(self):
        post = {"url": "https://maily.so/trendaword/posts/y", "date": "2026-10-22", "blocks": [
            {"kind": "h", "text": "26.10.22 (목) '치올'"}, {"kind": "p", "text": "DTD, 치올(치고 올라간다), 야푸 같은 줄임말이 계속 생겨나고 있다."}]}
        client, a = analyzer([post], "팀의 승리", "치올", judge())
        result = a.run(text="오늘부터 우리 팀 치올이다", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("E", "accept")])
        self.assertEqual(item["detail"]["exchange"][1]["by"], "rule")
        self.assertFalse([c for c in result["calls"] if c["stage"] == "debate"])
        self.assertEqual(item["meaning"], "'치고 올라간다'의 줄임말")


class ContrastDebateTests(unittest.TestCase):
    TEXT = "편의점에 두쫀쿠 들어왔대"

    def run_card(self, pick, cue):
        client = FixtureClient()
        client.pick, client.cue_answer = pick, cue
        a = CardAnalyzer(client, lexicon=[REVIEWED], usages=[], config={"debate": True, "mad_first": False})
        return a.run(text=self.TEXT, mode="card")

    def test_a_cue_from_the_comment_answers_d_and_d_asks_again(self):
        result = self.run_card(judge(plain=0.3, again=0.05), {"stance": "defend", "cue": "편의점에"})
        item = result["card"]["items"][0]
        self.assertEqual(acts(item), [("D", "object"), ("A", "defend"), ("D", "recheck")])
        self.assertAlmostEqual(item["detail"]["contrast_first"], 0.3, places=2)
        self.assertAlmostEqual(item["detail"]["contrast"], 0.05, places=2)
        self.assertEqual((item["status"], item["check_needed"], item["choice"]), ("proposed", False, "C1"))

    def test_giving_way_to_a_strong_objection_reads_the_words_as_they_are(self):
        result = self.run_card(judge(plain=0.6), {"stance": "concede", "cue": ""})
        self.assertEqual(result["card"]["items"], [])  # a DB word in its ordinary use leaves the card
        self.assertEqual(result["detection"]["ordinary_words"], ["두쫀쿠"])

    def test_the_expression_itself_is_no_cue(self):
        result = self.run_card(judge(plain=0.3), {"stance": "defend", "cue": "두쫀쿠"})
        item = result["card"]["items"][0]
        self.assertEqual(acts(item), [("D", "object"), ("A", "concede")])
        self.assertEqual(item["detail"]["exchange"][-1]["why"], "표현 말고는 단서가 없음")
        self.assertEqual((item["status"], item["check_needed"]), ("uncertain", True))  # below tau_concede: shown to check


def chooser(none=0.1, **rest):
    """E's choice among the posts' sentences: `none` is the share of 'none' (a function of the question, which holds B's meaning, or a
    number), the rest split evenly among the sentences; other questions go to judge()."""
    others = judge(**rest)

    def pick(payload, labels):
        q = payload["question"]
        if not q.startswith("보기는 근거 글의 문장들"):
            return others(payload, labels)
        n = none(q) if callable(none) else none
        return {l: n if payload["options"][l].startswith("없음") else (1 - n) / (len(labels) - 1) for l in labels}
    return pick


class SelectDebateTests(unittest.TestCase):
    """v16 select (the default): the code lists the posts' sentences that speak of the word; E chooses the one saying B's meaning."""

    def card(self, posts, reading, span, pick, **config):
        return analyzer(posts, reading, span, pick, debate_mode="select", **config)

    def test_e_finds_the_sentence_that_says_it(self):
        client, a = self.card([POST], "회와 피크닉을 합친 말", "회크닉", chooser(none=0.05))
        result = a.run(text="오늘 회크닉 가자", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("E", "accept")])
        self.assertEqual((item["meaning"], item["post_how"]), ("회와 피크닉을 합친 말", "debated"))
        self.assertIn(GLOSS, item["post_quote"])  # the post's own sentence (here with its heading line, which has no full stop)
        self.assertFalse([c for c in result["calls"] if c["stage"] == "debate"])  # B copied nothing
        asked = [json.loads(c["messages"][1]["content"]) for c in result["calls"] if c["stage"] == "choose"]
        sentences = [q for q in asked if q["question"].startswith("보기는 근거 글의 문장들")]
        self.assertEqual(len(sentences), len(sentences[0]["options"]))  # every order of the sentences

    def test_e_objects_b_reads_again_and_corrects(self):
        client, a = self.card([POST], "회사 사람들과 가는 소풍", "회크닉", chooser(none=lambda q: 0.9 if "회사 사람들" in q else 0.05))
        client.revise_answers = [{"stance": "revise", "meaning": "회와 피크닉을 합친 말"}]
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("E", "object"), ("B", "revise"), ("E", "accept")])
        self.assertEqual(item["meaning"], "회와 피크닉을 합친 말")

    def test_a_reading_no_sentence_backs_is_kept_but_never_settled(self):
        client, a = self.card([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", chooser(none=0.9))
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("E", "object"), ("B", "withdraw"), ("E", "hedge")])
        self.assertEqual((item["basis"], item["meaning"], item["status"], item["check_needed"]),
                         ("post", "귀엽다는 뜻의 감탄", "uncertain", True))
        self.assertIn("문장을 찾지 못했습니다", item["uncertainty"])
        self.assertEqual((item["post_how"], item["post_quote"]), ("unverified", ""))

    def test_a_correction_that_says_the_same_is_no_correction(self):
        client, a = self.card([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", chooser(none=0.9))
        client.revise_answers = [{"stance": "revise", "meaning": "귀엽다는 뜻의 감탄"}]
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(item["detail"]["exchange"][-2], {"agent": "B", "act": "withdraw", "why": "뜻을 고치지 못함"})
        self.assertEqual(item["check_needed"], True)

    def test_with_mad_first_c_reading_stands_beside_a_meaning_to_check(self):
        client, a = self.card([ROUNDUP], "귀엽다는 뜻의 감탄", "야르", chooser(none=0.9), mad_first=True)
        item = a.run(text="오늘 치킨 야르", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item)[0], ("C", "read"))
        self.assertEqual(item["alternatives"][0], "문맥으로 읽은 뜻(에이전트 C): 테스트용 짐작")


class MadFirstTests(unittest.TestCase):
    """v16 MAD first: B and C for every word, and C's reading of the sentence where no evidence holds the word (never settled)."""

    def test_a_word_nothing_covers_is_still_read_from_the_sentence_and_shown_as_a_guess(self):
        client, a = analyzer([], "없음", "야르", judge(), mad_first=True)
        result = a.run(text="오늘 치킨 진짜 야르", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["basis"], item["status"], item["check_needed"], item["choice"]), ("context", "uncertain", False, "N"))
        self.assertEqual((item["meaning"], item["reading"], item["easy"]), ("테스트용 짐작", "테스트용 상황", ""))
        self.assertIn("짐작", item["uncertainty"])
        self.assertEqual(acts(item), [("C", "read")])
        self.assertIsNone(result["card"]["sentence"])  # a guess never goes into the sentence

    def test_when_b_gives_way_c_reads_the_sentence_and_the_posts_stay(self):
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge(), mad_first=True)
        client.quote_answers = [{"stance": "withdraw", "quote": "", "meaning": ""}]
        item = a.run(text="오늘 회크닉 가자", mode="card")["card"]["items"][0]
        self.assertEqual(acts(item), [("B", "claim"), ("B", "withdraw"), ("C", "read")])
        self.assertEqual((item["basis"], item["meaning"], item["posts"][0]["url"]), ("context", "테스트용 짐작", POST["url"]))

    def test_a_reviewed_row_stands_against_b_and_c_too(self):
        row = {"id": "live-e-8", "expression": "회크닉", "variants": [], "meaning": "회사 사람들과 가는 소풍", "family": "live:회크닉",
               "source": "https://x.test/8", "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00", "review": "검수됨"}
        client, a = analyzer([POST], "회와 피크닉을 합친 말", "회크닉", judge(), lexicon=[row], mad_first=True)
        client.quote_answers = [{"stance": "keep", "quote": GLOSS, "meaning": ""}]
        result = a.run(text="오늘 회크닉 가자", mode="card")
        stages = [c["stage"] for c in result["calls"]]
        self.assertIn("post", stages)  # B reads the posts though a person reviewed the row
        self.assertIn("read", stages)  # C reads the comment though the row has one sense
        self.assertEqual(acts(result["card"]["items"][0])[0], ("C", "read"))

    def test_v17_with_nothing_besides_the_word_c_makes_no_guess(self):  # 쮀쮀이야 (발표자료 3쪽): only "이야" is left to read
        from tracetalk.mad.card import context_letters
        self.assertEqual((context_letters("쮀쮀이야!!", "쮀쮀"), context_letters("야르 ㅋㅋ", "야르"), context_letters("오늘 치킨 진짜 야르", "야르")),
                         (2, 0, 6))
        client, a = analyzer([], "없음", "쮀쮀", judge(), mad_first=True)
        result = a.run(text="쮀쮀이야", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["meaning"]), ("read", "model", ""))
        self.assertNotIn("read", [c["stage"] for c in result["calls"]])  # C is not asked to read a sentence that is not there

    def test_when_off_a_word_nothing_covers_is_not_known(self):
        client, a = analyzer([], "없음", "야르", judge())
        item = a.run(text="오늘 치킨 진짜 야르", mode="card")["card"]["items"][0]
        self.assertEqual((item["decided_by"], item["basis"], item["meaning"]), ("read", "model", ""))



class BareWordTests(unittest.TestCase):
    """v18: one word typed alone is a lookup (오디세이, 11-11): a DB word read literally is shown to check, not dropped, and a word
    nothing knows is asked about instead of passed over as 'no slang'. With words around it, nothing changes (ContrastDebateTests)."""

    def test_a_db_word_alone_read_literally_is_shown_to_check(self):
        client = FixtureClient()
        client.pick, client.cue_answer = judge(plain=0.6), {"stance": "concede", "cue": ""}
        a = CardAnalyzer(client, lexicon=[REVIEWED], usages=[], config={"debate": True, "mad_first": False})
        result = a.run(text="두쫀쿠", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["choice"], item["status"], item["detail"].get("bare")), ("C1", "uncertain", True))
        self.assertEqual(item["meaning"], REVIEWED["meaning"])
        self.assertIn("가릴 문맥이 없습니다", item["uncertainty"])
        self.assertEqual(result["detection"]["ordinary_words"], [])

    def test_a_word_alone_nothing_knows_is_asked_about(self):
        client = FixtureClient()
        client.probe = lambda payload: {"has_slang": 0.05, "new_word": 0.9}.get(payload["probe"], 0.1)
        result = CardAnalyzer(client, lexicon=[], usages=[], config={}).run(text="오디세이", mode="card")
        item = result["card"]["items"][0]
        self.assertEqual((item["expression"], item["decided_by"], item["basis"], item["meaning"]), ("오디세이", "read", "model", ""))
        self.assertFalse(item["flagged_by_model"])

    def test_an_ordinary_word_alone_stays_plain(self):
        client = FixtureClient()
        client.probe = lambda payload: 0.05
        self.assertTrue(CardAnalyzer(client, lexicon=[], usages=[], config={}).run(text="사과", mode="card")["card"]["plain"])

    def test_what_counts_as_one_word_alone(self):
        from tracetalk.mad.card import bare_word
        self.assertEqual((bare_word("오디세이?")["span"], bare_word("ㅋㅋ오디세이")["span"]), ("오디세이", "오디세이"))
        self.assertEqual((bare_word("오디세이 뭐야"), bare_word("ㅋㅋ"), bare_word("가")), (None, None, None))


class DefaultsTests(unittest.TestCase):
    def test_from_012_the_agents_debate_and_mad_comes_first(self):  # dev 216: 152 · 20 against 151 · 23 (_work/v16/NOTES.md)
        from tracetalk.mad.card import CARD
        self.assertEqual((CARD["debate"], CARD["debate_mode"], CARD["mad_first"], CARD["tau_support"]), (True, "select", True, 0.9))


if __name__ == "__main__":
    unittest.main()
