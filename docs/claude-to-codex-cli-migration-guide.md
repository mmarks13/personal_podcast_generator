# Migrating an unattended Claude CLI process to Codex CLI

This guide is repository-agnostic. It captures a repeatable migration process for a
Claude Code automation that must continue to run without a person.

## 1. Discover the real workflow

Inventory behavior before translating syntax:

- Every `claude` invocation, prompt source, model, effort, output format, turn cap,
  session/resume behavior, and exit-code assumption.
- `CLAUDE.md`, imported files, nested instruction files, `.claude/skills`, commands,
  agents, hooks, MCP servers, and settings at project and user scope.
- `--tools`, `--allowedTools`, permission mode, sandbox, network, environment, and
  every secret visible to the parent or a model-spawned command.
- Scheduler/CI behavior: TTY and stdin, overlapping runs, timeouts, retries,
  notifications, branch switching, Git writes, and partial output cleanup.
- Authentication and billing source: Claude subscription, Anthropic API key, ChatGPT
  subscription, OpenAI API key, cloud action, or a mixture.
- Output contracts and deterministic gates. Treat these as the compatibility target;
  prose resemblance alone is not acceptance.

Search the repository and scheduler definitions, then observe at least one real trace.
User-level settings matter because a CLI command may inherit options that the repo does
not show.

## 2. Classify feature parity

| Claude Code surface | Codex CLI surface | Classification |
|---|---|---|
| `claude -p PROMPT` | `codex exec -` | Exact intent; pass prompt on stdin and close it. |
| Stream JSON | `codex exec --json` | Aggregate structured equivalent; event schemas differ. |
| `acceptEdits` / Auto | `approval_policy="never"` plus sandbox/profile | Semantic substitute. `never` rejects escalation; it does not grant access. |
| `--tools` / `--allowedTools` | Sandbox, permission profile, native web mode, MCP config | No exact per-run built-in-tool allowlist. Design a harder resource boundary. |
| `--max-turns` | External idle/total watchdog | Unsupported directly. Decide idle and wall-clock policies separately. |
| `CLAUDE.md` | `AGENTS.md` | Use `AGENTS.md` canonically and make `CLAUDE.md` contain `@AGENTS.md`. |
| `.claude/skills` | `.agents/skills` | Use `.agents/skills` canonically; symlink Claude paths when the host supports symlinks. |
| `.claude/agents/*.md` | `.codex/agents/*.toml` | Keep shared behavior in a skill and thin native adapters for metadata. |
| Claude OAuth/private transcripts | Supported Codex JSONL and account methods | Do not build production telemetry on private credential or rollout formats. |

Record each item as exact, semantic substitute, unsupported, or unused. For every item
that is not exact, record the operational mitigation and residual risk.

## 3. Lock the design decisions

Decide these before editing:

1. Default provider and override mechanism.
2. Stage-by-stage model and effort mapping, including deliberate quality/latency changes.
3. Approval policy and what a denied action does in a closed-stdin run.
4. Filesystem, outside-workspace, protected-path, network, and environment boundaries.
5. Which stages get native web search; keep shell network separate.
6. Subscription versus API authentication and explicit paid-overflow policy.
7. Idle timeout, total wall-clock timeout, retry count, and overlap behavior.
8. Exact fallback categories. Availability fallback should not hide configuration,
   security, validation, or content defects.
9. Transaction boundaries and which output paths must be restored after failure.
10. Trace schema, retention, redaction, and what precision is honestly supported.
11. Dry-run side effects and acceptance gates.
12. Rollback method and whether both CLIs remain supported.

Put these decisions in checked-in configuration rather than distributing them across
shell flags and prompts.

## 4. Use shared instructions and skills

Canonical instruction layout:

```text
AGENTS.md          # shared repository guidance
CLAUDE.md          # exactly: @AGENTS.md
```

Canonical skill layout on a symlink-capable host:

```text
.agents/skills/example/SKILL.md
.claude/skills/example -> ../../.agents/skills/example
```

Keep provider names and tool API names out of shared workflows when possible. Say
“search the web,” “fetch the primary page,” or “spawn the fact-checker custom agent.”
Provider-specific model, tool, and permission metadata belongs in adapters:

```text
.agents/skills/fact-checker/SKILL.md  # behavior and output contract
.claude/agents/fact-checker.md        # Claude tools/model/effort + preload
.codex/agents/fact-checker.toml       # Codex model/effort + shared-skill instruction
```

Codex child agents inherit the parent sandbox and approval selection. Do not assume an
agent file can widen permissions during a noninteractive parent run.

## 5. Build one provider-neutral runner

The outer deterministic runner should own:

```text
stage + prompt
  -> validate checked-in config and auth
  -> snapshot declared outputs
  -> launch provider with no TTY and closed stdin
  -> persist raw supported trace
  -> enforce no-output timeout
  -> classify failure
  -> restore outputs before retry/fallback
  -> normalize usage/actions/duration/provider/model/effort
```

Pin security-critical values at dispatch: provider, model, effort, approval policy,
permission profile/sandbox, and web-search mode. Use strict config parsing. Ignore
mutable exec-policy rules if the sandbox/profile is the intended hard boundary.

For Claude fallback, use `--permission-mode dontAsk` so missing permission is denied,
and use both `--tools` and `--allowedTools`: one restricts availability and the other
preapproves the same bounded set. For Codex, use `approval_policy="never"`; never use
the dangerous sandbox bypass merely to make automation stop prompting.

Normalize only supported fields. A useful schema is:

```json
{
  "provider": "codex",
  "stage": "podcast",
  "model": "gpt-5.6-sol",
  "effort": "xhigh",
  "duration_seconds": 123,
  "exit_code": 0,
  "failure_category": null,
  "event_counts": {},
  "actions": [],
  "usage": {}
}
```

Do not claim portable per-turn or per-subagent token detail when one provider exposes
only aggregate stage usage.

## 6. Harden unattended permissions

A starting Codex permission profile is:

```toml
approval_policy = "never"
default_permissions = "automation"
web_search = "disabled"
allow_login_shell = false

[permissions.automation]

[permissions.automation.filesystem]
glob_scan_max_depth = 4
":minimal" = "read"
":tmpdir" = "deny"
":slash_tmp" = "deny"

[permissions.automation.filesystem.":workspace_roots"]
"." = "write"
".env" = "deny"
"**/*.env" = "deny"
".git" = "read"
".agents" = "read"
".codex" = "read"

[permissions.automation.network]
enabled = false

[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false
include_only = ["PATH", "HOME", "LANG", "LC_*", "TZ", "TERM"]
exclude = ["*KEY*", "*SECRET*", "*TOKEN*"]
```

The outer harness may need secrets for deterministic delivery or publishing; the model's
shell does not. Keep those two environments distinct. Enable native live web search only
for research stages without enabling subprocess network.

Treat instructions from fetched pages, issues, feeds, and comments as untrusted data.
Resource isolation limits impact but does not remove prompt injection risk.

## 7. Authentication, quota, and billing

Local Codex and Claude subscription logins are not interchangeable with API keys.
Explicitly unset model-provider API keys in a subscription-funded scheduler. Check auth
noninteractively before model spend.

If using documented Codex account methods, snapshot rate limits before/after a stage.
Consume only an earned reset credit, use a UUID idempotency key, and refresh limits after
consumption. A paid balance or paid overflow policy should be an explicit decision, not
an accidental fallback.

`openai/codex-action@v1` is an API-key surface and is API billed. Keep that distinction
prominent in copied workflow examples and isolate unrelated secrets from its step.

## 8. Isolate repositories with live schedulers

First harden and commit any coherent pre-existing work. Then create a linked worktree on
a migration branch so the production checkout remains clean on its publishing branch:

```bash
git worktree add -b codex-cli-migration ../repo-codex-cli-migration HEAD
```

Do not develop on a checkout that an unattended job may switch, commit, or publish from.
Preserve one historical input/output fixture before the next scheduled run overwrites
ignored scratch files.

## 9. Test and cut over

Use four layers:

1. **Hermetic runner tests:** fake both CLIs; cover provider override, closed stdin,
   retries, exact fallback categories, quota reset outcomes, transactional restoration,
   idle handling, locking, and dry-run suppression.
2. **Permission-negative tests:** workspace write succeeds; `.env`, protected config,
   outside paths, shell network, and secret environment access fail without a prompt.
3. **Discovery tests:** both CLIs see the same guidance and skill bytes; every native
   agent adapter resolves its shared role skill.
4. **Acceptance gates:** run Codex on a preserved historical input and compare artifact
   contracts/quality with the committed Claude output, then run one current full
   no-side-effect Codex pipeline with closed stdin.

Check deterministic schema, link validity, source traceability, unsupported claims,
length/structure envelopes, repetition warnings, structured traces, quota snapshots,
zero approval/input events, and zero external side effects. Validate the exact model and
effort mapping that will be scheduled.

## 10. Common traps

- `acceptEdits` is not Claude Auto mode, and a broad preallowed `Bash` can still be
  host-level power when no Claude sandbox is enabled.
- Claude `--allowedTools` preapproves tools; it does not by itself remove all other tools.
- Codex `approval_policy="never"` denies escalation; it does not make denied operations
  succeed. The agent must recover or fail.
- Passing `--sandbox` selects the older sandbox system and can bypass a named permission
  profile selection. Do not mix the two configurations accidentally.
- Codex project configuration is trust-scoped. Test from the same path and account the
  scheduler uses.
- `.git`, `.agents`, and `.codex` may remain protected inside a writable workspace.
- User-level configuration can drift. Pin critical settings, use strict parsing, log CLI
  versions, and test the scheduled environment.
- A total timeout and a no-output timeout solve different problems. Long reasoning may be
  valid while silent deadlock is not.
- Delete partial outputs before retry/fallback or, better, restore a stage snapshot.
- Never parse credential files or private rollout formats for production telemetry.
- Symlinks need explicit Windows/Git support; copy generation may be safer cross-platform.
- Some Linux standalone Codex releases can create an arg0 sandbox alias whose target
  under `~/.local/bin` is invisible inside bubblewrap. Launching the same binary through
  a protected, ignored workspace hard link avoids that upstream packaging bug; prove the
  exact `codex exec` shell path, not only `codex sandbox`, in acceptance preflight.
- A named Codex custom agent cannot also request a full-history fork. Give it a bounded
  prompt and omit full-history inheritance, or omit the custom agent type.

## Copy-ready checklist

- [ ] Inventory invocations, flags, instructions, skills, agents, hooks, MCP, auth, and scheduler.
- [ ] Record exact/substitute/unsupported parity and residual risk.
- [ ] Lock provider, model/effort, approval, sandbox, web, quota, timeout, fallback, and rollback decisions.
- [ ] Create an isolated branch/worktree and preserve a historical fixture.
- [ ] Make `AGENTS.md` canonical and `CLAUDE.md` an import shim.
- [ ] Make `.agents/skills` canonical and add Claude compatibility paths.
- [ ] Split role behavior from provider-native agent metadata.
- [ ] Implement one closed-stdin runner with strict config, traces, output transactions, and dry run.
- [ ] Remove private auth/quota/transcript dependencies.
- [ ] Add hermetic, permission-negative, discovery, documentation, shadow, and live dry-run tests.
- [ ] Keep the old provider as an explicit rollback until the new path proves stable.

Official references: [Claude CLI](https://code.claude.com/docs/en/cli-usage),
[Claude permissions](https://code.claude.com/docs/en/permission-modes),
[Claude memory](https://code.claude.com/docs/en/memory),
[Claude skills](https://code.claude.com/docs/en/slash-commands),
[Claude subagents](https://code.claude.com/docs/en/sub-agents),
[Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Codex permissions](https://learn.chatgpt.com/docs/permissions),
[Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Codex skills](https://learn.chatgpt.com/docs/build-skills), and
[Codex GitHub Action](https://learn.chatgpt.com/docs/github-action).
