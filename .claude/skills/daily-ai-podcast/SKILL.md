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
**~2,700–3,300 words** (the Gemini voices render that to roughly 20–26 minutes).

The pipeline is deliberately split by *how a source is gathered*, not how important it
is. **Deterministic Python** (step 1) pulls every watchlist source with a clean machine
feed — RSS and APIs. A **crawl subagent** (step 2) handles the watchlist's HTML-only
sources, which need a browser. **You, the main agent** (step 3), are the editor-in-chief:
you see everything both steps gathered, decide what the show is about, verify it, and
write the script. Importance is judged in step 3 and nowhere else.

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

**Rituals (light).** Open with the classic two-voice shape — date, names, then the
day's through-line: "Good morning — it's Friday, June twelfth. I'm Ada." / "And I'm
Alan. Here's what actually mattered in AI in the last twenty-four hours." (Vary the
wording naturally day to day; keep the shape.) Close every episode with the signature
sign-off — **"Stay grounded."** — alternating which host says it.

## Workflow

Run these steps in order. Do not skip the grounding rules in step 3.

### 1. Pull the structured sources
Run the fetcher. It writes `out/sources.json` and prints a summary.

```bash
python scripts/fetch_sources.py --hours 48 --out out/sources.json
```

It reads `config/sources.yaml` and deterministically pulls **every source whose method
is `rss` or `api`, both tiers** — arXiv (keyword-filtered to the topic priorities,
capped per query), Hugging Face Daily Papers, HN, and the lab/news/newsletter feeds.
Output is a `feeds` object keyed by source name; **every item carries the `source`
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
- **Read the hosts' `lore` too** (in episode records and `longterm.host_lore`): running
  bits that might return, and open positions that today's news may settle — see
  Continuity in the Hosts section. Same restraint as callbacks: use it only when earned.

### 2. Crawl the HTML sources with one subagent
The structured feeds (step 1) don't cover the watchlist's HTML-only sources — lab blogs,
release-note pages, leaderboards, news sections. These have no clean machine feed, so a
**single subagent** crawls them and returns a traceable candidate list. Spawn it with the
`Agent` tool as `subagent_type: source-crawler` (a Sonnet agent — its durable output
contract lives in `.claude/agents/source-crawler.md`).

Read `config/sources.yaml` first and pass the subagent, in the `prompt`, **every source
whose method is `fetch`** (the HTML ones), Tier-1 and Tier-2 alike — the eval, governance,
and delivery sources the topic priorities care about mostly live in Tier-2 — plus the date
window (today and yesterday only). Example prompt: *"Crawl these sources for {today} and
{yesterday} only: {labelled URL list}."* Add any per-run steering here (e.g. emphasis on a
particular beat) — it stacks on top of the saved contract. (Leaderboards and slow-moving
pages will often have nothing new — that's expected; the subagent just reports what it
finds.)

You'll merge this list with the step-1 feeds in step 3. Treat the subagent's `claims` as
leads you can cite or re-verify — it read the page so you don't have to re-read all of
them, but **anything you put in the script still follows the grounding rules** (verify at
the primary source when in doubt).

**Act on the failures.** A blocked source is a blind spot, not an empty source. For any
**Tier-1** source in `failures`, run a quick `WebSearch` (e.g. the lab's name + "announcement"
+ today's date) to check whether you missed something real; Tier-2 failures just get noted
in the step-5 report.

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
you (or the step-2 subagent) actually read. Don't take a number, date, or quote on faith.
**Load-bearing means:** any number, date, quote, or ranking; anything in the cold open;
and the lead claims of any full-treatment story. A truncated feed excerpt in
`sources.json` is a *lead*, not a read source — it supports at most a Headlines
one-liner; full treatment requires fetching the actual page.

Once you've chosen the stories, batch the load-bearing claims and hand them to the
`fact-checker` subagent (`Agent` tool, `subagent_type: fact-checker`, a Sonnet agent) —
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

Write the dialogue **in character** — Ada (`"A"`) and Alan (`"B"`) per the Hosts
section: story-by-story handoff, warm sparring, at most 1–2 AI-identity touches, lore
only when earned, the greeting and "Stay grounded." sign-off. Aim for
**~2,700–3,300 words**.

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

**Structure:** cold open (the greeting, then 1 line on the day's through-line) →
*(optional)* **Headlines** → **Papers** → **Releases / launches** → **Industry & news**
→ **One to watch** (1 item, slightly deeper) → 20–30s wrap + sign-off. The 5–7
full-treatment stories spread across the middle segments — let the day's material
decide how many land in each.

**Optional deep-dive segment.** Occasionally — when one of the day's items genuinely
merits it (a new architecture, an important technique, a debate worth unpacking) — replace
**One to watch** with a 3–4 minute deep dive that *teaches* the thing rather than just
reporting it. Use it sparingly, only when the material earns the time; the episode may run
up to ~25 minutes on those days. Same grounding rules apply.

**The Headlines segment** serves two purposes: it acknowledges the loud/viral/marketed
stories the topic priorities de-emphasize (so the show isn't oblivious to what listeners
heard elsewhere), and it's the **triage tier** for real-but-secondary items that didn't
make the 5–7 full-treatment cut. It is **optional and tightly capped**:
- Comes right after the cold open, before Papers. **Skip it entirely** if nothing
  qualifies.
- **At most ~6 items, one or two lines each**, no host back-and-forth — name it, say in a
  clause what it is, move on. It's a *mention, not coverage*.
- If a loud story also has real substance under the priorities, it belongs in its proper
  segment with full treatment, **not** here — never cover the same item in both.
- Same grounding rules apply: even a one-liner traces to a source.

Write **three** files:
- `out/episode.json` — the machine-readable script the renderer consumes. Schema:
  ```json
  { "date": "YYYY-MM-DD",
    "title": "string",
    "tts_notes": "OPTIONAL: 1-2 sentences of mood/tone direction (see above)",
    "turns": [ { "speaker": "A" | "B", "text": "one spoken line" } ] }
  ```
  Keep each turn's `text` plain spoken prose — no markdown, URLs, or stage
  directions. The **only** non-spoken text allowed is well-formed audio tags per the
  rules above.
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
                   "arc": "one line on how it has progressed" } ],
    "lore": [ { "host": "Ada" | "Alan",
                "type": "reveal" | "bit" | "position" | "settled",
                "note": "what is now canon, e.g. 'Alan revealed he runs weekend experiments on an ancient mining rig he refuses to replace'" } ] }
  ```
  Fill `threads` only for genuine multi-day storylines (a rollout, a lawsuit, a price
  war) — not one-off items. Reuse a thread's exact `name` from `history.json` when you're
  continuing one, so its arc accumulates instead of forking.
  Fill `lore` with what this episode added to the hosts' canon: a self-revelation or
  development of an established detail (`reveal` — the main event), a running bit worth
  returning to (`bit`), a genuine position a host staked out (`position`), or the
  settlement of one (`settled`). 0–2 entries; most episodes have 0. Routine banter and
  one-off jokes don't enter canon — only things that should still be true about this
  host next month.
  **Record only what the show actually covered in depth — exclude the Headlines
  one-liners.** A passing mention shouldn't enter memory, or it could later suppress the
  real story as a "repeat".

### 3.5. Validate the script before rendering
```bash
python scripts/check_episode.py --episode out/episode.json
```

This is a hard gate: it checks the schema, speaker values, the word-count band,
audio-tag form and density (~1 per 60 words max), and TTS-hostile artifacts
(markdown, URLs, embedded labels, malformed brackets). If it fails, **revise
`out/episode.json` and re-run it until it passes** — when under length, add or deepen
coverage from your candidate set; never pad with filler. (On a deep-dive day, pass the
wider band the deep-dive skill specifies.)

**Thin-day exception.** If the day is genuinely thin — you've deepened every story that
deserves it and promoting anything else would put noise in the show — run the gate with
`--min-words 2300` instead, and say so with one line of justification in the step-5
report. A shorter honest episode beats a padded one; never use the exception to avoid
the work of deepening real coverage.

### 4. Render the audio
```bash
python scripts/make_audio.py --episode out/episode.json --out "out/podcast-$(date +%F).mp3" --backend gemini
```

The show's voice **is** Gemini multi-speaker TTS (needs `GEMINI_API_KEY`; voices come
from `GEMINI_VOICE_A`/`GEMINI_VOICE_B` in `.env`). It performs the whole dialogue —
including audio tags and `tts_notes` — in NotebookLM style. The renderer retries each
chunk hard (5 attempts, ~10 min worst case) and then **fails; do not fall back to
another backend or re-render with `--backend kokoro`** — a flat-voiced episode must
never publish. If it fails, report the failure in step 5 and stop. (Kokoro exists in
the script for manual offline experiments only.)

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
anything that failed or any source gap (including step-2 crawl failures and whether the
thin-day exception was used, with its justification). Also list **which watchlist
sources contributed items that made the show** — over weeks this reveals which sources
earn their place in `sources.yaml`. If a downstream step (commit, upload, email) is
configured by the caller, that happens outside this skill — just produce the artifacts.

## Notes
- This skill produces files; it does not publish. Scheduling and delivery live in the
  caller (cron, a GitHub Actions workflow, or a Claude Code Routine) — see the README.
- If `out/` doesn't exist, create it.
- Tune the arXiv categories, the news source list, and the host personas to taste; they
  are meant to be edited.
