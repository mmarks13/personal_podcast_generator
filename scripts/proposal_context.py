#!/usr/bin/env python3
"""Print compact, newest-first coverage context for the evening proposal prompt."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import daily_ledger

DAILY_META = re.compile(r"^\d{4}-\d{2}-\d{2}-meta\.json$")


def build(history_path: str | Path, archive_dir: str | Path,
          *, episode_count: int = 8, archive_count: int = 2,
          ledger_path: str | Path = daily_ledger.LEDGER_FILE,
          candidates_path: str | Path = "out/candidates.json") -> dict:
    recent_episodes = []
    try:
        history = json.loads(Path(history_path).read_text())
        for episode in (history.get("episodes") or [])[:episode_count]:
            recent_episodes.append({
                key: episode[key] for key in ("date", "title", "summary", "topics", "dives")
                if episode.get(key)
            })
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    recent_rundowns = []
    archive = Path(archive_dir)
    paths = sorted(
        (path for path in archive.glob("*-meta.json") if DAILY_META.match(path.name)),
        key=lambda path: path.name,
        reverse=True,
    )[:archive_count]
    for path in paths:
        try:
            meta = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        recent_rundowns.append({
            "date": meta.get("date") or path.name[:10],
            "sources": [
                {key: source[key] for key in ("title", "url") if source.get(key)}
                for source in (meta.get("sources") or []) if isinstance(source, dict)
            ],
        })
    blockers = []
    try:
        ledger = daily_ledger.load(ledger_path)
        candidates = json.loads(Path(candidates_path).read_text())
        for candidate in candidates.get("items") or []:
            if not isinstance(candidate, dict):
                continue
            title = str(candidate.get("title") or candidate.get("summary") or "").strip()
            url = str(candidate.get("url") or "").strip()
            match = daily_ledger.find_match(ledger["stories"], url=url, label=title)
            reason = daily_ledger.blocked_reason(match)
            if reason:
                blockers.append({
                    "development_id": match["development_id"],
                    "title": title,
                    "url": url,
                    "reason": reason,
                    "times_proposed": match.get("times_proposed", 0),
                    "picked": match.get("picked"),
                    "aired": match.get("aired"),
                })
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        # The authoritative pre-notification gate fails closed. Context is advisory.
        blockers = []
    return {
        "recent_episodes_newest_first": recent_episodes,
        "recent_rundown_sources_newest_first": recent_rundowns,
        "current_candidate_blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default="history.json")
    parser.add_argument("--archive", default="archive/scripts")
    parser.add_argument("--episodes", type=int, default=8)
    parser.add_argument("--archives", type=int, default=2)
    parser.add_argument("--ledger", default=daily_ledger.LEDGER_FILE)
    parser.add_argument("--candidates", default="out/candidates.json")
    args = parser.parse_args()
    print(json.dumps(build(args.history, args.archive, episode_count=args.episodes,
                           archive_count=args.archives, ledger_path=args.ledger,
                           candidates_path=args.candidates), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
