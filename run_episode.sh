#!/usr/bin/env bash
# Nightly entrypoint. Uses logged-in subscription CLIs; Codex is the default.
set -euo pipefail
cd "$(dirname "$0")"

# Self-contained for cron (minimal PATH/env): activate the Python 3.12 venv and
# make the user-local agent CLIs reachable without depending on cron's PATH.
[ -f .venv/bin/activate ] && . .venv/bin/activate
# Prepend the user-local CLI dir (Codex/Claude); append conda's bin for ffmpeg/ffprobe
# (installed there via conda) without letting conda's python shadow the venv.
export PATH="$HOME/.local/bin:$PATH:$HOME/miniforge3/bin"

# Load storage + show config (but not an agent API key).
set -a; [ -f .env ] && . ./.env; set +a
unset ANTHROPIC_API_KEY OPENAI_API_KEY CODEX_API_KEY || true

DRY_RUN="${RUN_EPISODE_DRY_RUN:-0}"

# Never wait on an overlapping scheduler invocation and never ask a person what to do.
exec 9>.run_episode.lock
if ! flock -n 9; then
  if [ "$DRY_RUN" != "1" ]; then
    python3 scripts/notify.py --priority high --title "Podcast run skipped" \
      --message "Another run_episode.sh invocation already holds the repository lock." \
      >/dev/null 2>&1 || true
  fi
  echo "run_episode: another invocation is active; skipped" >&2
  exit 75
fi

DATE="$(date +%F)"
DOW="$(date +%u)"   # 1=Mon .. 6=Sat 7=Sun
# Cron jobs sharing this script: the full podcast pipeline at 04:00; the daily read on
# its own at ~06:30 — after the 5h limit resets — so the read stops competing with the
# podcast for one rate-limit window; and `propose` every evening at 20:00, which pushes
# tonight's candidate mini-dives to the listener's phone (ntfy) — plus, on Tue/Fri/Sat,
# the deep-dive topic pitches — so the reply steers the next morning's episodes.
# No arg runs the full pipeline.
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
if [ "$BRANCH" != "main" ] && [ "${RUN_EPISODE_ALLOW_ANY_BRANCH:-}" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "run_episode: on '$BRANCH' with uncommitted changes — refusing (commit or stash, then rerun on main)." >&2
    exit 1
  fi
  echo "run_episode: on '$BRANCH', switching to main (Pages publishes from main only)." >&2
  git checkout main || { echo "run_episode: could not switch to main — aborting." >&2; exit 1; }
fi

# Validate deterministic dependencies and provider configuration before fetching or
# spending model quota. Auth checks are noninteractive and redact credentials.
python3 scripts/preflight.py --mode "$MODE"

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

agent_stage() {
  local stage="$1" prompt="$2"
  printf '%s' "$prompt" | python3 scripts/agent_runner.py --stage "$stage"
}

FAILED=()
RUN_START=$(date +%s)
python3 scripts/run_log.py trim --keep "$((LOG_KEEP_RUNS-1))" --log "$LOG"
log run "===== RUN START $DATE mode=$MODE dow=$DOW pid=$$ host=$(hostname) git=$(git rev-parse --short HEAD 2>/dev/null || echo '?') ====="

cleanup() {
  local status
  if [ ${#FAILED[@]} -eq 0 ]; then status="OK"; else
    status="FAIL failed=[$(IFS=,; echo "${FAILED[*]}")]"
    # Best-effort phone alert (no-op when NTFY_TOPIC is unset).
    if [ "$DRY_RUN" != "1" ]; then
      python3 scripts/notify.py --priority high \
        --title "Podcast run FAILED ($DATE $MODE)" \
        --message "Failed steps: $(IFS=,; echo "${FAILED[*]}"). See logs/run.log." \
        >/dev/null 2>&1 || true
    fi
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
  READ_RECORD_INSTRUCTION="Build the EPUB with the cover and record the issue."
  if [ "$DRY_RUN" = "1" ]; then
    READ_RECORD_INSTRUCTION="Build the EPUB with the cover, but do not update reads_history.json; stop after the EPUB is validated."
  fi
  run_step read agent_stage read "Use the daily-read skill to write today's issue of Self Attention end to end, \
following its reasoning, grounding, and the day's length target. ${READ_RECORD_INSTRUCTION} \
Print the EPUB path when done." || log run "WARNING: daily read failed"
  if [ "$DRY_RUN" = "1" ]; then
    log run "dry-run: skipped Kindle delivery and read publish"
  else
    run_step kindle python3 scripts/send_to_kindle.py --epub "docs/reads/self-attention-$DATE.epub" \
      || log run "WARNING: Kindle email failed; EPUB still on GitHub Pages"
    run_step publish-read python3 scripts/publish_read.py --date "$DATE" \
      || log run "WARNING: read publish failed; EPUB may be unpushed"
  fi
  exit 0
fi

# In `propose` mode (nightly ~20:00 cron) a cheap session drafts two slates: six of
# today's stories the listener can lock as tomorrow's mini-dives, and — the night before
# a deep dive — six deep-dive topic pitches. Both ride in ONE ntfy push, numbers for the
# mini-dives and letters for the deep dive, so there is one notification and one reply.
# The 04:00 run reads the reply via scripts/ntfy_choice.py. No reply -> the writers pick,
# as ever.
if [ "$MODE" = "propose" ]; then
  # Tue/Fri/Sat evenings feed the Wed/Sat/Sun deep dives; the other four nights push
  # the mini-dive slate alone.
  case "$DOW" in 2|5|6) DEEPDIVE_TOMORROW=yes ;; *) DEEPDIVE_TOMORROW=no ;; esac

  # Clear last night's slates first: a drafting stage that fails must not re-push stale
  # options, and on a non-deep-dive night a leftover deep-dive slate would bump the
  # retirement ledger for topics nobody ever saw.
  rm -f out/daily_options.json out/deepdive_options.json

  # Fresh evening pull of the structured feeds so the picker sees today's papers
  # and discussion, not last night's snapshot. Non-fatal; a separate file so the
  # 04:00 run's own fetch is untouched.
  python3 scripts/fetch_sources.py --hours 24 --out out/sources_evening.json 2>&1 \
    | python3 scripts/run_log.py prefix --src propose-fetch >> "$LOG" \
    || log run "WARNING: evening fetch failed; picker works from memory alone"

  if [ "$DEEPDIVE_TOMORROW" = "yes" ]; then
    DIVE_SLATE_TASK="SECOND, the deep-dive slate. Read .agents/skills/weekly-deep-dive/SKILL.md (its topic palette and \
selection criteria), history.json (recent episodes, active threads, longterm.concepts_taught), \
deepdive_proposals.json (the proposal ledger — NEVER re-pitch a retired topic: times_proposed >= 3 \
and never chosen; avoid re-pitching anything already proposed twice unless it's newly urgent), the \
2-3 newest daily scripts in archive/scripts/, and out/sources_evening.json (today's fresh feed pull) \
if it exists. Propose exactly 6 candidate topics for tomorrow's deep-dive episode as a MIXED slate: \
about 2 of type 'mechanism' (the idea under this week's news), at least 1 'foundational', at least 1 \
'history', at least 1 'debate' — plus one wildcard of any type. Rules: a topic is NEVER a single \
paper — it is the idea or capability the paper instantiates, with the week's material as evidence; \
every pitch must briefly say what the twenty minutes would actually contain (so thin topics reveal \
themselves while drafting); nothing already taught (concepts_taught / past deepdive records). Write \
out/deepdive_options.json as exactly {\"options\": [{\"n\": 1, \"type\": \"mechanism|foundational|\
history|debate\", \"topic\": \"short topic name\", \"pitch\": \"one-line pitch: the hook plus what \
the episode contains\"}]}."
  else
    DIVE_SLATE_TASK="SECOND: tomorrow is not a deep-dive morning, so propose no deep-dive topics — \
write out/deepdive_options.json as exactly {\"options\": []} and move on."
  fi

  run_step propose agent_stage propose "Two slates for tonight's listener push; write both files. \
FIRST, the mini-dive slate for tomorrow's daily episode. Read out/sources_evening.json (tonight's \
fresh feed pull — the most current view you have), out/candidates.json if it exists (this morning's \
consolidated candidate set, ~16 hours old: its value is the stories the last episode only named or \
resolved and never dived), history.json (recent episodes, active threads, and each episode's \
'dives'), listener.yaml, feedback.md, and the 2-3 newest scripts in archive/scripts/. Propose \
exactly 15 stories the listener could lock as tomorrow's mini-dives, ordered strongest first. Take \
about 8 of them from the stories that objectively earned a dive — multi-source pickup, real \
community traction (HF upvotes, HN points), or continuation of an active history.json thread — and \
mark about 7 as wildcards: stories you find genuinely interesting but would not spend a dive on \
unprompted. On a thin news day let the wildcard share grow rather than padding the earned tier with \
stories that did not earn it. The slate is a menu, so make it a varied one: the fifteen must not \
all be papers, and the wildcards especially should reach across different kinds of story (a \
release, a policy or business move, an older thread that just advanced, something odd or human) \
rather than extending the signal ranking. Skip anything the show already dived unless it has materially advanced \
since; a story the show merely named or resolved is fair game. Write out/daily_options.json as exactly {\"options\": \
[{\"n\": 1, \"label\": \"short story label, phone-screen length\", \"url\": \"primary source URL\", \
\"why\": \"1-2 lines: what happened and who specifically would care\", \"signal\": \"terse evidence \
it earned a slot, e.g. '4 src' or 'HN 890' or 'HF 210' or 'thread: agent evals'\", \"wildcard\": \
false}]}. ${DIVE_SLATE_TASK} Do nothing else." \
    || log run "WARNING: propose failed; the writers will pick as usual"

  # Slate passes: renumber, stamp sent_at, and emit each half's message body. The
  # deep-dive half also runs its retirement ledger. Both print nothing when empty.
  DAILY_MSG=""
  DIVE_MSG=""
  if [ "$DRY_RUN" != "1" ]; then
    DAILY_MSG="$(python3 scripts/daily_options.py record || true)"
    DIVE_MSG="$(python3 scripts/proposal_ledger.py record || true)"
  fi

  # One push. Headers only when both halves are present — on a mini-dives-only night
  # the title already says what the numbers are.
  TITLE="Tonight's dives — reply with a number or two"
  FOOTER="Reply: numbers = tonight's dives (up to 3) · plain text = a dive of your own"
  if [ -n "$DAILY_MSG" ] && [ -n "$DIVE_MSG" ]; then
    OPTIONS_MSG="TONIGHT'S DIVES — pick 2-3
$DAILY_MSG

TOMORROW'S DEEP DIVE — pick one
$DIVE_MSG"
  else
    OPTIONS_MSG="${DAILY_MSG}${DIVE_MSG}"
  fi
  if [ -n "$DIVE_MSG" ]; then
    TITLE="Tonight's dives + tomorrow's deep dive"
    FOOTER="$FOOTER · letter = the deep dive · \"dd <topic>\" = your own deep-dive topic"
  fi
  if [ -n "$OPTIONS_MSG" ]; then
    run_step notify python3 scripts/notify.py \
      --title "$TITLE" \
      --message "$OPTIONS_MSG

$FOOTER" \
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
# out/daily_options.json is deliberately NOT cleared here — it was written at 20:00 and
# is read a few steps below. Its picks file is, so a dead run can't steer tonight.
rm -f out/sources.json out/crawl.json out/candidates.json out/daily_picks.json \
  out/script.txt out/episode_meta.json out/episode.json out/shownotes.md \
  out/deepdive_script.txt out/deepdive_meta.json out/deepdive.json out/deepdive_shownotes.md
log run "prep: cleared podcast scratch and required agent artifacts"

# 1. Structured fetch — deterministic, in-shell (no model).
set +e
python3 scripts/fetch_sources.py --hours 48 --out out/sources.json 2>&1 \
  | python3 scripts/run_log.py prefix --src fetch >> "$LOG"
FETCH_RC=${PIPESTATUS[0]}
set -e
[ "$FETCH_RC" -eq 0 ] || log run "WARNING: fetch_sources exit=$FETCH_RC; consolidator works from whatever exists"

# 2. Crawl the HTML watchlist — standalone Haiku session writing out/crawl.json.
run_step crawl agent_stage crawl "Use the source-crawler skill exactly. Read config/sources.yaml, \
take every source whose method is 'fetch' (both tiers), crawl them for today ($DATE) and yesterday only, \
recover Tier-1 failures via a backup search, and write out/crawl.json in that contract's shape." \
  || log run "WARNING: crawl failed; consolidator will work from sources.json alone"

# 2.2 Archive tonight's raw gather to smallbatch-lab as classifier training data.
# Deliberately the *pre*-consolidation inputs: the classifier being trained there is
# meant to eventually do the consolidator's triage itself, so it has to learn from
# what the consolidator sees, not from what it produced. Write-only (no commit/push)
# and skipped silently if the sibling repo isn't checked out — the show never depends
# on this, so it must never be able to break the run.
TRIAGE_DIR="${TRIAGE_DIR:-$HOME/Documents/Github/smallbatch-lab/data/podcast-triage}"
if [ "$DRY_RUN" != "1" ] && [ -d "$(dirname "$TRIAGE_DIR")" ]; then
  mkdir -p "$TRIAGE_DIR"
  for f in sources crawl; do
    if [ -f "out/$f.json" ]; then
      cp "out/$f.json" "$TRIAGE_DIR/$DATE-$f.json"
      log run "archived out/$f.json -> $TRIAGE_DIR/$DATE-$f.json"
    fi
  done
else
  log run "smallbatch-lab not found; skipped triage archive"
fi

# 2.5 Consolidate — standalone Sonnet session writing out/candidates.json.
run_step consolidate agent_stage consolidate "Use the source-consolidator skill exactly. Merge \
out/sources.json and out/crawl.json (use whichever exist) into out/candidates.json, flagging likely \
repeats against history.json. Write the file even if one input is missing." \
  || log run "WARNING: consolidate failed; podcast skill will gather inline"

# The listener's mini-dive picks, if they replied to last evening's push. Unlike the
# deep-dive read below this is not gated on DRY_RUN: it is a read-only poll with no side
# effect (the deep-dive call sits next to a ledger write, which is what that guard is for),
# so a dry run exercises the picker for real. DAILY_DIVES overrides the phone.
DIVE_PICK_NOTE=""
DIVE_PICKS="$(python3 scripts/ntfy_choice.py --kind daily 2>/dev/null || true)"
if [ -n "$DIVE_PICKS" ]; then
  log run "podcast: listener pre-chose dives: $DIVE_PICKS"
  DIVE_PICK_NOTE=" The listener pre-chose tonight's mini-dives via the evening picker: read \
out/daily_picks.json and follow the skill's pre-chosen-dives rule — those stories are locked dives."
fi

# 3: Opus selects, verifies, and writes the script — stops after validation.
run_step podcast agent_stage podcast "Use the daily-ai-podcast skill to produce today's episode. The harness has \
already run steps 1, 2, and 2.5 — out/sources.json, out/crawl.json, and out/candidates.json already \
exist, so SKIP them. Do step 1.5 (recall history) then steps 3 and 3.5 (select, verify, write, \
validate). STOP after the gate passes — do NOT run steps 4 or 4.5; the harness renders and updates \
history. If out/candidates.json is somehow missing, fall back to doing the gather steps yourself. \
Print the episode title and word count when done.${DIVE_PICK_NOTE}"

# Re-run the gate here, independently. The writer runs it inside its own session and
# reports the result, which means "gate passed, zero warnings" in the log has until now
# been the writer grading its own work. Running it again costs a second and catches both
# a mis-reported pass and anything that changed after the writer stopped — before we spend
# ~20 minutes of TTS and the Gemini credits behind it. Hard failures are the existing
# schema/word/tag checks; the breadth signal is warn-only and cannot fail a run.
run_step gate .venv/bin/python scripts/check_episode.py \
  --episode out/episode.json --meta out/episode_meta.json

# Update durable state, render, and publish only in a real run. Dry runs keep the
# generated artifacts for validation but cause no external or history side effects.
if [ "$DRY_RUN" = "1" ]; then
  log run "dry-run: skipped podcast history, archive, render, and publish"
else
  set +e
  .venv/bin/python scripts/update_history.py --append \
    2>&1 | python3 scripts/run_log.py prefix --src update-history >> "$LOG"
  HIST_RC=${PIPESTATUS[0]}
  set -e
  [ "$HIST_RC" -eq 0 ] || log run "WARNING: update_history failed; history.json may be stale"

  mkdir -p archive/scripts
  cp -f out/script.txt "archive/scripts/$DATE.txt" 2>/dev/null \
    && cp -f out/episode_meta.json "archive/scripts/$DATE-meta.json" 2>/dev/null \
    || log run "WARNING: script archive copy failed"

  run_step render-podcast \
    .venv/bin/python scripts/make_audio.py \
    --episode out/episode.json --out "out/podcast-$DATE.mp3"

  run_step publish python3 - "$DATE" <<'PY' || log run "WARNING: daily publish failed — feed not updated for $DATE; continuing"
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
  rm -f out/daily_options.json out/daily_picks.json  # consumed; must not steer tomorrow
fi

# Wed/Sat/Sun: also produce + publish the deep-dive episode. If the listener replied
# to the previous evening's options push, their choice becomes the topic.
if [ "$DOW" = "3" ] || [ "$DOW" = "6" ] || [ "$DOW" = "7" ]; then
  # DEEPDIVE_TOPIC overrides the phone picker — for manual reruns after a failed night,
  # when the ntfy reply has aged out of the topic's retention window.
  DIVE_CHOICE="${DEEPDIVE_TOPIC:-}"
  if [ -z "$DIVE_CHOICE" ] && [ "$DRY_RUN" != "1" ]; then
    DIVE_CHOICE="$(python3 scripts/ntfy_choice.py --kind deepdive 2>/dev/null || true)"
  fi
  DIVE_TOPIC_NOTE=""
  if [ -n "$DIVE_CHOICE" ]; then
    log run "deepdive: listener pre-chose topic: $DIVE_CHOICE"
    if [ "$DRY_RUN" != "1" ]; then
      python3 scripts/proposal_ledger.py choose --topic "$DIVE_CHOICE" 2>/dev/null \
        || log run "WARNING: proposal ledger update failed"
    fi
    DIVE_TOPIC_NOTE=" The listener pre-chose tonight's topic via the evening picker: \
'${DIVE_CHOICE}'. Take it as the deep-dive topic — skip topic selection and go straight to research."
  fi
  run_step deepdive agent_stage deepdive "Use the weekly-deep-dive skill to produce this week's deep-dive episode \
following its grounding rules and length target (20-25 min). STOP after step 4's validation gate \
passes — do NOT run the render or update_history lines in step 4; the harness handles both. \
Print the topic and word count when done.${DIVE_TOPIC_NOTE}"

  # Same independent re-check for the deep dive; band matches the skill's own gate line.
  run_step gate-deepdive .venv/bin/python scripts/check_episode.py \
    --episode out/deepdive.json --meta out/deepdive_meta.json \
    --min-words 3000 --max-words 4000

  if [ "$DRY_RUN" = "1" ]; then
    log run "dry-run: skipped deep-dive history, archive, render, publish, and ledger cleanup"
  else
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
fi

log run "Done: $DATE"
