#!/usr/bin/env bash
# End-to-end test of run_episode.sh's orchestration + logging, WITHOUT calling the
# real Claude CLI, the Gemini API, the real publisher, or the real Kindle emailer.
#
# How it stays hermetic:
#   - Runs a COPY of run_episode.sh in a temp sandbox; scripts/publish.py and
#     scripts/send_to_kindle.py are replaced with mocks (no uploads / no email).
#   - HOME is pointed at the sandbox, so $HOME/.local/bin/claude resolves to a FAKE
#     claude (run_episode.sh forces ~/.local/bin onto PATH, so only HOME-override wins).
#     The fake claude writes the artifacts each skill would produce.
#   - Gemini is never reached because it is only ever called by the real claude agent
#     inside the skill, which we never run.
#   - The usage poller runs for real but, with the sandbox HOME, finds no credentials
#     and logs an {"err":...} line — so the test needs no network and no secrets.
#
# Exits non-zero if any assertion fails.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d)"
GD="$(mktemp -d)"   # a real git repo for Scenario D's branch-guard checks
trap 'rm -rf "$SB" "$GD"' EXIT
LOG="$SB/logs/run.log"
FAILED_ASSERT=0

ok()  { echo "  ok   - $1"; }
bad() { echo "  FAIL - $1"; FAILED_ASSERT=1; }
has() { grep -qF -- "$2" "$LOG" && ok "$1" || bad "$1 (missing: $2)"; }
hasre() { grep -qE -- "$2" "$LOG" && ok "$1" || bad "$1 (no match: $2)"; }
no()  { grep -qF -- "$2" "$LOG" && bad "$1 (unexpected: $2)" || ok "$1"; }
# assert the exact set of steps that ran, so adding/dropping a step in
# run_episode.sh trips the test until this expectation is updated.
steps() {  # $1 = expected sorted, space-joined step names
  local actual
  actual=$(grep -oE 'step start: [a-z-]+' "$LOG" | sed 's/step start: //' | sort -u | tr '\n' ' ' | sed 's/[[:space:]]*$//')
  [ "$actual" = "$1" ] && ok "step set == [$1]" || bad "step set mismatch: expected [$1] got [$actual]"
}
# True if a usage poller spawned by THIS sandbox run is still alive. Scoped to the
# sandbox by cwd: the poller's cmdline ("scripts/run_log.py poll --log logs/run.log")
# is relative and so identical for every run_episode.sh. An unscoped pgrep therefore
# also matches the poller of a REAL nightly run that is in progress — e.g. when this
# test runs from its own pre-push hook during the live publish step — and would wrongly
# fail the cleanup assertion (and so block the nightly publish). Match on /proc cwd.
sandbox_poller_alive() {
  local pid sb; sb="$(readlink -f "$SB")"
  for pid in $(pgrep -f "scripts/run_log.py poll" 2>/dev/null); do
    [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$sb" ] && return 0
  done
  return 1
}

# ---- sandbox layout ----------------------------------------------------------
mkdir -p "$SB/scripts" "$SB/out" "$SB/docs/reads" "$SB/logs" "$SB/home/.local/bin"
# Provide a .venv/bin/python so the harness's .venv/bin/python calls resolve to
# the system python3, which then runs the mock scripts below.
mkdir -p "$SB/.venv/bin"
ln -sf "$(command -v python3)" "$SB/.venv/bin/python"
cp "$REPO/run_episode.sh" "$SB/run_episode.sh"
cp "$REPO/scripts/run_log.py" "$SB/scripts/run_log.py"

cat > "$SB/scripts/publish.py" <<'PY'
import sys
print("MOCK publish:", " ".join(sys.argv[1:]))
PY
cat > "$SB/scripts/send_to_kindle.py" <<'PY'
import sys
print("MOCK kindle:", " ".join(sys.argv[1:]))
PY
cat > "$SB/scripts/publish_read.py" <<'PY'
import sys
print("MOCK publish_read:", " ".join(sys.argv[1:]))
PY
# Mock fetcher: run_episode.sh now runs the deterministic fetch in-shell before the
# podcast Claude step. Stub it (no network) so the test stays hermetic; it just writes
# a minimal sources.json the way the real fetcher would.
cat > "$SB/scripts/fetch_sources.py" <<'PY'
import pathlib, sys
pathlib.Path("out").mkdir(exist_ok=True)
open("out/sources.json", "w").write('{"feeds": {}}')
print("MOCK fetch:", " ".join(sys.argv[1:]))
PY
# Mock renderer: write a fake MP3. MOCK_NO_MP3=1 makes it fail so the render and
# publish steps both catch the missing audio (testing the failure path end-to-end).
cat > "$SB/scripts/make_audio.py" <<'PY'
import sys, pathlib, os
args = sys.argv[1:]
out = next((args[i+1] for i, a in enumerate(args) if a == "--out"), None)
if os.environ.get("MOCK_NO_MP3"):
    print(f"MOCK make_audio: MOCK_NO_MP3 set, not writing {out}")
    raise SystemExit(1)
if out:
    pathlib.Path(out).write_bytes(b"FAKE-MP3")
    print(f"MOCK make_audio: wrote {out}")
PY
# Mock history updater: no-op (reads/writes history.json which doesn't exist in sandbox).
cat > "$SB/scripts/update_history.py" <<'PY'
import sys
print("MOCK update_history:", " ".join(sys.argv[1:]))
PY

# Fake claude: pick the skill out of the prompt args, emit the expected artifacts.
# Render and history-update now happen in the harness (not inside the Claude session),
# so this mock never writes MP3s — those come from the mock make_audio.py above.
cat > "$SB/home/.local/bin/claude" <<'SH'
#!/usr/bin/env bash
args="$*"; DATE="$(date +%F)"; mkdir -p out docs/reads
if [[ "$args" == *source-crawler* ]]; then
  echo "[fake-claude] ran crawl"
  printf '{"items":[],"failures":[]}\n' > "out/crawl.json"
elif [[ "$args" == *source-consolidator* ]]; then
  echo "[fake-claude] ran consolidate"
  printf '{"items":[],"dropped_off_topic":0}\n' > "out/candidates.json"
elif [[ "$args" == *daily-ai-podcast* ]]; then
  echo "[fake-claude] ran daily-ai-podcast skill"
  printf '{"title":"Test Episode %s","date":"%s","turns":[]}\n' "$DATE" "$DATE" > "out/episode.json"
  printf '{"summary":"test summary"}\n' > "out/episode_meta.json"
  printf 'show notes\n' > "out/shownotes.md"
elif [[ "$args" == *daily-read* ]]; then
  echo "[fake-claude] ran daily-read skill"
  printf 'FAKE-EPUB' > "docs/reads/self-attention-$DATE.epub"
elif [[ "$args" == *weekly-deep-dive* ]]; then
  echo "[fake-claude] ran weekly-deep-dive skill"
  printf '{"title":"DD %s","date":"%s","turns":[]}\n' "$DATE" "$DATE" > "out/deepdive.json"
  printf '{"summary":"dd"}\n' > "out/deepdive_meta.json"
  printf 'dd notes\n' > "out/deepdive_shownotes.md"
else
  # Fail loudly on an unrecognized prompt so a newly-added claude step in
  # run_episode.sh cannot silently slip through untested — extend this mock instead.
  echo "[fake-claude] ERROR: unrecognized prompt (no known skill name): $args" >&2
  exit 1
fi
SH
chmod +x "$SB/home/.local/bin/claude"

# reset generated artifacts so each scenario starts clean (a stale MP3 from a prior
# scenario would otherwise satisfy the publish guard).
reset_artifacts() { rm -f "$SB"/out/* "$SB"/docs/reads/* 2>/dev/null || true; }

# invoke <VAR=val...> : run the sandbox copy; echoes the exit code.
# RUN_EPISODE_ALLOW_ANY_BRANCH=1: the sandbox is a temp dir, not a git repo, so the
# script's main-branch guard would otherwise refuse every scenario. Scenario D below
# tests that guard directly, without this override.
invoke() {
  set +e
  ( cd "$SB" && env -u ANTHROPIC_API_KEY HOME="$SB/home" RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh ) \
    >>"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

# invoke_read <VAR=val...> : run the sandbox copy in `read` mode (the separate 06:30 job).
invoke_read() {
  set +e
  ( cd "$SB" && env -u ANTHROPIC_API_KEY HOME="$SB/home" RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh read ) \
    >>"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

# ---- Scenario A: happy path --------------------------------------------------
echo "Scenario A: successful daily run"
reset_artifacts; : > "$LOG"
rcA="$(invoke LOG_KEEP_RUNS=3)"
[ "$rcA" = "0" ] && ok "exit code 0" || bad "exit code 0 (got $rcA)"
hasre "run start banner"          '===== RUN START .* pid=[0-9]+'
has   "podcast step start"        "step start: podcast"
hasre "podcast step end exit=0"   "step end: podcast exit=0 dur=[0-9]+s"
hasre "publish step end exit=0"   "step end: publish exit=0"
no    "read not in full mode"      "step start: read"
no    "kindle not in full mode"    "step start: kindle"
has   "deterministic prep: scratch cleared" "prep: cleared podcast scratch"
has   "deterministic prep: fetcher ran in-shell" "MOCK fetch:"
has   "gather: crawl ran before opus"   "[fake-claude] ran crawl"
has   "gather: consolidate ran before opus" "[fake-claude] ran consolidate"
has   "captured fake-claude output"  "[fake-claude] ran daily-ai-podcast skill"
has   "publisher was the mock"    "MOCK publish:"
hasre "usage snapshot logged"     '\[usage\] \{'
hasre "run end status OK"         '===== RUN END .* status=OK'
no    "real claude not invoked"   "Use the daily-ai-podcast skill"  # prompt text only appears if claude echoed it
has   "render-podcast ran"        "MOCK make_audio: wrote out/podcast"
# Expected steps depend on the weekday: the deep-dive branch runs Wed (3) / Sat (6) / Sun (7).
expA="consolidate crawl podcast publish render-podcast"
if [ "$(date +%u)" = "3" ] || [ "$(date +%u)" = "6" ] || [ "$(date +%u)" = "7" ]; then
  expA="consolidate crawl deepdive podcast publish publish-deepdive render-deepdive render-podcast"
fi
steps "$expA"
sandbox_poller_alive \
  && bad "usage poller still running" || ok "usage poller terminated after run"

# ---- Scenario E: read mode runs ONLY the read + kindle + publish-read ---------
# The daily read is a separate ~06:30 cron job (`run_episode.sh read`) so it gets its own
# 5h rate-limit window instead of competing with the podcast. It must run the read, email,
# and read-publish — and none of the podcast pipeline.
echo "Scenario E: read mode (06:30 job) runs read + kindle + publish-read only"
reset_artifacts; : > "$LOG"
rcE="$(invoke_read LOG_KEEP_RUNS=3)"
[ "$rcE" = "0" ] && ok "read mode exit 0" || bad "read mode exit 0 (got $rcE)"
hasre "read mode banner"             '===== RUN START .* mode=read'
hasre "read step end exit=0"         "step end: read exit=0"
hasre "kindle step end exit=0"       "step end: kindle exit=0"
hasre "publish-read step end exit=0" "step end: publish-read exit=0"
has   "read built the EPUB"          "[fake-claude] ran daily-read skill"
has   "publish_read was the mock"    "MOCK publish_read:"
no    "podcast did not run in read mode" "step start: podcast"
no    "gather did not run in read mode"  "step start: consolidate"
steps "kindle publish-read read"
sandbox_poller_alive \
  && bad "usage poller still running (read mode)" || ok "usage poller terminated (read mode)"

# ---- Scenario B: render fails -> run fails before reaching publish -----------
# render-podcast is a fatal step (no || handler), so a failure exits immediately
# via set -e; the read/kindle/publish steps never run.
echo "Scenario B: render failure -> run fails, publish never reached"
reset_artifacts; : > "$LOG"
rcB="$(invoke LOG_KEEP_RUNS=3 MOCK_NO_MP3=1)"
[ "$rcB" != "0" ] && ok "non-zero exit ($rcB)" || bad "expected non-zero exit"
hasre "render step end exit=1"    "step end: render-podcast exit=1"
no    "publish did not run"       "step start: publish"
hasre "run end status FAIL"       '===== RUN END .* status=FAIL'
sandbox_poller_alive \
  && bad "usage poller still running" || ok "usage poller terminated after failed run"

# ---- Scenario C: retention trim ----------------------------------------------
echo "Scenario C: LOG_KEEP_RUNS=3 caps run.log at 3 run blocks"
reset_artifacts; : > "$LOG"
for _ in 1 2 3 4 5; do invoke LOG_KEEP_RUNS=3 >/dev/null; done
blocks="$(grep -c 'RUN START' "$LOG")"
[ "$blocks" = "3" ] && ok "exactly 3 run blocks retained (after 5 runs)" \
                     || bad "expected 3 run blocks, found $blocks"

# ---- Scenario D: branch guard (switch when clean, refuse when dirty) ----------
# Publishing is branch-scoped, so an off-main run must get onto main first: switch
# automatically when the tree is clean, but refuse rather than clobber in-progress work
# when it's dirty. (A feature-branch run is what kept 2026-06-20 off the live feed.)
# These checks run WITHOUT the override, in a throwaway git repo with the same mocks.
echo "Scenario D: off-main — auto-switch when clean, refuse when dirty"
mkdir -p "$GD/scripts" "$GD/home/.local/bin" "$GD/out" "$GD/docs/reads" "$GD/logs"
mkdir -p "$GD/.venv/bin" && ln -sf "$(command -v python3)" "$GD/.venv/bin/python"
cp "$SB/run_episode.sh" "$GD/run_episode.sh"
cp "$SB/scripts/run_log.py" "$SB/scripts/publish.py" "$SB/scripts/send_to_kindle.py" \
   "$SB/scripts/fetch_sources.py" "$SB/scripts/make_audio.py" "$SB/scripts/update_history.py" \
   "$GD/scripts/"
cp "$SB/home/.local/bin/claude" "$GD/home/.local/bin/claude"
printf 'out/\nlogs/\ndocs/reads/\nconsole.txt\n' > "$GD/.gitignore"
echo seed > "$GD/tracked.txt"   # a tracked file we can dirty in D2 without touching the script
( cd "$GD" && git init -q && git config user.email t@t && git config user.name t \
    && git add -A && git commit -qm init && git branch -M main && git branch feature ) >/dev/null
GDLOG="$GD/logs/run.log"
gd_run() { ( cd "$GD" && env -u ANTHROPIC_API_KEY HOME="$GD/home" "$@" bash run_episode.sh ); }

# D1: clean tree on a feature branch -> auto-switch to main, run normally.
( cd "$GD" && git checkout -q feature ); : > "$GDLOG"
set +e; gd_run LOG_KEEP_RUNS=3 >"$GD/console.txt" 2>&1; d1rc=$?; set -e
d1branch="$( cd "$GD" && git rev-parse --abbrev-ref HEAD )"
[ "$d1rc" = "0" ]            && ok "clean off-main: exit 0"         || bad "clean off-main: expected exit 0 (got $d1rc)"
[ "$d1branch" = "main" ]     && ok "clean off-main: switched to main" || bad "clean off-main: ended on $d1branch"
grep -q "step start: podcast" "$GDLOG" && ok "clean off-main: pipeline ran" || bad "clean off-main: no step ran"

# D2: dirty tree on a feature branch -> refuse, switch nothing, run nothing.
( cd "$GD" && git checkout -q feature && echo edit >> tracked.txt ); : > "$GDLOG"
set +e; d2out="$(gd_run 2>&1)"; d2rc=$?; set -e
[ "$d2rc" != "0" ]          && ok "dirty off-main: refused (exit $d2rc)" || bad "dirty off-main: expected non-zero"
echo "$d2out" | grep -qF "uncommitted changes" && ok "dirty off-main: refusal message" || bad "dirty off-main: message missing"
[ "$( cd "$GD" && git rev-parse --abbrev-ref HEAD )" = "feature" ] && ok "dirty off-main: stayed on feature" || bad "dirty off-main: branch changed"
grep -q "step start:" "$GDLOG" 2>/dev/null && bad "dirty off-main: a step ran" || ok "dirty off-main: no step ran"

echo
if [ "$FAILED_ASSERT" = "0" ]; then echo "ALL ASSERTIONS PASSED"; else echo "SOME ASSERTIONS FAILED"; fi
exit "$FAILED_ASSERT"
