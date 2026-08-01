#!/usr/bin/env python3
"""Focused, offline tests for structured source parsing."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fetch_sources as fs  # noqa: E402


class FetchSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        fs._reddit_token = None

    def test_hf_daily_sorting_metadata_and_top_limit(self) -> None:
        payload = [
            {
                "paper": {
                    "id": "2601.00001",
                    "title": "Lower voted",
                    "summary": "line one\nline two",
                    "upvotes": 4,
                    "authors": [{"name": "Ada"}],
                },
                "numComments": 2,
            },
            {
                "paper": {
                    "id": "2601.00002",
                    "title": "Higher voted",
                    "upvotes": 90,
                    "organization": {"name": "Example Lab"},
                    "githubRepo": "example/repo",
                    "projectPage": "https://example.test/project",
                }
            },
        ]
        with mock.patch.object(fs, "_get", return_value=json.dumps(payload).encode()):
            papers = fs.fetch_hf_daily_papers(
                "https://huggingface.co/api/daily_papers", top=1
            )

        self.assertEqual([paper["title"] for paper in papers], ["Higher voted"])
        self.assertEqual(papers[0]["organization"], "Example Lab")
        self.assertEqual(papers[0]["github_repo"], "example/repo")
        self.assertEqual(papers[0]["url"], "https://huggingface.co/papers/2601.00002")

    def test_hf_aged_pool_deduplicates_and_keeps_highest_vote_snapshot(self) -> None:
        pages = {
            "2026-08-01": [
                {"arxiv_id": "a", "title": "A", "upvotes": 5},
                {"arxiv_id": "b", "title": "B", "upvotes": 8},
            ],
            "2026-07-31": [
                {"arxiv_id": "a", "title": "A", "upvotes": 12},
            ],
        }
        with mock.patch.object(fs, "datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 8, 2, tzinfo=timezone.utc)
            pool = fs.hf_top_from_pages(pages, days=7, top=10)

        self.assertEqual([paper["arxiv_id"] for paper in pool], ["a", "b"])
        self.assertEqual(pool[0]["upvotes"], 12)
        self.assertEqual(pool[0]["listed_on"], "2026-07-31")

    def test_reddit_post_preserves_metadata_and_filters_stickied(self) -> None:
        listing = {
            "data": {
                "children": [
                    {"data": {"title": "Pinned", "stickied": True}},
                    {
                        "data": {
                            "title": "Useful benchmark discussion",
                            "selftext": "Details",
                            "score": 42,
                            "upvote_ratio": 0.91,
                            "num_comments": 7,
                            "link_flair_text": "Discussion",
                            "author": "tester",
                            "created_utc": 1_700_000_000,
                            "url": "https://example.test/benchmark",
                            "permalink": "/r/test/comments/abc/useful/",
                        }
                    },
                ]
            }
        }
        comments = [{"author": "reader", "score": 3, "body": "Useful caveat"}]
        with mock.patch.object(fs, "_reddit_get", return_value=listing), mock.patch.object(
            fs, "fetch_reddit_comments", return_value=comments
        ), mock.patch.object(fs.time, "sleep"):
            posts = fs.fetch_reddit("https://oauth.reddit.com/r/test/top?t=day&limit=10")

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["score"], 42)
        self.assertEqual(posts[0]["flair"], "Discussion")
        self.assertEqual(posts[0]["top_comments"], comments)
        self.assertEqual(posts[0]["discussion"], "https://www.reddit.com/r/test/comments/abc/useful/")

    def test_reddit_comment_failures_do_not_drop_post(self) -> None:
        listing = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Still useful",
                            "score": 1,
                            "permalink": "/r/test/comments/abc/useful/",
                        }
                    }
                ]
            }
        }
        with mock.patch.object(fs, "_reddit_get", return_value=listing), mock.patch.object(
            fs, "fetch_reddit_comments", side_effect=TimeoutError
        ):
            posts = fs.fetch_reddit("https://oauth.reddit.com/r/test/top")

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["top_comments"], [])

    def test_reddit_credentials_are_required_without_network_access(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "REDDIT_CLIENT_ID"):
                fs.reddit_token()

    def test_dispatch_routes_reddit_and_hf_daily_limit(self) -> None:
        with mock.patch.object(fs, "fetch_reddit", return_value=[]) as reddit:
            fs.dispatch_api("https://oauth.reddit.com/r/test/top", 24, None)
            reddit.assert_called_once()
        with mock.patch.object(fs, "fetch_hf_daily_papers", return_value=[]) as hf:
            fs.dispatch_api("https://huggingface.co/api/daily_papers", 24, "2026-08-01")
            hf.assert_called_once_with(
                "https://huggingface.co/api/daily_papers", "2026-08-01", top=fs.HF_DAILY_TOP
            )


if __name__ == "__main__":
    unittest.main()
