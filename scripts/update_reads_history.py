#!/usr/bin/env python3
"""Maintain the daily read's continuity memory: reads_history.json.

The daily-read skill READS this file before writing each issue so it doesn't repeat
recent topics/formats and so it rotates the masthead's seven writers evenly. This
script does the mechanical upkeep: parse the issue Claude just wrote and append a
compact record, keeping a bounded newest-first window.

It parses what's deterministic from out/daily_read.md:
  - the mood word           (`<!-- mood: X -->`)
  - each piece's title      (`## ...`)
  - each piece's author     (`*by <Name>*` on the line under the heading)
The skill passes a short per-issue topic/format note via --note (free text) so the
editorial summary isn't reverse-engineered from prose.

reads_history.json:
{
  "issues": [                         # newest-first, <= KEEP recent issues
    {"date","mood","note","pieces":[{"title","author"}]}
  ],
  "updated": "YYYY-MM-DD"
}
"""
from __future__ import annotations

import argparse
import json
import os
import re

READS_FILE = "reads_history.json"
KEEP = 30  # how many recent issues to retain in detail (~a month of dailies)

MOOD_RE = re.compile(r"<!--\s*mood:\s*(.+?)\s*-->")
BYLINE_RE = re.compile(r"^\*by\s+(.+?)\*\s*$", re.IGNORECASE)


def parse_issue(md_path: str) -> tuple[str, list[dict]]:
    with open(md_path) as f:
        text = f.read()
    mood_m = MOOD_RE.search(text)
    mood = mood_m.group(1).strip() if mood_m else ""

    pieces: list[dict] = []
    cur_title = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur_title = line[3:].strip()
            pieces.append({"title": cur_title, "author": ""})
        elif pieces:
            m = BYLINE_RE.match(line.strip())
            if m and not pieces[-1]["author"]:
                pieces[-1]["author"] = m.group(1).strip()
    return mood, pieces


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="out/daily_read.md")
    ap.add_argument("--date", required=True, help="issue date, YYYY-MM-DD")
    ap.add_argument("--note", default="",
                    help="short topic/format summary for this issue (for dedupe)")
    args = ap.parse_args()

    mood, pieces = parse_issue(args.md)
    record = {"date": args.date, "mood": mood, "note": args.note, "pieces": pieces}

    if os.path.exists(READS_FILE):
        with open(READS_FILE) as f:
            data = json.load(f)
    else:
        data = {"issues": []}

    # Replace any existing record for this date (idempotent re-runs), then prepend.
    data["issues"] = [i for i in data.get("issues", []) if i.get("date") != args.date]
    data["issues"].insert(0, record)
    data["issues"] = data["issues"][:KEEP]
    data["updated"] = args.date

    with open(READS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    authors = ", ".join(p["author"] for p in pieces if p["author"])
    print(f"reads_history: recorded {args.date} ({len(pieces)} pieces; {authors})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
