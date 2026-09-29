#!/usr/bin/env python3
"""Re-attach the deterministic facts the consolidator drops from out/candidates.json.

The consolidator is an agent, and it does not carry publication dates through: on
2026-09-23 none of its 231 candidates held `published_at`, `date_status`, or the
`proposal_eligible` verdict `crawl_freshness.py` had just computed for them. The writer
therefore decided "is this new?" with no publication date for anything, and the only age
signal reaching it — `days_since_first_seen` — measures how long this pipeline has seen a
URL, not how old the thing is. Gemini 3.8 Flash read 12 days on a post roughly 22 days
old and went to air as a release four times (09-03, 09-12, 09-13, 09-21).

So the facts are stamped onto the consolidator's output rather than routed through it:
anything handed to an agent mid-pipeline can be dropped again, and these two are exactly
the ones a writer cannot reconstruct. `archive/scripts/*-meta.json` already records the
source URLs of every published episode, so "has this been on the air?" is a lookup.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from daily_ledger import canonical_url

META_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-[a-z0-9]+)?-meta\.json$")


def aired_index(archive_dir: Path) -> dict[str, list[str]]:
    """Canonical URL -> the episode dates that cited it, oldest first.

    Deep-dive metas count: airing is airing, whichever show it went out on.
    """
    index: dict[str, set[str]] = {}
    for path in sorted(archive_dir.glob("*-meta.json")):
        match = META_NAME.match(path.name)
        if not match:
            continue
        try:
            meta = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # a damaged archive file must not take the gather down
        date = str(meta.get("date") or match.group(1))
        for source in meta.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = canonical_url(source.get("url") or "")
            if url:
                index.setdefault(url, set()).add(date)
    return {url: sorted(dates) for url, dates in index.items()}


def raw_dates(sources_path: Path, crawl_path: Path) -> dict[str, dict]:
    """Canonical URL -> the publication date the gather actually established.

    Feed entries carry a date the publisher stated, so they are `verified`; crawl items
    carry the crawler's own verdict, which is frequently `unknown` and is the whole
    point of passing it on.
    """
    dates: dict[str, dict] = {}

    def offer(url: str, published: object, status: str) -> None:
        key = canonical_url(url)
        if not key or not published:
            return
        # A verified feed date beats a crawler guess for the same URL.
        if key in dates and dates[key]["date_status"] == "verified" and status != "verified":
            return
        dates[key] = {"published_at": str(published), "date_status": status}

    try:
        feeds = json.loads(sources_path.read_text()).get("feeds") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        feeds = {}
    for entries in feeds.values() if isinstance(feeds, dict) else []:
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                offer(entry.get("url") or "", entry.get("published"), "verified")

    try:
        items = json.loads(crawl_path.read_text()).get("items") or []
    except (OSError, json.JSONDecodeError, AttributeError):
        items = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            status = str(item.get("date_status") or "unknown")
            offer(item.get("url") or "", item.get("published_at"), status)
    return dates


def stamp(candidates_path: Path, sources_path: Path, crawl_path: Path,
          archive_dir: Path) -> tuple[int, int, int]:
    document = json.loads(candidates_path.read_text())
    items = document.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{candidates_path} is missing an items list")

    aired = aired_index(archive_dir)
    dates = raw_dates(sources_path, crawl_path)
    aired_count = dated_count = unknown_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        # Stale keys from an earlier run would outlive the facts behind them.
        item.pop("aired_on", None)
        item.pop("published_at", None)
        item.pop("date_status", None)
        url = canonical_url(item.get("url") or "")
        if not url:
            continue
        if url in aired:
            item["aired_on"] = aired[url]
            aired_count += 1
        if url in dates:
            item.update(dates[url])
            dated_count += 1
            if dates[url]["date_status"] != "verified":
                unknown_count += 1

    candidates_path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    return aired_count, dated_count, unknown_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("out/candidates.json"))
    parser.add_argument("--sources", type=Path, default=Path("out/sources.json"))
    parser.add_argument("--crawl", type=Path, default=Path("out/crawl.json"))
    parser.add_argument("--archive", type=Path, default=Path("archive/scripts"))
    args = parser.parse_args()
    aired, dated, unknown = stamp(args.candidates, args.sources, args.crawl, args.archive)
    print(f"stamp_candidates: already_aired={aired} dated={dated} date_unknown={unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
