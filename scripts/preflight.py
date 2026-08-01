#!/usr/bin/env python3
"""Fail-fast, noninteractive dependency/auth/config checks for scheduled runs."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

import agent_runner
import codex_account

ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"preflight: {message}", file=sys.stderr)
    raise SystemExit(78)


def command(name: str) -> str:
    found = shutil.which(name)
    if not found:
        fail(f"required command is missing: {name}")
    return found


def claude_logged_in() -> bool:
    result = subprocess.run(
        ["claude", "auth", "status", "--json"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        return False
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return bool(status.get("loggedIn")) and status.get("authMethod") == "claude.ai"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "read", "propose"), required=True)
    parser.add_argument(
        "--exec-probe",
        action="store_true",
        help="make a minimal low-effort Codex request that verifies exec can launch its shell sandbox",
    )
    args = parser.parse_args()
    config = agent_runner.load_config()
    provider = os.environ.get("AGENT_PROVIDER") or config["default_provider"]
    if provider not in {"codex", "claude"}:
        fail(f"unsupported AGENT_PROVIDER={provider!r}")
    effort_override = os.environ.get("AGENT_EFFORT_OVERRIDE")
    if effort_override and effort_override not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        fail(f"invalid AGENT_EFFORT_OVERRIDE={effort_override!r}")

    for name in ("python3", "git", "flock"):
        command(name)
    if args.mode in {"full", "propose"}:
        try:
            __import__("feedparser")
        except ImportError:
            fail("Python dependency feedparser is missing; run pip install -r requirements.txt")
    try:
        yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    except Exception as exc:
        fail(f"config/sources.yaml is invalid: {exc}")

    checked = []
    if provider == "codex" or config.get("fallback", {}).get("to") == "codex":
        command("codex")
        runtime_bin = agent_runner.ensure_codex_sandbox_helper()
        sandbox_env = os.environ.copy()
        sandbox_env["PATH"] = f"{runtime_bin}{os.pathsep}{sandbox_env.get('PATH', '')}"
        permission_profile = "podcast-dry-run" if os.environ.get("RUN_EPISODE_DRY_RUN") == "1" else "podcast-automation"
        permission_probe = ROOT / "out" / ".codex-permission-preflight"
        permission_probe.unlink(missing_ok=True)
        probe = subprocess.run(
            ["codex", "sandbox", "-C", str(ROOT), "-P", permission_profile, "touch", str(permission_probe)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=sandbox_env,
        )
        if probe.returncode or not permission_probe.exists():
            fail("Codex permission profile cannot write the workspace: " + probe.stderr.strip())
        permission_probe.unlink()
        if args.exec_probe:
            last_message = ROOT / "out" / ".codex-exec-preflight.txt"
            probe_input = ROOT / "out" / ".codex-exec-preflight-input"
            sentinel = secrets.token_hex(16)
            last_message.unlink(missing_ok=True)
            probe_input.write_text(sentinel)
            try:
                exec_probe = subprocess.run(
                    agent_runner.codex_command(
                        "crawl",
                        {"model": "gpt-5.6-luna", "effort": "low", "web_search": "disabled"},
                        last_message,
                    ),
                    input=(
                        "Use the shell tool exactly once to run "
                        "`cat out/.codex-exec-preflight-input`. Reply exactly with its output. "
                        "The value is random and is not present in this prompt. Do not use any other tools."
                    ),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=sandbox_env,
                )
                shell_ok = False
                for line in exec_probe.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    item = event.get("item") or {}
                    if (
                        item.get("type") == "command_execution"
                        and item.get("status") == "completed"
                        and item.get("exit_code") == 0
                        and sentinel in (item.get("aggregated_output") or "")
                    ):
                        shell_ok = True
                if exec_probe.returncode or not shell_ok:
                    detail = (exec_probe.stdout + exec_probe.stderr)[-2000:].strip()
                    fail("Codex exec cannot launch its shell sandbox: " + detail)
            except subprocess.TimeoutExpired:
                fail("Codex exec shell sandbox probe timed out")
            finally:
                last_message.unlink(missing_ok=True)
                probe_input.unlink(missing_ok=True)
        try:
            snapshot = codex_account.safe_snapshot()
        except Exception as exc:
            fail(f"Codex account/config check failed: {exc}")
        account = snapshot.get("account") or {}
        if account.get("type") != "chatgpt":
            fail("Codex is not logged in with ChatGPT")
        if agent_runner.paid_credit_balance(snapshot) > 0:
            fail("paid Codex credits are present; local subscription-only policy refuses to run")
        checked.append(subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip())

    if provider == "claude" or config.get("fallback", {}).get("to") == "claude":
        command("claude")
        if not claude_logged_in():
            fail("Claude is not logged in through claude.ai")
        checked.append(subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip())

    print(f"preflight: provider={provider}; effort_override={effort_override or 'none'}; " + "; ".join(checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
