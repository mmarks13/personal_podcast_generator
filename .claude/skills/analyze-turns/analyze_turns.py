#!/usr/bin/env python3
"""Turn-by-turn usage analysis of a Claude Code session and its subagents.

Deterministic extraction only (no LLM, stdlib only). Reads the session transcript
JSONL that Claude Code already writes to ~/.claude/projects/<munged-cwd>/, plus each
subagent's own transcript under <session>/subagents/agent-<id>.jsonl, and produces:

  * a readable report to stdout (per-agent summary + per-turn timeline + flags)
  * a compact JSON digest (--json) for trending / for a skill to read cheaply

It answers two questions structurally: where the tokens/stdout go (every tool result
sized, ranked, threshold-flagged, split into INGESTED-by-an-agent vs RETURNED-to-the-
orchestrator) and why there are so many turns (action histogram per agent + flags for
batchable runs of identical tool calls and duplicate file reads). Judgment — whether a
big payload is *unnecessary* or a turn was *avoidable* — is left to the caller.

Usage:
  analyze_turns.py [SELECTOR] [--json PATH] [--threshold TOK] [--verbose] [--no-timeline]

SELECTOR (default "latest"):
  latest               most recent top-level session in the project dir
  podcast|read|deepdive  most recent session whose opening prompt invoked that skill
  <id-or-prefix>       a specific session id (full or leading chars)
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

SKILL_OF_STEP = {
    "podcast": "daily-ai-podcast",
    "read": "daily-read",
    "deepdive": "weekly-deep-dive",
}

# Per-token USD rates, keyed by model-id prefix. Source: Claude API pricing
# (claude-api skill, cached 2026-06-04) + prompt-caching economics: 5-min cache
# WRITE = 1.25x base input, cache READ = 0.1x base input.
#   in = uncached input, out = output, cw = cache_creation, cr = cache_read
# This is an ESTIMATE at public API rates — NOT what a Pro/Max subscription bills.
# Its purpose is to weight the 5h usage limit, which is consumed ~in proportion to
# model cost (Opus drains it far faster than Sonnet, Sonnet faster than Haiku), so
# cost is the right lens for finding bottlenecks. Update rates when pricing changes.
RATES = {
    "claude-fable-5":    {"in": 10e-6, "out": 50e-6, "cw": 12.5e-6, "cr": 1.0e-6},
    "claude-opus-4-8":   {"in": 5e-6,  "out": 25e-6, "cw": 6.25e-6, "cr": 0.5e-6},
    "claude-opus-4-7":   {"in": 5e-6,  "out": 25e-6, "cw": 6.25e-6, "cr": 0.5e-6},
    "claude-opus-4-6":   {"in": 5e-6,  "out": 25e-6, "cw": 6.25e-6, "cr": 0.5e-6},
    "claude-sonnet-4-6": {"in": 3e-6,  "out": 15e-6, "cw": 3.75e-6, "cr": 0.3e-6},
    "claude-haiku-4-5":  {"in": 1e-6,  "out": 5e-6,  "cw": 1.25e-6, "cr": 0.1e-6},
}
RATE_FALLBACK = RATES["claude-opus-4-8"]  # unknown model -> price as Opus (conservative)


def rate_for(model: str) -> dict:
    for prefix, r in RATES.items():
        if model and model.startswith(prefix):
            return r
    return RATE_FALLBACK


def turn_cost(u: dict, model: str) -> float:
    r = rate_for(model)
    return (u.get("input_tokens", 0) * r["in"]
            + u.get("output_tokens", 0) * r["out"]
            + u.get("cache_creation_input_tokens", 0) * r["cw"]
            + u.get("cache_read_input_tokens", 0) * r["cr"])


def est_tok(chars: int) -> int:
    return math.ceil(chars / 4)


def project_dir() -> str:
    munged = re.sub(r"[/_]", "-", os.path.abspath(os.getcwd()))
    return os.path.expanduser(f"~/.claude/projects/{munged}")


def _text_len(content) -> int:
    """Char length of a message-content value (str, or list of blocks)."""
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        n = 0
        for b in content:
            if isinstance(b, dict):
                n += len(b.get("text") or b.get("content") or "")
                if not (b.get("text") or b.get("content")):
                    n += len(json.dumps(b))
            else:
                n += len(str(b))
        return n
    return len(json.dumps(content))


def _text_str(content, limit=240) -> str:
    if isinstance(content, str):
        s = content
    elif isinstance(content, list):
        s = " ".join(
            (b.get("text") or b.get("content") or json.dumps(b)) if isinstance(b, dict) else str(b)
            for b in content
        )
    else:
        s = json.dumps(content) if content is not None else ""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def load_jsonl(path: str) -> list:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def tool_summary(name: str, inp: dict) -> str:
    inp = inp or {}
    if name == "Bash":
        return (inp.get("description") or inp.get("command") or "")[:60]
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        return os.path.basename(inp.get("file_path") or inp.get("notebook_path") or "")
    if name == "WebFetch":
        return inp.get("url", "")
    if name == "WebSearch":
        return (inp.get("query") or "")[:60]
    if name in ("Agent", "Task"):
        return f"{inp.get('subagent_type','?')}: {inp.get('description','')}"[:60]
    if name == "Skill":
        return inp.get("skill", "")
    if name in ("Grep", "Glob"):
        return (inp.get("pattern") or "")[:50]
    return _text_str(inp, 50)


def read_target(name: str, inp: dict) -> str | None:
    """The file/url a turn reads, for duplicate-read detection."""
    inp = inp or {}
    if name == "Read":
        return inp.get("file_path")
    if name == "WebFetch":
        return inp.get("url")
    return None


def parse_transcript(rows: list) -> dict:
    """Extract turns + ingested tool-results from one agent's transcript.

    Streaming logs each assistant message several times under one message.id; we
    keep the last (most complete) record per id so turns/tokens aren't multi-counted.
    Tool results are deduped by tool_use_id.
    """
    turns = []           # assistant turns with usage
    tool_names = {}       # tool_use_id -> tool name (for labeling results)
    tool_inputs = {}      # tool_use_id -> input
    results = []          # ingested tool_results: {tool, id, tok, is_error, preview}
    first_ts = last_ts = None

    # span from original order; then dedupe assistant records by message.id
    # (keep last/most-complete), preserving first-seen order.
    for r in rows:
        ts = r.get("timestamp")
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
    asst_order, asst_rec, other = [], {}, []
    for r in rows:
        m = r.get("message")
        if r.get("type") == "assistant" and isinstance(m, dict) and "usage" in m:
            mid = m.get("id") or id(r)
            if mid not in asst_rec:
                asst_order.append(mid)
            asst_rec[mid] = r
        else:
            other.append(r)
    rows = [asst_rec[mid] for mid in asst_order] + other

    seen_results = set()
    for r in rows:
        m = r.get("message")
        if not isinstance(m, dict):
            continue
        rtype = r.get("type")
        if rtype == "assistant" and "usage" in m:
            u = m["usage"]
            model = m.get("model", "")
            actions = []
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tool_names[c["id"]] = c["name"]
                    tool_inputs[c["id"]] = c.get("input") or {}
                    actions.append({"name": c["name"], "input": c.get("input") or {}, "id": c["id"]})
            txt = any(
                isinstance(c, dict) and c.get("type") in ("text", "thinking") and (c.get("text") or c.get("thinking"))
                for c in (m.get("content") or [])
            )
            turns.append({
                "ts": (ts or "")[11:19],
                "model": model,
                "in": u.get("input_tokens", 0),
                "cr": u.get("cache_read_input_tokens", 0),
                "cc": u.get("cache_creation_input_tokens", 0),
                "out": u.get("output_tokens", 0),
                "ctx": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                "cost": turn_cost(u, model),
                "actions": actions,
                "text_only": txt and not actions,
            })
        elif rtype == "user":
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tid = c.get("tool_use_id")
                    if tid in seen_results:
                        continue
                    seen_results.add(tid)
                    chars = _text_len(c.get("content"))
                    results.append({
                        "tool": tool_names.get(tid, "?"),
                        "id": tid,
                        "tok": est_tok(chars),
                        "is_error": bool(c.get("is_error")),
                        "preview": _text_str(c.get("content")),
                        "target": read_target(tool_names.get(tid, ""), tool_inputs.get(tid, {})),
                    })
    return {"turns": turns, "results": results, "first_ts": first_ts, "last_ts": last_ts}


def agent_metrics(parsed: dict) -> dict:
    turns = parsed["turns"]
    hist = Counter()
    for t in turns:
        if t["text_only"]:
            hist["(text/think only)"] += 1
        for a in t["actions"]:
            hist[a["name"]] += 1
    models = sorted({t["model"] for t in turns if t["model"].startswith("claude-")})
    return {
        "turns": len(turns),
        "model": models[0] if len(models) == 1 else (",".join(models) or "?"),
        "action_hist": dict(hist.most_common()),
        "tok_in": sum(t["in"] for t in turns),
        "tok_cache_read": sum(t["cr"] for t in turns),
        "tok_cache_create": sum(t["cc"] for t in turns),
        "tok_out": sum(t["out"] for t in turns),
        "input_total": sum(t["ctx"] for t in turns),
        "cost": sum(t["cost"] for t in turns),
        "startup_ctx": turns[0]["ctx"] if turns else 0,
        "peak_ctx": max((t["ctx"] for t in turns), default=0),
        "first_ts": parsed["first_ts"],
        "last_ts": parsed["last_ts"],
    }


def find_flags(parsed: dict, threshold: int) -> dict:
    turns, results = parsed["turns"], parsed["results"]
    # batchable: >=3 consecutive turns whose sole action is the same tool
    batchable = []
    run_tool, run_len, run_start = None, 0, 0
    seq = []
    for i, t in enumerate(turns):
        tool = t["actions"][0]["name"] if len(t["actions"]) == 1 else None
        seq.append((i, tool, t["ts"]))
    i = 0
    while i < len(seq):
        _, tool, ts = seq[i]
        if tool in ("WebFetch", "WebSearch", "Read", "Bash"):
            j = i
            while j < len(seq) and seq[j][1] == tool:
                j += 1
            if j - i >= 3:
                batchable.append({"tool": tool, "count": j - i, "from_ts": seq[i][2], "to_ts": seq[j - 1][2]})
            i = j
        else:
            i += 1
    # big tool results (ingested)
    big = sorted([r for r in results if r["tok"] >= threshold], key=lambda r: -r["tok"])
    # duplicate file/url reads
    dup = Counter(r["target"] for r in results if r.get("target"))
    dups = [{"target": k, "count": v} for k, v in dup.items() if v > 1]
    dups.sort(key=lambda d: -d["count"])
    return {"batchable": batchable, "big_ingested": big, "duplicate_reads": dups}


def resolve_session(pdir: str, selector: str) -> str:
    tops = [p for p in glob.glob(os.path.join(pdir, "*.jsonl"))]
    if not tops:
        sys.exit(f"no transcripts in {pdir}")
    tops.sort(key=os.path.getmtime, reverse=True)
    if selector == "latest":
        return tops[0]
    if selector in SKILL_OF_STEP:
        needle = SKILL_OF_STEP[selector]
        for p in tops:
            rows = load_jsonl(p)
            for r in rows[:6]:
                m = r.get("message")
                if r.get("type") == "user" and isinstance(m, dict) and needle in _text_str(m.get("content"), 4000):
                    return p
        sys.exit(f"no session found whose opening prompt used '{needle}'")
    # treat as id / prefix
    for p in tops:
        if os.path.basename(p).startswith(selector):
            return p
    sys.exit(f"no session id starting with '{selector}' in {pdir}")


def subagent_links(main_rows: list, session_path: str) -> list:
    """Map each subagents/agent-<id>.jsonl to its Agent call in the orchestrator."""
    sdir = session_path[:-6] + "/subagents"
    files = sorted(glob.glob(os.path.join(sdir, "agent-*.jsonl")))
    # orchestrator Agent tool_use inputs by id, and their returned result text/size
    agent_calls = {}     # tool_use_id -> input
    for r in main_rows:
        m = r.get("message")
        if r.get("type") == "assistant" and isinstance(m, dict):
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c["name"] in ("Agent", "Task"):
                    agent_calls[c["id"]] = c.get("input") or {}
    returns = {}        # agentId -> {subagent_type, description, return_tok}
    for r in main_rows:
        m = r.get("message")
        if r.get("type") == "user" and isinstance(m, dict):
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in agent_calls:
                    txt = c.get("content")
                    s = _text_str(txt, 100000)
                    mm = re.search(r"agent[_-]?[iI]d[\"':\s]+([a-f0-9]{8,})", s)
                    inp = agent_calls[c["tool_use_id"]]
                    if mm:
                        returns[mm.group(1)] = {
                            "subagent_type": inp.get("subagent_type", "?"),
                            "description": inp.get("description", ""),
                            "return_tok": est_tok(_text_len(txt)),
                        }
    linked = []
    for f in files:
        aid = re.sub(r"^agent-|\.jsonl$", "", os.path.basename(f))
        meta = returns.get(aid, {"subagent_type": "?", "description": "", "return_tok": None})
        linked.append({"file": f, "agent_id": aid, **meta})
    return linked


def fmt_hist(h: dict) -> str:
    return ", ".join(f"{k}×{v}" for k, v in h.items()) or "-"


def render(report: dict, threshold: int, show_timeline: bool, verbose: bool) -> None:
    p = print
    p("=" * 78)
    p(f"TURN ANALYSIS  session={report['session'][:8]}  step={report['step'] or '?'}")
    p(f"  span {report['first_ts']} -> {report['last_ts']}   threshold={threshold} tok")
    p("=" * 78)

    total_cost = sum(a["cost"] for a in report["agents"]) or 1e-9
    ranked = sorted(report["agents"], key=lambda a: -a["cost"])
    top = ranked[0]
    p(f"\n  ESTIMATED COST (API-rate proxy for the 5h limit): ${total_cost:.2f}")
    p(f"  Biggest cost center: {top['label']} ({top['model']}) — ${top['cost']:.2f} "
      f"({100*top['cost']/total_cost:.0f}%)")

    p("\n--- agents by COST (the bottleneck lens; 5h limit ~ cost-weighted) ---")
    hdr = (f"{'agent':22} {'model':9} {'turns':>5} {'$cost':>7} {'share':>6} "
           f"{'cache_rd':>9} {'out':>7} {'peak_ctx':>8} {'ret_tok':>7}")
    p(hdr); p("-" * len(hdr))
    for a in ranked:
        ret = "" if a.get("return_tok") in (None,) else f"{a['return_tok']:>7,}"
        mdl = a["model"].replace("claude-", "").split("-2025")[0][:9]
        p(f"{a['label'][:22]:22} {mdl:9} {a['turns']:>5} {a['cost']:>6.2f} "
          f"{100*a['cost']/total_cost:>5.0f}% {a['tok_cache_read']:>9,} {a['tok_out']:>7,} "
          f"{a['peak_ctx']:>8,} {ret:>7}")
    t = report["totals"]
    p("-" * len(hdr))
    p(f"{'TOTAL':22} {'':9} {t['turns']:>5} {total_cost:>6.2f} {'100%':>6} "
      f"{t['tok_cache_read']:>9,} {t['tok_out']:>7,}")
    p("  (cost = uncached·rate + output·5×in + cache_create·1.25×in + cache_read·0.1×in, per model)")

    p("\n--- why so many turns (actions per agent) ---")
    for a in report["agents"]:
        p(f"  {a['label']:22} {a['turns']:>3} turns  |  {fmt_hist(a['action_hist'])}")

    p("\n--- FLAGS: returned to orchestrator (pollutes main context) ---")
    rets = [a for a in report["agents"] if a.get("return_tok")]
    for a in sorted(rets, key=lambda a: -(a["return_tok"] or 0)):
        mark = "  <== over threshold" if a["return_tok"] >= threshold else ""
        p(f"  {a['label']:24} returned {a['return_tok']:>6,} tok{mark}")

    p("\n--- FLAGS: biggest ingested tool results (per agent) ---")
    any_big = False
    for a in report["agents"]:
        for b in a["flags"]["big_ingested"][:5]:
            any_big = True
            err = " [ERROR]" if b["is_error"] else ""
            p(f"  {a['label']:20} {b['tool']:>10} {b['tok']:>6,} tok{err}")
            if verbose:
                p(f"        {b['preview'][:160]}")
    if not any_big:
        p(f"  (none over {threshold} tok)")

    p("\n--- FLAGS: batchable runs (>=3 consecutive identical single-tool turns) ---")
    any_b = False
    for a in report["agents"]:
        for b in a["flags"]["batchable"]:
            any_b = True
            span = f"  ({b['from_ts']}→{b['to_ts']})" if b["from_ts"] and b["to_ts"] else ""
            p(f"  {a['label']:20} {b['count']}× {b['tool']} in a row{span}")
    if not any_b:
        p("  (none)")

    p("\n--- FLAGS: duplicate reads (same file/url read >1x) ---")
    any_d = False
    for a in report["agents"]:
        for d in a["flags"]["duplicate_reads"]:
            any_d = True
            tgt = d["target"]
            tgt = tgt if len(tgt) < 70 else "…" + tgt[-67:]
            p(f"  {a['label']:20} {d['count']}× {tgt}")
    if not any_d:
        p("  (none)")

    if show_timeline:
        p("\n--- per-turn timeline ---")
        for a in report["agents"]:
            p(f"\n  [{a['label']}]  {a['turns']} turns")
            for i, t in enumerate(a["timeline"]):
                acts = "; ".join(f"{x['name']}({x['summary']})" for x in t["actions"]) or (
                    "(text/think)" if t["text_only"] else "(stop)")
                res = f"  ->result {t['result_tok']:,}tok" if t.get("result_tok") else ""
                p(f"    {i+1:>3} {t['ts']}  ${t.get('cost',0):>5.2f} ctx={t['ctx']:>7,} out={t['out']:>5}  {acts}{res}")
                if verbose and t["actions"]:
                    for x in t["actions"]:
                        p(f"          · {x['name']}: {x['summary']}")


def build_report(session_path: str, threshold: int) -> dict:
    main_rows = load_jsonl(session_path)
    # step detection from opening prompt
    step = None
    for r in main_rows[:8]:
        m = r.get("message")
        if r.get("type") == "user" and isinstance(m, dict):
            s = _text_str(m.get("content"), 4000)
            for k, v in SKILL_OF_STEP.items():
                if v in s:
                    step = k
            break

    def agent_block(rows, label, return_tok=None, agent_id=None):
        parsed = parse_transcript(rows)
        met = agent_metrics(parsed)
        flags = find_flags(parsed, threshold)
        # attach result sizes to turns (by next tool_result for each tool_use id)
        res_by_id = {}
        for rr in parsed["results"]:
            res_by_id[rr["id"]] = rr["tok"]
        timeline = []
        for t in parsed["turns"]:
            rtok = sum(res_by_id.get(a["id"], 0) for a in t["actions"])
            timeline.append({
                "ts": t["ts"], "ctx": t["ctx"], "out": t["out"], "cost": t["cost"],
                "text_only": t["text_only"], "result_tok": rtok,
                "actions": [{"name": a["name"], "summary": tool_summary(a["name"], a["input"])} for a in t["actions"]],
            })
        return {
            "label": label, "agent_id": agent_id, "return_tok": return_tok,
            **met, "flags": flags, "timeline": timeline,
        }

    agents = [agent_block(main_rows, "orchestrator")]
    for link in subagent_links(main_rows, session_path):
        rows = load_jsonl(link["file"])
        label = link["subagent_type"] if link["subagent_type"] != "?" else f"agent-{link['agent_id'][:8]}"
        agents.append(agent_block(rows, label, return_tok=link["return_tok"], agent_id=link["agent_id"]))

    totals = {
        "turns": sum(a["turns"] for a in agents),
        "input_total": sum(a["input_total"] for a in agents),
        "tok_cache_read": sum(a["tok_cache_read"] for a in agents),
        "tok_cache_create": sum(a["tok_cache_create"] for a in agents),
        "tok_out": sum(a["tok_out"] for a in agents),
    }
    return {
        "session": os.path.basename(session_path)[:-6],
        "step": step,
        "first_ts": agents[0]["first_ts"],
        "last_ts": agents[0]["last_ts"],
        "threshold": threshold,
        "agents": agents,
        "totals": totals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("selector", nargs="?", default="latest",
                    help="latest | podcast | read | deepdive | <session-id-or-prefix>")
    ap.add_argument("--project-dir", default=None)
    ap.add_argument("--threshold", type=int, default=5000, help="tok size to flag a tool result (default 5000)")
    ap.add_argument("--json", default=None, help="write JSON digest here (default out/turn_analysis-<id>.json)")
    ap.add_argument("--verbose", action="store_true", help="include content previews / per-action detail")
    ap.add_argument("--no-timeline", action="store_true", help="omit the per-turn timeline")
    a = ap.parse_args()

    pdir = a.project_dir or project_dir()
    if not os.path.isdir(pdir):
        sys.exit(f"project dir not found: {pdir}")
    session = resolve_session(pdir, a.selector)
    report = build_report(session, a.threshold)

    render(report, a.threshold, show_timeline=not a.no_timeline, verbose=a.verbose)

    json_path = a.json or f"out/turn_analysis-{report['session'][:8]}.json"
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    # strip bulky previews from JSON unless verbose
    with open(json_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nJSON digest -> {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
