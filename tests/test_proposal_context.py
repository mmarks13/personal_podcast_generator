#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import proposal_context  # noqa: E402


class ProposalContextTests(unittest.TestCase):
    def test_uses_head_of_history_and_newest_daily_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            archive = root / "archive"
            archive.mkdir()
            history.write_text(json.dumps({"episodes": [
                {"date": "2026-09-10", "title": "Newest", "dives": [{"story": "A"}]},
                {"date": "2026-08-01", "title": "Oldest", "dives": [{"story": "B"}]},
            ]}))
            (archive / "2026-09-09-meta.json").write_text(json.dumps({
                "date": "2026-09-09", "sources": [{"title": "Nine", "url": "https://x/9"}],
            }))
            (archive / "2026-09-10-meta.json").write_text(json.dumps({
                "date": "2026-09-10", "sources": [{"title": "Ten", "url": "https://x/10"}],
            }))
            (archive / "2026-09-11-deepdive-meta.json").write_text(json.dumps({
                "date": "2026-09-11", "sources": [{"title": "Ignore", "url": "https://x/dd"}],
            }))

            value = proposal_context.build(history, archive, episode_count=1, archive_count=1)

            self.assertEqual(value["recent_episodes_newest_first"][0]["title"], "Newest")
            self.assertEqual(value["recent_rundown_sources_newest_first"][0]["date"], "2026-09-10")
            self.assertEqual(value["recent_rundown_sources_newest_first"][0]["sources"][0]["title"], "Ten")

    def test_projects_only_current_candidates_blocked_by_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.json"
            archive = root / "archive"
            ledger = root / "ledger.json"
            candidates = root / "candidates.json"
            archive.mkdir()
            history.write_text('{"episodes": []}')
            ledger.write_text(json.dumps({"stories": [{
                "url": "https://example.com/heard",
                "label": "Already heard",
                "first_proposed": None,
                "last_proposed": None,
                "times_proposed": 0,
                "picked": None,
                "aired": "2026-09-01",
            }]}))
            candidates.write_text(json.dumps({"items": [
                {"title": "Already heard", "url": "https://example.com/heard"},
                {"title": "Fresh", "url": "https://example.com/fresh"},
            ]}))

            value = proposal_context.build(history, archive, ledger_path=ledger,
                                             candidates_path=candidates)

            self.assertEqual(len(value["current_candidate_blockers"]), 1)
            self.assertEqual(value["current_candidate_blockers"][0]["title"], "Already heard")
            self.assertEqual(value["current_candidate_blockers"][0]["reason"], "aired")


if __name__ == "__main__":
    unittest.main()
