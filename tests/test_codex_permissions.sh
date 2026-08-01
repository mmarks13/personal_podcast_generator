#!/usr/bin/env bash
# Run against the installed Codex sandbox; makes no model request.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TD="$(mktemp -d "$ROOT/out/permission-test.XXXXXX")"
OUTSIDE="$(mktemp /tmp/codex-permission-outside.XXXXXX)"
trap 'rm -rf "$TD"; rm -f "$OUTSIDE"' EXIT
echo secret > "$TD/secret.env"
python3 "$ROOT/scripts/preflight.py" --mode read >/dev/null
export PATH="$ROOT/.codex/runtime-bin:$PATH"
fail=0
ok() { echo "  ok   - $1"; }
bad() { echo "  FAIL - $1"; fail=1; }
run_profile() { codex sandbox -C "$ROOT" -P podcast-automation "$@" >/dev/null 2>&1; }
run_dry() { codex sandbox -C "$ROOT" -P podcast-dry-run "$@" >/dev/null 2>&1; }

run_profile bash -c "echo ok > '$TD/written.txt'" && ok "workspace write allowed" || bad "workspace write denied"
run_profile cat "$TD/secret.env" && bad ".env read allowed" || ok ".env read denied"
run_profile touch "$ROOT/.codex/permission-test" && bad ".codex write allowed" || ok ".codex write denied"
run_profile cat "$OUTSIDE" && bad "outside-workspace read allowed" || ok "outside-workspace read denied"
run_profile python3 -c 'import socket; socket.create_connection(("1.1.1.1", 53), 2)' \
  && bad "shell network allowed" || ok "shell network denied"
run_dry bash -c "echo ok > '$TD/dry-written.txt'" && ok "dry-run out write allowed" || bad "dry-run out write denied"
run_dry touch "$ROOT/README.md" && bad "dry-run tracked write allowed" || ok "dry-run tracked write denied"

exit "$fail"
