---
name: analyze-turns
description: Diagnose where a Claude Code run's turns and tokens go — turn-by-turn, across the main orchestrator and every subagent — to find wasteful stdout/tool output and explain why a run took so many turns. Use when asked to "analyze turns", "turn-by-turn analysis", "why so many turns", "where did the usage/context go", "analyze subagent stdout", or to profile a podcast/read/deepdive run's token cost.
---

# Analyze Turns — usage & turn profiler

A run that hits the session limit (see the nightly `run_episode.sh` pipeline) usually
isn't doing one expensive thing — it's doing many turns, each re-sending a growing
context, with subagents quietly ingesting or returning large blobs. This skill finds
exactly where, then judges what's wasteful.

The split is deliberate:
- **`analyze_turns.py` does all extraction deterministically** (no tokens): it reads the
  session transcript Claude Code already wrote (`~/.claude/projects/<munged-cwd>/…`) plus
  each subagent's own transcript under `<session>/subagents/agent-*.jsonl`, dedupes the
  streaming-duplicated records by `message.id`, and reports per-agent turns, token
  accounting, every tool result sized (ingested vs returned-to-orchestrator), and
  pattern flags.
- **You (Claude) only read the compact digest it prints** and apply judgment. Do **not**
  read the raw transcripts yourself — they are megabytes; the whole point is to not spend
  tokens analyzing token spend.

## Workflow

### 1. Run the profiler on the target session
Default to the most recent run, or take the user's selector (a step name, a session id,
or `latest`):

```bash
.venv/bin/python .claude/skills/analyze-turns/analyze_turns.py <selector>
```

`<selector>` is one of: `latest` (default) · `podcast` · `read` · `deepdive` ·
`<session-id-or-prefix>`. Useful flags:
- `--threshold N` — token size at which a tool result is flagged (default 5000).
- `--verbose` — add content previews and per-action detail (use only if you need to
  judge whether a specific big payload was necessary).
- `--no-timeline` — summary + flags only, skip the per-turn list.
- `--json PATH` — where to write the JSON digest (default `out/turn_analysis-<id>.json`).

Read the printed report. Open the JSON only if you need a field the report didn't show.

### 2. Read the digest and form the diagnosis
The report gives you, deterministically:
- **Per-agent table** — turns, input total, cache read/create, output, peak context, and
  `ret_tok` (how much each subagent *returned* into the orchestrator's context).
- **Actions per agent** — the histogram that explains the turn count (e.g.
  `WebFetch×9, WebSearch×5` for a crawler).
- **Flags** — biggest returns to the orchestrator, biggest ingested tool results,
  batchable runs (≥3 consecutive identical single-tool turns), and duplicate file/url
  reads.

Interpret, don't just restate. For each flag decide **necessary vs wasteful**, and know
the difference: a crawler doing many `WebFetch`es is doing its job — the question is
whether they were serial (one per turn) when they could be parallel (many tool calls in
one turn), or whether a subagent re-read the same large file several times, or returned a
big blob the orchestrator didn't need.

### 3. Deliver: diagnosis + ranked, concrete fixes
Produce:
1. **Headline** — total turns and input tokens, and the single biggest cost center.
2. **Why so many turns** — per agent, tie the turn count to its action histogram; call
   out serial-tool runs that could be batched and any avoidable round-trips.
3. **Wasteful stdout** — list the flagged payloads you judged unnecessary, each with its
   agent, size, and a one-line fix (trim the return, summarize before returning, read the
   file once, stop echoing a large dump to stdout).
4. **Ranked recommendations** — ordered by estimated token savings, each tied to a
   specific agent/turn/number from the report. Distinguish cheap wins (a subagent
   returning a 4K blob → return a 200-tok summary) from structural ones (a whole phase
   that re-ingests a large file every turn).

Keep every claim traceable to a number in the report. If something looks off (e.g. a
subagent ran twice, or a tool result is labelled `?`), say so rather than guessing.

## Notes
- The profiler is read-only and offline; it never calls the model or the network.
- Token figures are from the transcript's `usage` fields (deduped); tool-result sizes are
  estimated from content length (~4 chars/token), so treat those as ±.
- The 5-hour session meter in `run.log` (`scripts/run_log.py`) is the authoritative
  utilization signal; this skill explains *what inside the run* drove it.
