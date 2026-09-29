#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import crawl_repair  # noqa: E402


class CrawlRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "sources.yaml"
        self.config.write_text("""sources:
  - {name: Feed One, method: rss, url: 'https://feed.test/rss', tier: 1}
  - {name: Kept, method: fetch, url: 'https://kept.test/news', tier: 1}
  - {name: Dropped, method: fetch, url: 'https://dropped.test/news', tier: 1}
  - {name: Dropped Two, method: fetch, url: 'https://dropped2.test/news', tier: 2}
""")
        self.crawl = self.root / "crawl.json"
        self.crawl.write_text(json.dumps({
            "items": [{"title": "Kept item", "sources": ["Kept"],
                       "url": "https://kept.test/a", "published_at": "2026-09-10",
                       "date_status": "verified", "claims": [], "summary": "",
                       "why_included": ""}],
            "failures": [],
            "source_statuses": [{"name": "Kept", "url": "https://kept.test/news",
                                 "tier": 1, "status": "ok"}],
        }))
        self.repair = self.root / "crawl_repair.json"

    def write_repair(self, body: dict) -> None:
        self.repair.write_text(json.dumps(body))

    def test_missing_lists_only_uncovered_fetch_sources(self) -> None:
        gaps = crawl_repair.missing_sources(self.config, self.crawl)
        self.assertEqual([source["name"] for source in gaps], ["Dropped", "Dropped Two"])

    def test_missing_is_empty_when_every_fetch_source_has_a_status(self) -> None:
        crawl = json.loads(self.crawl.read_text())
        crawl["source_statuses"] += [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
             "status": "no_recent_items"},
            {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
             "status": "no_recent_items"},
        ]
        self.crawl.write_text(json.dumps(crawl))
        self.assertEqual(crawl_repair.missing_sources(self.config, self.crawl), [])

    def test_merge_closes_the_gap_and_keeps_the_first_pass(self) -> None:
        self.write_repair({
            "items": [{"title": "Dropped item", "sources": ["Dropped"],
                       "url": "https://dropped.test/a", "published_at": "2026-09-10",
                       "date_status": "verified", "claims": [], "summary": "",
                       "why_included": ""}],
            "failures": [],
            "source_statuses": [
                {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1, "status": "ok"},
                {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
                 "status": "no_recent_items"},
            ],
        })
        self.assertEqual(crawl_repair.merge(self.config, self.crawl, self.repair), (2, 1, []))
        self.assertEqual(crawl_repair.missing_sources(self.config, self.crawl), [])
        crawl = json.loads(self.crawl.read_text())
        self.assertEqual([item["url"] for item in crawl["items"]],
                         ["https://kept.test/a", "https://dropped.test/a"])

    def test_merge_reports_a_source_the_repair_still_omits(self) -> None:
        self.write_repair({"items": [], "failures": [], "source_statuses": [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
             "status": "no_recent_items"},
        ]})
        sources, items, unresolved = crawl_repair.merge(
            self.config, self.crawl, self.repair)
        self.assertEqual((sources, items), (1, 0))
        self.assertEqual(len(unresolved), 1)
        self.assertIn("Dropped Two", unresolved[0])
        self.assertIn("no source_statuses record", unresolved[0])
        # The source that did answer is closed out even though the other one is open.
        self.assertEqual([source["name"] for source in crawl_repair.gap_sources(
            self.config, self.crawl)], ["Dropped Two"])

    def test_merge_rejects_a_tier1_ok_status_carrying_no_item(self) -> None:
        self.write_repair({"items": [], "failures": [], "source_statuses": [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1, "status": "ok"},
            {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
             "status": "no_recent_items"},
        ]})
        sources, _, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual(sources, 1)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("reports ok but the repair carries no item", unresolved[0])

    def test_missing_includes_a_tier1_failed_status_with_no_failure_record(self) -> None:
        # 2026-09-11: the crawl marked Tier-1 TLDR AI failed and wrote no failure
        # record, so nothing showed whether the page was tried or a backup search ran.
        crawl = json.loads(self.crawl.read_text())
        crawl["source_statuses"][0]["status"] = "failed"
        self.crawl.write_text(json.dumps(crawl))
        gaps = crawl_repair.gap_sources(self.config, self.crawl)
        self.assertEqual([source["name"] for source in gaps],
                         ["Dropped", "Dropped Two", "Kept"])
        # A failure record makes the status self-consistent; nothing to repair.
        crawl["failures"] = [{"url": "https://kept.test/news", "tier": 1,
                              "what_happened": "HTTP 403", "recovered": "none"}]
        self.crawl.write_text(json.dumps(crawl))
        self.assertEqual(crawl_repair.defective_sources(self.config, self.crawl), [])

    def test_merge_replaces_a_defective_status_instead_of_duplicating_it(self) -> None:
        crawl = json.loads(self.crawl.read_text())
        crawl["source_statuses"][0]["status"] = "failed"
        self.crawl.write_text(json.dumps(crawl))
        self.write_repair({
            "items": [{"title": "Replacement", "sources": ["Kept"],
                       "url": "https://kept.test/b", "published_at": "2026-09-10",
                       "date_status": "verified", "claims": [], "summary": "",
                       "why_included": ""}],
            "failures": [],
            "source_statuses": [
                {"name": "Kept", "url": "https://kept.test/news", "tier": 1, "status": "ok"},
                {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
                 "status": "no_recent_items"},
                {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
                 "status": "no_recent_items"},
            ],
        })
        self.assertEqual(crawl_repair.merge(self.config, self.crawl, self.repair), (3, 1, []))
        self.assertEqual(crawl_repair.gap_sources(self.config, self.crawl), [])
        merged = json.loads(self.crawl.read_text())
        kept = [record for record in merged["source_statuses"]
                if record["url"] == "https://kept.test/news"]
        self.assertEqual([record["status"] for record in kept], ["ok"])

    def test_merge_rejects_an_invalid_status(self) -> None:
        self.write_repair({"items": [], "failures": [], "source_statuses": [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1, "status": "maybe"},
        ]})
        before = self.crawl.read_text()
        sources, items, unresolved = crawl_repair.merge(
            self.config, self.crawl, self.repair)
        self.assertEqual((sources, items), (0, 0))
        self.assertEqual(len(unresolved), 2)
        self.assertIn("'maybe' is not one of the three allowed", unresolved[0])
        # Nothing survived, so the crawl is left exactly as the first pass wrote it.
        self.assertEqual(self.crawl.read_text(), before)

    def test_one_coined_status_does_not_discard_another_source(self) -> None:
        # 2026-09-23: the repair answered both gaps, but 'no_items_in_window' for
        # mistral.ai aborted the merge and took a correct `failed` record for OpenAI
        # News with it - leaving the manifest gate to report a failure record missing
        # that the repair had actually collected.
        self.write_repair({
            "items": [],
            "failures": [{"url": "https://dropped.test/news", "tier": 1,
                          "what_happened": "HTTP 403 Forbidden", "recovered": "none"}],
            "source_statuses": [
                {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
                 "status": "failed"},
                {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
                 "status": "no_items_in_window"},
            ],
        })
        sources, _, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual(sources, 1)
        self.assertEqual([source["name"] for source in crawl_repair.gap_sources(
            self.config, self.crawl)], ["Dropped Two"])
        merged = json.loads(self.crawl.read_text())
        self.assertIn({"name": "Dropped", "url": "https://dropped.test/news",
                       "tier": 1, "status": "failed"}, merged["source_statuses"])
        # The failure record the gate needs came along with the status it explains.
        self.assertEqual([failure["url"] for failure in merged["failures"]],
                         ["https://dropped.test/news"])
        self.assertIn("no_items_in_window", unresolved[0])

    def test_main_writes_the_rejections_for_the_retry_and_exits_3(self) -> None:
        self.write_repair({"items": [], "failures": [], "source_statuses": [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
             "status": "no_items_in_window"},
            {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
             "status": "no_recent_items"},
        ]})
        argv = ["crawl_repair.py", "merge", "--config", str(self.config),
                "--crawl", str(self.crawl), "--repair", str(self.repair)]
        with unittest.mock.patch.object(sys, "argv", argv):
            self.assertEqual(crawl_repair.main(), 3)
        rejections = self.crawl.parent / "crawl_repair_rejections.txt"
        self.assertIn("no_items_in_window", rejections.read_text())
        self.assertIn("Dropped <https://dropped.test/news>", rejections.read_text())
        # A clean follow-up merge clears the file rather than leaving it to be re-read.
        self.write_repair({"items": [], "failures": [], "source_statuses": [
            {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
             "status": "no_recent_items"},
        ]})
        with unittest.mock.patch.object(sys, "argv", argv):
            self.assertEqual(crawl_repair.main(), 0)
        self.assertFalse(rejections.exists())

    def test_missing_date_metadata_triggers_repair_and_replacement(self) -> None:
        crawl = json.loads(self.crawl.read_text())
        crawl["items"][0].pop("date_status")
        self.crawl.write_text(json.dumps(crawl))
        self.assertEqual([source["name"] for source in crawl_repair.gap_sources(
            self.config, self.crawl
        )], ["Dropped", "Dropped Two", "Kept"])

        self.write_repair({
            "items": [{
                "title": "Replacement", "sources": ["Kept"],
                "url": "https://kept.test/replacement", "published_at": None,
                "date_status": "unknown", "claims": [], "summary": "",
                "why_included": "date unavailable",
            }],
            "failures": [],
            "source_statuses": [
                {"name": "Kept", "url": "https://kept.test/news", "tier": 1,
                 "status": "ok"},
                {"name": "Dropped", "url": "https://dropped.test/news", "tier": 1,
                 "status": "no_recent_items"},
                {"name": "Dropped Two", "url": "https://dropped2.test/news", "tier": 2,
                 "status": "no_recent_items"},
            ],
        })
        crawl_repair.merge(self.config, self.crawl, self.repair)
        items = json.loads(self.crawl.read_text())["items"]
        self.assertEqual([item["url"] for item in items], ["https://kept.test/replacement"])

    def test_a_status_without_a_url_is_matched_by_its_configured_name(self) -> None:
        # 2026-09-25 and 2026-09-28: the repair agent wrote {"name": ..., "status": "ok"}
        # and nothing else. Matching statuses on url alone dropped that record as noise and
        # then reported the source as never answered, so the retry rewrote the same shape
        # and the gap survived two agent passes.
        self.write_repair({
            "items": [{"title": "Dropped Two item", "sources": ["Dropped Two"],
                       "url": "https://dropped2.test/a", "published_at": "2026-09-10",
                       "date_status": "verified", "claims": [], "summary": "",
                       "why_included": ""}],
            "failures": [],
            "source_statuses": [{"name": "Dropped Two", "status": "ok"}],
        })
        sources, _, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual(sources, 1)
        self.assertNotIn("Dropped Two", " ".join(unresolved))
        # The configured url is stamped on, because the coverage check keys off it: a
        # merged record without one leaves the source a gap forever.
        merged = json.loads(self.crawl.read_text())["source_statuses"]
        record = next(r for r in merged if r["name"] == "Dropped Two")
        self.assertEqual(record["url"], "https://dropped2.test/news")
        self.assertEqual(
            [s["name"] for s in crawl_repair.missing_sources(self.config, self.crawl)],
            ["Dropped"])

    def test_a_status_naming_no_configured_gap_stays_noise(self) -> None:
        self.write_repair({"items": [], "failures": [],
                           "source_statuses": [{"name": "Not configured", "status": "ok"}]})
        sources, _, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual(sources, 0)
        self.assertEqual(len(unresolved), 2)

    def test_sanitize_removes_the_trailing_commas_an_agent_leaves(self) -> None:
        # 2026-09-26: one comma after the last field of one of 53 items made crawl.json
        # unparseable, and crawl-freshness, seen-index, scoring and the manifest gate all
        # died on it in turn - including the coverage check that exists for this moment.
        self.crawl.write_text(
            '{"items": [{"url": "https://a.test/a",}], "failures": [],\n'
            ' "source_statuses": [],}')
        self.assertEqual(crawl_repair.sanitize(self.crawl), 2)
        document = json.loads(self.crawl.read_text())
        self.assertEqual(document["items"], [{"url": "https://a.test/a"}])

    def test_sanitize_leaves_valid_json_byte_identical(self) -> None:
        before = self.crawl.read_text()
        self.assertEqual(crawl_repair.sanitize(self.crawl), 0)
        self.assertEqual(self.crawl.read_text(), before)

    def test_sanitize_does_not_touch_a_comma_inside_a_string(self) -> None:
        # Why the repair follows the decoder's error position instead of matching a
        # pattern: prose in a summary can contain the exact bytes being repaired.
        self.crawl.write_text('{"items": [{"summary": "wrote a, } and left",}]}')
        crawl_repair.sanitize(self.crawl)
        self.assertEqual(json.loads(self.crawl.read_text())["items"][0]["summary"],
                         "wrote a, } and left")

    def test_sanitize_refuses_damage_it_cannot_explain(self) -> None:
        self.crawl.write_text('{"items": [')
        with self.assertRaises(json.JSONDecodeError):
            crawl_repair.sanitize(self.crawl)

    def test_an_ok_status_with_no_item_is_rejected_at_any_tier(self) -> None:
        # 2026-09-28: the repair named the Mistral item's source with a bare "source"
        # string instead of a "sources" list, so the item carried no source identity, was
        # attributed to nobody, and was silently dropped - while the status still merged as
        # ok. `ok` asserts the page loaded and had recent items, at Tier 2 as much as Tier 1.
        self.write_repair({
            "items": [{"title": "Hallo", "url": "https://dropped2.test/a",
                       "source": "Dropped Two", "published_at": "2026-09-28"}],
            "failures": [],
            "source_statuses": [{"name": "Dropped Two", "url": "https://dropped2.test/news",
                                 "tier": 2, "status": "ok"}],
        })
        sources, added, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual((sources, added), (0, 0))
        self.assertIn("reports ok but the repair carries no item from it",
                      " ".join(unresolved))

    def test_a_tier2_no_recent_items_status_needs_no_item(self) -> None:
        self.write_repair({
            "items": [], "failures": [],
            "source_statuses": [{"name": "Dropped Two", "url": "https://dropped2.test/news",
                                 "tier": 2, "status": "no_recent_items"}],
        })
        sources, _, unresolved = crawl_repair.merge(self.config, self.crawl, self.repair)
        self.assertEqual(sources, 1)
        self.assertNotIn("Dropped Two", " ".join(unresolved))


if __name__ == "__main__":
    unittest.main()
