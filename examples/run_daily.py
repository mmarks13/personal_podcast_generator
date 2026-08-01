#!/usr/bin/env python3
"""Provider-neutral example for one unattended podcast writing stage.

Uses the same checked-in provider, model, effort, approvals, sandbox, telemetry, and
fallback policy as production. Authentication remains subscription-based because this
invokes the local CLIs through scripts/agent_runner.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT = """Use the daily-ai-podcast skill to produce today's episode. Assume the
deterministic gather artifacts already exist. Select, verify, write, build, and validate,
then stop before rendering, history updates, or publishing. Print the title and word count.
"""


def main() -> int:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "agent_runner.py"), "--stage", "podcast"],
        cwd=ROOT,
        input=PROMPT,
        text=True,
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
