"""v15 (0.11, after the error split of the dev runs): rules pinned here. Rules only, no model."""
import unittest

from tracetalk.mad.card import easy_problem
from tracetalk.evidence.corpus import Corpus, post_date

DATING = {"url": "https://gogumafarm.kr/x", "date": "2026-07-16", "blocks": [
    {"kind": "h", "text": "셋로그 소개팅, 숏셜링: 요즘 MZ세대가 관계를 맺는 방식"},
    {"kind": "p", "text": "셋로그 소개팅은 2초짜리 일상 영상을 활용한 소개팅이에요. 최근 주목받은 ‘3일팅’은 5:5 셋로그 방에서 진행됩니다. "
                          "참가자들은 3일 동안 하루 여러 번 짧은 영상을 올리고 마지막 날 마음에 드는 상대를 선택해요."}]}
TIPS = {"url": "https://maily.so/farmingletter/posts/x", "date": "2025-01-10", "blocks": [
    {"kind": "h", "text": "이번 주의 밈"},
    {"kind": "p", "text": "담당자라면 릴스에서 '든든든든'을 활용해 고난스러운 상황 뒤에 긍정적인 행동을 붙이는 한 문장을 써 보면 끝이야."}]}


class UsePartTests(unittest.TestCase):
    def test_a_sentence_presenting_the_word_as_its_topic_is_read_though_another_sentence_says_활용(self):
        found = Corpus([DATING]).passages("3일팅")
        self.assertTrue(found and found[0]["score"] >= 1.5)
        self.assertIn("3일 동안", found[0]["text"])

    def test_a_block_that_says_활용_in_the_sentence_naming_the_word_is_still_the_part_on_using_it(self):
        self.assertFalse([p for p in Corpus([TIPS]).passages("든든든든") if p["score"] >= 1.5])


class DatedHeadingTests(unittest.TestCase):
    def test_a_post_without_a_date_takes_the_one_its_heading_gives_and_never_a_guess(self):
        self.assertEqual(post_date({"date": "", "blocks": [{"kind": "h", "text": "26.11.05 (목) '존박 맥도날드 랩'"}]}), "2026-11-05")
        self.assertEqual(post_date({"date": "", "blocks": [{"kind": "p", "text": "위픽레터2025.02.254분22111 낉여오거라"}]}), "2025-02-25")
        self.assertEqual(post_date({"date": "", "blocks": [{"kind": "p", "text": "매주 수요일 아침 7:30에 발송됩니다."}]}), "")
        self.assertEqual(post_date({"date": "2026-07-16", "blocks": []}), "2026-07-16")


class CutDownEasyTests(unittest.TestCase):
    def test_easy_words_cut_out_of_the_expression_are_sent_back(self):
        self.assertIsNotNone(easy_problem("존박 맥도날드 랩", "맥도날드 랩"))
        self.assertIsNone(easy_problem("존박 맥도날드 랩", "존박이 랩으로 주문하는 영상"))
        self.assertIsNone(easy_problem("회크닉", "회 먹는 소풍"))


if __name__ == "__main__":
    unittest.main()
