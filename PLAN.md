# BUILD RUNBOOK — `daily-ai-podcast`

**Audience: the Claude Code agent executing this build.** Follow it top to bottom.
Commit after each numbered milestone. Never fabricate credentials or invent URLs/feeds
you haven't verified. Where a value is unknown (hosting choice, RSS email, cover image),
**stop and ask the user** rather than guessing. Confirm before any destructive command.

---

## 1. Objective & locked decisions

Build a fresh **private** GitHub repo that hosts and orchestrates a daily AI-news
podcast end to end. The repo is the source of truth; it's cloned to the user's own
machine and a local scheduler runs it overnight.

Locked decisions for this build:

- **Plan A** — Claude work runs on the user's **Claude Pro subscription** (not the
  pay-per-token API); audio is **local Kokoro** (free); orchestration is a **local
  cron/launchd job** on the user's machine. Marginal cost ≈ $0 beyond Pro + cheap object
  storage.
- **Episode length: ~15 minutes** → target **~2,250 spoken words** (≈ 150 wpm). The
  script skill is tuned to this.
- **Auth model (critical):** the overnight run uses the **logged-in Claude Code CLI**
  (OAuth from `claude login`), so it draws on the Pro plan. **Do NOT export
  `ANTHROPIC_API_KEY` in the run environment** — that silently switches billing to the
  paid API. Object-storage keys are the only secrets the run needs.
- **Hosting:** object storage for the MP3s + RSS feed. Recommend **Cloudflare R2** (no
  egress fees — a podcast is all egress). AWS S3 or GitHub Releases are acceptable
  alternatives. **Confirm the user's choice before building the publish step.**
- Repo name suggestion: **`daily-ai-podcast`** (confirm with user).

---

## 2. Pre-flight checklist (verify, ask if missing)

Run these checks and report results. If something's missing, tell the user how to fix
it and pause.

```bash
gh auth status            # GitHub CLI authenticated?
claude --version          # Claude Code CLI present
python3 --version         # need 3.10+ (3.12 ideal)
node --version            # need 20+ (Agent SDK / CLI)
ffmpeg -version | head -1 # required by Kokoro render + publish (ffprobe)
```

Then confirm with the user:
1. **Claude Pro** active and `claude login` already completed on this machine.
2. **Hosting choice** (R2 / S3 / GitHub Releases) and that they can create a
   public-read bucket + get credentials.
3. An **email address** to embed in the RSS feed (Spotify uses it for verification).
4. A **cover image** (square, 1400–3000px, JPEG/PNG) — they provide one or ask us to
   generate a simple one.
5. Show metadata: **title**, **author/host name**, one-line **description**, category
   (default: Technology).

---

## 3. Create the private repo

```bash
mkdir -p daily-ai-podcast && cd daily-ai-podcast
git init -b main
# ...create files per sections 4–5 first, then:
git add -A
git commit -m "Initial scaffold: daily AI podcast (Plan A, 15-min)"
gh repo create daily-ai-podcast --private --source=. --remote=origin --push \
  --description "Automated daily AI-news podcast (papers, releases, news → audio)"
```

Confirm the repo is **Private** in the `gh repo create` output before continuing.

---

## 4. File tree

```
daily-ai-podcast/
├── CLAUDE.md                                  # project memory (section 5c)
├── README.md                                  # short usage notes
├── requirements.txt                           # section 5h
├── run_episode.sh                             # local entrypoint (section 5g)
├── .env.example                               # section 5e   (never commit real .env)
├── .gitignore                                 # section 5f
├── config/
│   └── sources.yaml                           # the watchlist (section 5d)
├── assets/
│   └── cover.jpg                              # show art (uploaded once to storage)
├── scripts/
│   ├── fetch_sources.py                       # arXiv + HF + HN (reference impl)
│   ├── make_audio.py                          # Kokoro / ElevenLabs (reference impl)
│   └── publish.py                             # upload + RSS rebuild (reference impl)
├── .claude/
│   └── skills/
│       └── daily-ai-podcast/
│           └── SKILL.md                       # editorial workflow (section 5b)
└── out/                                        # generated; gitignored
    └── .gitkeep
```

---

## 5. Create the files

### 5a. Python modules
Use the **three reference implementations already provided in this project**
(`fetch_sources.py`, `make_audio.py`, `publish.py`) as the starting point — copy them
into `scripts/` verbatim, then apply these build-specific changes:

- `make_audio.py`: default backend stays **`kokoro`** (free, local). Leave the
  ElevenLabs path intact for later but don't depend on it.
- `fetch_sources.py`: keep as-is (arXiv + HF Daily Papers + Hacker News). **Optional
  enhancement** (do only if time permits): add an `--rss` mode that also pulls the
  RSS/JSON Tier-1 feeds from `config/sources.yaml`, so more gathering is deterministic
  and fewer Pro tokens are spent at runtime. If you skip it, the skill gathers those via
  WebFetch.
- `publish.py`: unchanged. It reads storage config from env (section 5e).

Verify each compiles: `python -m py_compile scripts/*.py`.

### 5b. `SKILL.md` (15-minute tuning)
Use the **provided `daily-ai-podcast` SKILL.md** as the base, with these edits:

- **Length target:** change the script target to **~2,000–2,500 words (~15 min)**.
- **Segment plan for a 15-min show:** cold open (1 line) → **Papers** (2–3 items) →
  **Releases / launches** (2–3 items) → **Industry & news** (2–3 items) → **One to
  watch** (1 item, slightly deeper) → 20–30s wrap. Keep turns short; alternate hosts.
- **Add a step 1.5 — read the watchlist:** "Read `config/sources.yaml`. Gather from
  every Tier-1 source; pull from Tier-2 only if it's a notable day or a Tier-1 gap.
  Prefer each source's API/RSS; fall back to WebFetch. Always verify a claim at its
  primary source before it goes in the script."
- Keep the **grounding rules verbatim** (every claim traceable; no invented numbers,
  authors, quotes, or dates; "the authors report…" not "this proves…"; flag conflicts).
- Outputs unchanged: `out/episode.json` (structured turns) + `out/shownotes.md`, then
  render via `make_audio.py` with `--backend ${TTS_BACKEND:-kokoro}`.

### 5c. `CLAUDE.md` (create verbatim)
```markdown
# daily-ai-podcast — project memory

Automated daily AI-news podcast: gather the day's AI papers, model releases, and
top discussion → write a grounded ~15-minute two-host script → render to MP3 → publish
to an RSS feed Spotify polls.

## How this runs (Plan A)
- Orchestrated locally by `run_episode.sh`, fired nightly by launchd/cron.
- Claude work uses the **logged-in Claude Pro CLI** — do NOT set ANTHROPIC_API_KEY in
  the run environment (that switches to paid API billing). Only object-storage keys are
  needed at runtime.
- Audio is **local Kokoro** (free). ffmpeg must be on PATH.

## Editorial rules (non-negotiable)
- Every factual claim traces to a fetched source. No invented benchmark numbers,
  authors, dates, funding figures, or quotes. "The authors report…", not "this proves…".
- Verify newsletter/aggregator items at the primary source before including them.
- A quiet day is fine — say so rather than padding.

## Map
- `.claude/skills/daily-ai-podcast/SKILL.md` — the workflow Claude follows.
- `config/sources.yaml` — the source watchlist (Tier 1 = daily; Tier 2 = optional).
- `scripts/fetch_sources.py` — deterministic pulls (arXiv, HF Daily Papers, HN).
- `scripts/make_audio.py` — Kokoro/ElevenLabs render + ffmpeg stitch.
- `scripts/publish.py` — upload MP3 + rebuild iTunes-compatible feed.xml.

## Run it
`bash run_episode.sh`  → writes out/episode.json, out/shownotes.md, out/podcast-DATE.mp3,
then uploads and updates the feed.
```

### 5d. `config/sources.yaml` (create verbatim; the user picks what to enable)
The exact content mix is not yet decided — this is the menu. **Tier 1** is enabled now;
**Tier 2** is available to promote later. Verify each `rss`/`api` endpoint with `curl`
during setup and set `enabled: false` on anything that 404s.
```yaml
# Source watchlist. method: api | rss | fetch. tier 1 = daily core; tier 2 = optional.
sources:
  # --- Papers ---
  - name: arXiv (cs.AI/CL/LG/MA)
    method: api
    url: http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.MA&sortBy=submittedDate&sortOrder=descending
    tier: 1
  - name: Hugging Face Daily Papers
    method: api
    url: https://huggingface.co/api/daily_papers
    tier: 1
  - name: alphaXiv
    method: fetch
    url: https://www.alphaxiv.org
    tier: 2
  # --- Lab / official ---
  - name: Anthropic News
    method: fetch
    url: https://www.anthropic.com/news
    tier: 1
  - name: OpenAI News
    method: fetch
    url: https://openai.com/news/
    tier: 1
  - name: Google DeepMind Blog
    method: fetch
    url: https://deepmind.google/discover/blog/
    tier: 1
  - name: Hugging Face Blog
    method: fetch
    url: https://huggingface.co/blog
    tier: 1
  - name: Meta AI Blog
    method: fetch
    url: https://ai.meta.com/blog/
    tier: 2
  # --- News ---
  - name: TechCrunch AI
    method: rss
    url: https://techcrunch.com/category/artificial-intelligence/feed/
    tier: 2
  - name: VentureBeat AI
    method: rss
    url: https://venturebeat.com/category/ai/feed/
    tier: 2
  - name: The Verge AI
    method: rss
    url: https://www.theverge.com/rss/index.xml
    tier: 2
  - name: Ars Technica
    method: rss
    url: https://feeds.arstechnica.com/arstechnica/index
    tier: 2
  # --- Newsletters / curation ---
  - name: TLDR AI
    method: fetch
    url: https://tldr.tech/ai
    tier: 1
  - name: Import AI
    method: rss
    url: https://importai.substack.com/feed
    tier: 2
  - name: The Batch
    method: fetch
    url: https://www.deeplearning.ai/the-batch/
    tier: 2
  - name: Last Week in AI
    method: rss
    url: https://lastweekin.ai/feed
    tier: 2
  # --- Community ---
  - name: Hacker News (AI)
    method: api
    url: https://hn.algolia.com/api/v1/search_by_date?tags=story
    tier: 1
  - name: r/LocalLLaMA
    method: rss
    url: https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day
    tier: 1
  # --- Benchmarks ---
  - name: LMArena
    method: fetch
    url: https://lmarena.ai/leaderboard
    tier: 2
  - name: Artificial Analysis
    method: fetch
    url: https://artificialanalysis.ai/
    tier: 2
```

### 5e. `.env.example` (create verbatim)
```bash
# Copy to .env and fill in. .env is gitignored — never commit real values.
# NOTE: do NOT put ANTHROPIC_API_KEY here. The run uses your logged-in Claude Pro CLI.

TTS_BACKEND=kokoro

# Object storage (Cloudflare R2 shown; for AWS S3 omit S3_ENDPOINT_URL).
S3_BUCKET=your-podcast-bucket
S3_REGION=auto
S3_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# Public base URL that serves the bucket (R2 public dev URL or custom domain).
PUBLIC_BASE_URL=https://media.yourdomain.com

# Podcast metadata (used to build the RSS feed).
SHOW_TITLE=Your AI Daily
SHOW_DESC=A grounded 15-minute daily briefing on AI papers, releases, and news.
SHOW_AUTHOR=Your Name
OWNER_EMAIL=you@example.com          # Spotify sends the verification code here
SHOW_CATEGORY=Technology
COVER_URL=https://media.yourdomain.com/cover.jpg
```

### 5f. `.gitignore` (create verbatim)
```gitignore
.env
out/*
!out/.gitkeep
__pycache__/
*.pyc
.venv/
*.mp3
```

### 5g. `run_episode.sh` (create verbatim)
```bash
#!/usr/bin/env bash
# Nightly entrypoint. Uses the logged-in Claude Pro CLI (no ANTHROPIC_API_KEY).
set -euo pipefail
cd "$(dirname "$0")"

# Load storage + show config (but not an API key).
set -a; [ -f .env ] && . ./.env; set +a
unset ANTHROPIC_API_KEY || true   # belt-and-suspenders: stay on the Pro subscription

DATE="$(date +%F)"
mkdir -p out

# 1–4: Claude follows the skill — fetch, gather, write script, render MP3.
claude -p "Use the daily-ai-podcast skill to produce today's episode end to end, \
following its grounding rules and ~15-minute target. Print the MP3 path when done." \
  --allowedTools "Bash Read Write WebSearch WebFetch Skill" \
  --permission-mode acceptEdits \
  --max-turns 80

# 5: publish — read title/date/summary from the episode, upload + rebuild the feed.
python3 - "$DATE" <<'PY'
import json, subprocess, sys, glob, os
date = sys.argv[1]
ep = json.load(open("out/episode.json"))
mp3 = sorted(glob.glob(f"out/podcast-{date}*.mp3")) or sorted(glob.glob("out/podcast-*.mp3"))
assert mp3, "no MP3 produced"
summary = ""
try: summary = open("out/shownotes.md").read().split("\n\n")[1][:600]
except Exception: pass
subprocess.run(["python3","scripts/publish.py","--mp3",mp3[-1],
                "--title",ep.get("title",f"AI Daily — {date}"),
                "--summary",summary,"--date",ep.get("date",date)], check=True)
PY

echo "Done: $DATE"
```
Then: `chmod +x run_episode.sh`.

### 5h. `requirements.txt` (create verbatim)
```
feedparser>=6.0
requests>=2.31
feedgen>=1.0
boto3>=1.34
kokoro>=0.9
soundfile>=0.12
# ElevenLabs path (optional) uses requests above. System dep: ffmpeg.
```

Set up the environment:
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

---

## 6. Hosting & cover art

Once the user confirms the hosting target:

- **Cloudflare R2 (recommended):** create a bucket, enable public read (R2.dev public
  URL or a custom domain), create an API token, fill `S3_*`, `AWS_*`, `PUBLIC_BASE_URL`
  in `.env`. R2 is S3-compatible — `publish.py` works unchanged via `S3_ENDPOINT_URL`.
- **AWS S3:** create a bucket with public-read on the `episodes/` prefix + `feed.xml`,
  leave `S3_ENDPOINT_URL` blank.
- **GitHub Releases (no bucket):** host `feed.xml` on GitHub Pages and point enclosures
  at release-asset URLs; adapt `publish.py`'s upload function accordingly.

**Cover art:** upload the confirmed square image once to the bucket at `cover.jpg` and
set `COVER_URL`. (If asked to generate one, keep it simple and legible at 100×100 — but
prefer a user-supplied image.)

---

## 7. Orchestration (Plan A on Claude Pro)

The run must execute on the machine where the user ran `claude login`, so it uses the
Pro subscription. **Verify subscription auth works non-interactively before scheduling:**
```bash
claude -p "Reply with the single word: ok" --max-turns 1
```
If that returns `ok` without prompting for an API key, auth is good.

**macOS (launchd — preferred; can run at a fixed local time):** create
`~/Library/LaunchAgents/com.user.dailyaipodcast.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.user.dailyaipodcast</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd /ABSOLUTE/PATH/daily-ai-podcast && . .venv/bin/activate && ./run_episode.sh >> out/run.log 2>&1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>30</integer></dict>
  <key>RunAtLoad</key><false/>
</dict></plist>
```
Load it: `launchctl load ~/Library/LaunchAgents/com.user.dailyaipodcast.plist`. The Mac
must be awake at 5:30 (set Energy Saver to wake, or use `pmset repeat wake`).

**Linux (cron alternative):**
```cron
30 5 * * *  cd /ABSOLUTE/PATH/daily-ai-podcast && . .venv/bin/activate && ./run_episode.sh >> out/run.log 2>&1
```

> One run/night is light usage and fits comfortably within Pro's limits in normal use;
> if the user also does heavy Claude Code coding the same week, runs could occasionally
> hit a limit — note this and suggest Max if it becomes a problem. (A cloud **Routine**
> is the laptop-closed alternative, but it can't run local Kokoro, so it would require
> switching `TTS_BACKEND` to an API — a deviation from Plan A.)

---

## 8. One-time Spotify submission (manual, by the user)

After the first real episode is live in the feed:
1. Confirm `OWNER_EMAIL` appears in `feed.xml` (it's the iTunes owner email).
2. Go to **Spotify for Creators** → **Add a new show** → **Find an existing show** →
   host = **"Somewhere else"** → paste `PUBLIC_BASE_URL/feed.xml`.
3. Enter the **8-digit code** Spotify emails to `OWNER_EMAIL`.
4. Fill remaining details and submit. First review is typically hours–48h; afterward new
   episodes appear automatically within ~a couple hours of each nightly feed update.

Note to user: Spotify's content policies apply to AI-generated shows — keep the title and
artwork from impersonating a real outlet, and treat a public daily summary of others'
reporting thoughtfully.

---

## 9. Test & validate (do this before scheduling)

```bash
# a) deterministic sources only
python3 scripts/fetch_sources.py --hours 28 --out out/sources.json && cat out/sources.json | head

# b) full episode, once, by hand (uses Pro auth, local Kokoro)
bash run_episode.sh

# c) checks
#  - out/podcast-DATE.mp3 exists and is ~13–15 min (ffprobe it)
#  - the feed is live and valid: open PUBLIC_BASE_URL/feed.xml and run it through a
#    podcast feed validator (e.g. castfeedvalidator.com / podba.se)
#  - listen to the episode; tune host personas / segment count / word target in SKILL.md
```
Only after a clean manual run should the schedule (section 7) be enabled.

---

## 10. Secrets & safety

- `.env` and `out/` are gitignored — confirm nothing sensitive is staged before each
  commit (`git status`).
- Object-storage keys live only in `.env` (or the OS keychain). **No `ANTHROPIC_API_KEY`
  anywhere** — the run is meant to use the Pro subscription.
- Repo stays **private**.

---

## 11. Definition of done

- [ ] Private GitHub repo created and pushed.
- [ ] All files from section 4 committed; `python -m py_compile scripts/*.py` clean.
- [ ] Pro auth confirmed non-interactively (`claude -p` returns without an API-key prompt).
- [ ] One full episode produced locally: `episode.json`, `shownotes.md`, ~15-min MP3.
- [ ] MP3 + `feed.xml` live at `PUBLIC_BASE_URL`; feed passes a validator.
- [ ] Schedule installed (launchd/cron) and a logged dry run succeeded.
- [ ] User has the Spotify submission steps (section 8) and chosen Tier-1 sources.

---

## 12. Build order (milestones — commit after each)

1. Pre-flight checks (section 2); confirm open questions with the user.
2. Create repo + file tree (sections 3–4).
3. Add Python modules + SKILL.md + CLAUDE.md (sections 5a–5c). Commit.
4. Add `sources.yaml`, `.env.example`, `.gitignore`, `run_episode.sh`, `requirements.txt`
   (sections 5d–5h). Commit. Verify feeds with `curl`; disable any that fail.
5. Install deps; set up hosting + cover art + `.env` (section 6). Commit (no secrets).
6. `fetch_sources.py` dry run, then a full `run_episode.sh` (section 9).
7. Validate feed + listen; tune SKILL.md; re-run. Commit tweaks.
8. Install the schedule (section 7); hand the user the Spotify steps (section 8).

---

## Appendix — Source candidates (top 20)

The full table with descriptions and access methods is in **`SOURCES.md`**, reproduced
here for convenience. Tier-1 (enable first): arXiv, HF Daily Papers, Anthropic/OpenAI/
DeepMind/HF blogs, TLDR AI, Hacker News, r/LocalLLaMA.

| # | Source | Category | Access |
|---|--------|----------|--------|
| 1 | arXiv (cs.AI/CL/LG/MA) | Papers | API (export.arxiv.org) + RSS |
| 2 | Hugging Face Daily Papers | Papers | API (huggingface.co/api/daily_papers) |
| 3 | alphaXiv | Papers | fetch |
| 4 | Anthropic — News | Lab | fetch |
| 5 | OpenAI — News | Lab | fetch |
| 6 | Google DeepMind — Blog | Lab | fetch / RSS |
| 7 | Meta AI — Blog | Lab | fetch |
| 8 | Hugging Face — Blog | Open-source | fetch / RSS |
| 9 | TechCrunch — AI | News | RSS |
| 10 | VentureBeat — AI | News | RSS |
| 11 | The Verge — AI | News | RSS |
| 12 | Ars Technica — AI | News | RSS |
| 13 | Import AI (Jack Clark) | Newsletter | RSS (Substack) |
| 14 | The Batch (Andrew Ng) | Newsletter | RSS / web |
| 15 | TLDR AI | Newsletter | fetch |
| 16 | Last Week in AI | Newsletter/Pod | RSS |
| 17 | Hacker News | Community | API (Algolia) |
| 18 | r/LocalLLaMA | Community | RSS / JSON |
| 19 | LMArena | Benchmarks | fetch |
| 20 | Artificial Analysis | Benchmarks | fetch |

Honorable mentions (in `SOURCES.md`): Techmeme, Epoch AI, MIT Tech Review / The
Algorithm, Wired AI, Interconnects, Ahead of AI, Latent Space, The Rundown AI / The
Neuron, MarkTechPost, Mistral / Google Research / Microsoft Research blogs, Semantic
Scholar API.
