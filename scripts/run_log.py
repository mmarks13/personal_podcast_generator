#!/usr/bin/env python3
"""Run-logging helpers for run_episode.sh. Stdlib only — runs under the SYSTEM
python3 on purpose, so logging keeps working even when the project .venv is broken
(a broken .venv was the failure we are trying to make visible).

Subcommands:
  poll   --interval N --log F   Append a usage snapshot now, then every N seconds.
  prefix --src NAME             Read stdin, write "TS [NAME] line" to stdout per line.
  trim   --keep N --log F       Keep only the last N run blocks in F.

Line format matches `date '+%FT%T%:z'` used by the bash side, e.g.
  2026-06-19T01:23:00-07:00 [usage] {"5h_pct":16,"5h_reset":"22:49", ...}
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CRED_PATH = os.path.expanduser("~/.claude/.credentials.json")
RUN_MARKER = "===== RUN START"


def ts() -> str:
    """Local-time ISO-8601 to the second, e.g. 2026-06-19T01:23:00-07:00."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _local_hhmm(iso_utc: str, with_date: bool) -> str:
    """Convert an API resets_at (UTC ISO) to local time, 'HH:MM' or 'MM-DD HH:MM'."""
    dt = datetime.datetime.fromisoformat(iso_utc).astimezone()
    return dt.strftime("%m-%d %H:%M" if with_date else "%H:%M")


def _snapshot() -> dict:
    """One usage reading as the dict we log. Re-reads the token each call so a
    mid-run token refresh by the CLI is picked up. Never raises."""
    try:
        tok = json.load(open(CRED_PATH))["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {tok}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "run_log-usage-poller",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        fh, sd = d.get("five_hour") or {}, d.get("seven_day") or {}
        return {
            "5h_pct": round(fh.get("utilization", 0)),
            "5h_reset": _local_hhmm(fh["resets_at"], with_date=False),
            "7d_pct": round(sd.get("utilization", 0)),
            "7d_reset": _local_hhmm(sd["resets_at"], with_date=True),
        }
    except urllib.error.HTTPError as e:
        return {"err": e.code, "retry_after": e.headers.get("retry-after")}
    except Exception as e:  # network, parse, missing key, expired token, ...
        return {"err": type(e).__name__}


def cmd_poll(a) -> None:
    while True:
        line = f"{ts()} [usage] {json.dumps(_snapshot())}\n"
        with open(a.log, "a") as f:  # O_APPEND: each write is one atomic short line
            f.write(line)
        time.sleep(a.interval)


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

    pp = sub.add_parser("poll")
    pp.add_argument("--interval", type=int, default=60)
    pp.add_argument("--log", required=True)
    pp.set_defaults(func=cmd_poll)

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
