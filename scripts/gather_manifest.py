#!/usr/bin/env python3
"""Create and validate the identity of one reusable evening gather."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REQUIRED = ("sources.json", "crawl.json", "candidates.json")
SCORE_FIELDS = (
    "editorial_fit", "source_provenance", "evidence_quality", "story_strength", "total",
    "package_id", "revision", "raw_provenance",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _structured_error_names(errors: list) -> set[str]:
    names = set()
    for error in errors:
        if isinstance(error, str) and ":" in error:
            names.add(error.split(":", 1)[0])
    return names


def tier1_statuses(config: Path, sources: dict, crawl: dict) -> list[dict]:
    configured = yaml.safe_load(config.read_text()).get("sources", [])
    tier1 = [source for source in configured if source.get("tier") == 1]
    feeds = sources.get("feeds")
    if not isinstance(feeds, dict):
        raise ValueError("sources.json is missing its feeds object")
    error_names = _structured_error_names(sources.get("errors", []))
    crawl_statuses = crawl.get("source_statuses")
    if not isinstance(crawl_statuses, list):
        raise ValueError("crawl.json is missing source_statuses")
    by_url: dict[str, list[dict]] = {}
    for record in crawl_statuses:
        if isinstance(record, dict) and record.get("url"):
            by_url.setdefault(str(record["url"]), []).append(record)
    item_sources = {
        str(source)
        for item in crawl.get("items", []) if isinstance(item, dict)
        for source in item.get("sources", [])
    }
    failure_urls = {
        str(failure.get("url")) for failure in crawl.get("failures", [])
        if isinstance(failure, dict) and failure.get("url")
    }
    allowed = {"ok", "no_recent_items", "failed"}
    result = []
    for source in tier1:
        name, method, url = source["name"], source["method"], source["url"]
        if method in {"rss", "api"}:
            if name not in feeds:
                raise ValueError(f"Tier-1 source silently omitted from sources.json: {name}")
            status = "failed" if name in error_names else ("ok" if feeds[name] else "no_recent_items")
        elif method == "fetch":
            records = by_url.get(url, [])
            if not records:
                raise ValueError(f"Tier-1 source silently omitted from crawl.json: {name}")
            if len(records) != 1:
                raise ValueError(f"Tier-1 source has duplicate crawl statuses: {name}")
            record = records[0]
            if record.get("name") != name:
                raise ValueError(f"Tier-1 crawl status name mismatch: {name}")
            status = record.get("status")
            if status not in allowed:
                raise ValueError(f"Tier-1 source has invalid status {status!r}: {name}")
            if status == "ok" and name not in item_sources:
                # The crawl contract makes `ok` mean "loaded AND produced in-window
                # items"; a page that loaded with nothing recent is `no_recent_items`.
                # Agents conflate the two, and this gate runs last — after ~35 minutes
                # of fetch, crawl, score, and consolidation — so failing here throws
                # away a whole valid gather, and the evening picker with it, over a
                # label. Record what the crawl actually shows and say so loudly.
                print(
                    f"WARNING: Tier-1 source {name} reports ok but carries no item; "
                    "recording no_recent_items",
                    file=sys.stderr,
                )
                status = "no_recent_items"
            if status == "failed" and url not in failure_urls:
                # `failed` with no matching failure record is the same class of agent
                # sloppiness as `ok` with no item, and costs the same whole gather at
                # the same late gate. The status itself is already the pessimistic one:
                # nothing is being counted as success, only the narrative of what broke
                # and whether a backup search recovered it is missing. Record it and
                # say so loudly; the post-crawl repair check is where this gets fixed.
                print(
                    f"WARNING: Tier-1 source {name} reports failed with no failure "
                    "record; recording failed with no recovery detail",
                    file=sys.stderr,
                )
        else:
            raise ValueError(f"Tier-1 source has unsupported method {method!r}: {name}")
        result.append({"name": name, "url": url, "method": method, "status": status})
    return result


def _validate_scored_candidates(candidates: dict, scores: dict) -> list[int]:
    """Verify every score a candidate carries. Returns the candidates carrying none.

    The Smallbatch score ranks attention and never filters, so a candidate the
    consolidator could not match to a raw record — a synthesized roll-up owns no raw
    URL or title — is reported, not fatal. A score that is present is still fully
    verified: a partial or invented one is a fabrication and still fails the gather.
    """
    package = scores.get("package", {})
    by_provenance = {
        json.dumps(record.get("raw_provenance"), sort_keys=True, separators=(",", ":")): record
        for record in scores.get("records", []) if isinstance(record, dict)
    }
    unscored = []
    for index, item in enumerate(candidates.get("items", [])):
        score = item.get("smallbatch_score") if isinstance(item, dict) else None
        if score is None:
            unscored.append(index)
            continue
        if not isinstance(score, dict) or any(field not in score for field in SCORE_FIELDS):
            raise ValueError(f"candidate {index} has an incomplete smallbatch_score")
        dims = [score[field] for field in SCORE_FIELDS[:4]]
        if score["total"] != sum(dims):
            raise ValueError(f"candidate {index} has an inconsistent Smallbatch total")
        if score["package_id"] != package.get("package_id") or score["revision"] != package.get("revision"):
            raise ValueError(f"candidate {index} has a mismatched Smallbatch package identity")
        provenance = score["raw_provenance"]
        if not isinstance(provenance, list) or not provenance:
            raise ValueError(f"candidate {index} has no Smallbatch raw provenance")
        matched = []
        for raw in provenance:
            record = by_provenance.get(
                json.dumps(raw, sort_keys=True, separators=(",", ":"))
            )
            if record is None:
                raise ValueError(f"candidate {index} cites unknown Smallbatch raw provenance")
            matched.append(record)
        strongest = max(matched, key=lambda record: record.get("total", -1))
        expected = {**strongest.get("dimensions", {}), "total": strongest.get("total")}
        actual = {field: score[field] for field in (*SCORE_FIELDS[:4], "total")}
        if actual != expected:
            raise ValueError(f"candidate {index} does not preserve its strongest Smallbatch score")
    return unscored


def create_manifest(out_dir: Path, config: Path) -> dict:
    paths = {name: out_dir / name for name in REQUIRED}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError("missing gather artifacts: " + ", ".join(missing))
    sources = _json(paths["sources.json"])
    crawl = _json(paths["crawl.json"])
    candidates = _json(paths["candidates.json"])
    statuses = tier1_statuses(config, sources, crawl)

    score_path = out_dir / "source_scores.json"
    scoring = {"status": "failed"}
    artifact_names = list(REQUIRED)
    if score_path.is_file():
        scores = _json(score_path)
        if scores.get("status") != "ok":
            raise ValueError("source_scores.json does not report status=ok")
        expected_inputs = {"sources.json": sha256(paths["sources.json"]),
                           "crawl.json": sha256(paths["crawl.json"])}
        if scores.get("inputs") != expected_inputs:
            raise ValueError("source_scores.json does not identify the current raw inputs")
        unscored = _validate_scored_candidates(candidates, scores)
        total = len(candidates.get("items", []))
        if unscored:
            print(
                f"WARNING: {len(unscored)} of {total} candidates carry no Smallbatch score "
                f"(index {', '.join(str(i) for i in unscored)}); ranking aid only, gather stands",
                file=sys.stderr,
            )
        scoring = {"status": "ok", **scores.get("package", {}),
                   "scored_candidates": total - len(unscored), "candidates": total}
        artifact_names.append("source_scores.json")

    artifacts = {
        name: {"sha256": sha256(out_dir / name), "bytes": (out_dir / name).stat().st_size}
        for name in artifact_names
    }
    config_identity = {"path": str(config), "sha256": sha256(config)}
    identity_input = json.dumps(
        {"artifacts": artifacts, "source_config": config_identity},
        sort_keys=True, separators=(",", ":"),
    )
    return {
        "schema_version": 1,
        "status": "valid",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gather_id": "sha256:" + hashlib.sha256(identity_input.encode()).hexdigest(),
        "source_config": config_identity,
        "artifacts": artifacts,
        "scoring": scoring,
        "proposal_freshness": crawl.get("proposal_freshness", {"status": "unavailable"}),
        "tier1_sources": statuses,
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def validate_manifest(path: Path, out_dir: Path, config: Path, max_age_hours: float) -> dict:
    manifest = _json(path)
    if manifest.get("schema_version") != 1 or manifest.get("status") != "valid":
        raise ValueError("unsupported or invalid gather manifest")
    generated = datetime.fromisoformat(manifest["generated_at"])
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - generated).total_seconds() / 3600
    if age_hours < -0.25 or age_hours > max_age_hours:
        raise ValueError(f"gather manifest age {age_hours:.2f}h is outside the allowed window")
    if manifest.get("source_config", {}).get("sha256") != sha256(config):
        raise ValueError("source config changed since the evening gather")
    for name, identity in manifest.get("artifacts", {}).items():
        artifact = out_dir / name
        if not artifact.is_file() or sha256(artifact) != identity.get("sha256"):
            raise ValueError(f"gather artifact identity mismatch: {name}")
    if any(name not in manifest.get("artifacts", {}) for name in REQUIRED):
        raise ValueError("gather manifest omits a required artifact")
    # Re-evaluate the coverage contract so a hand-edited manifest cannot bless omissions.
    tier1_statuses(config, _json(out_dir / "sources.json"), _json(out_dir / "crawl.json"))
    return manifest


def verify_proposals(manifest: dict, proposals: list[Path]) -> None:
    gather_id = manifest.get("gather_id")
    for path in proposals:
        proposal = _json(path)
        if proposal.get("gather_id") != gather_id:
            raise ValueError(f"proposal gather identity mismatch: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "validate", "id", "verify-proposals"))
    parser.add_argument("--manifest", type=Path, default=Path("out/gather_manifest.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--max-age-hours", type=float, default=12.0)
    parser.add_argument("--proposal", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.command == "create":
        manifest = create_manifest(args.out_dir, args.config)
        write_manifest(args.manifest, manifest)
    else:
        manifest = validate_manifest(
            args.manifest, args.out_dir, args.config, args.max_age_hours
        )
        if args.command == "verify-proposals":
            if not args.proposal:
                parser.error("verify-proposals requires at least one --proposal")
            verify_proposals(manifest, args.proposal)
    print(manifest["gather_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
