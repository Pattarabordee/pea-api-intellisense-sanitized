from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import urlparse
import zipfile

import yaml

from .ais_inbound import API_VERSION, DEFAULT_INBOUND_PATH, SCHEMA_VERSION


DEFAULT_PUBLIC_BASE = "https://ais-etr-pea-pilot.loca.lt"
DEFAULT_AIS_FACING_DOCS = (
    "ais_inbound_api_contract_v1.md",
    "ais_inbound_api_contract_draft.md",
    "ais_inbound_api_handoff.md",
    "ais_inbound_quick_reply_to_ais.txt",
    "ais_inbound_pilot_readiness_note.md",
    "ais_inbound_openapi.json",
    "ais_inbound_openapi.yaml",
    "ais_inbound_postman_collection.json",
)
DEFAULT_AIS_SECURITY_AUDIT_PATHS = (
    "ais_inbound_api_contract_v1.md",
    "ais_inbound_api_contract_draft.md",
    "ais_inbound_api_handoff.md",
    "ais_inbound_quick_reply_to_ais.txt",
    "ais_inbound_pilot_readiness_note.md",
    "ais_inbound_openapi.json",
    "ais_inbound_openapi.yaml",
    "ais_inbound_postman_collection.json",
    "ais_inbound_test_kit/README.md",
    "ais_inbound_test_kit/current_endpoint.txt",
    "ais_inbound_test_kit/curl_examples.md",
    "ais_inbound_test_kit/powershell_examples.ps1",
    "ais_inbound_test_kit/sample_minimal_request.json",
    "ais_inbound_test_kit/sample_full_request.json",
    "ais_inbound_test_kit/manifest.json",
    "ais_inbound_test_kit.zip",
    "ais_inbound_readiness_gate.md",
    "ais_inbound_public_endpoint_readiness.md",
    "ais_inbound_db_snapshot_latest.md",
    "ais_inbound_db_snapshot_latest.json",
    "ais_inbound_doc_qa.md",
    "ais_inbound_production_migration_checklist.md",
    "ais_inbound_production_operations_runbook.md",
    "ais_inbound_production_env.example",
    "ais_inbound_production_migration_manifest.json",
)
DEFAULT_AIS_PRODUCTION_PACK_FILES = (
    "ais_inbound_production_migration_checklist.md",
    "ais_inbound_production_operations_runbook.md",
    "ais_inbound_production_env.example",
    "ais_inbound_production_migration_manifest.json",
)
THAI_TEXT_RE = re.compile(r"[\u0E00-\u0E7F]")
URL_RE = re.compile(r"https?://[^\s)\"\]]+")
SECRETISH_RE = re.compile(
    r"(webex_oauth_token|refresh_token|access_token|client_secret|room_id|WEBEX_|"
    r"sk-[A-Za-z0-9]|Bearer\s+[A-Za-z0-9_.-]{12,})",
    re.IGNORECASE,
)
LONG_DIGIT_RE = re.compile(r"\b\d{10,}\b")


def build_ais_inbound_openapi(public_base: str = DEFAULT_PUBLIC_BASE) -> dict[str, Any]:
    base = public_base.rstrip("/")
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "PEA AIS Outage Verification API",
            "version": SCHEMA_VERSION,
            "description": (
                "Pilot shadow API for AIS to ask whether an AIS meter outage is supported by "
                "PEA distribution-system evidence. Production customer ETR sending is blocked."
            ),
        },
        "servers": [{"url": base, "description": "Pilot public tunnel"}],
        "security": [{"ApiKeyAuth": []}],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "Endpoint is running in shadow mode",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"}
                                }
                            },
                        }
                    },
                }
            },
            DEFAULT_INBOUND_PATH: {
                "get": {
                    "summary": "Readiness metadata for the verification endpoint",
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "Endpoint metadata",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReadyResponse"}
                                }
                            },
                        }
                    },
                },
                "post": {
                    "summary": "Create an AIS outage verification request",
                    "description": (
                        "Accepts one AIS outage alarm/event. The API stores the request, checks "
                        "current WebEx/topology evidence, and returns 202 immediately. Result details "
                        "can be read from the status lookup endpoint by request_id."
                    ),
                    "parameters": [
                        {
                            "name": "bypass-tunnel-reminder",
                            "in": "header",
                            "required": False,
                            "schema": {"type": "string", "example": "true"},
                            "description": "Pilot-only localtunnel bypass header.",
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/AisOutageVerificationRequest"},
                                "examples": {
                                    "minimal": {
                                        "summary": "Minimal request",
                                        "value": _minimal_request_example(),
                                    },
                                    "withAlarmContext": {
                                        "summary": "Request with AIS alarm context",
                                        "value": _full_request_example(),
                                    },
                                },
                            }
                        },
                    },
                    "responses": {
                        "202": {
                            "description": "Request accepted for shadow verification",
                            "headers": {
                                "X-Request-ID": {
                                    "schema": {"type": "string"},
                                    "description": "Echoes request_id for tracing.",
                                }
                            },
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AcceptedResponse"},
                                    "examples": {
                                        "accepted": {
                                            "value": {
                                                "api_version": API_VERSION,
                                                "schema_version": SCHEMA_VERSION,
                                                "mode": "shadow",
                                                "status": "RECEIVED",
                                                "http_status": 202,
                                                "request_id": "AIS-TEST-0001",
                                                "duplicate": False,
                                                "callback_status": "CAPTURED_NO_CALLBACK_URL",
                                                "result_path": f"{DEFAULT_INBOUND_PATH}/AIS-TEST-0001",
                                                "production_send": "blocked",
                                                "received_at": "2026-06-20T01:00:00+00:00",
                                            }
                                        }
                                    },
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"},
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                        "413": {"$ref": "#/components/responses/PayloadTooLarge"},
                        "415": {"$ref": "#/components/responses/UnsupportedMediaType"},
                        "429": {"$ref": "#/components/responses/RateLimited"},
                    },
                },
                "options": {
                    "summary": "CORS preflight",
                    "security": [],
                    "responses": {"204": {"description": "Allowed methods and headers"}},
                },
            },
            f"{DEFAULT_INBOUND_PATH}/{{request_id}}": {
                "get": {
                    "summary": "Get verification result by request_id",
                    "description": "Returns the latest stored shadow verification result for a prior request.",
                    "parameters": [
                        {
                            "name": "request_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "bypass-tunnel-reminder",
                            "in": "header",
                            "required": False,
                            "schema": {"type": "string", "example": "true"},
                            "description": "Pilot-only localtunnel bypass header.",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Stored verification result",
                            "headers": {
                                "X-Request-ID": {
                                    "schema": {"type": "string"},
                                    "description": "Echoes request_id for tracing.",
                                }
                            },
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/VerificationStatusResponse"}
                                }
                            },
                        },
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                        "404": {"$ref": "#/components/responses/NotFound"},
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "Shared pilot key provided privately by PEA.",
                }
            },
            "responses": {
                "BadRequest": {
                    "description": "Invalid request",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
                "Unauthorized": {
                    "description": "Missing or invalid pilot API key",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
                "NotFound": {
                    "description": "Request or endpoint not found",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
                "PayloadTooLarge": {
                    "description": "Request body exceeds pilot limit",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
                "UnsupportedMediaType": {
                    "description": "Content-Type must be application/json",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
                "RateLimited": {
                    "description": "Too many requests for the pilot endpoint",
                    "headers": {
                        "Retry-After": {
                            "schema": {"type": "integer"},
                            "description": "Seconds to wait before retrying.",
                        }
                    },
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                },
            },
            "schemas": _schemas(),
        },
        "x-pea-pilot-guardrails": {
            "mode": "shadow",
            "production_send": "blocked",
            "customer_etr_auto_send": "blocked_until_green_gate_passes",
            "truth_source": "AIS outage/restore timestamps only for customer-facing evaluation",
            "webex_usage": "trigger and device evidence, not restoration truth",
        },
    }


def write_ais_inbound_contract_pack(
    output_dir: str | Path = "runtime",
    *,
    public_base: str = DEFAULT_PUBLIC_BASE,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    openapi = build_ais_inbound_openapi(public_base)

    json_path = output / "ais_inbound_openapi.json"
    yaml_path = output / "ais_inbound_openapi.yaml"
    md_path = output / "ais_inbound_api_contract_v1.md"
    draft_md_path = output / "ais_inbound_api_contract_draft.md"
    handoff_path = output / "ais_inbound_api_handoff.md"
    quick_reply_path = output / "ais_inbound_quick_reply_to_ais.txt"
    pilot_note_path = output / "ais_inbound_pilot_readiness_note.md"
    postman_path = output / "ais_inbound_postman_collection.json"
    request_path = output / "ais_inbound_demo_request.json"

    json_path.write_text(json.dumps(openapi, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")
    yaml_path.write_text(yaml.safe_dump(openapi, allow_unicode=True, sort_keys=False), encoding="utf-8")
    markdown = _contract_markdown(public_base)
    md_path.write_text(markdown, encoding="utf-8")
    draft_md_path.write_text(markdown, encoding="utf-8")
    handoff_path.write_text(_handoff_markdown(public_base), encoding="utf-8")
    quick_reply_path.write_text(_quick_reply(public_base), encoding="utf-8")
    pilot_note_path.write_text(_pilot_readiness_note(public_base), encoding="utf-8")
    postman_path.write_text(
        json.dumps(_postman_collection(public_base), ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    request_path.write_text(json.dumps(_full_request_example(), ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "openapi_json": str(json_path),
        "openapi_yaml": str(yaml_path),
        "contract_markdown": str(md_path),
        "contract_draft_markdown": str(draft_md_path),
        "handoff_markdown": str(handoff_path),
        "quick_reply": str(quick_reply_path),
        "pilot_readiness_note": str(pilot_note_path),
        "postman_collection": str(postman_path),
        "demo_request": str(request_path),
    }


def write_ais_inbound_test_kit(
    output_dir: str | Path = "runtime/ais_inbound_test_kit",
    *,
    public_base: str = DEFAULT_PUBLIC_BASE,
    source_dir: str | Path = "runtime",
    zip_output: str | Path | None = "runtime/ais_inbound_test_kit.zip",
) -> dict[str, Any]:
    """Create an AIS-shareable pilot test kit without embedding the private API key."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(source_dir)
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/{{request_id}}"

    files: dict[str, Path] = {
        "readme": output / "README.md",
        "endpoint": output / "current_endpoint.txt",
        "minimal_request": output / "sample_minimal_request.json",
        "full_request": output / "sample_full_request.json",
        "curl_examples": output / "curl_examples.md",
        "powershell_examples": output / "powershell_examples.ps1",
        "manifest": output / "manifest.json",
    }
    files["readme"].write_text(_test_kit_readme(base), encoding="utf-8")
    files["endpoint"].write_text(
        "\n".join(
            [
                f"POST {post_url}",
                f"GET  {health_url}",
                f"GET  {status_url}",
                "",
                "Headers:",
                "Content-Type: application/json",
                "X-API-Key: <private pilot key provided by PEA>",
                "bypass-tunnel-reminder: true",
                "",
                "Mode: shadow",
                "Production send: blocked",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files["minimal_request"].write_text(
        json.dumps(_minimal_request_example(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files["full_request"].write_text(
        json.dumps(_full_request_example(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files["curl_examples"].write_text(_curl_examples(base), encoding="utf-8")
    files["powershell_examples"].write_text(_powershell_examples(base), encoding="utf-8")

    copied: dict[str, str] = {}
    for name in (
        "ais_inbound_openapi.json",
        "ais_inbound_openapi.yaml",
        "ais_inbound_postman_collection.json",
        "ais_inbound_api_contract_v1.md",
    ):
        src = source / name
        if src.exists():
            dst = output / name
            shutil.copyfile(src, dst)
            copied[name] = str(dst)

    manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "production_send": "blocked",
        "public_base": base,
        "post_url": post_url,
        "health_url": health_url,
        "status_url_template": status_url,
        "contains_private_api_key": False,
        "files": {key: str(path) for key, path in files.items()},
        "copied_contract_files": copied,
    }
    files["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    zip_path: Path | None = Path(zip_output) if zip_output else None
    if zip_path:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = zip_path.with_name(zip_path.name + ".tmp")
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output.iterdir()):
                if path.is_file():
                    archive.write(path, arcname=path.name)
        tmp_path.replace(zip_path)
        manifest["zip_output"] = str(zip_path)
    return manifest


def write_ais_inbound_production_migration_pack(
    output_dir: str | Path = "runtime",
    *,
    public_base: str = DEFAULT_PUBLIC_BASE,
) -> dict[str, Any]:
    """Write production migration docs for the AIS inbound API without approving production send."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = public_base.rstrip("/")
    files = {
        "checklist": output / "ais_inbound_production_migration_checklist.md",
        "runbook": output / "ais_inbound_production_operations_runbook.md",
        "env_example": output / "ais_inbound_production_env.example",
        "manifest": output / "ais_inbound_production_migration_manifest.json",
    }
    files["checklist"].write_text(_production_migration_checklist(base), encoding="utf-8")
    files["runbook"].write_text(_production_operations_runbook(base), encoding="utf-8")
    files["env_example"].write_text(_production_env_example(base), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "production_send": "blocked",
        "current_pilot_base": base,
        "production_approval": "not_approved",
        "files": {key: str(path) for key, path in files.items()},
        "minimum_before_production": [
            "stable_https_endpoint",
            "approved_authentication",
            "secret_rotation",
            "monitoring_alerting",
            "durable_database_backup",
            "callback_retry_policy",
            "owner_approved_production_gate",
        ],
    }
    files["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def build_ais_inbound_doc_qa(
    docs_dir: str | Path = "runtime",
    *,
    public_base: str = DEFAULT_PUBLIC_BASE,
    output: str | Path = "runtime/ais_inbound_doc_qa.md",
) -> dict[str, Any]:
    """Check AIS-facing docs for stale URLs, Thai text, and obvious secret leakage."""
    docs_path = Path(docs_dir)
    current_host = urlparse(public_base.rstrip("/")).netloc
    files: list[dict[str, Any]] = []
    failures: list[str] = []

    for name in DEFAULT_AIS_FACING_DOCS:
        path = docs_path / name
        item: dict[str, Any] = {
            "file": str(path),
            "exists": path.exists(),
            "has_current_host": False,
            "thai_text": False,
            "stale_hosts": [],
            "secretish_lines": [],
        }
        if not path.exists():
            failures.append(f"{name}: missing")
            files.append(item)
            continue

        text = path.read_text(encoding="utf-8-sig", errors="replace")
        hosts = sorted({urlparse(url).netloc for url in URL_RE.findall(text)})
        stale_hosts = [
            host
            for host in hosts
            if host.endswith(".loca.lt") and host != current_host
        ]
        secretish_lines = _secretish_doc_lines(text)
        item.update(
            {
                "has_current_host": current_host in hosts,
                "thai_text": bool(THAI_TEXT_RE.search(text)),
                "stale_hosts": stale_hosts,
                "secretish_lines": secretish_lines,
                "line_count": len(text.splitlines()),
                "url_hosts": hosts,
            }
        )

        if current_host not in hosts:
            failures.append(f"{name}: current public host not found")
        if item["thai_text"]:
            failures.append(f"{name}: Thai text found")
        if stale_hosts:
            failures.append(f"{name}: stale tunnel host(s) {', '.join(stale_hosts)}")
        if secretish_lines:
            failures.append(f"{name}: possible secret-bearing line(s)")
        files.append(item)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "public_base": public_base.rstrip("/"),
        "current_host": current_host,
        "files_checked": len(files),
        "failures": failures,
        "files": files,
    }

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(_doc_qa_markdown(report), encoding="utf-8")
    tmp_path.replace(output_path)
    report["output"] = str(output_path)
    return report


def build_ais_inbound_security_audit(
    runtime_dir: str | Path = "runtime",
    *,
    private_key_file: str | Path = "runtime/private/ais_inbound_pilot_key.txt",
    output_markdown: str | Path = "runtime/ais_inbound_security_audit.md",
    output_json: str | Path = "runtime/ais_inbound_security_audit.json",
) -> dict[str, Any]:
    """Scan shareable AIS inbound artifacts for secret/privacy leakage."""
    root = Path(runtime_dir)
    private_key = _read_private_key(private_key_file)
    files: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []

    if not private_key:
        warnings.append("private pilot key file was not available for exact secret scanning")

    for relative in DEFAULT_AIS_SECURITY_AUDIT_PATHS:
        path = root / relative
        if not path.exists():
            warnings.append(f"{relative}: missing from audit scope")
            files.append(
                {
                    "file": str(path),
                    "exists": False,
                    "status": "WARN",
                    "entries_scanned": 0,
                    "issues": [{"severity": "WARN", "code": "missing"}],
                }
            )
            continue
        scanned = _scan_security_artifact(path, private_key=private_key)
        files.append(scanned)
        for issue in scanned["issues"]:
            if issue["severity"] == "FAIL":
                failures.append(f"{relative}: {issue['code']}")
            elif issue["severity"] == "WARN":
                warnings.append(f"{relative}: {issue['code']}")

    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "mode": "shadow",
        "production_send": "blocked",
        "runtime_dir": str(root),
        "private_key_exact_scan": "enabled" if private_key else "skipped_missing_key_file",
        "files_checked": len(files),
        "failures": failures,
        "warnings": warnings,
        "files": files,
    }

    markdown_path = Path(output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_tmp = markdown_path.with_name(markdown_path.name + ".tmp")
    markdown_tmp.write_text(_security_audit_markdown(report), encoding="utf-8")
    markdown_tmp.replace(markdown_path)

    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_name(json_path.name + ".tmp")
    json_tmp.write_text(json.dumps(_security_audit_public_json(report), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json_tmp.replace(json_path)

    report["output_markdown"] = str(markdown_path)
    report["output_json"] = str(json_path)
    return report


def _read_private_key(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _scan_security_artifact(path: Path, *, private_key: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    entries = _artifact_text_entries(path)
    for entry_name, text in entries:
        if private_key and private_key in text:
            issues.append({"severity": "FAIL", "code": "private_pilot_key_found", "entry": entry_name})
        secretish_lines = _secretish_doc_lines(text)
        for line in secretish_lines:
            issues.append(
                {
                    "severity": "FAIL",
                    "code": "possible_secretish_line",
                    "entry": entry_name,
                    "line": str(line.get("line", "")),
                }
            )
        if _raw_room_identifier_found(text):
            issues.append({"severity": "FAIL", "code": "possible_raw_webex_room_id", "entry": entry_name})
        if _raw_webex_body_found(text):
            issues.append({"severity": "WARN", "code": "possible_raw_webex_text", "entry": entry_name})
        for match in LONG_DIGIT_RE.findall(text):
            if _looks_like_public_timestamp_or_version(match):
                continue
            issues.append(
                {
                    "severity": "WARN",
                    "code": "long_digit_sequence_review",
                    "entry": entry_name,
                }
            )
            break
    status = "FAIL" if any(issue["severity"] == "FAIL" for issue in issues) else ("WARN" if issues else "PASS")
    return {
        "file": str(path),
        "exists": True,
        "status": status,
        "entries_scanned": len(entries),
        "issues": issues,
    }


def _artifact_text_entries(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() == ".zip":
        rows: list[tuple[str, str]] = []
        try:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir() or not _is_text_artifact_name(info.filename):
                        continue
                    data = archive.read(info.filename)
                    rows.append((info.filename, data.decode("utf-8-sig", errors="replace")))
        except zipfile.BadZipFile:
            return [(path.name, "BAD_ZIP_FILE")]
        return rows
    if not _is_text_artifact_name(path.name):
        return []
    return [(path.name, path.read_text(encoding="utf-8-sig", errors="replace"))]


def _is_text_artifact_name(name: str) -> bool:
    return Path(name).suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".ps1", ".csv"}


def _raw_room_identifier_found(text: str) -> bool:
    return bool(re.search(r"Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_-]{16,}", text))


def _raw_webex_body_found(text: str) -> bool:
    lowered = text.lower()
    return (
        '"raw_text"' in lowered
        or '"roomid"' in lowered
        or '"room_id"' in lowered
        or '"webex_message_id"' in lowered
    )


def _looks_like_public_timestamp_or_version(value: str) -> bool:
    if value.startswith(("202606", "202506", "202406")):
        return True
    if value in {SCHEMA_VERSION.replace("-", ""), API_VERSION.replace("v", "")}:
        return True
    return False


def _security_audit_public_json(report: dict[str, Any]) -> dict[str, Any]:
    safe_files = []
    for item in report["files"]:
        safe_files.append(
            {
                "file": item.get("file"),
                "exists": item.get("exists"),
                "status": item.get("status"),
                "entries_scanned": item.get("entries_scanned", 0),
                "issue_codes": sorted({issue.get("code", "") for issue in item.get("issues", [])}),
            }
        )
    return {
        "generated_at": report["generated_at"],
        "status": report["status"],
        "mode": report["mode"],
        "production_send": report["production_send"],
        "runtime_dir": report["runtime_dir"],
        "private_key_exact_scan": report["private_key_exact_scan"],
        "files_checked": report["files_checked"],
        "failures": report["failures"],
        "warnings": report["warnings"],
        "files": safe_files,
    }


def _secretish_doc_lines(text: str) -> list[dict[str, Any]]:
    allowed_markers = (
        "{{api_key}}",
        "<shared pilot key>",
        "<AIS_PILOT_API_KEY>",
        "X-API-Key",
        "webex_usage",
        "webex_messages",
        "WebEx",
        "Webex",
    )
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not SECRETISH_RE.search(line):
            continue
        if any(marker in line for marker in allowed_markers):
            continue
        rows.append({"line": line_number, "preview": line[:160]})
    return rows


def _doc_qa_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AIS Inbound API Document QA",
        "",
        f"- Status: `{report['status']}`",
        f"- Public base: `{report['public_base']}`",
        f"- Files checked: `{report['files_checked']}`",
        f"- Generated at: `{report['generated_at']}`",
        "",
        "## Checks",
        "",
        "| File | Exists | Current URL | Thai Text | Stale Tunnel | Possible Secret |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["files"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    Path(item["file"]).name,
                    _yes_no(item["exists"]),
                    _yes_no(item["has_current_host"]),
                    _yes_no(item["thai_text"]),
                    ", ".join(item["stale_hosts"]) if item["stale_hosts"] else "none",
                    str(len(item["secretish_lines"])),
                ]
            )
            + " |"
        )

    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
    else:
        lines.extend(
            [
                "",
                "## Result",
                "",
                "The AIS-facing document pack passed this automated QA scan. Placeholder API keys are allowed; real keys are not written to these files.",
            ]
        )
    return "\n".join(lines) + "\n"


def _security_audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AIS Inbound Security And Privacy Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        f"- Files checked: `{report['files_checked']}`",
        f"- Private key exact scan: `{report['private_key_exact_scan']}`",
        f"- Generated at: `{report['generated_at']}`",
        "",
        "## Checks",
        "",
        "| File | Exists | Status | Entries | Issue codes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report["files"]:
        issue_codes = sorted({issue.get("code", "") for issue in item.get("issues", [])})
        lines.append(
            "| "
            + " | ".join(
                [
                    Path(item["file"]).name,
                    _yes_no(item["exists"]),
                    f"`{item['status']}`",
                    str(item.get("entries_scanned", 0)),
                    ", ".join(issue_codes) if issue_codes else "none",
                ]
            )
            + " |"
        )
    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"][:50])
        if len(report["warnings"]) > 50:
            lines.append(f"- ... {len(report['warnings']) - 50} more warnings")
    if not report["failures"]:
        lines.extend(
            [
                "",
                "## Result",
                "",
                "No private pilot key, obvious WebEx room id, obvious secret token, or raw customer identifier leak was found in the audited shareable artifacts.",
            ]
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This audit does not print any secret value.",
            "- Placeholder API key text is allowed.",
            "- `mode` remains `shadow` and `production_send` remains `blocked`.",
            "- A warning means an operator should review the artifact before sharing; a failure means do not share it.",
            "",
        ]
    )
    return "\n".join(lines)


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


def _schemas() -> dict[str, Any]:
    return {
        "HealthResponse": {
            "type": "object",
            "required": ["status", "mode", "production_send"],
            "properties": {
                "status": {"type": "string", "const": "OK"},
                "mode": {"type": "string", "const": "shadow"},
                "api_version": {"type": "string"},
                "service": {"type": "string"},
                "production_send": {"type": "string", "const": "blocked"},
                "inbound_path": {"type": "string"},
            },
        },
        "ReadyResponse": {
            "type": "object",
            "required": ["status", "mode", "method", "production_send"],
            "properties": {
                "status": {"type": "string", "const": "READY"},
                "mode": {"type": "string", "const": "shadow"},
                "api_version": {"type": "string"},
                "method": {"type": "string", "const": "POST"},
                "required_headers": {"type": "array", "items": {"type": "string"}},
                "status_lookup": {"type": "string"},
                "production_send": {"type": "string", "const": "blocked"},
            },
        },
        "AisOutageVerificationRequest": {
            "type": "object",
            "required": ["request_id", "meter_no", "timestamp"],
            "properties": {
                "request_id": {
                    "type": "string",
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9._:@-]*$",
                    "description": (
                        "Unique event/alarm id. Reuse for retries. Use letters, numbers, dash, "
                        "underscore, dot, colon, or at sign only."
                    ),
                },
                "meter_no": {
                    "type": "string",
                    "maxLength": 64,
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9._:@-]*$",
                    "description": "PEA meter number / PEANO. Do not include slash, space, or newline.",
                },
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "AIS detected outage time. Include +07:00 when possible.",
                },
                "province": {"type": "string"},
                "district": {"type": "string"},
                "subdistrict": {"type": "string"},
                "alarm_type": {"type": "string", "example": "AC_MAIN_FAIL"},
                "main_cause": {"type": "string", "example": "Faulty AC main failed"},
                "subcause": {"type": "string", "example": "PEA no back up"},
            },
            "additionalProperties": True,
        },
        "AcceptedResponse": {
            "type": "object",
            "required": ["mode", "status", "http_status", "request_id", "production_send"],
            "properties": {
                "api_version": {"type": "string"},
                "schema_version": {"type": "string"},
                "mode": {"type": "string", "const": "shadow"},
                "status": {"type": "string", "const": "RECEIVED"},
                "http_status": {"type": "integer", "const": 202},
                "request_id": {"type": "string"},
                "duplicate": {"type": "boolean"},
                "callback_status": {"type": "string"},
                "result_path": {"type": "string"},
                "production_send": {"type": "string", "const": "blocked"},
                "received_at": {"type": "string", "format": "date-time"},
            },
        },
        "VerificationStatusResponse": {
            "type": "object",
            "required": ["mode", "request_id", "status", "production_send"],
            "properties": {
                "api_version": {"type": "string"},
                "schema_version": {"type": "string"},
                "mode": {"type": "string", "const": "shadow"},
                "request_id": {"type": "string"},
                "status": {"type": "string", "enum": ["RECEIVED", "COMPLETED"]},
                "request_status": {"type": "string"},
                "callback_status": {"type": "string"},
                "production_send": {"type": "string", "const": "blocked"},
                "received_at": {"type": "string", "format": "date-time"},
                "detected_at": {"type": "string"},
                "detected_at_original": {"type": "string"},
                "timestamp_quality": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["OK", "REVIEW", "unknown"]},
                        "flags": {"type": "array", "items": {"type": "string"}},
                        "assumption": {"type": "string"},
                    },
                },
                "meter": {"type": "object"},
                "area": {"type": "object"},
                "result": {"type": ["object", "null"]},
                "last_callback": {"type": ["object", "null"]},
            },
        },
        "ErrorResponse": {
            "type": "object",
            "required": ["mode", "status", "error", "production_send"],
            "properties": {
                "api_version": {"type": "string"},
                "schema_version": {"type": "string"},
                "mode": {"type": "string", "const": "shadow"},
                "status": {"type": "string", "const": "ERROR"},
                "request_id": {"type": "string"},
                "error": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
                "production_send": {"type": "string", "const": "blocked"},
                "generated_at": {"type": "string", "format": "date-time"},
            },
        },
    }


def _minimal_request_example() -> dict[str, str]:
    return {
        "request_id": "AIS-TEST-0001",
        "meter_no": "<PEA meter number / PEANO>",
        "timestamp": "2026-06-20T00:35:00+07:00",
        "province": "Sakon Nakhon",
        "district": "<district>",
        "subdistrict": "<subdistrict>",
    }


def _full_request_example() -> dict[str, str]:
    payload = _minimal_request_example()
    payload.update(
        {
            "request_id": "AIS-20260620-0001",
            "alarm_type": "AC_MAIN_FAIL",
            "main_cause": "Faulty AC main failed",
            "subcause": "PEA no back up",
        }
    )
    return payload


def _postman_collection(public_base: str) -> dict[str, Any]:
    base = public_base.rstrip("/")
    parsed = urlparse(base)
    host = parsed.netloc.split(".")
    return {
        "info": {
            "name": "AIS -> PEA Outage Verification Pilot",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "base_url", "value": base},
            {"key": "api_key", "value": "<shared pilot key>"},
            {"key": "request_id", "value": "AIS-TEST-0001"},
        ],
        "item": [
            {
                "name": "Health Check",
                "request": {
                    "method": "GET",
                    "header": [{"key": "bypass-tunnel-reminder", "value": "true"}],
                    "url": {"raw": "{{base_url}}/health", "host": host, "path": ["health"]},
                },
            },
            {
                "name": "Create Outage Verification",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "X-API-Key", "value": "{{api_key}}"},
                        {"key": "bypass-tunnel-reminder", "value": "true"},
                    ],
                    "body": {"mode": "raw", "raw": json.dumps(_full_request_example(), ensure_ascii=False, indent=2)},
                    "url": {
                        "raw": "{{base_url}}/api/v1/ais/outage-verifications",
                        "host": host,
                        "path": ["api", "v1", "ais", "outage-verifications"],
                    },
                },
            },
            {
                "name": "Get Verification Result",
                "request": {
                    "method": "GET",
                    "header": [
                        {"key": "X-API-Key", "value": "{{api_key}}"},
                        {"key": "bypass-tunnel-reminder", "value": "true"},
                    ],
                    "url": {
                        "raw": "{{base_url}}/api/v1/ais/outage-verifications/{{request_id}}",
                        "host": host,
                        "path": ["api", "v1", "ais", "outage-verifications", "{{request_id}}"],
                    },
                },
            },
        ],
    }


def _contract_markdown(public_base: str) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/{{request_id}}"
    return f"""# PEA AIS Outage Verification API Contract v1

Generated: `{now}`

Status: **pilot / shadow mode**. This API accepts real AIS test requests, stores redacted evidence in the local pilot runtime, and lets AIS/PEA read the verification result by `request_id`. **Automatic production ETR sending is still blocked.**

## Endpoints

```http
GET  {health_url}
GET  {post_url}
POST {post_url}
GET  {status_url}
```

## Headers

```http
Content-Type: application/json
X-API-Key: <shared pilot key>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed during the localtunnel pilot. Do not share the real pilot key in group chat.

## Request Body

Required:

| Field | Meaning |
| --- | --- |
| `request_id` | Unique AIS alarm/event id. Reuse the same value when retrying the same event. Max 128 characters. Use letters, numbers, dash, underscore, dot, colon, or at sign only. |
| `meter_no` | PEA meter number / PEANO for the AIS site. Max 64 characters. Do not include slash, space, or newline. |
| `timestamp` | AIS detected outage time. Include timezone when possible, for example `+07:00`. |

Recommended:

| Field | Meaning |
| --- | --- |
| `province`, `district`, `subdistrict` | AIS site area. |
| `alarm_type` | For example `AC_MAIN_FAIL`. |
| `main_cause`, `subcause` | Used to separate PEA no-backup, PEA activity, and AIS equipment/backup cases. |

Example:

```json
{json.dumps(_full_request_example(), ensure_ascii=False, indent=2)}
```

## Immediate Response

When the request is valid and the pilot key passes, the API returns HTTP `202 Accepted`.

```json
{{
  "api_version": "{API_VERSION}",
  "schema_version": "{SCHEMA_VERSION}",
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260620-0001",
  "duplicate": false,
  "callback_status": "CAPTURED_NO_CALLBACK_URL",
  "result_path": "{DEFAULT_INBOUND_PATH}/AIS-20260620-0001",
  "production_send": "blocked",
  "received_at": "2026-06-20T01:00:00+00:00"
}}
```

## Result Lookup

AIS/PEA can read the stored verification result by `request_id`:

```http
GET {status_url}
```

The result indicates whether PEA evidence currently supports a distribution-side outage, the confidence level, the evidence lane used, and whether any ETR output is still `SHADOW_ONLY`.

The lookup also returns `timestamp_quality`. If AIS sends a timestamp without a timezone, the API treats it as Asia/Bangkok time and flags `timezone_assumed_bangkok`. Very old or future timestamps are accepted for audit, but flagged as `REVIEW` so operators do not silently compare bad timing evidence.

## Decision Status

| Status | Meaning |
| --- | --- |
| `CONFIRMED_PEA_OUTAGE` | Current WebEx/topology evidence supports a PEA distribution-side outage. |
| `UNCERTAIN_NEEDS_REVIEW` | More operator review is needed before confirming. |
| `NO_PEA_EVIDENCE_FOUND` | Current pilot runtime does not find supporting PEA evidence yet. |
| `PLANNED_OR_PEA_ACTIVITY` | AIS indicates this is PEA activity/planned context. |
| `LIKELY_AIS_EQUIPMENT_OR_BACKUP` | AIS subcause points to AIS equipment/backup context. |
| `DUPLICATE_REQUEST` | The same `request_id` was already received. |

## Error Responses

All error responses use the same envelope:

```json
{{
  "api_version": "{API_VERSION}",
  "schema_version": "{SCHEMA_VERSION}",
  "mode": "shadow",
  "status": "ERROR",
  "error": {{
    "code": "UNAUTHORIZED",
    "message": "X-API-Key or Authorization Bearer credential is required"
  }},
  "production_send": "blocked",
  "generated_at": "2026-06-20T01:00:00+00:00"
}}
```

Common HTTP status:

| HTTP | Meaning |
| --- | --- |
| `202` | Request accepted. |
| `400` | Invalid JSON, missing required field, or invalid timestamp. |
| `401` | Missing or invalid pilot key. |
| `404` | Path or `request_id` not found. |
| `413` | Request body exceeds the pilot limit. |
| `415` | `Content-Type` is not `application/json`. |
| `429` | Too many requests. Retry after the `Retry-After` header value. |

## Guardrails

- `mode` must remain `shadow`.
- `production_send` must remain `blocked`.
- Default pilot rate limit is `120` POST requests per minute per client.
- WebEx is used as trigger/device evidence, not restoration truth.
- AIS outage/restore timestamps remain the primary customer-facing truth source for ETR evaluation.
- Feeder-only matches are review/audit-only.
- Automatic customer ETR is blocked until the green subset passes the production gate.

## Files

- OpenAPI JSON: `runtime/ais_inbound_openapi.json`
- OpenAPI YAML: `runtime/ais_inbound_openapi.yaml`
- Postman collection: `runtime/ais_inbound_postman_collection.json`
- Demo request: `runtime/ais_inbound_demo_request.json`
"""


def _handoff_markdown(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/{{request_id}}"
    return f"""# AIS -> PEA Outage Verification API: Pilot Handoff

Current status: the endpoint is ready for AIS testing. It is still **shadow mode only** and does not send automatic production ETR.

## Test URLs

```text
POST {post_url}
GET  {health_url}
GET  {status_url}
```

Use `POST` to send one outage alarm/event. Use `GET .../{{request_id}}` to read the stored verification result for the same request.

## Headers

```http
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed for this localtunnel pilot to bypass the tunnel warning page.

## Minimal Body

```json
{json.dumps(_minimal_request_example(), ensure_ascii=False, indent=2)}
```

If AIS has alarm context, include it like this:

```json
{json.dumps(_full_request_example(), ensure_ascii=False, indent=2)}
```

## Expected Response

If the request is valid, the API returns HTTP `202` and `status = RECEIVED`.

```json
{{
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260620-0001",
  "duplicate": false,
  "result_path": "{DEFAULT_INBOUND_PATH}/AIS-20260620-0001",
  "production_send": "blocked"
}}
```

Then read the result from:

```http
GET {post_url}/AIS-20260620-0001
```

## If There Is an Error

| Error | Meaning |
| --- | --- |
| `401` | The endpoint is reachable, but `X-API-Key` is missing or invalid. |
| `400` | Invalid JSON, missing required field, or invalid timestamp format. |
| `404` | The path or `request_id` was not found. |
| `415` | `Content-Type: application/json` is missing or wrong. |
| `429` | Too many pilot test requests. Retry after the `Retry-After` header value. |
| timeout | The tunnel or PEA pilot machine may be down. Ask PEA to check the endpoint. |

## Pilot Scope

- The API accepts requests and stores redacted runtime logs.
- The API supports status lookup by `request_id`.
- The pilot rate limit is 120 POST requests per minute per client.
- Any ETR output is still `SHADOW_ONLY`.
- `production_send` must remain `blocked`.
- Do not share the real pilot key in group chat.
"""


def _quick_reply(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    return f"""Please send the test request to this URL:

POST {post_url}

Headers:
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true

Minimal body:
{{
  "request_id": "AIS-TEST-0001",
  "meter_no": "<PEA meter number or PEANO>",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>"
}}

If the request is valid, the API returns HTTP 202 and status = RECEIVED.
To read the stored result, call:

GET {post_url}/AIS-TEST-0001

If you receive 401, the endpoint is reachable but the X-API-Key did not pass.
This pilot is still shadow mode and production_send is still blocked.
"""


def _test_kit_readme(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/{{request_id}}"
    return f"""# PEA AIS Outage Verification API Pilot Test Kit

This package is for AIS pilot connectivity testing.

The endpoint is ready for pilot API testing, but it is still **shadow mode only**.
Automatic production ETR sending is blocked.

## URLs

```text
POST {post_url}
GET  {health_url}
GET  {status_url}
```

## Required Headers

```http
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed for this localtunnel pilot.

## Files In This Kit

| File | Purpose |
| --- | --- |
| `current_endpoint.txt` | Current pilot URL and required headers. |
| `sample_minimal_request.json` | Smallest valid request body. |
| `sample_full_request.json` | Recommended request body with alarm context. |
| `curl_examples.md` | cURL commands for health, POST, and status lookup. |
| `powershell_examples.ps1` | PowerShell commands for Windows testing. |
| `ais_inbound_openapi.json` | OpenAPI contract, if copied from the runtime contract pack. |
| `ais_inbound_openapi.yaml` | OpenAPI YAML contract, if copied from the runtime contract pack. |
| `ais_inbound_postman_collection.json` | Postman collection, if copied from the runtime contract pack. |
| `manifest.json` | Machine-readable package manifest. |

## Expected Flow

1. Call `GET /health`.
2. Send one `POST` request with a unique `request_id`.
3. PEA confirms the request was stored.
4. Call `GET /api/v1/ais/outage-verifications/{{request_id}}`.
5. Review the response fields with PEA before sending a batch.

## Important Response Rules

- HTTP `202` means PEA received and stored the request.
- `status = RECEIVED` means the request passed validation.
- `production_send = blocked` must remain present.
- `mode = shadow` must remain present.
- The API may return `NO_PEA_EVIDENCE_FOUND` if current WebEx/topology evidence is not available for that meter/time.
- Any ETR field is for shadow evaluation only.

## Common Errors

| HTTP | Meaning |
| --- | --- |
| `400` | Invalid JSON, missing field, bad timestamp, or invalid identifier. |
| `401` | Endpoint is reachable, but the pilot API key is missing or invalid. |
| `404` | Path or request_id was not found. |
| `413` | Request body is too large. |
| `415` | `Content-Type: application/json` is missing or wrong. |
| `429` | Too many pilot requests. Retry after the `Retry-After` header. |

## Security Notes

- This package does not contain the private pilot API key.
- Do not send the private key in group chat.
- Full meter numbers are not written into public reports; the API stores hash and last4 for audit.
- This local tunnel is acceptable for pilot connectivity testing, not final production hosting.
"""


def _curl_examples(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/AIS-TEST-0001"
    payload = json.dumps(_minimal_request_example(), ensure_ascii=False, indent=2)
    return f"""# cURL Examples

Replace `<private pilot key provided by PEA>` with the private key shared outside this package.

## Health Check

```bash
curl -i \\
  -H "bypass-tunnel-reminder: true" \\
  "{health_url}"
```

## Send One Test Request

```bash
curl -i -X POST \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: <private pilot key provided by PEA>" \\
  -H "bypass-tunnel-reminder: true" \\
  --data '{payload}' \\
  "{post_url}"
```

Expected result: HTTP `202` with `status = RECEIVED`.

## Read Stored Result

```bash
curl -i \\
  -H "X-API-Key: <private pilot key provided by PEA>" \\
  -H "bypass-tunnel-reminder: true" \\
  "{status_url}"
```

## Authentication Check

If this returns HTTP `401`, the endpoint is reachable and authentication is being enforced.

```bash
curl -i -X POST \\
  -H "Content-Type: application/json" \\
  -H "bypass-tunnel-reminder: true" \\
  --data '{{"request_id":"AIS-AUTH-CHECK","meter_no":"TEST","timestamp":"2026-06-20T00:35:00+07:00"}}' \\
  "{post_url}"
```
"""


def _powershell_examples(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/AIS-TEST-0001"
    payload = json.dumps(_minimal_request_example(), ensure_ascii=False, indent=2)
    escaped_payload = payload.replace("'", "''")
    return f"""# PEA AIS pilot API test script for Windows PowerShell.
# Fill in the private pilot key before running.

$ApiKey = "<private pilot key provided by PEA>"
$HealthUrl = "{health_url}"
$PostUrl = "{post_url}"
$StatusUrl = "{status_url}"

$Headers = @{{
    "X-API-Key" = $ApiKey
    "bypass-tunnel-reminder" = "true"
}}

Write-Host "Health check"
Invoke-RestMethod -Method Get -Uri $HealthUrl -Headers @{{ "bypass-tunnel-reminder" = "true" }}

$Body = @'
{escaped_payload}
'@

Write-Host "Send one pilot request"
Invoke-RestMethod -Method Post -Uri $PostUrl -Headers $Headers -ContentType "application/json" -Body $Body

Write-Host "Read stored result"
Invoke-RestMethod -Method Get -Uri $StatusUrl -Headers $Headers
"""


def _production_migration_checklist(public_base: str) -> str:
    base = public_base.rstrip("/")
    return f"""# AIS Inbound API Production Migration Checklist

Current pilot base URL: `{base}`

This document is a migration checklist only. It does not approve production sending.

## Current Pilot State

- API version: `{API_VERSION}`
- Schema version: `{SCHEMA_VERSION}`
- Current mode: `shadow`
- Current production_send: `blocked`
- Current hosting: local pilot tunnel
- Current authentication: shared pilot API key
- Current storage: local SQLite runtime evidence

## Production Entry Criteria

Production must remain blocked until every item below has an owner and an evidence link.

| Area | Required Control | Evidence Needed | Status |
| --- | --- | --- | --- |
| Endpoint | Stable HTTPS domain or API gateway URL | Production URL and DNS/TLS owner | `pending` |
| Network | AIS and PEA agree on connectivity path | Allowlist, VPN, private link, or gateway policy | `pending` |
| Authentication | Replace or harden shared pilot key | mTLS, signed requests, OAuth client credentials, or API gateway key with rotation | `pending` |
| Secret management | Store secrets outside source/runtime reports | Secret manager path and rotation procedure | `pending` |
| Database | Durable store and backup policy | Backup/restore test evidence | `pending` |
| Observability | Health, error, latency, and request-volume monitoring | Dashboard and alert policy | `pending` |
| Replay/retry | Callback retry and idempotency policy | Retry schedule, dead-letter review, replay command | `pending` |
| Data privacy | Public docs and reports pass leakage scan | Security audit report with `PASS` | `pending` |
| Model/ETR | Customer-facing ETR gate approved | Green subset gate and owner approval | `pending` |
| Operations | Runbook and on-call owner assigned | Contact path and escalation rule | `pending` |

## Production Blockers Today

- No real AIS request has reached the pilot endpoint yet, unless the latest readiness gate says otherwise.
- The endpoint still runs through a local pilot tunnel.
- Automatic production ETR sending is not approved.
- Final authentication and secret rotation are not approved.
- Final monitoring and SLA are not approved.

## Recommended Promotion Path

1. Complete one real AIS pilot request and verify the stored status lookup.
2. Run the security audit and confirm `PASS`.
3. Move the endpoint behind a stable HTTPS gateway.
4. Configure production-grade authentication and secret rotation.
5. Configure durable database backup and restore.
6. Configure monitoring and alerting.
7. Run a shadow soak period with AIS real requests.
8. Approve only status-only or green-lane responses first.
9. Keep p50 ETR production blocked until the model gate is approved.
"""


def _production_operations_runbook(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    return f"""# AIS Inbound API Production Operations Runbook

This runbook describes how to operate the AIS inbound outage verification API during pilot-to-production migration.

## Service Contract

- Request endpoint: `POST {post_url}`
- Status lookup: `GET {post_url}/{{request_id}}`
- Health check: `GET {base}/health`
- Accepted request HTTP status: `202`
- Auth failure HTTP status: `401`
- Rate limit HTTP status: `429`
- Mode during pilot: `shadow`
- Production send during pilot: `blocked`

## Operator Checks

Run these checks after every endpoint restart or URL change:

```powershell
python -m ais_etr ais-inbound-status
python -m ais_etr ais-inbound-readiness-gate
python -m ais_etr ais-inbound-security-audit
```

Expected pilot result:

- readiness gate has no `FAIL` checks
- security audit status is `PASS`
- `mode = shadow`
- `production_send = blocked`

## First Real AIS Request Procedure

1. Ask AIS to send exactly one request with a unique `request_id`.
2. Run `python -m ais_etr ais-inbound-first-hit-packet`.
3. Check `real_requests > 0`.
4. Confirm the latest real request has no raw meter exposure in reports.
5. Send AIS the status lookup result summary, not internal runtime secrets.
6. Keep production send blocked.

## Incident Response

| Symptom | Likely Cause | Operator Action |
| --- | --- | --- |
| `GET /health` fails | Endpoint or tunnel down | Restart endpoint and rerun readiness gate. |
| AIS receives `401` | Missing/wrong API key | Confirm key out-of-band, never in group chat. |
| AIS receives `400` | Invalid body or timestamp | Ask AIS to share request_id and sanitized payload shape. |
| AIS receives `415` | Wrong content type | Ask AIS to send `Content-Type: application/json`. |
| AIS receives `429` | Too many pilot requests | Follow `Retry-After` header. |
| status lookup returns no match | request_id not stored | Check inbound status report and request log. |

## Data Handling Rules

- Store full inbound requests only through the API pipeline.
- Public reports must show meter hash/last4 only.
- Do not export verbatim WebEx text, room id, token, callback secret, or full meter lists.
- AIS outage/restore remains the customer-facing truth source.
- WebEx remains trigger/device evidence, not restoration truth.
- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.

## Production Cutover Rule

Production cutover requires explicit owner approval. A passing local readiness gate is not enough.

Before production cutover, the production environment must prove:

- stable HTTPS endpoint
- approved authentication
- secret rotation
- monitoring and alerting
- durable database backup
- callback retry and replay
- privacy/security audit PASS
- production response policy approved by PEA and AIS
"""


def _production_env_example(public_base: str) -> str:
    base = public_base.rstrip("/")
    return f"""# AIS inbound API production environment skeleton.
# Do not put real secrets in this file.

AIS_INBOUND_MODE=shadow
AIS_PRODUCTION_SEND=blocked
AIS_INBOUND_PUBLIC_BASE=https://api.example.pea.local
AIS_INBOUND_PILOT_BASE={base}
AIS_INBOUND_PATH={DEFAULT_INBOUND_PATH}

# Replace the pilot shared key with an approved production auth method.
AIS_AUTH_METHOD=mtls_or_signed_request_or_api_gateway_key
AIS_API_KEY_SECRET_REF=<secret-manager-reference>
AIS_SECRET_ROTATION_DAYS=90

# Durable runtime state.
AIS_RUNTIME_DB=sqlite_or_managed_database_connection
AIS_RUNTIME_DB_BACKUP_POLICY=daily_backup_with_restore_test

# Callback handling.
AIS_CALLBACK_MODE=shadow_until_approved
AIS_CALLBACK_RETRY_SCHEDULE_SECONDS=10,30,120,300
AIS_CALLBACK_DEAD_LETTER_REVIEW=required

# Monitoring.
AIS_HEALTHCHECK_PATH=/health
AIS_ALERT_ON_HEALTH_FAIL=true
AIS_ALERT_ON_5XX_RATE=true
AIS_ALERT_ON_CALLBACK_FAILURE=true
AIS_ALERT_ON_RATE_LIMIT_SPIKE=true

# Guardrails.
AIS_ALLOW_P50_ETR_PRODUCTION=false
AIS_REQUIRE_GREEN_GATE=true
AIS_REQUIRE_OWNER_APPROVAL=true
AIS_BLOCK_PEA_CONTEXT_AS_TRUTH=true
"""


def _pilot_readiness_note(public_base: str) -> str:
    base = public_base.rstrip("/")
    post_url = f"{base}{DEFAULT_INBOUND_PATH}"
    health_url = f"{base}/health"
    status_url = f"{post_url}/{{request_id}}"
    return f"""# AIS Inbound API Pilot Readiness Note

Generated from the current endpoint status.

## Current Decision

AIS can start pilot API testing now.

This means AIS may send real test requests to the current pilot URL and PEA will store the request, run shadow verification, and return/query a result by `request_id`.

This does not mean production ETR sending is approved. The API still returns `mode = shadow` and `production_send = blocked`.

## Current Pilot Endpoint

```text
POST {post_url}
GET  {health_url}
GET  {status_url}
```

Required headers:

```http
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true
```

## Is Local Hosting Normal At This Stage?

Yes, local hosting is acceptable for this phase if the goal is connectivity testing, payload validation, shadow evidence capture, and API contract alignment.

Local hosting is not acceptable as the final production architecture.

For the pilot, local hosting is reasonable because:

- The API is still shadow mode.
- Production customer ETR sending is blocked.
- AIS is testing the request/response contract, not relying on this endpoint for live customer operation.
- Requests are persisted in local SQLite and redacted runtime reports.
- The endpoint has live smoke checks for health, authentication, idempotency, status lookup, and controlled error handling.

Main local-hosting risks:

- The public tunnel URL may change after restart.
- The machine must stay awake and connected.
- Localtunnel availability is not an SLA-backed production service.
- Shared pilot keys are acceptable only for pilot testing, not final production security.

## What Is Verified Now

- Health endpoint returns HTTP `200`.
- Authorized POST returns HTTP `202`.
- Unauthorized POST returns HTTP `401`.
- Invalid JSON returns controlled HTTP `400`.
- Wrong or missing `Content-Type` returns HTTP `415`.
- Invalid `request_id` or `meter_no` format returns controlled HTTP `400`.
- Burst traffic over the pilot limit returns controlled HTTP `429` with `Retry-After`.
- Request status lookup works by `request_id`.
- Duplicate `request_id` is not reprocessed as a new event.
- Stored reports redact meter numbers to hash and last4.
- Callback/status result uses `meter_ref` instead of returning the raw meter number.
- `production_send` remains `blocked`.

## What AIS Should Send For The First Test

Ask AIS to send one request first, then wait for PEA confirmation before sending a batch.

Minimal body:

```json
{json.dumps(_minimal_request_example(), ensure_ascii=False, indent=2)}
```

Recommended body:

```json
{json.dumps(_full_request_example(), ensure_ascii=False, indent=2)}
```

## How PEA Confirms A Real AIS Hit

Run:

```powershell
python -m ais_etr ais-inbound-status
```

Interpretation:

- `real_requests = 0`: no real AIS request has reached the endpoint yet.
- `real_requests > 0`: AIS reached the endpoint. Check the latest real `request_id`, callback status, verification decision, and confidence.

## Production Migration Requirements

Before production use, replace the local tunnel with a stable PEA/AIS-approved endpoint.

Minimum production items:

- Stable HTTPS endpoint with a fixed domain.
- Network allowlist or mutually agreed secure connectivity.
- Stronger authentication than a shared pilot key, such as mTLS, signed requests, OAuth client credentials, or an API gateway key with rotation.
- Central secret management.
- Structured request logs and monitoring.
- Alerting for endpoint down, high error rate, and callback failures.
- Backup/retry policy agreed with AIS.
- Explicit approval to move any ETR field from `shadow` to production.

## Recommended Test Sequence

1. AIS calls `GET /health`.
2. AIS sends one authorized `POST`.
3. PEA confirms `real_requests > 0` from the status report.
4. AIS calls `GET /api/v1/ais/outage-verifications/{{request_id}}`.
5. PEA and AIS review the response fields.
6. AIS sends a small batch only after the single request is confirmed.
"""
