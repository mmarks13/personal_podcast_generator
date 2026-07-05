#!/usr/bin/env python3
"""Unit tests for scripts/proposal_ledger.py — the deep-dive proposal memory and
the ntfy reply resolution. Stdlib only; run with
`python3 tests/test_proposal_ledger.py`."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import proposal_ledger as pl  # noqa: E402

passed = 0


def check(name, cond):
    global passed
    print(f"  {'ok  ' if cond else 'FAIL'} - {name}")
    if not cond:
        raise SystemExit(f"assertion failed: {name}")
    passed += 1


with tempfile.TemporaryDirectory() as d:
    ledger = os.path.join(d, "ledger.json")
    options = os.path.join(d, "opts.json")

    # Seed: one retired topic (3 unchosen), one previously chosen.
    json.dump({"topics": [
        {"topic": "Old Topic", "type": "history", "times_proposed": 3, "chosen": None},
        {"topic": "Picked Once", "type": "mechanism", "times_proposed": 1,
         "chosen": "2026-06-25"},
    ]}, open(ledger, "w"))
    json.dump({"options": [
        {"n": 1, "type": "mechanism", "topic": "Fresh Idea", "pitch": "p1"},
        {"n": 2, "type": "history", "topic": "old topic", "pitch": "retired, drop me"},
        {"n": 3, "type": "debate", "topic": "Second Fresh", "pitch": "p3"},
    ]}, open(options, "w"))

    # --- record: filter retired, renumber, stamp, count -------------------------
    pl.record(options, ledger)
    opts = json.load(open(options))
    led = {t["topic"]: t for t in json.load(open(ledger))["topics"]}
    check("retired topic dropped from slate",
          [o["topic"] for o in opts["options"]] == ["Fresh Idea", "Second Fresh"])
    check("survivors renumbered 1..n", [o["n"] for o in opts["options"]] == [1, 2])
    check("sent_at stamped", opts.get("sent_at", 0) > 0)
    check("kept topics counted", led["Fresh Idea"]["times_proposed"] == 1)
    check("dropped topic not re-counted", led["Old Topic"]["times_proposed"] == 3)

    # retirement boundary: 2 proposals is still eligible, 3rd makes it retired
    check("is_retired at threshold", pl.is_retired({"times_proposed": 3, "chosen": None}))
    check("chosen never retires", not pl.is_retired({"times_proposed": 5,
                                                     "chosen": "2026-07-01"}))
    check("under threshold not retired", not pl.is_retired({"times_proposed": 2,
                                                            "chosen": None}))

    # --- choose: mark chosen; free text adds listener entry ----------------------
    pl.choose("fresh idea", ledger)   # case/punct-insensitive match
    pl.choose("My Own Thing", ledger)
    led = {t["topic"]: t for t in json.load(open(ledger))["topics"]}
    check("numbered choice marked chosen", bool(led["Fresh Idea"]["chosen"]))
    check("free-text choice recorded as listener entry",
          led["My Own Thing"]["type"] == "listener" and led["My Own Thing"]["chosen"])

# --- resolve_reply (pure function; no network) ----------------------------------
opts = {"sent_at": 1000,
        "options": [{"n": 1, "topic": "topic one"}, {"n": 2, "topic": "topic two"}]}
msgs = [
    {"event": "message", "time": 1100, "tags": ["bot"], "message": "the options push"},
    {"event": "message", "time": 1200, "message": "2"},
]
check("number resolves to that option", pl.resolve_reply(msgs, opts) == "topic two")
check("bot-tagged messages ignored",
      pl.resolve_reply([msgs[0]], opts) == "")
check("pre-sent_at replies ignored",
      pl.resolve_reply([{"event": "message", "time": 900, "message": "1"}], opts) == "")
check("free text used verbatim",
      pl.resolve_reply([{"event": "message", "time": 1300,
                         "message": "quantization deep dive"}], opts)
      == "quantization deep dive")
check("latest qualifying reply wins",
      pl.resolve_reply(msgs + [{"event": "message", "time": 1400, "message": "1"}],
                       opts) == "topic one")
check("too-short free text ignored",
      pl.resolve_reply([{"event": "message", "time": 1300, "message": "ok"}], opts) == "")

print(f"\nALL {passed} ASSERTIONS PASSED")
