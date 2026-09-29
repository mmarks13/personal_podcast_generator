#!/usr/bin/env python3
"""The listener's note may move the word band. These cases are the contract."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import note_band as nb  # noqa: E402


class BandFromNoteTests(unittest.TestCase):
    def test_a_minute_request_becomes_a_band_around_it(self) -> None:
        low, high, reduced = nb.band_from_note("Keep it to 20 minutes tonight.")
        self.assertFalse(reduced)
        # 20 min at 165 wpm is 3300 words; +/-12% around it.
        self.assertEqual((low, high), (2904, 3696))

    def test_a_word_request_is_taken_literally(self) -> None:
        low, high, _ = nb.band_from_note("note: about 2500 words is plenty")
        self.assertEqual((low, high), (2200, 2800))

    def test_a_range_is_used_as_the_band(self) -> None:
        low, high, _ = nb.band_from_note("Run 15-20 minutes.")
        self.assertEqual((low, high), (15 * nb.WPM, 20 * nb.WPM))

    def test_prose_with_no_figure_moves_nothing(self) -> None:
        self.assertIsNone(nb.band_from_note("Open cold and stay skeptical."))
        self.assertIsNone(nb.band_from_note("Make it short."))
        self.assertIsNone(nb.band_from_note(""))
        self.assertIsNone(nb.band_from_note(None))

    def test_a_segment_length_is_not_the_episode_length(self) -> None:
        # The likeliest phrasing in a real note. Clamping five minutes up to the floor
        # would turn "spend five minutes on the IPO" into a ten-minute episode.
        self.assertIsNone(nb.band_from_note("Spend 5 minutes on the IPO."))
        self.assertIsNone(nb.band_from_note("Give the Shopify story 90 seconds."))

    def test_an_oversized_request_is_reduced_and_says_so(self) -> None:
        low, high, reduced = nb.band_from_note("Give me 90 minutes on this.")
        self.assertTrue(reduced)
        self.assertEqual(high, nb.ABS_MAX_WORDS)
        # Clamping must not flatten the band into something no script can satisfy.
        self.assertGreaterEqual(high - low, nb.MIN_WIDTH)

    def test_a_request_just_over_the_floor_is_honored(self) -> None:
        low, high, reduced = nb.band_from_note("11 minutes, no more.")
        self.assertFalse(reduced)
        self.assertGreaterEqual(low, nb.ABS_MIN_WORDS)
        self.assertLess(high, 2200)

    def test_numbers_without_a_unit_are_ignored(self) -> None:
        self.assertIsNone(nb.band_from_note("Lead with the $42B loss and the 550B model."))


class PlumbingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_daily_note_is_read_out_of_the_picks_file(self) -> None:
        path = self.root / "daily_picks.json"
        path.write_text(json.dumps({"picks": [], "note": "Run 22 minutes."}))
        self.assertEqual(nb.read_note(path), "Run 22 minutes.")

    def test_a_picks_file_with_no_note_reads_empty(self) -> None:
        path = self.root / "daily_picks.json"
        path.write_text(json.dumps({"picks": [{"n": 1}], "note": None}))
        self.assertEqual(nb.read_note(path), "")

    def test_the_deepdive_note_is_read_as_plain_text(self) -> None:
        path = self.root / "deepdive_note.txt"
        path.write_text("Teach it from the hardware up.\n")
        self.assertEqual(nb.read_note(path), "Teach it from the hardware up.")

    def test_a_missing_note_file_reads_empty(self) -> None:
        self.assertEqual(nb.read_note(self.root / "nope.json"), "")
        self.assertEqual(nb.read_note(self.root / "nope.txt"), "")

    def test_stamping_records_the_direction_on_the_episode(self) -> None:
        meta = self.root / "episode_meta.json"
        meta.write_text(json.dumps({"title": "T", "summary": "S"}))
        self.assertTrue(nb.stamp(meta, "Run 20 minutes.", (2904, 3696)))
        value = json.loads(meta.read_text())
        self.assertEqual(value["listener_note"], "Run 20 minutes.")
        self.assertEqual(value["word_band"], [2904, 3696])
        self.assertEqual(value["title"], "T")  # nothing else disturbed

    def test_stamping_an_unwritten_meta_does_not_raise(self) -> None:
        self.assertFalse(nb.stamp(self.root / "missing.json", "x", None))

    def test_a_night_with_no_note_records_nulls(self) -> None:
        meta = self.root / "episode_meta.json"
        meta.write_text(json.dumps({"title": "T"}))
        nb.stamp(meta, "", None)
        value = json.loads(meta.read_text())
        self.assertIsNone(value["listener_note"])
        self.assertIsNone(value["word_band"])


if __name__ == "__main__":
    unittest.main()
