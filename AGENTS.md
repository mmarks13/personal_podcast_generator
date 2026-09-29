# daily-ai-podcast — project memory

Automated daily AI-news podcast: gather the day's AI papers, model releases, and
top discussion → write a grounded 18–28 minute two-host script (a front-loaded rundown of
the whole day + 2–3 mini-dives; the day's material picks the shape) → render to MP3 → publish
to an RSS feed Spotify polls.

## How this runs
- Orchestrated locally by `run_episode.sh`, fired nightly by launchd/cron.
- The 19:30 `propose` run performs the canonical structured fetch, HTML crawl,
  Smallbatch score, and consolidation, then writes `out/gather_manifest.json`. The 02:00
  run reuses that exact gather when the manifest is fresh and valid; it performs one
  recovery gather only when needed, never an automatic overnight delta.
- Agent work defaults to the **logged-in Claude CLI** and can use the logged-in Codex
  CLI through `AGENT_PROVIDER=codex` or availability-only fallback. Never set
  `OPENAI_API_KEY`, `CODEX_API_KEY`, or `ANTHROPIC_API_KEY` in the scheduled environment.
  (Claude became the default on 2026-08-13, after a Codex 0.147.0 upgrade broke its
  local tool host and cost a night's episode — see `ensure_codex_sandbox_helper`.)
- Attended work is a separate door: `bash scripts/codex_interactive.sh` starts Codex on
  the `podcast-interactive` permission profile with `--ask-for-approval on-request` and
  the render/publish variables in its environment, so a human can approve the steps the
  nightly profile is built to refuse. Nothing scheduled touches it, and `.env` stays
  denied on disk there too.
- Audio is **Gemini multi-speaker TTS** (needs `GEMINI_API_KEY`). ffmpeg must be on
  PATH. Kokoro remains for manual offline experiments only.

## Editorial rules (non-negotiable)
- Every factual claim traces to a fetched source. No invented benchmark numbers,
  authors, dates, funding figures, or quotes. "The authors report…", not "this proves…".
- Verify newsletter/aggregator items at the primary source before including them.

## Map
- `.agents/skills/daily-ai-podcast/SKILL.md` — the shared daily workflow. Also
  defines the hosts: Ada (A, MIT computing historian) and Alan (B, Berkeley builder),
  two self-aware AIs whose evolving canon lives in `history.json` `lore`.
- `.agents/skills/weekly-deep-dive/SKILL.md` — Wed/Sat/Sun teaching episode (~20–25
  min), one topic the week's news made worth learning; published with `--slug deepdive`
  (feed title gets a "Deep Dive:" prefix). Topic can be pre-chosen via the evening
  ntfy picker.
- `.agents/skills/daily-read/SKILL.md` — "Self Attention", a **daily** reading magazine
  → EPUB in `docs/reads/`, emailed to Kindle. Fully independent of the podcast (never
  mentions it). A fixed masthead of ten writers (roster and beats live in that skill's
  masthead section); weekday issues ~30 min, Sat/Sun ~1 hr. Continuity in
  `reads_history.json`. Masthead writers may guest on the podcast (one-way crossover).
- `config/sources.yaml` — the source watchlist (Tier 1 = daily; Tier 2 = optional).
- `scripts/fetch_sources.py` — deterministic pulls of ALL rss/api sources, both tiers
  (arXiv keyword-filtered to topic priorities, HF Daily Papers, HN, newsletters).
- `scripts/score_sources.py` — pinned private Smallbatch Qwen function adapter; verifies
  the full package identity/checksums and writes four dimensions plus their 0–9 sum to
  `out/source_scores.json`. Ranking aid only; it never filters records.
- `scripts/stamp_candidates.py` — runs on the consolidator's output, before the manifest:
  stamps every candidate with `published_at`/`date_status` recovered from the raw gather and
  `aired_on`, the exact past-episode dates that already cited its URL (read from
  `archive/scripts/*-meta.json`). The consolidator is an agent and drops date fields, so the
  two facts a writer cannot reconstruct are attached after it rather than routed through it.
- `scripts/gather_manifest.py` — checksum/freshness identity for the reusable gather,
  including an explicit status for every configured Tier-1 source.
- `scripts/crawl_repair.py` — the crawl's coverage check: `missing` lists configured
  `fetch` sources the crawl left unanswered — dropped from `source_statuses`, or Tier-1 and
  marked `failed` with no matching `failures` record (exit 3) — and `merge` folds a
  gap-only repair crawl back into `out/crawl.json`, replacing a defective status. Runs right
  after the crawl so a bad status costs a short repair pass, not a whole gather at the
  manifest gate. The gate itself records such a status and warns rather than discarding the
  gather: `GATHER_RESUME_AFTER_CONSOLIDATE=1 bash run_episode.sh propose` rebuilds only the
  manifest from existing artifacts when it still ends up blocking one.
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
  (`NTFY_TOPIC` in `.env`): run-failure alerts, and the **nightly picker**.
  `run_episode.sh propose` runs every evening and pushes ONE message carrying up to two
  slates: 15 of the day's stories the listener can lock as tomorrow's **mini-dives**
  (`out/daily_options.json`, **numbered**, ~8 top-by-signal plus ~7 marked wildcards
  deliberately spread across kinds of story so the slate reads as a menu), and
  — on Tue/Fri/Sat — a mixed slate of 8 typed deep-dive pitches
  (mechanism/foundational/history/debate, `out/deepdive_options.json`, **lettered**).
  Both are drafted from memory + the same canonical evening `out/candidates.json` that
  the 02:00 writers later receive. One reply answers both: numbers pick mini-dives (up to 3),
  a letter picks the deep dive, bare free text is a mini-dive in the listener's own
  words, and a `dd ` prefix makes it a deep-dive topic instead. Punctuation between
  picks is free ("3, 14. A" works); a wide slate goes out as two chunked pushes, and
  each half takes the newest reply that answers *it*, so answering the two pushes in
  separate messages works and a later message still corrects its own half. Mini-dive picks are
  **locked** — the writer never drops one, and post-cutoff news waits for the next cycle — and
  they override `listener.yaml` downweights and the paper-aging rule.
  `scripts/daily_options.py` renumbers/stamps the daily half (no ledger: stories are
  perishable). `scripts/proposal_ledger.py` maintains `deepdive_proposals.json`: a topic
  pitched 3 evenings without being chosen is retired from future slates, and a topic
  that was chosen leaves them too — it has already been an episode. The deep-dive run
  records the topic that actually aired even when the writer picked it itself; before
  that, only phone-chosen topics were recorded and taught subjects kept returning.
- `feedback.md` (root) — listener notes, read first each night; consumed notes land
  in `archive/feedback_log.md`. `listener.yaml` (root) — standing interest weights.
  `config/pronunciations.yaml` — TTS-mispronounced names and the respellings
  `make_audio.py` substitutes into the text it sends the API (audio only; the script
  and transcript keep the normal spelling). The writer may update these three;
  never SKILL.md.
- `scripts/update_history.py` — maintain `history.json` (show memory: 30-day detail +
  long-term thread/entity/monthly rollup) so episodes don't repeat and arcs build.
  Dedup key is (date, kind) so deep-dive records coexist with the daily's.
- `history.json` — the show's memory; read before writing each episode, committed so it
  persists across nightly runs.

## Run it
`bash run_episode.sh`  → writes out/episode.json, out/shownotes.md, out/podcast-DATE.mp3,
then uploads and updates the feed.

## Delegation compatibility

- Keep custom-agent prompts bounded and pass all required claims, URLs, sources, and
  output contracts explicitly.
- When Codex invokes a named custom agent, do not request a full-history fork; a named
  agent type and full-history inheritance are mutually exclusive. If full history is
  genuinely required, omit the custom agent type. Claude may use its native named-agent
  invocation for the same shared role skill.
- A rejected optional delegation must be handled locally or fail the stage; it must
  never turn into a request for user input during a scheduled run.



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

Use the surface's user-question mechanism when a consequential decision truly requires input. Scheduled production runs are unattended and must never request input.

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
