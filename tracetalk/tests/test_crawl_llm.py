"""Crawler v3 (tracetalk/crawl/extract_llm.py): the model lists what a post explains; the code keeps only words that are in
the post, are not section titles or questions, and are not an ordinary word read whole (좋다). The model here is a
stand-in that returns fixed JSON: TEST-FIXTURE-NOT-A-MODEL."""
import json
import unittest

from tracetalk.crawl import extract_llm as crawl_llm

try:
    from kiwipiepy import Kiwi
except ImportError:  # the Mac runtime has it (mac/setup.sh)
    Kiwi = None

PAGE = {"url": "https://gogumafarm.kr/?p=1", "date": "", "blocks": [
    {"kind": "p", "text": "🎵 케케크롱", "bold": []}, {"kind": "p", "text": "출처 X", "bold": []},
    {"kind": "p", "text": "‘케케크롱’은 뜻 없이 문장 끝에 붙이는 추임새예요. “출근 왜 하지 케케크롱”", "bold": []},
    {"kind": "p", "text": "좋🤙다👍 손동작 밈도 있어요. 어떤 밈인가요?", "bold": []}]}


class Stand:
    def __init__(self, items):
        self.items, self.calls = items, []

    def generate(self, messages, schema, seed, max_tokens):
        self.calls.append(json.loads(messages[1]["content"]))
        return {"raw": json.dumps({"items": self.items}, ensure_ascii=False)}


@unittest.skipIf(Kiwi is None, "kiwipiepy 없음")
class LlmExtractTests(unittest.TestCase):
    def test_only_words_in_the_post_and_not_ordinary_or_titles_are_kept(self):
        model = Stand([{"expression": "케케크롱", "meaning": "뜻 없이 문장 끝에 붙이는 추임새", "example": "출근 왜 하지 케케크롱"},
                       {"expression": "좋다", "meaning": "손동작으로 좋다를 표현하는 밈", "example": ""},
                       {"expression": "지어낸말", "meaning": "글에 없는 낱말", "example": ""},
                       {"expression": "어떤 밈인가요?", "meaning": "소제목", "example": ""}])
        log = []
        got = crawl_llm.llm_candidates(PAGE, model, Kiwi(), log=log)
        self.assertEqual([(c["expression"], c["examples"]) for c in got], [("케케크롱", ["출근 왜 하지 케케크롱"])])
        self.assertEqual({x["expression"]: x["why"] for x in log if not x["kept"]},
                         {"좋다": "보통 낱말", "지어낸말": "글에 없음", "어떤 밈인가요": "낱말 아님"})
        self.assertIn("instruction", model.calls[0])  # the post goes in as data, beside the instruction

    def test_a_broken_answer_loses_that_part_only(self):
        class Broken(Stand):
            def generate(self, *a):
                return {"raw": "{not json"}
        log = []
        self.assertEqual(crawl_llm.llm_candidates(PAGE, Broken([]), Kiwi(), log=log), [])
        self.assertTrue(any("problem" in x for x in log))

    def test_the_ordinary_word_check(self):
        k = Kiwi()
        self.assertEqual({w: crawl_llm.ordinary(w, k) for w in ("좋다", "가자", "진짜", "삐바삐", "학씨", "케케크롱")},
                         {"좋다": True, "가자": True, "진짜": True, "삐바삐": False, "학씨": False, "케케크롱": False})


@unittest.skipIf(Kiwi is None, "kiwipiepy 없음")
class V5Tests(unittest.TestCase):
    def test_names_and_the_title_are_left_out_memes_from_shows_stay(self):
        page = {"url": "https://maily.so/farmingletter/posts/x", "date": "", "blocks": [
            {"kind": "h", "text": "흑백요리사 밈 모음", "bold": []},
            {"kind": "p", "text": "흑백요리사는 요리 경연 프로그램이야. 생존입니다는 배달 리뷰에 쓰는 밈이야.", "bold": []}]}
        model = Stand([{"expression": "흑백요리사", "meaning": "넷플릭스 요리 경연 프로그램이다.", "example": ""},
                       {"expression": "생존입니다", "meaning": "맛있다는 뜻으로 배달 리뷰에 쓰는 밈이다.", "example": ""},
                       {"expression": "흑백요리사 밈 모음", "meaning": "흑백요리사 밈을 모은 글이다.", "example": ""}])
        log = []
        got = crawl_llm.llm_candidates(page, model, Kiwi(), log=log, size=1800, names=True)
        self.assertEqual([c["expression"] for c in got], ["생존입니다"])
        self.assertEqual({x["expression"]: x["why"] for x in log if not x["kept"]},
                         {"흑백요리사": "이름·제목", "흑백요리사 밈 모음": "이름·제목"})
        self.assertEqual(len(crawl_llm.llm_candidates(page, model, Kiwi())), 3)  # v3 (names=False) keeps them


class StandV4:
    """Answers the list step with fixed items and the define step from a table: TEST-FIXTURE-NOT-A-MODEL."""
    def __init__(self, items, meanings):
        self.items, self.meanings, self.pieces = items, meanings, {}

    def generate(self, messages, schema, seed, max_tokens):
        data = json.loads(messages[1]["content"])
        if "target" in data:
            self.pieces[data["target"]] = data["piece"]
            return {"raw": json.dumps({"meaning": self.meanings.get(data["target"], ""), "example": ""}, ensure_ascii=False)}
        return {"raw": json.dumps({"items": self.items}, ensure_ascii=False)}


ROUNDUP = {"url": "https://gogumafarm.kr/?p=2", "date": "", "blocks": [
    {"kind": "h", "text": "요즘 뜨는 밈 모음", "bold": []},
    {"kind": "p", "text": "오늘은 길차와 티크닉을 소개해요.", "bold": []},
    {"kind": "h", "text": "🍵 길차", "bold": []},
    {"kind": "p", "text": "길차는 개완을 들고 걸으며 차를 마시는 것이에요.", "bold": []},
    {"kind": "h", "text": "🧺 티크닉", "bold": []},
    {"kind": "p", "text": "티크닉은 티와 피크닉을 합친 말이에요.", "bold": []},
    {"kind": "p", "text": "흑백요리사는 요리 경연 프로그램이에요.", "bold": []}]}


@unittest.skipIf(Kiwi is None, "kiwipiepy 없음")
class V4Tests(unittest.TestCase):
    def test_new_words_are_defined_from_their_own_part_and_names_are_left_out(self):
        model = StandV4([{"expression": "길차", "kind": "new"}, {"expression": "티크닉", "kind": "new"},
                         {"expression": "흑백요리사", "kind": "name"}, {"expression": "요즘 뜨는 밈 모음", "kind": "new"},
                         {"expression": "좋다", "kind": "new"}],
                        {"길차": "개완을 들고 걸으며 차를 마시는 것", "티크닉": ""})
        log = []
        got = crawl_llm.llm_candidates_v4(ROUNDUP, model, Kiwi(), log=log)
        self.assertEqual([(c["expression"], c["meaning"]) for c in got], [("길차", "개완을 들고 걸으며 차를 마시는 것")])
        why = {x["expression"]: x["why"] for x in log if not x["kept"]}
        self.assertEqual(why, {"흑백요리사": "이름·기타", "요즘 뜨는 밈 모음": "글 제목", "좋다": "글에 없음", "티크닉": "뜻 없음"})
        # the define step saw the word's own section (its title and the paragraph under it), not the intro line
        self.assertTrue(model.pieces["길차"].startswith("🍵 길차"))
        self.assertNotIn("티크닉은", model.pieces["길차"])


if __name__ == "__main__":
    unittest.main()
