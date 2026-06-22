#!/usr/bin/env python3
"""Unit tests for scripts/build_episode.py — the plain-text -> episode.json/shownotes
converter. Stdlib only; run with `python3 tests/test_build_episode.py`."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_episode as be  # noqa: E402

passed = 0


def check(name, cond):
    global passed
    print(f"  {'ok  ' if cond else 'FAIL'} - {name}")
    if not cond:
        raise SystemExit(f"assertion failed: {name}")
    passed += 1


META = {
    "date": "2026-06-22", "title": "Test Episode",
    "summary": "A two-sentence recap. It covers things.",
    "tts_notes": "Measured energy today.",
    "topics": ["t1"], "entities": ["E1"], "threads": [], "lore": [],
    "sources": [
        {"group": "Papers", "title": "A Paper", "url": "https://example.com/p"},
        {"group": "Releases", "title": "A Release", "url": "https://example.com/r"},
        {"group": "Papers", "title": "No URL skipped", "url": ""},
    ],
}

SCRIPT = """\
A: Good morning, it's Monday.
B: And here's what mattered.

A: The first story is about evals,
which turned out to be subtle.
B: Right.
A:
"""

# --- build(): happy path ------------------------------------------------------
ep, notes, errors, warnings = be.build(SCRIPT, META)
check("no errors on valid input", not errors)
check("first turn speaker A", ep["turns"][0]["speaker"] == "A")
check("four non-empty turns (bare 'A:' dropped)", len(ep["turns"]) == 4)
check("continuation line joined into one turn",
      ep["turns"][2]["text"] == "The first story is about evals, which turned out to be subtle.")
check("tts_notes carried through", ep["tts_notes"] == "Measured energy today.")
check("date/title carried through",
      ep["date"] == "2026-06-22" and ep["title"] == "Test Episode")
check("episode has no sources/topics/lore keys (those stay in meta)",
      set(ep) == {"date", "title", "tts_notes", "turns"})

# --- shownotes ----------------------------------------------------------------
check("shownotes starts with H1 title (publish drops it)", notes.startswith("# Test Episode"))
check("shownotes has the summary", "A two-sentence recap." in notes)
check("shownotes groups Papers then Releases",
      notes.index("## Papers") < notes.index("## Releases"))
check("shownotes links a source", "[A Paper](https://example.com/p)" in notes)
check("shownotes skips a url-less source", "No URL skipped" not in notes)

# --- tts_notes omitted when blank ---------------------------------------------
m2 = dict(META); m2["tts_notes"] = ""
ep2, _, _, _ = be.build(SCRIPT, m2)
check("blank tts_notes omitted from episode", "tts_notes" not in ep2)

# --- missing required field ---------------------------------------------------
m3 = dict(META); del m3["title"]
_, _, errs3, _ = be.build(SCRIPT, m3)
check("missing title is an error", any("title" in e for e in errs3))

# --- no dialogue --------------------------------------------------------------
_, _, errs4, _ = be.build("(just a note, no tags)\n", META)
check("no A:/B: lines is an error", any("turn" in e.lower() for e in errs4))

# --- CLI end-to-end -----------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    sp, mp = os.path.join(d, "s.txt"), os.path.join(d, "m.json")
    epf, nf = os.path.join(d, "e.json"), os.path.join(d, "n.md")
    open(sp, "w").write(SCRIPT)
    json.dump(META, open(mp, "w"))
    rc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_episode.py"),
                         "--script", sp, "--meta", mp, "--episode", epf, "--notes", nf]).returncode
    check("CLI exit 0", rc == 0)
    written = json.load(open(epf))
    check("CLI wrote valid episode.json with turns", len(written["turns"]) == 4)
    check("CLI wrote shownotes.md", os.path.exists(nf) and os.path.getsize(nf) > 0)

    # malformed meta JSON -> exit 1
    open(mp, "w").write("{not json")
    rc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_episode.py"),
                         "--script", sp, "--meta", mp, "--episode", epf, "--notes", nf],
                        capture_output=True).returncode
    check("CLI exit 1 on bad meta JSON", rc == 1)

print(f"\nALL {passed} ASSERTIONS PASSED")
