import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from openconstruction_mcp.acquisition import AcquisitionPlan, resolve_dataset_download_plan
from openconstruction_mcp.catalog import CatalogClient
from openconstruction_mcp.downloads import DownloadManager, validate_public_download_url
from openconstruction_mcp.provider_auth import provider_auth_status


def fixture(path):
    if path != "datasets.json":
        return []
    return {
        "direct-data": {
            "name": "Direct Data",
            "license": "CC BY 4.0",
            "distribution": [
                {
                    "provider": "example",
                    "content_url": "https://downloads.example.org/direct.zip",
                    "filename": "direct.zip",
                    "content_size": 12,
                }
            ],
        },
        "github-data": {
            "name": "GitHub Data",
            "license": "MIT",
            "programmatic_access": [
                {
                    "provider": "github",
                    "method": "github_clone",
                    "repo_id": "open-construction/example",
                    "scope": "full",
                    "requires_auth": False,
                }
            ],
        },
        "globus-data": {
            "name": "Globus Data",
            "license": "custom",
            "programmatic_access": [
                {
                    "provider": "designsafe",
                    "method": "designsafe_globus",
                    "scope": "full",
                    "requires_auth": True,
                }
            ],
        },
        "manual-data": {
            "name": "Manual Data",
            "license": "custom",
            "access": "https://example.org/manual",
        },
    }


class AcquisitionPlanTest(unittest.TestCase):
    def setUp(self):
        self.catalog = CatalogClient(fetch_json=fixture)

    def test_resolves_direct_download(self):
        plan = resolve_dataset_download_plan(self.catalog, "DIRECT-DATA")
        self.assertEqual(plan.dataset_id, "direct-data")
        self.assertEqual(plan.kind, "direct")
        self.assertTrue(plan.executable_locally)
        self.assertEqual(plan.filename, "direct.zip")
        self.assertEqual(plan.estimated_size, 12)

    def test_resolves_automated_and_assisted_programmatic_routes(self):
        github = resolve_dataset_download_plan(self.catalog, "github-data")
        self.assertEqual(github.method, "github_clone")
        self.assertTrue(github.executable_locally)
        self.assertIn("git clone", github.instructions["command"])

        globus = resolve_dataset_download_plan(self.catalog, "globus-data")
        self.assertFalse(globus.executable_locally)
        self.assertTrue(globus.requires_auth)
        self.assertIn("Globus", globus.instructions["summary"])
        self.assertEqual(globus.auth["status"], "auth_required")
        self.assertEqual(globus.auth["auth_mode"], "local_provider")
        self.assertIsNone(globus.auth["credential_detected"])

    def test_resolves_manual_route_and_rejects_unknown_id(self):
        manual = resolve_dataset_download_plan(self.catalog, "manual-data")
        self.assertEqual(manual.kind, "site")
        self.assertFalse(manual.executable_locally)
        with self.assertRaisesRegex(ValueError, "Unknown dataset id"):
            resolve_dataset_download_plan(self.catalog, "missing")


class FakeResponse:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload.read(size)


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload

    def open(self, request, timeout=30):
        return FakeResponse(self.payload)


class FakeDownloadManager(DownloadManager):
    def _opener(self):
        return FakeOpener(b"test-payload")


class AuthFailureOpener:
    def open(self, request, timeout=30):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)


class AuthFailureDownloadManager(DownloadManager):
    def _opener(self):
        return AuthFailureOpener()


class DownloadManagerTest(unittest.TestCase):
    def direct_plan(self):
        return AcquisitionPlan(
            dataset_id="direct-data",
            dataset_name="Direct Data",
            kind="direct",
            provider="example",
            method="navigate",
            url="https://downloads.example.org/direct.zip",
            filename="direct.zip",
            license="CC BY 4.0",
            executable_locally=True,
            distributions=[
                {
                    "content_url": "https://downloads.example.org/direct.zip",
                    "filename": "direct.zip",
                }
            ],
        )

    def wait(self, manager, download_id):
        for _ in range(100):
            result = manager.get(download_id)
            if result["status"] in {"completed", "failed", "cancelled", "auth_required"}:
                return result
            time.sleep(0.01)
        self.fail("download job did not finish")

    def test_downloads_direct_file_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = FakeDownloadManager(root=tmp, url_validator=lambda url: None)
            started = manager.start(self.direct_plan(), "direct-data", accept_license=True)
            result = self.wait(manager, started["download_id"])

            self.assertEqual(result["status"], "completed")
            target = Path(tmp) / "direct-data"
            self.assertEqual((target / "direct.zip").read_bytes(), b"test-payload")
            manifest = json.loads((target / ".openconstruction-manifest.json").read_text())
            self.assertEqual(manifest["dataset_id"], "direct-data")
            self.assertEqual(manifest["files"][0]["size"], 12)

    def test_requires_license_acceptance_and_sandboxed_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = FakeDownloadManager(root=tmp, url_validator=lambda url: None)
            with self.assertRaisesRegex(ValueError, "accept_license=true"):
                manager.start(self.direct_plan(), None, accept_license=False)
            with self.assertRaisesRegex(ValueError, "inside OC_DOWNLOAD_ROOT"):
                manager.start(self.direct_plan(), "../escape", accept_license=True)

    def test_assisted_plan_returns_instructions_without_starting_job(self):
        plan = AcquisitionPlan(
            dataset_id="globus-data",
            dataset_name="Globus Data",
            kind="programmatic",
            method="designsafe_globus",
            executable_locally=False,
            instructions={"summary": "Authenticate with Globus."},
        )
        with tempfile.TemporaryDirectory() as tmp:
            manager = FakeDownloadManager(root=tmp, url_validator=lambda url: None)
            result = manager.start(plan, None, accept_license=False)
            self.assertEqual(result["status"], "instructions_required")

    def test_rejects_private_network_urls_and_guides_missing_provider_auth(self):
        with self.assertRaisesRegex(ValueError, "non-public"):
            validate_public_download_url("http://127.0.0.1/private")

        plan = AcquisitionPlan(
            dataset_id="private-hf",
            dataset_name="Private HF",
            kind="programmatic",
            method="huggingface_snapshot",
            requires_auth=True,
            executable_locally=True,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openconstruction_mcp.provider_auth._credential_detected", return_value=False
        ):
            manager = FakeDownloadManager(root=tmp, url_validator=lambda url: None)
            result = manager.start(plan, None, accept_license=True)

        self.assertEqual(result["status"], "auth_required")
        self.assertEqual(result["auth"]["auth_mode"], "local_provider")
        self.assertEqual(result["auth"]["provider"], "Hugging Face")
        self.assertIn("hf auth login", [step["command"] for step in result["auth"]["instructions"]])
        self.assertEqual(result["retry"]["tool"], "download_dataset")
        self.assertNotIn("hf_private-value", json.dumps(result))

    def test_detects_huggingface_cli_credential_without_exposing_it(self):
        with patch("huggingface_hub.get_token", return_value="hf_private-value"):
            result = provider_auth_status(
                "huggingface",
                "huggingface_snapshot",
                required=True,
            )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["credential_detected"])
        self.assertNotIn("hf_private-value", json.dumps(result))

    def test_runtime_http_auth_failure_becomes_safe_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthFailureDownloadManager(root=tmp, url_validator=lambda url: None)
            started = manager.start(self.direct_plan(), "protected-data", accept_license=True)
            result = self.wait(manager, started["download_id"])

        self.assertEqual(result["status"], "auth_required")
        self.assertIn("local terminal", result["auth"]["security_notice"])
        self.assertEqual(result["retry"]["tool"], "download_dataset")
        self.assertNotIn("Unauthorized", result["error"])


if __name__ == "__main__":
    unittest.main()
