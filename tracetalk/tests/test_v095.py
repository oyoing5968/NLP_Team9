"""v9.5 (11-04): teacher-drafted easy words for DB senses (marked, team words win), estimates on the card, the
system never swapping a dictionary-form verb into an inflected slot, and the gate options."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracetalk.mad.card import CardAnalyzer, sentence_problems, slot_fits
from tracetalk.db.lexicon import load_easy_drafts, meaning_sha, with_easy_drafts
from tracetalk.db.usage import LiveStore
from frontier_fixture import FixtureClient
from tracetalk.mad import card as card_module

def setUpModule():  # these tests are about the 0.7-0.8 routes, still selectable (card.CARD decide="roles", unknown="mad")
    card_module.CARD.update(decide="roles", unknown="mad", pick=False)


def tearDownModule():
    card_module.CARD.update(decide="witness", unknown="read", pick=True)


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

ENTRY = {"id": "lx-1", "expression": "긁히다", "variants": [], "meaning": "상대의 말에 자극받아 발끈하다",
         "family": "kc:긁히다", "source": "test", "license": "test"}


def draft_row(entry, easy, meaning=None):
    return {"entry_id": entry["id"], "expression": entry["expression"],
            "meaning_sha": meaning_sha(meaning or entry["meaning"]), "easy": easy, "source": "TEST 교사 초안",
            "model": "TEST-FIXTURE-NOT-A-MODEL", "made_at": "2026-11-04"}


def write(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


class DraftOverlayTests(unittest.TestCase):
    def test_drafts_fill_only_empty_easy_words_for_the_current_meaning(self):
        team = {**ENTRY, "id": "lx-2", "easy": "팀 쉬운 말"}
        stale = {**ENTRY, "id": "lx-3", "meaning": "바뀐 뜻풀이"}
        drafts = {r["entry_id"]: r for r in (draft_row(ENTRY, "발끈하다"), draft_row(team, "초안"),
                                             draft_row(stale, "옛 초안", meaning="예전 뜻풀이"))}
        out, used, old = with_easy_drafts([ENTRY, team, stale], drafts)
        self.assertEqual((used, old), (1, 1))
        self.assertEqual(with_easy_drafts([ENTRY], {"lx-1": {**draft_row(ENTRY, "발끈하다"), "slot": "서술어"}})[0][0]["easy_slot"], "서술어")
        self.assertEqual((out[0]["easy"], out[0]["easy_source"]), ("발끈하다", "draft"))
        self.assertEqual((out[1]["easy"], out[1].get("easy_source")), ("팀 쉬운 말", None))
        self.assertNotIn("easy", out[2])
        self.assertNotIn("easy", ENTRY)  # the lexicon itself is never changed

    def test_draft_files_are_checked_and_failed_drafts_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "d.jsonl"
            write(path, [draft_row(ENTRY, "발끈하다"), {**draft_row({**ENTRY, "id": "lx-9"}, ""), "error": "TEST"}])
            self.assertEqual(list(load_easy_drafts([path])), ["lx-1"])
            write(path, [{**draft_row(ENTRY, "발끈하다"), "extra": 1}])
            with self.assertRaises(ValueError):
                load_easy_drafts([path])
            write(path, [draft_row(ENTRY, "a"), draft_row(ENTRY, "b")])
            with self.assertRaises(ValueError):
                load_easy_drafts([path])

    def test_the_live_store_rereads_drafts(self):
        with tempfile.TemporaryDirectory() as temp:
            lex, drafts = Path(temp) / "lex.jsonl", Path(temp) / "d.jsonl"
            write(lex, [ENTRY])
            store = LiveStore([lex], [], [drafts])
            self.assertNotIn("easy", store.current()[0][0])
            write(drafts, [draft_row(ENTRY, "발끈하다")])
            self.assertEqual(store.current()[0][0]["easy"], "발끈하다")


class CardTests(unittest.TestCase):
    def test_a_drafted_easy_word_is_used_and_marked_and_db_meanings_are_not_estimates(self):
        client = FixtureClient()
        client.probe = lambda p: 0.9
        lexicon, _, _ = with_easy_drafts([ENTRY], {"lx-1": draft_row(ENTRY, "발끈하다")})
        item = CardAnalyzer(client, lexicon=lexicon).run(text="쟤 방금 긁힌거 같은데?")["card"]["items"][0]
        self.assertEqual((item["easy"], item["easy_source"], item["detail"].get("easy_from")),
                         ("발끈하다", "draft", "draft"))
        self.assertFalse(item["estimate"])
        self.assertNotIn("easy", [r.get("stage") for r in client.requests])  # no easy rewrite, no easy probe
        self.assertNotIn("easy_fit", [r.get("probe") for r in client.requests])

    def test_a_word_without_a_db_sense_is_an_estimate_with_the_models_easy_words(self):
        client = FixtureClient()
        client.detect = lambda text: ["야르"]
        item = CardAnalyzer(client).run(text="야르~ 맛있다")["card"]["items"][0]
        self.assertEqual((item["basis"], item["estimate"], item["easy_source"]), ("model", True, "model"))

    def test_a_guess_without_evidence_stays_as_written_in_the_sentence(self):
        client = FixtureClient()
        client.probe = lambda p: 0.9
        client.detect = lambda text: ["야르"]
        lexicon, _, _ = with_easy_drafts([ENTRY], {"lx-1": draft_row(ENTRY, "발끈한")})
        text = "야르~ 쟤 방금 긁힌거 같은데?"
        card = CardAnalyzer(client, lexicon=lexicon).run(text=text)["card"]
        self.assertEqual((card["kept_estimates"], card["sentence"]), (["야르"], "야르~ 쟤 방금 발끈한거 같은데?"))
        asked = [r for r in client.requests if r.get("stage") == "sentence"][0]["unverified_hypotheses"]
        self.assertEqual((asked["keep"], [r["expression"] for r in asked["replace"]]), (["야르"], ["긁힌"]))
        self.assertNotIn("slot", asked["replace"][0])  # a draft without a slot (v1 file) sends none
        self.assertNotIn("야르", [i["expression"] for i in asked["items"]])
        guess = next(i for i in card["items"] if i["expression"] == "야르")
        self.assertEqual((guess["basis"], guess["estimate"], guess["status"]), ("model", True, "proposed"))
        self.assertTrue(sentence_problems(text, "와~ 쟤 방금 발끈한거 같은데?", card["items"]))  # the guess was swapped
        self.assertFalse(sentence_problems(text, "야르~ 쟤 방금 발끈한거 같은데?", card["items"]))

    def test_the_system_does_not_swap_a_dictionary_form_into_an_inflected_slot(self):
        self.assertFalse(slot_fits("긁힌", "발끈하다"))
        self.assertTrue(slot_fits("긁힌", "발끈한"))
        self.assertTrue(slot_fits("마렵다", "하고 싶다"))
        # v9.6: a drafted slot decides; a predicate goes in only where the comment has the dictionary form
        self.assertFalse(slot_fits("돋네", "소름 돋다", "서술어"))
        self.assertTrue(slot_fits("마렵다", "하고 싶다", "서술어"))
        self.assertTrue(slot_fits("역대급", "엄청난", "꾸밈말"))
        self.assertTrue(slot_fits("경찰서 정모", "단체 경찰서행", "명사"))
        client = FixtureClient()
        client.probe = lambda p: 0.9
        client.hook = None
        lexicon, _, _ = with_easy_drafts([ENTRY], {"lx-1": draft_row(ENTRY, "발끈하다")})
        a = CardAnalyzer(client, lexicon=lexicon)
        original = client.generate

        def keep_expression(messages, schema, seed, max_tokens):  # the model keeps 긁힌 twice
            out = original(messages, schema, seed, max_tokens)
            if "sentence" in schema["properties"]:
                out = {**out, "raw": json.dumps({"sentence": json.loads(messages[-1]["content"])["original_text"]},
                                                ensure_ascii=False)}
            return out
        client.generate = keep_expression
        card = a.run(text="쟤 방금 긁힌거 같은데?")["card"]
        self.assertIsNone(card["sentence"])  # not "쟤 방금 발끈하다거 같은데?"
        self.assertTrue(card["sentence_problems"])
        self.assertTrue(sentence_problems("쟤 방금 긁힌거 같은데?", "쟤 방금 긁힌거 같은데?", card["items"]))


class TeacherFixture:
    """TEST-FIXTURE-NOT-A-MODEL: drafts '고친 쉬운 말' (명사) for every word but '고친', whose draft repeats the word;
    as the reviewer it files 같은 뜻, or `verdict` (twice) for words in `reject` (r2: classes, not yes/no)."""
    def __init__(self, reject=(), verdict="다른 뜻"):
        self.reject, self.verdict, self.calls = set(reject), verdict, []

    def health(self):
        return {"ready": True}

    def generate(self, messages, schema, seed, max_tokens):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        if "meaning" in schema["properties"]:
            bad = payload["expression"] in self.reject
            data = {"meaning": self.verdict if bad else "같은 뜻", "problem": "TEST 뜻과 다름" if bad else ""}
        else:
            data = {"slot": "명사", "easy": "고친 쉬운 말" if payload["expression"] != "고친" else "고친 말"}
        return {"raw": json.dumps(data, ensure_ascii=False), "finish_reason": "stop"}


class DraftScriptTests(unittest.TestCase):
    def run_draft(self, argv, teacher=None):
        import draft_easy
        teacher = teacher or TeacherFixture()
        with patch.object(draft_easy, "make_client", lambda config: teacher), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = draft_easy.main(argv)
        return code, out.getvalue()

    def test_a_draft_the_reviewer_rejects_is_rewritten_once_with_the_reason_then_left_out(self):
        with tempfile.TemporaryDirectory() as temp:
            lex, out = Path(temp) / "lex.jsonl", Path(temp) / "d.jsonl"
            write(lex, [ENTRY, {**ENTRY, "id": "lx-2", "expression": "갓겜"}])
            teacher = TeacherFixture(reject={"갓겜"})
            self.run_draft(["--model", "TEST", "--lexicon", str(lex), "--out", str(out), "--workers", "1"], teacher)
            rows = {r["entry_id"]: r for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
        self.assertEqual((rows["lx-1"]["easy"], rows["lx-1"]["slot"], rows["lx-1"]["review"]), ("고친 쉬운 말", "명사", "같은 뜻"))
        self.assertEqual((rows["lx-2"]["easy"], rows["lx-2"]["error"]), ("", "검토(다른 뜻): TEST 뜻과 다름"))
        rewrites = [c for c in teacher.calls if c["expression"] == "갓겜" and "previous" in c]
        self.assertEqual([c["previous"] for c in rewrites],  # once, with the rejected draft and the reason
                         [{"easy": "고친 쉬운 말", "problem": "검토(다른 뜻): TEST 뜻과 다름"}])
        self.assertEqual([t["review"]["meaning"] for t in rows["lx-2"]["tries"]], ["다른 뜻", "다른 뜻"])

    def test_drafts_are_written_to_their_own_file_with_their_meaning(self):
        with tempfile.TemporaryDirectory() as temp:
            lex, out = Path(temp) / "lex.jsonl", Path(temp) / "d.jsonl"
            bad = {**ENTRY, "id": "lx-2", "expression": "고친"}
            team = {**ENTRY, "id": "lx-3", "easy": "팀 쉬운 말"}
            write(lex, [ENTRY, bad, team])
            code, printed = self.run_draft(["--model", "TEST", "--lexicon", str(lex), "--out", str(out)])
            self.assertEqual(code, 0)
            rows = [json.loads(s) for s in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["entry_id"] for r in rows], ["lx-1", "lx-2"])  # the team's word is not redrafted
            self.assertEqual((rows[0]["easy"], rows[0]["meaning_sha"]), ("고친 쉬운 말", meaning_sha(ENTRY["meaning"])))
            self.assertEqual(rows[1]["easy"], "")
            self.assertIn("error", rows[1])
            self.assertIn("초안 1/2", printed)
            self.assertEqual(list(load_easy_drafts([out])), ["lx-1"])
            with self.assertRaises(SystemExit):  # never overwritten
                self.run_draft(["--model", "TEST", "--lexicon", str(lex), "--out", str(out)])
            other = Path(temp) / "other.jsonl"  # one id, two contents: stops
            write(other, [{**ENTRY, "meaning": "다른 뜻풀이"}])
            with self.assertRaises(SystemExit):
                self.run_draft(["--model", "TEST", "--lexicon", str(lex), str(other), "--out", str(Path(temp) / "o.jsonl")])
            with self.assertRaises(SystemExit):  # KoNeoBench is evaluation only
                self.run_draft(["--model", "TEST", "--lexicon", str(Path(temp) / "k1_koneo.jsonl"),
                                "--out", str(Path(temp) / "k.jsonl")])


    def test_the_real_validation_and_demo_lexicons_are_drafted_once_each(self):
        # 11-04: the chain's own pair of lexicons failed on their shared ids; the demo one holds the 389 as they are
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "d.jsonl"
            code, printed = self.run_draft(["--model", "TEST", "--lexicon", str(root / "data/db/lexicon/lexicon_eval_v1.jsonl"),
                                            str(root / "data/db/lexicon/lexicon_demo_v1.jsonl"), "--out", str(out)])
            plan = json.loads(printed.splitlines()[0])
            self.assertEqual((code, plan["entries"], plan["same_entry_merged"], plan["to_draft"]), (0, 495, 389, 495))
            drafts = load_easy_drafts([out])
            self.assertEqual(len(drafts), 495)
            for name in ("lexicon_eval_v1", "lexicon_teacher_v1"):  # validation (v9.5) and train (student v2) DBs
                lexicon = [json.loads(s) for s in (root / f"data/db/lexicon/{name}.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(with_easy_drafts(lexicon, drafts)[1:], (len(lexicon), 0))


class DraftSlotTests(unittest.TestCase):
    """v9.6 drafts: the form follows the slot the teacher names (not the spelling: 1104d failed 43 predicates such as
    돋네), and the teacher's own check sentence on an example."""

    def check(self, expression, slot, easy, check=None, example=None):
        import draft_easy
        data = {"slot": slot, "easy": easy, **({"check": check} if check is not None else {})}
        return draft_easy.check(expression, json.dumps(data, ensure_ascii=False), example)

    def test_the_form_follows_the_slot(self):
        self.assertEqual(self.check("역대급", "꾸밈말", "엄청난"), ("엄청난", "꾸밈말", ""))
        self.assertEqual(self.check("돋네", "서술어", "소름 돋다"), ("소름 돋다", "서술어", ""))  # a predicate not spelled '-다'
        self.assertEqual(self.check("꿀팁", "명사", "유용한 정보"), ("유용한 정보", "명사", ""))
        for easy in ("아주 재미있는", "최고의", "멋진", "귀여운", "힘든", "다른", "솔직히", "조금씩"):  # r2: adverbs too
            self.assertEqual(self.check("꿀잼", "꾸밈말", easy)[0], easy)
        # r2: an exclamation may end in '-다'; a whole line keeps its own ending
        self.assertEqual(self.check("무야호", "감탄", "신난다")[0], "신난다")
        self.assertEqual(self.check("너 뭐 됨?", "문장", "네가 뭔데?")[0], "네가 뭔데?")
        for expression, slot, easy in (("역대급", "꾸밈말", "가장 뛰어난 수준이다"), ("경찰서 정모", "명사", "다 같이 잡히다"),
                                       ("돋네", "서술어", "소름 돋는")):
            with self.assertRaises(ValueError):
                self.check(expression, slot, easy)
        with self.assertRaisesRegex(ValueError, "12자 이내"):  # the limit is given as a number
            self.check("꿀팁", "명사", "아주 쓸모 있고 유용한 생활 정보")

    def test_with_examples_the_check_sentence_must_hold_the_easy_words_and_not_the_word(self):
        ex = "와 역대급 택시 대란이네"
        ok = lambda easy, check: self.check("역대급", "꾸밈말", easy, check, ex)
        self.assertEqual(ok("엄청난", "와 엄청난 택시 대란이네"), ("엄청난", "꾸밈말", "와 엄청난 택시 대란이네"))
        self.assertEqual(self.check("긁히다", "서술어", "발끈하다", "하 개발끈한다", "하 개긁힌다")[0], "발끈하다")
        for check in ("와 택시 대란이네", "와 역대급 엄청난 택시 대란이네", "엄청난", ex):
            with self.assertRaises(ValueError):
                ok("엄청난", check)
        # r2: a conjugated predicate may spell the word again (소름 돋다 -> 소름 돋네); the word left behind still fails
        self.assertEqual(self.check("돋네", "서술어", "소름 돋다", "와 소름 돋네 ㄷㄷ", "와 돋네 ㄷㄷ")[2], "와 소름 돋네 ㄷㄷ")
        with self.assertRaises(ValueError):
            self.check("돋네", "서술어", "소름 돋다", "와 돋네 소름 돋다 ㄷㄷ", "와 돋네 ㄷㄷ")
        with self.assertRaises(ValueError):  # with an example the check sentence is required
            self.check("역대급", "꾸밈말", "엄청난", None, ex)

    def test_example_lines_reach_the_teacher_and_the_check_is_kept_in_the_draft(self):
        import draft_easy
        seen, review = [], []

        class Teacher:
            def health(self):
                return {"ready": True}

            def generate(self, messages, schema, seed, max_tokens):
                payload = json.loads(messages[-1]["content"])
                if "meaning" in schema["properties"]:
                    review.append(sorted(schema["properties"]))
                    data = {"meaning": "좁거나 뉘앙스가 빠짐", "problem": "",
                            **({"sentence": "자연스러움"} if "sentence" in schema["properties"] else {})}
                    return {"raw": json.dumps(data, ensure_ascii=False), "finish_reason": "stop"}
                seen.append(payload)
                data = {"slot": "꾸밈말", "easy": "엄청난"}
                if "check" in schema["properties"]:
                    data["check"] = payload["usage_examples"][0].replace(payload["expression"], "엄청난")
                return {"raw": json.dumps(data, ensure_ascii=False), "finish_reason": "stop"}
        word = {**ENTRY, "id": "lx-7", "expression": "역대급", "meaning": "역대 최고 수준"}
        with tempfile.TemporaryDirectory() as temp:
            lex, exs, out = Path(temp) / "lex.jsonl", Path(temp) / "ex.jsonl", Path(temp) / "d.jsonl"
            write(lex, [word, {**word, "id": "lx-8", "expression": "갓겜"}])
            write(exs, [{"entry_id": "lx-7", "expression": "역대급", "lines": ["와 역대급 택시 대란이네", "역대급 더위", "b", "c"],
                         "source": "TEST", "license": "test", "note": "TEST"}])
            with patch.object(draft_easy, "make_client", lambda config: Teacher()), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                draft_easy.main(["--model", "TEST", "--lexicon", str(lex), "--examples", str(exs), "--out", str(out),
                                 "--workers", "1"])
            rows = {r["entry_id"]: r for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
            self.assertEqual(len(load_easy_drafts([out])), 2)  # check is an allowed field
        self.assertEqual(seen[0]["usage_examples"], ["와 역대급 택시 대란이네", "역대급 더위", "b"])  # three at most
        self.assertNotIn("usage_examples", seen[1])
        self.assertEqual((rows["lx-7"]["check"], "check" in rows["lx-8"], rows["lx-7"]["slot"]), ("와 엄청난 택시 대란이네", False, "꾸밈말"))
        # r2: with a check sentence the reviewer also files the sentence; a narrow word is kept and marked
        self.assertEqual(review, [["meaning", "problem", "sentence"], ["meaning", "problem"]])
        self.assertEqual(rows["lx-7"]["review"], "좁거나 뉘앙스가 빠짐")
        self.assertIn("예시 용례를 본 항목 1", printed.getvalue())
        self.assertIn("예시 용례", rows["lx-7"]["source"])


class BenchOptionTests(unittest.TestCase):
    def test_stratum_gate_and_easy_draft_counts_in_the_plan(self):
        import run_bench
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            drafts = Path(temp) / "d.jsonl"
            lexicon = [json.loads(s) for s in (root / "data/db/lexicon/lexicon_eval_v1.jsonl").read_text(encoding="utf-8").splitlines()]
            write(drafts, [draft_row(lexicon[0], "TEST 쉬운 말")])
            argv = ["prog", "--model", "TEST", "--plan-only", "--inputs", str(root / "data/eval/eval_v1/val_inputs.jsonl"),
                    "--methods", "card", "--lexicon", str(root / "data/db/lexicon/lexicon_eval_v1.jsonl"),
                    "--easy-draft", str(drafts), "--stratum", "registered",
                    "--gold", str(root / "data/eval/eval_v1/val_gold.jsonl"), "--output", str(Path(temp) / "o.jsonl")]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as out:
                run_bench.main()
        plan = json.loads(out.getvalue())
        self.assertEqual((plan["cases"], plan["easy_draft_used"], plan["easy_draft_stale"], plan["strata"]),
                         (34, 1, 0, ["registered"]))


if __name__ == "__main__":
    unittest.main()


class CardSftExportTests(unittest.TestCase):
    """Student v2 data: only cards the judge passed whole, only the outputs the card kept, train split only."""

    def card(self, text, probe=0.9, first_sentence_keeps=False):
        client = FixtureClient()
        client.probe = lambda p: probe if p["probe"] == "sense" else 0.9
        if first_sentence_keeps:
            original, seen = client.generate, []

            def generate(messages, schema, seed, max_tokens):
                out = original(messages, schema, seed, max_tokens)
                if "sentence" in schema["properties"] and not seen:
                    seen.append(1)  # the first attempt keeps the expression: rejected by the checks
                    out = {**out, "raw": json.dumps({"sentence": json.loads(messages[-1]["content"])["original_text"]},
                                                    ensure_ascii=False)}
                return out
            client.generate = generate
        return CardAnalyzer(client, lexicon=[ENTRY]).run(text=text, mode="card")

    def export(self, records, graded, temp):
        import export_sft_card
        from tracetalk.mad.benchmark import record_for
        runs, grades, gold, out = (Path(temp) / n for n in ("runs.jsonl", "graded.jsonl", "gold.jsonl", "sft"))
        write(runs, [record_for(case, 42, "card", result) for case, result in records])
        write(grades, graded)
        write(gold, [{"case_id": c["id"], "family": c["family"], "stratum": "train"} for c, _ in records])
        with contextlib.redirect_stdout(io.StringIO()):
            stats = export_sft_card.main(["--runs", str(runs), "--graded", str(grades), "--gold", str(gold),
                                          "--out", str(out), "--val-share", "0"])
        rows = [json.loads(s) for s in (out / "sft_train.jsonl").read_text(encoding="utf-8").splitlines()]
        return stats, rows

    def grade(self, case, result, verdict="correct", sentence="yes"):
        return {"case_id": case["id"], "seed": 42, "method": "card", "model": result["model_config"]["model"],
                "verdict": verdict, "sentence": sentence}

    def test_only_whole_passes_and_only_kept_outputs_are_exported(self):
        good = ({"id": "kt-1", "family": "kc:긁히다", "split": "train", "text": "쟤 방금 긁힌거 같은데?"},
                self.card("쟤 방금 긁힌거 같은데?", first_sentence_keeps=True))
        mad = ({"id": "kt-2", "family": "kc:긁히다", "split": "train", "text": "하 또 긁혔네"},
               self.card("하 또 긁혔네", probe=0.4))
        bad = ({"id": "kt-3", "family": "kc:긁히다", "split": "train", "text": "긁힌 듯"}, self.card("긁힌 듯"))
        self.assertEqual(good[1]["card"]["sentence_by"], "model")
        self.assertEqual(mad[1]["card"]["items"][0]["decided_by"], "mad")
        with tempfile.TemporaryDirectory() as temp:
            stats, rows = self.export([good, mad, bad], [self.grade(*good), self.grade(*mad),
                                                         self.grade(*bad, sentence="no")], temp)
        self.assertEqual((stats["cards"], stats["cards_accepted"]), (3, 2))
        self.assertEqual((stats["sentence"], stats["judge"], stats["judge_extra"], stats["propose"]), (2, 1, 1, 2))
        sentences = [json.loads(r["messages"][-1]["content"])["sentence"] for r in rows if r["meta"]["stage"] == "sentence"]
        self.assertIn(good[1]["card"]["sentence"], sentences)
        self.assertNotIn(good[0]["text"], sentences)  # the rejected first attempt stays out
        self.assertTrue(all(r["messages"][-1]["role"] == "assistant" and r["meta"]["case_id"] != "kt-3" for r in rows))
        self.assertFalse([r for r in rows if r["meta"]["stage"] == "probe"])

    def test_records_outside_the_train_split_are_refused(self):
        case = {"id": "kc-1", "family": "kc:긁히다", "split": "validation", "text": "쟤 방금 긁힌거 같은데?"}
        result = self.card(case["text"])
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            self.export([(case, result)], [self.grade(case, result)], temp)
