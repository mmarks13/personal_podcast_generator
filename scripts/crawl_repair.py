#!/usr/bin/env python3
"""Find configured crawl sources the crawl agent left unanswered, and merge a repair pass.

The crawl agent has silently omitted configured sources from `source_statuses`
(three of the eight nights before this check existed), and has marked a Tier-1 source
`failed` while writing no matching `failures` record (2026-09-11). The manifest gate
catches both, but only after scoring and consolidation have already spent ~25 minutes,
so the evening picker is lost. These two commands catch them a minute after the crawl
and repair them in place.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from crawl_freshness import item_error, item_source_names

ALLOWED = {"ok", "no_recent_items", "failed"}


def _json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _drop_trailing_comma(raw: str, error: json.JSONDecodeError) -> str | None:
    """Delete one comma that a closing brace or bracket followed, or give up.

    The decoder's error position is the repair's whole safety argument: it points at a
    structural character outside any string token, so the comma found behind it cannot be
    prose. A pattern match over the text could not make that promise.
    """
    if error.pos >= len(raw) or raw[error.pos] not in "}]":
        return None
    cut = raw.rfind(",", 0, error.pos)
    if cut < 0 or raw[cut + 1:error.pos].strip():
        return None
    return raw[:cut] + raw[cut + 1:]


def sanitize(crawl_path: Path, limit: int = 60) -> int:
    """Make the agent's crawl.json parseable again. Returns the number of repairs.

    On 2026-09-26 a single comma after the last field of one of 53 items cost the whole
    evening: crawl-freshness, first-seen indexing, Smallbatch scoring and the manifest gate
    each died on the same JSONDecodeError, so no manifest existed and the ntfy picker never
    drafted. `missing` below died on it too, which is why the repair pass built for a broken
    crawl never ran. Nothing downstream can read the file until the syntax is legal, so this
    runs first and fixes only what it can name; anything else still raises.
    """
    raw = crawl_path.read_text()
    fixes = 0
    while True:
        try:
            json.loads(raw)
            break
        except json.JSONDecodeError as error:
            repaired = None if fixes >= limit else _drop_trailing_comma(raw, error)
            if repaired is None:
                raise
            raw = repaired
            fixes += 1
    if fixes:
        crawl_path.write_text(raw)
    return fixes


def configured_fetch(config: Path) -> list[dict]:
    sources = yaml.safe_load(config.read_text()).get("sources", [])
    return [source for source in sources if source.get("method") == "fetch"]


def _statuses(crawl: Path) -> list[dict]:
    statuses = _json(crawl).get("source_statuses")
    if not isinstance(statuses, list):
        raise ValueError("crawl.json is missing source_statuses")
    return [record for record in statuses if isinstance(record, dict)]


def missing_sources(config: Path, crawl: Path) -> list[dict]:
    """Configured fetch sources carrying no status in the crawl."""
    covered = {str(record["url"]) for record in _statuses(crawl) if record.get("url")}
    return [source for source in configured_fetch(config) if source["url"] not in covered]


def defective_sources(config: Path, crawl: Path) -> list[dict]:
    """Tier-1 fetch sources whose status contradicts the rest of the crawl.

    So far one form: `failed` with no matching entry in `failures`. The crawl says a
    Tier-1 page broke but carries no evidence of what broke or that the skill's backup
    search ran, so the source contributes nothing and nobody knows whether it was
    really tried. Recrawling just that page costs a short pass here; the manifest gate
    records the bare `failed` rather than failing, so this is where it gets an answer.
    """
    data = _json(crawl)
    failure_urls = {
        str(failure.get("url")) for failure in data.get("failures", [])
        if isinstance(failure, dict) and failure.get("url")
    }
    by_url: dict[str, list[dict]] = {}
    for record in _statuses(crawl):
        if record.get("url"):
            by_url.setdefault(str(record["url"]), []).append(record)
    configured = configured_fetch(config)
    configured_names = {str(source["name"]) for source in configured}
    malformed_names = set()
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        if item_error(item):
            malformed_names.update(item_source_names(item).intersection(configured_names))
    defective = []
    for source in configured:
        if source["name"] in malformed_names:
            defective.append(source)
            continue
        if source.get("tier") != 1:
            continue
        records = by_url.get(source["url"], [])
        if len(records) == 1 and records[0].get("status") == "failed" \
                and source["url"] not in failure_urls:
            defective.append(source)
    return defective


def gap_sources(config: Path, crawl: Path) -> list[dict]:
    """Every configured source the repair pass needs to crawl again."""
    result = {}
    for source in [*missing_sources(config, crawl), *defective_sources(config, crawl)]:
        result[source["url"]] = source
    return list(result.values())


def merge(
    config: Path, crawl_path: Path, repair_path: Path
) -> tuple[int, int, list[str]]:
    """Fold the repair pass into the crawl, judging one source at a time.

    A record that breaks the contract is rejected on its own instead of aborting the
    whole merge. On 2026-09-23 a single coined status ("no_items_in_window" for
    mistral.ai) threw out a correct `failed` record for OpenAI News gathered in the same
    pass, and the manifest gate half an hour later could only report that the failure
    record it wanted was missing. Valid records land; a rejected source simply stays a
    gap, and its reason goes back to the repair agent for one more attempt.
    """
    crawl = _json(crawl_path)
    repair = _json(repair_path)
    wanted = {source["url"]: source for source in gap_sources(config, crawl_path)}
    if not wanted:
        raise ValueError("crawl.json already covers every configured source")

    # Which gap a status answers. The crawl contract asks for name and url both, but the
    # repair agent wrote only {"name": ..., "status": "ok"} for Mistral AI News on
    # 2026-09-25 and again on 2026-09-28; keying on url alone dropped that record as noise
    # and then reported the source as never answered, which told the retry nothing it could
    # act on. The configured name identifies the source just as exactly.
    by_name = {str(source["name"]): url for url, source in wanted.items()}

    def answered_gap(record: dict) -> str | None:
        url = record.get("url")
        if url is not None and str(url) in wanted:
            return str(url)
        return by_name.get(str(record.get("name")))

    rejected: dict[str, str] = {}
    by_url: dict[str, dict] = {}
    for record in repair.get("source_statuses", []):
        if not isinstance(record, dict):
            continue
        url = answered_gap(record)
        if url is None:
            continue  # a status for an already-covered source is the agent's noise
        if url in by_url or url in rejected:
            by_url.pop(url, None)
            rejected[url] = "carries more than one source_statuses record; write exactly one"
            continue
        if record.get("status") not in ALLOWED:
            rejected[url] = (
                f"status {record.get('status')!r} is not one of the three allowed literal "
                f"strings {sorted(ALLOWED)}; synonyms and variants are not accepted"
            )
            continue
        # Both the coverage check above and the manifest gate key statuses by url, so a
        # record merged without one would leave its source a gap for good.
        by_url[url] = record if record.get("url") == url else {**record, "url": url}

    repair_items = [item for item in repair.get("items", []) if isinstance(item, dict)]
    name_to_url = {str(source["name"]): url for url, source in wanted.items()}
    # A malformed item taints only the source that produced it.
    for item in repair_items:
        if error := item_error(item):
            for name in item_source_names(item).intersection(name_to_url):
                rejected.setdefault(name_to_url[name], f"item {item.get('url')}: {error}")

    item_sources = {name for item in repair_items for name in item_source_names(item)}
    failure_urls = {
        str(failure.get("url")) for failure in repair.get("failures", [])
        if isinstance(failure, dict) and failure.get("url")
    }
    # Mirror the manifest gate's Tier-1 invariants so a hollow repair is caught here,
    # before scoring, rather than at the gate half an hour later.
    for url in sorted(by_url):
        record = by_url[url]
        name = wanted[url]["name"]
        # `ok` asserts the page loaded and had recent items, at Tier 2 as much as Tier 1; a
        # page that loaded with nothing recent is `no_recent_items`. On 2026-09-28 the
        # Mistral item named its source in a bare "source" string rather than a "sources"
        # list, so it carried no source identity, could be attributed to nobody, and was
        # dropped as the status merged as ok - the repair reported success having added
        # nothing.
        if record["status"] == "ok" and name not in item_sources:
            rejected.setdefault(url, "reports ok but the repair carries no item from it")
            continue
        # The remaining invariants mirror the manifest gate, which polices Tier 1 only.
        if wanted[url].get("tier") != 1:
            continue
        if record.get("name") != name:
            rejected.setdefault(
                url, f"status name {record.get('name')!r} must repeat the configured "
                     f"name {name!r} verbatim")
        elif record["status"] == "failed" and url not in failure_urls:
            rejected.setdefault(
                url, "reports failed but the repair carries no matching failures record")
    for url in rejected:
        by_url.pop(url, None)

    # Only the sources whose records survived are rewritten; a rejected source keeps
    # whatever the first pass left, so it is still reported as a gap afterwards.
    merged_names = {str(wanted[url]["name"]) for url in by_url}
    kept_items = []
    for item in crawl.get("items", []):
        if not isinstance(item, dict):
            continue
        names = item_source_names(item)
        if not names.intersection(merged_names):
            kept_items.append(item)
            continue
        remaining = names - merged_names
        if remaining:
            item = dict(item)
            item["sources"] = [source for source in item.get("sources", [])
                               if str(source).strip() in remaining]
            kept_items.append(item)
    known = {str(item.get("url")) for item in kept_items if item.get("url")}
    added_items = [
        item for item in repair_items
        if item.get("url") and str(item["url"]) not in known
        and item_source_names(item).intersection(merged_names)
    ]

    unresolved = [
        f"{wanted[url]['name']} <{url}>: "
        + rejected.get(url, "no source_statuses record was written for it")
        for url in sorted(set(wanted) - set(by_url))
    ]
    if by_url:
        crawl["items"] = kept_items + added_items
        crawl.setdefault("failures", []).extend(
            failure for failure in repair.get("failures", [])
            if isinstance(failure, dict) and str(failure.get("url")) in by_url
        )
        # A defective source already carries a status, so the repair replaces it; leaving
        # both would read as a duplicate status and fail the manifest gate.
        crawl["source_statuses"] = [
            record for record in crawl.get("source_statuses", [])
            if not (isinstance(record, dict) and str(record.get("url")) in by_url)
        ] + [by_url[url] for url in sorted(by_url)]
        crawl_path.write_text(json.dumps(crawl, indent=1, ensure_ascii=False) + "\n")
    return len(by_url), len(added_items), unresolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sanitize", "missing", "merge"))
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--crawl", type=Path, default=Path("out/crawl.json"))
    parser.add_argument("--repair", type=Path, default=Path("out/crawl_repair.json"))
    args = parser.parse_args()
    if args.command == "sanitize":
        fixes = sanitize(args.crawl)
        print(f"sanitize: repaired {fixes} trailing comma(s) in {args.crawl}")
        return 0
    if args.command == "missing":
        gaps = gap_sources(args.config, args.crawl)
        if not gaps:
            return 0
        # stdout is the repair pass's crawl list; the count goes to the log.
        print(json.dumps(gaps, ensure_ascii=False))
        print(f"{len(gaps)} configured source(s) need a repair crawl from {args.crawl}",
              file=sys.stderr)
        return 3
    rejections = args.crawl.parent / "crawl_repair_rejections.txt"
    rejections.unlink(missing_ok=True)
    sources, items, unresolved = merge(args.config, args.crawl, args.repair)
    print(f"repaired {sources} source status(es), added {items} item(s) to {args.crawl}")
    if unresolved:
        # The repair agent gets this file back verbatim for its one retry, so each line
        # has to name the source and say what to write instead.
        rejections.write_text("\n".join(unresolved) + "\n")
        for line in unresolved:
            print(f"unresolved: {line}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
