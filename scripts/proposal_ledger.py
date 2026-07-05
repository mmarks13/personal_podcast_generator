#!/usr/bin/env python3
"""Maintain deepdive_proposals.json — the deep-dive picker's proposal memory.

Every topic the evening picker pitches is recorded here. A topic pitched 3 times
without ever being chosen is retired: it is dropped from future option slates
before they reach the phone (and the picker is told not to pitch it). The
listener's explicit free-text choice always wins, retired or not.

Modes:
  record  --options out/deepdive_options.json
          Filter retired topics out of the freshly-drafted options (renumbering),
          increment proposal counts for the survivors, stamp `sent_at`, write the
          options file back, and print the numbered message body for notify.py.
          Prints nothing if no options survive.
  choose  --topic "the chosen topic"
          Mark a topic chosen (clears it from ever retiring). Unknown topics
          (listener free text) are added as listener-sourced entries.

Ledger shape (deepdive_proposals.json, committed by publish):
  { "topics": [ { "topic", "type", "first_proposed", "last_proposed",
                  "times_proposed", "chosen": "YYYY-MM-DD" | null } ] }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import date

LEDGER_FILE = "deepdive_proposals.json"
RETIRE_AFTER = 3  # unchosen proposals before a topic is retired


def _norm(topic: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", topic.lower()).strip()


def load(path: str = LEDGER_FILE) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        data.setdefault("topics", [])
        return data
    return {"topics": []}


def save(data: dict, path: str = LEDGER_FILE) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def is_retired(entry: dict) -> bool:
    return entry.get("times_proposed", 0) >= RETIRE_AFTER and not entry.get("chosen")


def record(options_path: str, ledger_path: str) -> int:
    try:
        opts = json.load(open(options_path))
    except Exception:
        return 0  # no options drafted; nothing to send
    ledger = load(ledger_path)
    by_key = {_norm(t["topic"]): t for t in ledger["topics"]}
    today = date.today().isoformat()

    kept = []
    for o in opts.get("options", []):
        topic = (o.get("topic") or "").strip()
        if not topic:
            continue
        entry = by_key.get(_norm(topic))
        if entry and is_retired(entry):
            continue  # pitched 3 evenings, never tapped — off the slate for good
        if entry is None:
            entry = {"topic": topic, "type": o.get("type", ""),
                     "first_proposed": today, "times_proposed": 0, "chosen": None}
            ledger["topics"].append(entry)
            by_key[_norm(topic)] = entry
        entry["times_proposed"] = entry.get("times_proposed", 0) + 1
        entry["last_proposed"] = today
        kept.append(o)

    for n, o in enumerate(kept, 1):
        o["n"] = n
    opts["options"] = kept
    opts["sent_at"] = int(time.time())
    json.dump(opts, open(options_path, "w"), indent=1, ensure_ascii=False)
    save(ledger, ledger_path)

    for o in kept:
        kind = f" [{o['type']}]" if o.get("type") else ""
        print(f"{o['n']}.{kind} {o.get('topic')} — {o.get('pitch')}")
    return 0


def choose(topic: str, ledger_path: str) -> int:
    ledger = load(ledger_path)
    today = date.today().isoformat()
    for entry in ledger["topics"]:
        if _norm(entry["topic"]) == _norm(topic):
            entry["chosen"] = today
            break
    else:
        ledger["topics"].append({"topic": topic.strip(), "type": "listener",
                                 "first_proposed": today, "last_proposed": today,
                                 "times_proposed": 0, "chosen": today})
    save(ledger, ledger_path)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["record", "choose"])
    ap.add_argument("--options", default="out/deepdive_options.json")
    ap.add_argument("--topic", default="")
    ap.add_argument("--file", default=LEDGER_FILE)
    args = ap.parse_args()
    if args.mode == "record":
        return record(args.options, args.file)
    if not args.topic.strip():
        return 0
    return choose(args.topic, args.file)


if __name__ == "__main__":
    raise SystemExit(main())
