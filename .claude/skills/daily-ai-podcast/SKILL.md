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

Turn the last ~24–48 hours of AI activity into an **18–22 minute**, two-host audio
briefing (~150 wpm spoken).

The pipeline is deliberately split by *how a source is gathered*, not how important it
is. **Deterministic Python** (step 1) pulls every watchlist source with a clean machine
feed — RSS and APIs. A **crawl subagent** (step 2) handles the watchlist's HTML-only
sources, which need a browser. **You, the main agent** (step 3), are the editor-in-chief:
you see everything both steps gathered, decide what the show is about, verify it, and
write the script. Importance is judged in step 3 and nowhere else.

## Workflow

Run these steps in order. Do not skip the grounding rules in step 3.

### 1. Pull the structured sources
Run the fetcher. It writes `out/sources.json` and prints a summary.

```bash
python scripts/fetch_sources.py --hours 48 --out out/sources.json
```

It reads `config/sources.yaml` and deterministically pulls **every Tier-1 source whose
method is `rss` or `api`** — arXiv, Hugging Face Daily Papers, and the lab/news/newsletter
feeds. Output is a `feeds` object keyed by source name; **every item carries the `source`
it came from**, so when the same story appears across several feeds you can see that. If
a single source fails or returns nothing in the window, the script keeps going and notes
it — read the printed summary and work with what you have.

### 1.5. Recall what the show has already covered
Read `history.json` if it exists. It is the show's memory — treat it the way a regular
host remembers their own past episodes, **not** as a script of callbacks:
- `episodes` — the last ~30 days in detail (title, summary, topics, entities, threads).
- `longterm` — older context: `active_threads` (named multi-day storylines with their
  status/arc), an `entities` roster, and a `monthly` rollup of major milestones.

Use it to inform, not to perform:
- **Don't re-explain what you've already established.** If you introduced a model, a
  paper, or a company recently, assume the listener has the background — cover today's
  development, not the backstory again.
- **Suppress true repeats.** A story already covered, with nothing new, doesn't run
  again — when it has moved, cover the *update*, not the original news. You apply this in
  step 3 when you select what goes in the show (there's a repeat-check there); keep it in
  mind as you read the memory now.
- **Pick up arcs naturally.** When today advances an ongoing thread, continue it the way
  a host naturally would — informed and current. A brief, earned reference to past
  coverage is fine **occasionally**, only when it adds something. Do not pepper the show
  with "as we discussed" callbacks; continuity should be felt, not announced. Most
  episodes need zero explicit callbacks.
- A topic only worth recalling is one still present in `history.json` (detail window or
  `longterm`). If it has fully aged out of memory, treat it as fresh.

### 2. Crawl the HTML sources with one subagent
The structured feeds (step 1) don't cover the watchlist's HTML-only sources — lab blogs,
release-note pages, leaderboards, news sections. These have no clean machine feed, so a
**single subagent** crawls them and returns a traceable candidate list. Spawn it with the
`Agent` tool. Read `config/sources.yaml` first and pass it **every source whose method is
`fetch`** (the HTML ones), Tier-1 and Tier-2 alike — the eval, governance, and
delivery sources the topic priorities care about mostly live in Tier-2. It may also
follow an obvious link to a primary source it finds on those pages. (Leaderboards and
slow-moving pages will often have nothing new — that's expected; the subagent just
reports what it finds.)

Give the subagent this brief, verbatim in spirit:

> Crawl each of these URLs (today and yesterday only). Return **every real AI-industry
> item** you find — a release, paper, benchmark result, partnership, price change, policy
> move, funding round, hire, outage, or similar concrete development. This is a *noise*
> filter, not an importance filter: **drop only** site boilerplate/navigation, pure
> marketing with no factual claim, and items clearly outside the last ~48h. **When unsure,
> include it** and say why you weren't sure. Do **not** judge whether an item is important
> enough for a show — that is decided downstream. For each item return JSON:
> `{ "sources": ["which watchlist source(s) it appeared on"], "url": "exact primary URL",
> "claims": ["the key factual claims, quoted or stated as the page had them — short, one
> or two sentences each, no paraphrase that changes meaning"], "summary": "1–2 line plain
> recap", "why_included": "one line; note here if you were unsure" }`. Keep quotes short.
> Return the JSON array as your final message and nothing else.

You'll merge this list with the step-1 feeds in step 3. Treat the subagent's `claims` as
leads you can cite or re-verify — it read the page so you don't have to re-read all of
them, but **anything you put in the script still follows the grounding rules** (verify at
the primary source when in doubt).

### 3. Select, verify, and write the script
Now you have everything: the step-1 `feeds` and the step-2 crawl list. **This is where
importance is judged.** Merge the two into one candidate set, decide what the show is
about using the topic priorities below, verify what you'll use, then write.

**Merge and de-duplicate.** The same story often appears across several feeds and on the
HTML sources — that multi-source pickup is a *signal of importance*, so note it rather
than discarding it. Collapse duplicates into one item, keeping the list of sources it
appeared on.

**Repeat-check against memory.** Before committing to an item, compare it to the
`history.json` memory you read in step 1.5. If it's clearly the same story you already
covered and nothing has moved (no new release, number, decision, or development), drop
it. If it might be an update — or you can't tell — verify; when confirmed, cover the
*update*, not the original news. When in doubt, keep it; never drop a real development
just because the topic is familiar.

**Verify what you'll use.** Every item that makes the show must trace to a primary source
you (or the step-2 subagent) actually read. Re-fetch with `WebFetch`/`WebSearch` when a
claim is load-bearing or you're unsure — don't take a number, date, or quote on faith.

**Topic prioritization (decide what the show is about).** Prioritize signal over noise.
Do not spend much time on stories that are interesting mainly because they are loud,
viral, speculative, or heavily marketed. Focus on developments that change how AI systems
are built, evaluated, deployed, governed, secured, priced, or adopted in real
organizations.

These six areas are **equally important — unranked.** Let the day's developments, not the
order below, decide what the show covers and how much.

- **Production AI Systems & Agentic Workflows** — the practical realities of deploying AI
  in enterprise, government, and consumer settings: agentic workflows, tool use,
  automation, human-in-the-loop oversight, context engineering, orchestration,
  observability, system integration, deployment patterns, operational lessons, and
  failures that show what separates durable AI systems from demos.
- **Retrieval, Document Intelligence & Knowledge Governance** — how AI systems find,
  structure, remember, govern, and reason over organizational and public knowledge: RAG,
  retrieval architectures, embeddings, reranking, document parsing, multimodal document
  understanding, unstructured-text workflows, knowledge graphs, enterprise memory,
  search, permissions, source freshness, data lineage, PII handling, synthetic data, and
  data-quality practices that make AI outputs more reliable and auditable.
- **AI Quality, Evaluation & Model Decision-Making** — how organizations determine whether
  AI systems are accurate, reliable, safe, and fit for purpose: LLM and agent evaluation,
  hallucination detection, claim verification, LLM-as-judge, benchmark design, model
  comparison, model selection, right-sizing, cost-performance tradeoffs, latency, small
  language models, quantization, routing, and evidence about which models work best for
  which tasks.
- **AI-Native Software Delivery & Engineering** — how organizations are moving from
  AI-assisted coding to agentic software development and AI-native delivery: coding
  agents, ticket-to-PR workflows, repo-level agent configuration, AI code review, test
  generation, CI repair, security controls, productivity metrics, engineering team
  structure, junior/senior role changes, project estimation, consulting delivery models,
  review burden, and evidence about how real teams are reorganizing work around AI.
- **AI Infrastructure, Local Deployment, Governance & Scaling Limits** — the
  infrastructure and governance realities that shape where and how AI runs: hardware
  releases, cloud and edge infrastructure, local LLM deployment, open-weight models,
  private inference, on-device AI, personal agents, chips, inference costs, energy
  constraints, data-center capacity, AI security, agent permissions, privacy, regulation,
  procurement, institutional risk, and the operational limits that determine whether AI
  can be deployed responsibly, affordably, and at scale.
- **Applied AI & Research Frontiers with Practical Signal** — research and applied
  breakthroughs that could matter within the next 12–36 months: world models, JEPA-style
  architectures, multimodal reasoning, geospatial AI, remote sensing,
  climate/conservation AI, Earth-observation foundation models, synthetic data,
  simulation, robotics, and other frontier work with plausible near-term product or
  public-sector relevance.

Write a two-host dialogue (`HOST_A`, `HOST_B`). Aim for **18–22 minutes**
(~2,700–3,300 words at ~150 wpm).

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

**Structure:** cold open (1 line on the day's through-line) → *(optional)* **Headlines**
→ **Papers** → **Releases / launches** → **Industry & news** → **One to watch** (1 item,
slightly deeper) → 20–30s wrap. Each middle segment carries ~2–3 items. Keep turns
short and conversational; alternate hosts. Spell out acronyms on first use. Avoid
reading URLs aloud.

**The Headlines segment** is the one place the loud/viral/marketed stories the topic
priorities de-emphasize get acknowledged — so the show isn't oblivious to what listeners
heard elsewhere — without dwelling on them. It is **optional and tightly capped**:
- Comes right after the cold open, before Papers. **Skip it entirely** if nothing
  qualifies.
- **At most ~5 items, one or two lines each**, no host back-and-forth — name it, say in a
  clause what it is, move on. It's a *mention, not coverage*.
- Only for **loud-but-thin** items. If a loud story also has real substance under the
  priorities, it belongs in its proper segment with full treatment, **not** here — never
  cover the same item in both.
- Same grounding rules apply: even a one-liner traces to a source.

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
  **Record only what the show actually covered in depth — exclude the Headlines
  one-liners.** A passing mention shouldn't enter memory, or it could later suppress the
  real story as a "repeat".

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
