#!/usr/bin/env python3
"""Overnight entrypoint: run the daily-ai-podcast skill via the Claude Agent SDK.

This is the programmatic option (vs. `claude -p` or a Routine). It gives you a clean
place to wrap logging/observability, set the model, and constrain tools. The SDK runs
the same agent harness as Claude Code, loading the project skill from .claude/skills/.

Requires: `pip install claude-agent-sdk`, Node.js, and the Claude Code CLI on PATH
(`npm install -g @anthropic-ai/claude-code`). Auth via ANTHROPIC_API_KEY (or Bedrock/
Vertex env toggles).

Usage:
    python run_daily.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from claude_agent_sdk import ClaudeAgentOptions, query

PROMPT = (
    "Use the daily-ai-podcast skill to produce today's episode end to end: pull the "
    "structured sources, gather notable releases and news with your web tools, write a "
    "grounded two-host script to out/episode.json and out/shownotes.md, then render the "
    "MP3. Follow the skill's grounding rules strictly. When done, print the MP3 path, "
    "the episode title, the word count, and any source gaps."
)


async def main() -> int:
    options = ClaudeAgentOptions(
        # Load CLAUDE.md + the project skill from .claude/ in this repo.
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code"},
        # Least privilege: the job reads, writes to out/, runs the two scripts, and
        # searches the web. It does not need anything else.
        allowed_tools=["Bash", "Read", "Write", "WebSearch", "WebFetch", "Skill"],
        # Unattended run: auto-accept the file writes/script runs above. Keep the tool
        # allowlist tight precisely because nothing will approve prompts at 3am.
        permission_mode="acceptEdits",
        model=os.environ.get("PODCAST_MODEL", "claude-sonnet-4-6"),
        cwd=os.path.dirname(os.path.abspath(__file__)),
        max_turns=60,
    )

    final = None
    async for message in query(prompt=PROMPT, options=options):
        # Stream a light trace; swap this block for your logger (e.g. Langfuse).
        if hasattr(message, "result"):
            final = message.result
        text = getattr(message, "text", None)
        if text:
            print(text, file=sys.stderr)

    print(final or "(no final result returned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
