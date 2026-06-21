---
name: analyze-turns
description: Diagnose where a Claude Code run's COST goes — turn-by-turn, across the main orchestrator and every subagent — by estimating analogous API dollars per agent, to find the real bottlenecks and explain why a run took so many turns. Use when asked to "analyze turns", "turn-by-turn analysis", "why so many turns", "where did the usage/cost go", "what's draining the 5h limit", "analyze subagent stdout", or to profile a podcast/read/deepdive run.
---

# Analyze Turns — cost & turn profiler

A run that hits the session limit usually isn't doing one expensive thing — it's doing
many turns, each re-sending a growing context, spread across models of very different
price. This skill estimates the **analogous API dollar cost per agent and per turn**, so
you optimize the thing that actually drains the budget.

## What we learned the hard way (read this before interpreting)

- **The 5-hour usage limit is weighted ~by model cost, NOT by flat token count.** Official
  Anthropic docs: usage depends on *"which Claude model you're chatting with"*; *"Opus
  costs several times more per turn than Sonnet, and Sonnet more than Haiku."* So a Haiku
  subagent that moves a lot of tokens is **cheap** against the limit, and an Opus
  orchestrator is expensive even when its token count looks modest. **Rank by estimated $,
  not by tokens** — that's why this tool leads with cost.
- **Current rates (per MTok, baked into the script, update when they change):** Opus 4.8
  `$5/$25`, Sonnet 4.6 `$3/$15`, Haiku 4.5 `$1/$5`. Cache write = 1.25× input, cache read =
  0.1× input. So Opus is ~1.7× Sonnet and ~5× Haiku — meaningful, but not the 15× you might
  assume; a Sonnet subagent can still be a real chunk of the bill.
- **Cost ≠ what the Pro/Max plan bills.** It's an *API-rate proxy* that tracks how the 5h
  limit is consumed. Use it to rank bottlenecks, not to quote a dollar figure as spend.
- **Each turn re-sends the whole accumulated context** (mostly as cheap `cache_read`), so an
  agent's cost is `context × turns × model-rate` plus output (the priciest token class:
  5× input). Shrinking context, cutting turns, and avoiding full-file rewrites all help.
- **Subagent transcripts are separate files** under `<session>/subagents/agent-*.jsonl`,
  linked to the orchestrator via the `agentId` in the Agent tool's result. A subagent's bulk
  output stays in *its* transcript; only its small final return reaches the orchestrator.
- **Streaming duplicates assistant records** (same `message.id` repeated) — the script
  dedupes by `message.id`, so trust its numbers over a raw `wc`/grep of the JSONL.

The split is deliberate:
- **`analyze_turns.py` does all extraction + the cost math deterministically** (zero tokens).
- **You (Claude) only read the compact digest it prints** and apply judgment. Do **not**
  read the raw transcripts yourself — they are megabytes; the point is to not spend tokens
  analyzing token spend.

## Workflow

### 1. Run the profiler on the target session
```bash
.venv/bin/python .claude/skills/analyze-turns/analyze_turns.py <selector>
```
`<selector>`: `latest` (default) · `podcast` · `read` · `deepdive` · `<session-id-or-prefix>`.
Flags:
- `--threshold N` — token size at which a tool result is flagged (default 5000).
- `--verbose` — content previews + per-action detail (use to judge whether a big payload was necessary).
- `--no-timeline` — summary + flags only.
- `--json PATH` — JSON digest location (default `out/turn_analysis-<id>.json`).

Read the printed report. Open the JSON only if you need a field it didn't show.

### 2. Read the digest and form the diagnosis
- **Cost headline + agents-by-cost table** — `$cost` and `share%` per agent (orchestrator +
  each subagent), sorted by cost, with model, turns, `cache_rd`, `out`, `peak_ctx`, and
  `ret_tok` (what each subagent returned into the orchestrator). **This is the bottleneck
  ranking — start here.**
- **Actions per agent** — the histogram that explains the turn count (e.g. `WebFetch×9`).
- **Flags** — biggest returns to the orchestrator, biggest ingested tool results, batchable
  runs (≥3 consecutive identical single-tool turns), duplicate file/url reads.
- **Per-turn timeline** — each turn's `$cost`, context size, output, action, and result size.

Interpret, don't restate. A Haiku crawler doing many `WebFetch`es is cheap and doing its
job — don't chase it just because its token *count* is high. Spend your attention on the
top of the **cost** table: the Opus orchestrator's context × turns and its output (full-file
rewrites), and any Sonnet subagent that re-reads a large file or writes its output twice.

### 3. Deliver: diagnosis + ranked, concrete fixes
1. **Headline** — total estimated $, the single biggest cost center (agent + model + %), and
   total turns.
2. **Why so many turns** — per agent, tie the turn count to its action histogram; call out
   serial-tool runs that could be one parallel turn, write→read→rewrite loops, and avoidable
   round-trips.
3. **Where the cost is** — walk the cost table top-down: for the dominant agent, attribute
   its $ across context re-send (`cache_rd`), context growth (`cache_cr`/`peak_ctx`), and
   output. Name the specific expensive turns from the timeline.
4. **Ranked recommendations** — ordered by **estimated $ saved**, each tied to a specific
   agent/turn/number. Distinguish cheap wins (a subagent returning a 4K blob → 200-tok
   summary) from structural ones (move a whole phase off the Opus session; write a file once
   then `Edit`; shrink a digest the orchestrator re-sends every turn; run a mechanical phase
   deterministically in Python instead of an LLM).

Keep every claim traceable to a number in the report. If something looks off (a subagent ran
twice, a tool result labelled `?`, a model shown as `<synthetic>`), say so rather than guess.

## Notes
- Read-only and offline; never calls the model or the network.
- Costs are an estimate at public API rates (proxy for the 5h limit), not subscription
  billing. Token figures come from `usage` (deduped by `message.id`); tool-result sizes are
  estimated from content length (~4 chars/token) — treat those as ±.
- The 5-hour meter in `run.log` (`scripts/run_log.py`) is the authoritative *account-wide*
  signal; this skill explains *what inside the run* drove it. Update `RATES` in the script
  when Anthropic pricing changes.
