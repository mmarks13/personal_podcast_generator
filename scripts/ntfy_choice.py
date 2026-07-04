#!/usr/bin/env python3
"""Read the listener's deep-dive choice from the ntfy topic.

The Tue/Fri evening `run_episode.sh propose` job wrote out/deepdive_options.json
(numbered topics + a `sent_at` epoch) and pushed the pitches to the phone. The
listener replies by publishing a message to the same topic from the ntfy app:
a number picks that option; any other text is taken verbatim as the topic.

This polls the topic's JSON feed for messages newer than `sent_at`, ignores the
pipeline's own messages (tagged "bot" by notify.py), and prints the chosen topic
to stdout. Prints nothing when there's no reply (or no options file) — the
deep-dive writer then picks, which is the status quo. Always exits 0: a broken
channel must never block the episode.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh")
OPTIONS_FILE = "out/deepdive_options.json"


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or not os.path.exists(OPTIONS_FILE):
        return 0
    try:
        opts = json.load(open(OPTIONS_FILE))
        sent_at = int(opts.get("sent_at", 0))
        url = f"{NTFY_BASE}/{topic}/json?poll=1&since={sent_at or '12h'}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            lines = resp.read().decode().splitlines()
    except Exception as exc:  # noqa: BLE001
        print(f"ntfy_choice: {exc}", file=sys.stderr)
        return 0

    reply = None
    for line in lines:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("event") != "message" or "bot" in (msg.get("tags") or []):
            continue
        if msg.get("time", 0) < sent_at:
            continue
        reply = msg  # keep the latest qualifying reply
    if not reply:
        return 0

    text = (reply.get("message") or "").strip()
    options = {str(o.get("n")): o.get("topic", "") for o in opts.get("options", [])}
    if text in options and options[text]:
        print(options[text])
    elif len(text) > 2:  # free-text topic of the listener's own
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
