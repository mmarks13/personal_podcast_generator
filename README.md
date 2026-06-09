# Daily AI Podcast

An overnight job that turns the last ~24 hours of AI activity — papers, model
releases, and top discussion — into a short two-host audio briefing with show notes.

It's built **Claude Code–native**: a [skill](.claude/skills/daily-ai-podcast/SKILL.md)
encodes the editorial workflow, deterministic Python handles the feeds and the
text-to-speech, and a scheduler of your choice fires it every night.

```
daily-ai-podcast/
├── .claude/skills/daily-ai-podcast/SKILL.md   # the editor-in-chief brain
├── scripts/fetch_sources.py                   # arXiv + HF Daily Papers + Hacker News
├── scripts/make_audio.py                       # Kokoro (local/free) or ElevenLabs (API)
├── run_daily.py                                # Agent SDK entrypoint (one of 3 options)
├── .github/workflows/daily-podcast.yml         # GitHub Actions entrypoint (option 2)
└── requirements.txt
```

## Architecture (and why it's split this way)

The pipeline deliberately separates **deterministic** work from **agentic** work:

| Stage | How | Why |
|---|---|---|
| Papers + HN | `fetch_sources.py` (plain HTTP) | These have clean, stable APIs. No LLM needed; cheaper and reproducible. |
| Releases + news | Claude's `WebSearch` / `WebFetch` | Launches and blog posts have no good feed. Multi-step discovery is exactly what an agent is for. |
| Summarize + script | Claude, via the skill | The judgment step — what matters, how to say it, grounded in only what was gathered. |
| Audio | `make_audio.py` (Kokoro or ElevenLabs) + ffmpeg | Deterministic render; swap the voice engine without touching anything else. |

The skill's **grounding rules** are the heart of it: every claim must trace to a fetched
source, no invented benchmarks/quotes/authors, and "the authors report…" rather than
"this proves…". (If you've built RAG with faithfulness scoring, this is the same
discipline applied to a generation task — you can even point an NLI check at
`episode.json` vs. `sources.json` as a nightly guardrail.)

## Sourcing

- **arXiv API** — `cs.AI`, `cs.CL`, `cs.LG`, newest first. Rock-solid, no key.
- **Hugging Face Daily Papers** (`/api/daily_papers`) — AK's curated, upvoted feed; the
  best single signal for "what the field is actually reading today." There's also an
  official [`huggingface-papers` skill](https://github.com/huggingface/skills) you can
  drop in if you want richer per-paper metadata.
- **Hacker News** (Algolia API) — AI-keyword front-page stories by points, for the
  practitioner pulse and links the curated feeds miss.
- **Releases & news** — gathered by the agent from primary sources (Anthropic, OpenAI,
  DeepMind, Meta, Mistral release notes/model cards), aggregators used only for
  discovery. More robust than hardcoding RSS feeds that rot.

## Text-to-speech: pick your engine

`make_audio.py` ships two backends; set `TTS_BACKEND` (or `--backend`).

- **`kokoro`** (default) — open-weight 82M model, **Apache-2.0, free, runs on CPU**.
  Excellent for informational narration; delivery is a touch flatter and it can't clone
  voices. Best when you want zero per-episode cost and full local control.
- **`elevenlabs`** — **ElevenLabs v3** (GA early 2026) leads expressive, multi-speaker
  narration and handles two-host banter best. Paid API (~$165/1M chars), needs
  `ELEVENLABS_API_KEY`.

Other reasonable swaps if you want them: **Gemini Flash TTS** (per-speaker scene
direction), **Fish Audio S2** (~$15/1M chars, cheap hosted), **Chatterbox** (MIT, voice
cloning, needs a GPU), **VibeVoice** (long-form). If you'd rather not maintain the
render step at all, [**Podcastfy**](https://github.com/souzatharsis/podcastfy) is a
batteries-included open-source library that does script→audio across OpenAI/Google/
ElevenLabs/Edge TTS in one call — but the thin pipeline here matches a
"no heavy framework" preference and keeps every step inspectable.

## Scheduling: three ways to run it overnight

All three run the *same* skill. Choose by where the audio must be generated and whether
you want a machine of your own involved.

### Option 1 — Claude Code Routine (cleanest hands-off)
Anthropic shipped **Routines** (research preview, April 2026): a saved Claude Code
config that runs in Anthropic's managed cloud on a schedule — **your laptop can be
closed**. Create one from the CLI:

```
/schedule every day at 1am: use the daily-ai-podcast skill to produce today's episode
```

Manage at `claude.ai/code/routines`. Caveats: minimum cadence is **hourly** (daily is
fine), it runs against a connected repo, and because it's in the cloud you must use an
**API TTS backend** (set `TTS_BACKEND=elevenlabs`) — local Kokoro needs a machine you
control. Available on Pro/Max/Team/Enterprise with Claude Code on the web; **not yet on
Bedrock/Vertex** (use Option 2 there). Have the routine commit the MP3 to the repo or
push it to S3/email for delivery.

### Option 2 — GitHub Actions (durable, serverless-ish, version-controlled)
See [`.github/workflows/daily-podcast.yml`](.github/workflows/daily-podcast.yml). A
`schedule:` cron trigger installs ffmpeg + the Claude Code CLI, runs the skill headless
with `claude -p`, and uploads the episode as an artifact. Works with Bedrock/Vertex,
runs local Kokoro on the runner for free, and you can swap the artifact step for a
commit, an R2/S3 upload, or an RSS-feed update. (Anthropic's official
`anthropics/claude-code-action@v1` is the alternative if you want the agent to operate
on the repo itself.)

### Option 3 — OS cron / launchd + `claude -p` (full control, local TTS)
Best if you want everything on your own box (and free local audio). One crontab line:

```bash
0 1 * * *  cd /path/to/daily-ai-podcast && TTS_BACKEND=kokoro \
  claude -p "Use the daily-ai-podcast skill to produce today's episode, following its grounding rules." \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill" \
  --permission-mode acceptEdits >> out/cron.log 2>&1
```

The machine must be awake at fire time (on macOS prefer `launchd`, which can wake the
machine; on a Mac mini / always-on server this is the sweet spot). `run_daily.py` is the
same thing via the **Agent SDK** if you'd rather drive it from Python and wrap it in your
own logging/observability.

> Two more session-scoped primitives exist — `/loop` (polls every few minutes while a
> session is open) and Claude Desktop scheduled tasks (machine must be on). Neither
> survives a closed terminal, so they're not the right tool for an unattended nightly
> job; Routines, Actions, or cron are.

## Setup

```bash
pip install -r requirements.txt
sudo apt-get install -y ffmpeg            # or: brew install ffmpeg
npm install -g @anthropic-ai/claude-code  # needed for claude -p and the Agent SDK
export ANTHROPIC_API_KEY=sk-ant-...
# Optional, for higher-quality voices:
export ELEVENLABS_API_KEY=...  &&  export TTS_BACKEND=elevenlabs
```

Test the pieces independently first, then wire up a scheduler:

```bash
python scripts/fetch_sources.py --hours 28 --out out/sources.json   # 1. sources
claude -p "Use the daily-ai-podcast skill to produce today's episode." \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill" --permission-mode acceptEdits
# 2. full run (writes out/episode.json, out/shownotes.md, out/podcast-*.mp3)
```

## Things you'll want to tune
- Host personas, segment count, and target length — in the skill.
- arXiv categories, the news source list, HN points threshold — in the skill / fetcher.
- Voice IDs and the TTS model — top of `make_audio.py` (env vars `ELEVEN_VOICE_A/B`).
- Delivery: add a step to push to a private podcast RSS feed (e.g. an S3/R2 bucket +
  a generated `feed.xml`) so it lands in your podcast app each morning.
- A faithfulness guardrail: a small post-step that scores `episode.json` claims against
  `sources.json` and flags anything unsupported before publish.
