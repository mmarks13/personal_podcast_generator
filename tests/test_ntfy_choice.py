#!/usr/bin/env python3
"""Offline tests for the nightly picker's reply grammar.

One phone message answers both slates: numbers are the daily mini-dives, letters the
deep dive, bare text a mini-dive in the listener's own words, and a `dd` prefix a
deep-dive topic. These cases are the contract.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ntfy_choice as nc  # noqa: E402


class ParseReplyTests(unittest.TestCase):
    CASES = [
        # reply,                     numbers,      letters, daily text,               dd text
        ("1,3",                      [1, 3],       [],  None,                       None),
        ("1, 3",                     [1, 3],       [],  None,                       None),
        ("1 3",                      [1, 3],       [],  None,                       None),
        ("1,3 B",                    [1, 3],       [2], None,                       None),
        ("10",                       [10],         [],  None,                       None),
        ("15",                       [15],         [],  None,                       None),
        ("1,10",                     [1, 10],      [],  None,                       None),
        ("10 1",                     [10, 1],      [],  None,                       None),
        ("12,3 C",                   [12, 3],      [3], None,                       None),
        ("16",                       [],           [],  None,                       None),  # out of range
        # 2026-08-12: "3, 14. A" lost both 14 and A to the period, and the deep dive
        # silently fell back to picking its own topic. People punctuate.
        ("3, 14. A",                 [3, 14],      [1], None,                       None),
        ("3, 14, and A",             [3, 14],      [1], None,                       None),
        ("1. 2. 3.",                 [1, 2, 3],    [],  None,                       None),
        ("3; 14 · B",                [3, 14],      [2], None,                       None),
        ("A",                        [],           [1], None,                       None),
        ("A shorter show please",    [],           [],  "A shorter show please",    None),
        ("A, 3",                     [3],          [1], None,                       None),
        ("14. A",                    [14],         [1], None,                       None),
        ("3, 14. dd tokenizers",     [3, 14],      [],  None,             "tokenizers"),
        ("B",                        [],           [2], None,                       None),
        ("b",                        [],           [2], None,                       None),
        ("1,2,3,4,5",                [1,2,3,4,5],  [],  None,                       None),
        ("dive the Gemini thing",    [],           [],  "dive the Gemini thing",    None),
        ("dd speculative decoding",  [],           [],  None,     "speculative decoding"),
        ("DD: speculative decoding", [],           [],  None,     "speculative decoding"),
        ("1 dd tokenizers",          [1],          [],  None,               "tokenizers"),
        ("3 more on the export story", [3],        [],  "more on the export story", None),
        ("ok",                       [],           [],  None,                       None),
        ("",                         [],           [],  None,                       None),
        ("   ",                      [],           [],  None,                       None),
        ("dd",                       [],           [],  None,                       None),
    ]

    def test_cases(self) -> None:
        for text, numbers, letters, daily, deepdive in self.CASES:
            with self.subTest(reply=text):
                got = nc.parse_reply(text)
                self.assertEqual(got["numbers"], numbers)
                self.assertEqual(got["letters"], letters)
                self.assertEqual(got["daily_text"], daily)
                self.assertEqual(got["deepdive_text"], deepdive)


class DailyPicksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.options = os.path.join(self.tmp.name, "daily_options.json")
        self.picks = os.path.join(self.tmp.name, "daily_picks.json")
        with open(self.options, "w") as f:
            json.dump({"sent_at": 1, "options": [
                {"n": i, "label": f"story {i}", "url": f"https://x/{i}"}
                for i in range(1, 16)]}, f)

    def _run(self, reply: str | None) -> str:
        buf = io.StringIO()
        with mock.patch.object(nc, "fetch_replies", return_value=([] if reply is None else [reply])), redirect_stdout(buf):
            nc.run_daily(self.options, self.picks)
        return buf.getvalue()

    def _result(self) -> dict:
        with open(self.picks) as f:
            return json.load(f)

    def test_capped_at_three_with_the_rest_as_overflow(self) -> None:
        out = self._run("1,2,3,4")
        result = self._result()
        self.assertEqual([o["n"] for o in result["picks"]], [1, 2, 3])
        self.assertEqual([o["n"] for o in result["overflow"]], [4])
        self.assertIsNone(result["free_text"])
        self.assertIn("#1 story 1", out)

    def test_dedups_and_keeps_reply_order(self) -> None:
        self._run("3,1,3")
        self.assertEqual([o["n"] for o in self._result()["picks"]], [3, 1])

    def test_free_text_is_a_locked_dive(self) -> None:
        self._run("dive the Gemini pricing thing")
        result = self._result()
        self.assertEqual(result["picks"], [])
        self.assertEqual(result["free_text"], "dive the Gemini pricing thing")

    def test_no_reply_writes_nothing(self) -> None:
        self.assertEqual(self._run(None), "")
        self.assertFalse(os.path.exists(self.picks))

    def test_a_deepdive_only_reply_is_not_a_daily_pick(self) -> None:
        self._run("dd tokenizers")
        self.assertFalse(os.path.exists(self.picks))

    def test_unknown_option_numbers_are_dropped(self) -> None:
        with open(self.options, "w") as f:
            json.dump({"sent_at": 1, "options": [{"n": 1, "label": "only one"}]}, f)
        self._run("1,4")
        self.assertEqual([o["n"] for o in self._result()["picks"]], [1])

    def test_the_last_option_is_reachable(self) -> None:
        self._run("15,2")
        self.assertEqual([o["n"] for o in self._result()["picks"]], [15, 2])

    def test_daily_dives_env_overrides_the_phone(self) -> None:
        boom = mock.Mock(side_effect=AssertionError("must not poll when overridden"))
        with mock.patch.dict(os.environ, {"DAILY_DIVES": "2"}), \
                mock.patch.object(nc, "fetch_replies", boom), redirect_stdout(io.StringIO()):
            nc.run_daily(self.options, self.picks)
        self.assertEqual([o["n"] for o in self._result()["picks"]], [2])


class SplitReplyTests(unittest.TestCase):
    """A wide slate arrives as two pushes, so answering each one separately must work."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.daily = os.path.join(self.tmp.name, "daily_options.json")
        self.picks = os.path.join(self.tmp.name, "daily_picks.json")
        self.dive = os.path.join(self.tmp.name, "deepdive_options.json")
        with open(self.daily, "w") as f:
            json.dump({"sent_at": 1, "options": [
                {"n": i, "label": f"story {i}"} for i in range(1, 16)]}, f)
        with open(self.dive, "w") as f:
            json.dump({"sent_at": 1, "options": [
                {"n": 1, "topic": "alpha"}, {"n": 2, "topic": "beta"}]}, f)

    def _both(self, replies: list[str]) -> tuple[list, str]:
        with mock.patch.object(nc, "fetch_replies", return_value=replies):
            with redirect_stdout(io.StringIO()):
                nc.run_daily(self.daily, self.picks)
            buf = io.StringIO()
            with redirect_stdout(buf):
                nc.run_deepdive(self.dive)
        picks = []
        if os.path.exists(self.picks):
            with open(self.picks) as f:
                picks = [o["n"] for o in json.load(f)["picks"]]
        return picks, buf.getvalue().strip()

    def test_two_messages_both_land(self) -> None:
        self.assertEqual(self._both(["3,14", "A"]), ([3, 14], "alpha"))

    def test_order_does_not_matter(self) -> None:
        self.assertEqual(self._both(["A", "3,14"]), ([3, 14], "alpha"))

    def test_a_later_message_corrects_only_its_own_half(self) -> None:
        self.assertEqual(self._both(["3,14", "A", "3,15"]), ([3, 15], "alpha"))

    def test_a_later_letter_corrects_the_dive_only(self) -> None:
        self.assertEqual(self._both(["3,14 A", "B"]), ([3, 14], "beta"))

    def test_one_combined_reply_still_works(self) -> None:
        self.assertEqual(self._both(["3, 14. A"]), ([3, 14], "alpha"))


class DeepdiveChoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.options = os.path.join(self.tmp.name, "deepdive_options.json")
        with open(self.options, "w") as f:
            json.dump({"sent_at": 1, "options": [
                {"n": 1, "topic": "alpha"}, {"n": 2, "topic": "beta"}]}, f)

    def _run(self, reply: str | None) -> str:
        buf = io.StringIO()
        with mock.patch.object(nc, "fetch_replies", return_value=([] if reply is None else [reply])), redirect_stdout(buf):
            nc.run_deepdive(self.options)
        return buf.getvalue().strip()

    def test_letters_map_to_topics(self) -> None:
        self.assertEqual(self._run("1,3 B"), "beta")

    def test_numbers_never_pick_a_deepdive_topic(self) -> None:
        self.assertEqual(self._run("1,2"), "")

    def test_free_text_needs_the_dd_prefix(self) -> None:
        self.assertEqual(self._run("dive the Gemini thing"), "")
        self.assertEqual(self._run("dd the Gemini thing"), "the Gemini thing")


class FetchRepliesTests(unittest.TestCase):
    def test_skips_bot_messages_and_keeps_all_replies_in_order(self) -> None:
        payload = "\n".join(json.dumps(m) for m in [
            {"event": "message", "time": 10, "tags": ["bot"], "message": "the push"},
            {"event": "message", "time": 11, "message": "1"},
            {"event": "message", "time": 12, "message": "1,3"},
            {"event": "keepalive", "time": 13},
        ]).encode()

        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                mock.patch.object(nc.urllib.request, "urlopen", return_value=resp):
            self.assertEqual(nc.fetch_replies(5), ["1", "1,3"])

    def test_messages_older_than_the_push_are_ignored(self) -> None:
        payload = json.dumps({"event": "message", "time": 3, "message": "1,3"}).encode()
        resp = mock.MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                mock.patch.object(nc.urllib.request, "urlopen", return_value=resp):
            self.assertEqual(nc.fetch_replies(5), [])

    def test_a_dead_channel_never_raises(self) -> None:
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                mock.patch.object(nc.urllib.request, "urlopen",
                                  side_effect=OSError("no route to host")):
            self.assertEqual(nc.fetch_replies(5), [])

    def test_no_topic_configured(self) -> None:
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}):
            self.assertEqual(nc.fetch_replies(5), [])


if __name__ == "__main__":
    unittest.main()
