#!/usr/bin/env python3
"""Build a Kindle-ready EPUB from the weekly read's markdown.

The weekly-read skill writes one markdown file: an H1 title, an optional intro,
then `## `-headed pieces. Each `## ` section becomes an EPUB chapter so the
Kindle table of contents mirrors the magazine's pieces.

Usage:
    python scripts/make_epub.py --md out/weekly_read.md \
        --out "docs/reads/weekly-$(date +%F).epub"
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
    lines = text.splitlines()
    title = "Weekly Read"
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]

    chapters: list[tuple[str, str]] = []
    current_title, current_lines = "This Week", []
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="out/weekly_read.md")
    ap.add_argument("--out", required=True, help="e.g. docs/reads/weekly-2026-06-14.epub")
    ap.add_argument("--author", default=os.environ.get("SHOW_AUTHOR", "AI Daily"))
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
