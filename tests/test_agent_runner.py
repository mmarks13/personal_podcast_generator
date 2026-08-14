#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import agent_runner as ar  # noqa: E402


class RuntimeBinTests(unittest.TestCase):
    """Codex resolves helper binaries next to its own argv[0], and we launch it from
    .codex/runtime-bin — so every sibling it expects has to be linked in. Missing
    codex-code-mode-host after the 0.147.0 upgrade failed every tool call closed and
    took down the 2026-08-13 run."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.install = self.root / "install"
        self.install.mkdir()
        self.codex = self.install / "codex"
        self.codex.write_bytes(b"codex")
        patcher = mock.patch.object(ar, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self):
        with mock.patch.object(ar.shutil, "which",
                               side_effect=lambda n: str(self.codex) if n == "codex" else None):
            return ar.ensure_codex_sandbox_helper()

    def test_links_the_code_mode_host_when_the_bundle_ships_one(self) -> None:
        host = self.install / "codex-code-mode-host"
        host.write_bytes(b"host")
        linked = self._run() / "codex-code-mode-host"
        self.assertTrue(linked.is_file())
        self.assertTrue(os.path.samefile(host, linked))

    def test_absent_host_is_not_fatal(self) -> None:
        runtime_bin = self._run()
        self.assertTrue((runtime_bin / "codex").is_file())
        self.assertFalse((runtime_bin / "codex-code-mode-host").exists())

    def test_a_stale_host_link_is_replaced(self) -> None:
        runtime_bin = self.root / ".codex" / "runtime-bin"
        runtime_bin.mkdir(parents=True)
        (runtime_bin / "codex-code-mode-host").write_bytes(b"stale")
        host = self.install / "codex-code-mode-host"
        host.write_bytes(b"fresh")
        linked = self._run() / "codex-code-mode-host"
        self.assertTrue(os.path.samefile(host, linked))


class AgentRunnerTests(unittest.TestCase):
    def test_locked_effort_mapping(self) -> None:
        cfg = ar.load_config()
        stages = cfg["providers"]["codex"]["stages"]
        self.assertEqual(stages["propose"]["effort"], "high")
        self.assertEqual(stages["podcast"]["effort"], "xhigh")
        self.assertEqual(stages["crawl"]["effort"], "max")
        self.assertEqual(stages["fact_check"]["effort"], "xhigh")

    def test_codex_command_is_noninteractive_and_pinned(self) -> None:
        settings = {"model": "gpt-5.6-sol", "effort": "xhigh", "web_search": "live"}
        command = ar.codex_command("podcast", settings, Path("last.txt"))
        joined = " ".join(command)
        self.assertIn("--json", command)
        self.assertIn('approval_policy="never"', command)
        # podcast must read primary sources, so it gets the network-enabled profile.
        self.assertIn('default_permissions="podcast-automation-net"', command)
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertIn('web_search="live"', command)
        self.assertNotIn("dangerously-bypass", joined)
        self.assertEqual(Path(command[0]).parent, ROOT / ".codex" / "runtime-bin")
        self.assertTrue(os.path.samefile(command[0], Path(command[0]).parent / "codex-linux-sandbox"))

    def test_codex_network_profile_is_per_stage(self) -> None:
        """Least privilege: only the stages that must fetch get shell network."""
        settings = {"model": "gpt-5.6-terra", "effort": "high", "web_search": "disabled"}
        for stage in ("podcast", "crawl", "deepdive", "read", "fact_check", "link_check"):
            self.assertIn('default_permissions="podcast-automation-net"',
                          ar.codex_command(stage, settings, Path("last.txt")), stage)
        for stage in ("consolidate", "propose"):
            self.assertIn('default_permissions="podcast-automation"',
                          ar.codex_command(stage, settings, Path("last.txt")), stage)

    def test_codex_dry_run_uses_output_only_profile(self) -> None:
        settings = {"model": "gpt-5.6-sol", "effort": "xhigh", "web_search": "live"}
        with mock.patch.dict(os.environ, {"RUN_EPISODE_DRY_RUN": "1"}):
            command = ar.codex_command("podcast", settings, Path("last.txt"))
        self.assertIn('default_permissions="podcast-dry-run"', command)

    def test_claude_command_denies_prompts_and_restricts_tools(self) -> None:
        settings = {"model": "sonnet", "effort": "low", "max_turns": 15}
        command = ar.claude_command("propose", settings, "prompt")
        self.assertIn("dontAsk", command)
        self.assertIn("--tools", command)
        self.assertIn("--allowedTools", command)
        self.assertIn("15", command)

    def test_only_locked_availability_failures_classify_for_fallback(self) -> None:
        self.assertEqual(ar.classify_failure("401 authentication required"), "auth")
        self.assertEqual(ar.classify_failure("429 usage limit reached"), "quota")
        self.assertEqual(ar.classify_failure("503 upstream service unavailable"), "service_startup")
        self.assertEqual(ar.classify_failure("sandbox denied write"), "config")
        self.assertEqual(ar.classify_failure("artifact validation failed"), "unknown")

    def test_effort_override_changes_runtime_not_production_config(self) -> None:
        config = ar.load_config()
        with mock.patch.dict(os.environ, {"AGENT_EFFORT_OVERRIDE": "low"}):
            runtime = ar.stage_settings(config, "codex", "podcast")
        self.assertEqual(runtime["effort"], "low")
        self.assertEqual(config["providers"]["codex"]["stages"]["podcast"]["effort"], "xhigh")
        with mock.patch.dict(os.environ, {"AGENT_EFFORT_OVERRIDE": "minimal"}):
            with self.assertRaises(ar.RunnerError):
                ar.stage_settings(config, "codex", "podcast")

    def test_read_dry_run_does_not_require_history_write(self) -> None:
        config = ar.load_config()
        self.assertIn("reads_history.json", ar.stage_output_patterns(config, "read"))
        with mock.patch.dict(os.environ, {"RUN_EPISODE_DRY_RUN": "1"}):
            outputs = ar.stage_output_patterns(config, "read")
        self.assertEqual(outputs, ["docs/reads/self-attention-*.epub"])

    def test_paid_credit_detection_ignores_earned_resets(self) -> None:
        snapshot = {"rateLimits": {"rateLimits": {"credits": {"balance": "0"}}, "rateLimitResetCredits": {"availableCount": 2}}}
        self.assertEqual(ar.paid_credit_balance(snapshot), 0)
        snapshot["rateLimits"]["rateLimits"]["credits"]["balance"] = "1.50"
        self.assertEqual(ar.paid_credit_balance(snapshot), 1.5)

    def test_output_transaction_restores_original(self) -> None:
        with tempfile.TemporaryDirectory(dir=ar.ROOT / "out") as directory:
            path = Path(directory) / "artifact.json"
            path.write_text("old")
            relative = str(path.relative_to(ar.ROOT))
            tx = ar.OutputTransaction([relative])
            try:
                path.write_text("partial")
                valid, _ = tx.validate_updated()
                self.assertTrue(valid)
                tx.restore()
                self.assertEqual(path.read_text(), "old")
            finally:
                tx.close()

    def test_output_transaction_rejects_stale_or_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir=ar.ROOT / "out") as directory:
            path = Path(directory) / "artifact.json"
            path.write_text("stale")
            relative = str(path.relative_to(ar.ROOT))
            tx = ar.OutputTransaction([relative, relative + ".missing"])
            try:
                valid, message = tx.validate_updated()
                self.assertFalse(valid)
                self.assertIn("not freshly written", message)
            finally:
                tx.close()

    def test_normalized_trace_uses_supported_aggregate_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "trace.jsonl"
            raw.write_text(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 2}}) + "\n")
            report = ar.normalize_trace(raw, "codex", "podcast", 0, 0, "unknown")
        self.assertEqual(report["usage"]["input_tokens"], 4)
        self.assertEqual(report["event_counts"]["turn.completed"], 1)


if __name__ == "__main__":
    unittest.main()
