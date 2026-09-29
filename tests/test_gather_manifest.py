#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gather_manifest as manifest  # noqa: E402


class GatherManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.config = self.root / "sources.yaml"
        self.config.write_text("""sources:
  - {name: Feed One, method: rss, url: 'https://feed.test/rss', tier: 1}
  - {name: HTML One, method: fetch, url: 'https://html.test/news', tier: 1, window_hours: 168}
""")
        (self.out / "sources.json").write_text(json.dumps({
            "feeds": {"Feed One": []}, "errors": [],
        }))
        (self.out / "crawl.json").write_text(json.dumps({
            "items": [], "failures": [],
            "source_statuses": [{
                "name": "HTML One", "url": "https://html.test/news", "tier": 1,
                "window_hours": 168, "status": "no_recent_items",
            }],
        }))
        (self.out / "candidates.json").write_text('{"items": []}')

    def test_manifest_accepts_explicit_no_recent_statuses_and_validates_identity(self) -> None:
        value = manifest.create_manifest(self.out, self.config)
        self.assertEqual(value["proposal_freshness"]["status"], "unavailable")
        self.assertEqual([s["status"] for s in value["tier1_sources"]],
                         ["no_recent_items", "no_recent_items"])
        path = self.out / "gather_manifest.json"
        manifest.write_manifest(path, value)
        checked = manifest.validate_manifest(path, self.out, self.config, 12)
        self.assertEqual(checked["gather_id"], value["gather_id"])

        (self.out / "candidates.json").write_text('{"items": [{"changed": true}]}')
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            manifest.validate_manifest(path, self.out, self.config, 12)

    def test_silent_tier1_omission_cannot_create_manifest(self) -> None:
        crawl = json.loads((self.out / "crawl.json").read_text())
        crawl["source_statuses"] = []
        (self.out / "crawl.json").write_text(json.dumps(crawl))
        with self.assertRaisesRegex(ValueError, "silently omitted"):
            manifest.create_manifest(self.out, self.config)

    def test_tier1_ok_status_without_a_result_is_downgraded_not_fatal(self) -> None:
        # `ok` means "loaded AND produced in-window items"; the crawl agent mislabels a
        # source that loaded with nothing recent (2026-09-02 lost the evening picker to
        # exactly this). The gather is still whole, so record what the crawl shows.
        crawl = json.loads((self.out / "crawl.json").read_text())
        crawl["source_statuses"][0]["status"] = "ok"
        name = crawl["source_statuses"][0]["name"]
        (self.out / "crawl.json").write_text(json.dumps(crawl))
        built = manifest.create_manifest(self.out, self.config)
        status = next(s for s in built["tier1_sources"] if s["name"] == name)
        self.assertEqual(status["status"], "no_recent_items")

    def test_tier1_failed_status_without_a_failure_record_is_recorded_not_fatal(self) -> None:
        # 2026-09-11: the crawl marked Tier-1 TLDR AI failed and wrote no failure
        # record, and this gate discarded a whole valid gather — and the evening picker
        # — over the missing narrative. `failed` is already the pessimistic label, so
        # record it; scripts/crawl_repair.py is where it gets recrawled.
        crawl = json.loads((self.out / "crawl.json").read_text())
        crawl["source_statuses"][0]["status"] = "failed"
        name = crawl["source_statuses"][0]["name"]
        (self.out / "crawl.json").write_text(json.dumps(crawl))
        built = manifest.create_manifest(self.out, self.config)
        status = next(s for s in built["tier1_sources"] if s["name"] == name)
        self.assertEqual(status["status"], "failed")

    def test_present_scores_verified_and_absent_scores_only_warn(self) -> None:
        sources_sha = manifest.sha256(self.out / "sources.json")
        crawl_sha = manifest.sha256(self.out / "crawl.json")
        raw = {"kind": "feed", "index": 0}
        (self.out / "source_scores.json").write_text(json.dumps({
            "status": "ok", "inputs": {"sources.json": sources_sha, "crawl.json": crawl_sha},
            "package": {"package_id": "sha256:package", "revision": "revision"},
            "records": [{
                "raw_provenance": raw,
                "dimensions": {"editorial_fit": 2, "source_provenance": 2,
                               "evidence_quality": 2, "story_strength": 3},
                "total": 9,
            }],
        }))
        # A candidate the consolidator could not match to a raw record is reported,
        # not fatal: the score ranks attention and never filters.
        (self.out / "candidates.json").write_text(json.dumps({"items": [{"title": "x"}]}))
        value = manifest.create_manifest(self.out, self.config)
        self.assertEqual(value["scoring"]["status"], "ok")
        self.assertEqual(value["scoring"]["scored_candidates"], 0)
        self.assertEqual(value["scoring"]["candidates"], 1)

        # A partial score is a fabrication, and still fails the gather.
        (self.out / "candidates.json").write_text(json.dumps({
            "items": [{"title": "x", "smallbatch_score": {"editorial_fit": 2, "total": 2}}],
        }))
        with self.assertRaisesRegex(ValueError, "incomplete smallbatch_score"):
            manifest.create_manifest(self.out, self.config)

        score = {
            "editorial_fit": 2, "source_provenance": 2, "evidence_quality": 2,
            "story_strength": 3, "total": 9, "package_id": "sha256:package",
            "revision": "revision", "raw_provenance": [raw],
        }
        (self.out / "candidates.json").write_text(json.dumps({
            "items": [{"title": "x", "smallbatch_score": score}],
        }))
        value = manifest.create_manifest(self.out, self.config)
        self.assertEqual(value["scoring"]["status"], "ok")
        self.assertEqual(value["scoring"]["scored_candidates"], 1)
        self.assertIn("source_scores.json", value["artifacts"])

    def test_both_proposal_halves_must_use_the_manifest_identity(self) -> None:
        value = manifest.create_manifest(self.out, self.config)
        daily = self.out / "daily_options.json"
        deep = self.out / "deepdive_options.json"
        daily.write_text(json.dumps({"gather_id": value["gather_id"], "options": []}))
        deep.write_text(json.dumps({"gather_id": value["gather_id"], "options": []}))
        manifest.verify_proposals(value, [daily, deep])
        deep.write_text(json.dumps({"gather_id": "sha256:other", "options": []}))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            manifest.verify_proposals(value, [daily, deep])


if __name__ == "__main__":
    unittest.main()
