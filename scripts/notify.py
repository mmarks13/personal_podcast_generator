#!/usr/bin/env python3
"""Send a phone banner notification via ntfy.sh.

No account needed: the phone's ntfy app subscribes to the private-ish random
topic in NTFY_TOPIC (.env), and anything POSTed to that topic arrives as a push.
Used for the nightly picker and for nightly-run failure alerts.

ntfy.sh rejects a message body of 4096 bytes or more with a 500, which is how a
long picker slate silently became no slate at all. Anything over the limit is
split across numbered pushes on option boundaries; the listener still answers
with one reply, since both halves share one options file and one reply window.

Silently a no-op (exit 0) when NTFY_TOPIC is unset, so the pipeline never breaks
on a machine without the channel configured. Pipeline-sent messages carry the
"bot" tag; replies the listener publishes from the app don't, which is how
ntfy_choice.py tells them apart.

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
MAX_MESSAGE_BYTES = 3800  # ntfy.sh rejects >= 4096; leave room for the JSON envelope


def _blocks(message: str) -> list[str]:
    """Group each line with the indented lines under it, so an option never splits
    away from its own why-line."""
    blocks: list[list[str]] = []
    for line in message.split("\n"):
        if blocks and (line.startswith(" ") or not line.strip()):
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return ["\n".join(b) for b in blocks]


def chunk(message: str, limit: int = MAX_MESSAGE_BYTES) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for block in _blocks(message):
        candidate = f"{cur}\n{block}" if cur else block
        if cur and len(candidate.encode()) > limit:
            chunks.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    # A single block over the limit can't be split on a boundary; truncate it rather
    # than let the whole push 500.
    return [c if len(c.encode()) <= limit else c.encode()[:limit].decode(errors="ignore")
            for c in chunks]


def _post(topic: str, title: str, message: str, priority: str) -> None:
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


def send(title: str, message: str, priority: str = "default") -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("notify: NTFY_TOPIC unset — skipping.", file=sys.stderr)
        return
    parts = chunk(message)
    for i, part in enumerate(parts, 1):
        part_title = title if len(parts) == 1 else f"{title} ({i}/{len(parts)})"
        _post(topic, part_title, part, priority)
        print(f"notify: sent ({part_title!r}).", file=sys.stderr)


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
