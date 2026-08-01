#!/usr/bin/env python3
"""Provider-neutral, noninteractive agent stage runner.

Prompts arrive on stdin. Provider subprocesses receive closed stdin and never have a
TTY, so an authentication, approval, or elicitation request fails instead of waiting
for a person. Structured traces are ignored by Git and normalized for local profiling.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import yaml

import codex_account

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "agents.yaml"
class RunnerError(RuntimeError):
    def __init__(self, message: str, category: str = "unknown") -> None:
        super().__init__(message)
        self.category = category


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open() as handle:
        config = yaml.safe_load(handle)
    if config.get("default_provider") not in config.get("providers", {}):
        raise RunnerError("default_provider is not configured", "config")
    for provider, body in config["providers"].items():
        if not isinstance(body.get("stages"), dict):
            raise RunnerError(f"provider {provider!r} has no stages", "config")
    return config


def stage_settings(config: dict, provider: str, stage: str) -> dict:
    settings = dict(config["providers"][provider]["stages"][stage])
    effort_override = os.environ.get("AGENT_EFFORT_OVERRIDE")
    if effort_override:
        if effort_override not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
            raise RunnerError(f"invalid AGENT_EFFORT_OVERRIDE={effort_override!r}", "config")
        settings["effort"] = effort_override
    return settings


def stage_output_patterns(config: dict, stage: str) -> list[str]:
    outputs = config.get("outputs", {}).get(stage, [])
    if os.environ.get("RUN_EPISODE_DRY_RUN") == "1":
        return config.get("dry_run_outputs", {}).get(stage, outputs)
    return outputs


def ensure_codex_sandbox_helper() -> Path:
    """Supply the standalone CLI and multicall helper under a protected project path.

    Some standalone Codex bundles install only the multicall `codex` binary. Invoking
    that same inode as `codex-linux-sandbox` activates its documented helper surface.
    Launching the main binary from the workspace also avoids the upstream Linux
    standalone arg0 bug where bwrap cannot resolve a helper symlink targeting
    ``~/.local/bin``. Hard links avoid mutable wrappers and remain read-only to the
    agent profile.
    """
    codex = Path(shutil.which("codex") or "").resolve()
    if not codex.is_file():
        raise RunnerError("codex executable is missing", "config")
    installed = codex.parent / "codex-linux-sandbox"
    if installed.is_file():
        return installed.parent
    runtime_bin = ROOT / ".codex" / "runtime-bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    for name in ("codex", "codex-linux-sandbox"):
        link = runtime_bin / name
        if link.exists() and not os.path.samefile(codex, link):
            link.unlink()
        if not link.exists():
            try:
                os.link(codex, link)
            except OSError as exc:
                raise RunnerError(f"cannot create Codex runtime hard link {name}: {exc}", "config") from exc
    rg_candidates = [
        Path(shutil.which("rg") or ""),
        codex.parent.parent / "codex-path" / "rg",
    ]
    rg = next((candidate.resolve() for candidate in rg_candidates if candidate.is_file()), None)
    if rg is not None:
        runtime_rg = runtime_bin / "rg"
        if runtime_rg.exists() and not os.path.samefile(rg, runtime_rg):
            runtime_rg.unlink()
        if not runtime_rg.exists():
            try:
                os.link(rg, runtime_rg)
            except OSError as exc:
                raise RunnerError(f"cannot create Codex runtime hard link rg: {exc}", "config") from exc
    return runtime_bin


def paid_credit_balance(snapshot: dict) -> float:
    """Return a known paid-credit balance without confusing earned reset credits."""
    limits = snapshot.get("rateLimits") or {}
    candidates = []
    for owner in (limits, limits.get("rateLimits") or {}):
        credits = owner.get("credits") if isinstance(owner, dict) else None
        if isinstance(credits, dict):
            for key in ("balance", "creditBalance", "remainingBalance"):
                if key in credits:
                    candidates.append(credits[key])
    for value in candidates:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            return amount
    return 0.0


def classify_failure(text: str, idle: bool = False) -> str:
    if idle:
        return "idle"
    lower = text.lower()
    if any(term in lower for term in ("not logged in", "authentication", "unauthorized", "login required", "401")):
        return "auth"
    if any(term in lower for term in ("rate limit", "usage limit", "quota", "too many requests", "429")):
        return "quota"
    if any(term in lower for term in ("service unavailable", "upstream", "startup failed", "failed to start", "502", "503", "504")):
        return "service_startup"
    if any(term in lower for term in ("sandbox", "permission", "approval", "config.toml", "strict config")):
        return "config"
    return "unknown"


class OutputTransaction:
    def __init__(self, patterns: list[str]) -> None:
        self.patterns = patterns
        self.temp = Path(tempfile.mkdtemp(prefix="agent-stage-outputs-"))
        self.originals: list[tuple[Path, Path]] = []
        self.before = {path: self.fingerprint(path) for path in self.current_paths()}
        for match in self.current_paths():
            relative = match.relative_to(ROOT)
            backup = self.temp / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if match.is_dir():
                shutil.copytree(match, backup)
            else:
                shutil.copy2(match, backup)
            self.originals.append((match, backup))

    def current_paths(self) -> list[Path]:
        paths: set[Path] = set()
        for pattern in self.patterns:
            for value in glob.glob(str(ROOT / pattern)):
                paths.add(Path(value))
        return sorted(paths)

    @staticmethod
    def fingerprint(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def validate_updated(self) -> tuple[bool, str]:
        for pattern in self.patterns:
            matches = [Path(value) for value in glob.glob(str(ROOT / pattern))]
            if not matches:
                return False, f"required output pattern has no match: {pattern}"
            if not any(self.before.get(path) != self.fingerprint(path) for path in matches):
                return False, f"required output was not freshly written: {pattern}"
        return True, ""

    def restore(self) -> None:
        for current in reversed(self.current_paths()):
            if current.is_dir():
                shutil.rmtree(current)
            else:
                current.unlink(missing_ok=True)
        for destination, backup in self.originals:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if backup.is_dir():
                shutil.copytree(backup, destination)
            else:
                shutil.copy2(backup, destination)

    def close(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)


def codex_command(stage: str, settings: dict, last_message: Path) -> list[str]:
    permission_profile = "podcast-dry-run" if os.environ.get("RUN_EPISODE_DRY_RUN") == "1" else "podcast-automation"
    runtime_bin = ensure_codex_sandbox_helper()
    shell_path = f"{runtime_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    return [
        str(runtime_bin / "codex"), "exec", "-", "--json", "--ephemeral", "--strict-config",
        "--ignore-rules", "--skip-git-repo-check", "-C", str(ROOT),
        "--model", settings["model"], "--output-last-message", str(last_message),
        "-c", 'approval_policy="never"',
        "-c", f'default_permissions="{permission_profile}"',
        "-c", f'model_reasoning_effort="{settings["effort"]}"',
        "-c", f'web_search="{settings.get("web_search", "disabled")}"',
        "-c", f"shell_environment_policy.set.PATH={json.dumps(shell_path)}",
    ]


CLAUDE_TOOLS = {
    "crawl": "Read WebSearch WebFetch Write",
    "consolidate": "Read Write Bash",
    "propose": "Read Write Bash",
    "podcast": "Bash Read Write WebSearch WebFetch Skill Agent",
    "read": "Bash Read Write WebSearch WebFetch Skill Agent",
    "deepdive": "Bash Read Write WebSearch WebFetch Skill Agent",
    "fact_check": "WebFetch WebSearch",
    "link_check": "WebFetch",
}


def claude_command(stage: str, settings: dict, prompt: str) -> list[str]:
    tools = CLAUDE_TOOLS[stage]
    command = [
        "claude", "-p", prompt, "--model", settings["model"],
        "--effort", settings["effort"], "--tools", tools,
        "--allowedTools", tools, "--permission-mode", "dontAsk",
        "--output-format", "stream-json", "--verbose",
    ]
    if settings.get("max_turns"):
        command += ["--max-turns", str(settings["max_turns"])]
    return command


def stream_process(command: list[str], prompt: str | None, idle_timeout: int, trace_path: Path) -> tuple[int, str, bool]:
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    if command and Path(command[0]).name == "codex":
        runtime_bin = ensure_codex_sandbox_helper()
        env["PATH"] = f"{runtime_bin}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        start_new_session=True,
    )
    if prompt is not None:
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    last_output = time.monotonic()
    lines: list[str] = []
    idle = False
    with trace_path.open("w") as trace:
        while True:
            events = selector.select(timeout=1)
            if events:
                line = proc.stdout.readline()
                if line:
                    last_output = time.monotonic()
                    lines.append(line)
                    trace.write(line)
                    trace.flush()
                    continue
            if proc.poll() is not None:
                remainder = proc.stdout.read()
                if remainder:
                    lines.append(remainder)
                    trace.write(remainder)
                break
            if time.monotonic() - last_output >= idle_timeout:
                idle = True
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                lines.append(f"idle timeout after {idle_timeout}s\n")
                trace.write(lines[-1])
                break
    return proc.returncode if proc.returncode is not None else 124, "".join(lines), idle


def normalize_trace(raw_path: Path, provider: str, stage: str, started: float, rc: int, category: str) -> dict:
    event_counts: dict[str, int] = {}
    usage: dict = {}
    actions: list[str] = []
    with raw_path.open(errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = str(event.get("type") or event.get("subtype") or "unknown")
            event_counts[kind] = event_counts.get(kind, 0) + 1
            if "usage" in event and isinstance(event["usage"], dict):
                usage = event["usage"]
            item = event.get("item") or event.get("message") or {}
            action = item.get("type") if isinstance(item, dict) else None
            if action:
                actions.append(str(action))
    return {
        "schema_version": 1,
        "provider": provider,
        "stage": stage,
        "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - started, 3),
        "exit_code": rc,
        "failure_category": category if rc else None,
        "event_counts": event_counts,
        "actions": actions,
        "usage": usage,
    }


def run_attempt(provider: str, stage: str, settings: dict, prompt: str, idle_timeout: int, trace_dir: Path, suffix: str) -> tuple[int, str, bool, Path]:
    raw = trace_dir / f"{stage}-{suffix}-{provider}.jsonl"
    last_message = trace_dir / f"{stage}-{suffix}-{provider}-last.txt"
    if provider == "codex":
        command = codex_command(stage, settings, last_message)
        prompt_input = prompt
    else:
        command = claude_command(stage, settings, prompt)
        prompt_input = None
    rc, output, idle = stream_process(command, prompt_input, idle_timeout, raw)
    return rc, output, idle, raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--provider", choices=("codex", "claude"))
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if not prompt.strip():
        raise SystemExit("agent_runner: prompt on stdin is required")

    config = load_config(args.config)
    stage = args.stage
    provider = args.provider or os.environ.get("AGENT_PROVIDER") or config["default_provider"]
    if provider not in config["providers"] or stage not in config["providers"][provider]["stages"]:
        raise SystemExit(f"agent_runner: unknown provider/stage: {provider}/{stage}")
    runtime = config["runtime"]
    trace_dir = ROOT / runtime["trace_dir"] / dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    trace_dir.mkdir(parents=True, exist_ok=True)
    transaction = OutputTransaction(stage_output_patterns(config, stage))
    before_quota = None

    try:
        if provider == "codex":
            try:
                before_quota = codex_account.safe_snapshot()
            except Exception as exc:  # documented account telemetry is a fail-closed preflight
                print(f"agent_runner: Codex account preflight failed: {exc}", file=sys.stderr)
                return 78
            if before_quota["account"].get("type") != "chatgpt":
                print("agent_runner: Codex login is unavailable", file=sys.stderr)
                return 77
            balance = paid_credit_balance(before_quota)
            if balance > 0:
                print(f"agent_runner: paid Codex credit balance detected ({balance}); refusing", file=sys.stderr)
                return 78
            (trace_dir / "quota-before.json").write_text(json.dumps(before_quota, indent=2, sort_keys=True))

        attempts: list[dict] = []
        current = provider
        reset_attempted = False
        retried: set[tuple[str, str]] = set()
        while True:
            try:
                settings = stage_settings(config, current, stage)
            except RunnerError as exc:
                print(f"agent_runner: {exc}", file=sys.stderr)
                return 78
            started = time.time()
            suffix = f"{len(attempts) + 1:02d}"
            rc, output, idle, raw = run_attempt(
                current, stage, settings, prompt, int(runtime["idle_timeout_seconds"]), trace_dir, suffix
            )
            if rc == 0:
                outputs_ok, output_error = transaction.validate_updated()
                if not outputs_ok:
                    rc = 65
                    output += f"\nartifact validation failed: {output_error}\n"
            category = "success" if rc == 0 else classify_failure(output, idle)
            normalized = normalize_trace(raw, current, stage, started, rc, category)
            normalized["model"] = settings["model"]
            normalized["effort"] = settings["effort"]
            attempts.append(normalized)
            print(f"agent_runner: stage={stage} provider={current} exit={rc} category={category} trace={raw}")
            if rc == 0:
                break

            transaction.restore()
            retry_key = (current, category)
            if category == "idle" and retry_key not in retried:
                retried.add(retry_key)
                continue
            if current == "codex" and category == "quota" and config["fallback"].get("consume_earned_reset") and not reset_attempted:
                reset_attempted = True
                try:
                    reset = codex_account.consume_reset(str(uuid.uuid4()))
                    (trace_dir / "quota-reset.json").write_text(json.dumps(reset, indent=2, sort_keys=True))
                    if (reset.get("consume") or {}).get("outcome") in {"reset", "alreadyRedeemed"}:
                        continue
                except Exception as exc:
                    (trace_dir / "quota-reset-error.txt").write_text(str(exc))
            if current == "codex" and category == "service_startup" and retry_key not in retried:
                retried.add(retry_key)
                continue
            fallback = config.get("fallback", {})
            if current == fallback.get("from") and fallback.get("enabled") and category in set(fallback.get("reasons", [])):
                current = fallback["to"]
                continue
            (trace_dir / "summary.json").write_text(json.dumps({"attempts": attempts}, indent=2, sort_keys=True))
            return rc or 1

        if provider == "codex":
            try:
                after = codex_account.safe_snapshot()
                (trace_dir / "quota-after.json").write_text(json.dumps(after, indent=2, sort_keys=True))
            except Exception as exc:
                (trace_dir / "quota-after-error.txt").write_text(str(exc))
        (trace_dir / "summary.json").write_text(json.dumps({"attempts": attempts}, indent=2, sort_keys=True))
        return 0
    finally:
        transaction.close()


if __name__ == "__main__":
    raise SystemExit(main())
