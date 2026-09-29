#!/usr/bin/env python3
"""Maintain deterministic novelty state for daily phone proposals.

The ledger treats URLs and titles as aliases of a news development. Proposal filtering
fails closed; episode-side bookkeeping may fail without blocking episode production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

LEDGER_FILE = "daily_pitch_ledger.json"
SCHEMA_VERSION = 2
RETIRE_AFTER = 3
KEEP_DAYS = 21
FUZZY_THRESHOLD = 0.82

_MULTI_LABEL_SUFFIXES = {
    "co.jp", "co.nz", "co.uk", "com.au", "com.br", "com.cn", "com.sg",
    "net.au", "org.au", "org.uk",
}
_KNOWN_URL_ALIASES = {
    "anthropic.com/news/claude-fable-and-mythos-5-1":
        "anthropic.com/claude-fable-and-mythos-5-1",
}
_VERSIONED_NAME = re.compile(r"\b([a-z][a-z0-9-]{1,})\s+(\d+(?:[._-]\d+)+)\b", re.I)
_GENERIC_VERSION_NAMES = {"api", "model", "release", "update", "version"}
_RUN_START = re.compile(r"^(\d{4}-\d{2}-\d{2}).*RUN START .*mode=propose")
_NOTIFY_OK = re.compile(r"^(\d{4}-\d{2}-\d{2}).*step end: notify exit=0\b")


def canonical_url(value: str) -> str:
    """Stable URL alias: host + path without tracking or known duplicate paths."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if not host:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    key = f"{host}{port}{path}"
    return _KNOWN_URL_ALIASES.get(key, key)


def registrable_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return host
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in _MULTI_LABEL_SUFFIXES else suffix


def normalize_label(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def story_signatures(value: str) -> set[str]:
    """Return conservative product/version fingerprints usable across publishers."""
    signatures = set()
    for name, version in _VERSIONED_NAME.findall(str(value or "")):
        if name.casefold() in _GENERIC_VERSION_NAMES:
            continue
        normalized_version = ".".join(re.findall(r"\d+", version))
        signatures.add(f"{name.casefold()}:{normalized_version}")
    return signatures


def _development_id(*, url: str, label: str) -> str:
    signatures = sorted(story_signatures(label))
    identity = "sig:" + "|".join(signatures) if signatures else ""
    identity = identity or "url:" + canonical_url(url)
    identity = identity or "label:" + normalize_label(label)
    return "dev_" + hashlib.sha256(identity.encode()).hexdigest()[:16]


def _parse_day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _ordered_unique(values) -> list:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _upgrade_story(story: dict) -> dict:
    value = dict(story)
    urls = _ordered_unique([
        text for text in [value.get("url"), *(value.get("urls") or [])]
        if isinstance(text, str) and text.strip()
    ])
    labels = _ordered_unique([
        text for text in [value.get("label"), *(value.get("labels") or [])]
        if isinstance(text, str) and text.strip()
    ])
    value["url"] = urls[0] if urls else ""
    value["label"] = labels[0] if labels else ""
    value["urls"] = urls
    value["labels"] = labels
    value["signatures"] = sorted(set(value.get("signatures") or []).union(
        *(story_signatures(label) for label in labels)
    ))
    value["development_id"] = value.get("development_id") or _development_id(
        url=value["url"], label=value["label"]
    )
    events = [event for event in (value.get("proposal_events") or [])
              if isinstance(event, dict) and event.get("event_id")]
    old_count = max(0, int(value.get("times_proposed") or 0))
    while len(events) < old_count:
        events.append({
            "event_id": f"legacy:{value['development_id']}:{len(events) + 1}",
            "date": value.get("last_proposed") or value.get("first_proposed"),
            "gather_id": None,
            "evidence": "legacy_count",
        })
    value["proposal_events"] = events
    value["times_proposed"] = max(old_count, len(events))
    value.setdefault("first_proposed", None)
    value.setdefault("last_proposed", None)
    event_days = [str(event.get("date")) for event in events if _parse_day(event.get("date"))]
    if event_days:
        value["first_proposed"] = min(
            [day for day in [value.get("first_proposed"), *event_days] if day]
        )
        value["last_proposed"] = max(
            [day for day in [value.get("last_proposed"), *event_days] if day]
        )
    value.setdefault("picked", None)
    value.setdefault("aired", None)
    value["coverage"] = [item for item in (value.get("coverage") or [])
                         if isinstance(item, dict)]
    return value


def _story_urls(story: dict) -> list[str]:
    return [str(value) for value in (story.get("urls") or [story.get("url")]) if value]


def _story_labels(story: dict) -> list[str]:
    return [str(value) for value in (story.get("labels") or [story.get("label")]) if value]


def _merge_into(target: dict, source: dict) -> None:
    target["urls"] = _ordered_unique([*_story_urls(target), *_story_urls(source)])
    target["labels"] = _ordered_unique([*_story_labels(target), *_story_labels(source)])
    target["signatures"] = sorted(set(target.get("signatures") or []).union(
        source.get("signatures") or []
    ))
    target["url"] = target["urls"][0] if target["urls"] else ""
    target["label"] = target["labels"][0] if target["labels"] else ""
    events = {event["event_id"]: event for event in target.get("proposal_events", [])}
    events.update({event["event_id"]: event for event in source.get("proposal_events", [])})
    target["proposal_events"] = list(events.values())
    target["times_proposed"] = max(
        int(target.get("times_proposed") or 0),
        int(source.get("times_proposed") or 0),
        len(events),
    )
    for field, chooser in (("first_proposed", min), ("last_proposed", max),
                           ("picked", min), ("aired", min)):
        values = [str(value) for value in (target.get(field), source.get(field)) if value]
        target[field] = chooser(values) if values else None
    coverage = {
        json.dumps(item, sort_keys=True, separators=(",", ":")): item
        for item in [*target.get("coverage", []), *source.get("coverage", [])]
    }
    target["coverage"] = list(coverage.values())


def find_match(stories: list[dict], *, url: str, label: str) -> dict | None:
    url_key = canonical_url(url)
    if url_key:
        for story in stories:
            if any(canonical_url(old_url) == url_key for old_url in _story_urls(story)):
                return story

    signatures = story_signatures(label)
    if signatures:
        for story in stories:
            if signatures.intersection(story.get("signatures") or []):
                return story

    label_key = normalize_label(label)
    if not label_key:
        return None
    for story in stories:
        if label_key in {normalize_label(old) for old in _story_labels(story)}:
            return story
    domain = registrable_domain(url)
    if not domain:
        return None
    best: tuple[float, dict] | None = None
    for story in stories:
        if not any(registrable_domain(old) == domain for old in _story_urls(story)):
            continue
        old_labels = [normalize_label(old) for old in _story_labels(story)]
        ratio = max((SequenceMatcher(None, label_key, old).ratio()
                     for old in old_labels if old), default=0.0)
        if ratio >= FUZZY_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, story)
    return best[1] if best else None


def _merge_duplicates(stories: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for raw in stories:
        story = _upgrade_story(raw)
        match = find_match(merged, url=story["url"], label=story["label"])
        if match is None:
            merged.append(story)
        else:
            _merge_into(match, story)
    return merged


def load(path: str | Path = LEDGER_FILE) -> dict:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return {"schema_version": SCHEMA_VERSION, "stories": []}
    value = json.loads(ledger_path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("stories", []), list):
        raise ValueError("daily pitch ledger must contain a stories list")
    stories = value.get("stories", [])
    if value.get("schema_version") == SCHEMA_VERSION:
        stories = [_upgrade_story(story) for story in stories]
    else:
        stories = _merge_duplicates(stories)
    return {**value, "schema_version": SCHEMA_VERSION, "stories": stories}


def save(value: dict, path: str | Path = LEDGER_FILE) -> None:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    stories = []
    for raw in value.get("stories", []):
        story = _upgrade_story(raw)
        if story["urls"] == ([story["url"]] if story["url"] else []):
            story.pop("urls")
        if story["labels"] == ([story["label"]] if story["label"] else []):
            story.pop("labels")
        story.pop("signatures", None)  # fully derived from labels on load
        if not story.get("proposal_events"):
            story.pop("proposal_events", None)
        if not story.get("coverage"):
            story.pop("coverage", None)
        stories.append(story)
    value = {**value, "schema_version": SCHEMA_VERSION, "stories": stories}
    temporary = ledger_path.with_name(ledger_path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n")
    temporary.replace(ledger_path)


def prune(stories: list[dict], today: date) -> list[dict]:
    kept = []
    for story in stories:
        if story.get("picked") or story.get("aired"):
            kept.append(story)
            continue
        dates = [parsed for parsed in (
            _parse_day(story.get("last_proposed")),
            _parse_day(story.get("first_proposed")),
        ) if parsed is not None]
        if not dates or (today - max(dates)).days <= KEEP_DAYS:
            kept.append(story)
    return kept


def blocked_reason(story: dict | None) -> str | None:
    if story is None:
        return None
    if story.get("picked"):
        return "picked"
    if story.get("aired"):
        return "aired"
    if int(story.get("times_proposed") or 0) >= RETIRE_AFTER:
        return "retired"
    return None


def _new_entry(*, url: str, label: str, proposed: str | None) -> dict:
    return _upgrade_story({
        "url": str(url or "").strip(),
        "label": str(label or "").strip(),
        "first_proposed": proposed,
        "last_proposed": proposed,
        "times_proposed": 0,
        "picked": None,
        "aired": None,
    })


def _read_options(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not isinstance(value.get("options"), list):
        raise ValueError("daily options must contain an options list")
    return value


def filter_options(options_path: str | Path, ledger_path: str | Path,
                   crawl_path: str | Path) -> int:
    options_file = Path(options_path)
    options = _read_options(options_file)
    ledger = load(ledger_path)
    crawl = json.loads(Path(crawl_path).read_text())
    if not isinstance(crawl, dict) or crawl.get("proposal_freshness", {}).get("status") != "valid":
        raise ValueError("crawl proposal freshness is unavailable")
    excluded_urls = {
        canonical_url(item.get("url", "")): item.get("proposal_exclusion_reason", "ineligible")
        for item in crawl.get("items", []) if isinstance(item, dict)
        and item.get("proposal_eligible") is False and canonical_url(item.get("url", ""))
    }
    kept = []
    removed = 0
    seen_options: list[dict] = []
    gather_id = str(options.get("gather_id") or "")
    for index, option in enumerate(options["options"]):
        if not isinstance(option, dict):
            raise ValueError(f"daily option {index} is not an object")
        label = str(option.get("label") or "").strip()
        url = str(option.get("url") or "").strip()
        if not label or not url:
            raise ValueError(f"daily option {index} is missing label or url")
        match = find_match(ledger["stories"], url=url, label=label)
        same_slate = find_match(seen_options, url=url, label=label)
        already_sent = bool(gather_id and match and any(
            event.get("gather_id") == gather_id for event in match.get("proposal_events", [])
        ))
        development_id = match["development_id"] if match else _development_id(
            url=url, label=label
        )
        if (canonical_url(url) in excluded_urls or blocked_reason(match) or already_sent
                or same_slate is not None):
            removed += 1
            continue
        option["development_id"] = development_id
        seen_options.append(_new_entry(url=url, label=label, proposed=None))
        kept.append(option)
    options["options"] = kept
    temporary = options_file.with_name(options_file.name + ".tmp")
    temporary.write_text(json.dumps(options, indent=1, ensure_ascii=False) + "\n")
    temporary.replace(options_file)
    return removed


def _add_proposal_event(entry: dict, *, event_id: str, day: str,
                        gather_id: str | None, evidence: str) -> bool:
    events = entry.setdefault("proposal_events", [])
    if any(event.get("event_id") == event_id or
           (gather_id and event.get("gather_id") == gather_id) for event in events):
        return False
    events.append({"event_id": event_id, "date": day,
                   "gather_id": gather_id, "evidence": evidence})
    entry["times_proposed"] = max(int(entry.get("times_proposed") or 0), len(events))
    entry["first_proposed"] = min(entry.get("first_proposed") or day, day)
    entry["last_proposed"] = max(entry.get("last_proposed") or day, day)
    return True


def record(options_path: str | Path, ledger_path: str | Path,
           *, today: date | None = None) -> int:
    options = _read_options(options_path)
    day = today or date.today()
    ledger = load(ledger_path)
    ledger["stories"] = prune(ledger["stories"], day)
    for option in options["options"]:
        label = str(option.get("label") or "").strip()
        url = str(option.get("url") or "").strip()
        if not label or not url:
            raise ValueError("daily option is missing label or url")
        entry = find_match(ledger["stories"], url=url, label=label)
        if blocked_reason(entry):
            raise ValueError(f"ineligible option reached record: {label}")
        if entry is None:
            entry = _new_entry(url=url, label=label, proposed=day.isoformat())
            ledger["stories"].append(entry)
        gather_id = str(options.get("gather_id") or "") or None
        event_id = f"sent:{gather_id or day.isoformat()}:{entry['development_id']}"
        _add_proposal_event(entry, event_id=event_id, day=day.isoformat(),
                            gather_id=gather_id, evidence="notify_success")
    save(ledger, ledger_path)
    return 0


def choose(picks_path: str | Path, ledger_path: str | Path,
           *, today: date | None = None) -> int:
    picks = json.loads(Path(picks_path).read_text())
    if not isinstance(picks, dict):
        raise ValueError("daily picks must be an object")
    day = today or date.today()
    ledger = load(ledger_path)
    ledger["stories"] = prune(ledger["stories"], day)
    chosen = [*(picks.get("picks") or []), *(picks.get("overflow") or [])]
    for option in chosen:
        url = str(option.get("url") or "").strip()
        label = str(option.get("label") or "").strip()
        if not url:
            continue
        entry = find_match(ledger["stories"], url=url, label=label)
        if entry is None:
            entry = _new_entry(url=url, label=label, proposed=day.isoformat())
            ledger["stories"].append(entry)
        entry["picked"] = entry.get("picked") or day.isoformat()
    save(ledger, ledger_path)
    return 0


def _mark_entry_aired(ledger: dict, *, url: str, label: str, aired_day: str,
                      coverage: dict | None = None) -> bool:
    if not url and not label:
        return False
    entry = find_match(ledger["stories"], url=url, label=label)
    if entry is None:
        entry = _new_entry(url=url, label=label, proposed=None)
        ledger["stories"].append(entry)
    entry["aired"] = min([value for value in (entry.get("aired"), aired_day) if value])
    if coverage and coverage not in entry["coverage"]:
        entry["coverage"].append(coverage)
    return True


def mark_aired(meta_path: str | Path, ledger_path: str | Path,
               *, today: date | None = None) -> int:
    meta = json.loads(Path(meta_path).read_text())
    if not isinstance(meta, dict):
        raise ValueError("episode metadata must be an object")
    fallback_day = today or date.today()
    aired_day = (_parse_day(meta.get("date")) or fallback_day).isoformat()
    ledger = load(ledger_path)
    ledger["stories"] = prune(ledger["stories"], fallback_day)
    for dive in meta.get("dives") or []:
        label = str(dive.get("story") if isinstance(dive, dict) else dive or "").strip()
        _mark_entry_aired(ledger, url="", label=label, aired_day=aired_day,
                          coverage={"date": aired_day, "level": "dive"})
    for source in meta.get("sources") or []:
        if not isinstance(source, dict):
            continue
        _mark_entry_aired(
            ledger,
            url=str(source.get("url") or "").strip(),
            label=str(source.get("title") or "").strip(),
            aired_day=aired_day,
            coverage={"date": aired_day, "level": "source"},
        )
    save(ledger, ledger_path)
    return 0


def sync_history(history_path: str | Path, archive_dir: str | Path,
                 ledger_path: str | Path, *, today: date | None = None) -> int:
    day = today or date.today()
    ledger = load(ledger_path)
    ledger["stories"] = prune(ledger["stories"], day)
    imported = 0
    history = json.loads(Path(history_path).read_text())
    for episode in history.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        aired_day = str(episode.get("date") or "")
        if not _parse_day(aired_day):
            continue
        for dive in episode.get("dives") or []:
            label = str(dive.get("story") if isinstance(dive, dict) else dive or "").strip()
            imported += _mark_entry_aired(
                ledger, url="", label=label, aired_day=aired_day,
                coverage={"date": aired_day, "level": "dive"},
            )
    # Historical synchronization intentionally uses explicit dives, not every source
    # in every rundown. The live mark-aired command records current episode sources;
    # treating old citations as dives would permanently suppress stories merely named.
    del archive_dir
    save(ledger, ledger_path)
    return imported


def _trace_writes(path: Path):
    for line in path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        # A provider may report a stage-level failure as {"type": "error",
        # "message": "<text>"}; such an event carries no tool_use blocks.
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content", []) if isinstance(message, dict) else []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inputs = block.get("input") or {}
            target = str(inputs.get("file_path") or inputs.get("path") or "")
            if block.get("name") != "Write" or not target.endswith("out/daily_options.json"):
                continue
            try:
                options = json.loads(inputs.get("content", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(options, dict) and isinstance(options.get("options"), list):
                yield str(block.get("id") or "write"), options


def _notify_evidence(run_log: Path) -> tuple[set[str], set[str]]:
    known = set()
    confirmed = set()
    if not run_log.exists():
        return known, confirmed
    for line in run_log.read_text(errors="replace").splitlines():
        if match := _RUN_START.search(line):
            known.add(match.group(1))
        if match := _NOTIFY_OK.search(line):
            confirmed.add(match.group(1))
    return known, confirmed


def backfill_traces(trace_dir: str | Path, run_log: str | Path, ledger_path: str | Path,
                    *, today: date | None = None) -> int:
    day = today or date.today()
    ledger = load(ledger_path)
    ledger["stories"] = prune(ledger["stories"], day)
    known_days, confirmed_days = _notify_evidence(Path(run_log))
    imported = 0
    root = Path(trace_dir)
    if not root.exists():
        save(ledger, ledger_path)
        return 0
    for path in sorted(root.rglob("propose-*.jsonl")):
        stamp = path.parent.name[:8]
        try:
            proposed_day = date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}").isoformat()
        except ValueError:
            continue
        if (day - date.fromisoformat(proposed_day)).days > KEEP_DAYS:
            continue
        if proposed_day in known_days and proposed_day not in confirmed_days:
            continue
        evidence = "confirmed_notify" if proposed_day in confirmed_days else "trace_no_retained_run_log"
        for tool_id, options in _trace_writes(path):
            gather_id = str(options.get("gather_id") or "") or None
            for option in options["options"]:
                if not isinstance(option, dict):
                    continue
                url = str(option.get("url") or "").strip()
                label = str(option.get("label") or "").strip()
                if not url or not label:
                    continue
                entry = find_match(ledger["stories"], url=url, label=label)
                if entry is None:
                    entry = _new_entry(url=url, label=label, proposed=proposed_day)
                    ledger["stories"].append(entry)
                # Schema-1 counts had no provenance. Replace a same-day synthetic
                # count when the original trace supplies the real event identity.
                legacy = next((event for event in entry.get("proposal_events", [])
                               if event.get("evidence") == "legacy_count"
                               and event.get("date") == proposed_day), None)
                if legacy:
                    entry["proposal_events"].remove(legacy)
                    entry["times_proposed"] = len(entry["proposal_events"])
                event_id = f"trace:{path.relative_to(root)}:{tool_id}:{entry['development_id']}"
                imported += _add_proposal_event(
                    entry, event_id=event_id, day=proposed_day,
                    gather_id=gather_id, evidence=evidence,
                )
    save(ledger, ledger_path)
    return imported


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=(
        "filter", "record", "choose", "mark-aired", "sync",
    ))
    parser.add_argument("--options", default="out/daily_options.json")
    parser.add_argument("--picks", default="out/daily_picks.json")
    parser.add_argument("--meta", default="out/episode_meta.json")
    parser.add_argument("--crawl", default="out/crawl.json")
    parser.add_argument("--history", default="history.json")
    parser.add_argument("--archive", default="archive/scripts")
    parser.add_argument("--traces", default="logs/agent-traces")
    parser.add_argument("--run-log", default="logs/run.log")
    parser.add_argument("--file", default=LEDGER_FILE)
    args = parser.parse_args()
    try:
        if args.mode == "filter":
            removed = filter_options(args.options, args.file, args.crawl)
            print(f"daily_ledger: removed={removed}")
            return 0
        if args.mode == "record":
            return record(args.options, args.file)
        if args.mode == "choose":
            return choose(args.picks, args.file)
        if args.mode == "mark-aired":
            return mark_aired(args.meta, args.file)
        synced = sync_history(args.history, args.archive, args.file)
        backfilled = backfill_traces(args.traces, args.run_log, args.file)
        print(f"daily_ledger: synced={synced} backfilled={backfilled}")
        return 0
    except Exception as exc:  # noqa: BLE001 - callers decide stage-specific failure policy
        print(f"daily_ledger: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
