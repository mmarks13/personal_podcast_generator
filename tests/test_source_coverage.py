#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class OfficialSourceCoverageTests(unittest.TestCase):
    def test_openai_and_anthropic_distinct_surfaces_are_direct_and_recoverable(self) -> None:
        config = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
        by_url = {source["url"]: source for source in config["sources"]}
        expected = {
            "https://claude.com/blog",
            "https://alignment.anthropic.com/",
            "https://platform.claude.com/docs/en/release-notes/overview",
            "https://openai.com/news/",
            "https://developers.openai.com/api/docs/changelog",
        }
        self.assertTrue(expected <= by_url.keys())
        for url in expected:
            self.assertEqual(by_url[url]["method"], "fetch")
            self.assertEqual(by_url[url]["tier"], 1)
            self.assertGreaterEqual(by_url[url]["window_hours"], 168)

        # The remembered Aug. 21 SDLC item is three days old on the handoff date;
        # this direct official surface and window are the regression condition.
        self.assertEqual(by_url["https://claude.com/blog"]["window_hours"], 168)

    def test_consolidator_contract_canonicalizes_openai_rss_html_duplicates(self) -> None:
        contract = (ROOT / ".agents" / "skills" / "source-consolidator" / "SKILL.md").read_text()
        self.assertIn("removes a leading `www.`", contract)
        self.assertIn("treats a trailing slash as", contract)
        self.assertIn("OpenAI News RSS item and the HTML fallback", contract)


if __name__ == "__main__":
    unittest.main()
