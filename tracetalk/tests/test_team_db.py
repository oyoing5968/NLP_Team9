"""0.7.3: the team's easy words in the DB, and the team's sheet imported in one go (all or none)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tracetalk.db import update as update_db
from tracetalk.mad.card import CardAnalyzer
from tracetalk.db.lexicon import load_lexicon
from tracetalk.db.usage import load_usages
from frontier_fixture import FixtureClient
from tracetalk.mad import card as card_module

def setUpModule():  # these tests are about the 0.7-0.8 routes, still selectable (card.CARD decide="roles", unknown="mad")
    card_module.CARD.update(decide="roles", unknown="mad", pick=False)


def tearDownModule():
    card_module.CARD.update(decide="witness", unknown="read", pick=True)


HEADER = "kind,expression,variants,meaning,easy,origin,pos,usage,context,source\n"


def quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return update_db.main(argv)


class TeamEasyTests(unittest.TestCase):
    def test_the_teams_easy_words_replace_the_models_for_the_chosen_sense(self):
        client = FixtureClient()
        client.probe = lambda p: 0.9
        rows = [{"expression": "긁히다", "senses": [{"meaning": "상대방의 말에 자극받아 발끈하다", "easy": "발끈한"}]}]
        item = CardAnalyzer(client).run(text="쟤 방금 긁힌거 같은데?", db=rows)["card"]["items"][0]
        self.assertEqual((item["easy"], item["detail"].get("easy_from")), ("발끈한", "db"))
        self.assertNotIn("easy", [r.get("stage") for r in client.requests])  # no easy step, no easy probe
        self.assertNotIn("easy_fit", [r.get("probe") for r in client.requests])
        # Without them the model's easy words go through the v9.3 check as before.
        rows[0]["senses"][0].pop("easy")
        item = CardAnalyzer(client).run(text="쟤 방금 긁힌거 같은데?", db=rows)["card"]["items"][0]
        self.assertIn("easy_fit", item["detail"])

    def test_a_team_meaning_in_live_supersedes_the_older_store_senses_of_that_word(self):
        from tracetalk.mad.card import entries_from_store
        base = [{"id": "lx-1", "expression": "마기꾼", "variants": [], "meaning": "긴 백과사전식 설명", "family": "kc:마기꾼",
                 "source": "KoCulture", "license": "CC"},
                {"id": "lx-2", "expression": "갓생", "variants": [], "meaning": "부지런한 삶", "family": "kc:갓생",
                 "source": "KoCulture", "license": "CC"}]
        live = [{"id": "live-s-1", "expression": "마기꾼", "variants": [], "meaning": "마스크를 벗으면 달라 보이는 사람",
                 "family": "live:마기꾼", "source": "팀", "license": "팀 입력", "easy": "마스크 효과 본 사람"}]
        rows = {r["expression"]: [s["meaning"] for s in r["senses"]] for r in entries_from_store(base + live, [])}
        self.assertEqual(rows, {"마기꾼": ["마스크를 벗으면 달라 보이는 사람"], "갓생": ["부지런한 삶"]})

    def test_add_entry_takes_easy_words_and_rejects_ones_that_repeat_the_expression(self):
        with tempfile.TemporaryDirectory() as live:
            quiet(["--live", live, "add-entry", "--expression", "긁히다", "--meaning", "발끈하다", "--easy", "발끈한",
                   "--source", "TEST"])
            self.assertEqual(load_lexicon(Path(live) / "entries.jsonl")[0]["easy"], "발끈한")
            with self.assertRaises(SystemExit):
                quiet(["--live", live, "add-entry", "--expression", "각", "--meaning", "그럴 것 같은 상황",
                       "--easy", "할 각", "--source", "TEST"])


class SheetTests(unittest.TestCase):
    def write(self, folder, body):
        path = Path(folder) / "sheet.csv"
        path.write_text("﻿" + HEADER + body, encoding="utf-8")  # Excel's BOM
        return path

    def test_a_good_sheet_goes_in_whole_and_a_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / "live"
            sheet = self.write(folder, "뜻,긁히다,긁힌 긁혔,상대방의 말에 자극받아 발끈하다,발끈한,긁다의 피동,동사,,,팀 회의 11-03\n"
                                       "용례,긁히다,,,,,,하 개긁힌다,,팀 회의 11-03\n\n"
                                       "usage,야르,,,,,,야르~ 오늘 치킨 미쳤다,,팀 회의 11-03\n")
            quiet(["--live", str(live), "import", str(sheet), "--dry-run"])
            self.assertFalse(live.exists() and any(live.iterdir()))
            rows = quiet(["--live", str(live), "import", str(sheet)])
            self.assertEqual(len(rows), 3)
            entry = load_lexicon(live / "entries.jsonl")[0]
            self.assertEqual((entry["expression"], entry["variants"], entry["easy"], entry["pos"]),
                             ("긁히다", ["긁힌", "긁혔"], "발끈한", "동사"))
            groups = {g["expression"]: [u["text"] for u in g["lines"]] for g in load_usages([live / "usages.jsonl"])}
            self.assertEqual(groups, {"긁히다": ["하 개긁힌다"], "야르": ["야르~ 오늘 치킨 미쳤다"]})

    def test_one_bad_line_stops_the_whole_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / "live"
            sheet = self.write(folder, "뜻,긁히다,,상대방의 말에 자극받아 발끈하다,,,,,,팀\n"
                                       "용례,야르,,,,,,오늘 치킨 미쳤다,,팀\n")  # the usage does not contain 야르
            with self.assertRaises(ValueError) as caught:
                quiet(["--live", str(live), "import", str(sheet)])
            self.assertIn("3번째 줄", str(caught.exception))
            self.assertFalse((live / "entries.jsonl").exists())
            bad_header = Path(folder) / "bad.csv"
            bad_header.write_text("expression,meaning\n긁히다,발끈\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                quiet(["--live", str(live), "import", str(bad_header)])

    def test_the_template_has_the_columns_the_importer_reads(self):
        template = Path(__file__).resolve().parents[1] / "data/db/team_db_template.csv"
        self.assertEqual(template.read_text(encoding="utf-8"), HEADER)
        self.assertEqual(tuple(HEADER.strip().split(",")), update_db.COLUMNS)


if __name__ == "__main__":
    unittest.main()
