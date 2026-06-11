# AI Podcast — Source Candidates (mid-2026)

A curated shortlist to choose from when configuring the show's content. Mixed across
five categories so the episode can balance *papers*, *releases*, *news*, *curation*,
and *community signal*. The **Access** column matters for the build: prefer API/RSS
where available (deterministic, cheap on tokens) and fall back to web fetch otherwise.

> Status notes worth knowing: **Papers with Code was retired by Meta in July 2025** and
> now redirects to Hugging Face — use HF Daily Papers instead. **Google Podcasts and
> Stitcher are dead.** The model leaderboards consolidated around **LMArena**,
> **Artificial Analysis**, and **Epoch AI**.

## Top 20

| # | Source | Category | Why it's useful (its angle) | Access |
|---|--------|----------|------------------------------|--------|
| 1 | [arXiv](https://arxiv.org/list/cs.AI/recent) (cs.AI / cs.CL / cs.LG / cs.MA) | Papers | The primary firehose of AI preprints; nearly everything else references it | **API** (export.arxiv.org/api/query, Atom) + per-category RSS |
| 2 | [Hugging Face Daily Papers](https://huggingface.co/papers) | Papers | AK's hand-picked, community-upvoted daily set — the single best "what the field is reading today" signal | **API** (huggingface.co/api/daily_papers, JSON) |
| 3 | [alphaXiv](https://www.alphaxiv.org) | Papers | Trending arXiv papers with public discussion + plain-language explanations; good for gauging traction | Web (fetch) |
| 4 | [Anthropic — News](https://www.anthropic.com/news) | Lab / official | Primary source for Claude model + feature releases and safety research | Web (fetch) |
| 5 | [OpenAI — News](https://openai.com/news/) | Lab / official | Primary source for GPT / o-series launches and product news | Web (fetch) |
| 6 | [Google DeepMind — Blog](https://deepmind.google/discover/blog/) | Lab / official | Gemini + DeepMind research straight from the source | Web (fetch), some RSS |
| 7 | [Meta AI — Blog](https://ai.meta.com/blog/) | Lab / official | Llama and FAIR open-model + research announcements | Web (fetch) |
| 8 | [Hugging Face — Blog](https://huggingface.co/blog) | Open-source | The hub for open-model launches, libraries, and community releases | Web (fetch), RSS |
| 9 | [TechCrunch — AI](https://techcrunch.com/category/artificial-intelligence/) | News | Fast, reliable coverage of funding, startups, and product launches | **RSS** (`/category/artificial-intelligence/feed/`) |
| 10 | [VentureBeat — AI](https://venturebeat.com/category/ai/) | News | Enterprise-AI angle others skip; deployment + infra stories | **RSS** (`/category/ai/feed/`) |
| 11 | [The Verge — AI](https://www.theverge.com/ai-artificial-intelligence) | News | Consumer-facing AI news, strong editorial quality and speed | **RSS** |
| 12 | [Ars Technica — AI](https://arstechnica.com/ai/) | News | Technical depth and "how it actually works" explainers | **RSS** (feeds.arstechnica.com) |
| 13 | [Import AI](https://importai.substack.com) (Jack Clark) | Newsletter | Weekly research + policy from an Anthropic co-founder; "Why this matters" framing | **RSS** (Substack) |
| 14 | [The Batch](https://www.deeplearning.ai/the-batch/) (Andrew Ng / DeepLearning.AI) | Newsletter | Weekly research framing + education; Andrew Ng's editorial letters | RSS / web |
| 15 | [TLDR AI](https://tldr.tech/ai) | Newsletter | Dense daily bullet summary of papers, launches, and industry news — very high signal density | Web archive (fetch) |
| 16 | [Last Week in AI](https://lastweekin.ai/) | Newsletter / Podcast | Comprehensive weekly recap (+ podcast) — a safety net for anything missed | **RSS** (Substack) |
| 17 | [Hacker News](https://news.ycombinator.com/) | Community | The practitioner pulse; surfaces tools, launches, and debate with substantive comments | **API** (hn.algolia.com/api/v1) |
| 18 | [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/) | Community | Fastest signal on open-weight model releases and hands-on results | **RSS / JSON** (append `.rss` or `.json`) |
| 19 | [LMArena](https://lmarena.ai/leaderboard) | Benchmarks | Human-preference Elo leaderboard (formerly Chatbot Arena) — who's on top by crowd vote | Web (fetch) |
| 20 | [Artificial Analysis](https://artificialanalysis.ai/) | Benchmarks | Independent capability index with price + speed — great for "model X now leads Y" beats | Web (fetch) |

## Honorable mentions (also worth wiring in)

- [Techmeme](https://www.techmeme.com/) — clustered tech-news aggregator; surfaces the day's most-discussed stories (RSS).
- [Epoch AI](https://epoch.ai/benchmarks) — rigorous capability trends over time, METR collaboration; great for "state of the field" segments.
- [MIT Technology Review — The Algorithm](https://www.technologyreview.com/) — research framing for a general audience (newsletter).
- [Wired — AI](https://www.wired.com/tag/artificial-intelligence/) — long-form features, ethics, investigations.
- [Interconnects](https://www.interconnects.ai/) (Nathan Lambert) — post-training / RL depth (Substack RSS).
- [Ahead of AI](https://magazine.sebastianraschka.com/) (Sebastian Raschka) — LLM architecture deep dives.
- [Latent Space](https://www.latent.space/) — AI engineering as a discipline; production tradeoffs (newsletter + podcast).
- [The Rundown AI](https://www.therundown.ai/) / [The Neuron](https://www.theneurondaily.com/) — accessible daily scans (2M+ / large audiences).
- [MarkTechPost](https://www.marktechpost.com/) — daily model/release tracking.
- [Mistral — News](https://mistral.ai/news/), [Google Research Blog](https://research.google/blog/), [Microsoft Research Blog](https://www.microsoft.com/en-us/research/blog/) — more lab primaries.
- [Semantic Scholar API](https://api.semanticscholar.org) — structured paper metadata/citations if you want richer paper context.

## How to use this list

- **Start lean.** A strong daily set is ~8–9 sources (see Tier 1 in `config/sources.yaml`): arXiv + HF Daily Papers + 3–4 lab blogs + one dense daily newsletter (TLDR AI) + Hacker News + r/LocalLLaMA. Add the rest once the show's voice is dialed in.
- **Avoid overlap.** The big dailies (TLDR AI, The Rundown, Superhuman AI) repeat ~80% of the same lead stories — pick one, not three.
- **Primary over secondary.** Use newsletters/aggregators to *discover* items, then verify and quote from the lab's own post or the paper itself.
- **Respect cadence.** arXiv, HF, HN, news sites, and the big dailies are daily; The Batch / Import AI / Last Week in AI / Interconnects are weekly — weight them accordingly so a weekly source's items don't resurface as if they were new each day.
