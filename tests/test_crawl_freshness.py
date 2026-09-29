#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import crawl_freshness  # noqa: E402


class CrawlFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "sources.yaml"
        self.crawl = self.root / "crawl.json"
        self.config.write_text("""sources:
  - {name: Anthropic News, method: fetch, url: 'https://anthropic.com/news', tier: 1, window_hours: 168}
  - {name: Fast News, method: fetch, url: 'https://fast.test/news', tier: 2}
""")

    def write_crawl(self, items: list[dict]) -> None:
        self.crawl.write_text(json.dumps({
            "items": items,
            "failures": [],
            "source_statuses": [],
        }))

    def test_known_stale_and_unknown_dates_are_phone_ineligible(self) -> None:
        self.write_crawl([
            {
                "title": "Old launch",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/old",
                "published_at": "2026-09-01T12:00:00Z",
                "date_status": "verified",
            },
            {
                "title": "Fresh launch",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/fresh",
                "published_at": "2026-09-10T12:00:00Z",
                "date_status": "verified",
            },
            {
                "title": "Undated launch",
                "sources": ["Fast News"],
                "url": "https://fast.test/unknown",
                "published_at": None,
                "date_status": "unknown",
            },
        ])

        counts = crawl_freshness.annotate(
            self.config,
            self.crawl,
            as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(counts, (1, 2))
        value = json.loads(self.crawl.read_text())
        self.assertFalse(value["items"][0]["proposal_eligible"])
        self.assertIn("outside", value["items"][0]["proposal_exclusion_reason"])
        self.assertTrue(value["items"][1]["proposal_eligible"])
        self.assertFalse(value["items"][2]["proposal_eligible"])
        self.assertIn("unknown", value["items"][2]["proposal_exclusion_reason"])
        self.assertEqual(value["proposal_freshness"]["eligible"], 1)
        self.assertEqual(value["proposal_freshness"]["quarantined"], 2)

    def test_recent_discovery_does_not_override_old_publication_date(self) -> None:
        self.write_crawl([{
            "title": "Old but newly found",
            "sources": ["Anthropic News"],
            "url": "https://anthropic.com/news/newly-found",
            "published_at": "2026-09-01",
            "date_status": "verified",
            "days_since_first_seen": 0,
        }])

        crawl_freshness.annotate(
            self.config,
            self.crawl,
            as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        )

        item = json.loads(self.crawl.read_text())["items"][0]
        self.assertEqual(item["days_since_first_seen"], 0)
        self.assertFalse(item["proposal_eligible"])

    def test_item_from_unconfigured_crawl_source_is_quarantined_not_fatal(self) -> None:
        """A stray item must cost itself, not the whole evening picker.

        On 2026-09-15 the crawler emitted three items from Simon Willison's Weblog,
        a Tier-1 source the RSS fetcher owns rather than the crawler. Raising on
        them blocked the proposal gate and the listener got no slate.
        """
        self.write_crawl([
            {
                "title": "Fresh launch",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/fresh",
                "published_at": "2026-09-10T12:00:00Z",
                "date_status": "verified",
            },
            {
                "title": "Blog post the RSS fetcher owns",
                "sources": ["Simon Willison's Weblog"],
                "url": "https://simonwillison.net/2026/Sep/12/navier-stokes/",
                "published_at": "2026-09-12T12:00:00Z",
                "date_status": "verified",
            },
        ])

        eligible, quarantined = crawl_freshness.annotate(
            self.config,
            self.crawl,
            as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        )

        self.assertEqual((eligible, quarantined), (1, 1))
        items = json.loads(self.crawl.read_text())["items"]
        self.assertTrue(items[0]["proposal_eligible"])
        self.assertFalse(items[1]["proposal_eligible"])
        self.assertIn("not configured crawl sources",
                      items[1]["proposal_exclusion_reason"])

    def test_untrusted_date_under_unknown_status_quarantines(self) -> None:
        """`date_status: unknown` settles the item; `published_at` is ignored.

        On 2026-09-20 the crawler kept dates it could not trust (a partial
        "2026-09", a future date) alongside an unknown status on 14 of 44 items,
        and raising on the contradiction cost the whole evening picker.
        """
        self.write_crawl([
            {
                "title": "Fresh launch",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/fresh",
                "published_at": "2026-09-20T06:00:00Z",
                "date_status": "verified",
            },
            {
                "title": "Partial date",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/partial",
                "published_at": "2026-09",
                "date_status": "unknown",
            },
            {
                "title": "Future date off an index page",
                "sources": ["Anthropic News"],
                "url": "https://anthropic.com/news/future",
                "published_at": "2026-09-29",
                "date_status": "unknown",
            },
        ])

        eligible, quarantined = crawl_freshness.annotate(
            self.config,
            self.crawl,
            as_of=datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
        )

        self.assertEqual((eligible, quarantined), (1, 2))
        for item in json.loads(self.crawl.read_text())["items"][1:]:
            self.assertFalse(item["proposal_eligible"])
            self.assertEqual(item["proposal_exclusion_reason"],
                             "publication date unknown")

    def _healthy(self, n: int) -> list[dict]:
        return [{
            "title": f"Fresh launch {i}",
            "sources": ["Anthropic News"],
            "url": f"https://anthropic.com/news/fresh-{i}",
            "published_at": "2026-09-12T06:00:00Z",
            "date_status": "verified",
        } for i in range(n)]

    def test_one_malformed_item_is_quarantined_not_fatal(self) -> None:
        malformed = {
            "title": "Malformed",
            "sources": ["Anthropic News"],
            "url": "https://anthropic.com/news/malformed",
        }
        self.write_crawl([*self._healthy(3), malformed])

        eligible, quarantined = crawl_freshness.annotate(
            self.config, self.crawl,
            as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        )

        self.assertEqual((eligible, quarantined), (3, 1))
        crawl = json.loads(self.crawl.read_text())
        self.assertEqual(crawl["proposal_freshness"]["malformed"], 1)
        self.assertEqual(crawl["proposal_freshness"]["status"], "valid")
        self.assertIn("date_status", crawl["items"][3]["proposal_exclusion_reason"])

    def test_mostly_malformed_crawl_still_fails(self) -> None:
        malformed = [{
            "title": f"Malformed {i}",
            "sources": ["Anthropic News"],
            "url": f"https://anthropic.com/news/malformed-{i}",
        } for i in range(3)]
        self.write_crawl([*self._healthy(2), *malformed])

        with self.assertRaisesRegex(ValueError, "3 of 5 crawl items are malformed"):
            crawl_freshness.annotate(
                self.config, self.crawl,
                as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
            )

    def test_crawl_that_establishes_no_dates_at_all_fails(self) -> None:
        """The regression a pure quarantine policy would hide."""
        self.write_crawl([{
            "title": f"Undated {i}",
            "sources": ["Anthropic News"],
            "url": f"https://anthropic.com/news/undated-{i}",
            "published_at": None,
            "date_status": "unknown",
        } for i in range(4)])

        with self.assertRaisesRegex(ValueError, "no verified publication date"):
            crawl_freshness.annotate(
                self.config, self.crawl,
                as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
            )

    def test_non_object_item_is_dropped_not_fatal(self) -> None:
        self.write_crawl([*self._healthy(3), "not an object"])

        eligible, quarantined = crawl_freshness.annotate(
            self.config, self.crawl,
            as_of=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
        )

        self.assertEqual((eligible, quarantined), (3, 0))
        crawl = json.loads(self.crawl.read_text())
        self.assertEqual(len(crawl["items"]), 3)
        self.assertEqual(crawl["proposal_freshness"]["malformed"], 1)


class CrawlerContractTests(unittest.TestCase):
    """The crawler copies the shape in its skill, not the caller's inline prompt.

    On 2026-09-14 the skill's item shape still omitted these three fields and the
    agent wrote all 45 items without them, so freshness failed and the evening
    picker never went out.
    """

    def test_skill_documents_every_field_freshness_requires(self) -> None:
        contract = (ROOT / ".agents" / "skills" / "source-crawler" / "SKILL.md").read_text()
        for field in ("title", "published_at", "date_status"):
            self.assertIn(f'"{field}"', contract)
        for status in sorted(crawl_freshness.DATE_STATUSES):
            self.assertIn(f'"{status}"', contract)


if __name__ == "__main__":
    unittest.main()
