#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class MigrationLayoutTests(unittest.TestCase):
    def test_claude_imports_canonical_agents_guidance(self) -> None:
        self.assertEqual((ROOT / "CLAUDE.md").read_text().strip(), "@AGENTS.md")
        self.assertTrue((ROOT / "AGENTS.md").read_text().strip())

    def test_claude_skill_links_resolve_to_canonical_bytes(self) -> None:
        canonical = ROOT / ".agents" / "skills"
        for skill in canonical.iterdir():
            if not skill.is_dir():
                continue
            compatibility = ROOT / ".claude" / "skills" / skill.name
            self.assertTrue(compatibility.is_symlink(), compatibility)
            self.assertEqual(compatibility.resolve(), skill.resolve())
            self.assertEqual(
                (compatibility / "SKILL.md").read_bytes(),
                (skill / "SKILL.md").read_bytes(),
            )

    def test_native_agent_adapters_resolve_shared_role_skills(self) -> None:
        config = yaml.safe_load((ROOT / "config" / "agents.yaml").read_text())
        role_stages = {
            "fact-checker": "fact_check",
            "link-checker": "link_check",
            "source-crawler": "crawl",
            "source-consolidator": "consolidate",
        }
        for role, stage in role_stages.items():
            shared = ROOT / ".agents" / "skills" / role / "SKILL.md"
            self.assertTrue(shared.exists())
            claude = (ROOT / ".claude" / "agents" / f"{role}.md").read_text()
            codex = (ROOT / ".codex" / "agents" / f"{role}.toml").read_text()
            self.assertIn(f"skills: {role}", claude)
            self.assertIn(str(Path(".agents/skills") / role / "SKILL.md"), codex)
            model = re.search(r'^model = "([^"]+)"$', codex, re.MULTILINE)
            effort = re.search(r'^model_reasoning_effort = "([^"]+)"$', codex, re.MULTILINE)
            self.assertIsNotNone(model)
            self.assertIsNotNone(effort)
            self.assertEqual(model.group(1), config["providers"]["codex"]["stages"][stage]["model"])
            self.assertEqual(effort.group(1), config["providers"]["codex"]["stages"][stage]["effort"])

    def test_documented_local_paths_exist(self) -> None:
        for path in (
            "docs/codex-cli-migration-report.md",
            "docs/claude-to-codex-cli-migration-guide.md",
            "scripts/agent_runner.py",
            "scripts/preflight.py",
            "config/agents.yaml",
            ".codex/config.toml",
        ):
            self.assertTrue((ROOT / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
