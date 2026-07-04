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
import os
import re
import sys

# Defaults match the daily envelope: 18-28 min at the ~165-170 wpm Gemini render
# pace, with ~20-22 min the norm. The width is deliberate — the day's material
# decides where in the band an episode lands.
MIN_WORDS = 3000
MAX_WORDS = 4700

# Well-formed audio tags — delivery directions Gemini TTS performs instead of
# reading: short, lowercase, bracketed ([laughs], [sighs], [short pause], ...).
TAG_RE = re.compile(r"\[[a-z][a-z ,'-]{0,38}\]")
# Episode-wide ceiling: more than ~1 tag per 60 spoken words is decoration.
TAG_DENSITY_WORDS = 60

# Phrase-recurrence check: the show's scripts are archived nightly (archive/scripts/);
# a distinctive run of words that today's script shares with two or more recent scripts
# is a verbal tic hardening into formula. Warn-only — technical phrases legitimately
# recur — but the warnings are meant to be acted on when they're real.
SCRIPTS_DIR = "archive/scripts"
RECENT_SCRIPTS = 10
NGRAM = 5
# Fragments that recur by design (the greeting and sign-off are ritual) — a flagged
# phrase containing one of these is dropped, not reported.
RITUAL_FRAGMENTS = ("good morning", "i'm ada", "i'm alan", "stay grounded")

SPEAKER_LINE_RE = re.compile(r"^[AB]\s*:\s?", re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9'-]+")


def _turn_words(text: str) -> list[str]:
    """Normalize one spoken turn to a lowercase word list (audio tags removed)."""
    return WORD_RE.findall(TAG_RE.sub(" ", text).lower())


def _script_ngrams(path: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    """N-grams of an archived script.txt (per line, speaker tags stripped)."""
    grams: set[tuple[str, ...]] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            words = _turn_words(SPEAKER_LINE_RE.sub("", line))
            grams.update(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
    return grams


def recurring_phrases(turns: list[dict], date: str,
                      scripts_dir: str = SCRIPTS_DIR,
                      recent: int = RECENT_SCRIPTS) -> list[str]:
    """Phrases (merged NGRAM runs) today's script shares with >=2 recent scripts."""
    if not os.path.isdir(scripts_dir):
        return []
    # Newest-first by filename (YYYY-MM-DD...); skip today's own archived copy.
    names = sorted(os.listdir(scripts_dir), reverse=True)
    paths = [os.path.join(scripts_dir, f) for f in names
             if f.endswith(".txt") and not f.startswith(str(date))][:recent]
    if len(paths) < 2:
        return []
    past = [_script_ngrams(p) for p in paths]

    flagged: list[str] = []
    for turn in turns:
        words = _turn_words(str(turn.get("text", "")))
        hits = [i for i in range(len(words) - NGRAM + 1)
                if sum(tuple(words[i:i + NGRAM]) in g for g in past) >= 2]
        # Merge overlapping/adjacent flagged n-grams into one readable phrase.
        while hits:
            start = end = hits.pop(0)
            while hits and hits[0] <= end + NGRAM:
                end = hits.pop(0)
            phrase = " ".join(words[start:end + NGRAM])
            if not any(fr in phrase for fr in RITUAL_FRAGMENTS):
                flagged.append(phrase)
    return flagged


# Things TTS would read aloud literally (checked after tags are removed).
ARTIFACT_PATTERNS = [
    (re.compile(r"[*_#`~]"), "markdown characters"),
    (re.compile(r"[\[\]]"), "a stray/malformed bracket (audio tags must be short "
                            "lowercase phrases like [laughs])"),
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

    notes = episode.get("tts_notes", "")
    if not isinstance(notes, str):
        errors.append(f"tts_notes must be a string, got {type(notes).__name__}")
    elif len(notes) > 300:
        warnings.append(f"tts_notes is {len(notes)} chars — keep it to 1-2 sentences "
                        "of mood/tone direction")

    total_words = 0
    total_tags = 0
    run_speaker, run_len = None, 0
    for i, turn in enumerate(turns):
        text = str(turn.get("text", "")).strip()
        speaker = turn.get("speaker")
        if speaker not in ("A", "B"):
            errors.append(f"turn {i}: speaker must be 'A' or 'B', got {speaker!r}")
        if not text:
            errors.append(f"turn {i}: empty text")
            continue
        # Audio tags are delivery directions, not spoken words: count them
        # separately and validate the remaining text without them.
        total_tags += len(TAG_RE.findall(text))
        spoken = TAG_RE.sub(" ", text)
        total_words += len(spoken.split())
        for pattern, label in ARTIFACT_PATTERNS:
            if pattern.search(spoken):
                errors.append(f"turn {i}: contains {label}: {text[:80]!r}")
        if speaker == run_speaker:
            run_len += 1
            if run_len == 3:
                warnings.append(f"turn {i}: 3+ consecutive turns by speaker {speaker}")
        else:
            run_speaker, run_len = speaker, 1

    if total_tags > total_words / TAG_DENSITY_WORDS:
        errors.append(
            f"{total_tags} audio tags for {total_words} words — over the cap of "
            f"~1 per {TAG_DENSITY_WORDS} words; keep tags for moments the writing earns"
        )

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
    ap.add_argument("--scripts-dir", default=SCRIPTS_DIR,
                    help="archived past scripts for the phrase-recurrence warning")
    args = ap.parse_args()

    try:
        with open(args.episode) as f:
            episode = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: can't load {args.episode}: {exc}")
        return 1

    errors, warnings = check(episode, args.min_words, args.max_words)
    repeats = recurring_phrases(episode.get("turns") or [], episode.get("date", ""),
                                scripts_dir=args.scripts_dir)
    if repeats:
        warnings.append(f"{len(repeats)} phrase(s) also appear in 2+ recent scripts — "
                        "a hardening verbal tic; rephrase the real ones:")
        warnings += [f'  recurring: "{p}"' for p in repeats[:15]]
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
