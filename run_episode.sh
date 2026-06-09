#!/usr/bin/env bash
# Nightly entrypoint. Uses the logged-in Claude Pro CLI (no ANTHROPIC_API_KEY).
set -euo pipefail
cd "$(dirname "$0")"

# Load storage + show config (but not an API key).
set -a; [ -f .env ] && . ./.env; set +a
unset ANTHROPIC_API_KEY || true   # belt-and-suspenders: stay on the Pro subscription

DATE="$(date +%F)"
mkdir -p out

# 1–4: Claude follows the skill — fetch, gather, write script, render MP3.
claude -p "Use the daily-ai-podcast skill to produce today's episode end to end, \
following its grounding rules and ~15-minute target. Print the MP3 path when done." \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill" \
  --permission-mode acceptEdits \
  --max-turns 80

# 5: publish — read title/date/summary from the episode, upload + rebuild the feed.
python3 - "$DATE" <<'PY'
import json, subprocess, sys, glob, os
date = sys.argv[1]
ep = json.load(open("out/episode.json"))
mp3 = sorted(glob.glob(f"out/podcast-{date}*.mp3")) or sorted(glob.glob("out/podcast-*.mp3"))
assert mp3, "no MP3 produced"
summary = ""
try: summary = open("out/shownotes.md").read().split("\n\n")[1][:600]
except Exception: pass
subprocess.run(["python3","scripts/publish.py","--mp3",mp3[-1],
                "--title",ep.get("title",f"AI Daily — {date}"),
                "--summary",summary,"--date",ep.get("date",date)], check=True)
PY

echo "Done: $DATE"
