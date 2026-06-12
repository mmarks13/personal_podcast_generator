#!/usr/bin/env python3
"""Pull the structured AI sources for the daily podcast.

Driven by `config/sources.yaml`: every source whose method is `rss` or `api`
(Tier 1 and Tier 2) is fetched here, deterministically, every run. These are the
feeds with clean, stable machine output — no judgment needed to *fetch* them
(judgment about what's notable happens later, in the skill's writing step).

  - `api`  sources are dispatched by URL shape (arXiv query, HF Daily Papers,
            Hacker News Algolia, GitHub releases).
  - `rss`  sources are parsed generically with feedparser and time-windowed.
  - `fetch` (HTML) sources are intentionally NOT pulled here — they need a browser
            and interpretation, so the skill's crawl subagent gathers those.

Each source is wrapped in its own try/except so one outage never kills the run.
Every item carries the `source` name it came from, so the writer can see when the
same story shows up across multiple sources.

Usage:
    python scripts/fetch_sources.py --hours 48 --out out/sources.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SOURCES_YAML = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")
ARXIV_MAX_RESULTS = 200   # raw pull per query; keyword-filtered + capped below
ARXIV_MAX_KEPT = 40       # per query, after topic filtering
ARXIV_SUMMARY_CHARS = 500  # judge relevance from this; fetch the paper if covering it
RSS_MAX_ITEMS = 25  # per feed, after time-windowing
# Word-boundary matching: a bare substring check let "ai" match "said"/"email".
AI_KEYWORDS = (
    "ai", "llm", "llms", "gpt", "claude", "gemini", "model", "models", "agent",
    "agents", "agentic", "neural", "transformer", "diffusion", "openai",
    "anthropic", "deepmind", "rag", "llama", "mistral", "qwen",
)
AI_PATTERN = re.compile(r"\b(" + "|".join(AI_KEYWORDS) + r")\b", re.IGNORECASE)
# arXiv topic filter, matched to the skill's six topic priorities. The raw
# category feeds are firehoses; keep papers whose title/abstract hit at least
# one priority area. HF Daily Papers stays the curated lead — this supplements.
ARXIV_TOPIC_TERMS = (
    # production AI systems & agentic workflows
    "agent", "agentic", "multi-agent", "tool use", "tool-use", "orchestration",
    "human-in-the-loop", "deployment", "observability",
    # retrieval, document intelligence & knowledge
    "retrieval", "rag", "retrieval-augmented", "embedding", "embeddings",
    "rerank", "reranking", "document", "knowledge graph", "question answering",
    # quality, evaluation & model decision-making
    "evaluation", "benchmark", "hallucination", "llm-as-judge", "calibration",
    "factuality", "faithfulness", "routing", "distillation", "quantization",
    # AI-native software delivery
    "code generation", "software engineering", "program repair", "coding",
    "code review", "test generation",
    # infrastructure, local deployment, governance & scaling
    "inference", "kv cache", "kv-cache", "mixture-of-experts", "moe",
    "on-device", "edge", "efficient", "open-weight", "safety", "jailbreak",
    "alignment", "privacy", "security",
    # applied & research frontiers with practical signal
    "world model", "multimodal", "remote sensing", "earth observation",
    "geospatial", "robotics", "simulation", "synthetic data", "long context",
    "reasoning", "reinforcement learning",
)
ARXIV_TOPIC_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in ARXIV_TOPIC_TERMS) + r")\b",
    re.IGNORECASE,
)
USER_AGENT = "daily-ai-podcast/1.0 (personal project)"


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _published(entry) -> datetime | None:
    """Best-effort published time from a feedparser entry, as aware UTC."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


# --- api sources, dispatched by URL shape ---------------------------------

def fetch_arxiv(url: str, hours: int) -> list[dict]:
    """Recent arXiv papers for the query in `url`, newest first, time-windowed."""
    import feedparser  # lazy import so other sources still work if it's missing

    if "max_results" not in url:
        url += ("&" if "?" in url else "?") + f"max_results={ARXIV_MAX_RESULTS}"
    feed = feedparser.parse(_get(url, timeout=40))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in feed.entries:
        published = _published(e)
        if published and published < cutoff:
            continue
        title = e.title.replace("\n", " ").strip()
        summary = e.summary.replace("\n", " ").strip()
        if not ARXIV_TOPIC_PATTERN.search(f"{title} {summary}"):
            continue
        out.append(
            {
                "title": title,
                "authors": [a.name for a in getattr(e, "authors", [])][:8],
                "summary": summary[:ARXIV_SUMMARY_CHARS],
                "url": e.link,
                "published": published.isoformat() if published else None,
                "categories": [t.term for t in getattr(e, "tags", [])],
            }
        )
    return out[:ARXIV_MAX_KEPT]


def fetch_hf_daily_papers(url: str, date: str | None = None) -> list[dict]:
    """Hugging Face Daily Papers feed (curated, upvoted AI papers)."""
    if date:
        url += ("&" if "?" in url else "?") + "date=" + urllib.parse.quote(date)
    data = json.loads(_get(url))
    out = []
    for item in data:
        paper = item.get("paper", {})
        out.append(
            {
                "title": (paper.get("title") or item.get("title", "")).strip(),
                "summary": (paper.get("summary") or "").replace("\n", " ").strip(),
                "upvotes": paper.get("upvotes"),
                "arxiv_id": paper.get("id"),
                "url": f"https://huggingface.co/papers/{paper.get('id')}"
                if paper.get("id")
                else item.get("url"),
            }
        )
    out.sort(key=lambda p: (p.get("upvotes") or 0), reverse=True)
    return out


def fetch_hacker_news(url: str, hours: int, min_points: int = 40) -> list[dict]:
    """AI-related HN stories from the window, by points."""
    since = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}numericFilters=created_at_i>{since},points>{min_points}&hitsPerPage=80"
    hits = json.loads(_get(full)).get("hits", [])
    out = []
    for h in hits:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        if not AI_PATTERN.search(title):
            continue
        out.append(
            {
                "title": title,
                "points": h.get("points"),
                "num_comments": h.get("num_comments"),
                "url": h.get("url")
                or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            }
        )
    out.sort(key=lambda s: (s.get("points") or 0), reverse=True)
    return out[:15]


def fetch_github_releases(url: str, hours: int) -> list[dict]:
    """GitHub repo releases in the window (e.g. llama.cpp)."""
    data = json.loads(_get(url))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for r in data:
        ts = r.get("published_at") or r.get("created_at")
        published = (
            datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        )
        if published and published < cutoff:
            continue
        out.append(
            {
                "title": (r.get("name") or r.get("tag_name") or "").strip(),
                "tag": r.get("tag_name"),
                "summary": (r.get("body") or "").replace("\r\n", " ").strip()[:1000],
                "url": r.get("html_url"),
                "published": published.isoformat() if published else None,
            }
        )
    return out


def dispatch_api(url: str, hours: int, hf_date: str | None) -> list[dict]:
    """Route an `api` source to the right fetcher by its URL shape."""
    if "export.arxiv.org" in url:
        return fetch_arxiv(url, hours)
    if "huggingface.co/api/daily_papers" in url:
        return fetch_hf_daily_papers(url, hf_date)
    if "hn.algolia.com" in url:
        return fetch_hacker_news(url, hours)
    if "api.github.com" in url and "/releases" in url:
        return fetch_github_releases(url, hours)
    raise ValueError(f"no api handler for URL shape: {url}")


# --- rss sources, generic --------------------------------------------------

def fetch_rss(url: str, hours: int) -> list[dict]:
    """Parse an RSS/Atom feed, keep items inside the time window, newest first."""
    import feedparser

    feed = feedparser.parse(_get(url, timeout=40))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in feed.entries:
        published = _published(e)
        if published and published < cutoff:
            continue
        summary = (getattr(e, "summary", "") or "").replace("\n", " ").strip()
        out.append(
            {
                "title": (getattr(e, "title", "") or "").replace("\n", " ").strip(),
                "summary": summary[:1000],
                "url": getattr(e, "link", ""),
                "published": published.isoformat() if published else None,
            }
        )
    # Newest first when we have dates; otherwise feed order.
    out.sort(key=lambda i: i.get("published") or "", reverse=True)
    return out[:RSS_MAX_ITEMS]


def safe(label: str, fn, *args):
    try:
        result = fn(*args)
        print(f"  [ok]   {label}: {len(result)} items", file=sys.stderr)
        return result, None
    except Exception as exc:  # noqa: BLE001 - we want every source isolated
        print(f"  [WARN] {label} failed: {exc}", file=sys.stderr)
        return [], f"{label}: {exc}"


def load_structured() -> list[dict]:
    """All watchlist sources with method rss|api, both tiers (fetch is agent-side).

    Pulling a machine feed is cheap and deterministic, so tier doesn't gate the
    fetch — importance is judged downstream by the writer.
    """
    import yaml

    with open(SOURCES_YAML) as f:
        cfg = yaml.safe_load(f)
    return [s for s in cfg.get("sources", []) if s.get("method") in ("rss", "api")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=48,
                    help="look-back window. >=48 so arXiv's daily announce gap "
                         "(newest papers can be ~28h old) doesn't zero out the feed")
    ap.add_argument("--out", default="out/sources.json")
    ap.add_argument("--hf-date", default=None, help="YYYY-MM-DD; default = today")
    args = ap.parse_args()

    print("Fetching structured sources (rss/api from sources.yaml, both tiers)...",
          file=sys.stderr)
    sources = load_structured()

    feeds: dict[str, list[dict]] = {}
    errors: list[str] = []
    for s in sources:
        name, method, url = s["name"], s["method"], s["url"]
        if method == "api":
            items, err = safe(name, dispatch_api, url, args.hours, args.hf_date)
            time.sleep(1)  # be polite to APIs (esp. arXiv)
        else:  # rss
            items, err = safe(name, fetch_rss, url, args.hours)
        for it in items:
            it["source"] = name
        feeds[name] = items
        if err:
            errors.append(err)

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        "feeds": feeds,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    total = sum(len(v) for v in feeds.values())
    print(
        f"Wrote {args.out}: {len(feeds)} feeds, {total} items total. "
        f"Errors: {len(errors)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
