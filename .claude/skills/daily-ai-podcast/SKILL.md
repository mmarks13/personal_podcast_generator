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

Turn the last ~24–48 hours of AI activity into a **16–25 minute**, two-host audio
briefing whose length tracks how much genuinely happened that day (~150 wpm spoken).

The pipeline is deliberately split: **deterministic Python** for the things that have
clean APIs (papers, Hacker News), and **your own web tools** for the things that don't
(model releases, blog announcements, breaking news). You are the editor-in-chief — you
gather, you decide what matters, you write the script, you press render.

## Workflow

Run these steps in order. Do not skip the grounding rules in step 3.

### 1. Pull the structured sources
Run the fetcher. It writes `out/sources.json` and prints a summary.

```bash
python scripts/fetch_sources.py --hours 48 --out out/sources.json
```

This covers: recent arXiv papers (cs.AI / cs.CL / cs.LG), the Hugging Face Daily Papers
feed, and top AI-related Hacker News stories. If any single source fails, the script
keeps going and notes the gap — read the printed summary and work with what you have.

### 1.5. Read the watchlist
Read `config/sources.yaml`. Gather from every Tier-1 source; pull from Tier-2 only if
it's a notable day or a Tier-1 gap. Prefer each source's API/RSS; fall back to WebFetch.
Always verify a claim at its primary source before it goes in the script.

### 1.6. Recall what the show has already covered
Read `history.json` if it exists. It is the show's memory — treat it the way a regular
host remembers their own past episodes, **not** as a script of callbacks:
- `episodes` — the last ~30 days in detail (title, summary, topics, entities, threads).
- `longterm` — older context: `active_threads` (named multi-day storylines with their
  status/arc), an `entities` roster, and a `monthly` rollup of major milestones.

Use it to inform, not to perform:
- **Don't re-explain what you've already established.** If you introduced a model, a
  paper, or a company recently, assume the listener has the background — cover today's
  development, not the backstory again.
- **Suppress true repeats.** Skip a story already covered unless it genuinely moved.
  When it has moved, cover the *update*, not the original news.
- **Pick up arcs naturally.** When today advances an ongoing thread, continue it the way
  a host naturally would — informed and current. A brief, earned reference to past
  coverage is fine **occasionally**, only when it adds something. Do not pepper the show
  with "as we discussed" callbacks; continuity should be felt, not announced. Most
  episodes need zero explicit callbacks.
- A topic only worth recalling is one still present in `history.json` (detail window or
  `longterm`). If it has fully aged out of memory, treat it as fresh.

### 2. Gather releases and news yourself
The structured feeds miss product launches and announcements. Use `WebSearch` /
`WebFetch` to check, for *today and yesterday only*, this source list:

- Anthropic news (anthropic.com/news), OpenAI news, Google DeepMind blog, Meta AI blog,
  Mistral, and the major labs' release notes / model cards.
- One or two reputable aggregators for anything you missed (e.g. a "this week in AI"
  roundup), used only to discover items — verify each claim at its primary source.

Pull as many genuinely notable items as the day actually warrants — roughly 6 on a
quiet day, 10+ on a heavy one. The count drives the episode length (see step 3). Prefer
primary sources over secondhand coverage. A quiet day is fine — a shorter show is the
correct outcome; never pad to hit a length.

### 3. Write the script — grounded, no embellishment
Write a two-host dialogue (`HOST_A`, `HOST_B`). **Length scales with the day's news** —
pick the tier from how many notable items you actually gathered (don't pad to reach one):

| Day | Notable items | Target words | ≈ minutes |
|-----|---------------|--------------|-----------|
| Quiet  | ~6      | ~2,500 | ~16–17 |
| Normal | ~7–9    | ~3,000 | ~20 |
| Heavy  | 10+     | ~3,700 | ~24–25 |

Stay within **16–25 minutes** (~2,400–3,800 words). A genuinely thin day lands near the
floor; a big day earns the longer show by covering more items and going slightly deeper —
not by padding existing ones.

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

**Structure (5 segments):** cold open (1 line on the day's through-line) →
**Papers** → **Releases / launches** → **Industry & news** → **One to watch** (1 item,
slightly deeper) → 20–30s wrap. Each middle segment carries ~2–3 items on a normal day,
more on a heavy day — scale the item count per segment with the tier above. Keep turns
short and conversational; alternate hosts. Spell out acronyms on first use. Avoid
reading URLs aloud.

Write **three** files:
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
- `out/episode_meta.json` — the memory record for `history.json` (step 4.5). Schema:
  ```json
  { "date": "YYYY-MM-DD",
    "title": "string",
    "summary": "1–2 sentence recap of the episode",
    "topics":   ["short topic/story labels covered today"],
    "entities": ["orgs/models/people featured today, e.g. Anthropic, Gemini 3"],
    "threads": [ { "name": "ongoing storyline",
                   "status": "where it stands now",
                   "arc": "one line on how it has progressed" } ] }
  ```
  Fill `threads` only for genuine multi-day storylines (a rollout, a lawsuit, a price
  war) — not one-off items. Reuse a thread's exact `name` from `history.json` when you're
  continuing one, so its arc accumulates instead of forking.

### 4. Render the audio
```bash
python scripts/make_audio.py --episode out/episode.json --out "out/podcast-$(date +%F).mp3" --backend ${TTS_BACKEND:-kokoro}
```

`--backend kokoro` runs locally and free; `--backend elevenlabs` calls the API for
higher-quality, more expressive voices (needs `ELEVENLABS_API_KEY`). Pick based on the
`TTS_BACKEND` env var so the same skill works in every scheduling setup.

### 4.5. Update the show's memory
Fold today into `history.json` so future episodes stay non-repetitive and can build on
ongoing arcs. This reads the `out/episode_meta.json` you wrote in step 3:

```bash
python scripts/update_history.py --append
```

It appends today's record to the detailed window, promotes/updates named threads, and
rolls episodes older than 30 days into the long-term summary (entities roster + monthly
milestone rollup), keeping the file bounded. Safe to re-run.

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
