"""0.8.1 (11-06, after fresh_v2): MAD over a word with one DB sense sets a side against the DB sense; a row whose part
of speech never inflects gets no verb pattern (사이다 / 팬사인회); what the collector stored for a word the DB has no
meaning for feeds the next card as usages (해석하면서 쌓기). Responses are TEST-FIXTURE-NOT-A-MODEL."""
import json
import tempfile
import unittest
from pathlib import Path

from tracetalk.mad.card import CardAnalyzer, entries_from_store, find
from tracetalk.db.usage import LiveStore, collected_groups, evidence, merge_groups
from frontier_fixture import FixtureClient
from tracetalk.mad import card as card_module

def setUpModule():  # these tests are about the 0.7-0.8 routes, still selectable (card.CARD decide="roles", unknown="mad")
    card_module.CARD.update(decide="roles", unknown="mad", pick=False)


def tearDownModule():
    card_module.CARD.update(decide="witness", unknown="read", pick=True)


LIVE = {"id": "live-e-1", "expression": "두쫀쿠", "variants": [], "meaning": "두바이 쫀득 쿠키", "family": "live:두쫀쿠",
        "source": "팀", "license": "팀 입력", "added_at": "2026-11-05T10:00:00+09:00"}
TWO = {**LIVE, "id": "live-e-2", "meaning": "두꺼운 쫀득 쿠키"}


def card(lexicon, usages=(), **config):
    client = FixtureClient()
    client.probe = lambda payload: 0.9
    return client, CardAnalyzer(client, lexicon=lexicon, usages=list(usages), config=config or None)


def row(expression, text, choice="N", headword=None, at="2026-11-06T10:00:00+09:00"):
    return {"expression": expression, "headword": headword, "text": text, "choice": choice, "status": "proposed",
            "meaning": "", "easy": "", "decided_by": "mad", "mad_reason": "unknown", "at": at, "input_sha256": ""}


class OneSenseTests(unittest.TestCase):
    def test_one_db_sense_is_debated_by_the_db_side_and_a_side_against_it(self):
        client, a = card([LIVE], one_sense="check")  # not the default since fresh_v3 ⑫
        item = a.run(text="편의점에 두쫀쿠 들어왔대", mode="card")["card"]["items"][0]
        self.assertEqual([d["side"] for d in item["detail"]["debate"]], ["DB 뜻 쪽", "반대 쪽"])
        self.assertEqual(item["detail"]["judge_role"], "check")
        roles = [r["role"] for r in client.requests if r.get("stage") == "propose"]
        self.assertTrue(any("작품 제목" in r for r in roles))
        judge = next(r for r in client.requests if r.get("stage") == "judge")
        self.assertIn("meaning은 그 후보와 같은 뜻이어야 한다", judge["role"])

    def test_the_080_roles_and_two_senses_keep_the_candidate_comparison(self):
        for lexicon, config in (([LIVE], {}), ([LIVE], {"one_sense": "compare"}), ([LIVE, TWO], {"one_sense": "check"})):
            client, a = card(lexicon, **config)
            item = a.run(text="편의점에 두쫀쿠 들어왔대", mode="card")["card"]["items"][0]
            self.assertEqual([d["side"] for d in item["detail"]["debate"]], ["가설 1", "가설 2"], config)
            self.assertEqual(item["detail"]["judge_role"], "v9")


class NounTests(unittest.TestCase):
    def test_a_noun_ending_in_da_is_not_matched_as_a_verb(self):
        noun = {"id": "lx-x", "expression": "사이다", "variants": [], "meaning": "통쾌함", "family": "kc:사이다",
                "source": "KoCulture", "license": "test"}
        verb = {**noun, "id": "lx-y", "expression": "짜치다", "family": "kc:짜치다"}
        spans = lambda lexicon, text: [h["span"] for h in find(text, entries_from_store(lexicon, []))]
        self.assertEqual(spans([noun], "어제 팬사인회 다녀왔어"), ["사인"])  # no part of speech: still a verb stem
        self.assertEqual(spans([{**noun, "pos": "명사"}], "어제 팬사인회 다녀왔어"), [])
        self.assertEqual(spans([{**noun, "pos": "명사"}], "완전 사이다네"), ["사이다"])
        self.assertEqual(spans([{**verb, "pos": "동사"}], "쟤 진짜 짜친다"), ["짜친"])
        self.assertEqual(spans([verb], "쟤 진짜 짜친다"), ["짜친"])

    def test_the_part_of_speech_supplement_covers_the_demo_db(self):
        from tracetalk.db.lexicon import load_lexicon
        from tracetalk.db.lexicon import ROOT
        lexicon = load_lexicon(ROOT / "data/db/lexicon/lexicon_demo_v1.jsonl")
        self.assertEqual([h["span"] for h in find("어제 장원영 팬사인회 다녀왔어", entries_from_store(lexicon, []))], [])


class VariantTests(unittest.TestCase):
    def test_a_spaced_variant_split_into_short_pieces_is_refused(self):
        from tracetalk.db import update as update_db
        with self.assertRaises(ValueError) as caught:
            update_db.entry_row("live-e-x", "2026-11-06", "너무 불미스러운 일이 일어났어요", ["불미스러운", "일이", "일어났어요"],
                                "황당한 일", "출처")
        self.assertIn("'일이'", str(caught.exception))
        with self.assertRaises(ValueError):
            update_db.usage_row("live-u-x", "2026-11-06", "감도 안 온다", ["감도", "안온다"], ["감도 안 온다 진짜"], "출처")
        row = update_db.entry_row("live-e-y", "2026-11-06", "너무 불미스러운 일이 일어났어요", ["불미스러운일이일어났어요"],
                                  "황당한 일", "출처")
        self.assertEqual(row["variants"], ["불미스러운일이일어났어요"])
        self.assertEqual(update_db.entry_row("live-e-z", "2026-11-06", "긁히다", ["긁힌"], "기분 상함", "출처")["variants"],
                         ["긁힌"])  # a short expression keeps its short forms


class CollectedUsageTests(unittest.TestCase):
    def test_two_different_comments_make_a_group_and_standard_or_known_words_do_not(self):
        rows = [row("볼꾸", "요즘 볼꾸에 빠짐"), row("볼꾸", "다이소에서 볼꾸 했다"), row("볼꾸", "다이소에서 볼꾸 했다"),
                row("젬민이네", "완전 젬민이네"), row("젬민이", "AI만 믿는 젬민이"),
                row("이쑤시개", "이쑤시개 줘", "L"), row("이쑤시개", "이쑤시개 하나만", "L"),
                row("두쫀쿠", "두쫀쿠 품절"), row("두쫀쿠", "두쫀쿠 또 품절"),
                row("하나뿐", "하나뿐인 문장")]
        groups = {g["expression"]: g for g in collected_groups(rows, known=["두쫀쿠"])}
        self.assertEqual(sorted(groups), ["볼꾸", "젬민이"])
        self.assertEqual(len(groups["볼꾸"]["lines"]), 2)
        self.assertEqual(groups["젬민이"]["variants"], ["젬민이네"])
        self.assertEqual({u["note"] for g in groups.values() for u in g["lines"]}, {"검수 전: 카드에 들어온 문장"})
        lines = evidence(groups["볼꾸"], "요즘 볼꾸에 빠짐")  # the comment being read is not its own evidence
        self.assertEqual([u["text"] for u in lines], ["다이소에서 볼꾸 했다"])
        merged = merge_groups([{"id": "u-1", "expression": "볼꾸", "variants": [], "lines": groups["볼꾸"]["lines"][:1]}],
                              [groups["볼꾸"]])
        self.assertEqual(len(merged[0]["lines"]), 2)

    def test_the_store_feeds_collected_comments_to_the_next_card(self):
        with tempfile.TemporaryDirectory() as temp:
            cands = Path(temp) / "candidates.jsonl"
            store = LiveStore([], [], candidates_path=cands)
            self.assertEqual(store.current()[1], [])
            cands.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                     for r in (row("볼꾸", "요즘 볼꾸에 빠짐"), row("볼꾸", "다이소에서 볼꾸 했다"))),
                             encoding="utf-8")
            lexicon, usages = store.current()
            self.assertEqual([g["expression"] for g in usages], ["볼꾸"])
            client, a = card(lexicon, usages)
            item = a.run(text="볼꾸 재료 또 샀다", mode="card")["card"]["items"][0]
            self.assertEqual((item["expression"], item["decided_by"], item["mad_reason"], item["estimate"]),
                             ("볼꾸", "mad", "usages", True))
            self.assertTrue(any(r.get("stage") == "propose" and "observed_usages" in json.dumps(r, ensure_ascii=False)
                                for r in client.requests))


if __name__ == "__main__":
    unittest.main()
