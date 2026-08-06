#!/usr/bin/env python3
"""Run one historical podcast-writing shadow and compare artifact contracts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Same "well below the norm" ratio the nightly breadth warning uses, so the two agree on
# what counts as a real drop rather than night-to-night noise.
from check_episode import BREADTH_FLOOR_RATIO  # noqa: E402


def words(path: Path) -> int:
    return len(path.read_text().split())


def coverage(meta_path: Path) -> tuple[int, int]:
    """(dives, sources) from an episode_meta.json."""
    meta = json.loads(meta_path.read_text())
    return len(meta.get("dives") or []), len(meta.get("sources") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="tests/fixtures/shadow/2026-08-01")
    args = parser.parse_args()
    fixture = ROOT / args.fixture
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    for name in ("sources.json", "crawl.json", "candidates.json"):
        shutil.copy2(fixture / "input" / name, out / name)

    prompt = """Run a historical shadow of the daily-ai-podcast writing stage for
2026-08-01. Use the already-present out/sources.json, out/crawl.json, and
out/candidates.json; do not fetch a different day's source slate. Read history and the
recent archive only for repeat/voice context. Select, verify, write, build, and run the
deterministic validation gate. Stop before history mutation, archive mutation, TTS,
delivery, Git, or publishing. The output date must remain 2026-08-01.
"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "agent_runner.py"), "--stage", "podcast"],
        cwd=ROOT,
        input=prompt,
        text=True,
    )
    required = ["script.txt", "episode_meta.json", "episode.json", "shownotes.md"]
    missing = [name for name in required if not (out / name).exists()]
    claude_dives, claude_sources = coverage(fixture / "claude-output" / "episode_meta.json")
    report = {
        "fixture": str(fixture.relative_to(ROOT)),
        "runner_exit": result.returncode,
        "missing_artifacts": missing,
        "claude_script_words": words(fixture / "claude-output" / "script.txt"),
        "claude_dives": claude_dives,
        "claude_sources": claude_sources,
    }
    if not missing:
        episode = json.loads((out / "episode.json").read_text())
        meta = json.loads((out / "episode_meta.json").read_text())
        report.update(
            {
                "codex_script_words": words(out / "script.txt"),
                "date": episode.get("date"),
                "turns": len(episode.get("turns") or []),
                "dives": len(meta.get("dives") or []),
                "sources": len(meta.get("sources") or []),
                "valid_http_sources": all(
                    str(source.get("url", "")).startswith(("http://", "https://"))
                    for source in (meta.get("sources") or [])
                ),
            }
        )
    # The cutover shadow recorded "Sources: eight" against the Claude script's eighteen and
    # still reported a pass, because nothing ever compared the two numbers it had already
    # collected. Coverage is precisely what a provider swap changes quietly, so compare it.
    coverage_ok = (not missing
                   and report.get("sources", 0) >= claude_sources * BREADTH_FLOOR_RATIO)
    report["coverage_ok"] = coverage_ok

    report_path = out / "shadow-gate-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(report_path)
    print(f"coverage: {report.get('dives')} dives / {report.get('sources')} sources "
          f"vs Claude's {claude_dives} / {claude_sources}"
          f"{'' if coverage_ok else '   <-- REGRESSION'}")
    contract_ok = (
        result.returncode == 0
        and not missing
        and report.get("date") == "2026-08-01"
        and 3000 <= report.get("codex_script_words", 0) <= 4700
        and report.get("turns", 0) > 0
        and report.get("sources", 0) > 0
        and report.get("valid_http_sources")
        and coverage_ok
    )
    return 0 if contract_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
