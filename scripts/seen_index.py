#!/usr/bin/env python3
"""Stamp raw gather items with how many days this pipeline has seen their URL."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from daily_ledger import canonical_url

STATE_FILE = ".state/seen_urls.json"


def _load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in value.items()):
        raise ValueError("seen URL index must be a JSON object of URL keys to ISO dates")
    normalized = {}
    for key, first_seen in value.items():
        alias = canonical_url(key)
        if not alias:
            continue
        normalized[alias] = min(first_seen, normalized.get(alias, first_seen))
    return normalized


def _write(path: Path, value: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")
    temporary.replace(path)


def _items(document: dict, kind: str):
    if kind == "sources":
        for entries in document.get("feeds", {}).values():
            if isinstance(entries, list):
                yield from (item for item in entries if isinstance(item, dict))
    else:
        yield from (item for item in document.get("items", []) if isinstance(item, dict))


def stamp(sources_path: str | Path, crawl_path: str | Path, state_path: str | Path,
          *, today: date | None = None, save_state: bool = True) -> tuple[int, int]:
    day = today or date.today()
    paths = ((Path(sources_path), "sources"), (Path(crawl_path), "crawl"))
    documents = [(path, kind, json.loads(path.read_text())) for path, kind in paths]
    state_file = Path(state_path)
    state = _load(state_file)
    stamped = new = 0

    for _, kind, document in documents:
        for item in _items(document, kind):
            key = canonical_url(item.get("url", ""))
            if not key:
                continue
            first_seen = state.get(key)
            if first_seen is None:
                first_seen = day.isoformat()
                state[key] = first_seen
                new += 1
            try:
                first_day = date.fromisoformat(first_seen)
            except ValueError:
                first_day = day
                state[key] = first_day.isoformat()
            item["days_since_first_seen"] = max(0, (day - first_day).days)
            stamped += 1

    for path, _, document in documents:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(path)
    if save_state:
        _write(state_file, state)
    return stamped, new


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="out/sources.json")
    parser.add_argument("--crawl", default="out/crawl.json")
    parser.add_argument("--state", default=STATE_FILE)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    stamped, new = stamp(args.sources, args.crawl, args.state, save_state=not args.no_save)
    print(f"seen_index: stamped={stamped} new={new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
