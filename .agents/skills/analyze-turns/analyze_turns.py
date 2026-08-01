#!/usr/bin/env python3
"""Aggregate profiler for provider-neutral agent_runner traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRACE_ROOT = ROOT / "logs" / "agent-traces"


def resolve(value: str) -> Path:
    if value != "latest":
        path = Path(value)
        return path if path.is_absolute() else ROOT / path
    summaries = sorted(TRACE_ROOT.glob("*/summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        raise SystemExit(f"no traces under {TRACE_ROOT}")
    return summaries[-1].parent


def token_total(usage: dict) -> int | None:
    values = []
    for key, value in usage.items():
        if isinstance(value, (int, float)) and "token" in key.lower():
            values.append(int(value))
    return sum(values) if values else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", nargs="?", default="latest")
    args = parser.parse_args()
    directory = resolve(args.trace)
    summary = json.loads((directory / "summary.json").read_text())
    attempts = summary.get("attempts", [])
    print(f"Trace: {directory}")
    print("stage provider model effort seconds exit category tokens events actions")
    total_seconds = 0.0
    for attempt in attempts:
        seconds = float(attempt.get("duration_seconds") or 0)
        total_seconds += seconds
        events = sum((attempt.get("event_counts") or {}).values())
        actions = len(attempt.get("actions") or [])
        tokens = token_total(attempt.get("usage") or {})
        print(
            attempt.get("stage"), attempt.get("provider"), attempt.get("model"),
            attempt.get("effort"), f"{seconds:.1f}", attempt.get("exit_code"),
            attempt.get("failure_category") or "-", tokens if tokens is not None else "?",
            events, actions,
        )
    providers = [attempt.get("provider") for attempt in attempts]
    print(f"attempts={len(attempts)} total_seconds={total_seconds:.1f} fallback={len(set(providers)) > 1}")
    for name in ("quota-before.json", "quota-after.json", "quota-reset.json"):
        if (directory / name).exists():
            print(f"telemetry={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
