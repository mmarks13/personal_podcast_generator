#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import daily_ledger as ledger  # noqa: E402


class DailyLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.options = self.root / "options.json"
        self.picks = self.root / "picks.json"
        self.meta = self.root / "meta.json"
        self.ledger = self.root / "ledger.json"
        self.today = date(2026, 9, 10)

    def write_options(self, options: list[dict]) -> None:
        self.options.write_text(json.dumps({"gather_id": "g", "options": options}))

    def test_filter_suppresses_blockers_then_record_counts_survivors(self) -> None:
        self.meta.write_text(json.dumps({
            "date": "2026-09-09",
            "sources": [{"title": "Already heard", "url": "https://www.Example.com/story/?utm_source=x"}],
        }))
        ledger.mark_aired(self.meta, self.ledger, today=self.today)
        value = ledger.load(self.ledger)
        value["stories"].append({
            "url": "https://papers.test/old", "label": "Old paper",
            "first_proposed": "2026-09-07", "last_proposed": "2026-09-09",
            "times_proposed": 3, "picked": None, "aired": None,
        })
        ledger.save(value, self.ledger)
        self.write_options([
            {"n": 1, "label": "Already heard", "url": "https://example.com/story#top"},
            {"n": 2, "label": "Old paper again", "url": "https://papers.test/old?ref=feed"},
            {"n": 3, "label": "Fresh story", "url": "https://fresh.test/new"},
        ])

        crawl = self.root / "crawl.json"
        crawl.write_text('{"items": [], "proposal_freshness": {"status": "valid"}}')
        self.assertEqual(ledger.filter_options(self.options, self.ledger, crawl), 2)
        ledger.record(self.options, self.ledger, today=self.today)

        options = json.loads(self.options.read_text())["options"]
        self.assertEqual([item["label"] for item in options], ["Fresh story"])
        fresh = ledger.find_match(ledger.load(self.ledger)["stories"],
                                  url="https://fresh.test/new", label="Fresh story")
        self.assertEqual(fresh["times_proposed"], 1)

    def test_fuzzy_label_match_requires_the_same_registrable_domain(self) -> None:
        story = {
            "url": "https://news.example.co.uk/one", "label": "OpenAI cuts off Cursor",
            "first_proposed": "2026-09-08", "last_proposed": "2026-09-08",
            "times_proposed": 1, "picked": None, "aired": None,
        }
        self.assertIs(
            ledger.find_match([story], url="https://blog.example.co.uk/two",
                              label="OpenAI cuts off Cursor access"),
            story,
        )
        self.assertIsNone(
            ledger.find_match([story], url="https://another.test/two",
                              label="OpenAI cuts off Cursor access")
        )

    def test_known_anthropic_page_aliases_share_one_url_identity(self) -> None:
        self.assertEqual(
            ledger.canonical_url("https://www.anthropic.com/news/claude-fable-and-mythos-5-1"),
            ledger.canonical_url("https://www.anthropic.com/claude-fable-and-mythos-5-1"),
        )

    def test_history_dive_blocks_later_primary_url_from_another_publisher(self) -> None:
        history = self.root / "history.json"
        archive = self.root / "archive"
        archive.mkdir()
        history.write_text(json.dumps({"episodes": [{
            "date": "2026-09-02",
            "dives": [{
                "story": "Claude Fable 5.1 and Mythos 5.1: same weights, two safeguard configurations"
            }],
        }]}))
        ledger.sync_history(history, archive, self.ledger, today=self.today)
        self.write_options([{
            "label": "Anthropic ships Claude Fable and Mythos 5.1",
            "url": "https://www.anthropic.com/news/claude-fable-and-mythos-5-1",
        }])
        crawl = self.root / "crawl.json"
        crawl.write_text(json.dumps({"items": [], "proposal_freshness": {"status": "valid"}}))

        removed = ledger.filter_options(self.options, self.ledger, crawl)

        self.assertEqual(removed, 1)
        self.assertEqual(json.loads(self.options.read_text())["options"], [])
        story = ledger.load(self.ledger)["stories"][0]
        self.assertEqual(story["aired"], "2026-09-02")
        self.assertTrue(story["development_id"].startswith("dev_"))

    def test_filter_rejects_crawl_item_quarantined_for_freshness(self) -> None:
        self.write_options([{
            "label": "Old launch",
            "url": "https://example.com/old",
        }])
        crawl = self.root / "crawl.json"
        crawl.write_text(json.dumps({
            "proposal_freshness": {"status": "valid"},
            "items": [{
                "url": "https://example.com/old",
                "proposal_eligible": False,
                "proposal_exclusion_reason": "published_at outside source window",
            }],
        }))

        removed = ledger.filter_options(self.options, self.ledger, crawl)

        self.assertEqual(removed, 1)
        self.assertEqual(json.loads(self.options.read_text())["options"], [])

    def test_filter_collapses_aliases_within_one_slate(self) -> None:
        self.write_options([
            {"label": "Anthropic ships Claude Fable and Mythos 5.1",
             "url": "https://anthropic.com/news/claude-fable-and-mythos-5-1"},
            {"label": "Claude Fable 5.1 and Mythos 5.1 arrive",
             "url": "https://anthropic.com/claude-fable-and-mythos-5-1"},
        ])
        crawl = self.root / "crawl.json"
        crawl.write_text('{"items": [], "proposal_freshness": {"status": "valid"}}')

        self.assertEqual(ledger.filter_options(self.options, self.ledger, crawl), 1)
        self.assertEqual(len(json.loads(self.options.read_text())["options"]), 1)

    def test_filter_does_not_resend_the_same_gather(self) -> None:
        self.write_options([{
            "label": "Fresh story", "url": "https://fresh.test/story",
        }])
        ledger.record(self.options, self.ledger, today=self.today)
        crawl = self.root / "crawl.json"
        crawl.write_text('{"items": [], "proposal_freshness": {"status": "valid"}}')

        self.assertEqual(ledger.filter_options(self.options, self.ledger, crawl), 1)
        self.assertEqual(json.loads(self.options.read_text())["options"], [])

    def test_trace_backfill_is_idempotent(self) -> None:
        traces = self.root / "traces" / "20260901T200945"
        traces.mkdir(parents=True)
        options = {
            "gather_id": "sha256:gather",
            "options": [{
                "label": "Anthropic ships Claude Fable and Mythos 5.1",
                "url": "https://www.anthropic.com/news/claude-fable-and-mythos-5-1",
            }],
        }
        event = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "id": "write-1",
                "name": "Write",
                "input": {
                    "file_path": "/repo/out/daily_options.json",
                    "content": json.dumps(options),
                },
            }]},
        }
        (traces / "propose-01-claude.jsonl").write_text(json.dumps(event) + "\n")
        run_log = self.root / "run.log"
        run_log.write_text(
            "2026-09-01T20:10:00-07:00 [run] ===== RUN START 2026-09-01 mode=propose =====\n"
            "2026-09-01T20:12:00-07:00 [run] step end: notify exit=0 dur=0s\n"
        )

        self.assertEqual(ledger.backfill_traces(traces.parent, run_log, self.ledger,
                                                today=self.today), 1)
        self.assertEqual(ledger.backfill_traces(traces.parent, run_log, self.ledger,
                                                today=self.today), 0)
        story = ledger.load(self.ledger)["stories"][0]
        self.assertEqual(story["times_proposed"], 1)
        self.assertEqual(len(story["proposal_events"]), 1)

    def test_provider_error_event_does_not_break_backfill(self) -> None:
        """A Codex quota error reports `message` as a string, not an object.

        On 2026-09-16 one such line in the previous night's propose trace crashed
        the novelty sync, which fails the run before drafting or notifying.
        """
        traces = self.root / "traces" / "20260901T200945"
        traces.mkdir(parents=True)
        options = {
            "gather_id": "sha256:gather",
            "options": [{
                "label": "Anthropic ships Claude Fable and Mythos 5.1",
                "url": "https://www.anthropic.com/news/claude-fable-and-mythos-5-1",
            }],
        }
        error_event = {
            "type": "error",
            "message": "You've hit your usage limit. Upgrade to Pro",
        }
        write_event = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "id": "write-1",
                "name": "Write",
                "input": {
                    "file_path": "/repo/out/daily_options.json",
                    "content": json.dumps(options),
                },
            }]},
        }
        (traces / "propose-02-codex.jsonl").write_text(
            json.dumps(error_event) + "\n" + json.dumps(write_event) + "\n"
        )
        run_log = self.root / "run.log"
        run_log.write_text(
            "2026-09-01T20:10:00-07:00 [run] ===== RUN START 2026-09-01 mode=propose =====\n"
            "2026-09-01T20:12:00-07:00 [run] step end: notify exit=0 dur=0s\n"
        )

        # The error line is skipped and the write that follows it still imports.
        self.assertEqual(ledger.backfill_traces(traces.parent, run_log, self.ledger,
                                                today=self.today), 1)

    def test_choose_marks_regular_and_overflow_picks(self) -> None:
        self.picks.write_text(json.dumps({
            "picks": [{"label": "One", "url": "https://example.com/one"}],
            "overflow": [{"label": "Four", "url": "https://example.com/four"}],
        }))
        ledger.choose(self.picks, self.ledger, today=self.today)
        stories = ledger.load(self.ledger)["stories"]
        self.assertEqual({story["label"] for story in stories}, {"One", "Four"})
        self.assertTrue(all(story["picked"] == "2026-09-10" for story in stories))

    def test_prune_drops_old_unchosen_entries_but_keeps_aired_blockers(self) -> None:
        stories = [
            {"last_proposed": "2026-08-19", "picked": None, "aired": None},
            {"last_proposed": "2026-08-20", "picked": None, "aired": None},
            {"last_proposed": None, "picked": None, "aired": "2026-01-01"},
        ]
        self.assertEqual(ledger.prune(stories, self.today), [stories[1], stories[2]])


if __name__ == "__main__":
    unittest.main()
