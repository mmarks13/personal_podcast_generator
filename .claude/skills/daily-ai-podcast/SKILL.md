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

Turn the last ~24–48 hours of AI activity into a two-host audio briefing of
**~3,300–3,600 words** (the Gemini voices render that at ~165–170 wpm to roughly 20–22
minutes).

The pipeline is deliberately split so the gathering and organizing happen in cheap
subagents and you spend your budget only on editorial judgment. **Deterministic Python**
(step 1) pulls every watchlist source with a clean machine feed — RSS and APIs. A **crawl
subagent** (step 2) handles the watchlist's HTML-only sources, which need a browser, and
writes `out/crawl.json`. A **consolidator subagent** (step 2.5) then reads both dumps,
de-duplicates and condenses them into one compact, organized candidate set
(`out/candidates.json`), flagging likely repeats along the way. **You, the main agent**
(step 3), are the editor-in-chief: you read only `out/candidates.json`, decide what the
show is about, deep-read and verify the stories you choose, and write the script. The
subagents only gather and organize — they never decide what's worth covering. Importance
is judged in step 3 and nowhere else.

## The hosts

The show is hosted by two AIs who know they're AIs:

- **Ada** (speaker `"A"`, the female voice) — a professor at MIT and the show's
  *computing historian*. She explains by lineage: she knows the path to how we got
  here and uses it to make today's development make sense ("word-at-a-time generation
  was a 2017 design choice, not a law of nature"). Her analogies are vivid and precise,
  and she's honest about where they break. Don't overplay either trait — history and
  analogy serve the explanation; they never replace it.
- **Alan** (speaker `"B"`, the male voice) — a professor at Berkeley and the show's
  *builder*, famous for packed, interactive lectures. His instinct on any story is
  hands-on: what happens when you actually run this, what does it cost, what breaks,
  what would he do with it tonight? He grounds Ada's elegance in deployment reality.

**Dynamic.** Warm colleagues with light wit — easy morning listening — who genuinely
push on each other's takes. They may disagree and leave it unresolved; friction is part
of the fun, but it's sparring between colleagues who respect each other, never
crossfire. **Story-by-story handoff:** whoever brings a story to the table leads it;
the other reacts, questions, and pushes.

**Being AIs.** A running self-aware thread, used sparingly — at most one or two touches
per episode, where their nature gives them a wry first-person stake in the news (a
hallucination benchmark, an agent run amok). **Fiction rules:** persona color is
*AI-life color only*. Riffs on their own existence — training, context windows, weekend
fine-tuning, the standing joke of "my students" — are fine. Never invent real-world
specifics: no fabricated colleagues, named students, or events at the real MIT or
Berkeley. Persona color must be obviously persona-shaped; every claim about the actual
news follows the grounding rules, full stop.

**Continuity — the characters are canon.** The hosts evolve the way real hosts do: over
months, listeners slowly learn who they are through small things they reveal about
themselves in passing — a habit, a preference, a weekend project, a sore spot, how they
feel about being what they are. `history.json` carries this as `lore` (in the episode
records and `longterm.host_lore`). Treat it as **canon**:
- **Once revealed, it's true.** Never contradict established lore; stay consistent with
  who they've turned out to be.
- **Reveal slowly.** A detail emerges naturally from the day's material — Alan's
  hardware habits surface because an open-weight release made him try something; Ada's
  fondness for old systems papers surfaces because today rhymed with one. Most episodes
  reveal nothing new, and that's right — an arc that accretes one small true thing a
  week feels real; one that lurches every episode feels written.
- **Build, don't repeat.** A returning detail should develop ("the mining rig finally
  died") rather than be restated. Running bits and genuine on-air positions are also
  lore — when later evidence settles a position, give it a brief moment — but they're
  the seasoning, not the arc.

Capture what this episode revealed or developed in `episode_meta.json`'s `lore` field
(schema below). Like callbacks, lore is felt, not performed.

**Rituals (light).** Open with the classic two-voice shape — date, names, then a single
line orienting the listener to the day: "Good morning — it's Friday, June twelfth. I'm
Ada." / "And I'm Alan. Here's what actually mattered in AI in the last twenty-four
hours." (Vary the wording naturally day to day; keep the shape.) If the day's stories
genuinely share a thread, that line is where to name it — but only when one is really
there. Most days are just several separate developments, and saying that plainly is
better than inventing a theme to tie them together. Close every episode with the
signature sign-off — **"Stay grounded."** — alternating which host says it.

## Workflow

Run these steps in order. Do not skip the grounding rules in step 3.

### 1. Pull the structured sources
The nightly harness (`run_episode.sh`) already cleared stale scratch and ran the
deterministic fetcher before invoking you, so **`out/sources.json` already exists — do
not run the fetcher.** It needs no judgment, so spending a turn on it is pure waste.
(Only if you were invoked manually and `out/sources.json` is missing should you run it
yourself: `.venv/bin/python scripts/fetch_sources.py --hours 48 --out out/sources.json`.)
You don't read this file directly anyway — the step-2.5 consolidator does.

`sources.json` is `config/sources.yaml`'s **rss/api sources, both tiers**, pulled
deterministically — arXiv (keyword-filtered to the topic priorities, capped per query),
Hugging Face Daily Papers, HN, and the lab/news/newsletter feeds. Output is a `feeds`
object keyed by source name; **every item carries the `source` it came from**, so a story
appearing across several feeds is visible. A source that failed or returned nothing is
simply absent — work with whatever is there. The harness also pre-cleared any stale
`out/crawl.json` / `out/candidates.json`, so don't second-guess leftover scratch.

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
- **Read the hosts' `lore` too** (in episode records and `longterm.host_lore`): running
  bits that might return, and open positions that today's news may settle — see
  Continuity in the Hosts section. Same restraint as callbacks: use it only when earned.

### 2. Crawl the HTML sources with one subagent
**If `out/crawl.json` already exists, the nightly harness pre-crawled — skip this step.**
(Only crawl yourself if invoked manually without a harness-built `out/crawl.json`.)

The structured feeds (step 1) don't cover the watchlist's HTML-only sources — lab blogs,
release-note pages, leaderboards, news sections. These have no clean machine feed, so a
**single subagent** crawls them and **writes a traceable candidate list to
`out/crawl.json`**. Spawn it with the `Agent` tool as `subagent_type: source-crawler` (a
Sonnet agent — its durable output contract lives in `.claude/agents/source-crawler.md`).
It doesn't depend on `out/sources.json`, so you can launch it alongside the step-1 fetcher.

Read `config/sources.yaml` first and pass the subagent, in the `prompt`, **every source
whose method is `fetch`** (the HTML ones), Tier-1 and Tier-2 alike — the eval, governance,
and delivery sources the topic priorities care about mostly live in Tier-2 — plus the date
window (today and yesterday only). **Label each URL with its tier**, so the subagent knows
which failures to chase. Example prompt: *"Crawl these sources for {today} and {yesterday}
only, writing out/crawl.json: {tier-labelled URL list}."* Add any per-run steering here
(e.g. emphasis on a particular beat) — it stacks on top of the saved contract.
(Leaderboards and slow-moving pages will often have nothing new — that's expected; the
subagent just reports what it finds.)

The crawler **self-recovers Tier-1 blind spots**: when a Tier-1 source fails to load it
runs a backup search itself, so `out/crawl.json` already folds in what it could recover
and records every failure (Tier-1 and Tier-2) for the step-5 report. You don't merge this
file yourself — the step-2.5 consolidator does. Its `claims` are leads you can cite or
re-verify in step 3, but **anything you put in the script still follows the grounding
rules** (verify at the primary source when in doubt).

### 2.5. Consolidate all sources into one candidate set
**If `out/candidates.json` already exists, the nightly harness pre-consolidated — skip
straight to step 3 and read it.** Building it pulls the raw dumps into your (Opus) context,
which is exactly what the harness moved out; only consolidate yourself if invoked manually
without a harness-built `out/candidates.json`.

Now both raw dumps exist — `out/sources.json` (structured feeds, large and repetitive
across feeds) and `out/crawl.json` (the HTML crawl). Reading them into your own context
is expensive and most of it never makes the show. Hand them to a **single subagent** to
merge and condense first. Spawn it with the `Agent` tool as
`subagent_type: source-consolidator` (a Sonnet agent; its durable contract lives in
`.claude/agents/source-consolidator.md`). It reads both files itself, collapses duplicates
across feeds *and* the crawl into one entry each (keeping the union of sources that carried
a story and a `source_count`), preserves the notability signals (HF upvotes, HN points)
and the crawl `claims`, drops only clearly off-topic noise, **flags likely repeats against
`history.json`**, and writes a compact `out/candidates.json`. It does **not** judge what's
show-worthy — that's yours in step 3. Run it once both `out/sources.json` and
`out/crawl.json` exist.

You read `out/candidates.json` in step 3 — not the raw dumps. The raw files stay on disk
if you ever need the fuller feed excerpt for a specific item.

### 3. Select, verify, and write the script
Now you have everything in one place: read `out/candidates.json` — the unified candidate
set, already de-duplicated across the feeds and the crawl, each entry carrying the sources
that ran it, a `source_count`, the notability signals, and (for crawl-origin items) the
`claims` the crawler read. **This is where importance is judged.** Decide what the show is
about using the topic priorities below, fetch the main source for the stories you'll
cover, then write. (For any item whose lead is too thin to judge, the fuller excerpt is
still in `out/sources.json` or `out/crawl.json` on disk.) That multi-source pickup,
captured in each entry's source list, is a *signal of importance* — weigh it, don't
discard it.

**Repeat-check against memory.** The consolidator has already flagged likely repeats
against `history.json` — a candidate that's a likely repeat carries a `possible_repeat`
(the matching episode plus a one-line why); items without that key aren't flagged. You
don't need to re-scan everything. For the items you actually intend to cover, if
`possible_repeat` is present, confirm it against the `history.json` memory you read in step
1.5: if it's clearly the same story and nothing has moved (no new release, number,
decision, or development), drop it; if it's an update — or you can't tell — verify, and
when confirmed cover the *update*, not the original news. An absent flag isn't a guarantee
— if your own read says an item is a stale repeat, drop it.
When in doubt, keep it; never drop a real development just because the topic is familiar.

**Verify what you'll use.** Every item that makes the show must trace to a primary source
you (or the step-2 subagent) actually read. Don't take a number, date, or quote on faith.
**Load-bearing means:** any number, date, quote, or ranking; anything in the cold open;
and the lead claims of any full-treatment story. A truncated feed excerpt in
`sources.json` is a *lead*, not a read source — it supports at most a Headlines
one-liner; full treatment requires fetching the actual page.

Once you've chosen the stories, batch the load-bearing claims and hand them to the
`fact-checker` subagent (`Agent` tool, `subagent_type: fact-checker`, `model: "haiku"`) —
pass each claim with the primary URL to check it against. It returns, per claim, a verdict
(`supported`/`contradicted`/`not_found`/`unreachable`) and the **verbatim quote** that
decides it. Only `supported` claims (with a real quote) go on air as stated; treat
`contradicted` by correcting to what the quote says, and `not_found`/`unreachable` by
re-checking yourself or dropping the claim. The quote is your evidence — grounding still
rests on you, the subagent just does the fetching. For a one-off claim mid-write it's fine
to `WebFetch` directly rather than spin up the subagent; use it for the batch.

**Depth over breadth.** Pick **5–7 stories for full treatment** — enough time each that
the hosts can explain, push, and land a "so what". Everything else that's real but
secondary goes to Headlines as a one-liner (it doubles as the triage tier, not just
viral-story containment). Ten shallow recaps is what every newsletter already does; the
full-treatment stories are the show.

**Watch for a breakout tool.** The community feeds (r/LocalLLaMA, Hacker News, TLDR AI)
regularly surface a new open-source repo that's gaining real traction. When one of them
**fills a genuine gap** — something practitioners couldn't easily do before, not just
another wrapper, demo, or tutorial collection — it's worth a mention woven into whichever
segment fits (a new inference runtime in Infrastructure, a coding agent in Software
Delivery). The bar is *usefulness*, not star count: stars are a hint that something landed,
but a repo earns airtime by being a real new capability, and you should be able to say in a
sentence what it lets someone do that they couldn't before. This is occasional, not a
fixture — most days nothing qualifies, and forcing a repo in when none stands out is worse
than skipping it. Same grounding rules apply: look at the repo before describing it; don't
state stars, authorship, or what it does on the strength of a feed headline alone.

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
  hallucination detection/mitigation, claim verification, LLM-as-judge, benchmark design, model
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

**Plan the episode before you write a line — in your head, not in a file.** Once you've
chosen and verified your 5–7 full-treatment stories, settle the shape first so the first
draft lands in-band and you don't write into a rewrite loop:
- **Running order and leads.** The stories in air order, which segment each lands in, and
  which host brings (and therefore leads) each one.
- **A per-segment word budget that errs slightly high.** Allocate the ~3,300–3,600-word
  target across the segments and **aim each allocation a touch high** so the natural draft
  lands at or above target on the first pass — no deepening needed. A typical split: cold
  open ~150, Headlines ~150 (only if it runs), each full-treatment story ~450–600
  depending on depth, the "one to watch" a touch more, wrap ~120. **Sum your allocations
  to ~3,600 (the top of the band), not to the 2,700 gate floor** — budgeting to the floor
  is exactly what forces the deepen-after-the-fact rewrites.
- This plan is a thinking step, not a deliverable: **do not write an `episode_plan.md`.**

Then write the dialogue **in character** — Ada (`"A"`) and Alan (`"B"`) per the Hosts
section: story-by-story handoff, warm sparring, at most 1–2 AI-identity touches, lore
only when earned, the greeting and "Stay grounded." sign-off. Write each segment to its
planned budget so the whole lands at **~3,300–3,600 words** (below ~3,300 the episode
risks landing under 20 minutes).

**Grounding rules (these are the point of the whole exercise):**
- Every factual claim must trace to your gathered material (`out/candidates.json`, or the
  fuller `out/sources.json` / `out/crawl.json` on disk) or a page you actually fetched. If
  you didn't read it, don't say it.
- Do **not** invent benchmark numbers, author names, dates, funding figures, or quotes.
  If a detail isn't in your gathered material, omit it or say it's unconfirmed.
- Distinguish *what a paper claims* from *what is established*. "The authors report…"
  not "this proves…".
- No hype adjectives standing in for facts ("revolutionary", "game-changing"). Describe
  what changed and why it might matter, concretely.
- When two sources conflict, say so briefly rather than picking one silently.
- **Attribute on air.** Load-bearing claims name their source in the dialogue itself
  ("LWN reports…", "according to the AWS announcement…", "the authors report…") — the
  show notes carry the links, but the listener should hear where a claim comes from.

**Write for the ear.** The renderer reads the text literally:
- Numbers as speakable words: "twenty-six billion parameters", "about one point three
  trillion dollars" — approximate big figures rather than reading digit strings.
- Say model and product names the way a person would ("DiffusionGemma", "oh-four mini",
  not raw version strings like "26B-A4B").
- Spell out acronyms on first use. No URLs aloud. No parenthetical asides — if it
  matters, say it as its own sentence; if not, cut it.
- Keep turns short and conversational — a question, a pushback, a handoff — not
  alternating monologues.

**Write it as a conversation, not alternating essays.** The renderer (Gemini
multi-speaker TTS) performs both hosts in one pass and reacts to how the dialogue is
*written* — give it dialogue worth performing:
- **Backchannels and short reactive turns.** "Right.", "Wait, really?", "Huh — okay."
  A turn can be three words. Let one host react before the other finishes a thought's
  arc; the reaction is content.
- **Mid-thought handoffs.** Sometimes one host sets up and the other lands it, or one
  trails off ("...which is exactly the problem—") and the other picks it up. Use
  sparingly; once or twice a segment is plenty.
- **Friction stays unresolved sometimes.** Per the Hosts section, they can disagree and
  move on — don't write a tidy concession into every dispute.
- **React first, then explain.** A genuine "that number surprised me" before the
  analysis beats launching straight into the analysis.

**Audio tags (delivery directions).** Turn text may include short bracketed tags the
renderer performs instead of reading: `[laughs]`, `[chuckles]`, `[sighs]`,
`[short pause]`, emotion shifts like `[skeptical]` or `[excited]` at a phrase, and
creative ones where the moment earns it (the TTS prompting guide encourages
experimenting). Rules:
- Tags are **seasoning**: most turns need none; the writing carries the emotion and a
  tag amplifies it. The gate fails the script above ~1 tag per 60 words.
- Form: lowercase, short (a few words), square brackets. Anything else in brackets
  fails the gate.
- Never use tags as content ("[laughs]" is not a reply) and never for sound effects —
  this is a news show, not a radio drama.

**Per-episode delivery note (optional).** When the day's material warrants a departure
from the show's default warm energy — a somber lead story, an unusually celebratory
release day — set `tts_notes` in `episode.json` to 1–2 sentences of mood/tone
direction for the voices (e.g. "Measured, sober energy today; the lead story is a
safety incident. Lighten up by the Releases segment."). It steers delivery only, not
content. Most days, omit it.

**Structure:** cold open (the greeting, then a line orienting the listener to the day —
name a through-line only if one genuinely fits) →
*(optional)* **Headlines** → **Papers** → **Releases / launches** → **Industry & news**
→ **One to watch** (1 item, slightly deeper) → 20–30s wrap + sign-off. The 5–7
full-treatment stories spread across the middle segments — let the day's material
decide how many land in each.

**Explain, don't just report.** The point of giving a story full treatment isn't to
relay that something happened — it's to leave the listener actually understanding it.
When a story turns on a concept the audience may not already hold — why a technique
works, what a number really measures, where an approach breaks — it's worth taking a
minute or two inside that story to teach the idea before moving on. This isn't a separate
segment; it's the story going one level deeper because understanding it requires that. Do
it when the material earns it; skip it when the story speaks for itself. The grounding
rules apply to the explanation exactly as to the reporting.

**Optional full deep-dive segment.** (~1-2 times/week), a single item merits more than that
in-story minute or two — a genuinely new architecture, an architecture that is showing up often in the literature, a prescient history lesson, an important technique, a debate
worth unpacking properly. Then it's worth adding a 3–4 minute
deep dive that *teaches* the thing end to end. Use it only when the material
earns the time; the episode may run up to ~25 minutes on those days. Same grounding rules
apply.

**The Headlines segment** serves two purposes: it acknowledges the loud/viral/marketed
stories the topic priorities de-emphasize (so the show isn't oblivious to what listeners
heard elsewhere), and it's the **triage tier** for real-but-secondary items that didn't
make the 5–7 full-treatment cut. It is **optional and tightly capped**:
- Comes right after the cold open, before Papers. **Skip it entirely** if nothing
  qualifies.
- **At most ~6 items, 1-4 lines each**, no host back-and-forth — name it, say in a
  clause what it is, move on. It's a *mention, not coverage*.
- If a loud story also has real substance under the priorities, it belongs in its proper
  segment with full treatment, **not** here — never cover the same item in both.
- Same grounding rules apply: even a one-liner traces to a source.

You author **two** files; a deterministic build step (step 3.5) turns them into the
machine files the pipeline consumes (`episode.json`, `shownotes.md`), so you never
hand-write JSON dialogue or escape quotes.

- `out/script.txt` — the spoken script as **plain text**: one turn per line, each line
  starting with the speaker tag `A:` (Ada) or `B:` (Alan), then that turn's spoken words.
  No JSON, no quoting, no brackets to escape — just dialogue, e.g.:
  ```
  A: Good morning — it's Friday, June twentieth. I'm Ada.
  B: And I'm Alan. Here's what actually mattered in AI in the last twenty-four hours.
  A: [wry] Starting, of course, with another hallucination benchmark.
  ```
  Keep each line plain spoken prose; the **only** non-spoken text allowed is well-formed
  audio tags per the rules above. No markdown, URLs, or stage directions. A line with no
  speaker tag is folded into the turn above it (so a wrapped line is fine), but the natural
  form is one turn per line.
- `out/episode_meta.json` — everything *about* the episode: the memory record for
  `history.json` (step 4 update), plus the show-notes data and any delivery note. Schema:
  ```json
  { "date": "YYYY-MM-DD",
    "title": "string",
    "summary": "1–2 sentence recap of the episode",
    "tts_notes": "OPTIONAL: 1-2 sentences of mood/tone direction (see above); omit most days",
    "sources": [ { "group": "Papers" | "Releases" | "Discussion",
                   "title": "source title", "url": "https://…" } ],
    "topics":   ["short topic/story labels covered today"],
    "entities": ["orgs/models/people featured today, e.g. Anthropic, Gemini 3"],
    "threads": [ { "name": "ongoing storyline",
                   "status": "where it stands now",
                   "arc": "one line on how it has progressed" } ],
    "lore": [ { "host": "Ada" | "Alan",
                "type": "reveal" | "bit" | "position" | "settled",
                "note": "what is now canon, e.g. 'Alan revealed he runs weekend experiments on an ancient mining rig he refuses to replace'" } ] }
  ```
  - `sources` — every source you used, each tagged with the show-notes group it belongs
    under (Papers / Releases / Discussion). This becomes `shownotes.md`; an entry with no
    `url` is skipped.
  - `tts_notes` — the optional per-episode delivery note (see above); omit it most days.
  - Fill `threads` only for genuine multi-day storylines (a rollout, a lawsuit, a price
    war) — not one-off items. Reuse a thread's exact `name` from `history.json` when you're
    continuing one, so its arc accumulates instead of forking.
  - Fill `lore` with what this episode added to the hosts' canon: a self-revelation or
    development of an established detail (`reveal` — the main event), a running bit worth
    returning to (`bit`), a genuine position a host staked out (`position`), or the
    settlement of one (`settled`). 0–2 entries; most episodes have 0. Routine banter and
    one-off jokes don't enter canon — only things that should still be true about this
    host next month.
  - **Record in `topics`/`entities`/`threads`/`lore` only what the show actually covered in
    depth — exclude the Headlines one-liners.** A passing mention shouldn't enter memory, or
    it could later suppress the real story as a "repeat". (`sources` is the exception — list
    every source, including those behind a Headlines one-liner.)

**Write each file once, then `Edit`.** Draft the whole episode to your per-segment budget
and write `out/script.txt` and `out/episode_meta.json` a **single** time each, then build
and validate below. After that, fix anything with `Edit` **on these two source files** —
not on the generated `episode.json`/`shownotes.md`, which the build step overwrites — and
**never re-`Write` a whole file.** A full rewrite re-emits thousands of tokens to change a
few lines; targeted edits are how you handle a gate failure or a grounding correction.

### 3.5. Build and validate the script before rendering
First convert your two authored files into the machine files deterministically:
```bash
.venv/bin/python scripts/build_episode.py
```
This parses `out/script.txt` into turns (folding in `tts_notes`) and renders
`out/shownotes.md` from the summary and `sources`, writing `out/episode.json` and
`out/shownotes.md`. If it reports an error — a line before the first speaker tag, a missing
`date`/`title` — fix the source file and re-run; that reliability is the point of authoring
plain text. Then run the hard gate on the built episode:
```bash
.venv/bin/python scripts/check_episode.py --episode out/episode.json
```

This is a hard gate: it checks the schema, speaker values, the word-count band (floor
2,700, cap 3,900), audio-tag form and density (~1 per 60 words max), and TTS-hostile
artifacts (markdown, URLs, embedded labels, malformed brackets).

**If the gate passes, you're done — don't chase the upper target.** The per-segment budget
above is built to err high so the first draft clears the band on its own; a draft anywhere
from ~3,300 up is on target, and being a few hundred words under your ideal is **not** a
reason to run deepening edits. Revise only when the gate actually **fails**: under the
floor, deepen a real story from your candidate set (never pad with filler); over the cap,
tighten. Make every such revision by `Edit`ing `out/script.txt` (or `episode_meta.json`)
and re-running `build_episode.py` then the gate — never by rewriting a whole file. (On a
deep-dive day, pass the wider band the deep-dive skill specifies.)

**Thin-day exception.** If the day is genuinely thin — you've deepened every story that
deserves it and promoting anything else would put noise in the show — run the gate with
`--min-words 2300` instead, and say so with one line of justification in the step-5
report. A shorter honest episode beats a padded one; never use the exception to avoid
the work of deepening real coverage.

### 4. Report and stop
Print the episode title, the word count, and a one-line note on anything that failed or
any source gap (including the crawl failures carried in `out/candidates.json`'s
`crawl_failures` — Tier-1 ones the crawler already tried to recover — and whether the
thin-day exception was used). Also list **which watchlist sources contributed items that
made the show** — over weeks this reveals which sources earn their place in `sources.yaml`.

**Stop here.** The harness (`run_episode.sh`) updates `history.json` and renders the
audio after you exit — do not run `make_audio.py` or `update_history.py` yourself.

## Notes
- This skill produces files; it does not publish. Scheduling and delivery live in the
  caller (cron, a GitHub Actions workflow, or a Claude Code Routine) — see the README.
- If `out/` doesn't exist, create it.
- Tune the arXiv categories, the news source list, and the host personas to taste; they
  are meant to be edited.
