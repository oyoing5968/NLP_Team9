"""v14 (0.11, docs/DESIGN.md 0.11): four rule gaps the fresh_v5 test showed, each fixed and pinned here. Rules only, and the card with
TEST-FIXTURE-NOT-A-MODEL responses."""
import unittest

from tracetalk.evidence import reading
from tracetalk.mad.card import CardAnalyzer
from tracetalk.evidence.corpus import Corpus
from frontier_fixture import FixtureClient
from test_mad09 import SENSE, shares

ONE_WORD = {"url": "https://maily.so/trendaword/posts/x", "date": "2026-11-05", "blocks": [
    {"kind": "h", "text": "[Trend A Word #650] 햄버거 주문하랬더니 힙합을 말아주는 존박"},
    {"kind": "h", "text": "26.11.05 (목) '존박 맥도날드 랩'"},
    {"kind": "h", "text": "어떤 이야기일까?"},
    {"kind": "p", "text": "요즘 알고리즘에서 자꾸 마주치는 존박의 ‘맥도날드 랩’ 이야기다. 노래 잘하는 건 알고 있었지만 그가 햄버거까지 이렇게 주문할 줄은 몰랐다."},
    {"kind": "p", "text": "유튜브 채널에 올라온 ‘맥도날드에서 랩으로 주문하는 존박’ 영상이 시작이다. 매장에서 준비한 랩으로 메뉴를 주문하는 콘텐츠다."}]}


class OneWordPostTests(unittest.TestCase):
    def test_the_words_own_post_is_read_even_when_its_body_does_not_repeat_the_word(self):
        found = Corpus([ONE_WORD]).passages("존박 맥도날드 랩")
        self.assertTrue(found and found[0]["score"] >= 1.5)
        self.assertIn("랩으로 메뉴를 주문", found[0]["text"])


class ParenthesisTests(unittest.TestCase):
    def test_a_parenthesis_after_a_long_phrase_is_part_of_a_title_not_a_gloss(self):
        p = [{"text": "🎙️ 내가 아이돌이었으면 이 파트는 꼭 하고 싶음 (직접 부름) 이 밈은 엑스에서 시작됐어요."}]
        self.assertIsNone(reading.stated(["내가 아이돌이었으면 이 파트는 꼭 하고 싶음"], p))
        self.assertEqual(reading.stated(["치올"], [{"text": "DTD, 치올(치고 올라간다) 같은 말"}])[0], "'치고 올라간다'의 줄임말")


ROUNDUP = {"url": "https://gogumafarm.kr/x", "date": "2026-11-05", "blocks": [
    {"kind": "h", "text": "26.11.04 (수) '얼데이드립'"},
    {"kind": "p", "text": "2. 나는 원곡보다 얼데이드립이 말아주는 7080이 좋더라 요즘 알고리즘에 자주 뜨는 채널 이야기다."},
    {"kind": "p", "text": "얼데이드립은 아이돌 노래를 7080 스타일로 다시 불러 주는 유튜브 채널이다. 부모님 세대도 즐겨 듣는다."}]}
MALAJU = {**SENSE, "id": "live-e-9", "expression": "말아주다", "variants": ["말아주"], "meaning": "무언가를 아주 잘 해내다"}
LIP = {**SENSE, "id": "live-e-8", "expression": "립 버전", "variants": [], "meaning": "용량을 줄인 파일"}


def analyzer(lexicon, post, pick, meaning):
    client = FixtureClient()
    client.pick, client.post_meaning, client.probe = pick, meaning, (lambda payload: 0.9)
    return CardAnalyzer(client, lexicon=lexicon, usages=[], corpus=Corpus([post]))


class HeadwordTests(unittest.TestCase):
    def test_a_headword_is_read_though_its_post_also_names_a_db_word_of_the_comment(self):
        a = analyzer([MALAJU], ROUNDUP, shares({"7080": 0.9, "잘 해내다": 0.9, "표준어": 0.05, "맞지 않고": 0.05}),
                     "아이돌 노래를 7080 스타일로 다시 불러 주는 유튜브 채널")
        result = a.run(text="나는 원곡보다 얼데이드립이 말아주는 7080이 좋더라", mode="card")
        words = {it["expression"]: it for it in result["card"]["items"]}
        self.assertIn("얼데이드립", words)
        self.assertEqual(words["얼데이드립"]["basis"], "post")

    def test_a_db_word_starting_inside_a_headword_gives_way_to_it(self):
        a = analyzer([LIP], ROUNDUP, shares({"7080": 0.9, "용량": 0.9, "표준어": 0.05, "맞지 않고": 0.05}),
                     "아이돌 노래를 7080 스타일로 다시 불러 주는 유튜브 채널")
        result = a.run(text="얼데이드립 버전 들었는데 엄빠도 좋아하심", mode="card")
        spans = [it["expression"] for it in result["card"]["items"]]
        self.assertIn("얼데이드립", spans)
        self.assertNotIn("립 버전", spans)
        self.assertEqual(result["detection"]["db_fragments_of_headwords"], ["립 버전"])


if __name__ == "__main__":
    unittest.main()
