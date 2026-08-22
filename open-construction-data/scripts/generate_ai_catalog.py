#!/usr/bin/env python3
# Copyright (c) 2024-2026 OpenConstruction Open Science Initiative
# SPDX-License-Identifier: Apache-2.0

"""Generate a compact AI search index for Ask OpenConstruction.

The generated file is intentionally public metadata only. It is designed to be
small enough to send to an LLM for MVP search/ranking while preserving links
back to real OpenConstruction records.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIRS = [REPO_ROOT]
DEFAULT_OUTPUT = REPO_ROOT / "ai-catalog.json"

SOURCE_FILES = {
    "dataset": ["datasets.json", "dataset.json", "data/datasets.json", "catalog/datasets.json"],
    "model": ["models.json", "model.json", "data/models.json", "catalog/models.json"],
    "workflow": ["use-cases.json", "workflows.json", "deployments.json", "data/use-cases.json", "data/workflows.json"],
    "oer": ["oer.json", "oers.json", "education.json", "data/oer.json", "data/oers.json"],
}

SOURCE_DIRS = {
    "dataset": ["datasets", "data/datasets", "catalog/datasets"],
    "model": ["models", "data/models", "catalog/models"],
    "workflow": ["workflows", "deployments", "use-cases", "data/workflows", "catalog/workflows"],
    "oer": ["oer", "oers", "education", "data/oer", "catalog/oer"],
}

LIST_KEYS = (
    "datasets",
    "models",
    "workflows",
    "use_cases",
    "oers",
    "resources",
    "items",
    "data",
    "records",
    "results",
    "list",
)

ALIASES = {
    "hardhat": ["helmet", "ppe", "personal protective equipment"],
    "hard hats": ["helmet", "ppe", "personal protective equipment"],
    "helmet": ["hardhat", "ppe", "personal protective equipment"],
    "safety vest": ["vest", "ppe", "personal protective equipment"],
    "vest": ["safety vest", "ppe", "personal protective equipment"],
    "ppe": ["personal protective equipment", "helmet", "hardhat", "vest", "worker"],
    "worker": ["person", "people", "construction worker"],
    "workers": ["person", "people", "construction worker"],
    "bbox": ["bounding box", "bounding boxes", "object detection"],
    "bounding box": ["bbox", "bounding boxes", "object detection"],
    "bounding boxes": ["bbox", "bounding box", "object detection"],
    "segmentation mask": ["semantic segmentation", "instance segmentation", "mask"],
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    if isinstance(value, tuple):
        return [item for item in value if item not in (None, "")]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [part.strip() for part in re.split(r"\s*[,;]\s*", text) if part.strip()]
    return [value]


def text(value: Any, max_len: int = 500) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("title") or value.get("label") or value.get("url") or ""
    elif isinstance(value, list):
        value = ", ".join(text(item, max_len=120) for item in value if item not in (None, ""))
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    return clean[:max_len]


def first(record: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return ""


def first_media_url(record: dict[str, Any], media_type: str = "image") -> str:
    for item in as_list(record.get("media")):
        if isinstance(item, dict):
            item_type = text(item.get("type"), 80).lower()
            url = text(item.get("url") or item.get("src") or item.get("href"), 260)
            if url and (media_type in item_type or not item_type):
                return url
        else:
            url = text(item, 260)
            if re.search(r"\.(png|jpe?g|webp|gif|avif)(\?|$)", url, re.I):
                return url
    return ""


def unique_text(values: Iterable[Any], max_items: int = 16) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        for item in as_list(value):
            clean = text(item, 120)
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)
            output.append(clean)
            if len(output) >= max_items:
                return output
    return output


def normalize_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [item for item in value.values() if isinstance(item, dict)]
        return [
            item for key, item in payload.items()
            if key not in {"schema", "about", "metadata", "schema_version"}
            and isinstance(item, dict)
        ]
    return []


def find_sources(data_dirs: list[Path], kind: str) -> list[Path]:
    sources: list[Path] = []
    for data_dir in data_dirs:
        for relative in SOURCE_FILES[kind]:
            path = data_dir / relative
            if path.exists():
                sources.append(path)
        for relative in SOURCE_DIRS[kind]:
            folder = data_dir / relative
            if not folder.exists() or not folder.is_dir():
                continue
            sources.extend(
                path for path in sorted(folder.rglob("*.json"))
                if not re.search(r"(schema|template|example|vocab|validation)", path.name, re.I)
            )
    seen: set[Path] = set()
    unique: list[Path] = []
    for source in sources:
        resolved = source.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(source)
    return unique


def href_for(kind: str, record: dict[str, Any], title: str) -> str:
    record_id = text(first(record, ["id", "slug", "name", "title"]), 160) or title
    encoded = quote(record_id, safe="")
    if kind == "dataset":
        return f"datasets/detail.html?id={encoded}"
    if kind == "model":
        return f"models/details.html?id={encoded}"
    if kind == "workflow":
        return f"workflows/details.html?id={encoded}"
    if kind == "oer":
        return f"oers/details.html?id={encoded}"
    return "#"


def generated_terms(record: dict[str, Any]) -> list[str]:
    source = " ".join(
        unique_text(
            [
                record.get("classes"),
                record.get("object_classes"),
                record.get("objects"),
                record.get("annotation_types"),
                record.get("tasks"),
                record.get("potential_tasks"),
                record.get("applications"),
                record.get("topics"),
                record.get("media"),
                record.get("ai_tech"),
                record.get("tags"),
                record.get("title"),
                record.get("name"),
            ],
            max_items=80,
        )
    ).lower()
    terms: list[str] = []
    for key, aliases in ALIASES.items():
        if key in source:
            terms.extend(aliases)
    return unique_text(terms, max_items=24)


def compact_record(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    title = text(first(record, ["title", "name", "paper_title", "id"]), 180)
    topics = unique_text([record.get("topics"), record.get("topic"), record.get("keywords"), record.get("tags")])
    media = unique_text([record.get("media"), record.get("formats"), record.get("format"), record.get("resource_types"), record.get("resource_type")])
    summary = text(first(record, ["summary", "description", "abstract", "paper_title", "paper"]), 420)
    if not summary and kind == "oer":
        summary = text(
            ". ".join(
                item for item in [
                    f"Topics: {', '.join(topics[:6])}" if topics else "",
                    f"Formats: {', '.join(media[:6])}" if media else "",
                    f"Provider: {text(first(record, ['provider', 'publisher', 'organization']), 120)}" if first(record, ["provider", "publisher", "organization"]) else "",
                ]
                if item
            ),
            420,
        )
    links = record.get("links") if isinstance(record.get("links"), dict) else {}
    tasks = unique_text([record.get("tasks"), record.get("task"), record.get("potential_tasks")])
    objects = unique_text([record.get("classes"), record.get("object_classes"), record.get("objects"), record.get("categories")])
    annotations = unique_text([record.get("annotation_types"), record.get("annotations")])
    modalities = unique_text([record.get("data_modality"), record.get("data_modalities"), record.get("modalities"), record.get("modality")])
    applications = unique_text([record.get("applications"), record.get("application"), record.get("use_cases"), record.get("use_case")])
    image = text(first(record, ["image", "image_url", "image_path", "thumbnail", "thumbnail_url", "preview", "preview_image", "cover", "cover_image"]), 260) or first_media_url(record, "image")
    data_url = text(first(record, ["data_url", "dataset_url", "access", "url", "source", "link"]), 260) or text(links.get("source") or links.get("url") or links.get("paper") or links.get("doi"), 260)
    code_url = text(first(record, ["code_url", "github_url", "repo_url", "repository", "code"]), 260) or text(links.get("code") or links.get("github") or links.get("repository"), 260)
    return {
        "id": text(first(record, ["id", "slug", "name", "title"]), 160),
        "type": kind,
        "title": title,
        "summary": summary,
        "year": first(record, ["year", "publication_year", "release_year"]) or None,
        "tasks": tasks,
        "objects": objects,
        "annotations": annotations,
        "modalities": modalities,
        "applications": applications,
        "topics": topics,
        "media": media,
        "ai_tech": unique_text([record.get("ai_tech"), record.get("technology"), record.get("technologies")]),
        "stakeholders": unique_text([record.get("stakeholders")]),
        "phase": text(record.get("phase"), 120),
        "provider": text(first(record, ["provider", "publisher", "organization"]), 160),
        "publisher": text(record.get("publisher"), 160),
        "institutions": unique_text([record.get("institutions"), record.get("institution"), record.get("organizations")]),
        "contributor": text(record.get("contributor"), 160),
        "license": text(first(record, ["license", "licence"]), 120),
        "image": image,
        "data_url": data_url,
        "code_url": code_url,
        "href": href_for(kind, record, title),
        "aliases": generated_terms(record),
    }


def build_catalog(data_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind in ("dataset", "model", "workflow", "oer"):
        for source in find_sources(data_dirs, kind):
            for record in normalize_payload(load_json(source)):
                compact = compact_record(kind, record)
                if not compact["title"]:
                    continue
                key = (kind, (compact["id"] or compact["title"]).lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append(compact)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ai-catalog.json for Ask OpenConstruction.")
    parser.add_argument(
        "--data-dir",
        action="append",
        type=Path,
        help="Directory containing catalog JSON files. Can be passed multiple times.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data_dirs = [path.resolve() for path in (args.data_dir or DEFAULT_DATA_DIRS) if path.exists()]
    if not data_dirs:
        raise SystemExit("No catalog data directory found. Pass --data-dir path/to/catalog-data.")

    catalog = build_catalog(data_dirs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for row in catalog:
        counts[row["type"]] = counts.get(row["type"], 0) + 1
    print(f"Wrote {len(catalog)} AI catalog records to {args.output}")
    print("Counts:", ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())) or "none")


if __name__ == "__main__":
    main()
