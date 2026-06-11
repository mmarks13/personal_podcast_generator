# Daily AI Podcast

An overnight job that turns the last ~24–48 hours of AI activity — papers, model
releases, and top discussion — into a grounded **18–22 minute** two-host audio briefing,
renders it to MP3, and publishes it to an RSS feed Spotify polls.

It's built **Claude Code–native**: a [skill](.claude/skills/daily-ai-podcast/SKILL.md)
encodes the editorial workflow, deterministic Python handles the feeds, the
text-to-speech, and the publish step, and a local scheduler fires it every night.

```
personal_podcast_generator/
├── .claude/skills/daily-ai-podcast/SKILL.md   # the editor-in-chief brain
├── config/sources.yaml                        # the source watchlist (Tier 1/2)
├── scripts/fetch_sources.py                   # deterministic pull of Tier-1 rss/api feeds
├── scripts/make_audio.py                      # Kokoro (local/free) or ElevenLabs (API)
├── scripts/publish.py                         # upload MP3 + rebuild feed.xml (github|s3)
├── scripts/update_history.py                  # maintain history.json (the show's memory)
├── history.json                               # show memory: 30-day detail + long-term arcs
├── run_episode.sh                             # the nightly local entrypoint
├── docs/                                       # GitHub Pages: feed.xml + cover.png
├── examples/                                   # alternative entrypoints (Actions, SDK)
└── requirements.txt
```

## How this runs

The whole pipeline runs **locally on your machine** and costs ≈ $0 beyond your Claude
Pro subscription:

- **Claude work** uses the **logged-in Claude Pro CLI** (`claude login` / OAuth) — so it
  draws on the Pro plan, not the pay-per-token API. **`ANTHROPIC_API_KEY` is never set in
  the run environment** (`run_episode.sh` explicitly unsets it); setting it would switch
  billing to the paid API.
- **Audio** is **local [Kokoro](https://github.com/hexgrad/kokoro)** (open-weight,
  Apache-2.0, free, CPU-friendly). `ffmpeg` must be on `PATH`.
- **Hosting** is **GitHub-native**: the MP3 is uploaded as a **GitHub Release asset**,
  and `feed.xml` + the cover are served from `docs/` via **GitHub Pages**. No object
  storage or credentials required. (`publish.py` also has an S3/R2 backend behind
  `PUBLISH_BACKEND=s3` if you'd rather use a bucket.)
- **Orchestration** is a local **launchd/cron** job that fires `run_episode.sh` nightly.

## Architecture (and why it's split this way)

The pipeline deliberately separates **deterministic** work from **agentic** work:

| Stage | How | Why |
|---|---|---|
| Structured feeds | `fetch_sources.py` (all Tier-1 `rss`/`api` from `sources.yaml`) | Clean, stable machine feeds — arXiv, HF, lab/news/newsletter RSS. No LLM needed; deterministic, cheap, every item tagged with its source. |
| HTML sources | one crawl subagent (via the skill) | Lab blogs, release-note pages, and leaderboards have no good feed and need a browser. The subagent returns a traceable candidate list; importance isn't judged here. |
| Select + verify + script | the main agent, via the skill | The judgment step — merge everything, decide what matters (topic priorities), verify at primary sources, write, grounded in only what was gathered. |
| Audio | `make_audio.py` (Kokoro or ElevenLabs) + ffmpeg | Deterministic render; swap the voice engine without touching anything else. |
| Publish | `publish.py` (github or s3 backend) | Uploads the MP3 and rebuilds an iTunes-compatible `feed.xml` from the episode catalog. |

The skill's **grounding rules** are the heart of it: every claim must trace to a fetched
source, no invented benchmarks/quotes/authors, and "the authors report…" rather than
"this proves…".

## Length & memory

- **Length.** Episodes run **18–22 minutes** (~2,700–3,300 spoken words).
- **The show remembers.** `history.json` is the show's memory — the last ~30 days in
  detail plus a long-term rollup of ongoing storylines, recurring entities, and monthly
  milestones. Before writing, the skill reads it the way a host recalls their own past
  episodes: it doesn't re-explain what it's already covered, suppresses true repeats
  (covering the *update* when a story moves), and picks up ongoing arcs naturally —
  continuity is felt, not announced with constant callbacks. `update_history.py` keeps
  the file bounded (rolling episodes past 30 days into the summary). It's committed so
  the memory persists across nightly runs.

## Sourcing

The watchlist lives in [`config/sources.yaml`](config/sources.yaml) (Tier 1 = daily
core; Tier 2 = optional), keyed by `method`: `rss` | `api` | `fetch`. The split is by
*how* a source is gathered, not how important it is:

- **`rss` / `api` (Tier 1) → `fetch_sources.py`.** Pulled deterministically every run and
  written to `out/sources.json`, each item tagged with its source so cross-source pickup
  is visible. Covers:
  - **arXiv API** — `cs.AI`, `cs.CL`, `cs.LG`, `cs.MA`, newest first. Rock-solid, no key.
    (The fetcher defaults to a **48-hour** window because arXiv's daily announcement gap
    can leave the freshest papers ~28h old — a tighter window intermittently returns zero.)
  - **Hugging Face Daily Papers** (`/api/daily_papers`) — curated, upvoted feed; the best
    single signal for "what the field is actually reading today."
  - **The lab / news / newsletter RSS feeds** (OpenAI, TechCrunch, VentureBeat, Import AI,
    Latent Space, SemiAnalysis, …).
- **`fetch` (HTML) → a crawl subagent (via the skill).** Lab blogs, release-note pages,
  leaderboards, and news sections that have no clean feed. One subagent crawls them
  (Tier-1 and Tier-2) and returns a traceable candidate list. Aggregators are used only
  for discovery; every claim is verified at the primary source before it goes in the show.

The main agent then merges both, decides what matters (topic priorities), and writes.

## Text-to-speech: pick your engine

`make_audio.py` ships two backends; set `TTS_BACKEND` (or `--backend`).

- **`kokoro`** (default) — open-weight 82M model, **Apache-2.0, free, runs on CPU**.
  Excellent for informational narration; delivery is a touch flatter. This is the default.
- **`elevenlabs`** — more expressive, multi-speaker. Paid API, needs `ELEVENLABS_API_KEY`.
  Left intact for later; the default pipeline does not depend on it.

Voice IDs and the TTS model are at the top of `make_audio.py`.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# ffmpeg is a system dependency:  sudo apt-get install -y ffmpeg   (or: brew install ffmpeg)
# Claude Code CLI, logged in on this machine:
claude login          # one-time; the nightly run uses this Pro session

cp .env.example .env  # then fill in SHOW_* / OWNER_EMAIL. Do NOT add ANTHROPIC_API_KEY.
```

Test the pieces independently, then do a full run:

```bash
# 1. deterministic sources only
python scripts/fetch_sources.py --hours 48 --out out/sources.json

# 2. confirm Pro auth works non-interactively (must print "ok", no API-key prompt)
claude -p "Reply with the single word: ok" --max-turns 1

# 3. full episode end to end (fetch → crawl → select/write → render → publish)
bash run_episode.sh
```

`run_episode.sh` writes `out/episode.json`, `out/shownotes.md`, and
`out/podcast-YYYY-MM-DD.mp3`, then calls `publish.py` to upload the MP3 and update the
feed. Validate the feed (e.g. castfeedvalidator.com / podba.se) and listen before you
schedule anything.

## Publishing & Spotify

`publish.py` (github backend) uploads the MP3 as a release asset, copies the cover to
`docs/cover.png`, rebuilds `docs/feed.xml` from `episodes.json`, and commits + pushes
`docs/`. GitHub Pages then serves the feed at
`https://<owner>.github.io/<repo>/feed.xml`.

One-time Spotify submission: **Spotify for Creators → Add a new show → host =
"Somewhere else"** → paste the Pages feed URL → enter the 8-digit code Spotify emails to
`OWNER_EMAIL`. After approval, new episodes appear automatically within a couple hours of
each nightly feed update.

## Scheduling (local launchd / cron)

The run must execute on the machine where you ran `claude login`, so it uses your Pro
subscription. Verify auth works non-interactively first (step 2 above), then install a
schedule.

**Linux (cron):**
```cron
30 5 * * *  cd /ABSOLUTE/PATH/personal_podcast_generator && . .venv/bin/activate && ./run_episode.sh >> out/run.log 2>&1
```

**macOS (launchd):** a `~/Library/LaunchAgents/com.user.dailyaipodcast.plist` with a
`StartCalendarInterval` — preferred because it can wake the machine. The Mac must be
awake at fire time. See `PLAN.md` §7 for the full plist.

> One run/night fits comfortably within Pro's normal limits; a heavy Claude Code coding
> week could occasionally bump a limit, in which case Max helps.

## Other entrypoints

`examples/` holds two alternatives, kept for reference and not wired in:

- `examples/run_daily.py` — the same skill driven via the **Claude Agent SDK** (Python),
  for wrapping in your own logging/observability.
- `examples/daily-podcast.yml` — a **GitHub Actions** workflow that runs the skill on
  GitHub's infrastructure. Note: it sets `ANTHROPIC_API_KEY` (paid API) and renders on
  the runner — a deliberate deviation from the local-Pro + local-Kokoro setup.

## Things you'll want to tune
- Host personas, segment count, and target length — in the skill.
- Tier-1/Tier-2 source mix — in `config/sources.yaml`.
- arXiv categories and which feeds are pulled deterministically — in `config/sources.yaml`
  (Tier-1 `rss`/`api`); HN points threshold and look-back window — in the fetcher.
- A faithfulness guardrail: a small post-step that scores `episode.json` claims against
  `sources.json` and flags anything unsupported before publish.
