from __future__ import annotations

import re
import shlex
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any

from .catalog import CatalogClient, clean_text
from .provider_auth import provider_auth_status


AUTOMATED_METHODS = {
    "github_clone",
    "huggingface_snapshot",
    "figshare_files",
    "http_files",
}


def _http_url(value: Any) -> str | None:
    text = clean_text(value, 1000)
    if not text:
        return None
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return text


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_dirname(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return safe or "dataset"


@dataclass(frozen=True)
class AcquisitionPlan:
    dataset_id: str
    dataset_name: str
    kind: str
    provider: str | None = None
    method: str | None = None
    url: str | None = None
    filename: str | None = None
    license: str | None = None
    requires_auth: bool = False
    executable_locally: bool = False
    estimated_size: int | None = None
    distributions: list[dict[str, Any]] = field(default_factory=list)
    programmatic_access: dict[str, Any] | None = None
    instructions: dict[str, Any] | None = None
    auth: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_exact_dataset(catalog: CatalogClient, dataset_id: str) -> dict[str, Any]:
    requested = clean_text(dataset_id, 180).casefold()
    if not requested:
        raise ValueError("dataset_id is required")
    for resource in catalog.load():
        if resource.get("type") != "dataset":
            continue
        if clean_text(resource.get("id"), 180).casefold() == requested:
            return resource
    raise ValueError(f"Unknown dataset id: {dataset_id}")


def _instructions(dataset_id: str, method: str, metadata: dict[str, Any]) -> dict[str, Any]:
    destination = f"./{_safe_dirname(dataset_id)}"
    if method == "github_clone":
        repo_id = clean_text(metadata.get("repo_id"), 240)
        if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
            return {
                "summary": "Clone the versioned dataset repository with Git.",
                "command": f"git clone {shlex.quote(f'https://github.com/{repo_id}.git')} {shlex.quote(destination)}",
            }
    if method == "huggingface_snapshot":
        repo_id = clean_text(metadata.get("repo_id"), 240)
        if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
            revision = clean_text(metadata.get("revision"), 160) or "main"
            return {
                "summary": "Download the pinned Hugging Face dataset snapshot.",
                "command": (
                    "python -m pip install -U huggingface_hub\n"
                    f"hf download {shlex.quote(repo_id)} --repo-type dataset "
                    f"--revision {shlex.quote(revision)} --local-dir {shlex.quote(destination)}"
                ),
            }
    if method in AUTOMATED_METHODS:
        return {
            "summary": f"The local OC MCP can execute the {method} adapter.",
            "command": None,
        }

    labels = {
        "google_drive_folder": "Use the Google Drive API with the user's own credentials.",
        "dataverse_collection": "Enumerate the Dataverse collection and download its published dataset bundles.",
        "designsafe_globus": "Authenticate with Globus and select a user-controlled destination collection.",
        "dreamhouse_setup": "Install the official DreamHouse package and run its artifact setup command.",
        "roboflow_version": "Authenticate with Roboflow and request the declared versioned export.",
        "kaggle_competition": "Accept the competition rules and authenticate with the Kaggle CLI.",
        "baidu_share_transfer": "Authenticate locally with BaiduPCS-Go and transfer the shared dataset.",
    }
    return {
        "summary": labels.get(method, "Follow the provider-specific access instructions."),
        "command": None,
        "documentation_url": _http_url(metadata.get("documentation_url")),
        "notice": clean_text(metadata.get("notice"), 1000) or None,
    }


def resolve_dataset_download_plan(catalog: CatalogClient, dataset_id: str) -> AcquisitionPlan:
    resource = get_exact_dataset(catalog, dataset_id)
    source = resource.get("source") if isinstance(resource.get("source"), dict) else {}
    canonical_id = clean_text(resource.get("id"), 180)
    dataset_name = clean_text(resource.get("title"), 240) or canonical_id
    license_name = clean_text(source.get("license") or resource.get("license"), 160) or None
    distributions = _objects(source.get("distribution"))

    if len(distributions) == 1:
        distribution = distributions[0]
        url = _http_url(distribution.get("content_url") or distribution.get("contentUrl") or distribution.get("url"))
        if distribution.get("browser_download") is not False and url:
            size = distribution.get("content_size")
            return AcquisitionPlan(
                dataset_id=canonical_id,
                dataset_name=dataset_name,
                kind="direct",
                provider=clean_text(distribution.get("provider"), 120) or None,
                method=clean_text(distribution.get("download_method"), 80) or "navigate",
                url=url,
                filename=clean_text(distribution.get("filename"), 240) or None,
                license=license_name,
                executable_locally=True,
                estimated_size=size if isinstance(size, int) and size >= 0 else None,
                distributions=distributions,
            )

    methods = _objects(source.get("programmatic_access"))
    if methods:
        method_metadata = methods[0]
        method = clean_text(method_metadata.get("method"), 120)
        provider = clean_text(method_metadata.get("provider"), 120) or None
        requires_auth = method_metadata.get("requires_auth") is True
        sizes = [item.get("content_size") for item in distributions]
        estimated_size = sum(size for size in sizes if isinstance(size, int) and size >= 0) if sizes else None
        warnings: list[str] = []
        if method not in AUTOMATED_METHODS:
            warnings.append("This provider still requires an assisted or provider-specific workflow.")
        if requires_auth:
            warnings.append("Provider authentication is required and must be completed locally by the user.")
        if estimated_size is None and method in AUTOMATED_METHODS:
            warnings.append("The source does not declare a total size, so disk usage cannot be fully checked before execution.")
        return AcquisitionPlan(
            dataset_id=canonical_id,
            dataset_name=dataset_name,
            kind="programmatic",
            provider=provider,
            method=method or None,
            url=_http_url(method_metadata.get("documentation_url")) or _http_url(source.get("access")),
            license=license_name,
            requires_auth=requires_auth,
            executable_locally=method in AUTOMATED_METHODS,
            estimated_size=estimated_size,
            distributions=distributions,
            programmatic_access=method_metadata,
            instructions=_instructions(canonical_id, method, method_metadata),
            auth=(
                provider_auth_status(provider, method, required=True, detect_credentials=False)
                if requires_auth
                else None
            ),
            warnings=warnings,
        )

    fallback = _http_url(source.get("access")) or _http_url(source.get("url")) or _http_url(resource.get("url"))
    return AcquisitionPlan(
        dataset_id=canonical_id,
        dataset_name=dataset_name,
        kind="site",
        url=fallback,
        license=license_name,
        instructions={"summary": "Open the source page and complete the provider's manual access workflow.", "command": None},
        warnings=["No machine-readable download route is currently available for this dataset."],
    )
