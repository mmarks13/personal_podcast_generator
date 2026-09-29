#!/usr/bin/env bash
# Attended Codex session for this repository.
#
# The nightly path is deliberately incapable of asking for anything: agent_runner.py pins
# approval_policy="never", a credential-free environment, and a permission profile that
# denies .env, on every invocation. That is right for 2 AM and wrong for a person sitting
# at the terminal -- a session started that way can read and test this repo but cannot
# render or publish it, because there is no route to request the missing access.
#
# This launcher is that route, and only that route. It changes nothing on disk that a
# scheduled run reads: run_episode.sh never calls it, and every setting below is passed as
# a command-line override that the nightly runner re-pins anyway.
#
#   bash scripts/codex_interactive.sh                 # interactive TUI
#   bash scripts/codex_interactive.sh "render the deep dive"
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Values only ever reach the child through the environment -- never through argv, where
# `ps` would show them. The include_only list below is names, not values.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# What the attended session is allowed to see. Deliberately shorter than "everything in
# .env": the podcast render and publish path, plus the desktop-session variables `gh` needs
# to reach its keyring. The daily read's mail credentials (KINDLE_EMAIL,
# GMAIL_APP_PASSWORD) are not here; add them only when a session actually needs to send an
# issue.
INTERACTIVE_ENV='["PATH","HOME","USER","LOGNAME","SHELL","LANG","LC_*","TZ","TERM","COLORTERM","XDG_RUNTIME_DIR","DBUS_SESSION_BUS_ADDRESS","SSH_AUTH_SOCK","GEMINI_API_KEY","GEMINI_VOICE_A","GEMINI_VOICE_B","GEMINI_VOICE_C","OWNER_EMAIL","NTFY_TOPIC"]'

# Launch from .codex/runtime-bin for the same reason the nightly runner does: some
# standalone bundles ship only the multicall binary, and Codex resolves
# codex-linux-sandbox and codex-code-mode-host next to its own argv[0]. See
# ensure_codex_sandbox_helper() in scripts/agent_runner.py -- reused here rather than
# reimplemented, so the 2026-08-13 code-mode-host outage cannot come back through this path.
#
# ignore_default_excludes below must be true, which reads backwards. It widens nothing on
# its own: it switches off Codex's built-in *KEY*/*TOKEN*/*SECRET* name filter, which
# otherwise drops GEMINI_API_KEY before the include_only allowlist is ever consulted. The
# allowlist is the actual gate. Verified 2026-09-13: left at false, a probe variable named
# GEMINI_PROBE_KEY never reached the agent's shell even while explicitly listed.
RUNTIME_BIN="$(.venv/bin/python -c 'import sys; sys.path.insert(0, "scripts"); import agent_runner; print(agent_runner.ensure_codex_sandbox_helper())')"

exec "${RUNTIME_BIN}/codex" \
  --ask-for-approval on-request \
  --cd "$PWD" \
  -c 'default_permissions="podcast-interactive"' \
  -c 'web_search="live"' \
  -c 'shell_environment_policy.inherit="all"' \
  -c 'shell_environment_policy.ignore_default_excludes=true' \
  -c 'shell_environment_policy.exclude=[]' \
  -c "shell_environment_policy.include_only=${INTERACTIVE_ENV}" \
  -c "shell_environment_policy.set.PATH=\"${RUNTIME_BIN}:${PATH}\"" \
  "$@"
