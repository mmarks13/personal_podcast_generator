---
name: analyze-turns
description: Profile podcast agent runs from their provider-neutral structured traces. Use for usage, action, duration, retry, fallback, quota-delta, or large-result analysis across Codex and Claude stages.
---

# Analyze agent runs

Analyze only `logs/agent-traces/*/summary.json` and neighboring supported trace files.
Never inspect private Codex rollout storage, Claude credential files, or private Claude
session transcripts.

Run:

```bash
python3 .agents/skills/analyze-turns/analyze_turns.py [TRACE_DIR|latest]
```

The deterministic report covers provider, stage, model, effort, duration, aggregate
usage exposed by the provider, action/event counts, retries, fallback, and quota delta.
It deliberately does not claim per-turn or per-subagent token precision when the
supported trace does not expose it.

Lead the diagnosis with the slowest and highest-usage stages. Call out retries,
fallback, unusual action counts, and missing telemetry. Keep every recommendation
traceable to a field in the report.
