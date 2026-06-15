#!/usr/bin/env python3
"""Build a Kindle-ready EPUB from the read's markdown.

The read skill writes one markdown file: an H1 title, an optional intro, then
`## `-headed pieces. Each `## ` section becomes an EPUB chapter so the Kindle
table of contents mirrors the magazine's pieces.

Optionally renders a cover: the show's cover image centered on a standard
1600x2560 e-reader canvas, with the book title and a per-issue subtitle set
below it.

Usage:
    python scripts/make_epub.py --md out/daily_read.md \
        --out "docs/reads/self-attention-$(date +%F).epub" \
        --cover-src docs/cover.png \
        --cover-subtitle "Sunday, June 14 · Drift"
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import markdown as md
from ebooklib import epub

STYLE = """
body { font-family: serif; line-height: 1.5; }
h1 { font-size: 1.4em; }
h2 { font-size: 1.2em; }
blockquote { font-style: italic; margin-left: 1em; }
"""


def split_chapters(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (book_title, [(chapter_title, chapter_markdown), ...])."""
    # Drop the mood-word marker (`<!-- mood: X -->`); the cover, not the body, uses it.
    text = re.sub(r"<!--\s*mood:.*?-->\s*", "", text)
    lines = text.splitlines()
    title = "Self Attention"
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]

    chapters: list[tuple[str, str]] = []
    current_title, current_lines = "Today", []
    for line in lines:
        if line.startswith("## "):
            if "".join(current_lines).strip():
                chapters.append((current_title, "\n".join(current_lines)))
            current_title, current_lines = line[3:].strip(), []
        else:
            current_lines.append(line)
    if "".join(current_lines).strip():
        chapters.append((current_title, "\n".join(current_lines)))
    return title, chapters


def _load_font(size: int, bold: bool = False):
    """Best-effort TrueType lookup so the cover text isn't the tiny PIL bitmap default."""
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_cover(src: str, title: str, subtitle: str, out_path: str) -> str:
    """Center the source image on a 1600x2560 canvas; set title + subtitle below it."""
    from PIL import Image, ImageDraw

    W, H = 1600, 2560
    bg = (17, 18, 22)
    fg = (240, 240, 245)
    accent = (170, 174, 190)

    canvas = Image.new("RGB", (W, H), bg)
    art = Image.open(src).convert("RGB")
    # Fit the (square-ish) art into the upper region, leaving a lower band for text.
    art_box = 1180
    scale = min(art_box / art.width, art_box / art.height)
    art = art.resize((round(art.width * scale), round(art.height * scale)))
    art_x = (W - art.width) // 2
    art_y = 240
    canvas.paste(art, (art_x, art_y))

    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(140, bold=True)
    sub_font = _load_font(58)

    text_y = art_y + art.height + 150
    tw = draw.textlength(title, font=title_font)
    draw.text(((W - tw) / 2, text_y), title, font=title_font, fill=fg)

    if subtitle:
        sw = draw.textlength(subtitle, font=sub_font)
        draw.text(((W - sw) / 2, text_y + 200), subtitle, font=sub_font, fill=accent)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    canvas.save(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="out/daily_read.md")
    ap.add_argument("--out", required=True,
                    help="e.g. docs/reads/self-attention-2026-06-14.epub")
    ap.add_argument("--author", default=os.environ.get("SHOW_AUTHOR", "Self Attention"))
    ap.add_argument("--cover-src", help="image to place on the cover (e.g. docs/cover.png)")
    ap.add_argument("--cover-subtitle", default="", help="subtitle under the title")
    args = ap.parse_args()

    with open(args.md) as f:
        text = f.read()
    title, chapters = split_chapters(text)
    if not chapters:
        print(f"{args.md} has no content — not building an EPUB.", file=sys.stderr)
        return 1

    book = epub.EpubBook()
    book.set_identifier(re.sub(r"\W+", "-", os.path.basename(args.out)))
    book.set_title(title)
    book.set_language("en")
    book.add_author(args.author)
    css = epub.EpubItem(uid="style", file_name="style.css",
                        media_type="text/css", content=STYLE.encode())
    book.add_item(css)

    if args.cover_src:
        cover_png = os.path.join(os.path.dirname(args.out) or ".", "_cover.png")
        make_cover(args.cover_src, title, args.cover_subtitle, cover_png)
        with open(cover_png, "rb") as cf:
            book.set_cover("cover.png", cf.read())
        os.remove(cover_png)

    items = []
    for i, (ch_title, ch_md) in enumerate(chapters):
        html = md.markdown(ch_md, output_format="html5")
        ch = epub.EpubHtml(title=ch_title, file_name=f"chap_{i:02d}.xhtml", lang="en")
        ch.content = f"<h2>{ch_title}</h2>\n{html}"
        ch.add_item(css)
        book.add_item(ch)
        items.append(ch)

    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    epub.write_epub(args.out, book)
    print(f"Wrote {args.out}: \"{title}\", {len(items)} pieces, "
          f"{len(text.split())} words.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
