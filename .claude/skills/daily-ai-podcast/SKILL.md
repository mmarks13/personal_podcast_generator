---
name: daily-ai-podcast
description: >
  Produce a daily AI-news podcast: gather the day's AI papers, model releases, and
  top discussion, write a tight two-host script, and render it to an MP3 with show
  notes. Use this skill whenever asked to "make the daily podcast", "do today's AI
  briefing", "run the overnight AI digest", or any request to summarize recent AI
  news/releases/papers into audio — even if the word "podcast" isn't used.
---

# Daily AI Podcast

Turn the last ~24 hours of AI activity into a ~15-minute, two-host audio briefing
(target ~2,000–2,500 spoken words at ~150 wpm).

The pipeline is deliberately split: **deterministic Python** for the things that have
clean APIs (papers, Hacker News), and **your own web tools** for the things that don't
(model releases, blog announcements, breaking news). You are the editor-in-chief — you
gather, you decide what matters, you write the script, you press render.

## Workflow

Run these steps in order. Do not skip the grounding rules in step 3.

### 1. Pull the structured sources
Run the fetcher. It writes `out/sources.json` and prints a summary.

```bash
python scripts/fetch_sources.py --hours 28 --out out/sources.json
```

This covers: recent arXiv papers (cs.AI / cs.CL / cs.LG), the Hugging Face Daily Papers
feed, and top AI-related Hacker News stories. If any single source fails, the script
keeps going and notes the gap — read the printed summary and work with what you have.

### 1.5. Read the watchlist
Read `config/sources.yaml`. Gather from every Tier-1 source; pull from Tier-2 only if
it's a notable day or a Tier-1 gap. Prefer each source's API/RSS; fall back to WebFetch.
Always verify a claim at its primary source before it goes in the script.

### 2. Gather releases and news yourself
The structured feeds miss product launches and announcements. Use `WebSearch` /
`WebFetch` to check, for *today and yesterday only*, this source list:

- Anthropic news (anthropic.com/news), OpenAI news, Google DeepMind blog, Meta AI blog,
  Mistral, and the major labs' release notes / model cards.
- One or two reputable aggregators for anything you missed (e.g. a "this week in AI"
  roundup), used only to discover items — verify each claim at its primary source.

Pull 6–9 genuinely notable items (enough to fill the five segments). Prefer primary
sources over secondhand coverage.
A quiet day is fine — say so rather than padding.

### 3. Write the script — grounded, no embellishment
Write a two-host dialogue (`HOST_A`, `HOST_B`). Target ~2,000–2,500 words (~15 min).

**Grounding rules (these are the point of the whole exercise):**
- Every factual claim must trace to something in `out/sources.json` or a page you
  actually fetched. If you didn't read it, don't say it.
- Do **not** invent benchmark numbers, author names, dates, funding figures, or quotes.
  If a detail isn't in your gathered material, omit it or say it's unconfirmed.
- Distinguish *what a paper claims* from *what is established*. "The authors report…"
  not "this proves…".
- No hype adjectives standing in for facts ("revolutionary", "game-changing"). Describe
  what changed and why it might matter, concretely.
- When two sources conflict, say so briefly rather than picking one silently.

**Structure (15-min show, 5 segments):** cold open (1 line on the day's through-line) →
**Papers** (2–3 items) → **Releases / launches** (2–3 items) → **Industry & news**
(2–3 items) → **One to watch** (1 item, slightly deeper) → 20–30s wrap. Keep turns
short and conversational; alternate hosts. Spell out acronyms on first use. Avoid
reading URLs aloud.

Write **two** files:
- `out/episode.json` — the machine-readable script the renderer consumes. Schema:
  ```json
  { "date": "YYYY-MM-DD",
    "title": "string",
    "turns": [ { "speaker": "A" | "B", "text": "one spoken line, no markdown" } ] }
  ```
  Keep each turn's `text` plain spoken prose — no asterisks, brackets, or stage
  directions; those get read aloud literally.
- `out/shownotes.md` — episode title, date, a 2–3 sentence summary, then a linked list
  of every source you used (title + URL), grouped as Papers / Releases / Discussion.

### 4. Render the audio
```bash
python scripts/make_audio.py --episode out/episode.json --out "out/podcast-$(date +%F).mp3" --backend ${TTS_BACKEND:-kokoro}
```

`--backend kokoro` runs locally and free; `--backend elevenlabs` calls the API for
higher-quality, more expressive voices (needs `ELEVENLABS_API_KEY`). Pick based on the
`TTS_BACKEND` env var so the same skill works in every scheduling setup.

### 5. Report
Print the final MP3 path, the episode title, the word count, and a one-line note on
anything that failed or any source gap. If a downstream step (commit, upload, email) is
configured by the caller, that happens outside this skill — just produce the artifacts.

## Notes
- This skill produces files; it does not publish. Scheduling and delivery live in the
  caller (cron, a GitHub Actions workflow, or a Claude Code Routine) — see the README.
- If `out/` doesn't exist, create it.
- Tune the arXiv categories, the news source list, and the host personas to taste; they
  are meant to be edited.
