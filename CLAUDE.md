# daily-ai-podcast — project memory

Automated daily AI-news podcast: gather the day's AI papers, model releases, and
top discussion → write a grounded ~15-minute two-host script → render to MP3 → publish
to an RSS feed Spotify polls.

## How this runs (Plan A)
- Orchestrated locally by `run_episode.sh`, fired nightly by launchd/cron.
- Claude work uses the **logged-in Claude Pro CLI** — do NOT set ANTHROPIC_API_KEY in
  the run environment (that switches to paid API billing). Only object-storage keys are
  needed at runtime.
- Audio is **local Kokoro** (free). ffmpeg must be on PATH.

## Editorial rules (non-negotiable)
- Every factual claim traces to a fetched source. No invented benchmark numbers,
  authors, dates, funding figures, or quotes. "The authors report…", not "this proves…".
- Verify newsletter/aggregator items at the primary source before including them.
- A quiet day is fine — say so rather than padding.

## Map
- `.claude/skills/daily-ai-podcast/SKILL.md` — the workflow Claude follows.
- `config/sources.yaml` — the source watchlist (Tier 1 = daily; Tier 2 = optional).
- `scripts/fetch_sources.py` — deterministic pulls (arXiv, HF Daily Papers, HN).
- `scripts/make_audio.py` — Kokoro/ElevenLabs render + ffmpeg stitch.
- `scripts/publish.py` — upload MP3 + rebuild iTunes-compatible feed.xml.
- `scripts/update_history.py` — maintain `history.json` (show memory: 30-day detail +
  long-term thread/entity/monthly rollup) so episodes don't repeat and arcs build.
- `history.json` — the show's memory; read before writing each episode, committed so it
  persists across nightly runs.

## Run it
`bash run_episode.sh`  → writes out/episode.json, out/shownotes.md, out/podcast-DATE.mp3,
then uploads and updates the feed.
