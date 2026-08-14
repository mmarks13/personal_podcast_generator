#!/usr/bin/env python3
"""Prepare the daily mini-dive slate for the phone.

The evening `run_episode.sh propose` job drafts out/daily_options.json — six of the
day's stories the listener can lock as tomorrow's mini-dives. This validates that
draft, renumbers it 1..6, stamps the `sent_at` epoch that scripts/ntfy_choice.py
later uses as its reply window, and prints the numbered message body for notify.py.

The deep-dive half of the same push goes through scripts/proposal_ledger.py, which
also keeps a retirement ledger. Daily stories are perishable — an unpicked story is
stale by tomorrow — so there is nothing here to remember between nights.

Prints nothing when there is no usable draft; the writer then picks its own dives,
which is the status quo.
"""
from __future__ import annotations

import argparse
import json
import time

OPTIONS_FILE = "out/daily_options.json"
MAX_OPTIONS = 15


def record(options_path: str) -> int:
    try:
        opts = json.load(open(options_path))
    except Exception:
        return 0  # nothing drafted; nothing to send
    kept = [o for o in opts.get("options", []) if (o.get("label") or "").strip()][:MAX_OPTIONS]
    for n, o in enumerate(kept, 1):
        o["n"] = n
    opts["options"] = kept
    opts["sent_at"] = int(time.time())
    json.dump(opts, open(options_path, "w"), indent=1, ensure_ascii=False)

    for o in kept:
        mark = "*" if o.get("wildcard") else ""
        signal = f" [{o['signal']}]" if o.get("signal") else ""
        print(f"{mark}{o['n']}. {o['label'].strip()}{signal}")
        why = (o.get("why") or "").strip()
        if why:
            print(f"   {why}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["record"])
    ap.add_argument("--options", default=OPTIONS_FILE)
    args = ap.parse_args()
    return record(args.options)


if __name__ == "__main__":
    raise SystemExit(main())
