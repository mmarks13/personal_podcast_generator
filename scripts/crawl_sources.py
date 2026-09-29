#!/usr/bin/env python3
"""Crawl HTML-only AI sources for the daily podcast.

Reads config/sources.yaml, extracts sources with method='fetch' (both tiers),
crawls them for today and yesterday only, self-recovers Tier-1 failures via
backup search, and writes out/crawl.json in the source-crawler contract.

Usage:
    python scripts/crawl_sources.py --date 2026-08-13 --out out/crawl.json
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
from typing import Any
from html.parser import HTMLParser

SOURCES_YAML = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")
USER_AGENT = "daily-ai-podcast/1.0 (personal project)"
HTML_TIMEOUT = 40


def _get(url: str, timeout: int = HTML_TIMEOUT) -> str | None:
    """Fetch HTML, return decoded string or None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [FETCH] {url}: {type(e).__name__}", file=sys.stderr)
        return None


def _normalize_url(url: str, base_url: str) -> str:
    """Make URLs absolute, handling relative paths."""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    if url.startswith("#"):
        return ""
    parsed = urllib.parse.urlparse(base_url)
    base_path = parsed.path.rsplit("/", 1)[0] if "/" in parsed.path else "/"
    relative = f"{base_path}/{url}".replace("//", "/")
    return f"{parsed.scheme}://{parsed.netloc}{relative}"


def _parse_dates_in_text(text: str) -> list[datetime]:
    """Extract all date-like strings from text."""
    dates = []
    # ISO format: YYYY-MM-DD
    for match in re.finditer(r"(\d{4}-\d{2}-\d{2})", text):
        try:
            dates.append(datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    # Verbose format: Month D[D], YYYY or Month D[D] YYYY
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for match in re.finditer(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        text, re.IGNORECASE
    ):
        try:
            month = month_map.get(match.group(1).lower())
            day = int(match.group(2))
            year = int(match.group(3))
            dates.append(datetime(year, month, day, tzinfo=timezone.utc))
        except (ValueError, TypeError):
            pass
    return dates


def _is_date_in_window(date: datetime, today_str: str, yesterday_str: str) -> bool:
    """Check if a date falls within the window (today or yesterday)."""
    today = datetime.fromisoformat(today_str).replace(tzinfo=timezone.utc).date()
    yesterday = datetime.fromisoformat(yesterday_str).replace(tzinfo=timezone.utc).date()
    return date.date() in (today, yesterday)


class BlogPageParser(HTMLParser):
    """Parse blog/news pages to extract article-like items."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.items = []
        self.current_article = None
        self.in_heading = False
        self.in_summary = False
        self.text_buffer = []
        self.tag_stack = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.tag_stack.append(tag)
        attrs_dict = dict(attrs)

        if tag in ("article", "div") and any(
            c in attrs_dict.get("class", "").lower() for c in ("post", "article", "item", "entry")
        ):
            self.current_article = {"heading": "", "summary": "", "url": "", "claims": []}

        if tag == "a" and "href" in attrs_dict and self.current_article is not None:
            self.current_article["url"] = _normalize_url(attrs_dict["href"], self.base_url)

        if tag in ("h1", "h2", "h3", "h4", "a") and self.current_article is not None:
            self.in_heading = True

        if tag == "p" and self.current_article is not None:
            self.in_summary = True

    def handle_endtag(self, tag: str) -> None:
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()

        if tag in ("article", "div"):
            if self.current_article and (self.current_article.get("heading") or self.current_article.get("url")):
                self.items.append(self.current_article)
            self.current_article = None

        if tag in ("h1", "h2", "h3", "h4", "a") and self.in_heading:
            text = " ".join(self.text_buffer).strip()
            if self.current_article and len(text) > 5:
                self.current_article["heading"] = text
            self.text_buffer = []
            self.in_heading = False

        if tag == "p" and self.in_summary:
            text = " ".join(self.text_buffer).strip()
            if self.current_article and len(text) > 10:
                self.current_article["summary"] = text
                if text:
                    self.current_article["claims"].append(text[:200])
            self.text_buffer = []
            self.in_summary = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and (self.in_heading or self.in_summary):
            self.text_buffer.append(text)

    def get_items(self) -> list[dict]:
        return self.items


def crawl_page(url: str, source_name: str, date_window: tuple[str, str]) -> list[dict]:
    """Crawl a single HTML page and extract items within the date window."""
    html_content = _get(url)
    if not html_content:
        return []

    today_str, yesterday_str = date_window
    items = []

    # Try structured parsing first (articles, divs with article-like classes).
    parser = BlogPageParser(url)
    try:
        parser.feed(html_content)
    except Exception:
        pass

    parsed_items = parser.get_items()

    # Fallback: regex-based link extraction if parser didn't find much.
    if not parsed_items:
        link_pattern = r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        for match in re.finditer(link_pattern, html_content):
            link_url = match.group(1)
            link_text = match.group(2).strip()

            # Skip navigation.
            if not link_text or len(link_text) < 5 or link_text.lower() in (
                "home", "about", "contact", "privacy", "terms", "search", "next", "previous"
            ):
                continue

            link_url = _normalize_url(link_url, url)
            if not link_url.startswith(("http://", "https://")):
                continue

            parsed_items.append({
                "heading": link_text,
                "summary": link_text[:150],
                "url": link_url,
                "claims": [link_text[:200]] if link_text else [],
            })

    # Filter by date and de-duplicate.
    seen_urls = set()
    for item in parsed_items:
        if not item.get("url") or not item.get("heading"):
            continue

        if item["url"] in seen_urls:
            continue
        seen_urls.add(item["url"])

        # Try to find dates in the item or HTML context around it.
        # For now, we include items from pages dated today/yesterday,
        # or that mention today/yesterday in their content.
        search_start = max(0, html_content.find(item["heading"]) - 500) if item["heading"] in html_content else 0
        search_end = min(len(html_content), html_content.find(item["heading"]) + 500) if item["heading"] in html_content else len(html_content)
        context = html_content[search_start:search_end]

        dates_found = _parse_dates_in_text(context)

        # If we found dates in window, include the item.
        has_recent_date = any(_is_date_in_window(d, today_str, yesterday_str) for d in dates_found)

        # Also check if page itself is recent (has today's or yesterday's date).
        page_has_recent_date = any(
            d in html_content for d in [today_str, yesterday_str, today_str.replace("-", "/"), yesterday_str.replace("-", "/")]
        )

        if has_recent_date or page_has_recent_date or not dates_found:
            # If no dates found, assume page is listing recent content.
            entry = {
                "sources": [source_name],
                "url": item["url"],
                "claims": item.get("claims", [])[:3],
                "summary": item.get("summary", item.get("heading", ""))[:200],
                "why_included": "Found on watchlist page.",
            }
            items.append(entry)

    return items[:20]  # Limit per-source to avoid bloat.


def crawl_source(
    name: str, url: str, tier: int, date_window: tuple[str, str]
) -> tuple[list[dict], dict | None]:
    """Crawl a single fetch source. Returns (items, failure_dict | None)."""
    print(f"  [crawl] {name} (tier {tier})", file=sys.stderr)
    items = crawl_page(url, name, date_window)

    if items:
        print(f"    → {len(items)} items", file=sys.stderr)
        return items, None
    else:
        failure = {
            "url": url,
            "tier": tier,
            "what_happened": "No items found or page failed to load",
            "recovered": None,
        }
        # For Tier-1, try backup search.
        if tier == 1:
            print(f"    [T1 fail] {name}; attempting recovery...", file=sys.stderr)
            query = f'"{name}" announcement {date_window[0][:7]}'
            try:
                search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                search_html = _get(search_url, timeout=20)
                if search_html:
                    # Look for result links.
                    results = re.findall(
                        r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
                        search_html,
                        re.IGNORECASE
                    )[:3]
                    if results:
                        recovered_url = results[0][0]
                        if not recovered_url.startswith("http"):
                            recovered_url = f"https{recovered_url}" if recovered_url.startswith("//") else recovered_url
                        failure["recovered"] = recovered_url
                        item = {
                            "sources": [f"{name} (backup search)"],
                            "url": recovered_url,
                            "claims": ["Recovered via backup search after primary Tier-1 source failed"],
                            "summary": f"Backup search recovery for {name}",
                            "why_included": "Tier-1 source failed; recovered via web search.",
                        }
                        print(f"    [recovered] {recovered_url}", file=sys.stderr)
                        return [item], failure
            except Exception:
                pass

        return [], failure


def load_fetch_sources() -> list[dict]:
    """Load all sources with method='fetch' from config/sources.yaml."""
    import yaml

    with open(SOURCES_YAML) as f:
        cfg = yaml.safe_load(f)
    return [s for s in cfg.get("sources", []) if s.get("method") == "fetch"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Today's date (YYYY-MM-DD); default = today",
    )
    ap.add_argument("--out", default="out/crawl.json")
    args = ap.parse_args()

    today = args.date
    yesterday = (
        datetime.fromisoformat(today).replace(tzinfo=timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    date_window = (today, yesterday)

    print(f"Crawling fetch sources for {today} and {yesterday}...", file=sys.stderr)
    sources = load_fetch_sources()

    all_items: list[dict] = []
    all_failures: list[dict] = []

    for s in sources:
        name, url, tier = s["name"], s["url"], s.get("tier", 2)
        items, failure = crawl_source(name, url, tier, date_window)
        all_items.extend(items)
        if failure:
            all_failures.append(failure)
        time.sleep(1)  # Be polite.

    bundle: dict[str, Any] = {"items": all_items, "failures": all_failures}

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    total_items = len(all_items)
    total_failures = len(all_failures)
    print(
        f"Wrote {args.out}: {total_items} items, {total_failures} failures",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
