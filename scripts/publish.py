#!/usr/bin/env python3
"""Publish today's episode: upload the MP3 and rebuild the podcast RSS feed.

GitHub-native hosting: audio goes up as a GitHub Release asset (per-episode tag);
feed.xml + cover + episode pages are committed to docs/ and served by GitHub Pages.
No storage creds — uses the locally authenticated `gh` CLI + git.

ffprobe reads the exact duration; feedgen builds an iTunes-compatible feed. ffmpeg
(ffprobe) must be on PATH. The episode catalog (episodes.json) is the source of
truth the feed is rebuilt from.

Title/date/summary can be given explicitly or derived from the built episode files:
  python scripts/publish.py --episode out/episode.json --meta out/episode_meta.json \
      --mp3 "out/podcast-2026-06-09*.mp3" --notes out/shownotes.md
(--mp3 accepts a glob; the newest match is published, and no match is a hard error.)

Env: PAGES_URL (optional, for a custom domain), COVER_SRC (default
     assets/podcast_cover.png), SHOW_TITLE, SHOW_DESC, SHOW_AUTHOR, OWNER_EMAIL,
     SHOW_CATEGORY.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

import markdown as md
from feedgen.feed import FeedGenerator

CATALOG_FILE = "episodes.json"   # repo root; the feed is rebuilt from it
HISTORY_FILE = "history.json"    # show memory; written by update_history.py, persisted here
ARCHIVE_DIR = "archive"          # past scripts (archive/scripts/), copied by run_episode.sh
FEED_NAME = "feed.xml"
DOCS = "docs"                    # GitHub Pages source folder (main branch /docs)
EPISODES_DIR = "episodes"        # per-episode HTML notes pages (under DOCS / bucket)
READS_DIR = "reads"              # weekly-read EPUBs (under DOCS), built by make_epub.py


# Audio tags ([laughs], [sighs], ...) are TTS delivery directions; strip any that
# leak into summary/notes text. The (?!\() lookahead protects markdown links.
TAG_RE = re.compile(r"\[[a-z][a-z ,'-]{0,38}\](?!\()")


def strip_audio_tags(text: str) -> str:
    return re.sub(r"  +", " ", TAG_RE.sub("", text))


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


SPEAKER_NAMES = {"A": "Ada", "B": "Alan", "C": "Guest"}
SPEAKER_LINE_RE = re.compile(r"^([ABC])\s*:\s?(.*)$")
CHAPTER_LINE_RE = re.compile(r"^##\s+(.+)$")


def transcript_section_html(script_path: str) -> str:
    """Chapter list + collapsible transcript from an archived script.txt.

    Best-effort: returns "" when the archive has no script for the episode
    (pre-archive episodes). Audio tags are stripped; `##` markers become the
    chapter list and headings inside the transcript.
    """
    if not os.path.exists(script_path):
        return ""
    chapters: list[str] = []
    body: list[str] = []
    with open(script_path, encoding="utf-8") as f:
        for raw in f:
            line = strip_audio_tags(raw.strip())
            if not line:
                continue
            c = CHAPTER_LINE_RE.match(line)
            if c:
                chapters.append(c.group(1).strip())
                body.append(f"<h3>{c.group(1).strip()}</h3>")
                continue
            m = SPEAKER_LINE_RE.match(line)
            if m:
                name = SPEAKER_NAMES.get(m.group(1), m.group(1))
                body.append(f"<p><b>{name}:</b> {m.group(2).strip()}</p>")
            elif body and body[-1].endswith("</p>"):
                body[-1] = body[-1][:-4] + " " + line + "</p>"  # wrapped line
    if not body:
        return ""
    chap_html = ""
    if chapters:
        items = "\n".join(f"<li>{c}</li>" for c in chapters)
        chap_html = f"<h2>In this episode</h2>\n<ol>\n{items}\n</ol>\n"
    return (f"{chap_html}<details><summary>Transcript</summary>\n"
            + "\n".join(body) + "\n</details>")


def episode_page_html(title: str, date: str, notes_html: str, mp3_url: str,
                      extra_html: str = "") -> str:
    """A standalone per-episode notes page for GitHub Pages."""
    show = os.environ.get("SHOW_TITLE", "Self-Attention")
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
{extra_html}
<footer><a href="../index.html">← All episodes</a></footer>
</body></html>"""


def index_page_html(catalog: list[dict], reads: list[str] | None = None) -> str:
    """A simple episodes index for GitHub Pages, newest first."""
    show = os.environ.get("SHOW_TITLE", "Self-Attention")
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
    fg.title(os.environ.get("SHOW_TITLE", "Self-Attention"))
    fg.link(href=feed_self_url, rel="self")
    fg.link(href=site_link, rel="alternate")
    fg.description(os.environ.get("SHOW_DESC", "A daily AI news briefing."))
    fg.language("en")
    fg.podcast.itunes_author(os.environ.get("SHOW_AUTHOR", "Self-Attention"))
    fg.podcast.itunes_owner(
        os.environ.get("SHOW_AUTHOR", "Self-Attention"),
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
            digest = hashlib.sha256(open(cover_src, "rb").read()).hexdigest()[:8]
            self._cover_filename = f"cover-{digest}.png"
            shutil.copyfile(cover_src, os.path.join(DOCS, self._cover_filename))
        else:
            print(f"WARNING: cover not found at {cover_src}; Spotify requires show art")
            self._cover_filename = "cover.png"

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
        return f"{self.pages_base}/{self._cover_filename}"

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
            extra = transcript_section_html(
                os.path.join(ARCHIVE_DIR, "scripts", f"{page_name(ep)}.txt"))
            html = episode_page_html(ep["title"], ep["date"],
                                     ep.get("summary_html", f"<p>{ep.get('summary','')}</p>"),
                                     ep["mp3_url"], extra_html=extra)
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
        if os.path.isdir(ARCHIVE_DIR):            # persist the script archive too
            add.append(ARCHIVE_DIR)
        # Listener-tunable files the writer may update in response to feedback,
        # plus the deep-dive proposal ledger the picker maintains.
        for extra in ("listener.yaml", "feedback.md", "config/pronunciations.yaml",
                      "deepdive_proposals.json"):
            if os.path.exists(extra):
                add.append(extra)
        subprocess.run(add, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            subprocess.run(["git", "commit", "-m", message], check=True)
            subprocess.run(["git", "push"], check=True)
        else:
            print("Nothing changed to commit.")


# ---------------------------------------------------------------- orchestration
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mp3", required=True, help="MP3 path or glob (newest match wins)")
    ap.add_argument("--title", default="", help="explicit title; else from --episode")
    ap.add_argument("--summary", default="", help="explicit summary; else from --meta")
    ap.add_argument("--notes", default="", help="path to shownotes.md (full show notes)")
    ap.add_argument("--date", default="", help="YYYY-MM-DD; else from --episode")
    ap.add_argument("--episode", default="", help="built episode.json to derive title/date from")
    ap.add_argument("--meta", default="", help="episode_meta.json to derive the summary from")
    ap.add_argument("--slug", default="daily",
                    help="episode kind; 'daily' (default) or e.g. 'deepdive' so a "
                         "second same-day episode gets its own guid/tag/page")
    args = ap.parse_args()

    # Derive what wasn't given explicitly from the built episode files — this is
    # how run_episode.sh calls it (no inline shims in the harness).
    if args.episode:
        with open(args.episode) as f:
            ep_json = json.load(f)
        args.title = args.title or ep_json.get("title", "")
        args.date = args.date or ep_json.get("date", "")
    if args.meta and os.path.exists(args.meta):
        with open(args.meta) as f:
            args.summary = args.summary or (json.load(f).get("summary", "") or "")[:600]
    if not args.title or not args.date:
        ap.error("need --title and --date (explicitly or via --episode)")

    mp3_matches = sorted(glob.glob(args.mp3))
    assert mp3_matches, f"no MP3 matches {args.mp3!r} — not publishing a stale episode"
    args.mp3 = mp3_matches[-1]

    # Feed titles distinguish the episode kind: deep dives get a standing prefix
    # (the daily stays unprefixed). Idempotent for titles that already carry it.
    if args.slug == "deepdive" and not args.title.lower().startswith("deep dive"):
        args.title = f"Deep Dive: {args.title}"

    args.summary = strip_audio_tags(args.summary)
    summary_html = ""
    if args.notes and os.path.exists(args.notes):
        with open(args.notes) as f:
            summary_html = notes_to_html(strip_audio_tags(f.read()))

    backend = GitHubBackend()

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
    print(f"Notes page: {backend.pages_base}/{EPISODES_DIR}/{stem}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
