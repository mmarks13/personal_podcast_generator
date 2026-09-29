---
name: weekly-deep-dive
description: >
  Produce a deep-dive podcast episode (runs three times a week: Wednesday, Saturday, Sunday): pick
  one topic recent AI news made worth learning properly, research it at primary sources,
  and teach it as a ~20-25 minute two-host episode rendered to MP3. Use when asked to
  "make the deep dive", "do the deep-dive episode", or produce a Wed/Sat/Sun teaching episode.
---

# Weekly Deep Dive

A second episode in the same feed, three times a week (Wednesday, Saturday, and Sunday): not the day's
news, but a **teaching episode** — one topic, explained properly, chosen because recent
events made it worth understanding. Aim for **~3,000–3,750 words** (the Gemini voices
render that to roughly 22–29 minutes).

Because this runs three times a week, **check `history.json` for a deep-dive (`"kind":
"deepdive"`) already recorded in the last several days and pick a clearly different
topic** — don't re-teach what the week's earlier deep-dives already covered.

The listener already hears the daily show, so don't re-report the week. Use the week's
news as the doorway: "X kept coming up this week — here's how it actually works."

## Workflow

### 1. Pick the topic
**If the invocation prompt says the listener pre-chose tonight's topic** (via the
evening options push), take it as given — skip selection and go straight to step 2.
Their free-text topic may need light interpretation into a teachable framing; keep
its intent.

**If it carries an editorial note**, that note **outranks this skill**. It is direction on
*how to teach* this episode — emphasis, framing, depth, where to go slow, what to leave out —
and where it conflicts with anything written here, it wins. It can arrive without a topic,
and then the topic is still yours to pick from the palette below.

Three things it cannot move, and you say so in your closing report when one binds:
grounding (every claim still traces to a fetched source, whatever the note asks); the
harness (rendering, publishing, archiving, and these skill files, which you never edit);
and the word band, which it moves only through the harness — if a note asked for a length,
the band in your invocation prompt already reflects it, clamped to what the show can
render. Teach to the band you were given.

**The topic palette — four types, all first-class:**
- **Mechanism** — the idea under this week's news: an architecture, a training or
  serving technique, an evaluation method. (Named examples are deliberately absent here:
  the obvious ones have mostly been taught already, and a palette that lists them invites
  re-pitching a past episode. Check `concepts_taught` and the ledger, not this list.) Across every slate so far, mechanism pitches whose subject is the
  model or the agent itself are the ones that get picked; pitches where the model is only
  the setting — attacker tradecraft, scoring and judging harnesses, silicon fabrication,
  byte-level serving economics, verification tooling internals, single-product
  applications — account for roughly half of all mechanism pitches and none of the picks.
  That is an aggregate tendency, not a rule: treat those subjects as low-yield rather
  than closed, pitch one when it is genuinely the week's defining story, and prefer the
  wildcard slot when you do.
- **Foundational** — a load-bearing concept of the field taught properly, needing no
  news hook beyond "you hear this word constantly." Two lanes qualify. **Named technical
  apparatus**, taught mechanically — what the thing is and how it works (RLHF,
  distillation, calibration, embeddings, high-bandwidth memory) — drawn from any of
  training and learning methods, representation and model internals, evaluation and
  model behaviour, or systems, serving and hardware. And **craft reality** — how this
  work actually goes in practice, of which "the gap between a prototype and a product"
  is the type case. Two framings do *not* belong here and have never been picked as
  foundational: "what a benchmark, study, or proof can really tell you" epistemics, and
  "what this legal or contractual term actually covers" — pitch those as Debate. Reach
  outside AI into an applied field only when a result there is genuinely the week's story.
- **History** — how we got here: the lineage of an idea, told as narrative, landing
  in the present.
- **Debate** — a genuine unresolved argument, steel-manned from both sides.

Otherwise read `history.json` — the last ~7 days of `episodes` plus
`longterm.active_threads` and `longterm.concepts_taught` — and pick **one** topic
from the palette.

Rules:
- **Soft "why now."** The cold open still answers *why this, now* — but "this word has
  been in every episode this month" or "this fight keeps resurfacing" counts. A
  this-week hook is preferred when it's real; never manufacture one.
- **A topic is never a single paper.** It's the idea or capability the paper
  instantiates; the paper is the episode's centerpiece and evidence, not its whole
  body. If research (step 2) reveals the chosen framing is thin — one paper's worth of
  material stretched over twenty minutes — you are **obligated to widen to the
  surrounding idea**, keeping the chosen thing at the heart of the episode. You also
  have license to spend real time on future implications — where this could go if it
  works — clearly flagged as speculation, not fact.
- Don't repeat a recent deep dive: skip anything already in an episode record with
  `"kind": "deepdive"`, a `deep dive:` topic label, or the `longterm.concepts_taught`
  ledger in `history.json`.
- Prefer topics where understanding transfers (how the thing works, why it matters,
  what its limits are) over news recaps or product tours.

### 2. Research it properly
Use the available web fetch/search tools to read the primary material: the paper(s), official docs,
technical blog posts, credible independent analyses. **Read the one or two core sources
yourself** — the paper(s) the episode actually teaches — because the "how it works" and
"where the analogy breaks" sections depend on your own understanding, not a secondhand
extract. The daily show's grounding rules apply unchanged and matter even more here,
because a deep dive invites confident explanation:
- Every factual claim traces to a page you actually read. If you didn't read it,
  don't say it.
- No invented numbers, names, dates, or quotes. "The authors report…", not "this
  proves…". Distinguish established results from claims.
- When sources disagree, say so on air rather than picking one silently.

For the **specific load-bearing details** that pepper a teaching episode — exact numbers,
dates, benchmark figures, quotes, who-did-what-when — **delegate the batch to the
`fact-checker` agent**, phrased as delegation and naming it ("Delegate this batch: have
fact-checker verify these claims against these URLs"), each with the URL to check it
against; a soft hand-off tends to get executed in your own context instead. It returns a
verdict and the **verbatim quote** per claim. Use it to confirm the details, not to replace
your reading of the core material: only `supported` claims (with a real quote) are safe to
state, `contradicted` gets corrected to the quote, `not_found`/`unreachable` gets re-checked
or dropped.

If delegation doesn't take and you do the fetching yourself, that's fine. What is never fine
is **stating a detail whose page nobody actually read this session** — leave it out rather
than asserting it, and never narrate a fact-check that didn't happen.

### 3. Write the script
Same hosts as the daily show — **Ada** (`"A"`) and **Alan** (`"B"`); read the **Hosts
section of the daily skill** (`.agents/skills/daily-ai-podcast/SKILL.md`) for their
personas, fiction rules, lore canon, and rituals, all of which apply here. Teaching
mode plays to type: **Ada owns the lineage and foundations** — the computing historian
in her element, tracing how we got here — while **Alan stress-tests everything** as the
builder: he wants to run it, cost it, and find where it breaks, asking the questions a
smart listener would. Open with the two-voice greeting (adapted for the weekend), close
with "Stay grounded."

**Shape follows topic type** — pick the archetype, then flex it where the material
wants to (the archetypes are defaults, not slots):

*Mechanism / Foundational* — the classic lesson:
1. **Cold open** — the hook: the "why now", and the question it raises.
2. **Foundations** — the minimum background, in plain language. Spell out acronyms.
3. **How it actually works** — the core mechanism, step by step. Analogies welcome,
   but keep them precise; say where the analogy breaks down.
4. **Evidence and limits** — what's demonstrated vs. claimed, known failure modes,
   open questions.
5. **So what** — what a practitioner or informed listener should do or watch for —
   and, when the material earns it, where this could plausibly go (flagged as
   speculation).
6. **Wrap** — 20–30 seconds.

*History* — a narrative arc, not a lecture: the eras and turning points in order, what
each generation was actually trying to do, why the promising paths died, and the
landing in the present — what today inherits from that lineage. Ada leads by
temperament; the mechanism beats still appear inside the story wherever an idea needs
to be actually understood, not just named.

*Debate* — both cases built honestly: the strongest version of each side (steel-manned
by the host who least agrees with it), the evidence audit — what would settle it and
why it hasn't — then the hosts' own honest reads, which may differ and **may stay
unresolved**. No fake balance: if the evidence leans, say so.

Keep turns short and conversational. The daily skill's **"Write it as a
conversation"**, **"the hosts are the continuity, not a thesis"**, **"you can't change
gears from a full stop"**, **audio tags**, and **per-episode delivery note**
(`tts_notes`) rules apply verbatim — backchannels and reactive turns matter even more in
teaching mode, where the temptation is alternating lectures. The transition rules bind
here too: a lesson's sections hand off exactly the way a daily's stories do, so **no
section begins by naming itself** ("Now the evidence", "Second, the mechanism") and no
section ends on a full stop that leaves the next one nowhere to start. A teaching
episode has no rundown — it is one topic, and its cold open is a hook by design.
No markdown, URLs, or stage directions in turn text; well-formed audio tags are the only
non-spoken text.

Author **two** files (same plain-text → build flow as the daily skill); the build step
(step 4) turns them into `deepdive.json` + `deepdive_shownotes.md`, so you never hand-write
JSON dialogue:
- `out/deepdive_script.txt` — the spoken script as **plain text**, one turn per line, each
  starting with `A:` (Ada) or `B:` (Alan); audio tags are the only non-spoken text; no
  markdown, URLs, or stage directions. A tag-less line folds into the turn above it.
  Add `## Title` **chapter markers** (never spoken; they become MP3 chapters and the
  episode page's outline) before each major section of the lesson.
**The title names the concept the episode teaches.** Someone browsing the feed should be
able to tell what they would learn, before pressing play. One line, 70 characters or
fewer, in two parts: **the concept plainly, then the angle**, split by a colon or em dash.
`publish.py` prepends the standing "Deep Dive:" label, so never write it yourself.

```
You will not find it
  -> Undetectable model backdoors: why open weights can't prove innocence
The deputy with a credit card
  -> Giving an agent a budget: the confused deputy and macaroons
Sixty years of no technician, ever
  -> Computers in orbit: rope memory to rad-hard, with no repair crew
```

The angle half carries the show's voice and should vary week to week; the concept half is
allowed to repeat its shape. A title with no nameable concept in it is not a title.

- `out/deepdive_meta.json` — the memory record plus the show-notes data, with the deepdive
  extras so the daily show's repeat-check and future deep dives see it correctly:
  ```json
  { "date": "YYYY-MM-DD", "kind": "deepdive",
    "title": "names the concept taught, then the angle — see the title rule below; <= 70 chars",
    "summary": "1–2 sentences",
    "tts_notes": "OPTIONAL delivery note; omit most episodes",
    "sources": [ { "group": "Primary sources" | "Further reading",
                   "title": "source title", "url": "https://…" } ],
    "topics": ["deep dive: <topic>"], "entities": [...], "threads": [],
    "concepts_taught": ["the concept this episode taught, e.g. 'speculative decoding'"],
    "lore": [ { "host": "Ada" | "Alan", "type": "reveal" | "bit" | "position" | "settled",
                "note": "what is now canon" } ] }
  ```
  `sources` becomes `deepdive_shownotes.md`, grouped as Primary sources / Further reading.
  `concepts_taught` feeds the `longterm.concepts_taught` ledger — a deep dive always
  fills it (that's the episode's whole job). `lore` follows the daily skill's rules:
  only what this episode added to the hosts' canon, 0–2 entries, usually 0.

**Write each file once, then `Edit`** the source files (not the generated JSON/notes) — same
discipline as the daily skill; never re-`Write` a whole file.

### 4. Build, validate, and stop
Convert your two files into the machine files, then run the gate on the built episode:
```bash
PYTHON_BIN=.venv/bin/python; [[ -x "$PYTHON_BIN" ]] || PYTHON_BIN=python3
"$PYTHON_BIN" scripts/build_episode.py --script out/deepdive_script.txt \
  --meta out/deepdive_meta.json --episode out/deepdive.json --notes out/deepdive_shownotes.md
"$PYTHON_BIN" scripts/check_episode.py --episode out/deepdive.json --min-words 3000 --max-words 4000
```
The check is a hard gate — when it fails, `Edit` `out/deepdive_script.txt`, re-run the build,
and re-check until it passes. When under length, deepen the explanation (more mechanism,
more evidence), never pad. If the build itself errors (a malformed line, a missing
`date`/`title`), fix the source file and re-run.

**Stop here.** The harness (`run_episode.sh`) updates `history.json` and renders the
audio after you exit — do not run `make_audio.py` or `update_history.py` yourself.

### 5. Report
Print the topic chosen and the week's hook it ties to, the word count, and any source
gaps. Rendering and publishing happen in the caller (`run_episode.sh`), not here.
