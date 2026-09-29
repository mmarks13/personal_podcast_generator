#!/usr/bin/env python3
"""Turn the listener's editorial note into tonight's word band, and record it.

A note outranks the skill's editorial guidance, and length is the one piece of that
guidance the writer cannot simply obey: `check_episode.py` hard-fails the run before TTS
if the script misses the band, so a note asking for twelve minutes would either be ignored
or cost the whole episode. So the harness reads the request, converts it, clamps it to what
the show can still render, and hands the same numbers to both the writer and the gate. The
gate therefore stays an independent check — the writer never chooses the bar it is judged
against.

Only a number with a unit counts, because prose has to stay prose: "open cold and stay
skeptical" moves nothing, and the note still steers length inside whatever band applies.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# The Gemini render pace. check_episode.py prints minutes at a rounder 150 wpm for the
# log line; conversions that decide a band use the real number.
WPM = 165

# Absolute bounds, in words: ~10 to ~35 minutes. Below ten minutes it stops being the
# show; above thirty-five the TTS render time and the Gemini credits behind it climb
# steeply for an episode nobody asked to be that long.
ABS_MIN_WORDS = 1700
ABS_MAX_WORDS = 5900

# A single figure is a target, not a band. ±12% is tight enough that the request is
# actually honored and wide enough to land on without padding or cutting mid-thought.
TOLERANCE = 0.12
# Clamping a wild request can flatten the band to nothing, which no script can satisfy.
MIN_WIDTH = 600

_REQUEST = re.compile(
    r"(\d{1,5})\s*(?:-|–|to)?\s*(\d{1,5})?\s*(minutes|minute|mins|min|words|word)\b",
    re.IGNORECASE,
)


def band_from_note(text: str) -> tuple[int, int, bool] | None:
    """(min_words, max_words, reduced) the note asked for, or None if it asked nothing.

    `reduced` says the request was larger than the show can render and was brought down,
    which the caller reports so the shortfall is never silent.
    """
    match = _REQUEST.search(text or "")
    if not match:
        return None
    unit = match.group(3).lower()
    scale = 1 if unit.startswith("word") else WPM
    low = int(match.group(1)) * scale
    high = int(match.group(2)) * scale if match.group(2) else None

    if high is None:
        low, high = round(low * (1 - TOLERANCE)), round(low * (1 + TOLERANCE))
    elif high < low:
        low, high = high, low

    # A figure under the floor is read as a segment ("spend five minutes on the IPO"),
    # not as the length of the whole show, and moves nothing. Clamping it up would turn
    # the commonest phrasing in an editorial note into a ten-minute episode.
    if high < ABS_MIN_WORDS:
        return None

    reduced = high > ABS_MAX_WORDS
    high = min(high, ABS_MAX_WORDS)
    low = max(ABS_MIN_WORDS, min(low, ABS_MAX_WORDS))
    if high - low < MIN_WIDTH:
        low = max(ABS_MIN_WORDS, high - MIN_WIDTH)
    return low, high, reduced


def note_from_picks(path: Path) -> str:
    """The daily note, which travels inside the picks file the writer already reads."""
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return str((value or {}).get("note") or "") if isinstance(value, dict) else ""


def read_note(path: Path) -> str:
    if path.suffix == ".json":
        return note_from_picks(path)
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def stamp(meta_path: Path, note: str, band: tuple[int, int] | None) -> bool:
    """Record on the episode what direction produced it. Never fails the run."""
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(meta, dict):
        return False
    meta["listener_note"] = note or None
    meta["word_band"] = list(band) if band else None
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", type=Path, required=True,
                        help="out/daily_picks.json or out/deepdive_note.txt")
    parser.add_argument("--meta", type=Path,
                        help="stamp the note and band onto this episode meta instead")
    args = parser.parse_args()
    note = read_note(args.note)
    band = band_from_note(note)
    if args.meta:
        stamp(args.meta, note, band[:2] if band else None)
        return 0
    # stdout is the band for the shell: "min max reduced", or nothing at all.
    if band:
        print(f"{band[0]} {band[1]} {int(band[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
