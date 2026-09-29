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
cat > "$SB/archive/scripts/2026-09-12-meta.json" <<'JSON'
{"date": "2026-09-12", "sources": [{"title": "Aired before", "url": "https://blog.test/aired-story/"}]}
JSON
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
__import__("pathlib").Path("out").mkdir(exist_ok=True)
__import__("pathlib").Path(f"out/prompt-{stage}.txt").write_text(prompt)
if os.environ.get("MOCK_FAIL_STAGE") == stage:
    raise SystemExit(9)
p = pathlib.Path
p("out").mkdir(exist_ok=True)
date = __import__("datetime").date.today().isoformat()
if stage == "crawl": p("out/crawl.json").write_text('{"items":[],"failures":[]}')
elif stage == "consolidate": p("out/candidates.json").write_text(json.dumps({"items": [
    {"title": "Aired before", "url": "https://blog.test/aired-story/", "sources": ["S"]},
    {"title": "Brand new", "url": "https://blog.test/new-story/", "sources": ["S"]}]}))
elif stage == "podcast":
    p("out/script.txt").write_text("A: test\nB: test\n")
    p("out/episode.json").write_text(json.dumps({"title":"Test","date":date,"turns":[]}))
    p("out/episode_meta.json").write_text('{"summary":"test"}')
    p("out/shownotes.md").write_text("notes")
elif stage == "deepdive":
    p("out/deepdive-prompt.txt").write_text(prompt)
    p("out/deepdive_script.txt").write_text("A: deep\nB: dive\n")
    p("out/deepdive.json").write_text(json.dumps({"title":"Dive","date":date,"turns":[]}))
    p("out/deepdive_meta.json").write_text(json.dumps(
        {"summary": "test", "kind": "deepdive",
         "topics": ["deep dive: The two numbers on every model card"]}))
    p("out/deepdive_shownotes.md").write_text("notes")
elif stage == "read":
    p("docs/reads").mkdir(parents=True, exist_ok=True)
    p(f"docs/reads/self-attention-{date}.epub").write_bytes(b"epub")
elif stage == "propose":
    p("out/daily_options.json").write_text('{"options":[]}')
    p("out/deepdive_options.json").write_text('{"options":[]}')
if stage in {"crawl", "consolidate"}:
    p("out/gather-calls.log").open("a").write(stage + "\n")
PY
cat > "$SB/scripts/fetch_sources.py" <<'PY'
import pathlib
pathlib.Path("out").mkdir(exist_ok=True)
pathlib.Path("out/sources.json").write_text('{"feeds":{}}')
pathlib.Path("out/gather-calls.log").open("a").write("fetch\n")
print("MOCK fetch")
PY
cat > "$SB/scripts/score_sources.py" <<'PY'
import os, pathlib, sys
p = pathlib.Path
p("out/gather-calls.log").open("a").write("score\n")
if os.environ.get("MOCK_FAIL_SCORE"):
    raise SystemExit(8)
p("out/source_scores.json").write_text('{"status":"ok"}')
print("MOCK score")
PY
cat > "$SB/scripts/crawl_repair.py" <<'PY'
import os, pathlib, sys
command = sys.argv[1]
pathlib.Path("out/gather-calls.log").open("a").write("crawl_repair:" + command + "\n")
if command == "sanitize":
    print("MOCK crawl sanitize")
    raise SystemExit(0)
if command == "missing":
    if not os.environ.get("MOCK_CRAWL_GAP"):
        raise SystemExit(0)
    print('[{"name": "Dropped", "method": "fetch", "url": "https://dropped.test/news", "tier": 1}]')
    raise SystemExit(3)
rejections = pathlib.Path("out/crawl_repair_rejections.txt")
rejections.unlink(missing_ok=True)
if os.environ.get("MOCK_MERGE_REJECT"):
    seen = pathlib.Path("out/merge-attempts")
    count = int(seen.read_text()) + 1 if seen.exists() else 1
    seen.write_text(str(count))
    if count == 1:
        rejections.write_text(
            "Dropped <https://dropped.test/news>: status 'no_items_in_window' is not one "
            "of the three allowed literal strings\n")
        print("MOCK crawl repair merge rejected")
        raise SystemExit(3)
print("MOCK crawl repair merge")
PY
cp "$REPO/scripts/stamp_candidates.py" "$SB/scripts/stamp_candidates.py"
cp "$REPO/scripts/note_band.py" "$SB/scripts/note_band.py"
cp "$REPO/scripts/daily_ledger.py" "$SB/scripts/_daily_ledger_real.py"
cat > "$SB/scripts/gather_manifest.py" <<'PY'
import json, pathlib, sys
p = pathlib.Path
command = sys.argv[1]
manifest = p("out/gather_manifest.json")
required = [p("out/sources.json"), p("out/crawl.json"), p("out/candidates.json")]
if command == "create":
    if not all(path.exists() for path in required): raise SystemExit(1)
    manifest.write_text(json.dumps({"status":"valid","gather_id":"sha256:test-gather"}))
    p("out/gather-calls.log").open("a").write("manifest\n")
elif not manifest.exists() or json.loads(manifest.read_text()).get("status") != "valid":
    raise SystemExit(1)
print("sha256:test-gather")
PY
cat > "$SB/scripts/seen_index.py" <<'PY'
import pathlib
pathlib.Path("out/gather-calls.log").open("a").write("seen-index\n")
print("MOCK seen index")
PY
cat > "$SB/scripts/crawl_freshness.py" <<'PY'
import json, pathlib
p = pathlib.Path("out/crawl.json")
value = json.loads(p.read_text())
value["proposal_freshness"] = {"status":"valid"}
p.write_text(json.dumps(value))
pathlib.Path("out/gather-calls.log").open("a").write("freshness\n")
print("MOCK crawl freshness")
PY
cat > "$SB/scripts/proposal_context.py" <<'PY'
print('{"recent_episodes_newest_first":[],"recent_rundown_sources_newest_first":[]}')
PY
for script in update_history.py send_to_kindle.py publish_read.py notify.py proposal_ledger.py daily_options.py ntfy_choice.py; do
  cat > "$SB/scripts/$script" <<'PY'
import pathlib, sys
pathlib.Path("out/deterministic-calls.log").open("a").write(pathlib.Path(sys.argv[0]).name + "\n")
PY
done
cat > "$SB/scripts/proposal_ledger.py" <<'PY'
import pathlib, sys
pathlib.Path("out/deterministic-calls.log").open("a").write("proposal_ledger.py\n")
pathlib.Path("out/ledger-calls.log").open("a").write(" ".join(sys.argv[1:]) + "\n")
PY
cat > "$SB/scripts/ntfy_choice.py" <<'PY'
import os, pathlib, sys
pathlib.Path("out/deterministic-calls.log").open("a").write("ntfy_choice.py\n")
# The real script writes the deep-dive note beside stdout, which carries the topic.
note = os.environ.get("MOCK_DIVE_NOTE")
if note and "deepdive" in sys.argv:
    pathlib.Path("out/deepdive_note.txt").write_text(note + "\n")
daily = os.environ.get("MOCK_DAILY_NOTE")
if daily and "daily" in sys.argv:
    import json
    pathlib.Path("out/daily_picks.json").write_text(
        json.dumps({"picks": [], "free_text": None, "note": daily}))
    print("note: " + daily)
PY
cat > "$SB/scripts/daily_ledger.py" <<'PY'
import os, pathlib, sys
# Real: stamp_candidates imports it, and URL matching is what it is being tested on.
from _daily_ledger_real import canonical_url  # noqa: F401
if __name__ == "__main__":
    mode = sys.argv[1]
    pathlib.Path("out/deterministic-calls.log").open("a").write("daily_ledger.py:" + mode + "\n")
    if mode == "filter" and os.environ.get("MOCK_FAIL_DAILY_GATE"):
        raise SystemExit(9)
PY
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
import pathlib, sys
pathlib.Path("out/gate-calls.log").open("a").write(" ".join(sys.argv[1:]) + "\n")
print("MOCK gate")
PY

invoke() {
  set +e
  (cd "$SB" && env -u AGENT_PROVIDER -u AGENT_EFFORT_OVERRIDE \
    RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

invoke_read() {
  set +e
  (cd "$SB" && env -u AGENT_PROVIDER -u AGENT_EFFORT_OVERRIDE \
    RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh read) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

invoke_propose() {
  set +e
  (cd "$SB" && env -u AGENT_PROVIDER -u AGENT_EFFORT_OVERRIDE \
    RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh propose) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

invoke_deepdive() {
  set +e
  (cd "$SB" && env -u AGENT_PROVIDER -u AGENT_EFFORT_OVERRIDE \
    RUN_EPISODE_ALLOW_ANY_BRANCH=1 "$@" bash run_episode.sh deepdive) >"$SB/console.txt" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

echo "Scenario A: Claude-default full run"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke)"
[ "$rc" = 0 ] && ok "full run exits 0" || bad "full run exit $rc"
has "Claude default reached runner" "provider=claude"
has "podcast stage ran" "step end: podcast exit=0"
has "crawl stage ran" "step end: crawl exit=0"
has "harness re-ran the gate" "step end: gate exit=0"
has "render ran" "step end: render-podcast exit=0"
has "publish ran" "step end: publish exit=0"
has "missing evening manifest uses recovery" "gather: evening manifest missing or invalid; starting recovery"

echo "Scenario A1: successful evening gather is reused without 02:00 gathering calls"
: > "$LOG"; rm -f "$SB/out/gather-calls.log" "$SB/out/gather_manifest.json"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1)"
[ "$rc" = 0 ] && ok "propose run exits 0" || bad "propose run exit $rc"
for stage in fetch crawl freshness seen-index score consolidate manifest; do
  grep -q "^$stage$" "$SB/out/gather-calls.log" && ok "evening ran $stage" || bad "evening missed $stage"
done

has "evening stamped the candidates" "step end: stamp-candidates exit=0"
python3 - "$SB/out/candidates.json" <<'PY' && ok "only the already-aired candidate is flagged" \
  || bad "aired_on stamp is wrong"
import json, sys
items = json.load(open(sys.argv[1]))["items"]
flagged = {i["title"]: i.get("aired_on") for i in items}
assert flagged == {"Aired before": ["2026-09-12"], "Brand new": None}, flagged
PY

echo "Scenario A1a: resume after crawl skips fetch and crawl"
: > "$LOG"; : > "$SB/out/gather-calls.log"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1 GATHER_RESUME_AFTER_CRAWL=1)"
[ "$rc" = 0 ] && ok "resumed propose exits 0" || bad "resumed propose exit $rc"
has "resume is logged" "gather: resuming evening gather after crawl"
for stage in freshness seen-index score consolidate manifest; do
  grep -q "^$stage$" "$SB/out/gather-calls.log" && ok "resume ran $stage" || bad "resume missed $stage"
done
for stage in fetch crawl; do
  if grep -q "^$stage$" "$SB/out/gather-calls.log"; then bad "resume reran $stage"; else ok "resume skipped $stage"; fi
done

: > "$LOG"; : > "$SB/out/gather-calls.log"
rc="$(invoke RUN_EPISODE_DRY_RUN=1)"
[ "$rc" = 0 ] && ok "reuse full run exits 0" || bad "reuse full run exit $rc"
has "full run reused evening identity" "gather: reusing fresh evening sha256:test-gather"
if [ -s "$SB/out/gather-calls.log" ]; then bad "reuse made gather calls"; else ok "reuse made no gather calls"; fi

echo "Scenario A1b: proposal without a valid manifest fails visibly"
: > "$LOG"; rm -f "$SB/out/gather-calls.log" "$SB/out/gather_manifest.json"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1 MOCK_FAIL_STAGE=consolidate)"
[ "$rc" != 0 ] && ok "invalid proposal gather exits nonzero" || bad "invalid proposal gather exit $rc"
has "proposal skip is logged" "no valid evening gather; skipped proposal drafting and notification"
has "invalid proposal gather is failed" "status=FAIL"

echo "Scenario A1b2: novelty gate failure blocks ntfy but preserves the gather"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke_propose MOCK_FAIL_DAILY_GATE=1)"
[ "$rc" != 0 ] && ok "failed novelty gate exits nonzero" || bad "failed novelty gate exit $rc"
has "novelty failure is explicit" "daily novelty gate failed closed"
if grep -qE '\[run\] step start: notify$' "$LOG"; then
  bad "failed novelty gate sent the options push"
else
  ok "failed novelty gate skipped the options push"
fi
[ -s "$SB/out/gather_manifest.json" ] \
  && ok "failed novelty gate preserved gather manifest" || bad "failed novelty gate lost gather manifest"

echo "Scenario A1c: resume after consolidate rebuilds only the manifest"
# A1b's failed consolidate left no candidates, so restore a complete gather first.
: > "$LOG"; rm -f "$SB/out/gather_manifest.json"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1)"
[ "$rc" = 0 ] && ok "gather restored before resume" || bad "gather restore exit $rc"
: > "$LOG"; : > "$SB/out/gather-calls.log"; rm -f "$SB/out/gather_manifest.json"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1 GATHER_RESUME_AFTER_CONSOLIDATE=1)"
[ "$rc" = 0 ] && ok "manifest-only resume exits 0" || bad "manifest-only resume exit $rc"
has "manifest-only resume is logged" "gather: reusing evening gather artifacts; rebuilding manifest only"
grep -q "^manifest$" "$SB/out/gather-calls.log" \
  && ok "manifest-only resume rebuilt the manifest" || bad "manifest-only resume missed manifest"
for stage in fetch crawl seen-index score consolidate; do
  if grep -q "^$stage$" "$SB/out/gather-calls.log"; then
    bad "manifest-only resume reran $stage"
  else ok "manifest-only resume skipped $stage"; fi
done

: > "$LOG"; rm -f "$SB/out/candidates.json" "$SB/out/gather_manifest.json"
rc="$(invoke_propose RUN_EPISODE_DRY_RUN=1 GATHER_RESUME_AFTER_CONSOLIDATE=1)"
[ "$rc" != 0 ] && ok "resume without a gather exits nonzero" || bad "resume without a gather exit $rc"
has "missing artifact is logged" "cannot resume after consolidate without out/candidates.json"

echo "Scenario A2: failed optional crawl degrades but does not fail publish"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke MOCK_FAIL_STAGE=crawl)"
[ "$rc" = 0 ] && ok "degraded run exits 0" || bad "degraded run exit $rc"
has "crawl failure logged" "step end: crawl exit=9"
has "podcast still published" "step end: publish exit=0"
has "run reports degraded gathering" "status=OK degraded=[crawl"
no "run is not reported failed" "status=FAIL"


echo "Scenario A2a: a crawl that drops a configured source triggers the repair pass"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke MOCK_CRAWL_GAP=1)"
[ "$rc" = 0 ] && ok "repaired run exits 0" || bad "repaired run exit $rc"
has "coverage gap is logged" "configured sources left unanswered by crawl.json; running repair pass"
has "repair stage ran" "MOCK agent stage=crawl_repair"
has "repair merge ran" "step end: crawl-merge exit=0"
grep -q "crawl_repair:sanitize" "$SB/out/gather-calls.log" \
  && ok "the crawl JSON is sanitized" || bad "no sanitize pass"
[ "$(grep -c 'crawl_repair:' "$SB/out/gather-calls.log")" -ge 2 ] \
  && [ "$(grep -n 'crawl_repair:' "$SB/out/gather-calls.log" | head -1)" = "$(grep -n 'crawl_repair:sanitize' "$SB/out/gather-calls.log" | head -1)" ] \
  && ok "sanitize runs before the coverage check" || bad "sanitize does not run first"
grep -qF "crawl_repair:merge" "$SB/out/gather-calls.log" \
  && ok "merge folded the repair into the crawl" || bad "merge did not run"
has "repaired run still publishes" "step end: publish exit=0"

echo "Scenario A2b: a complete crawl skips the repair pass"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke)"
[ "$rc" = 0 ] && ok "complete-coverage run exits 0" || bad "complete-coverage run exit $rc"
no "no repair stage" "MOCK agent stage=crawl_repair"

echo "Scenario A2c: a repair that breaks the crawl contract is handed its rejections once"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json" "$SB/out/merge-attempts" "$SB/out/prompt-crawl_repair.txt"
rc="$(invoke MOCK_CRAWL_GAP=1 MOCK_MERGE_REJECT=1)"
[ "$rc" = 0 ] && ok "retried run exits 0" || bad "retried run exit $rc"
has "contract violation is logged" "repair pass broke the crawl contract; retrying once"
has "retry stage ran" "step end: crawl-repair-retry exit=0"
has "retry merge succeeded" "step end: crawl-merge-retry exit=0"
grep -qF "no_items_in_window" "$SB/out/prompt-crawl_repair.txt" \
  && ok "the rejection reached the repair agent" || bad "retry prompt lacks the rejection"
grep -qF "ok, no_recent_items, or failed" "$SB/out/prompt-crawl_repair.txt" \
  && ok "the status vocabulary is spelled out in the prompt" || bad "prompt omits the vocabulary"
has "retried run still publishes" "step end: publish exit=0"

echo "Scenario A3: failed Smallbatch scoring is visible but non-destructive"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json"
rc="$(invoke MOCK_FAIL_SCORE=1)"
[ "$rc" = 0 ] && ok "score-degraded run exits 0" || bad "score-degraded run exit $rc"
has "score failure logged" "step end: score exit=8"
has "score failure keeps podcast path" "step end: podcast exit=0"
has "score failure keeps publish path" "step end: publish exit=0"
has "score failure is degraded" "status=OK degraded=[score]"

echo "Scenario A4: a note's requested length becomes the band the writer and gate both use"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json" "$SB/out/gate-calls.log" "$SB/out/prompt-podcast.txt"
rc="$(invoke MOCK_DAILY_NOTE='Lead with the IPO. Keep it to 20 minutes.')"
[ "$rc" = 0 ] && ok "note-with-length run exits 0" || bad "note-with-length run exit $rc"
# 20 min at 165 wpm is 3300 words, +/-12%.
has "the band is logged" "the note set tonight's band to 2904-3696 words"
grep -qF 'word band is 2904-3696 words' "$SB/out/prompt-podcast.txt" \
  && ok "the band reaches the writer" || bad "band missing from the writer prompt"
grep -qF 'OUTRANKS the skill' "$SB/out/prompt-podcast.txt" \
  && ok "the note's precedence is stated to the writer" || bad "precedence missing from the prompt"
grep -qF -- '--min-words 2904 --max-words 3696' "$SB/out/gate-calls.log" \
  && ok "the same band reaches the gate" || bad "gate band wrong: $(cat "$SB/out/gate-calls.log" 2>&1)"
python3 -c "
import json,sys
m=json.load(open('$SB/out/episode_meta.json'))
sys.exit(0 if m.get('listener_note','').startswith('Lead with the IPO')
         and m.get('word_band')==[2904,3696] else 1)" \
  && ok "the note and band are recorded on the episode" \
  || bad "meta not stamped: $(cat "$SB/out/episode_meta.json" 2>&1)"

echo "Scenario A4a: a note with no length leaves the band alone"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log" \
  "$SB/out/gather_manifest.json" "$SB/out/gate-calls.log"
rc="$(invoke MOCK_DAILY_NOTE='Open cold and stay skeptical about the loss figure.')"
[ "$rc" = 0 ] && ok "prose-only note run exits 0" || bad "prose-only note run exit $rc"
no "no band was set" "set tonight's band"
if grep -q -- "--min-words" "$SB/out/gate-calls.log"; then
  bad "prose moved the band"; else ok "the gate keeps its default band"; fi

echo "Scenario B: explicit Codex provider"
: > "$LOG"
rc="$(invoke_read AGENT_PROVIDER=codex)"
[ "$rc" = 0 ] && ok "Codex read exits 0" || bad "Codex read exit $rc"
has "Codex override reached runner" "provider=codex"
has "read stage ran" "step end: read exit=0"
has "Kindle stage ran" "step end: kindle exit=0"

echo "Scenario B2: failed read suppresses downstream delivery"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log"
rc="$(invoke_read MOCK_FAIL_STAGE=read)"
[ "$rc" = 0 ] && ok "failed read is reported through run log" || bad "failed read exit $rc"
has "read failure logged" "daily read failed; skipped Kindle delivery and publishing"
no "Kindle stage skipped" "step start: kindle"
no "read publish skipped" "step start: publish-read"

echo "Scenario B3: deep-dive-only recovery skips the daily pipeline"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/gather-calls.log"
rc="$(invoke_deepdive DEEPDIVE_TOPIC='State as context')"
[ "$rc" = 0 ] && ok "deep-dive recovery exits 0" || bad "deep-dive recovery exit $rc"
has "recovery topic reaches writer" "deepdive: listener pre-chose topic: State as context"
grep -qF "Preserve every distinct subject and qualifier" "$SB/out/deepdive-prompt.txt" \
  && ok "custom deep-dive intent is preserved" || bad "custom deep-dive intent is preserved"
grep -qF "State as context" "$SB/out/deepdive-prompt.txt" \
  && ok "custom deep-dive wording reaches writer" || bad "custom deep-dive wording reaches writer"
has "deep-dive stage ran" "step end: deepdive exit=0"
has "deep-dive gate ran" "step end: gate-deepdive exit=0"
has "deep-dive render ran" "step end: render-deepdive exit=0"
has "deep-dive publish ran" "step end: publish-deepdive exit=0"
no "daily writer skipped" "step start: podcast"
no "daily render skipped" "step start: render-podcast"
if grep -qE '\[run\] step start: publish$' "$LOG"; then bad "daily publish skipped"; else ok "daily publish skipped"; fi
no "gather skipped" "step start: fetch"

echo "Scenario B4: a writer-chosen deep dive is archived and recorded in the ledger"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/ledger-calls.log" \
  "$SB/archive/scripts/$(date +%F)-deepdive-meta.json"
rc="$(invoke_deepdive)"
[ "$rc" = 0 ] && ok "writer-chosen deep dive exits 0" || bad "writer-chosen deep dive exit $rc"
no "no listener topic was claimed" "deepdive: listener pre-chose topic"
[ -s "$SB/archive/scripts/$(date +%F)-deepdive-meta.json" ] \
  && ok "deep-dive meta reached the archive" || bad "deep-dive meta was not archived"
has "ledger records the aired topic" "deepdive: recorded writer-chosen topic in the ledger: The two numbers on every model card"
grep -qF 'choose --topic The two numbers on every model card' "$SB/out/ledger-calls.log" \
  && ok "ledger was called with the aired topic, prefix stripped" \
  || bad "ledger call wrong: $(cat "$SB/out/ledger-calls.log" 2>&1)"

echo "Scenario B5: an editorial note steers a deep dive whose topic the writer still picks"
: > "$LOG"; rm -f "$SB/out/deterministic-calls.log" "$SB/out/deepdive-prompt.txt" \
  "$SB/out/deepdive_note.txt"
rm -f "$SB/out/gate-calls.log"
rc="$(invoke_deepdive MOCK_DIVE_NOTE='Go slower than usual. Run 30 minutes.')"
[ "$rc" = 0 ] && ok "note-only deep dive exits 0" || bad "note-only deep dive exit $rc"
has "the note is logged" "deepdive: listener editorial note: Go slower than usual"
no "no topic was claimed" "deepdive: listener pre-chose topic"
grep -qF 'Go slower than usual. Run 30 minutes.' "$SB/out/deepdive-prompt.txt" \
  && ok "the note reaches the deep-dive writer" || bad "note missing from the deep-dive prompt"
# 30 min at 165 wpm is 4950 words, +/-12% - above the usual 4000 deep-dive cap.
has "the deep-dive band is logged" "the note set the band to 4356-5544 words"
grep -qF -- '--min-words 4356 --max-words 5544' "$SB/out/gate-calls.log" \
  && ok "the deep-dive gate uses the note's band" \
  || bad "deepdive gate band wrong: $(cat "$SB/out/gate-calls.log" 2>&1)"

# A note is direction for one episode. The run above left one on disk, so this run proves
# it is cleared rather than silently inherited.
: > "$LOG"; rm -f "$SB/out/deepdive-prompt.txt" "$SB/out/gate-calls.log"
rc="$(invoke_deepdive)"
[ "$rc" = 0 ] && ok "the next deep dive exits 0" || bad "the next deep dive exit $rc"
if grep -qF 'Go slower than usual' "$SB/out/deepdive-prompt.txt"; then
  bad "last episode's note steered this one"
else ok "a stale note does not steer the next episode"; fi
grep -qF -- '--min-words 3000 --max-words 4000' "$SB/out/gate-calls.log" \
  && ok "the deep-dive band falls back to the default" \
  || bad "default band missing: $(cat "$SB/out/gate-calls.log" 2>&1)"

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
