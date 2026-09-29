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

    def test_copies_rg_when_protected_hardlinks_reject_the_bundle(self) -> None:
        rg = self.install / "rg"
        rg.write_bytes(b"ripgrep")
        real_link = os.link

        def protected_link(source, destination):
            if Path(source) == rg:
                raise PermissionError("protected hardlink")
            return real_link(source, destination)

        with mock.patch.object(
            ar.shutil,
            "which",
            side_effect=lambda name: str(self.codex) if name == "codex" else str(rg),
        ), mock.patch.object(ar.os, "link", side_effect=protected_link):
            runtime_rg = ar.ensure_codex_sandbox_helper() / "rg"

        self.assertEqual(runtime_rg.read_bytes(), b"ripgrep")
        self.assertFalse(os.path.samefile(rg, runtime_rg))
        self.assertEqual(runtime_rg.stat().st_mode & 0o222, 0)

    def test_keeps_an_identical_rg_copy_when_only_its_timestamp_differs(self) -> None:
        rg = self.install / "rg"
        rg.write_bytes(b"ripgrep")
        runtime_bin = self.root / ".codex" / "runtime-bin"
        runtime_bin.mkdir(parents=True)
        cached_rg = runtime_bin / "rg"
        cached_rg.write_bytes(b"ripgrep")
        os.utime(rg, (100, 100))
        os.utime(cached_rg, (200, 200))

        with mock.patch.object(
            ar.shutil,
            "which",
            side_effect=lambda name: str(self.codex) if name == "codex" else str(rg),
        ):
            self.assertEqual(self._run() / "rg", cached_rg)


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

    def test_no_scheduled_stage_can_reach_the_attended_profile(self) -> None:
        """podcast-interactive carries credentials and an approval prompt; 2 AM has neither."""
        settings = {"model": "gpt-5.6-terra", "effort": "high", "web_search": "live"}
        for stage in sorted(ar.CLAUDE_TOOLS):
            command = ar.codex_command(stage, settings, Path("last.txt"))
            joined = " ".join(command)
            self.assertNotIn("podcast-interactive", joined, stage)
            self.assertIn('approval_policy="never"', command, stage)

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

    def test_claude_crawler_can_load_its_skill_without_shell_access(self) -> None:
        settings = {"model": "haiku", "effort": "high", "max_turns": 40}
        command = ar.claude_command("crawl", settings, "prompt")
        tools = command[command.index("--tools") + 1].split()
        self.assertIn("Skill", tools)
        self.assertNotIn("Bash", tools)

    def test_only_locked_availability_failures_classify_for_fallback(self) -> None:
        self.assertEqual(ar.classify_failure("401 authentication required"), "auth")
        self.assertEqual(ar.classify_failure("429 usage limit reached"), "quota")
        claude_session_limit = json.dumps({
            "type": "result",
            "terminal_reason": "api_error",
            "api_error_status": 429,
            "result": "You've hit your session limit · resets 2:10am (America/Los_Angeles)",
        })
        self.assertIn("429", ar.failure_diagnostics(claude_session_limit))
        self.assertEqual(ar.classify_failure(claude_session_limit), "quota")
        self.assertEqual(
            ar.classify_failure(json.dumps({
                "type": "result",
                "result": "You've hit your session limit · resets 2:10am",
            })),
            "quota",
        )
        self.assertEqual(ar.classify_failure("503 upstream service unavailable"), "service_startup")
        self.assertEqual(ar.classify_failure("sandbox denied write"), "config")
        self.assertEqual(ar.classify_failure("artifact validation failed"), "artifact")
        self.assertEqual(
            ar.classify_failure('{"type":"result","subtype":"error_max_turns"}'),
            "artifact",
        )
        self.assertEqual(ar.classify_failure("Failed to authenticate: OAuth session expired"), "auth")

    def test_artifact_failure_uses_provider_fallback(self) -> None:
        config = ar.load_config()
        self.assertIn("artifact", config["fallback"]["reasons"])

    def test_artifact_failure_retries_the_same_provider_first(self) -> None:
        """Falling straight to a quota-exhausted provider costs the whole night."""
        self.assertIn("artifact", ar.SAME_PROVIDER_RETRY)
        self.assertIn("idle", ar.SAME_PROVIDER_RETRY)
        # Retries are one-shot per (provider, category); quota must never loop.
        self.assertNotIn("quota", ar.SAME_PROVIDER_RETRY)
        self.assertNotIn("auth", ar.SAME_PROVIDER_RETRY)

    def test_failure_classification_ignores_agent_visible_content(self) -> None:
        trace = "\n".join([
            json.dumps({
                "type": "item.completed",
                "item": {"type": "command_execution",
                         "aggregated_output": "wait for the rate-limit window"},
            }),
            json.dumps({
                "type": "result",
                "subtype": "error_during_execution",
                "terminal_reason": "aborted_streaming",
                "errors": ["stream ended"],
            }),
        ])
        self.assertNotIn("rate-limit window", ar.failure_diagnostics(trace))
        self.assertEqual(ar.classify_failure(trace), "service_startup")

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
