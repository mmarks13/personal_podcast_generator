#!/usr/bin/env python3
"""Publish today's episode: upload the MP3 and rebuild the podcast RSS feed.

Storage backend is swappable via PUBLISH_BACKEND so the 15-minute hosting test can
decide it without touching anything else:

  github  (default)  Audio -> GitHub Release asset (per-episode tag). feed.xml + cover
                     committed to docs/ and served by GitHub Pages. NO storage creds —
                     uses the locally authenticated `gh` CLI + git. Most self-contained.
  s3                 Audio + feed.xml + state -> an S3-compatible bucket (AWS S3 or
                     Cloudflare R2 via S3_ENDPOINT_URL). Needs S3_*/AWS_* creds.

Common: ffprobe reads the exact duration; feedgen builds an iTunes-compatible feed.
ffmpeg (ffprobe) must be on PATH. The episode catalog (episodes.json) is the source of
truth the feed is rebuilt from — kept in the repo for `github`, in the bucket for `s3`.

CLI is identical for both backends (run_episode.sh doesn't change):
  python scripts/publish.py --mp3 out/podcast-2026-06-09.mp3 \
      --title "AI Daily — Jun 9" --summary "Today's papers and releases." --date 2026-06-09

Env (github):  PAGES_URL (optional, for a custom domain), COVER_SRC (default
               assets/podcast_cover.png), SHOW_TITLE, SHOW_DESC, SHOW_AUTHOR,
               OWNER_EMAIL, SHOW_CATEGORY.
Env (s3):      S3_BUCKET, S3_REGION, S3_ENDPOINT_URL (R2 only), AWS_* creds,
               PUBLIC_BASE_URL, COVER_URL, SHOW_* / OWNER_EMAIL as above.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import markdown as md
from feedgen.feed import FeedGenerator

CATALOG_FILE = "episodes.json"   # github: repo root; s3: bucket key
HISTORY_FILE = "history.json"    # show memory; written by update_history.py, persisted here
FEED_NAME = "feed.xml"
DOCS = "docs"                    # GitHub Pages source folder (main branch /docs)
EPISODES_DIR = "episodes"        # per-episode HTML notes pages (under DOCS / bucket)
READS_DIR = "reads"              # weekly-read EPUBs (under DOCS), built by make_epub.py


# ---------------------------------------------------------------- shared helpers
def page_name(ep: dict) -> str:
    """Filename stem for an episode's notes page; daily keeps the bare date."""
    slug = ep.get("slug", "daily")
    return ep["date"] if slug == "daily" else f"{ep['date']}-{slug}"


def ffprobe_seconds(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(float(out))


def hhmmss(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def notes_to_html(notes_md: str) -> str:
    """Convert shownotes.md to the HTML used in <content:encoded> and the web page.

    The skill writes the notes as: an H1 title, a bold date line, the summary
    paragraph, then '## Papers / ## Releases / ## Industry & Discussion' sections of
    linked sources. The H1/date are redundant with the feed's own title/pubDate, so we
    drop the leading H1 and render from the summary down.
    """
    lines = notes_md.splitlines()
    # Drop a leading H1 (the episode title) if present; keep everything after it.
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    return md.markdown(body, output_format="html5")


def episode_page_html(title: str, date: str, notes_html: str, mp3_url: str) -> str:
    """A standalone per-episode notes page for GitHub Pages."""
    show = os.environ.get("SHOW_TITLE", "AI Daily")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {show}</title>
<style>
  body {{ max-width: 720px; margin: 2rem auto; padding: 0 1rem;
         font: 16px/1.6 -apple-system, system-ui, sans-serif; color: #1a1a1a; }}
  h1 {{ font-size: 1.5rem; line-height: 1.25; }}
  .date {{ color: #666; margin-bottom: 1.5rem; }}
  audio {{ width: 100%; margin: 1rem 0 2rem; }}
  h2 {{ margin-top: 2rem; font-size: 1.15rem; }}
  a {{ color: #0b5fff; }}
  footer {{ margin-top: 3rem; color: #888; font-size: 0.9rem; }}
</style></head><body>
<h1>{title}</h1>
<div class="date">{show} — {date}</div>
<audio controls preload="none" src="{mp3_url}"></audio>
{notes_html}
<footer><a href="../index.html">← All episodes</a></footer>
</body></html>"""


def index_page_html(catalog: list[dict], reads: list[str] | None = None) -> str:
    """A simple episodes index for GitHub Pages, newest first."""
    show = os.environ.get("SHOW_TITLE", "AI Daily")
    desc = os.environ.get("SHOW_DESC", "A daily AI news briefing.")
    rows = []
    for ep in sorted(catalog, key=lambda e: e["date"], reverse=True):
        kind = "" if ep.get("slug", "daily") == "daily" else f' · {ep["slug"]}'
        rows.append(
            f'<li><a href="{EPISODES_DIR}/{page_name(ep)}.html">{ep["title"]}</a>'
            f'<div class="meta">{ep["date"]}{kind}</div></li>'
        )
    items = "\n".join(rows) or "<li>No episodes yet.</li>"
    reads_html = ""
    if reads:
        links = "\n".join(
            f'<li><a href="{READS_DIR}/{r}">{r}</a></li>' for r in sorted(reads, reverse=True)
        )
        reads_html = f"<h2>Weekly reads (EPUB)</h2>\n<ul>\n{links}\n</ul>"
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{show}</title>
<style>
  body {{ max-width: 720px; margin: 2rem auto; padding: 0 1rem;
         font: 16px/1.6 -apple-system, system-ui, sans-serif; color: #1a1a1a; }}
  h1 {{ font-size: 1.6rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 0.75rem 0; border-bottom: 1px solid #eee; }}
  li a {{ font-weight: 600; color: #0b5fff; text-decoration: none; }}
  .meta {{ color: #777; font-size: 0.9rem; }}
  .lead {{ color: #555; }}
</style></head><body>
<h1>{show}</h1>
<p class="lead">{desc}</p>
<ul>
{items}
</ul>
{reads_html}
</body></html>"""


def build_feed(catalog: list[dict], *, feed_self_url: str, cover_url: str) -> bytes:
    """Build an iTunes-compatible RSS feed from the episode catalog."""
    site_link = feed_self_url.rsplit("/", 1)[0] or feed_self_url
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(os.environ.get("SHOW_TITLE", "AI Daily"))
    fg.link(href=feed_self_url, rel="self")
    fg.link(href=site_link, rel="alternate")
    fg.description(os.environ.get("SHOW_DESC", "A daily AI news briefing."))
    fg.language("en")
    fg.podcast.itunes_author(os.environ.get("SHOW_AUTHOR", "AI Daily"))
    fg.podcast.itunes_owner(
        os.environ.get("SHOW_AUTHOR", "AI Daily"),
        os.environ["OWNER_EMAIL"],  # the address Spotify emails the claim code to
    )
    fg.podcast.itunes_category(os.environ.get("SHOW_CATEGORY", "Technology"))
    fg.podcast.itunes_explicit("no")
    if cover_url:
        fg.podcast.itunes_image(cover_url)
        fg.image(url=cover_url, title=fg.title(), link=site_link)

    # feedgen prepends each add_entry, so iterate oldest-first to get a
    # newest-first feed.
    for ep in sorted(catalog, key=lambda e: e["date"]):
        fe = fg.add_entry()
        fe.id(ep["guid"])
        fe.title(ep["title"])
        # Full show notes (summary + linked sources) as HTML in <description>, which
        # Spotify/Apple render; the plain summary goes in <itunes:summary>. Fall back
        # to the plain summary for older episodes with no stored HTML.
        notes_html = ep.get("summary_html")
        if notes_html:
            fe.description(notes_html, isSummary=False)
        else:
            fe.description(ep.get("summary", ""))
        fe.podcast.itunes_summary(ep.get("summary", ""))
        fe.enclosure(ep["mp3_url"], str(ep["bytes"]), "audio/mpeg")
        fe.published(datetime.fromisoformat(ep["pub_date"]))
        fe.podcast.itunes_duration(hhmmss(ep["duration_seconds"]))
    return fg.rss_str(pretty=True)


# ---------------------------------------------------------------- github backend
class GitHubBackend:
    """Audio in Releases; feed + cover committed to docs/ for GitHub Pages."""

    def __init__(self):
        self.owner_repo = self._owner_repo()
        owner, repo = self.owner_repo.split("/", 1)
        self.pages_base = os.environ.get(
            "PAGES_URL", f"https://{owner}.github.io/{repo}"
        ).rstrip("/")
        os.makedirs(DOCS, exist_ok=True)
        open(os.path.join(DOCS, ".nojekyll"), "a").close()  # serve files raw
        cover_src = os.environ.get("COVER_SRC", "assets/podcast_cover.png")
        if os.path.exists(cover_src):
            shutil.copyfile(cover_src, os.path.join(DOCS, "cover.png"))
        else:
            print(f"WARNING: cover not found at {cover_src}; Spotify requires show art")

    @staticmethod
    def _owner_repo() -> str:
        try:
            r = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                capture_output=True, text=True, check=True,
            )
            if r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
        if os.environ.get("GITHUB_REPOSITORY"):
            return os.environ["GITHUB_REPOSITORY"]
        raise RuntimeError("Can't determine owner/repo — run inside the repo or set GITHUB_REPOSITORY")

    @property
    def feed_self_url(self) -> str:
        return f"{self.pages_base}/{FEED_NAME}"

    @property
    def cover_url(self) -> str:
        return f"{self.pages_base}/cover.png"

    def upload_audio(self, mp3: str, tag: str, title: str, notes: str) -> str:
        exists = subprocess.run(["gh", "release", "view", tag],
                                capture_output=True).returncode == 0
        if exists:  # idempotent re-run for the same day
            subprocess.run(["gh", "release", "upload", tag, mp3, "--clobber"], check=True)
        else:
            subprocess.run(["gh", "release", "create", tag, mp3,
                            "-t", title, "-n", notes or title], check=True)
        fname = os.path.basename(mp3)
        return f"https://github.com/{self.owner_repo}/releases/download/{tag}/{fname}"

    def load_catalog(self) -> list[dict]:
        if os.path.exists(CATALOG_FILE):
            with open(CATALOG_FILE) as f:
                return json.load(f)
        return []

    def publish_feed(self, feed_bytes: bytes) -> None:
        with open(os.path.join(DOCS, FEED_NAME), "wb") as f:
            f.write(feed_bytes)

    def publish_pages(self, catalog: list[dict]) -> None:
        """Write a per-episode notes page + an episodes index into docs/ (Pages)."""
        ep_dir = os.path.join(DOCS, EPISODES_DIR)
        os.makedirs(ep_dir, exist_ok=True)
        for ep in catalog:
            html = episode_page_html(ep["title"], ep["date"],
                                     ep.get("summary_html", f"<p>{ep.get('summary','')}</p>"),
                                     ep["mp3_url"])
            with open(os.path.join(ep_dir, f"{page_name(ep)}.html"), "w") as f:
                f.write(html)
        reads_dir = os.path.join(DOCS, READS_DIR)
        reads = sorted(os.listdir(reads_dir)) if os.path.isdir(reads_dir) else []
        reads = [r for r in reads if r.endswith(".epub")]
        with open(os.path.join(DOCS, "index.html"), "w") as f:
            f.write(index_page_html(catalog, reads))

    def save_catalog(self, catalog: list[dict], message: str) -> None:
        with open(CATALOG_FILE, "w") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
        add = ["git", "add", DOCS, CATALOG_FILE]
        if os.path.exists(HISTORY_FILE):          # persist the show's memory too
            add.append(HISTORY_FILE)
        subprocess.run(add, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            subprocess.run(["git", "commit", "-m", message], check=True)
            subprocess.run(["git", "push"], check=True)
        else:
            print("Nothing changed to commit.")


# ---------------------------------------------------------------- s3 / r2 backend
class S3Backend:
    """Audio + feed + state in an S3-compatible bucket (AWS S3 or Cloudflare R2)."""

    def __init__(self):
        import boto3  # lazy: only needed for this backend
        self.bucket = os.environ["S3_BUCKET"]
        self.base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
        self.s3 = boto3.client(
            "s3",
            region_name=os.environ.get("S3_REGION"),
            endpoint_url=os.environ.get("S3_ENDPOINT_URL"),  # None for AWS, set for R2
        )

    @property
    def feed_self_url(self) -> str:
        return f"{self.base}/{FEED_NAME}"

    @property
    def cover_url(self) -> str:
        return os.environ.get("COVER_URL", f"{self.base}/cover.png")

    def upload_audio(self, mp3: str, tag: str, title: str, notes: str) -> str:
        key = f"episodes/{os.path.basename(mp3)}"
        self.s3.upload_file(mp3, self.bucket, key,
                            ExtraArgs={"ContentType": "audio/mpeg"})
        return f"{self.base}/{key}"

    def load_catalog(self) -> list[dict]:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=CATALOG_FILE)
            return json.loads(obj["Body"].read())
        except Exception:
            return []

    def publish_feed(self, feed_bytes: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=FEED_NAME, Body=feed_bytes,
                           ContentType="application/rss+xml")

    def publish_pages(self, catalog: list[dict]) -> None:
        """Write per-episode notes pages + an index into the bucket."""
        for ep in catalog:
            html = episode_page_html(ep["title"], ep["date"],
                                     ep.get("summary_html", f"<p>{ep.get('summary','')}</p>"),
                                     ep["mp3_url"])
            self.s3.put_object(Bucket=self.bucket,
                               Key=f"{EPISODES_DIR}/{page_name(ep)}.html",
                               Body=html.encode(), ContentType="text/html")
        self.s3.put_object(Bucket=self.bucket, Key="index.html",
                           Body=index_page_html(catalog).encode(),
                           ContentType="text/html")

    def save_catalog(self, catalog: list[dict], message: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=CATALOG_FILE,
                           Body=json.dumps(catalog, indent=2).encode(),
                           ContentType="application/json")
        if os.path.exists(HISTORY_FILE):          # persist the show's memory too
            with open(HISTORY_FILE, "rb") as f:
                self.s3.put_object(Bucket=self.bucket, Key=HISTORY_FILE,
                                   Body=f.read(), ContentType="application/json")


# ---------------------------------------------------------------- orchestration
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp3", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--notes", default="", help="path to shownotes.md (full show notes)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--slug", default="daily",
                    help="episode kind; 'daily' (default) or e.g. 'deepdive' so a "
                         "second same-day episode gets its own guid/tag/page")
    args = ap.parse_args()

    summary_html = ""
    if args.notes and os.path.exists(args.notes):
        with open(args.notes) as f:
            summary_html = notes_to_html(f.read())

    backend_name = os.environ.get("PUBLISH_BACKEND", "github").lower()
    backend = GitHubBackend() if backend_name == "github" else S3Backend()
    print(f"Backend: {backend_name}")

    duration = ffprobe_seconds(args.mp3)
    size = os.path.getsize(args.mp3)
    # Daily keeps the original guid/tag shapes so existing episodes are untouched.
    if args.slug == "daily":
        tag, guid = f"ep-{args.date}", f"daily-ai-{args.date}"
    else:
        tag, guid = f"ep-{args.date}-{args.slug}", f"{args.slug}-{args.date}"
    pub_dt = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)

    print(f"Uploading {args.mp3} ({size/1e6:.1f} MB, {hhmmss(duration)})...")
    mp3_url = backend.upload_audio(args.mp3, tag, args.title, args.summary)

    catalog = backend.load_catalog()
    catalog = [e for e in catalog if e["guid"] != guid]  # idempotent
    catalog.append({
        "guid": guid,
        "slug": args.slug,
        "title": args.title,
        "summary": args.summary,
        "summary_html": summary_html,   # full show notes (HTML) for the feed + web page
        "date": args.date,
        "pub_date": pub_dt.isoformat(),  # ISO; build_feed parses it with fromisoformat
        "mp3_url": mp3_url,
        "bytes": size,
        "duration_seconds": duration,
    })

    feed = build_feed(catalog, feed_self_url=backend.feed_self_url,
                      cover_url=backend.cover_url)
    backend.publish_feed(feed)
    backend.publish_pages(catalog)
    backend.save_catalog(catalog, f"Publish episode {args.date}")

    print(f"Published. Audio: {mp3_url}")
    print(f"Feed: {backend.feed_self_url}  ({len(catalog)} episodes)")
    stem = args.date if args.slug == "daily" else f"{args.date}-{args.slug}"
    print(f"Notes page: {backend.pages_base if hasattr(backend,'pages_base') else backend.base}"
          f"/{EPISODES_DIR}/{stem}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
