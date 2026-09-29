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

# Who started us. A read run fires here every morning around 06:07 that no crontab,
# systemd timer, or autostart entry accounts for (syslog logs no CRON line for it), and
# it duplicates the 07:05 read. Walk the process ancestry so the invocation names its own
# scheduler in the log instead of staying anonymous. Diagnostic only - never fails a run.
invoker_chain() {
  local pid="$PPID" depth=0 out="" args next
  while [ "${pid:-0}" -gt 1 ] && [ "$depth" -lt 4 ]; do
    args="$(ps -o args= -p "$pid" 2>/dev/null | head -1 | cut -c1-160 || true)"
    [ -z "$args" ] && break
    out="${out}${out:+ <- }[$pid] $args"
    next="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
    [ -z "$next" ] && break
    pid="$next"
    depth=$((depth + 1))
  done
  printf '%s' "${out:-unknown}"
}
INVOKER="$(invoker_chain)"

# Never wait on an overlapping scheduler invocation and never ask a person what to do.
exec 9>.run_episode.lock
if ! flock -n 9; then
  # The refused invocation is the one that pages the phone, so it has to identify
  # itself too - it exits before the logging block below ever runs.
  mkdir -p logs 2>/dev/null || true
  printf '%s [run] lock refused: mode=%s pid=%s invoker=%s\n' \
    "$(date '+%FT%T%:z')" "${1:-full}" "$$" "$INVOKER" >> logs/run.log 2>/dev/null || true
  if [ "$DRY_RUN" != "1" ]; then
    python3 scripts/notify.py --priority high --title "Podcast run skipped" \
      --message "Another run_episode.sh invocation already holds the repository lock.
Started by: $INVOKER" \
      >/dev/null 2>&1 || true
  fi
  echo "run_episode: another invocation is active; skipped" >&2
  exit 75
fi

DATE="$(date +%F)"
DOW="$(date +%u)"   # 1=Mon .. 6=Sat 7=Sun
# Cron jobs sharing this script: the full podcast pipeline at 02:00; the daily read on
# its own at 07:05 — 02:00 opens the 5h window, so it has reset by 07:00 and the read no
# longer competes with the podcast for it; and `propose` every evening at 19:30, which gathers
# first and then pushes
# tonight's candidate mini-dives to the listener's phone (ntfy) — plus, on Tue/Fri/Sat,
# the deep-dive topic pitches — so the reply steers the next morning's episodes.
# No arg runs the full pipeline.
MODE="${1:-full}"
case "$MODE" in full|read|propose|deepdive) ;; *) echo "usage: $0 [full|read|propose|deepdive]" >&2; exit 2 ;; esac
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

# --- Logging ------------------------------------------------------------------
# The script owns its log (logs/run.log); cron only catches catastrophic pre-logging
# errors via its own bootstrap redirect. Logging helpers run on the SYSTEM python3 so
# they keep working even if the .venv is broken (a broken .venv was a real failure mode).
LOG="logs/run.log"
LOG_KEEP_RUNS="${LOG_KEEP_RUNS:-10}"   # how many past run blocks to retain in run.log

log() { printf '%s [%s] %s\n' "$(date '+%FT%T%:z')" "$1" "$2" >> "$LOG"; }

# run_step <src> [--optional] <cmd...> : run a stage, timestamping its stdout+stderr
# into the log tagged by <src>, bracketed by start/end markers (exit code + duration).
# Failed optional stages degrade the run instead of triggering a failure alert. Returns
# the command's exit code so callers keep their control-flow semantics (`|| log ...`).
run_step() {
  local src="$1"; shift
  local optional=0
  if [ "${1:-}" = "--optional" ]; then optional=1; shift; fi
  local start; start=$(date +%s)
  log run "step start: $src"
  set +e
  "$@" 2>&1 | python3 scripts/run_log.py prefix --src "$src" >> "$LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  log run "step end: $src exit=$rc dur=$(( $(date +%s) - start ))s"
  if [ "$rc" -ne 0 ]; then
    if [ "$optional" = "1" ]; then DEGRADED+=("$src"); else FAILED+=("$src"); fi
  fi
  return "$rc"
}

agent_stage() {
  local stage="$1" prompt="$2"
  printf '%s' "$prompt" | python3 scripts/agent_runner.py --stage "$stage"
}

FAILED=()
DEGRADED=()
RUN_START=$(date +%s)
python3 scripts/run_log.py trim --keep "$((LOG_KEEP_RUNS-1))" --log "$LOG"
log run "===== RUN START $DATE mode=$MODE dow=$DOW pid=$$ host=$(hostname) git=$(git rev-parse --short HEAD 2>/dev/null || echo '?') ====="
log run "invoker: $INVOKER"

cleanup() {
  local status
  if [ ${#FAILED[@]} -eq 0 ]; then
    if [ ${#DEGRADED[@]} -eq 0 ]; then
      status="OK"
    else
      status="OK degraded=[$(IFS=,; echo "${DEGRADED[*]}")]"
      if [ "$DRY_RUN" != "1" ]; then
        python3 scripts/notify.py --priority default \
          --title "Podcast published with degraded gathering ($DATE $MODE)" \
          --message "Optional steps skipped: $(IFS=,; echo "${DEGRADED[*]}"). The episode still published; see logs/run.log." \
          >/dev/null 2>&1 || true
      fi
    fi
  else
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

# Validate deterministic dependencies and provider configuration before fetching or
# spending model quota. Auth checks are noninteractive and redact credentials. This
# runs AFTER the log and the EXIT trap exist: preflight's own failure mode (an expired
# CLI login) is the likeliest one, and before the trap it exited silently into
# cron-bootstrap.log with no run.log entry and no phone alert.
run_step preflight python3 scripts/preflight.py --mode "$MODE" || exit 78

run_deepdive_episode() {
  # DEEPDIVE_TOPIC overrides the phone picker — for manual reruns after a failed night,
  # when the ntfy reply has aged out of the topic's retention window.
  rm -f out/deepdive_note.txt  # a note is for one episode; never let last week's steer this one
  local dive_choice="${DEEPDIVE_TOPIC:-}"
  if [ -z "$dive_choice" ] && [ "$DRY_RUN" != "1" ]; then
    dive_choice="$(python3 scripts/ntfy_choice.py --kind deepdive 2>/dev/null || true)"
  fi
  local dive_topic_note=""
  local dive_gate_band=""
  if [ -n "$dive_choice" ]; then
    log run "deepdive: listener pre-chose topic: $dive_choice"
    if [ "$DRY_RUN" != "1" ]; then
      python3 scripts/proposal_ledger.py choose --topic "$dive_choice" 2>/dev/null \
        || log run "WARNING: proposal ledger update failed"
    fi
    dive_topic_note=" The listener pre-chose tonight's topic via the evening picker: \
'${dive_choice}'. Take it as the deep-dive topic — skip topic selection and go straight to research. \
Preserve every distinct subject and qualifier in the listener's wording: you may widen it into a \
teachable framing, but must not narrow away or replace any requested dimension. Before writing, \
audit the planned title and outline against the original wording."
  fi
  # An editorial note stands on its own: the listener can say how to teach an episode
  # without naming the topic, and then the writer still picks it.
  if [ -s out/deepdive_note.txt ]; then
    local dive_note
    dive_note="$(cat out/deepdive_note.txt)"
    log run "deepdive: listener editorial note: $dive_note"
    dive_topic_note="$dive_topic_note The listener also left an editorial note for this episode: \
'${dive_note}'. That note OUTRANKS the skill and this prompt on every editorial question — emphasis, \
framing, depth, what to dwell on or skip, how to teach it. Two things it cannot move: the grounding rules \
(every claim still traces to a fetched source) and the harness (rendering, publishing, archiving, and the \
skill files, which you never edit). Length it can move, but only through the band below."
    local band bmin bmax breduced
    band="$(python3 scripts/note_band.py --note out/deepdive_note.txt 2>/dev/null || true)"
    if [ -n "$band" ]; then
      read -r bmin bmax breduced <<<"$band"
      dive_gate_band="--min-words $bmin --max-words $bmax"
      log run "deepdive: the note set the band to $bmin-$bmax words (~$((bmin/165))-$((bmax/165)) min)"
      dive_topic_note="$dive_topic_note This episode's word band is $bmin-$bmax words \
(~$((bmin/165))-$((bmax/165)) minutes), set from that note and enforced by the gate, in place of the usual \
3000-4000. Teach to it: go deeper or narrower to fit, never pad or stop mid-explanation."
      if [ "$breduced" = "1" ]; then
        log run "deepdive: the requested length exceeded what the show renders; reduced to the maximum"
        dive_topic_note="$dive_topic_note The note asked for more time than the show can render, so this is \
the longest episode available; say so in your closing report."
      fi
    fi
  fi
  run_step deepdive agent_stage deepdive "Use the weekly-deep-dive skill to produce this week's deep-dive episode \
following its grounding rules and length target (20-25 min). STOP after step 4's validation gate \
passes — do NOT run the render or update_history lines in step 4; the harness handles both. \
Print the topic and word count when done.${dive_topic_note}"

  # Same independent re-check for the deep dive; band matches the skill's own gate line.
  run_step gate-deepdive .venv/bin/python scripts/check_episode.py \
    --episode out/deepdive.json --meta out/deepdive_meta.json \
    ${dive_gate_band:---min-words 3000 --max-words 4000}

  if [ "$DRY_RUN" = "1" ]; then
    log run "dry-run: skipped deep-dive history, archive, render, publish, and ledger cleanup"
    return
  fi

  set +e
  .venv/bin/python scripts/update_history.py --append --meta out/deepdive_meta.json \
    2>&1 | python3 scripts/run_log.py prefix --src update-history >> "$LOG"
  local hist_dd_rc=${PIPESTATUS[0]}
  set -e
  [ "$hist_dd_rc" -eq 0 ] || log run "WARNING: update_history (deepdive) failed; history.json may be stale"

  mkdir -p archive/scripts
  cp -f out/deepdive_script.txt "archive/scripts/$DATE-deepdive.txt" 2>/dev/null \
    || log run "WARNING: deepdive script archive copy failed"
  # The daily path archives its meta; this one never did, so 35 deep dives left one meta
  # on disk. Everything that reads archived metas was blind to them: the source URLs a
  # deep dive used never reached the aired-URL stamp, and no deep dive's own record was
  # there for a later one to read.
  python3 scripts/note_band.py --note out/deepdive_note.txt --meta out/deepdive_meta.json 2>/dev/null \
    || log run "WARNING: could not record the listener note on the deep-dive meta"
  cp -f out/deepdive_meta.json "archive/scripts/$DATE-deepdive-meta.json" 2>/dev/null \
    || log run "WARNING: deepdive meta archive copy failed"

  # Record the topic that actually aired. The ledger used to hear only about topics the
  # listener picked from the phone, so a topic the writer chose for itself was never
  # marked and stayed on future slates: mixture-of-experts (2026-07-11) and quantization
  # (2026-07-08) were each taught and then pitched again, repeatedly.
  if [ -z "$dive_choice" ]; then
    local aired_topic
    aired_topic="$(python3 - <<'PY'
import json, re
try:
    meta = json.load(open("out/deepdive_meta.json"))
except Exception:
    raise SystemExit(0)
topics = meta.get("topics") or []
label = str(topics[0]) if topics else str(meta.get("title") or "")
print(re.sub(r"^\s*deep dive:\s*", "", label, flags=re.IGNORECASE).strip())
PY
)"
    if [ -n "$aired_topic" ]; then
      python3 scripts/proposal_ledger.py choose --topic "$aired_topic" \
        && log run "deepdive: recorded writer-chosen topic in the ledger: $aired_topic" \
        || log run "WARNING: proposal ledger update failed for writer-chosen topic"
    else
      log run "WARNING: could not read the aired deep-dive topic; ledger not updated"
    fi
  fi

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
}

# In `read` mode (the separate 07:05 cron job) write + publish ONLY the daily read, then
# stop. The skill builds the EPUB into docs/reads/ and records reads_history.json; we then
# email it to the Kindle and commit the EPUB + reads_history so it persists and serves on
# Pages. Non-fatal steps mirror the podcast path: a failed read/email must not wedge the run.
if [ "$MODE" = "read" ]; then
  READ_RECORD_INSTRUCTION="Build the EPUB with the cover and record the issue."
  if [ "$DRY_RUN" = "1" ]; then
    READ_RECORD_INSTRUCTION="Build the EPUB with the cover, but do not update reads_history.json; stop after the EPUB is validated."
  fi
  if ! run_step read agent_stage read "Use the daily-read skill to write today's issue of Self Attention end to end, \
following its reasoning, grounding, and the day's length target. ${READ_RECORD_INSTRUCTION} \
Print the EPUB path when done."; then
    log run "WARNING: daily read failed; skipped Kindle delivery and publishing"
  elif [ "$DRY_RUN" = "1" ]; then
    log run "dry-run: skipped Kindle delivery and read publish"
  else
    run_step kindle python3 scripts/send_to_kindle.py --epub "docs/reads/self-attention-$DATE.epub" \
      || log run "WARNING: Kindle email failed; EPUB still on GitHub Pages"
    run_step publish-read python3 scripts/publish_read.py --date "$DATE" \
      || log run "WARNING: read publish failed; EPUB may be unpushed"
  fi
  exit 0
fi

# Manual recovery after a failed Wed/Sat/Sun teaching episode. This deliberately skips
# gathering and every daily-podcast stage, while retaining the same gate/render/publish
# path as a normal full run.
if [ "$MODE" = "deepdive" ]; then
  rm -f out/deepdive_script.txt out/deepdive_meta.json \
    out/deepdive.json out/deepdive_shownotes.md
  log run "prep: cleared deep-dive scratch; skipped gather and daily episode"
  run_deepdive_episode
  log run "Done: $DATE deepdive"
  exit 0
fi

GATHER_MANIFEST="out/gather_manifest.json"
GATHER_MAX_AGE_HOURS="${GATHER_MAX_AGE_HOURS:-12}"

# Build the one canonical gather used by both evening proposal halves and the 02:00
# writers. Scoring is optional; source artifacts and consolidation are still useful
# when the local Qwen runtime is unavailable. The manifest is written last, only after
# the raw inputs, candidate set, and explicit Tier-1 coverage statuses validate.
gather_manifest_step() {
  # The consolidator drops publication dates and cannot be relied on to carry a repeat
  # verdict, so the two facts the writer cannot reconstruct are stamped onto its output
  # instead of routed through it: when each story was published, and which past episodes
  # already aired its URL. It runs here, ahead of the checksum, so no manifest can
  # certify an unstamped candidate set - including on the manifest-only resume path.
  run_step stamp-candidates --optional python3 scripts/stamp_candidates.py \
    --candidates out/candidates.json --sources out/sources.json --crawl out/crawl.json \
    --archive archive/scripts \
    || log run "WARNING: candidate stamping failed; candidates carry no airing or date facts"
  run_step gather-manifest --optional python3 scripts/gather_manifest.py create \
    --manifest "$GATHER_MANIFEST" --out-dir out --config config/sources.yaml \
    || log run "WARNING: gather produced no valid reusable manifest"
}

gather_sources() {
  local reason="$1"
  local resume_after_crawl="${2:-0}"
  # The gather is expensive at the end, not the start: scoring and consolidation cost
  # ~30 minutes, and a manifest-only failure (a crawl status the gate refuses) throws
  # away artifacts that are themselves fine. GATHER_RESUME_AFTER_CONSOLIDATE=1 rebuilds
  # the manifest from the existing artifacts and nothing else.
  if [ "${GATHER_RESUME_AFTER_CONSOLIDATE:-0}" = "1" ]; then
    for artifact in sources.json crawl.json candidates.json; do
      if [ ! -s "out/$artifact" ]; then
        FAILED+=("resume-after-consolidate")
        log run "ERROR: cannot resume after consolidate without out/$artifact"
        return 1
      fi
    done
    rm -f "$GATHER_MANIFEST"
    log run "gather: reusing $reason gather artifacts; rebuilding manifest only"
    gather_manifest_step
    return 0
  fi
  if [ "$resume_after_crawl" = "1" ]; then
    if [ ! -s out/sources.json ] || [ ! -s out/crawl.json ]; then
      FAILED+=("resume-after-crawl")
      log run "ERROR: cannot resume after crawl without out/sources.json and out/crawl.json"
      return 1
    fi
    rm -f out/source_scores.json out/candidates.json out/crawl_repair.json "$GATHER_MANIFEST"
    log run "gather: resuming $reason gather after crawl"
  else
    rm -f out/sources.json out/crawl.json out/crawl_repair.json out/source_scores.json \
      out/candidates.json "$GATHER_MANIFEST"
    log run "gather: starting $reason gather"

    run_step fetch --optional python3 scripts/fetch_sources.py \
      --hours 48 --out out/sources.json \
      || log run "WARNING: structured fetch failed"

    run_step crawl --optional agent_stage crawl "Use the Skill tool to load the source-crawler skill exactly. \
Read config/sources.yaml and treat every complete source object whose method is 'fetch' (both tiers, including \
its name, URL, tier, and window_hours) as the exact crawl list. Use each source's window_hours, defaulting to \
48 hours only when absent; do not reduce 168-hour sources to today/yesterday. Record exactly one explicit \
ok, no_recent_items, or failed status for every configured source in source_statuses. Write one item per concrete \
development with its own title and primary development URL, never an index-page rollup. Every item must carry \
published_at plus date_status='verified', or published_at=null plus date_status='unknown' when diligent inspection \
cannot establish a date. Keep exact configured names in item sources, including backup-search recoveries. Recover \
Tier-1 failures via a backup search and write out/crawl.json in the skill contract. Use WebFetch, WebSearch, and Write directly; \
do not create helper scripts or ask for shell access." \
      || log run "WARNING: crawl failed"

    # The crawl agent has silently dropped configured sources from source_statuses on
    # three of the eight nights before this check existed, and has marked a Tier-1 source
    # failed while writing no matching failure record. The manifest gate catches both,
    # but only after ~25 minutes of scoring and consolidation, which loses the evening
    # picker. Catch them here instead and recrawl just those sources.
    crawl_gaps=""; gaps_rc=0
    if [ -s out/crawl.json ]; then
      # One trailing comma in the agent's JSON cost the whole 2026-09-26 evening: crawl
      # freshness, first-seen indexing, scoring and the manifest each died on the same
      # JSONDecodeError, so no manifest existed and no slate went to the phone. The coverage
      # check below died on it too, which is why the repair pass built for a broken crawl
      # never ran. Legal syntax first, then everything else.
      run_step crawl-sanitize --optional python3 scripts/crawl_repair.py sanitize \
        --crawl out/crawl.json \
        || log run "WARNING: out/crawl.json is not valid JSON and the damage was not a trailing comma"
      set +e
      crawl_gaps=$(python3 scripts/crawl_repair.py missing \
        --config config/sources.yaml --crawl out/crawl.json 2>/dev/null)
      gaps_rc=$?
      set -e
    fi
    if [ "$gaps_rc" = "3" ]; then
      log run "crawl: configured sources left unanswered by crawl.json; running repair pass"
      # The status vocabulary is spelled out here, exactly as the main crawl prompt above
      # spells it out. Leaving it to "the skill's crawl contract" is what let the repair
      # agent coin `no_items_in_window` for no_recent_items on 2026-09-23 while this
      # prompt's own wording ("window_hours", "unsupported status") pulled toward it.
      CRAWL_REPAIR_PROMPT="Use the Skill tool to load the \
source-crawler skill exactly. Crawl ONLY these source objects, which an earlier crawl pass either omitted \
or left with an unsupported status, using each source's window_hours and 48 hours when absent: $crawl_gaps \
Write out/crawl_repair.json (NOT out/crawl.json) in the skill's crawl contract, carrying only these \
sources' items, failures, and exactly one source_statuses record per source listed above. Each record's status \
must be one of the three literal strings ok, no_recent_items, or failed - never a synonym, paraphrase, or \
variant spelling, however reasonable it reads. Each record must also repeat its source's configured name \
verbatim, alongside that source's url, tier, and window_hours copied from the list above. Write one item per \
development with title, primary development URL, a \"sources\" LIST holding the exact configured name (the key is \
plural and stays a list even for one source), and either a verified published_at with date_status \"verified\" or \
date_status \"unknown\"; never use an index-page rollup or the crawl date. Use WebFetch, \
WebSearch, and Write directly; do not create helper scripts or ask for shell access."
      repair_merged=0
      run_step crawl-repair --optional agent_stage crawl_repair "$CRAWL_REPAIR_PROMPT" \
        && run_step crawl-merge --optional python3 scripts/crawl_repair.py merge \
          --config config/sources.yaml --crawl out/crawl.json --repair out/crawl_repair.json \
        && repair_merged=1
      # The merge is the only thing that ever reads the repair's output, and it runs after
      # the agent has exited, so a contract violation used to be terminal and silent to the
      # agent that caused it. Hand the rejections back once. Valid records from the first
      # attempt have already landed; this pass only has to close what is still open.
      if [ "$repair_merged" != "1" ] && [ -s out/crawl_repair_rejections.txt ]; then
        log run "crawl: repair pass broke the crawl contract; retrying once with the rejections"
        run_step crawl-repair-retry --optional agent_stage crawl_repair "$CRAWL_REPAIR_PROMPT

Your previous attempt was rejected. Each line below names a source and what was wrong with the record you \
wrote for it. Recrawl exactly those sources and rewrite out/crawl_repair.json in full, fixing every line:
$(cat out/crawl_repair_rejections.txt)" \
          && run_step crawl-merge-retry --optional python3 scripts/crawl_repair.py merge \
            --config config/sources.yaml --crawl out/crawl.json --repair out/crawl_repair.json \
          && repair_merged=1
      fi
      [ "$repair_merged" = "1" ] \
        || log run "WARNING: crawl repair did not close every gap; the manifest gate decides"
    fi
  fi

  # Publication freshness governs the phone, not whether the raw gather is useful.
  # Annotate before first-seen/scoring so rediscovery cannot make old material fresh.
  # Failure degrades gathering and later makes the proposal gate fail closed, while
  # the same raw artifacts remain available to the 02:00 writer.
  run_step crawl-freshness --optional python3 scripts/crawl_freshness.py \
    --config config/sources.yaml --crawl out/crawl.json \
    || log run "WARNING: crawl freshness unavailable; daily ntfy proposals will be blocked"

  # Publication dates are missing or inconsistent across the raw sources. Record when
  # this pipeline first saw each canonical URL and stamp both raw inputs before scoring
  # and consolidation. Dry runs get the age signal without mutating durable state.
  SEEN_INDEX_ARGS=()
  [ "$DRY_RUN" = "1" ] && SEEN_INDEX_ARGS+=(--no-save)
  run_step seen-index --optional python3 scripts/seen_index.py \
    --sources out/sources.json --crawl out/crawl.json --state .state/seen_urls.json \
    "${SEEN_INDEX_ARGS[@]}" \
    || log run "WARNING: first-seen indexing failed; candidates have no age signal"

  # Archive the pre-consolidation inputs during the canonical gather. This is
  # write-only training data and cannot make the show fail.
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

  run_step score --optional python3 scripts/score_sources.py \
    --sources out/sources.json --crawl out/crawl.json --out out/source_scores.json \
    || log run "WARNING: Smallbatch scoring failed; candidates retain existing signals"

  run_step consolidate --optional agent_stage consolidate "Use the source-consolidator skill exactly. Merge \
out/sources.json and out/crawl.json (use whichever exist) into out/candidates.json, flagging likely repeats \
against history.json. If out/source_scores.json exists with status ok, preserve the strongest supporting four \
dimensions, total, pinned package identity, and all raw provenance on every candidate exactly as the skill \
requires. A low score never removes an item. Write the file even if one raw input or the score sidecar is missing." \
    || log run "WARNING: consolidate failed"

  gather_manifest_step
}

# In `propose` mode (nightly ~19:30 cron) the gather runs before a cheap session drafts
# today's stories the listener can lock as tomorrow's mini-dives, and — the night before
# a deep dive — six deep-dive topic pitches. Both ride in ONE ntfy push, numbers for the
# mini-dives and letters for the deep dive, so there is one notification and one reply.
# The 02:00 run reads the reply via scripts/ntfy_choice.py. No reply -> the writers pick,
# as ever.
if [ "$MODE" = "propose" ]; then
  # Tue/Fri/Sat evenings feed the Wed/Sat/Sun deep dives; the other four nights push
  # the mini-dive slate alone.
  case "$DOW" in 2|5|6) DEEPDIVE_TOMORROW=yes ;; *) DEEPDIVE_TOMORROW=no ;; esac

  # Clear last night's slates first: a drafting stage that fails must not re-push stale
  # options, and on a non-deep-dive night a leftover deep-dive slate would bump the
  # retirement ledger for topics nobody ever saw.
  rm -f out/daily_options.json out/deepdive_options.json

  gather_sources evening "${GATHER_RESUME_AFTER_CRAWL:-0}"
  if ! PROPOSAL_GATHER_ID="$(python3 scripts/gather_manifest.py validate \
      --manifest "$GATHER_MANIFEST" --out-dir out --config config/sources.yaml \
      --max-age-hours "$GATHER_MAX_AGE_HOURS" 2>>"$LOG")"; then
    log run "WARNING: no valid evening gather; skipped proposal drafting and notification"
    FAILED+=("evening-gather")
    exit 1
  fi

  if [ "$DRY_RUN" != "1" ]; then
    if ! run_step proposal-novelty-sync python3 scripts/daily_ledger.py sync \
        --history history.json --archive archive/scripts \
        --traces logs/agent-traces --run-log "$LOG"; then
      log run "ERROR: daily novelty state could not be synchronized; skipped proposal drafting and notification"
      exit 1
    fi
  fi

  # Put the load-bearing recent coverage directly in the prompt. history.json is
  # newest-first, but agents repeatedly sliced its tail and read the oldest episodes;
  # they also skipped the archive instruction on most nights.
  PROPOSAL_RECENT_CONTEXT="$(python3 scripts/proposal_context.py 2>>"$LOG" || true)"

  if [ "$DEEPDIVE_TOMORROW" = "yes" ]; then
    DIVE_SLATE_TASK="SECOND, the deep-dive slate. Read .agents/skills/weekly-deep-dive/SKILL.md (its topic palette and \
selection criteria), history.json (recent episodes, active threads, longterm.concepts_taught), \
deepdive_proposals.json (the proposal ledger — NEVER re-pitch a retired topic: times_proposed >= 3 \
and never chosen; NEVER re-pitch a topic whose entry carries a 'chosen' date, which means it has already \
been an episode, however long ago and however differently you would frame it now; avoid re-pitching \
anything already proposed twice unless it's newly urgent), the \
2-3 newest daily scripts in archive/scripts/, out/gather_manifest.json, and out/candidates.json. \
Propose exactly 8 candidate topics for tomorrow's deep-dive episode as a MIXED slate: \
about 2 of type 'mechanism' (the idea under this week's news), exactly 3 'foundational', at least 1 \
'history', at least 1 'debate' — plus one wildcard of any type. Foundational carries three slots \
because it is the type the listener picks most: read the skill's foundational lanes and honour both \
what belongs there and what does not. The three must not all be the same kind of thing — spread them \
across the areas that section names rather than offering three variations on one idea. Rules: a topic is NEVER a single \
paper — it is the idea or capability the paper instantiates, with the week's material as evidence; \
every pitch must briefly say what the twenty minutes would actually contain (so thin topics reveal \
themselves while drafting); nothing already taught (concepts_taught / past deepdive records). Copy \
the manifest's gather_id exactly. Write out/deepdive_options.json as exactly \
{\"gather_id\": \"${PROPOSAL_GATHER_ID}\", \"options\": [{\"n\": 1, \"type\": \"mechanism|foundational|\
history|debate\", \"topic\": \"short topic name\", \"pitch\": \"one-line pitch: the hook plus what \
the episode contains\"}]}."
  else
    DIVE_SLATE_TASK="SECOND: tomorrow is not a deep-dive morning, so propose no deep-dive topics — \
copy gather_id from out/gather_manifest.json and write out/deepdive_options.json as exactly \
{\"gather_id\": \"${PROPOSAL_GATHER_ID}\", \"options\": []} and move on."
  fi

  run_step propose agent_stage propose "Two slates for tonight's listener push; write both files. \
FIRST, the mini-dive slate for tomorrow's daily episode. Read out/gather_manifest.json and \
out/candidates.json: this is tonight's canonical consolidated and optionally Smallbatch-scored gather, \
and it is the exact candidate set the 02:00 writer will reuse. Read history.json (recent episodes, active threads, and each episode's \
'dives'), listener.yaml, feedback.md, and the 2-3 newest scripts in archive/scripts/. Propose \
exactly 15 stories the listener could lock as tomorrow's mini-dives, ordered strongest first. Take \
about 8 of them from the stories that objectively earned a dive — multi-source pickup, real \
community traction (HF upvotes, HN points), or continuation of an active history.json thread — and \
mark about 7 as wildcards: stories you find genuinely interesting but would not spend a dive on \
unprompted. On a thin news day let the wildcard share grow rather than padding the earned tier with \
stories that did not earn it. The slate is a menu, so make it a varied one: the fifteen must not \
all be papers, and the wildcards especially should reach across different kinds of story (a \
release, a policy or business move, an older thread that just advanced, something odd or human) \
rather than extending the signal ranking. Smallbatch is a ranking aid, not a filter: low-scored \
candidates remain eligible. Skip anything the show already dived unless it has materially advanced \
since; a story the show merely named or resolved is fair game only if it is not in the recent rundown \
sources embedded below. A candidate carrying aired_on has already been on the air on those exact dates - do not \
propose it again unless it has materially advanced since the most recent one, and say what advanced in its why. \
Treat published_at with date_status 'unknown' as an unverified guess: a reason to doubt a story is new, never \
evidence that it is. Never propose an entry listed in current_candidate_blockers in the deterministic \
context below; the phone gate enforces those blockers again after drafting. \
Use days_since_first_seen as a slate-novelty signal, not a claimed publication date: fresher stories \
break otherwise close ranking ties, while an older story needs newly accumulated signal or a material \
advance rather than the same deterministic score. Copy the manifest's gather_id exactly. \
Write out/daily_options.json as exactly {\"gather_id\": \"${PROPOSAL_GATHER_ID}\", \"options\": \
[{\"n\": 1, \"label\": \"short story label, phone-screen length\", \"url\": \"primary source URL\", \
\"why\": \"1-2 lines: what happened and who specifically would care\", \"signal\": \"terse evidence \
it earned a slot, e.g. '4 src' or 'HN 890' or 'HF 210' or 'thread: agent evals'\", \"wildcard\": \
false}]}. ${DIVE_SLATE_TASK} Recent coverage context, assembled deterministically and already \
newest-first (do not tail-slice it): ${PROPOSAL_RECENT_CONTEXT} Do nothing else." \
    || log run "WARNING: propose failed; the writers will pick as usual"

  PROPOSALS_VALID=yes
  PROPOSAL_ERROR=no
  if ! run_step proposal-identity --optional python3 scripts/gather_manifest.py verify-proposals \
      --manifest "$GATHER_MANIFEST" --out-dir out --config config/sources.yaml \
      --max-age-hours "$GATHER_MAX_AGE_HOURS" \
      --proposal out/daily_options.json --proposal out/deepdive_options.json; then
    PROPOSALS_VALID=no
    PROPOSAL_ERROR=yes
    rm -f out/daily_options.json out/deepdive_options.json
    log run "WARNING: proposal files did not match the canonical gather identity; skipped notification"
  fi

  if [ "$DRY_RUN" != "1" ] && [ "$PROPOSALS_VALID" = "yes" ]; then
    if ! run_step daily-proposal-gate python3 scripts/daily_ledger.py filter \
        --options out/daily_options.json --crawl out/crawl.json; then
      PROPOSALS_VALID=no
      PROPOSAL_ERROR=yes
      rm -f out/daily_options.json out/deepdive_options.json
      log run "ERROR: daily novelty gate failed closed; skipped the combined notification"
    fi
  fi

  # Slate passes: renumber, stamp sent_at, and emit each half's message body. The
  # deep-dive half also runs its retirement ledger. Both print nothing when empty.
  DAILY_MSG=""
  DIVE_MSG=""
  if [ "$DRY_RUN" != "1" ] && [ "$PROPOSALS_VALID" = "yes" ]; then
    DAILY_MSG="$(python3 scripts/daily_options.py record || true)"
    DIVE_MSG="$(python3 scripts/proposal_ledger.py record || true)"
  fi

  # One push. Headers only when both halves are present — on a mini-dives-only night
  # the title already says what the numbers are.
  TITLE="Tonight's dives — reply with a number or two"
  FOOTER="Reply: numbers = tonight's dives (up to 3) · plain text = a dive of your own"
  NOTE_HINT="· \"note: ...\" = how to do the episode (1-4 sentences, on its own or after a pick)"
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
  FOOTER="$FOOTER
$NOTE_HINT"
  NOTIFY_SENT=no
  if [ -n "$OPTIONS_MSG" ]; then
    # High priority, like the failure alert: on Android the default-priority channel
    # can be silenced, and a picker that arrives without a banner is a picker nobody
    # answers — the writers then choose for themselves and the reply never happens.
    if run_step notify python3 scripts/notify.py \
        --priority high \
        --title "$TITLE" \
        --message "$OPTIONS_MSG

$FOOTER"; then
      NOTIFY_SENT=yes
    else
      log run "WARNING: options notification failed"
    fi
  fi
  # Only count a daily slate after ntfy confirms delivery. Filtering already proved
  # the prospective state readable before the external side effect.
  if [ "$NOTIFY_SENT" = "yes" ] && [ -n "$DAILY_MSG" ]; then
    if ! run_step daily-ledger-record python3 scripts/daily_ledger.py record \
        --options out/daily_options.json; then
      PROPOSAL_ERROR=yes
      log run "ERROR: ntfy succeeded but daily proposal state could not be committed"
    fi
  fi
  [ "$PROPOSAL_ERROR" = "no" ] || exit 1
  exit 0
fi

# --- Reuse the evening gather; recover only when it is absent or invalid -------
# A valid manifest binds the exact raw, score, and candidate bytes seen by proposals.
# There is deliberately no overnight delta pull: news after the evening cutoff waits
# for the next cycle. A failed evening gather gets one full recovery attempt here.
rm -f out/daily_picks.json \
  out/script.txt out/episode_meta.json out/episode.json out/shownotes.md \
  out/deepdive_script.txt out/deepdive_meta.json out/deepdive.json out/deepdive_shownotes.md
log run "prep: cleared episode scratch; preserving canonical gather artifacts"

if GATHER_ID="$(python3 scripts/gather_manifest.py validate \
    --manifest "$GATHER_MANIFEST" --out-dir out --config config/sources.yaml \
    --max-age-hours "$GATHER_MAX_AGE_HOURS" 2>>"$LOG")"; then
  log run "gather: reusing fresh evening $GATHER_ID"
else
  log run "gather: evening manifest missing or invalid; starting recovery"
  gather_sources recovery
  GATHER_ID="$(python3 scripts/gather_manifest.py validate \
    --manifest "$GATHER_MANIFEST" --out-dir out --config config/sources.yaml \
    --max-age-hours "$GATHER_MAX_AGE_HOURS" 2>>"$LOG" || true)"
fi

# The listener's mini-dive picks, if they replied to last evening's push. Unlike the
# deep-dive read below this is not gated on DRY_RUN: it is a read-only poll with no side
# effect (the deep-dive call sits next to a ledger write, which is what that guard is for),
# so a dry run exercises the picker for real. DAILY_DIVES overrides the phone.
DIVE_PICK_NOTE=""
DIVE_PICKS="$(python3 scripts/ntfy_choice.py --kind daily 2>/dev/null || true)"
if [ "$DRY_RUN" != "1" ]; then
  python3 scripts/daily_ledger.py choose 2>>"$LOG" \
    || log run "WARNING: daily proposal choice ledger update failed"
fi
if [ -n "$DIVE_PICKS" ]; then
  log run "podcast: listener pre-chose dives: $DIVE_PICKS"
  DIVE_PICK_NOTE=" The listener answered the evening picker: read out/daily_picks.json. Any stories it \
lists are locked dives — follow the skill's pre-chosen-dives rule. If it carries a \"note\", that note \
OUTRANKS the skill and this prompt on every editorial question: emphasis, framing, structure, tone, which \
stories to dive, even dropping or reordering a locked pick from the same reply. Two things it cannot move: \
the grounding rules (every claim still traces to a fetched source) and the harness (rendering, publishing, \
archiving, and the skill files, which you never edit). Length it can move, but only through the band below. \
A note can arrive with no stories attached; you then choose the dives yourself and shape them as it asks."
fi

# A note may set tonight's length. The gate hard-fails the run before TTS on the word band,
# so a request the writer simply obeyed would cost the whole episode; the harness converts
# it, clamps it, and hands the same numbers to the writer and to the gate. The gate stays an
# independent check that way — the writer never picks the bar it is judged against.
GATE_BAND=""
DAILY_BAND="$(python3 scripts/note_band.py --note out/daily_picks.json 2>/dev/null || true)"
if [ -n "$DAILY_BAND" ]; then
  read -r BMIN BMAX BREDUCED <<<"$DAILY_BAND"
  GATE_BAND="--min-words $BMIN --max-words $BMAX"
  log run "podcast: the note set tonight's band to $BMIN-$BMAX words (~$((BMIN/165))-$((BMAX/165)) min)"
  DIVE_PICK_NOTE="$DIVE_PICK_NOTE Tonight's word band is $BMIN-$BMAX words \
(~$((BMIN/165))-$((BMAX/165)) minutes), set from that note and enforced by the gate, in place of the usual \
3000-4700. Write to it: cut or expand coverage to fit the length the listener asked for, never pad or \
truncate mid-thought."
  if [ "$BREDUCED" = "1" ]; then
    log run "podcast: the requested length exceeded what the show renders; reduced to the maximum"
    DIVE_PICK_NOTE="$DIVE_PICK_NOTE The note asked for more time than the show can render, so this is the \
longest episode available; say so in your closing report."
  fi
fi

# 3: Opus selects, verifies, and writes the script — stops after validation.
run_step podcast agent_stage podcast "Use the daily-ai-podcast skill to produce today's episode. The harness has \
already supplied the canonical evening gather (identity ${GATHER_ID:-unavailable}) in out/sources.json, \
out/crawl.json, out/source_scores.json when scoring succeeded, and out/candidates.json, so SKIP gather \
steps 1, 2, and 2.5. Do step 1.5 (recall history) then steps 3 and 3.5 (select, verify, write, \
validate). STOP after the gate passes — do NOT run steps 4 or 4.5; the harness renders and updates \
history. If out/candidates.json is missing after the harness's documented recovery attempt, work from \
the surviving local gather files and memory; do not make a second gathering pass. \
Print the episode title and word count when done.${DIVE_PICK_NOTE}"

# Re-run the gate here, independently. The writer runs it inside its own session and
# reports the result, which means "gate passed, zero warnings" in the log has until now
# been the writer grading its own work. Running it again costs a second and catches both
# a mis-reported pass and anything that changed after the writer stopped — before we spend
# ~20 minutes of TTS and the Gemini credits behind it. Hard failures are the existing
# schema/word/tag checks; the breadth signal is warn-only and cannot fail a run.
run_step gate .venv/bin/python scripts/check_episode.py \
  --episode out/episode.json --meta out/episode_meta.json $GATE_BAND

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
  # What direction produced this episode, kept with it. After the gate, so the meta the
  # gate read is the one the writer wrote; before the archive copy, so the record persists.
  python3 scripts/note_band.py --note out/daily_picks.json --meta out/episode_meta.json 2>/dev/null \
    || log run "WARNING: could not record the listener note on the episode meta"
  cp -f out/script.txt "archive/scripts/$DATE.txt" 2>/dev/null \
    && cp -f out/episode_meta.json "archive/scripts/$DATE-meta.json" 2>/dev/null \
    || log run "WARNING: script archive copy failed"
  python3 scripts/daily_ledger.py mark-aired \
    --meta "archive/scripts/$DATE-meta.json" 2>>"$LOG" \
    || log run "WARNING: daily aired-story ledger update failed"

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
  run_deepdive_episode
fi

log run "Done: $DATE"
