#!/usr/bin/env python3
"""Score raw podcast gather records with the pinned Smallbatch function.

The function is an editorial ranking aid only. This script writes a sidecar; it
does not filter or rewrite either raw gather input.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

FUNCTION_REPO = "mmarks13/podcast-triage-structured-numeric-labels-qwen3.5-4b-GGUF"
FUNCTION_REVISION = "a0dccaa151e5d38202045019dcb0da196e738011"
PACKAGE_ID = "sha256:61e852b11c403d17be398f4a52c599234942ca24495a236e45426ccf7ae78db2"
MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
MODULE = "smallbatch_functions.triage_structured_numeric_labels"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIMENSIONS = ("editorial_fit", "source_provenance", "evidence_quality", "story_strength")
RANGES = {"editorial_fit": 2, "source_provenance": 2, "evidence_quality": 2, "story_strength": 3}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").casefold()
    return host.removeprefix("www.")


def _render_metadata(entry: dict) -> str:
    fields = (
        "organization", "author", "authors", "tags", "ai_keywords", "arxiv_id",
        "tag", "prerelease", "github_repo", "project_page", "discussion", "flair",
    )
    parts = []
    for field in fields:
        value = entry.get(field)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, dict, bool)):
            value = json.dumps(value, ensure_ascii=False)
        parts.append(f"{field}: {value}")
    return " | ".join(parts)


def _render_signals(entry: dict) -> str:
    labels = (
        ("upvotes", "upvotes"), ("points", "points"), ("score", "community_points"),
        ("num_comments", "comments"), ("upvote_ratio", "upvote_ratio"),
    )
    return " | ".join(
        f"{label}: {entry[field]}" for field, label in labels
        if entry.get(field) is not None
    )


def project_records(sources: Path, crawl: Path) -> list[dict]:
    """Project every raw record independently, retaining exact file provenance."""
    rows = []
    source_data = json.loads(sources.read_text())
    for feed, entries in source_data.get("feeds", {}).items():
        for index, entry in enumerate(entries):
            summary = str(entry.get("summary") or "").strip()
            url = str(entry.get("url") or "").strip()
            item = {
                "title": str(entry.get("title") or "").strip(),
                "source": str(entry.get("source") or feed).strip(),
                "metadata": _render_metadata(entry),
                "signals": _render_signals(entry),
                "summary": summary,
                "url": url,
                "source_domain": _domain(url),
                "summary_present": bool(summary),
            }
            provenance = {
                "file": sources.name, "kind": "feed", "feed": feed, "index": index,
                "source": item["source"], "title": item["title"], "url": url,
            }
            rows.append({"id": _stable_id({"input": item, "provenance": provenance}),
                         "input": item, "raw_provenance": provenance})

    crawl_data = json.loads(crawl.read_text())
    for index, entry in enumerate(crawl_data.get("items", [])):
        claims = [str(claim).strip() for claim in entry.get("claims", []) if str(claim).strip()]
        why = str(entry.get("why_included") or "").strip()
        summary = "\n".join([*(f"- {claim}" for claim in claims),
                              *( [f"why included: {why}"] if why else [])])
        display = str(entry.get("summary") or "").strip()
        sources_list = [str(value).strip() for value in entry.get("sources", []) if str(value).strip()]
        url = str(entry.get("url") or "").strip()
        item = {
            "title": display or (claims[0] if claims else url),
            "source": ", ".join(sources_list) + " (crawled)",
            "metadata": "",
            "signals": "",
            "summary": summary,
            "url": url,
            "source_domain": _domain(url),
            "summary_present": bool(display or claims),
        }
        provenance = {
            "file": crawl.name, "kind": "crawl", "index": index,
            "sources": sources_list, "title": item["title"], "url": url,
        }
        rows.append({"id": _stable_id({"input": item, "provenance": provenance}),
                     "input": item, "raw_provenance": provenance})
    return rows


def _verify_metadata(metadata: dict) -> dict:
    package = metadata.get("package", {})
    provenance = metadata.get("provenance", {})
    if package.get("package_id") != PACKAGE_ID:
        raise ValueError(f"Smallbatch package mismatch: {package.get('package_id')!r}")
    if provenance.get("base", {}).get("revision") != MODEL_REVISION:
        raise ValueError("Smallbatch underlying-model revision mismatch")
    return metadata


def _validate_output(output: object) -> dict[str, int]:
    if not isinstance(output, dict) or set(output) != set(DIMENSIONS):
        raise ValueError(f"Smallbatch returned an invalid dimension object: {output!r}")
    checked = {}
    for field in DIMENSIONS:
        value = output[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= RANGES[field]:
            raise ValueError(f"Smallbatch returned invalid {field}: {value!r}")
        checked[field] = value
    return checked


def score_files(
    sources: Path,
    crawl: Path,
    *,
    classify_batch: Callable[[list[dict]], list[dict]],
    metadata: dict,
) -> dict:
    metadata = _verify_metadata(metadata)
    rows = project_records(sources, crawl)
    outputs = list(classify_batch([row["input"] for row in rows]))
    if len(outputs) != len(rows):
        raise ValueError(f"Smallbatch returned {len(outputs)} outputs for {len(rows)} records")
    scored = []
    for row, output in zip(rows, outputs):
        dimensions = _validate_output(output)
        scored.append({
            **row,
            "dimensions": dimensions,
            "total": sum(dimensions.values()),
        })
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "package": {
            "repo": FUNCTION_REPO,
            "revision": FUNCTION_REVISION,
            "package_id": PACKAGE_ID,
            "model_revision": MODEL_REVISION,
            "module": MODULE,
        },
        "inputs": {
            sources.name: sha256(sources),
            crawl.name: sha256(crawl),
        },
        "records": scored,
    }


def _materialize_package(snapshot: Path, target: Path) -> Path:
    """Copy the package-declared tree out of its Hub transport snapshot.

    Hugging Face repositories contain a transport-level `.gitattributes` file. The
    published package intentionally excludes it from `checksums.json`, and its strict
    runtime rejects undeclared files. Materializing exactly the declared files retains
    the complete function package and leaves all integrity enforcement to that runtime.
    """
    checksums_path = snapshot / "checksums.json"
    checksums = json.loads(checksums_path.read_text())
    declared = checksums.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("Smallbatch snapshot has no declared package files")
    if target.is_dir():
        required = (target / "checksums.json", *(target / name for name in declared))
        if all(path.is_file() for path in required):
            return target
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=target.name + ".", dir=target.parent))
    try:
        _link_or_copy(checksums_path, temporary / "checksums.json")
        for name in declared:
            source = snapshot / name
            if not source.is_file():
                raise FileNotFoundError(f"Smallbatch snapshot is missing declared file: {name}")
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(source, destination)
        try:
            temporary.rename(target)
        except FileExistsError:  # another scorer populated the same immutable revision
            pass
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def _link_or_copy(source: Path, destination: Path) -> None:
    """Keep immutable package files alive if the Hub transport cache is evicted."""
    try:
        os.link(source.resolve(), destination)
    except OSError:
        shutil.copy2(source, destination)


def _materialized_package_complete(root: Path) -> bool:
    checksums_path = root / "checksums.json"
    if not checksums_path.is_file():
        return False
    try:
        declared = json.loads(checksums_path.read_text()).get("files")
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(declared, dict) and bool(declared) and all(
        (root / name).is_file() for name in declared
    )


def _resolve_package() -> Path:
    configured = os.environ.get("SMALLBATCH_FUNCTION_SOURCE")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"SMALLBATCH_FUNCTION_SOURCE is not a directory: {root}")
        return root
    cache_root = Path(
        os.environ.get(
            "SMALLBATCH_PACKAGE_CACHE",
            PROJECT_ROOT / "out" / "smallbatch-function",
        )
    ).expanduser()
    materialized = cache_root / FUNCTION_REVISION
    if _materialized_package_complete(materialized):
        return materialized
    if materialized.is_dir():
        shutil.rmtree(materialized)
    from huggingface_hub import snapshot_download
    snapshot = Path(
        snapshot_download(repo_id=FUNCTION_REPO, revision=FUNCTION_REVISION)
    ).resolve()
    return _materialize_package(snapshot, materialized)


def _runtime(root: Path):
    python_src = root / "python" / "src"
    if not python_src.is_dir():
        raise FileNotFoundError(f"Smallbatch package is missing python/src: {root}")
    sys.path.insert(0, str(python_src))
    module = importlib.import_module(MODULE)
    threads = int(os.environ["SMALLBATCH_THREADS"]) if os.environ.get("SMALLBATCH_THREADS") else None
    return module.load(root, device=os.environ.get("SMALLBATCH_DEVICE", "auto"), threads=threads)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("out/sources.json"))
    parser.add_argument("--crawl", type=Path, default=Path("out/crawl.json"))
    parser.add_argument("--out", type=Path, default=Path("out/source_scores.json"))
    args = parser.parse_args()
    root = _resolve_package()
    with _runtime(root) as function:
        result = score_files(
            args.sources,
            args.crawl,
            classify_batch=function.run_batch,
            metadata=function.metadata(),
        )
    atomic_json(args.out, result)
    print(f"Wrote {args.out}: {len(result['records'])} scored raw records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
