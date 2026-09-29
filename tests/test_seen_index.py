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
import seen_index  # noqa: E402


class SeenIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sources = self.root / "sources.json"
        self.crawl = self.root / "crawl.json"
        self.state = self.root / "state.json"

    def write_inputs(self, *, extra: bool = False) -> None:
        entries = [{"title": "Feed copy", "url": "https://www.example.com/story?utm_source=rss"}]
        if extra:
            entries.append({"title": "New", "url": "https://new.test/item"})
        self.sources.write_text(json.dumps({"feeds": {"Feed": entries}}))
        self.crawl.write_text(json.dumps({
            "items": [{"summary": "Crawl copy", "url": "https://example.com/story#details"}],
            "failures": [],
        }))

    def test_stamps_duplicate_urls_from_one_first_seen_record(self) -> None:
        self.write_inputs()
        stamped, new = seen_index.stamp(
            self.sources, self.crawl, self.state, today=date(2026, 9, 7)
        )
        self.assertEqual((stamped, new), (2, 1))
        self.assertEqual(len(json.loads(self.state.read_text())), 1)

        self.write_inputs(extra=True)
        stamped, new = seen_index.stamp(
            self.sources, self.crawl, self.state, today=date(2026, 9, 10)
        )
        self.assertEqual((stamped, new), (3, 1))
        sources = json.loads(self.sources.read_text())["feeds"]["Feed"]
        crawl = json.loads(self.crawl.read_text())["items"]
        self.assertEqual(sources[0]["days_since_first_seen"], 3)
        self.assertEqual(crawl[0]["days_since_first_seen"], 3)
        self.assertEqual(sources[1]["days_since_first_seen"], 0)

    def test_no_save_stamps_files_without_mutating_durable_state(self) -> None:
        self.write_inputs()
        seen_index.stamp(self.sources, self.crawl, self.state,
                         today=date(2026, 9, 10), save_state=False)
        self.assertFalse(self.state.exists())
        item = json.loads(self.sources.read_text())["feeds"]["Feed"][0]
        self.assertEqual(item["days_since_first_seen"], 0)

    def test_known_url_alias_keeps_the_earliest_seen_date(self) -> None:
        self.sources.write_text(json.dumps({"feeds": {"Feed": [{
            "title": "Fable",
            "url": "https://www.anthropic.com/claude-fable-and-mythos-5-1",
        }]}}))
        self.crawl.write_text('{"items": []}')
        self.state.write_text(json.dumps({
            "anthropic.com/news/claude-fable-and-mythos-5-1": "2026-09-01",
        }))

        seen_index.stamp(self.sources, self.crawl, self.state, today=date(2026, 9, 12))

        item = json.loads(self.sources.read_text())["feeds"]["Feed"][0]
        self.assertEqual(item["days_since_first_seen"], 11)


if __name__ == "__main__":
    unittest.main()
