#!/usr/bin/env python3
"""Commit + push the day's daily-read EPUB and reads_history.json.

The daily read runs in its own ~06:30 window, separate from the podcast publish, so it
commits its own two artifacts here rather than riding along in publish.py's docs/ commit.
The EPUB lands on GitHub Pages (direct URL) immediately; its link on the episodes index
page is refreshed by the next podcast publish, which re-lists docs/reads/.
"""
import argparse
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    epub = f"docs/reads/self-attention-{args.date}.epub"
    if not os.path.exists(epub):
        print(f"publish_read: no EPUB at {epub} — nothing to publish", file=sys.stderr)
        return 1

    subprocess.run(["git", "add", epub, "reads_history.json"], check=True)
    # Nothing staged (e.g. EPUB already committed) is success, not an error.
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        print("publish_read: nothing staged to commit")
        return 0
    subprocess.run(["git", "commit", "-m", f"Publish daily read {args.date}"], check=True)
    subprocess.run(["git", "push"], check=True)
    print(f"publish_read: committed + pushed {epub}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
