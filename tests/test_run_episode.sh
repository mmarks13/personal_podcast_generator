#!/usr/bin/env bash
# Hermetic scheduler test: no real model, network, TTS, notification, email, or publish.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d)"
GD="$(mktemp -d)"
trap 'rm -rf "$SB" "$GD"' EXIT
LOG="$SB/logs/run.log"
FAIL=0
ok() { echo "  ok   - $1"; }
bad() { echo "  FAIL - $1"; FAIL=1; }
has() { grep -qF -- "$2" "$LOG" && ok "$1" || bad "$1"; }
no() { grep -qF -- "$2" "$LOG" && bad "$1" || ok "$1"; }

mkdir -p "$SB"/{scripts,out,logs,docs/reads,archive/scripts,.venv/bin}
# run_episode.sh archives each night's raw gather to smallbatch-lab as classifier training
# data, defaulting TRIAGE_DIR to an absolute $HOME path. That path is NOT inside the
# sandbox, so without this the suite copied its own empty stubs over the real archive for
# today's date - every run since 2026-08-01 was destroyed that way, on every push, because
# the pre-push hook runs this file. Point it somewhere disposable.
export TRIAGE_DIR="$SB/triage"
ln -sf "$(command -v python3)" "$SB/.venv/bin/python"
cp "$REPO/run_episode.sh" "$SB/run_episode.sh"
cp "$REPO/scripts/run_log.py" "$SB/scripts/run_log.py"

cat > "$SB/scripts/preflight.py" <<'PY'
import os
print("MOCK preflight provider=" + os.environ.get("AGENT_PROVIDER", "claude"))
PY
cat > "$SB/scripts/agent_runner.py" <<'PY'
import json, os, pathlib, sys
stage = sys.argv[sys.argv.index("--stage") + 1]
prompt = sys.stdin.read()
provider = os.environ.get("AGENT_PROVIDER", "claude")
print(f"MOCK agent stage={stage} provider={provider} stdin_closed={bool(prompt)}")
if os.environ.get("MOCK_FAIL_STAGE") == stage:
    raise SystemExit(9)
p = pathlib.Path
p("out").mkdir(exist_ok=True)
date = __import__("datetime").date.today().isoformat()
if stage == "crawl": p("out/crawl.json").write_text('{"items":[],"failures":[]}')
elif stage == "consolidate": p("out/candidates.json").write_text('{"items":[]}')
elif stage == "podcast":
    p("out/script.txt").write_text("A: test\nB: test\n")
    p("out/episode.json").write_text(json.dumps({"title":"Test","date":date,"turns":[]}))
    p("out/episode_meta.json").write_text('{"summary":"test"}')
    p("out/shownotes.md").write_text("notes")
elif stage == "deepdive":
    p("out/deepdive_script.txt").write_text("A: deep\nB: dive\n")
    p("out/deepdive.json").write_text(json.dumps({"title":"Dive","date":date,"turns":[]}))
    p("out/deepdive_meta.json").write_text('{"summary":"test"}')
    p("out/deepdive_shownotes.md").write_text("notes")
elif stage == "read":
    p("docs/reads").mkdir(parents=True, exist_ok=True)
    p(f"docs/reads/self-attention-{date}.epub").write_bytes(b"epub")
elif stage == "propose":
    p("out/daily_options.json").write_text('{"options":[]}')
    p("out/deepdive_options.json").write_text('{"options":[]}')
PY
cat > "$SB/scripts/fetch_sources.py" <<'PY'
import pathlib
pathlib.Path("out").mkdir(exist_ok=True)
pathlib.Path("out/sources.json").write_text('{"feeds":{}}')
print("MOCK fetch")
PY
for script in update_history.py send_to_kindle.py publish_read.py notify.py proposal_ledger.py daily_options.py ntfy_choice.py; do
  cat > "$SB/scripts/$script" <<'PY'
import pathlib, sys
pathlib.Path("out/deterministic-calls.log").open("a").write(pathlib.Path(sys.argv[0]).name + "\n")
PY
done
cat > "$SB/scripts/make_audio.py" <<'PY'
import pathlib, sys
pathlib.Path("out/deterministic-calls.log").open("a").write("make_audio.py\n")
out = sys.argv[sys.argv.index("--out") + 1]
pathlib.Path(out).write_bytes(b"mp3")
PY
cat > "$SB/scripts/publish.py" <<'PY'
import pathlib
pathlib.Path("out/deterministic-calls.log").open("a").write("publish.py\n")
PY
# The harness re-runs the episode gate independently of the writer's own in-session run.
# Stubbed here because the mock artifacts carry no turns and the real gate would (rightly)
# reject them; this asserts the wiring, not the checks. Deliberately not logged to
# deterministic-calls.log - it is a local check with no side effects, so it must not
# trip the dry-run "skipped external steps" assertions.
cat > "$SB/scripts/check_episode.py" <<'PY'
print("MOCK gate")
PY

invoke() {
  set +e
  (cd "$SB" && env RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

invoke_read() {
  set +e
  (cd "$SB" && env RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh read) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

echo "Scenario A: Claude-default full run"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log"
rc="$(invoke)"
[ "$rc" = 0 ] && ok "full run exits 0" || bad "full run exit $rc"
has "Claude default reached runner" "provider=claude"
has "podcast stage ran" "step end: podcast exit=0"
has "crawl stage ran" "step end: crawl exit=0"
has "harness re-ran the gate" "step end: gate exit=0"
has "render ran" "step end: render-podcast exit=0"
has "publish ran" "step end: publish exit=0"

echo "Scenario B: explicit Codex provider"
: > "$LOG"
rc="$(invoke_read AGENT_PROVIDER=codex)"
[ "$rc" = 0 ] && ok "Codex read exits 0" || bad "Codex read exit $rc"
has "Codex override reached runner" "provider=codex"
has "read stage ran" "step end: read exit=0"
has "Kindle stage ran" "step end: kindle exit=0"

echo "Scenario C: no-side-effect dry run"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log"
rc="$(invoke RUN_EPISODE_DRY_RUN=1)"
[ "$rc" = 0 ] && ok "dry run exits 0" || bad "dry run exit $rc"
has "dry-run suppression logged" "dry-run: skipped podcast history, archive, render, and publish"
# ntfy_choice.py is expected here and only here: reading the listener's mini-dive picks
# is a read-only poll with no side effect, so it is deliberately not dry-run-gated —
# that is what lets a dry run exercise the picker end to end.
unexpected="$(sort -u "$SB/out/deterministic-calls.log" 2>/dev/null | grep -v '^ntfy_choice\.py$' || true)"
if [ -n "$unexpected" ]; then bad "dry run called external deterministic step: $unexpected"; else ok "dry run skipped external deterministic steps"; fi

echo "Scenario C2: no-side-effect read dry run"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log"
rc="$(invoke_read RUN_EPISODE_DRY_RUN=1)"
[ "$rc" = 0 ] && ok "read dry run exits 0" || bad "read dry run exit $rc"
has "read dry-run suppression logged" "dry-run: skipped Kindle delivery and read publish"
if [ -e "$SB/out/deterministic-calls.log" ]; then bad "read dry run called delivery step"; else ok "read dry run skipped delivery steps"; fi

echo "Scenario D: overlap skips immediately"
flock "$SB/.run_episode.lock" -c "sleep 5" & lock_pid=$!
sleep 0.2
rc="$(invoke RUN_EPISODE_DRY_RUN=1)"
wait "$lock_pid"
[ "$rc" = 75 ] && ok "overlap exits 75" || bad "overlap exit $rc"

echo "Scenario E: branch guard"
mkdir -p "$GD"/{scripts,out,logs,docs/reads,archive/scripts,.venv/bin}
ln -sf "$(command -v python3)" "$GD/.venv/bin/python"
cp "$SB/run_episode.sh" "$GD/run_episode.sh"
cp "$SB/scripts/"*.py "$GD/scripts/"
printf 'out/\nlogs/\ndocs/reads/\n.run_episode.lock\nconsole.txt\n' > "$GD/.gitignore"
echo seed > "$GD/tracked.txt"
(cd "$GD" && git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm init && git branch -M main && git branch feature)
gd_run() { (cd "$GD" && "$@" bash run_episode.sh); }
(cd "$GD" && git checkout -q feature)
set +e; gd_run >"$GD/console.txt" 2>&1; rc=$?; set -e
[ "$rc" = 0 ] && [ "$(cd "$GD" && git branch --show-current)" = main ] && ok "clean feature switches to main" || bad "clean feature guard"
(cd "$GD" && git checkout -q feature && echo dirty >> tracked.txt)
set +e; output="$(gd_run 2>&1)"; rc=$?; set -e
[ "$rc" != 0 ] && [[ "$output" == *"uncommitted changes"* ]] && ok "dirty feature refuses" || bad "dirty feature guard"

echo
[ "$FAIL" = 0 ] && echo "ALL ASSERTIONS PASSED" || echo "SOME ASSERTIONS FAILED"
exit "$FAIL"
