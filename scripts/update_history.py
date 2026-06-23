#!/usr/bin/env python3
"""Maintain the show's long-term memory: history.json.

This is the deterministic bookkeeping half of the show's memory. The *editorial*
half — deciding what a story arc means, what to recall, how to cover a thread as it
moves — is the skill's job (Claude). This script only does the mechanical upkeep so
Claude doesn't waste tokens on it:

  --append   Add today's episode to the detailed window (called after the script is
             written). Reads the day's topics/threads/entities from a small JSON the
             skill emits (out/episode_meta.json), or from flags.
  (default)  Roll-off pass: any episode in `episodes` older than KEEP_DAYS is folded
             into `longterm` (entities rolled up, milestones kept, monthly rollup
             extended) and dropped from the detailed list. Idempotent.

Memory model (history.json):
{
  "episodes": [                      # detailed window, newest-first, <= ~KEEP_DAYS old
    {"date","title","summary","topics":[...],"entities":[...],"threads":[...]}
  ],
  "longterm": {
    "active_threads":  [ {"name","status","last_seen","arc"} ],   # capped
    "entities":        [ {"name","note","last_seen"} ],           # roster, capped
    "monthly":         [ {"month":"YYYY-MM","summary"} ],         # one line per month
    "host_lore":       [ {"host","type","note","last_seen"} ],    # host canon, capped
    "updated": "YYYY-MM-DD"
  }
}

The skill READS this file before writing an episode (to stay non-repetitive and pick up
arcs), and the run calls this script to keep it bounded. Caps keep what Claude reads
each night small.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta

HISTORY_FILE = "history.json"
# Audio tags ([laughs], [sighs], ...) are TTS delivery directions; if the skill
# quotes dialogue into meta fields, they must not enter the show's memory.
TAG_RE = re.compile(r"\[[a-z][a-z ,'-]{0,38}\]")
KEEP_DAYS = 30           # detailed window
MAX_THREADS = 15         # active_threads cap
MAX_ENTITIES = 40        # entity roster cap
MAX_LORE = 40            # host canon cap (~years at the intended reveal rate)
# The only fields that belong in the show's memory. episode_meta.json may also
# carry `sources` / `tts_notes` (for the show notes and the renderer), which must
# not leak into history.json — it is re-read into context every run.
STORE_KEYS = ("date", "kind", "title", "summary", "topics", "entities", "threads", "lore")


def _strip_tags(value):
    """Recursively remove audio tags from every string in a JSON-ish structure."""
    if isinstance(value, str):
        return re.sub(r"\s{2,}", " ", TAG_RE.sub("", value)).strip()
    if isinstance(value, list):
        return [_strip_tags(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_tags(v) for k, v in value.items()}
    return value


def _empty() -> dict:
    return {"episodes": [], "longterm": {
        "active_threads": [], "entities": [], "monthly": [], "host_lore": [],
        "updated": ""}}


def load(path: str = HISTORY_FILE) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        data.setdefault("episodes", [])
        lt = data.setdefault("longterm", {})
        lt.setdefault("active_threads", [])
        lt.setdefault("entities", [])
        lt.setdefault("monthly", [])
        lt.setdefault("host_lore", [])
        lt.setdefault("updated", "")
        return data
    return _empty()


def save(data: dict, path: str = HISTORY_FILE) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date()


def append_episode(data: dict, ep: dict) -> dict:
    """Insert/replace an episode in the detailed window (newest-first).

    Dedup key is (date, kind) so a weekend deep-dive episode ("kind": "deepdive"
    in its meta) coexists with that day's daily record instead of replacing it.
    """
    key = (ep["date"], ep.get("kind", "daily"))
    data["episodes"] = [
        e for e in data["episodes"]
        if (e.get("date"), e.get("kind", "daily")) != key
    ]
    data["episodes"].append(ep)
    data["episodes"].sort(key=lambda e: e["date"], reverse=True)
    return data


def roll_off(data: dict, today: date, keep_days: int = KEEP_DAYS) -> dict:
    """Fold episodes older than keep_days into longterm, then drop them from detail."""
    cutoff = today - timedelta(days=keep_days)
    lt = data["longterm"]
    keep, aged = [], []
    for e in data["episodes"]:
        (aged if _parse_date(e["date"]) < cutoff else keep).append(e)

    # Merge aged episodes into the monthly rollup (one entry per YYYY-MM).
    by_month: dict[str, list[dict]] = {}
    for e in aged:
        by_month.setdefault(e["date"][:7], []).append(e)
    monthly = {m["month"]: m for m in lt["monthly"]}
    for month, eps in sorted(by_month.items()):
        # Major milestones only: titles of the aged episodes that quarter, deduped.
        titles = [e.get("title", "").strip() for e in eps if e.get("title")]
        line = "; ".join(dict.fromkeys(titles))[:600]
        prev = monthly.get(month, {}).get("summary", "")
        merged = (prev + ("; " if prev and line else "") + line)[:800]
        monthly[month] = {"month": month, "summary": merged}
    lt["monthly"] = [monthly[m] for m in sorted(monthly)]

    # Refresh entity roster + thread last_seen from aged episodes (so old arcs persist).
    ents = {x["name"].lower(): x for x in lt["entities"]}
    for e in aged:
        for name in e.get("entities", []):
            k = name.lower()
            row = ents.setdefault(k, {"name": name, "note": "", "last_seen": e["date"]})
            row["last_seen"] = max(row["last_seen"], e["date"])
    lt["entities"] = sorted(ents.values(), key=lambda x: x["last_seen"], reverse=True)[:MAX_ENTITIES]
    lt["active_threads"] = sorted(
        lt["active_threads"], key=lambda t: t.get("last_seen", ""), reverse=True)[:MAX_THREADS]

    # Preserve host canon: fold aged episodes' lore into the long-term list. Oldest
    # entries are evicted last only by the cap — canon should outlive the 30-day window.
    for e in aged:
        for item in e.get("lore", []):
            lt["host_lore"].append({**item, "last_seen": e["date"]})
    lt["host_lore"] = sorted(
        lt["host_lore"], key=lambda x: x.get("last_seen", ""), reverse=True)[:MAX_LORE]

    lt["updated"] = today.isoformat()
    data["episodes"] = keep
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--append", action="store_true",
                    help="append today's episode (from out/episode_meta.json) then roll off")
    ap.add_argument("--meta", default="out/episode_meta.json",
                    help="JSON the skill emits: {date,title,summary,topics,entities,threads}")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD; default = system date")
    ap.add_argument("--file", default=HISTORY_FILE)
    args = ap.parse_args()

    today = _parse_date(args.today) if args.today else date.today()
    data = load(args.file)

    if args.append:
        if not os.path.exists(args.meta):
            print(f"WARNING: {args.meta} not found; skipping append (roll-off only).")
        else:
            with open(args.meta) as f:
                ep = _strip_tags(json.load(f))
            # Keep only the show-memory fields (drop sources/tts_notes etc.).
            ep = {k: v for k, v in ep.items() if k in STORE_KEYS}
            ep.setdefault("date", today.isoformat())
            for key in ("topics", "entities", "threads"):
                ep.setdefault(key, [])
            data = append_episode(data, ep)
            # Promote/refresh any named threads the episode carried.
            threads = {t["name"].lower(): t for t in data["longterm"]["active_threads"]}
            for t in ep.get("threads", []):
                if isinstance(t, str):
                    t = {"name": t, "status": "", "arc": ""}
                k = t["name"].lower()
                row = threads.get(k, {"name": t["name"], "status": "", "arc": ""})
                row.update({kk: vv for kk, vv in t.items() if vv})
                row["last_seen"] = ep["date"]
                threads[k] = row
            data["longterm"]["active_threads"] = list(threads.values())
            print(f"Appended episode {ep['date']} ({len(ep.get('topics', []))} topics, "
                  f"{len(ep.get('threads', []))} threads).")

    before = len(data["episodes"])
    data = roll_off(data, today)
    print(f"Roll-off: {before} -> {len(data['episodes'])} episodes in detailed window; "
          f"{len(data['longterm']['active_threads'])} threads, "
          f"{len(data['longterm']['entities'])} entities, "
          f"{len(data['longterm']['monthly'])} months in longterm.")

    save(data, args.file)
    print(f"Wrote {args.file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
