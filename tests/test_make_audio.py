#!/usr/bin/env python3
"""Offline tests for chapter transition assembly in scripts/make_audio.py."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import make_audio as ma  # noqa: E402


class TransitionCueTests(unittest.TestCase):
    def test_cues_only_precede_nonopening_chapters(self) -> None:
        rendered = [
            (0, "opening.wav", 10.0),
            (2, "chapter.wav", 5.0),
            (4, "technical-split.wav", 3.0),
            (6, "close.wav", 2.0),
        ]
        parts, starts = ma._sequence_parts_with_cues(
            rendered, {0, 2, 6}, "cue.wav", 2.88
        )

        self.assertEqual(parts, [
            "opening.wav", "cue.wav", "chapter.wav", "technical-split.wav",
            "cue.wav", "close.wav",
        ])
        self.assertEqual(starts[0], 0.0)
        self.assertEqual(starts[2], 10.0)
        self.assertAlmostEqual(starts[4], 17.88)
        self.assertAlmostEqual(starts[6], 20.88)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_cue_converts_to_gemini_pcm_format(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            converted = os.path.join(directory, "cue.wav")
            seconds = ma._prepare_transition_cue(
                ma.TRANSITION_CUE_PATH, converted, bits=16, rate=24000
            )
            with wave.open(converted, "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertEqual(wf.getframerate(), 24000)
            self.assertAlmostEqual(seconds, 2.88, places=2)


if __name__ == "__main__":
    unittest.main()


class PronunciationTests(unittest.TestCase):
    RULES = None

    def setUp(self) -> None:
        self.rules = ma.load_pronunciations()

    def respell(self, text: str) -> str:
        return ma.apply_pronunciations([{"speaker": "A", "text": text}],
                                       self.rules)[0]["text"]

    def test_shipped_lexicon_covers_the_flagged_terms(self) -> None:
        self.assertEqual(self.respell("Qwen3-Next beat Sol on that eval."),
                         "Kwen3-Next beat Sole on that eval.")

    def test_substring_matches_are_left_alone(self) -> None:
        text = "They solved it; the solar solution was sold, so consoles stay."
        self.assertEqual(self.respell(text), text)

    def test_rewrites_only_the_turns_handed_to_the_tts(self) -> None:
        turns = [{"speaker": "A", "text": "Qwen shipped."}]
        out = ma.apply_pronunciations(turns, self.rules)
        self.assertEqual(out[0]["text"], "Kwen shipped.")
        self.assertEqual(turns[0]["text"], "Qwen shipped.")  # caller untouched

    def test_empty_lexicon_is_a_no_op(self) -> None:
        turns = [{"speaker": "A", "text": "Qwen shipped."}]
        self.assertIs(ma.apply_pronunciations(turns, []), turns)

    def test_missing_lexicon_file_is_not_fatal(self) -> None:
        self.assertEqual(ma.load_pronunciations("/nonexistent/lexicon.yaml"), [])
