#!/usr/bin/env python3
"""Send a phone banner notification via ntfy.sh.

No account needed: the phone's ntfy app subscribes to the private-ish random
topic in NTFY_TOPIC (.env), and anything POSTed to that topic arrives as a push.
Used for the Tue/Fri deep-dive picker and for nightly-run failure alerts.

Silently a no-op (exit 0) when NTFY_TOPIC is unset, so the pipeline never breaks
on a machine without the channel configured. Pipeline-sent messages carry the
"bot" tag; replies the listener publishes from the app don't, which is how
the ledger's `choice` mode tells them apart.

Usage:
    python scripts/notify.py --title "Deep-dive options" --message "..." [--priority high]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh")


def send(title: str, message: str, priority: str = "default") -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("notify: NTFY_TOPIC unset — skipping.", file=sys.stderr)
        return
    # JSON publish endpoint (POST to the base URL, topic in the body): unlike
    # header-based publishing it is fully UTF-8, so titles may contain em-dashes
    # etc. (urllib headers are latin-1-only — that bit us on day one).
    body = json.dumps({"topic": topic, "title": title, "message": message,
                       "priority": {"min": 1, "low": 2, "default": 3,
                                    "high": 4, "urgent": 5}[priority],
                       "tags": ["bot"]}).encode()
    req = urllib.request.Request(
        NTFY_BASE, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    print(f"notify: sent ({title!r}).", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--priority", default="default",
                    choices=["min", "low", "default", "high", "urgent"])
    args = ap.parse_args()
    try:
        send(args.title, args.message, args.priority)
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        print(f"notify: failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
