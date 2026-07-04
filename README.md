# Daily AI Podcast

An overnight job that turns the last ~24–48 hours of AI activity — papers, model
releases, and top discussion — into a grounded **18–28 minute** two-host episode,
renders it to MP3, and publishes it to an RSS feed Spotify polls. A typical episode is
**2–3 mini deep-dives** (stories taught properly: mechanism, numbers, pushback, so-what)
plus a **brisk sweep** of everything else worth knowing, honestly sized; the day's
material — not a template — picks the exact shape.

It's built **Claude Code–native**: skills encode the editorial workflows, small
subagents do the gathering, deterministic Python handles feeds, validation, TTS, and
publishing, and a local scheduler fires it every night.

```
personal_podcast_generator/
├── .claude/skills/daily-ai-podcast/SKILL.md   # the editor-in-chief brain (nightly)
├── .claude/skills/weekly-deep-dive/SKILL.md   # Wed + Sat teaching episode (~20–25 min)
├── .claude/skills/daily-read/SKILL.md         # "Self Attention": daily magazine → EPUB → Kindle
├── .claude/agents/source-crawler.md           # crawls the HTML-only watchlist sources
├── .claude/agents/source-consolidator.md      # merges dumps → out/candidates.json
├── .claude/agents/fact-checker.md             # verifies load-bearing claims at the source
├── .claude/agents/link-checker.md             # validates cited URLs in the daily read
├── config/sources.yaml                        # the source watchlist (Tier 1/2)
├── scripts/fetch_sources.py                   # deterministic pull of all rss/api feeds
├── scripts/build_episode.py                   # script.txt + meta → episode.json + shownotes
├── scripts/check_episode.py                   # pre-render gate: schema, length, tags, artifacts
├── scripts/make_audio.py                      # Gemini multi-speaker TTS (default) or Kokoro
├── scripts/make_epub.py                       # read markdown → EPUB (with cover)
├── scripts/send_to_kindle.py                  # email the EPUB to a Kindle
├── scripts/publish.py                         # upload MP3 + rebuild feed.xml (github|s3)
├── scripts/update_history.py                  # maintain history.json (the show's memory)
├── history.json                               # show memory: 30-day detail + long-term arcs
├── reads_history.json                         # the daily read's memory
├── archive/scripts/                           # every published script; the show's mirror
├── run_episode.sh                             # the nightly local entrypoint
├── docs/                                      # GitHub Pages: feed.xml, episode pages, reads/
├── examples/                                  # alternative entrypoints (Actions, SDK)
└── requirements.txt
```

## How this runs

The whole pipeline runs **locally on your machine** and draws on a Claude Pro
subscription rather than pay-per-token API billing:

- **Claude work** uses the **logged-in Claude Pro CLI** (`claude login` / OAuth).
  **`ANTHROPIC_API_KEY` is never set in the run environment** (`run_episode.sh`
  explicitly unsets it); setting it would switch billing to the paid API.
- **Audio** is **Gemini multi-speaker TTS** (NotebookLM-style dialogue; needs
  `GEMINI_API_KEY`, voices via `GEMINI_VOICE_A/B` in `.env`) + `ffmpeg` on `PATH`. The
  renderer retries hard and then **fails** — it never silently falls back. A local
  [Kokoro](https://github.com/hexgrad/kokoro) path is kept for manual offline
  experiments only.
- **Hosting** is **GitHub-native**: the MP3 is uploaded as a **GitHub Release asset**,
  and `feed.xml` + episode pages + the cover are served from `docs/` via **GitHub
  Pages**. (`publish.py` also has an S3/R2 backend behind `PUBLISH_BACKEND=s3`.)
- **Orchestration** is local **cron/launchd** firing `run_episode.sh` nightly.

## The show

Two hosts who know they're AIs: **Ada** (MIT computing historian — explains by
lineage) and **Alan** (Berkeley builder — what does it cost, what breaks). In each
dive one of them **teaches** and the other plays working skeptic; roles swap story by
story. Their slowly accreting canon (habits, running bits, staked positions) lives in
`history.json` as `lore`. The only fixed rituals are the dated two-voice greeting and
the sign-off — **"Stay grounded."**

Every night the writer also reads its own **last 2–3 scripts** (`archive/scripts/`,
committed by the publish step) with a standing instruction: notice your own patterns —
shape, phrases, framings, titles — and break them. Variety is defined relative to what
the show just did, not by a rulebook, and the **week** (not the episode) is the unit
that must deliver both deep understanding and full situational awareness.

## Architecture (and why it's split this way)

The pipeline separates **deterministic** work from **agentic** work, and the cheap
gathering from the expensive judgment. `run_episode.sh` runs the whole gather phase
*before* the main writing session, so the Opus editor starts clean:

| Stage | How | Why |
|---|---|---|
| Structured feeds | `fetch_sources.py` (all `rss`/`api` from `sources.yaml`, both tiers) → `out/sources.json` | Clean machine feeds — arXiv (keyword-filtered), HF Daily Papers, HN, lab/news/newsletter RSS. No LLM; every item tagged with its source. |
| HTML sources | a **Haiku** session following `source-crawler.md` → `out/crawl.json` | Lab blogs, release notes, leaderboards have no feed. Self-recovers Tier-1 failures via backup search. |
| Consolidate | a **Sonnet** session following `source-consolidator.md` → `out/candidates.json` | De-dupes across feeds + crawl, preserves signals, **flags likely repeats against `history.json`**. Judgment-free. |
| Select + verify + write | the **Opus** session, via the daily-ai-podcast skill | The editorial step: read only `candidates.json`, decide what matters, verify at primary sources (batched through the `fact-checker` agent), write `out/script.txt` + `out/episode_meta.json`. |
| Build + gate | `build_episode.py` then `check_episode.py` | Deterministic conversion to `episode.json`/`shownotes.md`, then a hard gate: schema, word band (3,000–4,700), audio-tag form/density, TTS artifacts — plus a warn-only check for phrases recurring across recent archived scripts. |
| Render | `make_audio.py` (Gemini TTS) + ffmpeg | Deterministic; honors optional per-episode `tts_notes`. |
| Publish | `publish.py` (github or s3 backend) | Uploads the MP3, rebuilds `feed.xml` + episode pages, commits `docs/` + `history.json` + `archive/`. |

The skill's **grounding rules** are the heart of it: every claim traces to a fetched
source, no invented benchmarks/quotes/authors, load-bearing claims are attributed on
air, and "the authors report…" rather than "this proves…".

## Memory & repeats

`history.json` is the show's memory — the last ~30 days in detail plus a long-term
rollup (active threads, entity roster, monthly milestones, host lore). Before writing,
the skill reads it the way a host recalls their own past episodes; `update_history.py`
keeps it bounded (30-day roll-off, caps, threads untouched for ~3 weeks retire
automatically). Threads are **concrete storylines** with actors and a possible ending —
never topic areas.

Repeats are enforced, not just discouraged: the consolidator flags likely repeats
against memory, and a flagged story may only run if the writer records what's *new*
(`repeat_coverage` in `episode_meta.json` — the audit trail). Same-thesis repetition is
handled by the self-reading step: the writer sees what conclusions the show recently
drew and takes a different angle.

## The other two productions

- **Weekly deep-dive** (Wed + Sat, `weekly-deep-dive` skill): one topic the week's news
  made worth learning properly, researched at primary sources and taught end-to-end,
  ~20–25 min, published with `--slug deepdive`.
- **"Self Attention"** (daily, `daily-read` skill, separate ~06:30 cron job): a reading
  magazine — essays, explainers, history, fiction — from a fixed masthead of writers,
  built into an EPUB (`make_epub.py`), emailed to a Kindle (`send_to_kindle.py`;
  needs `KINDLE_EMAIL` + `GMAIL_APP_PASSWORD`), and served from `docs/reads/`.
  Weekday issues ~30 min; weekend issues ~1 hr. Continuity in `reads_history.json`.
  Fully independent of the podcast.

## Sourcing

The watchlist lives in [`config/sources.yaml`](config/sources.yaml) (Tier 1 = daily
core; Tier 2 = optional), keyed by `method`: `rss` | `api` | `fetch`. The split is by
*how* a source is gathered, not how important it is:

- **`rss` / `api` (both tiers) → `fetch_sources.py`**, written to `out/sources.json`.
  arXiv runs on a **48-hour** window because its announcement gap can leave the
  freshest papers ~28h old.
- **`fetch` (HTML) → the crawler session.** Aggregators are used only for discovery;
  every claim is verified at the primary source before it goes in the show.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# ffmpeg is a system dependency:  sudo apt-get install -y ffmpeg   (or: brew install ffmpeg)
# Claude Code CLI, logged in on this machine:
claude login          # one-time; the nightly run uses this Pro session

cp .env.example .env  # fill in SHOW_* / OWNER_EMAIL / GEMINI_API_KEY (+ Kindle vars
                      # for the daily read). Do NOT add ANTHROPIC_API_KEY.
```

Test the pieces independently, then do a full run:

```bash
# 1. deterministic sources only
python scripts/fetch_sources.py --hours 48 --out out/sources.json

# 2. confirm Pro auth works non-interactively (must print "ok", no API-key prompt)
claude -p "Reply with the single word: ok" --max-turns 1

# 3. full run end to end (gather → write → gate → render → publish)
bash run_episode.sh
```

`run_episode.sh` writes `out/episode.json`, `out/shownotes.md`, and
`out/podcast-YYYY-MM-DD.mp3`, then publishes and archives the script. Validate the
feed (e.g. castfeedvalidator.com / podba.se) and listen before you schedule anything.

**Note:** publishing is branch-scoped — the feed serves from `main`/`docs`, so
`run_episode.sh` refuses to run on another branch with uncommitted changes and
otherwise switches to `main` itself.

## Publishing & Spotify

`publish.py` (github backend) uploads the MP3 as a release asset, rebuilds
`docs/feed.xml` + per-episode HTML pages from `episodes.json`, and commits + pushes
`docs/`, `history.json`, and `archive/`. GitHub Pages serves the feed at
`https://<owner>.github.io/<repo>/feed.xml`.

One-time Spotify submission: **Spotify for Creators → Add a new show → host =
"Somewhere else"** → paste the Pages feed URL → enter the 8-digit code Spotify emails
to `OWNER_EMAIL`. New episodes then appear automatically within a couple hours of each
nightly feed update.

## Scheduling (local cron / launchd)

The run must execute on the machine where you ran `claude login`. Two jobs: the full
podcast pipeline overnight, and the daily read on its own after the 5h rate-limit
window resets, so the read gets a fresh budget instead of competing with the podcast:

```cron
0 1 * * *  cd /ABSOLUTE/PATH/personal_podcast_generator && bash run_episode.sh      >> logs/cron-bootstrap.log 2>&1
5 6 * * *  cd /ABSOLUTE/PATH/personal_podcast_generator && bash run_episode.sh read >> logs/cron-bootstrap.log 2>&1
```

`run_episode.sh` (no arg) runs the full pipeline — including the deep-dive on
Wednesdays and Saturdays; `run_episode.sh read` runs only the daily read (write →
Kindle → commit EPUB + reads_history). On macOS, use a launchd
`StartCalendarInterval` plist instead (it can wake the machine).

> One run/night fits comfortably within Pro's normal limits; a heavy Claude Code
> coding week could occasionally bump a limit, in which case Max helps.

## Other entrypoints

`examples/` holds two alternatives, kept for reference and not wired in:

- `examples/run_daily.py` — the same skill driven via the **Claude Agent SDK** (Python).
- `examples/daily-podcast.yml` — a **GitHub Actions** workflow. Note: it sets
  `ANTHROPIC_API_KEY` (paid API) — a deliberate deviation from the local-Pro setup.

## Things you'll want to tune

- Host personas, dive criteria, and the length envelope — in the daily skill.
- Tier-1/Tier-2 source mix, arXiv categories — in `config/sources.yaml`.
- HN points threshold and look-back window — in the fetcher.
- TTS voices and model — `GEMINI_VOICE_A/B`, `GEMINI_TTS_MODEL` in `.env`.
