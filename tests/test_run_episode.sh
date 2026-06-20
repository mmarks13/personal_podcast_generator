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
trap 'rm -rf "$SB"' EXIT
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

# ---- sandbox layout ----------------------------------------------------------
mkdir -p "$SB/scripts" "$SB/out" "$SB/docs/reads" "$SB/logs" "$SB/home/.local/bin"
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

# Fake claude: pick the skill out of the prompt args, emit the expected artifacts.
# MOCK_NO_MP3=1 makes the podcast run skip the MP3 (reproduces last night's failure:
# the agent "succeeds" but no audio is produced, so the publish guard must catch it).
cat > "$SB/home/.local/bin/claude" <<'SH'
#!/usr/bin/env bash
args="$*"; DATE="$(date +%F)"; mkdir -p out docs/reads
if [[ "$args" == *daily-ai-podcast* ]]; then
  echo "[fake-claude] ran daily-ai-podcast skill"
  printf '{"title":"Test Episode %s","date":"%s"}\n' "$DATE" "$DATE" > "out/episode.json"
  printf '{"summary":"test summary"}\n' > "out/episode_meta.json"
  printf 'show notes\n' > "out/shownotes.md"
  [ -n "${MOCK_NO_MP3:-}" ] || printf 'FAKE-MP3' > "out/podcast-$DATE.mp3"
elif [[ "$args" == *daily-read* ]]; then
  echo "[fake-claude] ran daily-read skill"
  printf 'FAKE-EPUB' > "docs/reads/self-attention-$DATE.epub"
elif [[ "$args" == *weekly-deep-dive* ]]; then
  echo "[fake-claude] ran weekly-deep-dive skill"
  printf '{"title":"DD %s","date":"%s"}\n' "$DATE" "$DATE" > "out/deepdive.json"
  printf '{"summary":"dd"}\n' > "out/deepdive_meta.json"
  printf 'dd notes\n' > "out/deepdive_shownotes.md"
  [ -n "${MOCK_NO_MP3:-}" ] || printf 'FAKE' > "out/deepdive-$DATE.mp3"
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
invoke() {
  set +e
  ( cd "$SB" && env -u ANTHROPIC_API_KEY HOME="$SB/home" "$@" bash run_episode.sh ) \
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
hasre "read step end exit=0"      "step end: read exit=0"
hasre "kindle step end exit=0"    "step end: kindle exit=0"
hasre "publish step end exit=0"   "step end: publish exit=0"
has   "captured fake-claude output"  "[fake-claude] ran daily-ai-podcast skill"
has   "publisher was the mock"    "MOCK publish:"
has   "kindle sender was the mock" "MOCK kindle:"
hasre "usage snapshot logged"     '\[usage\] \{'
hasre "run end status OK"         '===== RUN END .* status=OK'
no    "real claude not invoked"   "Use the daily-ai-podcast skill"  # prompt text only appears if claude echoed it
# Expected steps depend on the weekday: the deep-dive branch runs Wed (3) / Sat (6).
expA="kindle podcast publish read"
if [ "$(date +%u)" = "3" ] || [ "$(date +%u)" = "6" ]; then
  expA="deepdive kindle podcast publish publish-deepdive read"
fi
steps "$expA"
! pgrep -f "scripts/run_log.py poll" >/dev/null \
  && ok "usage poller terminated after run" || bad "usage poller still running"

# ---- Scenario B: agent 'succeeds' but produces no MP3 ------------------------
echo "Scenario B: no MP3 -> publish guard must fail the run"
reset_artifacts; : > "$LOG"
rcB="$(invoke LOG_KEEP_RUNS=3 MOCK_NO_MP3=1)"
[ "$rcB" != "0" ] && ok "non-zero exit ($rcB)" || bad "expected non-zero exit"
hasre "publish step end exit=1"   "step end: publish exit=1"
has   "MP3 guard message logged"  "no MP3 produced"
hasre "run end status FAIL[publish]" '===== RUN END .* status=FAIL failed=\[publish\]'
! pgrep -f "scripts/run_log.py poll" >/dev/null \
  && ok "usage poller terminated after failed run" || bad "usage poller still running"

# ---- Scenario C: retention trim ----------------------------------------------
echo "Scenario C: LOG_KEEP_RUNS=3 caps run.log at 3 run blocks"
reset_artifacts; : > "$LOG"
for _ in 1 2 3 4 5; do invoke LOG_KEEP_RUNS=3 >/dev/null; done
blocks="$(grep -c 'RUN START' "$LOG")"
[ "$blocks" = "3" ] && ok "exactly 3 run blocks retained (after 5 runs)" \
                     || bad "expected 3 run blocks, found $blocks"

echo
if [ "$FAILED_ASSERT" = "0" ]; then echo "ALL ASSERTIONS PASSED"; else echo "SOME ASSERTIONS FAILED"; fi
exit "$FAILED_ASSERT"
