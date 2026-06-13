#!/usr/bin/env bash
# Nightly entrypoint. Uses the logged-in Claude Pro CLI (no ANTHROPIC_API_KEY).
set -euo pipefail
cd "$(dirname "$0")"

# Self-contained for cron (minimal PATH/env): activate the Python 3.12 venv and
# make the user-local `claude` CLI reachable without depending on cron's PATH.
[ -f .venv/bin/activate ] && . .venv/bin/activate
# Prepend the user-local CLI dir (claude); append conda's bin for ffmpeg/ffprobe
# (installed there via conda) without letting conda's python shadow the venv.
export PATH="$HOME/.local/bin:$PATH:$HOME/miniconda3/bin"

# Load storage + show config (but not an API key).
set -a; [ -f .env ] && . ./.env; set +a
unset ANTHROPIC_API_KEY || true   # belt-and-suspenders: stay on the Pro subscription

DATE="$(date +%F)"
DOW="$(date +%u)"   # 1=Mon .. 6=Sat 7=Sun
mkdir -p out

# Pin the model explicitly so the nightly job never inherits whatever the
# interactive CLI default happens to be (an interactive /model switch persists
# into settings and would otherwise leak into this run).
MODEL="opus"

# 1–4: Claude follows the skill — fetch, gather, write script, render MP3.
claude -p "Use the daily-ai-podcast skill to produce today's episode end to end, \
following its grounding rules and length target (18-22 min). \
Print the MP3 path when done." \
  --model "$MODEL" \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
  --permission-mode acceptEdits \
  --max-turns 80

# Sunday: write the weekly evening read and build its EPUB into docs/reads/ first,
# so the publish step below sweeps it into the same commit + index page. Non-fatal:
# a failed read must not block the daily episode.
if [ "$DOW" = "7" ]; then
  claude -p "Use the weekly-read skill to write this week's evening read and build \
the EPUB. Print the EPUB path when done." \
    --model "$MODEL" \
    --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
    --permission-mode acceptEdits \
    --max-turns 60 || echo "WARNING: weekly read failed; continuing with daily publish"
fi

# 5: publish — read title/date/summary from the episode, upload + rebuild the feed.
python3 - "$DATE" <<'PY'
import json, subprocess, sys, glob
date = sys.argv[1]
ep = json.load(open("out/episode.json"))
mp3 = sorted(glob.glob(f"out/podcast-{date}*.mp3"))
assert mp3, f"no MP3 produced for {date} — not publishing a stale episode"
summary = ""
try: summary = json.load(open("out/episode_meta.json")).get("summary", "")[:600]
except Exception: pass
subprocess.run(["python3","scripts/publish.py","--mp3",mp3[-1],
                "--title",ep.get("title",f"Self-Attention — {date}"),
                "--summary",summary,"--notes","out/shownotes.md",
                "--date",ep.get("date",date)], check=True)
PY

# Saturday: also produce + publish the weekly deep-dive episode.
if [ "$DOW" = "6" ]; then
  claude -p "Use the weekly-deep-dive skill to produce this week's deep-dive episode \
end to end, following its grounding rules and length target (20-25 min). \
Print the MP3 path when done." \
    --model "$MODEL" \
    --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
    --permission-mode acceptEdits \
    --max-turns 80

  python3 - "$DATE" <<'PY'
import json, subprocess, sys, glob
date = sys.argv[1]
ep = json.load(open("out/deepdive.json"))
mp3 = sorted(glob.glob(f"out/deepdive-{date}*.mp3"))
assert mp3, f"no deep-dive MP3 produced for {date}"
summary = ""
try: summary = json.load(open("out/deepdive_meta.json")).get("summary", "")[:600]
except Exception: pass
subprocess.run(["python3","scripts/publish.py","--mp3",mp3[-1],
                "--title",ep.get("title",f"Deep Dive — {date}"),
                "--summary",summary,"--notes","out/deepdive_shownotes.md",
                "--date",ep.get("date",date),"--slug","deepdive"], check=True)
PY
fi

echo "Done: $DATE"
