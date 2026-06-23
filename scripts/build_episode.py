#!/usr/bin/env python3
"""Build the renderer's episode.json + shownotes.md from a plain-text script.

The Opus writing session authors two files instead of hand-writing JSON:
  - a plain-text script (out/script.txt) — dialogue as `A:` / `B:` lines, which
    is escaping-safe (no JSON quoting/bracket traps in spoken text), and
  - the memory record (out/episode_meta.json) — date, title, summary, topics,
    entities, threads, lore, plus `sources` (for the show notes) and an optional
    `tts_notes`.
This script deterministically converts those into the two machine artifacts the
rest of the pipeline already consumes:
  - episode.json — {date, title, tts_notes?, turns:[{speaker,text}]} for the TTS
    renderer and the check_episode.py gate, and
  - shownotes.md — title, date, summary, grouped linked sources, for publish.py.

Run it in the writing session right before the gate, so a malformed script is
caught while the agent can still fix it. Same script serves the deep dive via
--script/--meta/--episode/--notes overrides.

Usage:
    python scripts/build_episode.py            # daily defaults
    python scripts/build_episode.py --script out/deepdive_script.txt \
        --meta out/deepdive_meta.json --episode out/deepdive.json \
        --notes out/deepdive_shownotes.md

Exit 0 = built, 1 = the inputs were malformed (message says what to fix).
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# A turn line: a speaker tag (A or B) + ":" + the spoken text. Leading whitespace
# is tolerated; everything after the colon is the line's spoken text.
SPEAKER_RE = re.compile(r"^([AB])\s*:\s?(.*)$")

# Source groups render in this order; any other group follows in first-seen order.
GROUP_ORDER = ["Papers", "Releases", "Discussion", "Industry & Discussion",
               "Primary sources", "Further reading"]


def parse_script(text: str) -> tuple[list[dict], list[str], list[str]]:
    """Parse `A:`/`B:` lines into turns. A non-tag, non-blank line continues the
    current turn (so a wrapped turn still joins into one), which also means a
    forgotten tag merges rather than vanishes — the gate's embedded-label check
    is the backstop. Returns (turns, errors, warnings)."""
    turns: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        m = SPEAKER_RE.match(line)
        if m:
            turns.append({"speaker": m.group(1), "text": m.group(2).strip()})
        elif turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line).strip()
        else:
            errors.append(f"line {n}: text before the first A:/B: speaker tag — {line!r}")
    # A turn that ended up with no spoken text (e.g. a bare "A:") is dropped — a
    # harmless authoring slip, not a build failure.
    empties = sum(1 for t in turns if not t["text"])
    if empties:
        warnings.append(f"dropped {empties} empty turn(s) — a speaker tag with no text")
    kept = [t for t in turns if t["text"]]
    if not kept:
        errors.append("no dialogue turns found — script must have A:/B: lines")
    return kept, errors, warnings


def render_shownotes(meta: dict) -> str:
    """title (H1, dropped by publish), date, summary, then grouped linked sources."""
    title = meta.get("title", "").strip()
    date = meta.get("date", "").strip()
    summary = (meta.get("summary") or "").strip()
    out = [f"# {title}", "", f"*{date}*", "", summary, ""]

    # sources: a flat list of {group, title, url}. Group in GROUP_ORDER, then any
    # remaining groups in first-seen order; skip entries missing a url.
    by_group: dict[str, list[dict]] = {}
    for s in meta.get("sources", []) or []:
        if not s.get("url"):
            continue
        by_group.setdefault(s.get("group", "Sources"), []).append(s)
    ordered = [g for g in GROUP_ORDER if g in by_group]
    ordered += [g for g in by_group if g not in ordered]
    for g in ordered:
        out.append(f"## {g}")
        for s in by_group[g]:
            out.append(f"- [{s.get('title', s['url']).strip()}]({s['url'].strip()})")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build(script_text: str, meta: dict) -> tuple[dict, str, list[str], list[str]]:
    """Return (episode, shownotes_md, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    turns, perrs, pwarns = parse_script(script_text)
    errors += perrs
    warnings += pwarns

    for key in ("date", "title"):
        if not (meta.get(key) or "").strip():
            errors.append(f"episode_meta.json is missing required '{key}'")
    if not (meta.get("summary") or "").strip():
        warnings.append("episode_meta.json has no 'summary' — show notes will have an empty lead")
    if not (meta.get("sources") or []):
        warnings.append("episode_meta.json has no 'sources' — show notes will list none")

    episode = {"date": meta.get("date", ""), "title": meta.get("title", "")}
    tts = (meta.get("tts_notes") or "").strip()
    if tts:
        episode["tts_notes"] = tts
    episode["turns"] = turns

    shownotes = render_shownotes(meta)
    return episode, shownotes, errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", default="out/script.txt")
    ap.add_argument("--meta", default="out/episode_meta.json")
    ap.add_argument("--episode", default="out/episode.json")
    ap.add_argument("--notes", default="out/shownotes.md")
    args = ap.parse_args()

    try:
        with open(args.script, encoding="utf-8") as f:
            script_text = f.read()
    except FileNotFoundError:
        print(f"FAIL: script not found: {args.script}", file=sys.stderr)
        return 1
    try:
        with open(args.meta, encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        print(f"FAIL: meta not found: {args.meta}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"FAIL: {args.meta} is not valid JSON: {e}", file=sys.stderr)
        return 1

    episode, shownotes, errors, warnings = build(script_text, meta)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        print("FAIL: could not build episode:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    with open(args.episode, "w", encoding="utf-8") as f:
        json.dump(episode, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(args.notes, "w", encoding="utf-8") as f:
        f.write(shownotes)

    words = sum(len(t["text"].split()) for t in episode["turns"])
    print(f"Built {args.episode} ({len(episode['turns'])} turns, ~{words} words) "
          f"and {args.notes}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
