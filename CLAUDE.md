# daily-ai-podcast — project memory

Automated daily AI-news podcast: gather the day's AI papers, model releases, and
top discussion → write a grounded 18–28 minute two-host script (2–3 mini-dives + a
brisk sweep by default; the day's material picks the shape) → render to MP3 → publish
to an RSS feed Spotify polls.

## How this runs
- Orchestrated locally by `run_episode.sh`, fired nightly by launchd/cron.
- Claude work uses the **logged-in Claude Pro CLI** — do NOT set ANTHROPIC_API_KEY in
  the run environment (that switches to paid API billing). Only object-storage keys are
  needed at runtime.
- Audio is **Gemini multi-speaker TTS** (needs `GEMINI_API_KEY`). ffmpeg must be on
  PATH. Kokoro remains for manual offline experiments only.

## Editorial rules (non-negotiable)
- Every factual claim traces to a fetched source. No invented benchmark numbers,
  authors, dates, funding figures, or quotes. "The authors report…", not "this proves…".
- Verify newsletter/aggregator items at the primary source before including them.

## Map
- `.claude/skills/daily-ai-podcast/SKILL.md` — the daily workflow Claude follows. Also
  defines the hosts: Ada (A, MIT computing historian) and Alan (B, Berkeley builder),
  two self-aware AIs whose evolving canon lives in `history.json` `lore`.
- `.claude/skills/weekly-deep-dive/SKILL.md` — Wed/Sat/Sun teaching episode (~20–25
  min), one topic the week's news made worth learning; published with `--slug deepdive`
  (feed title gets a "Deep Dive:" prefix). Topic can be pre-chosen via the evening
  ntfy picker.
- `.claude/skills/daily-read/SKILL.md` — "Self Attention", a **daily** reading magazine
  → EPUB in `docs/reads/`, emailed to Kindle. Fully independent of the podcast (never
  mentions it). A fixed masthead of ten writers (roster and beats live in that skill's
  masthead section); weekday issues ~30 min, Sat/Sun ~1 hr. Continuity in
  `reads_history.json`. Masthead writers may guest on the podcast (one-way crossover).
- `config/sources.yaml` — the source watchlist (Tier 1 = daily; Tier 2 = optional).
- `scripts/fetch_sources.py` — deterministic pulls of ALL rss/api sources, both tiers
  (arXiv keyword-filtered to topic priorities, HF Daily Papers, HN, newsletters).
- `scripts/check_episode.py` — hard pre-render gate: schema, word band, audio-tag
  form/density, TTS artifacts; warns (never fails) on phrases recurring across recent
  archived scripts.
- `archive/scripts/` — every published script + meta, archived by `run_episode.sh` and
  committed by publish. The nightly writer reads the last 2–3 to break its own
  patterns and balance the week; the gate's phrase check reads them too.
- `scripts/make_audio.py` — Gemini multi-speaker TTS render (NotebookLM-style
  dialogue; the show's voice) + ffmpeg. Needs `GEMINI_API_KEY`; voices via
  `GEMINI_VOICE_A/B` (and `_C` for the occasional guest, speaker `"C"`) in `.env`;
  honors optional `tts_notes`/`guest` in episode.json and writes ID3 chapters from
  the script's `##` markers.
  Retries hard then FAILS — never silently falls back. Kokoro path kept for manual
  offline experiments only (loudnorm on that path; Gemini audio ships untouched).
- `scripts/make_epub.py` — read markdown → EPUB (chapters from `##` headings); renders a
  cover from `docs/cover.png` + title/subtitle via `--cover-src`/`--cover-subtitle`.
- `scripts/update_reads_history.py` — append today's issue to `reads_history.json` (the
  daily read's memory: mood, pieces, authors) so issues don't repeat and voices rotate.
- `scripts/send_to_kindle.py` — email a read EPUB to the Kindle (Gmail SMTP; needs
  `KINDLE_EMAIL`, `GMAIL_APP_PASSWORD`).
- `scripts/publish.py` — upload MP3 + rebuild iTunes-compatible feed.xml; `--slug`
  distinguishes same-day episodes (daily vs deepdive). Episode pages get a chapter
  list + full transcript from the archived script; commits the listener-tunable
  files too.
- `scripts/notify.py` / `scripts/ntfy_choice.py` — the ntfy.sh phone channel
  (`NTFY_TOPIC` in `.env`): run-failure alerts, and the Tue/Fri/Sat-evening deep-dive
  picker (`run_episode.sh propose` pushes 3-5 topic pitches; a reply with a number
  or free text becomes the next morning's deep-dive topic).
- `feedback.md` (root) — listener notes, read first each night; consumed notes land
  in `archive/feedback_log.md`. `listener.yaml` (root) — standing interest weights.
  `config/pronunciations.yaml` — TTS-mispronounced names and speakable spellings
  (gate warns on raw forms). The writer may update these three; never SKILL.md.
- `scripts/update_history.py` — maintain `history.json` (show memory: 30-day detail +
  long-term thread/entity/monthly rollup) so episodes don't repeat and arcs build.
  Dedup key is (date, kind) so deep-dive records coexist with the daily's.
- `history.json` — the show's memory; read before writing each episode, committed so it
  persists across nightly runs.

## Run it
`bash run_episode.sh`  → writes out/episode.json, out/shownotes.md, out/podcast-DATE.mp3,
then uploads and updates the feed.



# Coding Standards

*Apply these standards to all code in this project.*

## Core Development Principles

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

The user owns the priorities and constraints behind design decisions - surface the tradeoffs and ask, don't decide for them.

Use the `AskUserQuestion` tool as the primary medium for surfacing these to the user — treat alignment-checking as a normal planning step, not an escape hatch.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### 5. Report Observable Facts, Acknowledge Missing Context

**Say what's true. Flag what's missing.**

- Limit statements to observable, verifiable facts about what you implemented, tested, or researched.
- Don't declare work "done," "ready," or "production-ready" - completeness is judged against business requirements you don't own (see #4). Report what you did and what's verified; let the user decide whether it meets the bar.
- State what context is missing rather than guessing.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.