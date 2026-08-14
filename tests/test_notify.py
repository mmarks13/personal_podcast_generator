#!/usr/bin/env python3
"""Offline tests for ntfy message chunking.

ntfy.sh rejects a body of 4096 bytes or more with a 500, so a long picker slate
must be split across pushes — on option boundaries, never mid-option.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import notify  # noqa: E402


def _slate(n: int, why_len: int = 260) -> str:
    """A picker slate the size of a real one — tonight's fifteen ran 4,477 bytes."""
    lines = []
    for i in range(1, n + 1):
        lines.append(f"{i}. story number {i} [4 src]")
        lines.append("   " + "w" * why_len)
    lines.append("")
    lines.append("Reply: numbers = tonight's dives (up to 3)")
    return "\n".join(lines)


class ChunkTests(unittest.TestCase):
    def test_short_message_is_one_chunk(self) -> None:
        self.assertEqual(notify.chunk("hello"), ["hello"])

    def test_every_chunk_is_under_the_limit(self) -> None:
        for part in notify.chunk(_slate(15)):
            self.assertLessEqual(len(part.encode()), notify.MAX_MESSAGE_BYTES)

    def test_a_fifteen_option_slate_splits(self) -> None:
        self.assertGreater(len(notify.chunk(_slate(15))), 1)

    def test_no_option_is_split_from_its_why_line(self) -> None:
        for part in notify.chunk(_slate(15)):
            self.assertFalse(part.split("\n")[0].startswith(" "),
                             "a chunk must not open with a continuation line")

    def test_nothing_is_lost_or_duplicated(self) -> None:
        message = _slate(15)
        self.assertEqual("\n".join(notify.chunk(message)), message)

    def test_the_footer_rides_the_last_chunk(self) -> None:
        parts = notify.chunk(_slate(15))
        self.assertIn("Reply: numbers", parts[-1])

    def test_an_oversized_single_block_is_truncated_not_dropped(self) -> None:
        parts = notify.chunk("x" * (notify.MAX_MESSAGE_BYTES + 500))
        self.assertEqual(len(parts), 1)
        self.assertEqual(len(parts[0].encode()), notify.MAX_MESSAGE_BYTES)


class SendTests(unittest.TestCase):
    def test_each_chunk_is_posted_and_numbered(self) -> None:
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                mock.patch.object(notify, "_post") as post:
            notify.send("Tonight's dives", _slate(15))
        titles = [c.args[1] for c in post.call_args_list]
        self.assertEqual(len(titles), len(notify.chunk(_slate(15))))
        self.assertTrue(all(t.startswith("Tonight's dives (") for t in titles))

    def test_a_single_chunk_keeps_the_bare_title(self) -> None:
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                mock.patch.object(notify, "_post") as post:
            notify.send("Run FAILED", "one line")
        self.assertEqual(post.call_args.args[1], "Run FAILED")

    def test_no_topic_is_a_silent_no_op(self) -> None:
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}), \
                mock.patch.object(notify, "_post") as post:
            notify.send("t", "m")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
