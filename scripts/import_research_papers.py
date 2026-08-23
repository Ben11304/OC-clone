#!/usr/bin/env python3
"""Import an audited dataset-paper corpus into OpenConstruction.

The importer keeps one stable location per dataset and emits a machine-readable
manifest for the website and MCP layer. PDF binaries are intentionally ignored
by Git until their redistribution rights have been reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Directory against which paths in the source manifest are resolved.",
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset_id(dataset_id: str) -> None:
    if (
        not dataset_id
        or dataset_id in {".", ".."}
        or "/" in dataset_id
        or "\\" in dataset_id
        or "\0" in dataset_id
    ):
        raise ValueError(f"Unsafe dataset id: {dataset_id!r}")


def atomic_copy(source: Path, destination: Path, expected_hash: str | None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing_hash = sha256(destination)
        if not expected_hash or existing_hash == expected_hash:
            return existing_hash

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    copied_hash = sha256(temporary)
    if expected_hash and copied_hash != expected_hash:
        temporary.unlink(missing_ok=True)
        raise ValueError(
            f"Checksum mismatch for {source}: expected {expected_hash}, got {copied_hash}"
        )
    os.replace(temporary, destination)
    return copied_hash


def main() -> int:
    args = parse_args()
    source_manifest = load_json(args.source_manifest)
    catalog = load_json(args.catalog)
    results = source_manifest.get("results", [])

    catalog_ids = set(catalog)
    result_ids = {row["id"] for row in results}
    if catalog_ids != result_ids:
        raise ValueError(
            "Catalog and paper manifest IDs differ: "
            f"catalog_only={sorted(catalog_ids - result_ids)!r}, "
            f"manifest_only={sorted(result_ids - catalog_ids)!r}"
        )

    available = 0
    unresolved = 0
    total_bytes = 0
    papers: dict[str, dict[str, Any]] = {}

    for row in sorted(results, key=lambda item: item["id"].casefold()):
        dataset_id = row["id"]
        validate_dataset_id(dataset_id)
        status = row.get("status")
        entry: dict[str, Any] = {
            "dataset_name": row.get("name") or catalog[dataset_id].get("name"),
            "paper_title": row.get("expected_paper_title"),
            "doi": row.get("doi"),
            "source_url": row.get("source_url") or row.get("final_url"),
            "redistribution_status": "unreviewed",
        }

        if status == "have_pdf":
            source_path = args.source_root / row["path"]
            if not source_path.is_file():
                raise FileNotFoundError(f"Paper not found for {dataset_id}: {source_path}")
            destination_path = args.destination / dataset_id / "paper.pdf"
            expected_hash = row.get("pdf_sha256")
            copied_hash = expected_hash
            if not args.dry_run:
                copied_hash = atomic_copy(source_path, destination_path, expected_hash)
            entry.update(
                {
                    "status": "available_local",
                    "path": f"papers/{dataset_id}/paper.pdf",
                    "sha256": copied_hash,
                    "bytes": row.get("bytes") or source_path.stat().st_size,
                    "pages": row.get("pages"),
                    "identity_basis": row.get("identity_basis"),
                    "acquisition_method": row.get("method"),
                }
            )
            available += 1
            total_bytes += int(entry["bytes"] or 0)
        else:
            entry.update(
                {
                    "status": "unresolved",
                    "reason": row.get("reason") or "paper_not_available",
                    "path": None,
                }
            )
            unresolved += 1

        papers[dataset_id] = entry

    output = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": args.source_manifest.name,
        "summary": {
            "datasets": len(papers),
            "available_local": available,
            "unresolved": unresolved,
            "total_bytes": total_bytes,
        },
        "papers": papers,
    }

    if not args.dry_run:
        args.destination.mkdir(parents=True, exist_ok=True)
        manifest_path = args.destination / "manifest.json"
        temporary_manifest = manifest_path.with_suffix(".json.tmp")
        with temporary_manifest.open("w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_manifest, manifest_path)

    print(
        json.dumps(
            {
                "datasets": len(papers),
                "available_local": available,
                "unresolved": unresolved,
                "total_bytes": total_bytes,
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
