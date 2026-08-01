#!/usr/bin/env python3
"""Small JSON-RPC client for Codex's documented account endpoints.

The output intentionally contains account state and quota data only; it never logs
tokens or identifiers from Codex's local authentication files.
"""

from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import sys
import time
import uuid


class AccountError(RuntimeError):
    pass


def request(method: str, params: dict | None = None) -> dict:
    proc = subprocess.Popen(
        ["codex", "app-server", "--strict-config"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    messages = [
        {
            "method": "initialize",
            "id": 0,
            "params": {
                "clientInfo": {
                    "name": "personal_podcast_generator",
                    "title": "Personal Podcast Generator",
                    "version": "1.0.0",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": method, "id": 1, **({"params": params} if params else {})},
    ]
    try:
        for message in messages:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not selector.select(timeout=0.5):
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 1:
                if "error" in message:
                    raise AccountError(str(message["error"]))
                return message.get("result") or {}
        stderr = ""
        if proc.poll() is not None and proc.stderr:
            stderr = proc.stderr.read()
        raise AccountError(stderr.strip() or "Codex app-server account request timed out")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def safe_snapshot() -> dict:
    """Return non-secret auth, rate-limit, and usage state."""
    account = request("account/read", {"refreshToken": False})
    limits = request("account/rateLimits/read")
    usage = request("account/usage/read")
    acct = account.get("account") or {}
    return {
        "account": {
            "type": acct.get("type"),
            "planType": acct.get("planType"),
            "requiresOpenaiAuth": account.get("requiresOpenaiAuth"),
        },
        "rateLimits": limits,
        "usage": usage,
    }


def consume_reset(idempotency_key: str, credit_id: str | None = None) -> dict:
    params = {"idempotencyKey": idempotency_key}
    if credit_id:
        params["creditId"] = credit_id
    result = request("account/rateLimitResetCredit/consume", params)
    return {"consume": result, "rateLimits": request("account/rateLimits/read")}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    consume = sub.add_parser("consume-reset")
    consume.add_argument("--idempotency-key", default=None)
    consume.add_argument("--credit-id", default=None)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            result = safe_snapshot()
        else:
            result = consume_reset(args.idempotency_key or str(uuid.uuid4()), args.credit_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AccountError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
