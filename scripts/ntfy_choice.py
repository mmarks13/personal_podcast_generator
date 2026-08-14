#!/usr/bin/env python3
"""Read the listener's picks from the ntfy topic.

Each evening `run_episode.sh propose` pushes one message carrying up to two slates:
tonight's candidate mini-dives, **numbered** 1-15 (out/daily_options.json), and — on
Tue/Fri/Sat, for the next morning's deep dive — candidate topics **lettered** A-F
(out/deepdive_options.json). Both files carry the `sent_at` epoch that bounds the
reply window. The listener answers with a single message:

    1,3          tonight's dives are stories 1 and 3
    3, 14. A     ...punctuate however you like; picks are picks
    1,12 B       ...and tomorrow's deep dive is topic B
    B            deep dive only
    <free text>  a mini-dive of the listener's own, in their words
    dd <topic>   a deep-dive topic of their own

The 04:00 run calls this twice with `--kind`. Numbers and bare free text belong to
the daily slate (the every-night lever); letters and the `dd` prefix belong to the
deep dive. `--kind deepdive` prints the chosen topic to stdout, as it always has;
`--kind daily` writes the chosen story records to out/daily_picks.json for the
writer to read, and prints a one-line summary for the run log. A wide slate goes
out as two pushes, so each half takes the newest reply that actually answers it
rather than the newest reply overall — answering the two pushes separately works,
and a later message still corrects an earlier one within its own half.

Prints nothing when there is no reply (or no options file) — the writer then picks,
which is the status quo. Always exits 0: a broken channel must never block an episode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh")
DAILY_OPTIONS = "out/daily_options.json"
DAILY_PICKS = "out/daily_picks.json"
DEEPDIVE_OPTIONS = "out/deepdive_options.json"
MAX_PICKS = 3  # the show carries 2-3 mini-dives; extras become rundown lines

# A pick is a mini-dive number (1-15) or a deep-dive letter standing on its own. The
# negative lookahead is what keeps "dd tokenizers" from being read as option D followed
# by "d tokenizers"; the two-digit form leads the alternation so "12" is never read as
# a bare "1". `(?!\w)` rather than `(?![^\s,])` because people punctuate: "3, 14. A" is
# a perfectly ordinary way to answer, and requiring a space or comma after every pick
# silently threw away everything from the period onward.
_PICK = r"(?:1[0-5]|[1-9]|[A-Fa-f])(?!\w)"
_SEP = r"(?:[\s,;:.&/+·—-]|\band\b)+"
_PICK_RUN = re.compile(rf"^\s*({_PICK}(?:{_SEP}{_PICK})*)")
_LEADING_SEP = re.compile(rf"^{_SEP}")
_DD_PREFIX = re.compile(r"^dd\b[:\s]*(.*)$", re.IGNORECASE | re.DOTALL)
# Free text has to look like words before it becomes a locked dive. Stray fragments
# ("14. A") must never reach the writer as an instruction to go dive something.
_HAS_WORD = re.compile(r"[A-Za-z]{3}")


def parse_reply(text: str) -> dict:
    """Split a reply into daily picks, a deep-dive pick, and either kind of free text."""
    text = (text or "").strip()
    numbers: list[int] = []
    letters: list[int] = []
    rest = text
    run = _PICK_RUN.match(text)
    if run:
        picks = run.group(1)
        rest = _LEADING_SEP.sub("", text[run.end():])
        # "A shorter show please" opens with the English article, not option A. A lone
        # leading "a" followed by prose is prose; every other reading loses the message.
        if rest and picks.strip().lower() == "a" and not _DD_PREFIX.match(rest):
            rest = text
        else:
            for tok in re.split(_SEP, picks):
                if tok.isdigit():
                    numbers.append(int(tok))
                elif tok:
                    letters.append(ord(tok.upper()) - 64)

    daily_text = deepdive_text = None
    dd = _DD_PREFIX.match(rest)
    if dd:
        deepdive_text = dd.group(1).strip() or None
    elif _HAS_WORD.search(rest):  # a mini-dive in the listener's own words
        daily_text = rest
    return {"numbers": numbers, "letters": letters,
            "daily_text": daily_text, "deepdive_text": deepdive_text}


def load_options(path: str) -> dict | None:
    try:
        return json.load(open(path))
    except Exception:  # noqa: BLE001
        return None


def fetch_replies(sent_at: int) -> list[str]:
    """Every listener message since the push, oldest first. Never raises."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return []
    try:
        url = f"{NTFY_BASE}/{topic}/json?poll=1&since={sent_at or '12h'}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            lines = resp.read().decode().splitlines()
    except Exception as exc:  # noqa: BLE001
        print(f"ntfy_choice: {exc}", file=sys.stderr)
        return []

    replies = []
    for line in lines:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("event") != "message" or "bot" in (msg.get("tags") or []):
            continue  # the pipeline's own pushes are tagged "bot" by notify.py
        if msg.get("time", 0) < sent_at:
            continue
        text = (msg.get("message") or "").strip()
        if text:
            replies.append(text)
    return replies


def latest_answering(replies: list[str], answers) -> dict | None:
    """The most recent reply that actually answers this half of the slate.

    A wide slate arrives as two pushes, so replying to each one separately is the
    natural thing to do — and a plain latest-wins rule would throw the first away.
    Each half takes the newest reply that speaks to it, which still lets a later
    message correct an earlier one within that half.
    """
    for text in reversed(replies):
        parsed = parse_reply(text)
        if answers(parsed):
            return parsed
    return None


def run_daily(options_path: str, picks_path: str) -> int:
    # DAILY_DIVES overrides the phone for manual reruns, mirroring DEEPDIVE_TOPIC —
    # the ntfy reply has usually aged out by the time a failed night is re-run.
    override = os.environ.get("DAILY_DIVES", "").strip()
    opts = load_options(options_path)
    if override:
        parsed = parse_reply(override)
    else:
        if not opts:
            return 0
        parsed = latest_answering(fetch_replies(int(opts.get("sent_at", 0))),
                                  lambda p: p["numbers"] or p["daily_text"])
        if parsed is None:
            return 0

    by_n = {o.get("n"): o for o in (opts or {}).get("options", [])}
    chosen, seen = [], set()
    for n in parsed["numbers"]:
        if n in by_n and n not in seen:
            seen.add(n)
            chosen.append(by_n[n])
    if not chosen and not parsed["daily_text"]:
        return 0

    result = {"picks": chosen[:MAX_PICKS], "free_text": parsed["daily_text"],
              "overflow": chosen[MAX_PICKS:]}
    json.dump(result, open(picks_path, "w"), indent=1, ensure_ascii=False)

    summary = [f"#{o['n']} {o.get('label', '')}" for o in result["picks"]]
    if result["free_text"]:
        summary.append(f"free: {result['free_text']}")
    if result["overflow"]:
        summary.append(f"overflow: {len(result['overflow'])}")
    print(" | ".join(summary))
    return 0


def run_deepdive(options_path: str) -> int:
    opts = load_options(options_path)
    if not opts:
        return 0
    parsed = latest_answering(fetch_replies(int(opts.get("sent_at", 0))),
                              lambda p: p["letters"] or p["deepdive_text"])
    if parsed is None:
        return 0
    by_n = {o.get("n"): o for o in opts.get("options", [])}
    for n in parsed["letters"]:
        if n in by_n and by_n[n].get("topic"):
            print(by_n[n]["topic"])
            return 0
    if parsed["deepdive_text"]:
        print(parsed["deepdive_text"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["daily", "deepdive"], default="deepdive")
    ap.add_argument("--options", default=None)
    ap.add_argument("--picks", default=DAILY_PICKS)
    args = ap.parse_args()
    if args.kind == "daily":
        return run_daily(args.options or DAILY_OPTIONS, args.picks)
    return run_deepdive(args.options or DEEPDIVE_OPTIONS)


if __name__ == "__main__":
    raise SystemExit(main())
