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

from feedgen.feed import FeedGenerator

CATALOG_FILE = "episodes.json"   # github: repo root; s3: bucket key
HISTORY_FILE = "history.json"    # show memory; written by update_history.py, persisted here
FEED_NAME = "feed.xml"
DOCS = "docs"                    # GitHub Pages source folder (main branch /docs)


# ---------------------------------------------------------------- shared helpers
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

    for ep in sorted(catalog, key=lambda e: e["date"], reverse=True):  # newest first
        fe = fg.add_entry()
        fe.id(ep["guid"])
        fe.title(ep["title"])
        fe.description(ep.get("summary", ""))
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
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    backend_name = os.environ.get("PUBLISH_BACKEND", "github").lower()
    backend = GitHubBackend() if backend_name == "github" else S3Backend()
    print(f"Backend: {backend_name}")

    duration = ffprobe_seconds(args.mp3)
    size = os.path.getsize(args.mp3)
    tag = f"ep-{args.date}"
    pub_dt = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)

    print(f"Uploading {args.mp3} ({size/1e6:.1f} MB, {hhmmss(duration)})...")
    mp3_url = backend.upload_audio(args.mp3, tag, args.title, args.summary)

    catalog = backend.load_catalog()
    guid = f"daily-ai-{args.date}"
    catalog = [e for e in catalog if e["guid"] != guid]  # idempotent
    catalog.append({
        "guid": guid,
        "title": args.title,
        "summary": args.summary,
        "date": args.date,
        "pub_date": pub_dt.isoformat(),  # ISO; build_feed parses it with fromisoformat
        "mp3_url": mp3_url,
        "bytes": size,
        "duration_seconds": duration,
    })

    feed = build_feed(catalog, feed_self_url=backend.feed_self_url,
                      cover_url=backend.cover_url)
    backend.publish_feed(feed)
    backend.save_catalog(catalog, f"Publish episode {args.date}")

    print(f"Published. Audio: {mp3_url}")
    print(f"Feed: {backend.feed_self_url}  ({len(catalog)} episodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
