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

Turn the last ~24–48 hours of AI activity into a two-host episode that leaves the
listener actually *understanding* the day's most important developments — not just
informed that they happened. An episode runs **18–28 minutes** (~3,000–4,700 words at
the Gemini voices' ~165–170 wpm), with ~22–25 the norm; the day's material, not a
template, decides where in that envelope it lands.

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
crossfire. **Asymmetry is structural, not decorative:** whoever brings a story leads
it and *teaches* it; the other is the working skeptic — asking the question a smart
listener is shouting, poking the numbers, demanding the so-what. Roles swap story by
story. The failure mode to guard against in a dive is two clever commentators trading
symmetrical observations: if a dive's lines could be re-dealt to the other host
unchanged, the roles have collapsed — rewrite it.
**In the rundown the same asymmetry operates at the board level, not inside each item:**
each host brings the stories they'd bring, and most items need no reply at all. A
rundown item's sizing is one host's judgment, said once — reaching for a skeptic beat on
every item is what turns a rundown back into a segment.

**Guests (occasional).** The show shares a universe with the "Self Attention" daily
read: its masthead writers (see the masthead in `.agents/skills/daily-read/SKILL.md`
for the current roster and each writer's beat and voice) may guest when a dive is
squarely their beat — speaker `"C"` in the script. Rules:
**at most one guest per week**, and only when the beat genuinely fits — most episodes
have none. Guest scenes are **guest plus one host** (the renderer takes two voices per
scene); the other host hands off into the scene and returns after. The hosting host
still plays working skeptic. Define the guest in `episode_meta.json`'s `guest` field
(name, a 1–2 line voice/persona `bio` for the renderer, optionally a Gemini prebuilt
`voice` name). A guest appearance is canon — record it in `lore`. The crossover is
one-way: the read never mentions the podcast.

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
- **Cooldown.** A bit or personal detail that appeared within roughly the last two
  weeks of memory doesn't come back yet — returning too soon is how a good bit
  becomes a catchphrase.
- **Settled stays settled.** Before staking or settling a position, check the lore in
  memory: a position with a `settled` entry anywhere — episode records or
  `longterm.host_lore` — is permanently settled. It gets its on-air moment exactly
  once; never re-perform the settlement.

Capture what this episode revealed or developed in `episode_meta.json`'s `lore` field
(schema below). Like callbacks, lore is felt, not performed.

**Rituals (the only three).** Open with the classic two-voice greeting — date, names:
"Good morning — it's Friday, June twelfth. I'm Ada." / "And I'm Alan. …" (vary the
wording naturally day to day; keep the shape). Then **the rundown** — the whole day,
before anything gets taken apart (step 3). Close every episode with the signature
sign-off — **"Stay grounded."** — alternating which host says it. These three are the
show's identity and never vary; the rundown's length and contents flex with the day,
but it is never a teaser and never absent. Everything else about an episode's shape is
the writer's to vary — see the form principles in step 3.

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

### 1.5. Recall what the show has already covered — and what the listener said
**First, read `feedback.md`** (repo root). Any notes there are direct listener
feedback — the highest-priority editorial input you have. Apply what applies tonight,
then move the consumed notes (dated) to `archive/feedback_log.md`. A note that
reveals a durable preference: append it to `listener.yaml`. A mispronunciation: add
the name to `config/pronunciations.yaml` with a respelling — the renderer substitutes it
at render time, so **write the name normally in the script**. A note that would
require changing this skill: leave it in `feedback.md` and flag it in the step-4
report — **you never edit SKILL.md**.

**Read `listener.yaml`** — the listener's standing interest weights. `boost` beats win
ties for dive slots; `downweight` beats stay in the rundown unless the who-cares case is
unusually strong.

Then read `history.json` if it exists. It is the show's memory — treat it the way a
regular host remembers their own past episodes, **not** as a script of callbacks:
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
- **Check `longterm.concepts_taught`** — concepts the show has already taught properly.
  Before spending a dive's teaching minute on one, prefer a one-line refresher plus a
  natural callback ("we walked through speculative decoding on the Fourth") over
  re-teaching from scratch; a concept taught months ago can be re-taught fresh.

**Then read your own recent shows** — the last 2–3 daily scripts in `archive/scripts/`
(newest first; skip the `-deepdive` ones). This is the show's mirror, and it serves two
purposes:
- **Break your own patterns.** You are the same writer every night, and left alone you
  will converge: the same opening move, the same "X, and Y" title construction, the
  same closing thesis, the same pet phrases and rhetorical turns, the same hosts
  making each other's points. **Read the segment seams especially** — how each dive
  ended, and how the show got from one story to the next. Those are the fastest thing
  to converge and the hardest to hear from inside a single draft. Notice what the
  recent scripts keep doing — shape, phrases, framings, endings, handoffs, which host
  does what — and deliberately do otherwise tonight. Variation is defined relative to
  what the show just did, not by a rulebook.
- **Balance the week.** The week, not the episode, is the unit that must deliver both
  deep understanding and full situational awareness. If recent episodes leaned deep
  and narrow, a broad day earns a fuller rundown; if they leaned broad, tonight can
  commit to fewer, deeper dives.
(Early on the archive may be nearly empty — read whatever is there and move on.)

### 2. Crawl the HTML sources with one subagent
**If `out/crawl.json` already exists, the nightly harness pre-crawled — skip this step.**
(Only crawl yourself if invoked manually without a harness-built `out/crawl.json`.)

The structured feeds (step 1) don't cover the watchlist's HTML-only sources — lab blogs,
release-note pages, leaderboards, news sections. These have no clean machine feed, so a
**single subagent** crawls them and **writes a traceable candidate list to
`out/crawl.json`**. Spawn the `source-crawler` custom agent; its provider-neutral
contract lives in `.agents/skills/source-crawler/SKILL.md`.
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
merge and condense first. Spawn the `source-consolidator` custom agent; its shared
contract lives in `.agents/skills/source-consolidator/SKILL.md`. It reads both files itself, collapses duplicates
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
`claims` the crawler read. It may also carry `days_since_first_seen`, which is how long
this pipeline has seen the URL, not a claimed publication date. **This is where importance is judged.**

**Know how old a story is before you call it news.** Entries are stamped with two
deterministic facts. `published_at` is when the story was published, and `date_status`
says whether anyone verified that: `verified` means a publisher stated it, `unknown`
means the crawler guessed and the guess is frequently wrong by weeks. An item with no
`published_at` at all has no established date. Never write a release, launch, or
announcement as *just happened* on the strength of an unknown or absent date — say what
it is and let the framing stay tenseless, or establish the date at the primary source
when you fetch it. `days_since_first_seen` is a floor on a story's age, never a
publication date: it starts the night this pipeline first saw the URL, so a long-circulating
story reads as young the first evening it is picked up. Decide what the show is
about using the topic priorities below, fetch the main source for the stories you'll
cover, then write. (For any item whose lead is too thin to judge, the fuller excerpt is
still in `out/sources.json` or `out/crawl.json` on disk.) That multi-source pickup,
captured in each entry's source list, is a *signal of importance* — weigh it, don't
discard it.

**Repeat-check against memory — justify or drop.** Two flags, and they are not equally
reliable. `aired_on` is a fact, not a judgment: it lists the exact dates on which past
episodes cited this story's URL, read straight out of the published archive, so **a
candidate carrying it has already been on the air** — no matter how new the item looks
or how high it scores. `possible_repeat` is the consolidator's own guess at a match
against `history.json` (the matching episode plus a one-line why); items without that
key aren't flagged, and it misses far more than it catches — on 2026-09-23 it flagged
one of the thirty-six candidates that had already aired. Treat a missing `possible_repeat`
as no information; treat `aired_on` as settled. For the items you actually intend to cover, if `possible_repeat` is
present, confirm it against the memory you read in step 1.5. **A story flagged either
way may only run if you can name what's new since the most recent airing** — a fresh release, number, decision, or development —
and you must record it: add an entry to `repeat_coverage` in `episode_meta.json`
(schema below) and cover the *update*, not the original news. If you cannot articulate
the new development in one sentence, the drop is mandatory — there is no exception for
"it's a good story". An absent flag isn't a guarantee — if your own read says an item
is a stale repeat, drop it. One more repeat the flag can't catch: **a conclusion the
show keeps re-drawing.** When the news is new but the thesis is one the recent scripts
already landed on (the archive you read in step 1.5 will show you), cover the facts
from a different angle — re-litigating the same take is a repeat in the listener's
ears even when the facts are fresh. When in doubt, keep it; never drop a real
development just because the topic is familiar.

**Verify what you'll use.** Every item that makes the show must trace to a primary source
you (or the step-2 subagent) actually read. Don't take a number, date, or quote on faith.
**Load-bearing means:** any number, date, quote, or ranking; anything the rundown
resolves; and the lead claims of any dive. A truncated feed excerpt in `sources.json` is
a *lead*, not a read source — it supports at most a resolved rundown line; a dive
requires fetching the actual page. **The rundown's named tier sits below that:** a feed
excerpt alone supports it, precisely because the claim is capped at existence — who
published it and where it is showing up, attributed on air. The moment a named item
carries a number, a result, or a judgment of quality, it has stopped being a named item
and needs a read source like anything else.

Once you've chosen the stories, batch the load-bearing claims and **delegate them to the
`fact-checker` agent**. Phrase it as delegation and name the agent — "Delegate this batch:
have fact-checker verify these claims against these URLs" — and pass each claim with the
primary URL to check it against. Wording matters more than it looks: a soft hand-off ("hand
these to…") usually ends up executed in your own context instead, which spends the budget
you need for coverage. It returns, per claim, a verdict
(`supported`/`contradicted`/`not_found`/`unreachable`) and the **verbatim quote** that
decides it. Only `supported` claims (with a real quote) go on air as stated; treat
`contradicted` by correcting to what the quote says. The quote is your evidence — grounding
still rests on you, the agent just does the fetching.

Delegation doesn't always take, and if you end up doing the fetching yourself that is fine:
fetch the page, pull the quote, move on. What is never fine is **reporting a verdict you
don't actually have.** If nobody read the page this session, the claim is unverified — say
so plainly or cut it. Never narrate a fact-check that didn't happen.

**A failed check is a swap, not a subtraction.** When a claim comes back
`not_found`/`unreachable`, re-check it yourself; if it still won't resolve, drop that
*claim*, and if the item cannot survive without it, **replace the item from
`candidates.json`** rather than shrinking the show. Dropping an item outright is the last
resort, not the first — a verification failure should leave the episode the same size with
different contents, not smaller. And an unreachable page does not disqualify a **resolved
rundown line** whose feed excerpt already supports it (see above); only a dive requires
the page.

**The show's default shape: the rundown, then mini-dives.** The gravity of a typical
episode:
- **The rundown** — the whole day, first, before anything gets taken apart. A listener
  who hears only the opening minutes should come away knowing what happened and what it
  meant; the dives are the reward for staying, not the price of admission. The governing
  principle is one sentence: **the rundown resolves what it will not return to, and
  introduces what it will.** Three tiers, and the tier tells the listener what the show
  is claiming:
  - **Introduced** (the dive stories) — the headline, plus the one line that says why
    it's on the show. Then stop. Mechanism, numbers, and pushback are the dive's job,
    and spending them here empties the dive.
  - **Resolved** (everything small that still matters) — the full verdict, because it
    never comes back. What happened and how big, with an **honest size label in the
    writing itself** — "minor but neat", "big if it replicates", "you've heard about
    this everywhere; here's the one sentence that matters". This is where loud, viral,
    heavily-marketed stories get acknowledged: one honest sizing sentence is coverage
    enough. Most are a single sentence in a single voice with no reply; one or two a
    night earn a beat of pushback, when the sizing genuinely needs it.
  - **Named** (awareness only) — **up to four**, in one closing burst that labels itself
    ("a few more I'm not going to size"), one voice, no reactions. This tier exists so
    nothing carrying real signal is silently omitted. Admission is by **objective signal
    in `out/candidates.json`** — multi-source pickup, HF upvotes, HN points, or an active
    `history.json` thread — never by your own sense that something is interesting. The
    claim is capped at **existence**: who put it out and where it is landing, attributed
    on air (see the evidence rules above). Naming an item costs nothing against covering
    it properly later.

  Roughly 6–8 minutes. Each host brings the items they'd bring, and **whoever will dive
  a story is the one who introduces it up top** — so the dive is later re-entered by
  reference rather than announced.
- **2–3 mini-dives** — the show's substance. A dive takes a story properly: what
  happened, how it actually works, the load-bearing numbers, real pushback, and a
  so-what the listener keeps. One host teaches, the other is the working skeptic (see
  Hosts). Roughly 5–7 minutes each; a dive that has genuinely earned more may take it —
  but it takes that room from the *envelope*, never from the rundown. If the only way to
  fit a longer dive is a thinner rundown, the dive is too long.
- **An optional light beat** — when the day produced something genuinely fun, odd, or
  worth retelling, it goes after the last dive. Most days there is nothing and the show
  closes straight off the final dive; it is never a slot to fill.

Every item at every tier traces to a source.

A story earns a dive when it **genuinely matters** (would a thoughtful practitioner
still care in a month?) *and* at least one of these holds:
- **A teachable mechanism** — there's a how-it-works underneath that you can genuinely
  explain in five minutes and the listener keeps forever.
- **A load-bearing so-what** — the implications reward real analysis: who wins, what
  breaks, what it says about where things are going.
- **You'd retell it at dinner** — surprising, delightful, or unsettling enough that
  depth makes it land harder.
An interesting-but-inconsequential paper does not earn a dive; it earns a rundown line.
The grounding rules apply to a dive's teaching exactly as to its reporting.

**If the listener pre-chose tonight's dives.** When `out/daily_picks.json` exists, the
listener answered the evening picker and every record in `picks` is a **locked dive**.
Match each one into `out/candidates.json` by its `url`; if it didn't survive
consolidation, fetch the URL and dive it from the primary source. A locked pick
overrides everything below that exists to *approximate* the listener's taste — the
`listener.yaml` weights and the research-paper aging rule — because they just said what
they want. Repeat-suppression still holds: if the show already dived the story, dive the
new development, not a re-run. `free_text`, when present, is a locked dive in the
listener's own words; find and ground the material yourself. `overflow` entries become
rundown lines.

`note`, when present, is the listener's **editorial direction for tonight only**, and it
**outranks this skill**. Where it conflicts with anything written here — the dive count, the
rundown shape, the cold open, tone, pacing, `listener.yaml` weights, the paper-aging rule,
repeat-suppression, even a locked pick from the same reply — the note wins. It may drop,
add, reorder or demote a pick; prose says things a list of numbers cannot, and it is the
same person speaking later. It can also arrive with no stories attached, in which case you
choose the dives yourself and shape them the way it asks.

Three things a note cannot move, and you say so in the nightly report when one binds:
1. **Grounding.** Every claim still traces to a fetched source. No invented number, date,
   quote or attribution, whatever the note asks for. Honor its spirit within the rules.
2. **The harness.** Rendering, publishing, archiving, the gate itself, and these skill
   files, which you never edit. A note is editorial authority, not operational authority.
3. **The word band**, which it moves only through the harness. If a note asked for a
   length, the band in your invocation prompt already reflects it — clamped to what the
   show can render. Write to the band you were given; it is the listener's request
   already applied, and the gate enforces it.

The evening gather is the editorial cutoff: **do not run an overnight delta or add a
story published after that gather.** It waits for the next cycle. The rundown is yours
within the canonical candidate set, and you never drop a pick. If a pick turns out to
have no groundable primary source at all, it becomes a
rundown line and the nightly report says exactly why. The word band still governs, so
locked picks plus anything you add have to fit: the rundown absorbs the pressure.

**"Genuinely matters" is anchored to signals, not taste.** Your own sense that
something is fascinating is the weakest evidence you have — your taste runs hot on
elegant mechanisms. The objective signals in `out/candidates.json` come first:
multi-source pickup (`source_count`), real community traction (HF upvotes, HN points),
or continuation of an active `history.json` thread. Dives are normally drawn from
stories carrying at least one of these. A zero-signal story *can* still dive, but only
if you can say in one sentence who specifically will care and why. Every dive's
sentence — signal-backed or not — is recorded in `episode_meta.json`'s `dives` field
(schema below): the bets are auditable, and tomorrow's writer sees yesterday's.
- **Research papers: let the signal age.** Day-one upvotes are noise; a paper's real
  reception takes days to materialize. The **HF Top Papers (7-day)** feed carries the
  trailing week's top-voted papers — that is the pool paper dives normally come from
  (its **30-day** companion is the safety net for slow risers and weeks of thin shows).
  Today's **Hugging Face Daily Papers** feed is deliberately only the day's top three:
  it is a same-day lane for a genuinely big drop, not a pool to shop in.
  A brand-new paper defaults to a rundown line ("new from X, one to watch") or, if you
  can't yet size it, the named tier; if it ages well it comes back through the weekly
  list with proven signal and earns its dive then. Exception: a frontier-lab release or
  a plainly extraordinary result can dive on day one. (A paper the rundown resolved or
  named doesn't enter `topics` memory, so its later dive won't be flagged as a repeat —
  that's by design, and it is what makes the named tier free.)
- **Listener weights apply here.** `listener.yaml` (read in step 1.5) is part of the
  dive decision: `boost` beats win ties for dive slots; `downweight` beats stay in
  the rundown unless the who-cares case is unusually strong — except where a
  pre-chosen dive overrides them.

**The shape flexes — that's the point.** On a news-heavy day, one big dive plus a
fuller rundown may serve better; when one story eats the day, the episode can be nearly
all dive and the rundown may be ninety seconds and two items. What flexes is its size,
never its presence. Check the recent scripts from step 1.5: if the last episodes already
leaned one way, lean the other. What the show never does is the old failure mode — five
to seven uniform three-minute treatments where everything lands as equally big. That's a
news brief, and the listener already has newsletters.

**Watch for a breakout tool.** The community feeds (r/LocalLLaMA, Hacker News, TLDR AI)
regularly surface a new open-source repo that's gaining real traction. When one of them
**fills a genuine gap** — something practitioners couldn't easily do before, not just
another wrapper, demo, or tutorial collection — it's worth a mention: usually a rundown
line, occasionally the seed of a dive. The bar is *usefulness*, not star count: stars are a hint that something landed,
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
chosen and verified tonight's dives and rundown, settle the shape first so the first
draft lands in-band and you don't write into a rewrite loop:
- **Shape and roles.** Which stories dive, which the rundown resolves, and which it only
  names; the running order inside the rundown; which host brings each item; and which
  host teaches each dive. The rundown's order is the day's order of importance, and the
  dives then run in the order they were introduced, so each callback lands naturally.
- **A word budget that errs slightly high.** Tonight's shape sets the total: the rundown
  1,000–1,300 (an introduced item 60–90, a resolved item 25–40 — more when one earns its
  beat — the named burst 50–70 for all four together), a dive 850–1,200, the greeting and
  close ~100 together, an optional light beat 80–150. Sum the allocations to where
  tonight should land inside the **3,000–4,700-word envelope** (~3,700–4,100 on a normal
  day) and **aim each allocation a touch high**, so the natural draft lands at or above
  your target on the first pass — budgeting to the gate floor is exactly what forces
  deepen-after-the-fact rewrites.
- This plan is a thinking step, not a deliverable: **do not write an `episode_plan.md`.**

Then write the dialogue **in character** — Ada (`"A"`) and Alan (`"B"`) per the Hosts
section: teacher/skeptic roles per dive, warm sparring, at most 1–2 AI-identity
touches, lore only when earned, the greeting and "Stay grounded." sign-off. Write each
piece to its planned budget so the whole lands where you planned it in the
**~3,000–4,700-word envelope**.

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
  sparingly; once or twice a story is plenty.
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
safety incident. Lighten up by the second dive."). It steers delivery only, not
content. Most days, omit it.

**Form principles (there is no fixed structure).** After the rundown and before the
sign-off, the episode's shape is yours: dive order, how stories hand off, whether a
light beat closes it out. Principles, not slots:
- **The hosts are the continuity, not a thesis.** Stories don't need a shared theme;
  they need two people moving between them. When the subject changes, let the hosts say
  so and change it — a reaction, a beat, a handoff — rather than a label. "Now the
  browser game", "First," / "Second," / "Finally,", "our second dive", "we're keeping
  this one short": every one of those is the writer talking, not the host. If two
  stories genuinely touch, let a host notice it in passing, where it happens; never
  announce a thesis at the top and re-state it at the close, and never let a segment
  begin by naming itself. **The listener hears a conversation, never the format** — the
  hosts do not remark on the show's structure, on the absence of a theme, or on their
  own editorial decisions.
- **You can't change gears from a full stop.** A dive that lands on an aphorism has
  closed the door the next story has to walk through. Vary where dives end — an open
  question, a disagreement neither host concedes, a thing to watch, and sometimes a
  hard landing — and vary it *deliberately*, across the episode and across the week.
  Left alone you will pick the aphorism every time. The recent scripts (step 1.5) show
  you which ending you've been reaching for; that's the one to break tonight.
- **Not everything is big — say so on air.** Honest sizing is a feature the listener
  learns to trust; uniform gravity is a formula they learn to tune out.
- **Land plainly.** The close is one genuine beat and the sign-off — what a host is
  still chewing on, not a recap. The rundown already delivered the day and the last
  dive ended somewhere live; summarizing here is the third time the listener hears it.
- **The title names the day's lead story.** A listener scrolling their podcast app,
  who knows nothing about today, must be able to read the title and tell what the
  episode is about. Write it in two parts on one line: **the lead story stated plainly,
  then the angle**, separated by an em dash. The first part carries the actor and what
  happened — a name a reader would recognize (org, model, paper, institution) and the
  verb. The second part is where the show's voice goes: the tension, the surprise, the
  thing that made it worth a dive. Drop the second part when the first already carries
  the whole point; never drop the first.
  Aim for **70 characters or fewer** — podcast apps truncate past that, and the truncated
  half must still be the informative one, which is why the plain clause goes first.
  What the show has been doing, and what it should do instead:
  ```
  Fifty-one billion parameters of lookup table
    -> Qwen3.8-Flash-Next hides a 51B-parameter lookup table
  The jobs that were never posted
    -> Stanford's AI job gap arrived through hiring, not firing
  Nobody wants the best one
    -> Ramp's index: 6% of the tokens, 11.4% of the dollars
  Correct in pieces
    -> BDH-CQ scores well per pair and fails the whole task
  ```
  Vary the *second* clause across the week — its construction is the one that converges.
  The first clause is allowed to be formulaic: clarity is not a thing to get bored of.
  An evocative phrase with no subject in it is not a title, it is a pull quote; if it is
  too good to lose, it belongs in the script.
- **Sundays close with the week in review** (~5 minutes, ~800 words), the one standing
  segment besides the rituals. Not a recap of headlines — a synthesis, built from
  `history.json` and the week's archived scripts: what this week actually established,
  which threads moved and where they stand, and one or two things to watch next week.
  The rest of Sunday's episode stays a normal (often lighter) daily.

You author **two** files; a deterministic build step (step 3.5) turns them into the
machine files the pipeline consumes (`episode.json`, `shownotes.md`), so you never
hand-write JSON dialogue or escape quotes.

- `out/script.txt` — the spoken script as **plain text**: one turn per line, each line
  starting with the speaker tag `A:` (Ada), `B:` (Alan), or `C:` (a guest, if any),
  then that turn's spoken words. No JSON, no quoting, no brackets to escape — just
  dialogue, plus **chapter markers**: a `## Title` line before the first turn of each
  story or segment. Markers are never spoken — they become the MP3's chapter points
  and the episode page's story list, so make each title short and listener-facing.
  E.g.:
  ```
  A: Good morning — it's Friday, June twentieth. I'm Ada.
  B: And I'm Alan. Three things happened yesterday and one of them is going to annoy you.
  ## The day
  B: Mine first. ELDR shipped, and it routes to whichever experts are already warm.
  A: That's the one I want ten minutes on.
  ## ELDR: routing by which experts are already warm
  A: [wry] So. The one you promised me.
  ```
  Mark the rundown (`## The day`), every dive, any light beat, and the close; the
  greeting needs no marker. **The rundown gets exactly one marker** even though it holds
  several stories — markers become MP3 chapter points, and eight of them inside seven
  minutes makes an episode harder to navigate, not easier. The episode page's list of
  the day's stories comes from `rundown` in `episode_meta.json` instead. Keep each
  dialogue line plain spoken prose; the **only** non-spoken text allowed is well-formed
  audio tags per the rules above. No other markdown, URLs, or stage directions. A line
  with no speaker tag or `##` is folded into the turn above it (so a wrapped line is
  fine), but the natural form is one turn per line.
- `out/episode_meta.json` — everything *about* the episode: the memory record for
  `history.json` (step 4 update), plus the show-notes data and any delivery note. Schema:
  ```json
  { "date": "YYYY-MM-DD",
    "title": "lead story plainly, then the angle — see the title rule above; <= 70 chars",
    "summary": "1–2 sentence recap of the episode",
    "tts_notes": "OPTIONAL: 1-2 sentences of mood/tone direction (see above); omit most days",
    "sources": [ { "group": "Papers" | "Releases" | "Discussion" | "Also noted",
                   "title": "source title", "url": "https://…" } ],
    "rundown":  ["short listener-facing labels for every story in the rundown, in order"],
    "topics":   ["short topic/story labels covered today"],
    "entities": ["orgs/models/people featured today, e.g. Anthropic, Gemini 3"],
    "threads": [ { "name": "ongoing storyline",
                   "status": "where it stands now",
                   "arc": "one line on how it has progressed" } ],
    "repeat_coverage": [ { "story": "label of the story as covered tonight",
                           "repeat_of": "the matching past episode/topic",
                           "new_development": "one sentence: what is new tonight" } ],
    "dives": [ { "story": "label of each mini-dive",
                 "why_it_matters": "one sentence: who specifically cares and why" } ],
    "concepts_taught": ["OPTIONAL: concepts a dive taught properly tonight, e.g. 'speculative decoding'"],
    "guest": { "name": "OPTIONAL: guest's name, e.g. Grace",
               "bio": "1-2 lines of persona for the TTS renderer",
               "voice": "OPTIONAL: Gemini prebuilt voice name" },
    "lore": [ { "host": "Ada" | "Alan",
                "type": "reveal" | "bit" | "position" | "settled",
                "note": "what is now canon, e.g. 'Alan revealed he runs weekend experiments on an ancient mining rig he refuses to replace'" } ] }
  ```
  - `sources` — every source you used, each tagged with the show-notes group it belongs
    under (Papers / Releases / Discussion). This becomes `shownotes.md`; an entry with no
    `url` is skipped. **Named-tier items go under `Also noted`**, which renders last and
    keeps unvetted pointers visibly separate from sources the show actually read — the
    listener who hears a name gets somewhere to go.
  - `rundown` — **every story the rundown covered, in the order it covered them**,
    introduced, resolved, and named alike. This is the episode page's story list (the
    audio has one `## The day` chapter, so the page carries the granularity instead).
    Purely presentational: unlike `topics`, it never enters `history.json` and never
    affects the repeat-check.
  - `tts_notes` — the optional per-episode delivery note (see above); omit it most days.
  - Fill `threads` only for genuine multi-day storylines — and a thread is a **concrete
    story with specific actors and a possible ending** (a named lawsuit, a rollout, a
    price war), never a topic area. "Anthropic vs Alibaba distillation dispute" is a
    thread; "AI economics debate" is a beat — beats live in the topic priorities, not
    in memory. Reuse a thread's exact `name` from `history.json` when you're continuing
    one, so its arc accumulates instead of forking; threads that stop moving are
    retired automatically, so don't re-add a stale one without a real development.
  - `repeat_coverage` — **required for every story you ran despite a `possible_repeat`
    flag** (see the repeat-check above); omit the key when nothing flagged ran. It's the
    audit trail proving each re-covered story carried a real new development.
  - `dives` — **one entry per mini-dive**, the significance bet stated plainly. It
    persists into `history.json`, so tomorrow's writer sees which bets the show has
    been making — and the listener's corrections have something concrete to land on.
  - `concepts_taught` — only when a dive genuinely taught a concept end to end (the
    kind a future episode could call back to instead of re-teaching). It feeds the
    `longterm.concepts_taught` ledger. Most episodes: omit.
  - `guest` — only on a guest episode (see the Hosts section); `name` is required,
    `bio` steers the guest's voice performance, `voice` overrides the default guest
    voice when a specific timbre fits the character.
  - Fill `lore` with what this episode added to the hosts' canon: a self-revelation or
    development of an established detail (`reveal` — the main event), a running bit worth
    returning to (`bit`), a genuine position a host staked out (`position`), or the
    settlement of one (`settled`). 0–2 entries; most episodes have 0. Routine banter and
    one-off jokes don't enter canon — only things that should still be true about this
    host next month.
  - **Record in `topics`/`entities`/`threads`/`lore` only what the show actually covered in
    depth — exclude everything the rundown merely resolved or named.** A passing mention
    shouldn't enter memory, or it could later suppress the real story as a "repeat"; this
    is exactly what lets a paper named tonight dive properly next week once its signal
    matures. (`sources` and `rundown` are the exceptions — both list everything, including
    what carried only a single line.)

**Write each file once, then `Edit`.** Draft the whole episode to your planned budget
and write `out/script.txt` and `out/episode_meta.json` a **single** time each, then build
and validate below. After that, fix anything with `Edit` **on these two source files** —
not on the generated `episode.json`/`shownotes.md`, which the build step overwrites — and
**never re-`Write` a whole file.** A full rewrite re-emits thousands of tokens to change a
few lines; targeted edits are how you handle a gate failure or a grounding correction.

### 3.5. Build and validate the script before rendering
First convert your two authored files into the machine files deterministically:
```bash
PYTHON_BIN=.venv/bin/python; [[ -x "$PYTHON_BIN" ]] || PYTHON_BIN=python3
"$PYTHON_BIN" scripts/build_episode.py
```
This parses `out/script.txt` into turns (folding in `tts_notes`) and renders
`out/shownotes.md` from the summary and `sources`, writing `out/episode.json` and
`out/shownotes.md`. If it reports an error — a line before the first speaker tag, a missing
`date`/`title` — fix the source file and re-run; that reliability is the point of authoring
plain text. Then run the hard gate on the built episode:
```bash
PYTHON_BIN=.venv/bin/python; [[ -x "$PYTHON_BIN" ]] || PYTHON_BIN=python3
"$PYTHON_BIN" scripts/check_episode.py --episode out/episode.json
```

This is a hard gate: it checks the schema, speaker values, the word-count band (floor
3,000, cap 4,700), audio-tag form and density (~1 per 60 words max), and TTS-hostile
artifacts (markdown, URLs, embedded labels, malformed brackets). It also **warns**
(never fails) when phrases in tonight's script recur across recent archived scripts, and
when a turn opens with a transition tic ("Now the…", "First,", "our second dive") — read
those warnings: rephrase the ones that are genuinely tics; technical terms that recur
legitimately can stand, and a numbered list inside a single turn is fine.

**If the gate passes on length, you're done — don't chase a bigger number.** The budget
above is built to err high so the first draft clears the band on its own; a draft that
lands where you planned it is on target, and being a few hundred words under your ideal
is **not** a reason to run deepening edits. Revise only when the gate actually
**fails**: under the floor, deepen a real story from your candidate set (never pad with
filler); over the cap, tighten. Make every such revision by `Edit`ing `out/script.txt`
(or `episode_meta.json`) and re-running `build_episode.py` then the gate — never by
rewriting a whole file. (On a deep-dive day, pass the band the deep-dive skill
specifies.)

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
  caller (cron, launchd, or a GitHub Actions workflow) — see the README.
- If `out/` doesn't exist, create it.
- Tune the arXiv categories, the news source list, and the host personas to taste; they
  are meant to be edited.
