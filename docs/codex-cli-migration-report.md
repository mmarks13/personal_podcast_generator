# Repository-specific Claude CLI to Codex CLI migration report

Tested on 2026-08-01 with Codex CLI 0.146.0 and Claude Code 2.1.220.

## Outcome

`config/agents.yaml` makes Codex the default provider. `AGENT_PROVIDER=claude`
selects Claude explicitly. Each stage is dispatched through
`scripts/agent_runner.py`, which provides one unattended execution, trace, retry,
quota, output-transaction, and fallback contract for both CLIs.

The scheduled process never has a TTY and closes provider stdin after the prompt.
Codex runs with `approval_policy="never"`; Claude runs with `--permission-mode
dontAsk`, `--tools`, and `--allowedTools`. A prompt cannot wait for a person.

## Feature inventory and parity

| Feature used before migration | Codex port | Parity and risk |
|---|---|---|
| `claude -p` headless sessions | `codex exec - --json --ephemeral` | Equivalent noninteractive entrypoint. Both receive closed stdin. |
| `acceptEdits` plus broad allowed tools | `approval_policy="never"` plus `podcast-automation` permission profile | Semantic substitute, not exact parity. Claude has named tool availability/allowlists; Codex relies on sandbox, web mode, and environment boundaries. |
| `--allowedTools` | Per-stage Codex web mode and one hardened filesystem/network profile | No exact Codex per-stage built-in-tool allowlist. This is the largest permissions gap. |
| `--max-turns` | 30-minute no-output watchdog | Codex has no documented maximum-turn equivalent. There is intentionally no total wall-clock limit. |
| `WebSearch`/`WebFetch` | Codex native live web search for research stages | Shell network remains disabled. Web content remains untrusted and prompt-injection-prone. |
| Explicit Claude model and effort | Explicit Codex model and effort in YAML and command overrides | Codex effort is deliberately two supported levels higher than the corresponding Claude stage. This increases latency and quota use. |
| `CLAUDE.md` | Canonical `AGENTS.md`; `CLAUDE.md` contains only `@AGENTS.md` | Official interoperability pattern. |
| `.claude/skills` | Canonical `.agents/skills`; relative symlinks under `.claude/skills` | Both CLIs load the same skill bytes on Linux. Windows requires Git symlink support. |
| `.claude/agents/*.md` | Shared role skill plus thin Claude Markdown and Codex TOML adapters | Behavioral contract is shared. Provider-specific model/tool metadata remains native. Codex children inherit parent approval/sandbox. |
| Claude stream output | Normalized provider JSONL traces | Aggregate stage usage/actions are portable. Private per-turn/subagent internals are intentionally not parsed. |
| Private Claude OAuth usage poll | Removed | It read a credential file and an undocumented endpoint. Codex quota uses documented app-server account methods; Claude usage is limited to supported CLI trace fields. |
| Manual retry after partial output | Transactional per-stage output restore | Declared artifacts are restored before retry or fallback. Unknown, content, validation, sandbox, and config failures never cross providers. |

Official references: [Claude CLI](https://code.claude.com/docs/en/cli-usage),
[Claude permissions](https://code.claude.com/docs/en/permission-modes),
[Claude memory and AGENTS import](https://code.claude.com/docs/en/memory),
[Claude skills](https://code.claude.com/docs/en/slash-commands),
[Claude subagents](https://code.claude.com/docs/en/sub-agents),
[Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Codex permissions](https://learn.chatgpt.com/docs/permissions),
[Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Codex skills](https://learn.chatgpt.com/docs/build-skills), and
[Codex GitHub Action](https://learn.chatgpt.com/docs/github-action).

## Locked model and effort mapping

The ordered effort uplift is `low → high`, `medium → xhigh`, `high → max`.

| Stage or role | Codex | Effort | Claude | Effort |
|---|---|---:|---|---:|
| Podcast, read, deep dive | `gpt-5.6-sol` | `xhigh` | Opus | `medium` |
| Proposals | `gpt-5.6-terra` | `high` | Sonnet | `low` |
| Source consolidation | `gpt-5.6-terra` | `high` | Sonnet | `low` |
| Source crawling | `gpt-5.6-luna` | `max` | Haiku | `high` |
| Fact/link checking | `gpt-5.6-luna` | `xhigh` | Haiku | `medium` |

## Unattended safety decisions

- The custom Codex profile permits workspace writes, keeps protected Codex/Git
  configuration read-only, denies `.env`, denies shell network, and filters secret-like
  variables from model-spawned commands. Native web search is enabled only for web stages.
- The deterministic outer harness retains delivery/fetch/TTS secrets. All model API-key
  variables are unset. A positive paid Codex credit balance fails preflight.
- Only earned, no-cost Codex reset credits may be consumed. One idempotent reset is
  attempted after a quota failure.
- Cross-provider fallback is limited to authentication, exhausted quota, and upstream
  service startup. Sandbox, configuration, validation, artifact, content, and unknown
  failures stop and notify.
- A no-output timeout retries once. A whole-run `flock` makes overlaps skip with exit 75
  and a high-priority notification.
- `RUN_EPISODE_DRY_RUN=1` preserves generated model artifacts but suppresses Git changes,
  publication, TTS, Kindle, ntfy, history, archive, proposal-ledger, and sibling-repo writes.
  Codex additionally switches to `podcast-dry-run`, which makes the repository read-only
  except for `out/`, `logs/`, and generated `docs/reads/` artifacts. Read-mode dry runs
  stop before `reads_history.json` and validate only the generated EPUB.
- CLI versions are logged but not gated or auto-updated. Strict configuration failures
  stop instead of falling back.
- Standalone Codex packages that omit the `codex-linux-sandbox` filename are handled by
  creating same-inode `codex` and `codex-linux-sandbox` hard links under protected,
  ignored `.codex/runtime-bin/`. Launching the workspace-local main link also works
  around the upstream [Linux standalone arg0/bubblewrap bug](https://github.com/openai/codex/issues/24341).
  The directory optionally exposes the bundled `rg` the same way. Preflight's opt-in
  `--exec-probe` proves an actual low-effort `codex exec` shell call, not only the lower-level
  profile helper; it does not download or update Codex.
- The protected runtime directory is pinned into the restricted model-shell `PATH`.
  A provider exit code of zero is insufficient: every declared stage artifact must exist
  and be freshly written, preventing a polite blocked response or stale file from passing.

## Operations and rollback

Run the checked-in default:

```bash
bash run_episode.sh
```

Select Claude for one run:

```bash
AGENT_PROVIDER=claude bash run_episode.sh
```

Run a no-side-effect Codex acceptance pass:

```bash
RUN_EPISODE_DRY_RUN=1 AGENT_PROVIDER=codex bash run_episode.sh
```

For inexpensive functional testing, override every stage without changing production:

```bash
RUN_EPISODE_DRY_RUN=1 AGENT_PROVIDER=codex AGENT_EFFORT_OVERRIDE=low bash run_episode.sh
```

Inspect the newest aggregate trace:

```bash
python3 .agents/skills/analyze-turns/analyze_turns.py latest
```

Immediate operational rollback does not require a code revert: set
`AGENT_PROVIDER=claude` in the scheduler environment. A code rollback can revert the
migration branch after any useful ignored traces have been copied elsewhere.

## Validation status

Hermetic tests cover the Codex default, explicit Claude selection, closed prompt input,
effort mapping, zero-prompt flags, failure classification, paid-credit rejection,
transactional restoration, dry-run side-effect suppression, locking, and branch guard.
The historical shadow and live Codex dry-run gates are recorded separately when run;
they are acceptance evidence, not unit tests.
