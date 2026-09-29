#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import score_sources as scorer  # noqa: E402


def metadata(package_id: str = scorer.PACKAGE_ID) -> dict:
    return {
        "package": {"package_id": package_id},
        "provenance": {"base": {"revision": scorer.MODEL_REVISION}},
    }


class ScoreSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sources = self.root / "sources.json"
        self.crawl = self.root / "crawl.json"
        self.sources.write_text(json.dumps({
            "feeds": {
                "OpenAI News RSS": [
                    {"title": "Same release", "summary": "", "url": "https://openai.com/news/x/", "source": "OpenAI News RSS"},
                    {"title": "Low-signal item", "summary": "A real item", "url": "https://example.test/low", "source": "Other"},
                ]
            }
        }))
        self.crawl.write_text(json.dumps({
            "items": [{
                "sources": ["OpenAI News"], "url": "https://openai.com/news/x/",
                "summary": "Same release", "claims": ["OpenAI released X."],
                "why_included": "Official news page.",
            }],
            "failures": [], "source_statuses": [],
        }))

    def test_scores_every_raw_record_without_filtering_duplicates_or_lows(self) -> None:
        outputs = [
            {"editorial_fit": 2, "source_provenance": 2, "evidence_quality": 2, "story_strength": 3},
            {"editorial_fit": 0, "source_provenance": 0, "evidence_quality": 0, "story_strength": 0},
            {"editorial_fit": 2, "source_provenance": 2, "evidence_quality": 2, "story_strength": 2},
        ]
        result = scorer.score_files(
            self.sources, self.crawl,
            classify_batch=lambda inputs: outputs,
            metadata=metadata(),
        )
        self.assertEqual(len(result["records"]), 3)
        self.assertEqual([row["total"] for row in result["records"]], [9, 0, 8])
        self.assertEqual(result["records"][1]["raw_provenance"]["index"], 1)
        self.assertEqual(result["records"][2]["input"]["source_domain"], "openai.com")
        self.assertTrue(result["records"][2]["input"]["summary_present"])
        self.assertEqual(result["package"]["revision"], scorer.FUNCTION_REVISION)

    def test_refuses_wrong_package_before_inference(self) -> None:
        called = False

        def classify(_inputs):
            nonlocal called
            called = True
            return []

        with self.assertRaisesRegex(ValueError, "package mismatch"):
            scorer.score_files(
                self.sources, self.crawl,
                classify_batch=classify,
                metadata=metadata("sha256:wrong"),
            )
        self.assertFalse(called)

    def test_materializes_only_the_checksum_declared_package_tree(self) -> None:
        snapshot = self.root / "snapshot"
        target = self.root / "materialized"
        snapshot.mkdir()
        (snapshot / ".gitattributes").write_text("*.gguf filter=lfs")
        (snapshot / "package.json").write_text("package")
        (snapshot / "checksums.json").write_text(json.dumps({
            "files": {"package.json": "digest"},
        }))
        resolved = scorer._materialize_package(snapshot, target)
        self.assertEqual(resolved, target)
        self.assertTrue((target / "package.json").is_file())
        self.assertTrue((target / "checksums.json").is_file())
        self.assertFalse((target / "package.json").is_symlink())
        self.assertFalse((target / ".gitattributes").exists())

    def test_rebuilds_materialization_with_broken_cache_symlinks(self) -> None:
        snapshot = self.root / "snapshot"
        target = self.root / "materialized"
        snapshot.mkdir()
        target.mkdir()
        (snapshot / "package.json").write_text("package")
        (snapshot / "checksums.json").write_text(json.dumps({
            "files": {"package.json": "digest"},
        }))
        (target / "checksums.json").symlink_to(self.root / "missing-checksums.json")
        (target / "package.json").symlink_to(self.root / "missing-package.json")

        resolved = scorer._materialize_package(snapshot, target)

        self.assertEqual(resolved, target)
        self.assertEqual((target / "package.json").read_text(), "package")
        self.assertTrue(scorer._materialized_package_complete(target))

    def test_resolve_rehydrates_an_incomplete_materialization(self) -> None:
        snapshot = self.root / "snapshot"
        cache = self.root / "cache"
        target = cache / scorer.FUNCTION_REVISION
        snapshot.mkdir()
        target.mkdir(parents=True)
        (snapshot / "package.json").write_text("package")
        (snapshot / "checksums.json").write_text(json.dumps({
            "files": {"package.json": "digest"},
        }))
        (target / "checksums.json").symlink_to(self.root / "missing-checksums.json")

        with mock.patch.dict(os.environ, {"SMALLBATCH_PACKAGE_CACHE": str(cache)}), \
                mock.patch("huggingface_hub.snapshot_download", return_value=str(snapshot)) as download:
            resolved = scorer._resolve_package()

        self.assertEqual(resolved, target)
        self.assertEqual((target / "package.json").read_text(), "package")
        download.assert_called_once_with(
            repo_id=scorer.FUNCTION_REPO,
            revision=scorer.FUNCTION_REVISION,
        )


if __name__ == "__main__":
    unittest.main()
