#!/usr/bin/env python3
"""Run-logging helpers for run_episode.sh. Stdlib only — runs under the SYSTEM
python3 on purpose, so logging keeps working even when the project .venv is broken
(a broken .venv was the failure we are trying to make visible).

Subcommands:
  prefix --src NAME             Read stdin, write "TS [NAME] line" to stdout per line.
  trim   --keep N --log F       Keep only the last N run blocks in F.

Provider usage and quota data now comes from supported structured CLI output and
Codex account endpoints, stored under logs/agent-traces/ by agent_runner.py.
"""
import argparse
import datetime
import os
import sys
RUN_MARKER = "===== RUN START"


def ts() -> str:
    """Local-time ISO-8601 to the second, e.g. 2026-06-19T01:23:00-07:00."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def cmd_prefix(a) -> None:
    out = sys.stdout
    for line in iter(sys.stdin.readline, ""):
        out.write(f"{ts()} [{a.src}] {line.rstrip(chr(10))}\n")
        out.flush()


def cmd_trim(a) -> None:
    if not os.path.exists(a.log):
        return
    lines = open(a.log).readlines()
    starts = [i for i, ln in enumerate(lines) if RUN_MARKER in ln]
    if a.keep <= 0:
        kept = []
    elif len(starts) <= a.keep:
        return
    else:
        kept = lines[starts[len(starts) - a.keep]:]
    with open(a.log, "w") as f:
        f.writelines(kept)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    px = sub.add_parser("prefix")
    px.add_argument("--src", required=True)
    px.set_defaults(func=cmd_prefix)

    tr = sub.add_parser("trim")
    tr.add_argument("--keep", type=int, required=True)
    tr.add_argument("--log", required=True)
    tr.set_defaults(func=cmd_trim)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
