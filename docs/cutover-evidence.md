# Codex cutover evidence

## Historical shadow: 2026-08-01

- Provider/model/effort: Codex, `gpt-5.6-sol`, `xhigh`.
- Result: passed in one attempt; no fallback or earned reset.
- Runtime: 1,631 seconds.
- Artifact contracts: script, metadata, episode JSON, and show notes all present.
- Date: 2026-08-01.
- Codex script: 3,197 whitespace words; committed Claude script: 3,843.
- Built dialogue: 73 turns.
- Sources: eight, all HTTP(S).
- Deterministic gate: passed, zero warnings; estimated 21 minutes at 150 wpm.
- Quota: weekly utilization moved from 23% to 32%; paid balance remained zero;
  two earned reset credits remained available.
- Trace: ignored local `logs/agent-traces/20260801T113928/`.

The preserved inputs and Claude output are under
`tests/fixtures/shadow/2026-08-01/`. Re-run with:

```bash
python3 scripts/shadow_gate.py
```

That command performs a fresh production-mapped `xhigh` Codex request and consumes
subscription quota; it is not a fixture-only unit test.

## Current no-side-effect gate

- Command: `RUN_EPISODE_DRY_RUN=1 AGENT_PROVIDER=codex AGENT_EFFORT_OVERRIDE=low bash run_episode.sh`.
- Result: passed, exit 0, 1,009 seconds; no fallback, retry, earned reset, approval,
  or user-input event.
- Sources: 39 feeds, 186 items; one recorded source error.
- Crawl: passed in 50 seconds with a freshly written artifact.
- Consolidation: passed in 138 seconds; 172 candidates, zero empty summaries.
- Podcast: passed in 369 seconds; 101 turns, 3,219 words, zero gate warnings.
- Deep dive: passed in 314 seconds; 125 turns, 3,164 words, zero gate warnings.
- Quota: weekly utilization moved from 41% to 45%; paid balance remained zero;
  both earned reset credits remained available.
- Dry-run side-effect audit: skipped Git, history, archive, TTS, publication, Kindle,
  ntfy, proposal-ledger cleanup, and sibling-repository writes.
- Traces: ignored local directories `logs/agent-traces/20260801T134459/`,
  `20260801T134549/`, `20260801T134808/`, and `20260801T135416/`.

Re-run with:

```bash
RUN_EPISODE_DRY_RUN=1 AGENT_PROVIDER=codex AGENT_EFFORT_OVERRIDE=low bash run_episode.sh
```

The functional gate used the user-approved `low` test override. The historical gate
above exercised the locked production `xhigh` podcast mapping. Two low-effort tool
assumptions recovered without intervention: `grep` replaced an unavailable `rg` and
`python3` replaced a missing worktree-local `.venv/bin/python`. The runtime now exposes
the bundled `rg` through its protected helper directory, and shared skills explicitly
fall back to `python3`.
