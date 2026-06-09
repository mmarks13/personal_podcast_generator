#!/usr/bin/env python3
"""Pull the structured AI sources for the daily podcast.

Covers the feeds that have clean, stable APIs:
  - arXiv recent submissions (cs.AI / cs.CL / cs.LG)
  - Hugging Face Daily Papers
  - Hacker News (Algolia) AI-related front-page stories

Each source is wrapped in its own try/except so one outage never kills the run.
Product launches / blog announcements are intentionally NOT here — the agent
gathers those with its own web tools (see the skill).

Usage:
    python scripts/fetch_sources.py --hours 28 --out out/sources.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ARXIV_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG"]
AI_KEYWORDS = (
    "ai", "llm", "gpt", "claude", "gemini", "model", "agent", "neural",
    "transformer", "diffusion", "openai", "anthropic", "deepmind", "rag",
)
USER_AGENT = "daily-ai-podcast/1.0 (personal project)"


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_arxiv(hours: int, max_results: int = 40) -> list[dict]:
    """Recent arXiv papers in the target categories, newest first."""
    import feedparser  # lazy import so other sources still work if it's missing

    cat_q = "+OR+".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query={cat_q}"
        "&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    feed = feedparser.parse(_get(url, timeout=40))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in feed.entries:
        published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        if published < cutoff:
            continue
        out.append(
            {
                "title": e.title.replace("\n", " ").strip(),
                "authors": [a.name for a in getattr(e, "authors", [])][:8],
                "summary": e.summary.replace("\n", " ").strip(),
                "url": e.link,
                "published": published.isoformat(),
                "categories": [t.term for t in getattr(e, "tags", [])],
            }
        )
    return out


def fetch_hf_daily_papers(date: str | None = None) -> list[dict]:
    """Hugging Face Daily Papers feed (curated, upvoted AI papers)."""
    url = "https://huggingface.co/api/daily_papers"
    if date:
        url += "?date=" + urllib.parse.quote(date)
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
    # Most-upvoted first.
    out.sort(key=lambda p: (p.get("upvotes") or 0), reverse=True)
    return out


def fetch_hacker_news(hours: int, min_points: int = 40) -> list[dict]:
    """AI-related HN stories from the window, by points."""
    since = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    url = (
        "https://hn.algolia.com/api/v1/search_by_date?tags=story"
        f"&numericFilters=created_at_i>{since},points>{min_points}"
        "&hitsPerPage=80"
    )
    hits = json.loads(_get(url)).get("hits", [])
    out = []
    for h in hits:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        if not any(k in title.lower() for k in AI_KEYWORDS):
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


def safe(label: str, fn, *args):
    try:
        result = fn(*args)
        print(f"  [ok]   {label}: {len(result)} items", file=sys.stderr)
        return result, None
    except Exception as exc:  # noqa: BLE001 - we want every source isolated
        print(f"  [WARN] {label} failed: {exc}", file=sys.stderr)
        return [], f"{label}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=28, help="look-back window")
    ap.add_argument("--out", default="out/sources.json")
    ap.add_argument("--hf-date", default=None, help="YYYY-MM-DD; default = today")
    args = ap.parse_args()

    print("Fetching structured sources...", file=sys.stderr)
    arxiv, e1 = safe("arXiv", fetch_arxiv, args.hours)
    time.sleep(1)  # be polite to arXiv
    hf, e2 = safe("HF Daily Papers", fetch_hf_daily_papers, args.hf_date)
    hn, e3 = safe("Hacker News", fetch_hacker_news, args.hours)

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.hours,
        "papers_arxiv": arxiv,
        "papers_hf": hf,
        "hn_stories": hn,
        "errors": [e for e in (e1, e2, e3) if e],
    }

    import os

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    total = len(arxiv) + len(hf) + len(hn)
    print(
        f"Wrote {args.out}: {len(arxiv)} arXiv, {len(hf)} HF, {len(hn)} HN "
        f"({total} total). Errors: {len(bundle['errors'])}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
