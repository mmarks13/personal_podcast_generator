#!/usr/bin/env python3
"""Unit tests for scripts/check_episode.py — the pre-render gate. Run with
`python3 tests/test_check_episode.py` (uses the venv-independent stdlib except the
optional yaml import inside pronunciation_warnings)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_episode as ce  # noqa: E402

passed = 0


def check(name, cond):
    global passed
    print(f"  {'ok  ' if cond else 'FAIL'} - {name}")
    if not cond:
        raise SystemExit(f"assertion failed: {name}")
    passed += 1


def episode(turns, **kw):
    return {"date": "2026-07-05", "title": "T", "turns": turns, **kw}


def words(n):
    return " ".join(["word"] * n)


# --- schema / speakers -------------------------------------------------------
errs, _ = ce.check(episode([{"speaker": "A", "text": words(10)},
                            {"speaker": "C", "text": words(10)}]), 1, 100)
check("speaker C (guest) is valid", not any("speaker" in e for e in errs))

errs, _ = ce.check(episode([{"speaker": "D", "text": "hi there"}]), 1, 100)
check("unknown speaker fails", any("speaker" in e for e in errs))

errs, _ = ce.check({"date": "bad", "title": "", "turns": [{"speaker": "A", "text": "x"}]}, 1, 100)
check("bad date + empty title fail", len([e for e in errs if "date" in e or "title" in e]) == 2)

# --- word band ----------------------------------------------------------------
errs, _ = ce.check(episode([{"speaker": "A", "text": words(50)}]), 100, 200)
check("under floor fails", any("floor" in e for e in errs))
errs, _ = ce.check(episode([{"speaker": "A", "text": words(300)}]), 100, 200)
check("over cap fails", any("cap" in e for e in errs))
errs, _ = ce.check(episode([{"speaker": "A", "text": words(150)}]), 100, 200)
check("in band passes", not errs)

# --- audio tags ----------------------------------------------------------------
t = [{"speaker": "A", "text": "[laughs] " + words(100)}]
errs, _ = ce.check(episode(t), 1, 1000)
check("well-formed tag ok at low density", not errs)
t = [{"speaker": "A", "text": "[laughs] [sighs] [wry] " + words(60)}]
errs, _ = ce.check(episode(t), 1, 1000)
check("tag density over ~1/60 words fails", any("audio tags" in e for e in errs))

# --- TTS artifacts -------------------------------------------------------------
for bad, label in [("see https://x.com now", "URL"),
                   ("some *markdown* here", "markdown"),
                   ("a [Broken Tag] here", "bracket")]:
    errs, _ = ce.check(episode([{"speaker": "A", "text": bad + " " + words(10)}]), 1, 1000)
    check(f"artifact caught: {label}", bool(errs))

# --- phrase recurrence ----------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    for i, day in enumerate(("2026-07-01", "2026-07-02")):
        with open(os.path.join(d, f"{day}.txt"), "w") as f:
            f.write("A: Good morning — it's a day. I'm Ada.\n"
                    "B: the whole ballgame right there my friend\n")
    turns = [{"speaker": "A", "text": "Good morning — it's a day. I'm Ada."},
             {"speaker": "B", "text": "that is the whole ballgame right there my friend"}]
    rep = ce.recurring_phrases(turns, "2026-07-05", scripts_dir=d)
    check("recurring phrase flagged", any("ballgame" in p for p in rep))
    check("ritual greeting whitelisted", not any("good morning" in p for p in rep))
    rep = ce.recurring_phrases(turns, "2026-07-01", scripts_dir=d)  # same-date excluded
    check("same-date script excluded (needs 2+ others)", rep == [])
check("missing scripts dir is a no-op", ce.recurring_phrases(turns, "2026-07-05",
                                                             scripts_dir="/nonexistent") == [])

# --- pronunciations --------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    lex = os.path.join(d, "p.yaml")
    with open(lex, "w") as f:
        f.write('Aramco: "ah-RAHM-koh"\n')
    warns = ce.pronunciation_warnings([{"speaker": "A", "text": "Aramco led the round."}], path=lex)
    check("known mispronunciation warned", len(warns) == 1 and "ah-RAHM-koh" in warns[0])
    warns = ce.pronunciation_warnings([{"speaker": "A", "text": "ah-RAHM-koh led it."}], path=lex)
    check("speakable form passes clean", warns == [])
check("missing lexicon is a no-op", ce.pronunciation_warnings(
    [{"speaker": "A", "text": "Aramco"}], path="/nonexistent") == [])

print(f"\nALL {passed} ASSERTIONS PASSED")
