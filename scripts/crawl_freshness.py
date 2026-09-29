#!/usr/bin/env python3
"""Annotate HTML-crawl items with deterministic phone-proposal eligibility."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import yaml

DEFAULT_WINDOW_HOURS = 48
DATE_STATUSES = {"verified", "unknown"}
# Above this share of malformed items the crawl is broken, not merely quirky.
MALFORMED_FAIL_RATIO = 0.5
BACKUP_SUFFIX = " (backup search)"


def source_name(value: object) -> str:
    name = str(value or "").strip()
    if name.casefold().endswith(BACKUP_SUFFIX.casefold()):
        return name[:-len(BACKUP_SUFFIX)].strip()
    return name


def item_source_names(item: dict) -> set[str]:
    values = item.get("sources")
    if not isinstance(values, list):
        return set()
    return {source_name(value) for value in values if source_name(value)}


def _parse_published(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("published_at is empty")
    if len(raw) == 10:
        # A page that publishes only a calendar date stays eligible through that day.
        return datetime.combine(datetime.fromisoformat(raw).date(), time.max, timezone.utc)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def item_error(item: dict) -> str | None:
    """Structural validity: what a well-formed crawl item must always carry."""
    if not str(item.get("title") or "").strip():
        return "missing title"
    if not str(item.get("url") or "").strip():
        return "missing url"
    if not item_source_names(item):
        return "missing configured source identity"
    status = item.get("date_status")
    if status not in DATE_STATUSES:
        return "date_status must be verified or unknown"
    published = item.get("published_at")
    if status == "unknown":
        # An unknown status settles the item: it is phone-ineligible whatever
        # `published_at` holds. The crawler routinely reports a date it found but
        # could not trust — a partial "2026-09", an index page's date, a future
        # date — and reads that as the honest answer, so keep the date for the
        # record and let the status decide.
        return None
    if published in (None, ""):
        return "verified date_status requires published_at"
    try:
        _parse_published(published)
    except (TypeError, ValueError):
        return "published_at is not an ISO date or timestamp"
    return None


def out_of_scope_reason(item: dict, configured_names: set[str]) -> str | None:
    """Whether an item falls outside the crawl's configured `fetch` sources.

    The crawler occasionally wanders onto a source the RSS fetcher already owns.
    Such an item has no crawl window to judge it against, but it is not malformed
    and must not cost the evening picker, so it is quarantined rather than raised.
    """
    names = item_source_names(item)
    if names.intersection(configured_names):
        return None
    listed = ", ".join(sorted(names))
    return f"sources ({listed}) are not configured crawl sources"


def _configured_windows(config_path: Path) -> dict[str, float]:
    config = yaml.safe_load(config_path.read_text()) or {}
    result = {}
    for source in config.get("sources", []):
        if source.get("method") != "fetch" or not source.get("name"):
            continue
        result[str(source["name"])] = float(source.get("window_hours", DEFAULT_WINDOW_HOURS))
    return result


def annotate(config_path: str | Path, crawl_path: str | Path,
             *, as_of: datetime | None = None) -> tuple[int, int]:
    config_file = Path(config_path)
    crawl_file = Path(crawl_path)
    windows = _configured_windows(config_file)
    value = json.loads(crawl_file.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("crawl.json must contain an items list")
    evaluated = as_of or datetime.now(timezone.utc)
    if evaluated.tzinfo is None:
        evaluated = evaluated.replace(tzinfo=timezone.utc)
    evaluated = evaluated.astimezone(timezone.utc)
    configured = set(windows)
    eligible = quarantined = malformed = dated = 0

    # A malformed item costs itself, not the evening picker. Three pickers were
    # lost in six nights to a single bad record among forty, each time a different
    # quirk in the crawler's output, so quarantine the record and keep the gather.
    # Systemic breakage still fails loudly; see the checks after the loop.
    items = [item for item in value["items"] if isinstance(item, dict)]
    malformed += len(value["items"]) - len(items)
    value["items"] = items

    for item in items:
        error = item_error(item)
        if error:
            item["proposal_eligible"] = False
            item["proposal_exclusion_reason"] = f"malformed crawl item: {error}"
            malformed += 1
            quarantined += 1
            continue
        if item["date_status"] == "verified":
            dated += 1
        reason = out_of_scope_reason(item, configured)
        if reason is None and item["date_status"] == "unknown":
            reason = "publication date unknown"
        elif reason is None:
            published = _parse_published(item["published_at"])
            names = item_source_names(item).intersection(configured)
            widest_window = max(windows[name] for name in names)
            cutoff = evaluated - timedelta(hours=widest_window)
            if published > evaluated + timedelta(hours=12):
                reason = f"published_at {published.isoformat()} is in the future"
            elif published < cutoff:
                reason = (
                    f"published_at {published.isoformat()} is outside the "
                    f"{widest_window:g}h source window (cutoff {cutoff.isoformat()})"
                )
        item["proposal_eligible"] = reason is None
        if reason is None:
            item.pop("proposal_exclusion_reason", None)
            eligible += 1
        else:
            item["proposal_exclusion_reason"] = reason
            quarantined += 1

    # Systemic breakage, as opposed to a quirk in one record: the crawler produced
    # mostly unusable output, or stopped establishing dates altogether. Either means
    # the gather cannot be trusted to govern the phone, so fail rather than ship a
    # slate quietly drawn from whatever survived.
    total = len(items)
    if total and malformed / total > MALFORMED_FAIL_RATIO:
        raise ValueError(
            f"{malformed} of {total} crawl items are malformed; the crawl is unusable"
        )
    if total and not dated:
        raise ValueError(
            f"no verified publication date among {total} crawl items; "
            "the crawler established no dates at all"
        )

    value["proposal_freshness"] = {
        "status": "valid",
        "evaluated_at": evaluated.isoformat(),
        "eligible": eligible,
        "quarantined": quarantined,
        "malformed": malformed,
    }
    temporary = crawl_file.with_name(crawl_file.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(crawl_file)
    return eligible, quarantined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--crawl", type=Path, default=Path("out/crawl.json"))
    parser.add_argument("--as-of")
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    eligible, quarantined = annotate(args.config, args.crawl, as_of=as_of)
    malformed = json.loads(args.crawl.read_text())["proposal_freshness"]["malformed"]
    print(f"crawl_freshness: eligible={eligible} quarantined={quarantined} "
          f"malformed={malformed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
