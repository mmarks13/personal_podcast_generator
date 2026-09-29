#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import proposal_ledger as pl  # noqa: E402


class ProposalLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "deepdive_proposals.json"
        self.options = self.root / "deepdive_options.json"

    def write_ledger(self, topics: list[dict]) -> None:
        self.ledger.write_text(json.dumps({"topics": topics}))

    def write_options(self, options: list[dict]) -> None:
        self.options.write_text(json.dumps({"gather_id": "sha256:x", "options": options}))

    def record(self) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            pl.record(str(self.options), str(self.ledger))
        return buf.getvalue()

    def kept(self) -> list[dict]:
        return json.loads(self.options.read_text())["options"]

    def entry(self, topic: str) -> dict:
        topics = json.loads(self.ledger.read_text())["topics"]
        return next(t for t in topics if pl._norm(t["topic"]) == pl._norm(topic))

    def test_an_already_chosen_topic_leaves_the_slate(self) -> None:
        # 2026-07-11 taught mixture-of-experts and it was pitched three more times:
        # nothing filtered a topic that had already been an episode.
        self.write_ledger([
            {"topic": "Mixture of Experts, taught properly", "type": "foundational",
             "first_proposed": "2026-07-25", "last_proposed": "2026-09-25",
             "times_proposed": 2, "chosen": "2026-07-11"},
        ])
        self.write_options([
            {"n": 1, "type": "foundational", "topic": "Mixture of Experts, taught properly",
             "pitch": "what a router decides"},
            {"n": 2, "type": "mechanism", "topic": "Delta-rule linear attention", "pitch": "p"},
        ])
        out = self.record()
        self.assertEqual([o["topic"] for o in self.kept()], ["Delta-rule linear attention"])
        self.assertNotIn("Mixture of Experts", out)
        # Survivors renumber so the phone letters stay contiguous.
        self.assertEqual([o["n"] for o in self.kept()], [1])
        self.assertIn("A.", out)
        # A filtered topic is not re-counted as pitched again.
        self.assertEqual(self.entry("Mixture of Experts, taught properly")["times_proposed"], 2)

    def test_a_retired_topic_still_leaves_the_slate(self) -> None:
        self.write_ledger([
            {"topic": "Declined thrice", "type": "history", "first_proposed": "2026-08-01",
             "last_proposed": "2026-09-01", "times_proposed": 3, "chosen": None},
        ])
        self.write_options([{"n": 1, "type": "history", "topic": "Declined thrice", "pitch": "p"}])
        self.assertEqual(self.record(), "")
        self.assertEqual(self.kept(), [])

    def test_a_surviving_topic_is_counted_and_dated(self) -> None:
        self.write_ledger([])
        self.write_options([{"n": 1, "type": "foundational", "topic": "Fresh topic", "pitch": "p"}])
        self.record()
        e = self.entry("Fresh topic")
        self.assertEqual(e["times_proposed"], 1)
        self.assertEqual(e["chosen"], None)
        self.assertEqual(e["type"], "foundational")

    def test_choose_marks_the_pitched_entry(self) -> None:
        self.write_ledger([
            {"topic": "Calibration, properly taught", "type": "foundational",
             "first_proposed": "2026-09-23", "last_proposed": "2026-09-23",
             "times_proposed": 1, "chosen": None},
        ])
        pl.choose("calibration properly taught!", str(self.ledger))  # normalization applies
        self.assertIsNotNone(self.entry("Calibration, properly taught")["chosen"])
        self.assertEqual(len(json.loads(self.ledger.read_text())["topics"]), 1)

    def test_choose_records_a_topic_the_ledger_never_pitched(self) -> None:
        # The writer picks its own topic when no phone reply arrives; before this was
        # recorded, that topic stayed eligible for every later slate.
        self.write_ledger([])
        pl.choose("The two numbers on every model card", str(self.ledger))
        e = self.entry("The two numbers on every model card")
        self.assertIsNotNone(e["chosen"])
        self.assertEqual(e["times_proposed"], 0)

    def test_a_recorded_topic_cannot_come_back(self) -> None:
        # The end-to-end guarantee: what airs tonight is off tomorrow's slate.
        self.write_ledger([])
        self.write_options([{"n": 1, "type": "mechanism", "topic": "Proof search", "pitch": "p"}])
        self.record()
        pl.choose("Proof search", str(self.ledger))
        self.write_options([{"n": 1, "type": "mechanism", "topic": "Proof search", "pitch": "p"}])
        self.assertEqual(self.record(), "")
        self.assertEqual(self.kept(), [])


if __name__ == "__main__":
    unittest.main()
