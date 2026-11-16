"""v13 (docs/DESIGN.md): the posts are read by quoting (tracetalk/evidence/reading.py). Rules only; no model."""
import unittest

from tracetalk.evidence import reading


def P(text):
    return [{"text": text}]


class NamesTests(unittest.TestCase):
    def test_a_word_on_its_own_not_the_start_of_a_longer_word(self):
        self.assertTrue(reading.names("치올(치고 올라간다)과 야푸 같은 말", ["치올"]))
        self.assertTrue(reading.names("요즘 손절하고 싶은 사람", ["손절"]))
        self.assertFalse(reading.names("너 맨날 지각하는 거 되게 손절미 있다", ["손절"]))
        self.assertTrue(reading.names("전액 현금으로 매입했다는 보도", ["전액 현금으로 매입"]))

    def test_a_sentence_that_glosses_another_word_is_not_a_candidate(self):
        self.assertTrue(reading.defines_longer("손절미: 손절하고 싶어지는 특징", ["손절"]))
        self.assertTrue(reading.defines_other("위쑤시개: 스트레스 받을 때 먹는 매운 음식들 엽떡, 마라탕 등", ["마라탕"]))
        self.assertFalse(reading.defines_other("치올: 치고 올라간다", ["치올"]))
        self.assertTrue(reading.explains_other(["손절"], P("2️⃣ 손절미: 손절하고 싶어지는 특징 매번 지각하는 사람한테 쓰는 용어야.")))
        self.assertFalse(reading.explains_other(["손절"], P("요즘 손절이 유행이다. 손절은 관계를 끊는 것.")))


class StatedTests(unittest.TestCase):
    def test_brackets_an_abbreviation(self):
        self.assertEqual(reading.stated(["치올"], P("DTD, 치올(치고 올라간다), 야푸 같은 줄임말이 생겨나고 있다."))[0], "'치고 올라간다'의 줄임말")
        self.assertEqual(reading.stated(["다꾸"], P("다꾸(다이어리 꾸미기)처럼 야구일기를 꾸민다."))[0], "'다이어리 꾸미기'의 줄임말")

    def test_letters_spelled_out_are_not_a_gloss(self):
        self.assertIsNone(reading.stated(["GMG"], P("요즘 GMG(가면 감)라는 말이 유행이다.")))

    def test_colon_called_and_expressed_as(self):
        self.assertEqual(reading.stated(["손절미"], P("손절미: 손절하고 싶어지는 특징 ex) 너 맨날 지각하는 거"))[0], "손절하고 싶어지는 특징")
        self.assertEqual(reading.stated(["손민수"], P("내 최애가 간 맛집을 따라하는 걸 손민수라고 하잖아."))[0], "내 최애가 간 맛집을 따라하는 것")
        self.assertEqual(reading.stated(["동결건조"], P("작년 엑스에서 엄마가 늙지 않았으면 좋겠다는 마음을 ‘동결건조’로 표현하며 시작됐다."))[0],
                         "엄마가 늙지 않았으면 좋겠다는 마음을 나타내는 말")

    def test_a_misheard_line(self):
        text = "원래 가사를 알고 나서도 계속 이혼앤비혼으로 들리는 게 문제다. 원래 가사는 'Neon and Beyond'."
        self.assertEqual(reading.stated(["이혼앤비혼"], P(text))[0], "원래 가사 'Neon and Beyond'가 '이혼앤비혼'처럼 들리는 데서 나온 말")

    def test_nothing_stated(self):
        self.assertIsNone(reading.stated(["회크닉"], P("날씨가 더 추워지기 전에 회크닉 한번 가보길 바란다.")))


if __name__ == "__main__":
    unittest.main()


class HeadwordTests(unittest.TestCase):
    def corpus(self):
        from tracetalk.evidence.corpus import Corpus
        taw = {"url": "https://maily.so/trendaword/posts/a", "date": "", "blocks": [
            {"kind": "h", "text": "[Trend A Word #647] 온라인 절에서도 구석 자리만 찾게 되는 사람 등장"}, {"kind": "h", "text": "26.11.02 (월) '산사'"},
            {"kind": "p", "text": "지난 10월 메타몽 개발자가 만든 온라인 사찰 ‘산사’가 엄청난 인기다."}]}
        roundup = {"url": "https://gogumafarm.kr/x", "date": "2026-10-27", "blocks": [
            {"kind": "h", "text": "나 왜 유행 밈 소개가 영원할 거 같지? [2026년 10월 최신 밈 모음]"}, {"kind": "h", "text": "🫢 구글 이모지 뒷모습"},
            {"kind": "h", "text": "💡 어떻게 활용할 수 있나요?"}, {"kind": "h", "text": "1+1 세트: 반대가 있어서 카피가 easy!"}]}
        return Corpus([taw, roundup])

    def test_a_newsletter_word_and_a_roundup_heading_not_its_section_titles(self):
        self.assertEqual(set(self.corpus().headwords().values()), {"산사", "구글 이모지 뒷모습"})

    def test_found_on_its_own_in_a_comment(self):
        c = self.corpus()
        self.assertEqual([h["span"] for h in c.headword_hits("팀장님한테 산사 알려주지 마")], ["산사"])
        self.assertEqual([h["span"] for h in c.headword_hits("산사에 가서 목탁 쳤어")], ["산사"])
        self.assertEqual(c.headword_hits("등산사진 올렸어"), [])  # not inside another word
        self.assertEqual([h["span"] for h in c.headword_hits("구글이모지 뒷모습 봤어?")], ["구글이모지 뒷모습"])

    def test_a_sung_line_with_tildes(self):
        from tracetalk.evidence.corpus import Corpus
        taw = {"url": "https://maily.so/trendaword/posts/b", "date": "", "blocks": [{"kind": "h", "text": "26.10.08 (목) 'L을 가져가'"}]}
        hits = Corpus([taw]).headword_hits("L~을 가져가~ 측면대~측면~ 크리스!크로스~! 셀~카~?")
        self.assertEqual([h["span"] for h in hits], ["L~을 가져가"])


class SentenceTests(unittest.TestCase):
    def test_a_finished_easy_word_with_the_comments_ending_glued_on(self):
        from tracetalk.mad.card import sentence_problems
        item = {"expression": "동결건조", "start": 9, "end": 13, "easy": "멈추세요", "status": "proposed", "basis": "post", "choice": "R1", "estimate": False}
        text = "아누누님 우리엄마좀 동결건조시켜주세요"
        self.assertTrue(any("어미가 붙어" in p for p in sentence_problems(text, "아누누님 우리엄마 좀 멈추세요시켜주세요", [item])))
        self.assertFalse(any("어미가 붙어" in p for p in sentence_problems(text, "아누누님 우리엄마 좀 멈추게 해 주세요", [{**item, "easy": "멈추게 하다"}])))

    def test_an_easy_word_that_ends_the_sentence_where_the_comment_goes_on(self):
        from tracetalk.mad.card import easy_problem
        self.assertIn("이어지는 꼴", easy_problem("동결건조", "멈추세요", "우리엄마좀 동결건조시켜주세요") or "")
        self.assertIsNone(easy_problem("동결건조", "늙지 않게", "우리엄마좀 동결건조시켜주세요"))
        self.assertIsNone(easy_problem("럭키비키", "운이 좋아요", "오늘 완전 럭키비키"))  # the comment ends with the word: fine
