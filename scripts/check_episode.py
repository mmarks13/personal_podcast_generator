#!/usr/bin/env python3
"""Deterministic pre-render checks for an episode.json.

The skill's writing rules (length band, plain spoken prose, A/B speakers) are
instructions to a model — this script makes the ones a machine can verify into a
hard gate before TTS, so an under-length or markdown-littered script never gets
rendered. Run it after writing episode.json; on failure, revise and re-run.

Usage:
    python scripts/check_episode.py --episode out/episode.json
    python scripts/check_episode.py --episode out/deepdive.json --min-words 2800 --max-words 4200

Exit 0 = pass (warnings allowed), 1 = fail.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Defaults match the daily target: 18-22 min at ~150 wpm, with headroom for an
# occasional deep-dive segment (up to ~25 min).
MIN_WORDS = 2700
MAX_WORDS = 3900

# Things TTS would read aloud literally.
ARTIFACT_PATTERNS = [
    (re.compile(r"[*_#`~]|\[|\]"), "markdown/stage-direction characters"),
    (re.compile(r"https?://"), "a URL (don't read URLs aloud)"),
    (re.compile(r"\bHOST_[AB]\b", re.IGNORECASE), "a speaker label inside the text"),
    (re.compile(r"\n"), "an embedded newline"),
]


def check(episode: dict, min_words: int, max_words: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(episode.get("date", ""))):
        errors.append(f"date is missing or not YYYY-MM-DD: {episode.get('date')!r}")
    if not str(episode.get("title", "")).strip():
        errors.append("title is missing or empty")

    turns = episode.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append("turns is missing or empty")
        return errors, warnings

    total_words = 0
    run_speaker, run_len = None, 0
    for i, turn in enumerate(turns):
        text = str(turn.get("text", "")).strip()
        speaker = turn.get("speaker")
        if speaker not in ("A", "B"):
            errors.append(f"turn {i}: speaker must be 'A' or 'B', got {speaker!r}")
        if not text:
            errors.append(f"turn {i}: empty text")
            continue
        total_words += len(text.split())
        for pattern, label in ARTIFACT_PATTERNS:
            if pattern.search(text):
                errors.append(f"turn {i}: contains {label}: {text[:80]!r}")
        if speaker == run_speaker:
            run_len += 1
            if run_len == 3:
                warnings.append(f"turn {i}: 3+ consecutive turns by speaker {speaker}")
        else:
            run_speaker, run_len = speaker, 1

    if total_words < min_words:
        errors.append(
            f"script is {total_words} words — below the {min_words}-word floor "
            f"(~{total_words / 150:.0f} min at 150 wpm); expand coverage, don't pad"
        )
    elif total_words > max_words:
        errors.append(f"script is {total_words} words — above the {max_words}-word cap; tighten")
    else:
        print(f"word count: {total_words} (~{total_words / 150:.0f} min at 150 wpm)")

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="out/episode.json")
    ap.add_argument("--min-words", type=int, default=MIN_WORDS)
    ap.add_argument("--max-words", type=int, default=MAX_WORDS)
    args = ap.parse_args()

    try:
        with open(args.episode) as f:
            episode = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: can't load {args.episode}: {exc}")
        return 1

    errors, warnings = check(episode, args.min_words, args.max_words)
    for w in warnings:
        print(f"  warn: {w}")
    for e in errors:
        print(f"  FAIL: {e}")
    if errors:
        print(f"{args.episode}: {len(errors)} problem(s) — fix and re-run.")
        return 1
    print(f"{args.episode}: OK ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
