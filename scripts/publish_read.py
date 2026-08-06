#!/usr/bin/env python3
"""Publish the day's daily-read EPUB and commit reads_history.json.

The daily read runs in its own ~06:30 window, separate from the podcast publish, so it
handles its own artifacts here rather than riding along in publish.py's docs/ commit.

The EPUB ships as an asset on the single `reads` GitHub Release, NOT through Pages.
It used to be committed into docs/reads/, but that meant the whole 67 MB back catalogue
was redeployed to Pages on every publish; the deploy started exceeding its 10-minute
timeout, which left the podcast feed stale and episodes invisible to Spotify. Only
reads_history.json is committed now. The EPUB's link on the index page is refreshed by
the next podcast publish, which lists the release's assets.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import GitHubBackend  # noqa: E402  - reuses the release-upload machinery


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    epub = f"docs/reads/self-attention-{args.date}.epub"
    if not os.path.exists(epub):
        print(f"publish_read: no EPUB at {epub} — nothing to publish", file=sys.stderr)
        return 1

    url = GitHubBackend().upload_read(epub)
    print(f"publish_read: uploaded {os.path.basename(epub)} -> {url}")

    subprocess.run(["git", "add", "reads_history.json"], check=True)
    # Nothing staged (e.g. history already committed) is success, not an error.
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        print("publish_read: nothing staged to commit")
        return 0
    subprocess.run(["git", "commit", "-m", f"Publish daily read {args.date}"], check=True)
    subprocess.run(["git", "push"], check=True)
    print(f"publish_read: committed + pushed reads_history.json for {args.date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
