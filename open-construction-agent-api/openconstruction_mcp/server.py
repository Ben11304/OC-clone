from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .acquisition import resolve_dataset_download_plan
from .catalog import CatalogClient
from .downloads import DownloadManager
from .skills import get_skill, list_skills
from .workflows import dataset_discovery


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "openconstruction", "version": "0.1.0"}

catalog = CatalogClient()
download_manager = DownloadManager()


def schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


RESOURCE_TYPES = ["dataset", "model", "workflow", "oer", "tool", "guide", "contributor", "benchmark", "vocabulary"]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_resources",
        "title": "Search OpenConstruction resources",
        "description": "Search datasets, models, workflows, OERs, tools, guides, contributors, benchmarks, and vocabulary.",
        "inputSchema": schema(
            {
                "query": {"type": "string", "minLength": 1},
                "types": {"type": "array", "items": {"type": "string", "enum": RESOURCE_TYPES}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["query"],
        ),
    },
    {
        "name": "get_resource",
        "title": "Get OpenConstruction resource",
        "description": "Get one resource by type and id.",
        "inputSchema": schema(
            {
                "type": {"type": "string", "enum": RESOURCE_TYPES},
                "id": {"type": "string", "minLength": 1},
            },
            ["type", "id"],
        ),
    },
    {
        "name": "compare_resources",
        "title": "Compare OpenConstruction resources",
        "description": "Compare two or more catalog resources for a user goal.",
        "inputSchema": schema(
            {
                "resources": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 8,
                    "items": schema(
                        {
                            "type": {"type": "string", "enum": RESOURCE_TYPES},
                            "id": {"type": "string", "minLength": 1},
                        },
                        ["type", "id"],
                    ),
                },
                "goal": {"type": "string"},
            },
            ["resources"],
        ),
    },
    {
        "name": "get_catalog_stats",
        "title": "Get catalog statistics",
        "description": "Return counts by resource type for the loaded catalog snapshot.",
        "inputSchema": schema(),
    },
    {
        "name": "ask_openconstruction",
        "title": "Ask OpenConstruction",
        "description": "Answer a catalog-grounded question with matching resources.",
        "inputSchema": schema({"query": {"type": "string", "minLength": 1}}, ["query"]),
    },
    {
        "name": "find_datasets",
        "title": "Dataset Discovery",
        "description": "Find datasets by task, modality, object class, annotation type, license, or access needs.",
        "inputSchema": schema(
            {
                "task": {"type": "string"},
                "modality": {"type": "string"},
                "object_class": {"type": "string"},
                "annotation": {"type": "string"},
                "license": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }
        ),
    },
    {
        "name": "run_dataset_discovery",
        "title": "Run Dataset Discovery Skill",
        "description": "Run the Dataset Discovery skill as a structured workflow that searches, ranks, and explains dataset candidates.",
        "inputSchema": schema(
            {
                "task": {"type": "string", "minLength": 1},
                "modality": {"type": "string"},
                "object_class": {"type": "string"},
                "annotation": {"type": "string"},
                "license": {"type": "string"},
                "access_requirement": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ["task"],
        ),
    },
    {
        "name": "find_models",
        "title": "Model Discovery",
        "description": "Find models by task, dataset, modality, method, or publication evidence.",
        "inputSchema": schema(
            {
                "task": {"type": "string"},
                "dataset": {"type": "string"},
                "modality": {"type": "string"},
                "method": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }
        ),
    },
    {
        "name": "explain_schema",
        "title": "Schema Explainer",
        "description": "Explain common OpenConstruction metadata fields and where they appear in catalog records.",
        "inputSchema": schema({"field": {"type": "string"}, "resource_type": {"type": "string", "enum": RESOURCE_TYPES}}),
    },
    {
        "name": "analyze_catalog_gaps",
        "title": "Catalog Gap Analysis",
        "description": "Inspect catalog coverage by type and return possible metadata gaps for a topic.",
        "inputSchema": schema({"topic": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
    },
    {
        "name": "prepare_benchmark_submission",
        "title": "Benchmark Submission Prep",
        "description": "Create a checklist for preparing benchmark metadata and linked resources.",
        "inputSchema": schema(
            {
                "dataset_id": {"type": "string"},
                "model_id": {"type": "string"},
                "task": {"type": "string"},
                "metric": {"type": "string"},
            },
            ["task"],
        ),
    },
    {
        "name": "validate_metadata_record",
        "title": "Metadata Validation",
        "description": "Check one draft metadata record for important missing fields.",
        "inputSchema": schema({"record": {"type": "object"}, "resource_type": {"type": "string", "enum": RESOURCE_TYPES}}, ["record", "resource_type"]),
    },
    {
        "name": "list_skills",
        "title": "List OpenConstruction skills",
        "description": "List repo-defined OpenConstruction skill metadata.",
        "inputSchema": schema(
            {
                "lifecycle_stage": {
                    "type": "string",
                    "enum": ["discover", "select", "access", "understand", "analyze", "execute"],
                }
            }
        ),
    },
    {
        "name": "get_skill",
        "title": "Get OpenConstruction skill",
        "description": "Get one OpenConstruction skill definition by id.",
        "inputSchema": schema({"id": {"type": "string", "minLength": 1}}, ["id"]),
    },
    {
        "name": "get_dataset_download_plan",
        "title": "Get Dataset Download Plan",
        "description": "Resolve the trusted OpenConstruction metadata route without writing files, including local provider-auth guidance when required.",
        "inputSchema": schema({"dataset_id": {"type": "string", "minLength": 1}}, ["dataset_id"]),
    },
    {
        "name": "download_dataset",
        "title": "Download Dataset Locally",
        "description": "Start a background download inside OC_DOWNLOAD_ROOT. If status is auth_required, show its local provider login instructions and retry payload; never ask the user to paste credentials into chat. Requires explicit license acceptance and never accepts arbitrary source URLs or shell commands.",
        "inputSchema": schema(
            {
                "dataset_id": {"type": "string", "minLength": 1},
                "destination": {
                    "type": "string",
                    "maxLength": 160,
                    "pattern": "^[A-Za-z0-9._-]+$",
                    "description": "Optional path relative to OC_DOWNLOAD_ROOT. Defaults to the dataset id.",
                },
                "accept_license": {
                    "type": "boolean",
                    "description": "True only after the user reviews and accepts the dataset license and source terms.",
                },
            },
            ["dataset_id", "accept_license"],
        ),
    },
    {
        "name": "get_download_status",
        "title": "Get Dataset Download Status",
        "description": "Return progress, files, and errors for a local OC dataset download job.",
        "inputSchema": schema({"download_id": {"type": "string", "minLength": 1}}, ["download_id"]),
    },
    {
        "name": "cancel_download",
        "title": "Cancel Dataset Download",
        "description": "Request cancellation of a running local OC dataset download job.",
        "inputSchema": schema({"download_id": {"type": "string", "minLength": 1}}, ["download_id"]),
    },
]

LOCAL_ONLY_TOOLS = {"download_dataset", "get_download_status", "cancel_download"}


def text_content(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value,
            }
        ],
        "isError": False,
    }


def query_from_args(arguments: dict[str, Any], keys: list[str]) -> str:
    return " ".join(str(arguments.get(key, "")) for key in keys if arguments.get(key)).strip()


def call_tool(name: str, arguments: dict[str, Any], allow_download_execution: bool = True) -> Any:
    if name == "search_resources":
        return {"resources": catalog.search(arguments["query"], arguments.get("types"), int(arguments.get("limit", 20)))}
    if name == "get_resource":
        return {"resource": catalog.get(arguments["type"], arguments["id"])}
    if name == "compare_resources":
        return catalog.compare(arguments["resources"], arguments.get("goal", ""))
    if name == "get_catalog_stats":
        return catalog.stats()
    if name == "ask_openconstruction":
        return catalog.answer(arguments["query"])
    if name == "find_datasets":
        query = query_from_args(arguments, ["task", "modality", "object_class", "annotation", "license"])
        return {"resources": catalog.search(query or "dataset", ["dataset"], int(arguments.get("limit", 12)))}
    if name == "run_dataset_discovery":
        return dataset_discovery(arguments, catalog)
    if name == "find_models":
        query = query_from_args(arguments, ["task", "dataset", "modality", "method"])
        return {"resources": catalog.search(query or "model", ["model"], int(arguments.get("limit", 12)))}
    if name == "explain_schema":
        return explain_schema(arguments.get("field", ""), arguments.get("resource_type", ""))
    if name == "analyze_catalog_gaps":
        return analyze_catalog_gaps(arguments.get("topic", ""), int(arguments.get("limit", 20)))
    if name == "prepare_benchmark_submission":
        return prepare_benchmark_submission(arguments)
    if name == "validate_metadata_record":
        return validate_metadata_record(arguments["record"], arguments["resource_type"])
    if name == "list_skills":
        return list_skills(arguments.get("lifecycle_stage"))
    if name == "get_skill":
        return {"skill": get_skill(arguments["id"])}
    if name == "get_dataset_download_plan":
        return {"plan": resolve_dataset_download_plan(catalog, arguments["dataset_id"]).to_dict()}
    if name == "download_dataset":
        if not allow_download_execution:
            raise ValueError("Remote MCP cannot write to the user's filesystem; use the local stdio MCP to execute downloads")
        plan = resolve_dataset_download_plan(catalog, arguments["dataset_id"])
        return download_manager.start(plan, arguments.get("destination"), arguments.get("accept_license") is True)
    if name == "get_download_status":
        if not allow_download_execution:
            raise ValueError("Download jobs are available only on the local stdio MCP")
        return download_manager.get(arguments["download_id"])
    if name == "cancel_download":
        if not allow_download_execution:
            raise ValueError("Download jobs are available only on the local stdio MCP")
        return download_manager.cancel(arguments["download_id"])
    raise ValueError(f"Unknown tool: {name}")


def explain_schema(field: str, resource_type: str) -> dict[str, Any]:
    field_text = field.strip()
    examples = [item for item in catalog.load() if not resource_type or item["type"] == resource_type][:8]
    observed = sorted({key for item in examples for key in item.get("source", {}).keys()})
    return {
        "field": field_text or None,
        "resource_type": resource_type or None,
        "observed_fields": observed,
        "summary": "OpenConstruction metadata fields describe resource identity, provenance, task fit, access, licensing, and links back to source material.",
        "matching_examples": [item for item in examples if not field_text or field_text in item.get("source", {})][:5],
    }


def analyze_catalog_gaps(topic: str, limit: int) -> dict[str, Any]:
    matches = catalog.search(topic or "construction", limit=limit)
    stats = catalog.stats()
    sparse = [resource_type for resource_type, count in stats["by_type"].items() if count < 5]
    return {
        "topic": topic,
        "matching_resources": matches,
        "counts_by_type": stats["by_type"],
        "possible_gaps": sparse,
        "notes": [
            "Review records with missing license, year, source URL, or task fields.",
            "Compare coverage across datasets, models, workflows, and benchmarks for the topic.",
        ],
    }


def prepare_benchmark_submission(arguments: dict[str, Any]) -> dict[str, Any]:
    dataset = catalog.get("dataset", arguments.get("dataset_id", "")) if arguments.get("dataset_id") else None
    model = catalog.get("model", arguments.get("model_id", "")) if arguments.get("model_id") else None
    return {
        "task": arguments.get("task"),
        "metric": arguments.get("metric"),
        "linked_dataset": dataset,
        "linked_model": model,
        "checklist": [
            "Define task and evaluation split",
            "Identify dataset and model records",
            "List metrics and reporting units",
            "Add source paper or repository links",
            "Include license and citation fields",
            "Document validation notes",
        ],
    }


def validate_metadata_record(record: dict[str, Any], resource_type: str) -> dict[str, Any]:
    required_by_type = {
        "dataset": ["name", "year", "license"],
        "model": ["title", "authors", "year"],
        "workflow": ["title", "summary"],
        "oer": ["title", "provider", "license"],
        "tool": ["name", "url", "summary"],
    }
    required = required_by_type.get(resource_type, ["title"])
    missing = [field for field in required if not record.get(field)]
    recommended = [field for field in ("summary", "url", "doi", "tasks", "modalities", "license") if not record.get(field)]
    return {
        "resource_type": resource_type,
        "valid": not missing,
        "missing_required": missing,
        "missing_recommended": recommended,
    }


def handle_request(message: dict[str, Any], allow_download_execution: bool = True) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if request_id is None:
        return None

    try:
        if method == "initialize":
            return response(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": (
                        "Use OpenConstruction to discover and understand public AEC datasets and related resources. "
                        "Call get_dataset_download_plan before download_dataset. If a download returns auth_required, "
                        "show the returned local provider-login instructions, never ask for credentials in chat, "
                        "wait for the user to authenticate locally, and then use the returned retry payload."
                    ),
                },
            )
        if method == "server/discover":
            return response(
                request_id,
                {
                    "protocolVersion": "2026-07-28",
                    "supportedVersions": ["2026-07-28", "2025-06-18", "2025-03-26"],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "ping":
            return response(request_id, {})
        if method == "tools/list":
            tools = TOOLS if allow_download_execution else [tool for tool in TOOLS if tool["name"] not in LOCAL_ONLY_TOOLS]
            return response(request_id, {"tools": tools})
        if method == "tools/call":
            params = message.get("params") or {}
            result = call_tool(params.get("name", ""), params.get("arguments") or {}, allow_download_execution)
            return response(request_id, text_content(result))
        return error(request_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        return error(request_id, -32000, str(exc))


def response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(input_stream: Any = sys.stdin, output_stream: Any = sys.stdout) -> None:
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            result = handle_request(message)
        except Exception as exc:
            result = error(None, -32700, f"Parse error: {exc}")
        if result is not None:
            output_stream.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_stream.flush()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
