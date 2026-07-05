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
# Cron jobs sharing this script: the full podcast pipeline at 01:00; the daily read on
# its own at ~06:30 — after the 5h limit resets — so the read stops competing with the
# podcast for one rate-limit window; and `propose` on Tue/Fri/Sat evenings, which pushes
# 3-5 deep-dive topic pitches to the listener's phone (ntfy) so the reply can steer
# the next morning's deep dive. No arg runs the full pipeline.
MODE="${1:-full}"
case "$MODE" in full|read|propose) ;; *) echo "usage: $0 [full|read|propose]" >&2; exit 2 ;; esac
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
# Opus is the default orchestrator for every Claude run — the podcast (editorial
# judgment, grounding, source selection), the read, and the deep dive.
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
log run "===== RUN START $DATE mode=$MODE dow=$DOW pid=$$ host=$(hostname) git=$(git rev-parse --short HEAD 2>/dev/null || echo '?') ====="

# Per-minute usage snapshot (5h + 7d limits) as a parallel sidecar; killed on exit.
python3 scripts/run_log.py poll --interval 60 --log "$LOG" &
USAGE_PID=$!
cleanup() {
  kill "$USAGE_PID" 2>/dev/null || true
  local status
  if [ ${#FAILED[@]} -eq 0 ]; then status="OK"; else
    status="FAIL failed=[$(IFS=,; echo "${FAILED[*]}")]"
    # Best-effort phone alert (no-op when NTFY_TOPIC is unset).
    python3 scripts/notify.py --priority high \
      --title "Podcast run FAILED ($DATE $MODE)" \
      --message "Failed steps: $(IFS=,; echo "${FAILED[*]}"). See logs/run.log." \
      >/dev/null 2>&1 || true
  fi
  log run "===== RUN END $DATE dur=$(( $(date +%s) - RUN_START ))s status=$status ====="
}
trap cleanup EXIT
# ------------------------------------------------------------------------------

# In `read` mode (the separate ~06:30 cron job) write + publish ONLY the daily read, then
# stop. The skill builds the EPUB into docs/reads/ and records reads_history.json; we then
# email it to the Kindle and commit the EPUB + reads_history so it persists and serves on
# Pages. Non-fatal steps mirror the podcast path: a failed read/email must not wedge the run.
if [ "$MODE" = "read" ]; then
  run_step read claude -p "Use the daily-read skill to write today's issue of Self Attention end to end, \
following its reasoning, grounding, and the day's length target. Build the EPUB with the \
cover and record the issue. Print the EPUB path when done." \
    --model "$READ_MODEL" \
    --effort medium \
    --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
    --permission-mode acceptEdits \
    --max-turns 50 || log run "WARNING: daily read failed"
  run_step kindle python3 scripts/send_to_kindle.py --epub "docs/reads/self-attention-$DATE.epub" \
    || log run "WARNING: Kindle email failed; EPUB still on GitHub Pages"
  run_step publish-read python3 scripts/publish_read.py --date "$DATE" \
    || log run "WARNING: read publish failed; EPUB may be unpushed"
  exit 0
fi

# In `propose` mode (Tue/Fri/Sat ~20:00 cron) a cheap session drafts 3-5 deep-dive topic
# options from the week's coverage, then the pitches go to the phone via ntfy. The
# listener replies with a number (or a topic of their own); the 01:00 run reads the
# reply via scripts/ntfy_choice.py. No reply -> the deep-dive writer picks, as ever.
if [ "$MODE" = "propose" ]; then
  run_step propose claude -p "Read .claude/skills/weekly-deep-dive/SKILL.md (its topic-selection \
criteria), history.json (recent episodes, active threads, and longterm.concepts_taught), and the \
2-3 newest daily scripts in archive/scripts/. Propose 3-5 candidate topics for tomorrow's deep-dive \
episode: motivated by this week's news, teachable end-to-end in ~20 minutes, and not already taught \
(check concepts_taught and past deepdive-kind episode records). Write out/deepdive_options.json as \
exactly {\"options\": [{\"n\": 1, \"topic\": \"short topic name\", \"pitch\": \"one-line pitch for a \
phone notification\"}]}. Do nothing else." \
    --model sonnet \
    --effort low \
    --allowedTools "Read Write Bash" \
    --permission-mode acceptEdits \
    --max-turns 15 \
    || log run "WARNING: propose failed; deep-dive writer will pick as usual"
  OPTIONS_MSG="$(python3 - <<'PY'
import json, time
try:
    opts = json.load(open("out/deepdive_options.json"))
except Exception:
    raise SystemExit(0)
opts["sent_at"] = int(time.time())
json.dump(opts, open("out/deepdive_options.json", "w"), indent=1)
print("\n".join(f"{o.get('n')}. {o.get('topic')} — {o.get('pitch')}"
                for o in opts.get("options", [])))
PY
)"
  if [ -n "$OPTIONS_MSG" ]; then
    run_step notify python3 scripts/notify.py \
      --title "Deep-dive options for tomorrow — reply with a number or your own topic" \
      --message "$OPTIONS_MSG" \
      || log run "WARNING: options notification failed"
  fi
  exit 0
fi

# --- Gather pipeline (podcast): run ENTIRELY before the Opus session ----------
# The gather phase (fetch → crawl → consolidate) needs little/no Opus-grade judgment, but
# when it ran *inside* the Opus orchestrator it dragged the whole gather residue into the
# expensive Opus context and made Opus block on (and recover from) cheap subagents. So we
# run it here, on the cheapest model that does the job, and let the Opus podcast session
# start clean at out/candidates.json. Each stage is non-fatal: the podcast skill still
# falls back to doing any missing stage itself, so a flaky gather can't lose the night.
rm -f out/sources.json out/crawl.json out/candidates.json
log run "prep: cleared podcast scratch (sources/crawl/candidates.json)"

# 1. Structured fetch — deterministic, in-shell (no model).
set +e
python3 scripts/fetch_sources.py --hours 48 --out out/sources.json 2>&1 \
  | python3 scripts/run_log.py prefix --src fetch >> "$LOG"
FETCH_RC=${PIPESTATUS[0]}
set -e
[ "$FETCH_RC" -eq 0 ] || log run "WARNING: fetch_sources exit=$FETCH_RC; consolidator works from whatever exists"

# 2. Crawl the HTML watchlist — standalone Haiku session writing out/crawl.json.
run_step crawl claude -p "Follow .claude/agents/source-crawler.md exactly. Read config/sources.yaml, \
take every source whose method is 'fetch' (both tiers), crawl them for today ($DATE) and yesterday only, \
recover Tier-1 failures via a backup search, and write out/crawl.json in that contract's shape." \
  --model haiku \
  --allowedTools "Read WebSearch WebFetch Write" \
  --permission-mode acceptEdits \
  --max-turns 40 \
  || log run "WARNING: crawl failed; consolidator will work from sources.json alone"

# 2.5 Consolidate — standalone Sonnet session writing out/candidates.json.
run_step consolidate claude -p "Follow .claude/agents/source-consolidator.md exactly. Merge \
out/sources.json and out/crawl.json (use whichever exist) into out/candidates.json, flagging likely \
repeats against history.json. Write the file even if one input is missing." \
  --model sonnet \
  --effort low \
  --allowedTools "Read Write Bash" \
  --permission-mode acceptEdits \
  --max-turns 30 \
  || log run "WARNING: consolidate failed; podcast skill will gather inline"

# One-time steering (self-expiring): aged-well papers the pre-refresh pipeline missed
# (found in a 30-day HF audit on 2026-07-04). The date guard makes this a no-op from
# 2026-07-12 on — nothing to remember; delete the block whenever this file is next touched.
BACKLOG_NOTE=""
if [ "$DATE" \< "2026-07-12" ]; then
  BACKLOG_NOTE=" One-time backlog: these aged-well HF papers were never covered — consider at most \
one per night as a dive where it genuinely fits (check history.json first and skip any already \
covered): 'ABot-Earth 0.5: Generative 3D Earth Model' (486 upvotes), 'Looped World Models' (476), \
'LoopCoder-v2: Only Loop Once for Efficient Test-Time Computation Scaling' (209)."
fi

# 3: Opus selects, verifies, and writes the script — stops after validation.
run_step podcast claude -p "Use the daily-ai-podcast skill to produce today's episode. The harness has \
already run steps 1, 2, and 2.5 — out/sources.json, out/crawl.json, and out/candidates.json already \
exist, so SKIP them. Do step 1.5 (recall history) then steps 3 and 3.5 (select, verify, write, \
validate). STOP after the gate passes — do NOT run steps 4 or 4.5; the harness renders and updates \
history. If out/candidates.json is somehow missing, fall back to doing the gather steps yourself. \
Print the episode title and word count when done.${BACKLOG_NOTE}" \
  --model "$PODCAST_MODEL" \
  --effort medium \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
  --permission-mode acceptEdits \
  --max-turns 60

# Update show memory — pure Python, reads out/episode_meta.json; runs before render so
# history is current even if the render fails.
set +e
.venv/bin/python scripts/update_history.py --append \
  2>&1 | python3 scripts/run_log.py prefix --src update-history >> "$LOG"
HIST_RC=${PIPESTATUS[0]}
set -e
[ "$HIST_RC" -eq 0 ] || log run "WARNING: update_history failed; history.json may be stale"

# Archive the night's script + meta (committed by publish.py alongside the feed).
# The writer reads the last few archived scripts to notice — and break — its own
# patterns, and the gate's phrase-recurrence check compares against them.
mkdir -p archive/scripts
cp -f out/script.txt "archive/scripts/$DATE.txt" 2>/dev/null \
  && cp -f out/episode_meta.json "archive/scripts/$DATE-meta.json" 2>/dev/null \
  || log run "WARNING: script archive copy failed"

# 4: Render the podcast audio — pure Python, no model needed.
run_step render-podcast \
  .venv/bin/python scripts/make_audio.py \
  --episode out/episode.json --out "out/podcast-$DATE.mp3"

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

# Wed/Sat/Sun: also produce + publish the deep-dive episode. If the listener replied
# to the previous evening's options push, their choice becomes the topic.
if [ "$DOW" = "3" ] || [ "$DOW" = "6" ] || [ "$DOW" = "7" ]; then
  DIVE_CHOICE="$(python3 scripts/ntfy_choice.py 2>/dev/null || true)"
  DIVE_TOPIC_NOTE=""
  if [ -n "$DIVE_CHOICE" ]; then
    log run "deepdive: listener pre-chose topic: $DIVE_CHOICE"
    DIVE_TOPIC_NOTE=" The listener pre-chose tonight's topic via the evening picker: \
'${DIVE_CHOICE}'. Take it as the deep-dive topic — skip topic selection and go straight to research."
  fi
  run_step deepdive claude -p "Use the weekly-deep-dive skill to produce this week's deep-dive episode \
following its grounding rules and length target (20-25 min). STOP after step 4's validation gate \
passes — do NOT run the render or update_history lines in step 4; the harness handles both. \
Print the topic and word count when done.${DIVE_TOPIC_NOTE}" \
    --model "$DEEPDIVE_MODEL" \
    --effort medium \
    --allowedTools "Bash Read Write WebSearch WebFetch Skill Agent" \
    --permission-mode acceptEdits \
    --max-turns 60

  set +e
  .venv/bin/python scripts/update_history.py --append --meta out/deepdive_meta.json \
    2>&1 | python3 scripts/run_log.py prefix --src update-history >> "$LOG"
  HIST_DD_RC=${PIPESTATUS[0]}
  set -e
  [ "$HIST_DD_RC" -eq 0 ] || log run "WARNING: update_history (deepdive) failed; history.json may be stale"

  mkdir -p archive/scripts
  cp -f out/deepdive_script.txt "archive/scripts/$DATE-deepdive.txt" 2>/dev/null \
    || log run "WARNING: deepdive script archive copy failed"

  run_step render-deepdive \
    .venv/bin/python scripts/make_audio.py \
    --episode out/deepdive.json --out "out/deepdive-$DATE.mp3"

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
  rm -f out/deepdive_options.json   # consumed; a stale one must not steer next week
fi

log run "Done: $DATE"
