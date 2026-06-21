#!/usr/bin/env bash
# Nightly entrypoint. Uses the logged-in Claude Pro CLI (no ANTHROPIC_API_KEY).
set -euo pipefail
cd "$(dirname "$0")"

# Self-contained for cron (minimal PATH/env): activate the Python 3.12 venv and
# make the user-local `claude` CLI reachable without depending on cron's PATH.
[ -f .venv/bin/activate ] && . .venv/bin/activate
# Prepend the user-local CLI dir (claude); append conda's bin for ffmpeg/ffprobe
# (installed there via conda) without letting conda's python shadow the venv.
export PATH="$HOME/.local/bin:$PATH:$HOME/miniforge3/bin"

# Load storage + show config (but not an API key).
set -a; [ -f .env ] && . ./.env; set +a
unset ANTHROPIC_API_KEY || true   # belt-and-suspenders: stay on the Pro subscription

DATE="$(date +%F)"
DOW="$(date +%u)"   # 1=Mon .. 6=Sat 7=Sun
mkdir -p out logs

# Publishing is branch-scoped: publish.py commits the rebuilt feed into docs/, and
# GitHub Pages serves the feed Spotify polls from main/docs. A run on any other branch
# strands the feed update where Pages can't see it (episodes silently never go live).
# So before spending any session budget, get onto main: switch automatically when the
# working tree is clean, but refuse (rather than stash/clobber) if there are uncommitted
# changes — an unattended job must not make state decisions on top of in-progress work.
# RUN_EPISODE_ALLOW_ANY_BRANCH=1 skips this for the hermetic test, which runs a copy of
# this script in a non-repo sandbox (no branch to check).
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
if [ "$BRANCH" != "main" ] && [ "${RUN_EPISODE_ALLOW_ANY_BRANCH:-}" != "1" ]; then
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "run_episode: on '$BRANCH' with uncommitted changes — refusing (commit or stash, then rerun on main)." >&2
    exit 1
  fi
  echo "run_episode: on '$BRANCH', switching to main (Pages publishes from main only)." >&2
  git checkout main || { echo "run_episode: could not switch to main — aborting." >&2; exit 1; }
fi

# Pin models explicitly so the nightly job never inherits an interactive /model switch.
# Opus for the podcast (editorial judgment, grounding, source selection).
# Sonnet for the read and deep dive (writing-heavy tasks; saves Pro session budget).
PODCAST_MODEL="opus"
READ_MODEL="opus"
DEEPDIVE_MODEL="opus"

# --- Logging ------------------------------------------------------------------
# The script owns its log (logs/run.log); cron only catches catastrophic pre-logging
# errors via its own bootstrap redirect. Logging helpers run on the SYSTEM python3 so
# they keep working even if the .venv is broken (a broken .venv was a real failure mode).
LOG="logs/run.log"
LOG_KEEP_RUNS="${LOG_KEEP_RUNS:-10}"   # how many past run blocks to retain in run.log

log() { printf '%s [%s] %s\n' "$(date '+%FT%T%:z')" "$1" "$2" >> "$LOG"; }

# run_step <src> <cmd...> : run a stage, timestamping its stdout+stderr into the log
# tagged by <src>, bracketed by start/end markers (exit code + duration). Returns the
# command's exit code so callers keep their fatal/non-fatal semantics (e.g. `|| log ...`).
run_step() {
  local src="$1"; shift
  local start; start=$(date +%s)
  log run "step start: $src"
  set +e
  "$@" 2>&1 | python3 scripts/run_log.py prefix --src "$src" >> "$LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  log run "step end: $src exit=$rc dur=$(( $(date +%s) - start ))s"
  if [ "$rc" -ne 0 ]; then FAILED+=("$src"); fi
  return "$rc"
}

FAILED=()
RUN_START=$(date +%s)
python3 scripts/run_log.py trim --keep "$((LOG_KEEP_RUNS-1))" --log "$LOG"
log run "===== RUN START $DATE dow=$DOW pid=$$ host=$(hostname) git=$(git rev-parse --short HEAD 2>/dev/null || echo '?') ====="

# Per-minute usage snapshot (5h + 7d limits) as a parallel sidecar; killed on exit.
python3 scripts/run_log.py poll --interval 60 --log "$LOG" &
USAGE_PID=$!
cleanup() {
  kill "$USAGE_PID" 2>/dev/null || true
  local status
  if [ ${#FAILED[@]} -eq 0 ]; then status="OK"; else status="FAIL failed=[$(IFS=,; echo "${FAILED[*]}")]"; fi
  log run "===== RUN END $DATE dur=$(( $(date +%s) - RUN_START ))s status=$status ====="
}
trap cleanup EXIT
# ------------------------------------------------------------------------------

# 1–4: Claude follows the skill — fetch, gather, write script, render MP3.
run_step podcast claude -p "Use the daily-ai-podcast skill to produce today's episode end to end, \
following its grounding rules and length target (18-22 min). \
Print the MP3 path when done." \
  --model "$PODCAST_MODEL" \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
  --permission-mode acceptEdits \
  --max-turns 60

# Daily: write "Self Attention" (the daily read) and build its EPUB into docs/reads/
# first, so the publish step below sweeps it into the same commit + index page, then
# email it to the Kindle. The skill itself builds the EPUB (with cover) and records the
# issue in reads_history.json; it knows the day's length target from the date. Non-fatal:
# a failed read (or failed email) must not block the daily podcast publish.
run_step read claude -p "Use the daily-read skill to write today's issue of Self Attention end to end, \
following its reasoning, grounding, and the day's length target. Build the EPUB with the \
cover and record the issue. Print the EPUB path when done." \
  --model "$READ_MODEL" \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
  --permission-mode acceptEdits \
  --max-turns 50 || log run "WARNING: daily read failed; continuing with daily publish"
run_step kindle python3 scripts/send_to_kindle.py --epub "docs/reads/self-attention-$DATE.epub" \
  || log run "WARNING: Kindle email failed; EPUB still on GitHub Pages"

# 5: publish — read title/date/summary from the episode, upload + rebuild the feed.
run_step publish python3 - "$DATE" <<'PY'
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

# Wed/Sat: also produce + publish the deep-dive episode.
if [ "$DOW" = "6" ] || [ "$DOW" = "3" ]; then
  run_step deepdive claude -p "Use the weekly-deep-dive skill to produce this week's deep-dive episode \
end to end, following its grounding rules and length target (20-25 min). \
Print the MP3 path when done." \
    --model "$DEEPDIVE_MODEL" \
    --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
    --permission-mode acceptEdits \
    --max-turns 60

  run_step publish-deepdive python3 - "$DATE" <<'PY'
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

log run "Done: $DATE"
