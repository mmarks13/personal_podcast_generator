#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import stamp_candidates  # noqa: E402

GEMINI = "https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash/"


class StampCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.candidates = self.root / "candidates.json"
        self.sources = self.root / "sources.json"
        self.crawl = self.root / "crawl.json"
        self.sources.write_text(json.dumps({"feeds": {}}))
        self.crawl.write_text(json.dumps({"items": []}))

    def write_meta(self, date: str, urls: list[str], slug: str = "") -> None:
        name = f"{date}-{slug}-meta.json" if slug else f"{date}-meta.json"
        (self.archive / name).write_text(json.dumps({
            "date": date, "sources": [{"title": "t", "url": url} for url in urls]}))

    def write_candidates(self, items: list[dict]) -> None:
        self.candidates.write_text(json.dumps({"items": items}))

    def stamp(self) -> tuple[int, int, int]:
        return stamp_candidates.stamp(
            self.candidates, self.sources, self.crawl, self.archive)

    def items(self) -> list[dict]:
        return json.loads(self.candidates.read_text())["items"]

    def test_aired_on_lists_every_episode_that_cited_the_url(self) -> None:
        # The 2026-09-23 complaint: Gemini 3.8 Flash went out as a release four times.
        for date in ("2026-09-03", "2026-09-12", "2026-09-13", "2026-09-21"):
            self.write_meta(date, [GEMINI])
        self.write_meta("2026-09-22", ["https://example.test/other"])
        self.write_candidates([{"title": "Gemini 3.8 Flash", "url": GEMINI}])
        aired, _, _ = self.stamp()
        self.assertEqual(aired, 1)
        self.assertEqual(self.items()[0]["aired_on"],
                         ["2026-09-03", "2026-09-12", "2026-09-13", "2026-09-21"])

    def test_a_never_aired_candidate_carries_no_flag(self) -> None:
        self.write_meta("2026-09-21", ["https://example.test/other"])
        self.write_candidates([{"title": "Brand new", "url": "https://example.test/new"}])
        aired, _, _ = self.stamp()
        self.assertEqual(aired, 0)
        self.assertNotIn("aired_on", self.items()[0])

    def test_airing_is_matched_past_url_cosmetics(self) -> None:
        # seen_index and the ledger already canonicalize this way; the archive is raw.
        self.write_meta("2026-09-12", ["http://www.blog.google/a/b?utm_source=x"])
        self.write_candidates([{"title": "x", "url": "https://blog.google/a/b/"}])
        self.stamp()
        self.assertEqual(self.items()[0]["aired_on"], ["2026-09-12"])

    def test_a_deep_dive_airing_counts(self) -> None:
        self.write_meta("2026-09-20", [GEMINI], slug="deepdive")
        self.write_candidates([{"title": "x", "url": GEMINI}])
        self.stamp()
        self.assertEqual(self.items()[0]["aired_on"], ["2026-09-20"])

    def test_dates_come_back_from_the_raw_gather(self) -> None:
        self.crawl.write_text(json.dumps({"items": [
            {"url": GEMINI, "published_at": "2026-09-01", "date_status": "unknown"}]}))
        self.sources.write_text(json.dumps({"feeds": {"Feed": [
            {"url": "https://example.test/paper", "published": "2026-09-23T10:00:00+00:00"}]}}))
        self.write_candidates([
            {"title": "Gemini", "url": GEMINI},
            {"title": "Paper", "url": "https://example.test/paper"},
            {"title": "Undated", "url": "https://example.test/undated"},
        ])
        _, dated, unknown = self.stamp()
        self.assertEqual((dated, unknown), (2, 1))
        gemini, paper, undated = self.items()
        self.assertEqual((gemini["published_at"], gemini["date_status"]),
                         ("2026-09-01", "unknown"))
        self.assertEqual(paper["date_status"], "verified")
        self.assertNotIn("published_at", undated)

    def test_a_verified_feed_date_beats_a_crawler_guess(self) -> None:
        self.crawl.write_text(json.dumps({"items": [
            {"url": GEMINI, "published_at": "2026-09-01", "date_status": "unknown"}]}))
        self.sources.write_text(json.dumps({"feeds": {"Feed": [
            {"url": GEMINI, "published": "2026-09-11T08:00:00+00:00"}]}}))
        self.write_candidates([{"title": "Gemini", "url": GEMINI}])
        self.stamp()
        self.assertEqual(self.items()[0]["date_status"], "verified")

    def test_stale_stamps_from_an_earlier_run_are_replaced(self) -> None:
        self.write_candidates([{"title": "x", "url": "https://example.test/a",
                                "aired_on": ["2026-01-01"], "published_at": "2026-01-01",
                                "date_status": "verified"}])
        self.stamp()
        item = self.items()[0]
        self.assertNotIn("aired_on", item)
        self.assertNotIn("published_at", item)
        self.assertNotIn("date_status", item)

    def test_a_damaged_archive_file_does_not_stop_the_stamp(self) -> None:
        self.write_meta("2026-09-12", [GEMINI])
        (self.archive / "2026-09-13-meta.json").write_text("{not json")
        self.write_candidates([{"title": "x", "url": GEMINI}])
        aired, _, _ = self.stamp()
        self.assertEqual(aired, 1)

    def test_other_candidate_fields_survive(self) -> None:
        self.write_candidates([{"title": "x", "url": GEMINI, "sources": ["A"],
                                "smallbatch_score": {"total": 8},
                                "days_since_first_seen": 12}])
        self.stamp()
        item = self.items()[0]
        self.assertEqual(item["smallbatch_score"], {"total": 8})
        self.assertEqual(item["days_since_first_seen"], 12)
        self.assertEqual(item["sources"], ["A"])


if __name__ == "__main__":
    unittest.main()
