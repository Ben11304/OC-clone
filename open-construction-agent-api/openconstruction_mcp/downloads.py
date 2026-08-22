from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .acquisition import AcquisitionPlan
from .provider_auth import auth_required_response, provider_auth_status


DEFAULT_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
USER_AGENT = "OpenConstruction-MCP/0.1"


def _safe_filename(value: str, fallback: str = "download.bin") -> str:
    name = Path(value).name
    if name in {"", ".", ".."} or not re.fullmatch(r"[A-Za-z0-9._ -]+", name):
        return fallback
    return name


def _safe_directory_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return name or "dataset"


def validate_public_download_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Download URL is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) download URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in download URLs")
    if port not in {None, 80, 443}:
        raise ValueError("Non-standard download URL ports are not allowed")
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("Local network download URLs are not allowed")
    try:
        addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Download hostname cannot be resolved: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("Download URL resolves to a non-public network address")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        validate_public_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class DownloadJob:
    id: str
    dataset_id: str
    destination: str
    plan: dict[str, Any]
    status: str = "queued"
    bytes_downloaded: int = 0
    bytes_total: int | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    auth: dict[str, Any] | None = None
    retry: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    process: subprocess.Popen[Any] | None = field(default=None, repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "download_id": self.id,
            "dataset_id": self.dataset_id,
            "destination": self.destination,
            "status": self.status,
            "bytes_downloaded": self.bytes_downloaded,
            "bytes_total": self.bytes_total,
            "files": list(self.files),
            "error": self.error,
            "auth": self.auth,
            "retry": self.retry,
            "created_at": int(self.created_at),
            "started_at": int(self.started_at) if self.started_at else None,
            "completed_at": int(self.completed_at) if self.completed_at else None,
        }


class DownloadManager:
    def __init__(
        self,
        root: str | Path | None = None,
        max_download_bytes: int | None = None,
        url_validator: Callable[[str], None] = validate_public_download_url,
    ) -> None:
        configured_root = root or os.environ.get("OC_DOWNLOAD_ROOT") or Path.home() / ".openconstruction" / "datasets"
        self.root = Path(configured_root).expanduser().resolve()
        configured_max = os.environ.get("OC_MAX_DOWNLOAD_BYTES")
        self.max_download_bytes = max_download_bytes or int(configured_max or DEFAULT_MAX_DOWNLOAD_BYTES)
        self.url_validator = url_validator
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def resolve_destination(self, plan: AcquisitionPlan, destination: str | None) -> Path:
        relative = destination.strip() if isinstance(destination, str) and destination.strip() else _safe_directory_name(plan.dataset_id)
        candidate = Path(relative)
        if candidate.is_absolute():
            raise ValueError("destination must be relative to OC_DOWNLOAD_ROOT")
        if len(candidate.parts) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", candidate.name):
            raise ValueError("destination must be one dataset directory name inside OC_DOWNLOAD_ROOT")
        target = (self.root / candidate).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("destination must stay inside OC_DOWNLOAD_ROOT") from exc
        if target == self.root:
            raise ValueError("destination must name a dataset directory")
        return target

    def start(self, plan: AcquisitionPlan, destination: str | None, accept_license: bool) -> dict[str, Any]:
        if not plan.executable_locally:
            result = {"status": "instructions_required", "plan": plan.to_dict()}
            if plan.requires_auth:
                result["auth"] = provider_auth_status(plan.provider, plan.method, required=True)
            return result
        if accept_license is not True:
            raise ValueError("Set accept_license=true only after the user reviews and accepts the dataset license and source terms")
        if plan.estimated_size is not None and plan.estimated_size > self.max_download_bytes:
            raise ValueError("Dataset exceeds OC_MAX_DOWNLOAD_BYTES")
        target = self.resolve_destination(plan, destination)
        if plan.requires_auth:
            auth = provider_auth_status(plan.provider, plan.method, required=True)
            if auth["status"] == "auth_required":
                return auth_required_response(
                    plan.provider,
                    plan.method,
                    dataset_id=plan.dataset_id,
                    destination=destination,
                    accept_license=accept_license,
                )
        with self._lock:
            if target.exists() or any(job.destination == str(target) and job.status not in {"failed", "cancelled"} for job in self._jobs.values()):
                raise ValueError("Download destination already exists or is reserved by another job")
            job = DownloadJob(
                id=f"dl_{uuid.uuid4().hex[:16]}",
                dataset_id=plan.dataset_id,
                destination=str(target),
                plan=plan.to_dict(),
                bytes_total=plan.estimated_size,
            )
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job,), name=f"oc-{job.id}", daemon=True)
        thread.start()
        return job.public_dict()

    def get(self, download_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(download_id)
            if not job:
                raise ValueError(f"Unknown download id: {download_id}")
            return job.public_dict()

    def cancel(self, download_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(download_id)
            if not job:
                raise ValueError(f"Unknown download id: {download_id}")
            if job.status in {"completed", "failed", "cancelled", "auth_required"}:
                return job.public_dict()
            job.cancel_event.set()
            process = job.process
        if process and process.poll() is None:
            process.terminate()
        return self.get(download_id)

    def _run(self, job: DownloadJob) -> None:
        job.status = "resolving"
        job.started_at = time.time()
        target = Path(job.destination)
        try:
            if job.cancel_event.is_set():
                raise InterruptedError("Download cancelled")
            method = str(job.plan.get("method") or "")
            kind = str(job.plan.get("kind") or "")
            if kind == "direct":
                target.mkdir(parents=True, exist_ok=False)
                distribution = job.plan["distributions"][0]
                filename = _safe_filename(str(distribution.get("filename") or job.plan.get("filename") or "download.bin"))
                self._download_url(job, str(job.plan["url"]), target / filename)
            elif method == "http_files":
                target.mkdir(parents=True, exist_ok=False)
                for index, item in enumerate(job.plan.get("distributions") or [], start=1):
                    url = str(item.get("content_url") or "")
                    filename = _safe_filename(str(item.get("filename") or ""), f"download-{index}.bin")
                    self._download_url(job, url, target / filename)
            elif method == "github_clone":
                self._clone_github(job, target)
            elif method == "huggingface_snapshot":
                self._download_huggingface(job, target)
            elif method == "figshare_files":
                target.mkdir(parents=True, exist_ok=False)
                self._download_figshare(job, target)
            else:
                raise ValueError(f"No local executor is available for method: {method or kind}")
            if job.cancel_event.is_set():
                raise InterruptedError("Download cancelled")
            self._write_manifest(job, target)
            job.status = "completed"
        except InterruptedError as exc:
            job.status = "cancelled"
            job.error = str(exc)
        except Exception as exc:
            if self._is_auth_failure(exc):
                job.status = "auth_required"
                job.error = "Provider authentication is required or the local credential was rejected."
                job.auth = provider_auth_status(
                    str(job.plan.get("provider") or "") or None,
                    str(job.plan.get("method") or "") or None,
                    required=True,
                    detect_credentials=False,
                )
                job.retry = {
                    "tool": "download_dataset",
                    "arguments": {
                        "dataset_id": job.dataset_id,
                        "destination": Path(job.destination).name,
                        "accept_license": True,
                    },
                }
            else:
                job.status = "failed"
                job.error = str(exc)
        finally:
            job.completed_at = time.time()

    def _opener(self) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(SafeRedirectHandler())

    @staticmethod
    def _is_auth_failure(exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return code in {401, 403} or status_code in {401, 403}

    def _download_url(self, job: DownloadJob, url: str, target: Path) -> None:
        if job.cancel_event.is_set():
            raise InterruptedError("Download cancelled")
        self.url_validator(url)
        if target.exists():
            raise ValueError(f"Refusing to overwrite existing file: {target.name}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        written = 0
        job.status = "downloading"
        try:
            with self._opener().open(request, timeout=30) as response, partial.open("xb") as output:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_download_bytes:
                    raise ValueError("Remote file exceeds OC_MAX_DOWNLOAD_BYTES")
                while True:
                    if job.cancel_event.is_set():
                        raise InterruptedError("Download cancelled")
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if job.bytes_downloaded + len(chunk) > self.max_download_bytes:
                        raise ValueError("Download exceeds OC_MAX_DOWNLOAD_BYTES")
                    output.write(chunk)
                    digest.update(chunk)
                    job.bytes_downloaded += len(chunk)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        job.files.append({"path": target.name, "size": written, "sha256": digest.hexdigest(), "source_url": url})

    def _clone_github(self, job: DownloadJob, target: Path) -> None:
        metadata = job.plan.get("programmatic_access") or {}
        repo_id = str(metadata.get("repo_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
            raise ValueError("Invalid GitHub repo_id in catalog metadata")
        if shutil.which("git") is None:
            raise ValueError("git is required for github_clone downloads")
        target.parent.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone", "--depth", "1"]
        revision = str(metadata.get("revision") or "").strip()
        if revision and revision not in {"main", "master"}:
            if not re.fullmatch(r"[A-Za-z0-9._/-]+", revision):
                raise ValueError("Invalid Git revision in catalog metadata")
            command.extend(["--branch", revision])
        command.extend([f"https://github.com/{repo_id}.git", str(target)])
        job.status = "downloading"
        job.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        while job.process.poll() is None:
            if job.cancel_event.wait(0.2):
                job.process.terminate()
                raise InterruptedError("Download cancelled")
        if job.process.returncode != 0:
            raise ValueError(f"Git clone failed with exit code {job.process.returncode}")
        job.files.append({"path": ".", "kind": "git_repository", "source": repo_id, "revision": revision or None})

    def _download_huggingface(self, job: DownloadJob, target: Path) -> None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ValueError("Install huggingface_hub to execute huggingface_snapshot downloads") from exc
        metadata = job.plan.get("programmatic_access") or {}
        repo_id = str(metadata.get("repo_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
            raise ValueError("Invalid Hugging Face repo_id in catalog metadata")
        target.parent.mkdir(parents=True, exist_ok=True)
        job.status = "downloading"
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            revision=str(metadata.get("revision") or "main"),
            local_dir=str(target),
            token=True if bool(job.plan.get("requires_auth")) else None,
        )
        job.files.append({"path": ".", "kind": "huggingface_snapshot", "source": repo_id})

    def _download_figshare(self, job: DownloadJob, target: Path) -> None:
        metadata = job.plan.get("programmatic_access") or {}
        record_id = str(metadata.get("record_id") or "")
        if not record_id.isdigit():
            raise ValueError("Invalid Figshare record_id in catalog metadata")
        api_url = str(metadata.get("api_url") or f"https://api.figshare.com/v2/articles/{record_id}")
        parsed = urllib.parse.urlparse(api_url)
        if parsed.hostname != "api.figshare.com":
            raise ValueError("Figshare API URL must use api.figshare.com")
        self.url_validator(api_url)
        request = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
        with self._opener().open(request, timeout=30) as response:
            payload = json.load(response)
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(files, list) or not files:
            raise ValueError("Figshare returned no public files")
        for index, item in enumerate(files, start=1):
            if not isinstance(item, dict):
                continue
            filename = _safe_filename(str(item.get("name") or ""), f"figshare-{index}.bin")
            self._download_url(job, str(item.get("download_url") or ""), target / filename)

    def _write_manifest(self, job: DownloadJob, target: Path) -> None:
        job.status = "verifying"
        manifest = {
            "schema_version": "1.0",
            "dataset_id": job.dataset_id,
            "provider": job.plan.get("provider"),
            "method": job.plan.get("method"),
            "license": job.plan.get("license"),
            "source": job.plan.get("url"),
            "downloaded_at": int(time.time()),
            "bytes_downloaded": job.bytes_downloaded,
            "files": job.files,
        }
        target.mkdir(parents=True, exist_ok=True)
        manifest_path = target / ".openconstruction-manifest.json"
        with manifest_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
