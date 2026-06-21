from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import zipfile
from typing import Any


TEXT_EXTENSIONS = {
    ".cfg",
    ".dockerfile",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

EXCLUDED_DIR_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "chrome_profile",
    "chrome_profile_en",
    "logs",
    "private",
    "shareable_pea_pitch_pack",
    "snapshots",
}

EXCLUDED_RUNTIME_DIRS = {
    "browser_chatgpt_brave_profile",
    "browser_chatgpt_chrome_profile",
    "dev_export",
    "office_pc_handoff",
    "pc_command_bridge",
    "unattended_pc_bridge",
    "webex_command_bridge",
}

EXCLUDED_SUFFIXES = {
    ".7z",
    ".db",
    ".gz",
    ".jpeg",
    ".jpg",
    ".jsonl",
    ".log",
    ".pbix",
    ".png",
    ".pptx",
    ".pyc",
    ".sqlite",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}

RUNTIME_ALLOWLIST = {
    "AIS_INBOUND_API_CONTRACT_DRAFT.MD",
    "AIS_INBOUND_API_CONTRACT_V1.MD",
    "AIS_INBOUND_API_HANDOFF.MD",
    "AIS_INBOUND_OPENAPI.JSON",
    "AIS_INBOUND_OPENAPI.YAML",
    "AIS_INBOUND_POSTMAN_COLLECTION.JSON",
    "AIS_INBOUND_PRODUCTION_MIGRATION_CHECKLIST.MD",
    "AIS_INBOUND_PRODUCTION_OPERATIONS_RUNBOOK.MD",
    "AIS_INBOUND_READINESS_GATE.MD",
    "AIS_INBOUND_SECURITY_AUDIT.MD",
    "CHATGPT_COPILOT_SAFETY.MD",
    "CHATGPT_PRODUCTION_REVIEW_RESPONSE_STALL.MD",
    "GO_NO_GO_SUMMARY.MD",
    "GREEN_GATE_TRACKER.MD",
    "PEA_PITCH_DELIVERY_MANIFEST.MD",
    "PILOT_COMPLETE_README.MD",
    "PILOT_COMPLETION_GATE.MD",
    "PRODUCTION_READINESS_GATE.MD",
}

SECRET_VALUE_PATTERNS = [
    re.compile(
        r'(?i)(\b(?:AIS_INBOUND_API_KEY|WEBEX_BOT_TOKEN|WEBEX_CLIENT_SECRET|WEBEX_ROOM_ID|OPENAI_API_KEY|'
        r'API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|CLIENT_SECRET|TOKEN|SECRET)\s*[:=]\s*)(["\']?)[^\s"\']{6,}(["\']?)'
    ),
    re.compile(
        r'(?i)(["\'](?:access_token|refresh_token|client_secret|webex_room_id|room_id|api_key|x-api-key|token|secret)["\']\s*:\s*)'
        r'["\'][^"\']+["\']'
    ),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-+/=]{12,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_\-=]+"),
    re.compile(r"https://[A-Za-z0-9\-]+\.loca\.lt"),
]

IDENTIFIER_VALUE_PATTERNS = [
    re.compile(r'(?i)(["\'](?:meter_no|peano|PEANO|meterNumber|meterNo)["\']\s*:\s*)["\'][^"\']{6,}["\']'),
    re.compile(r'(?i)(\b(?:meter_no|peano|PEANO|meterNumber|meterNo)\s*=\s*)["\'][^"\']{6,}["\']'),
    re.compile(r'(?i)(\broom_id\s*=\s*)["\'][^"\']+["\']'),
    re.compile(r'(?i)(["\']roomId["\']\s*:\s*)["\'][^"\']+["\']'),
]

FORBIDDEN_AFTER_SANITIZE = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_\-=]+"),
    re.compile(r"https://[A-Za-z0-9\-]+\.loca\.lt"),
    re.compile(r'(?i)["\'](?:access_token|refresh_token|client_secret|api_key|token|secret)["\']\s*:\s*["\'](?!<REDACTED)[^"\']+["\']'),
    re.compile(r'(?i)["\'](?:meter_no|peano|meterNumber|meterNo)["\']\s*:\s*["\'][0-9]{6,}["\']'),
]


@dataclass(frozen=True)
class SanitizedFile:
    source: Path
    relative_path: str
    redactions: int
    bytes_written: int


def export_sanitized_codebase(
    workspace: str | Path,
    *,
    output_dir: str | Path = "runtime/chatgpt_production_review",
    zip_output: str | Path = "runtime/sanitized_codebase_bundle.zip",
    manifest_output: str | Path = "runtime/sanitized_codebase_manifest.json",
    prompt_output: str | Path = "runtime/chatgpt_production_review_prompt.md",
    audit_output: str | Path = "runtime/chatgpt_production_review_audit.md",
) -> dict[str, Any]:
    root = Path(workspace)
    out_dir = _resolve(root, output_dir)
    zip_path = _resolve(root, zip_output)
    manifest_path = _resolve(root, manifest_output)
    prompt_path = _resolve(root, prompt_output)
    audit_path = _resolve(root, audit_output)

    if out_dir.exists():
        _assert_safe_workspace_child(root, out_dir)
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    included: list[SanitizedFile] = []
    excluded: list[str] = []
    scan_failures: list[dict[str, str]] = []

    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        rel_path = source.relative_to(root).as_posix()
        include, reason = _should_include_for_chatgpt(source, root)
        if not include:
            if _should_record_exclusion(rel_path):
                excluded.append(f"{rel_path} :: {reason}")
            continue
        text = _read_text(source)
        if text is None:
            excluded.append(f"{rel_path} :: not utf-8 text")
            continue
        sanitized, redactions = _sanitize_text(text)
        issues = _scan_sanitized_text(sanitized)
        for issue in issues:
            scan_failures.append({"file": rel_path, "issue": issue})
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sanitized, encoding="utf-8")
        included.append(
            SanitizedFile(
                source=source,
                relative_path=rel_path,
                redactions=redactions,
                bytes_written=target.stat().st_size,
            )
        )

    _write_chatgpt_prompt(prompt_path, zip_path, manifest_path)
    _write_chatgpt_audit(audit_path, included, excluded, scan_failures)

    if zip_path.exists():
        _assert_safe_workspace_child(root, zip_path)
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(out_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(out_dir).as_posix())
        archive.write(prompt_path, prompt_path.name)
        archive.write(audit_path, audit_path.name)

    manifest = {
        "generated_at": _utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "status": "PASS" if not scan_failures else "FAIL",
        "zip_output": str(zip_path),
        "output_dir": str(out_dir),
        "prompt_output": str(prompt_path),
        "audit_output": str(audit_path),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "redaction_count": sum(item.redactions for item in included),
        "scan_failures": scan_failures,
        "included_files": [
            {
                "path": item.relative_path,
                "redactions": item.redactions,
                "bytes": item.bytes_written,
            }
            for item in included
        ],
        "excluded_samples": excluded[:300],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def build_production_readiness_gate(
    workspace: str | Path,
    *,
    cloud_dir: str | Path = "runtime/cloud_pilot",
    sanitized_manifest: str | Path = "runtime/sanitized_codebase_manifest.json",
    pilot_gate_file: str | Path = "runtime/pilot_completion_gate.json",
    green_gate_file: str | Path = "runtime/green_gate_tracker.md",
    production_gate_file: str | Path = "runtime/production_readiness_gate.md",
    owner_approval_file: str | Path = "runtime/cloud_pilot/owner_approval_status.json",
    output_markdown: str | Path = "runtime/production_path_readiness_gate.md",
    output_json: str | Path = "runtime/production_path_readiness_gate.json",
) -> dict[str, Any]:
    root = Path(workspace)
    cloud_root = _resolve(root, cloud_dir)
    manifest = _read_json(_resolve(root, sanitized_manifest))
    pilot_gate = _read_json(_resolve(root, pilot_gate_file))
    owner_approval = _read_json(_resolve(root, owner_approval_file))
    green_gate_text = _read_text(_resolve(root, green_gate_file)) or ""
    production_gate_text = _read_text(_resolve(root, production_gate_file)) or ""

    checks = [
        _prod_check(
            "sanitized_codebase_bundle",
            manifest.get("status") == "PASS" and bool(manifest.get("zip_output")),
            "ChatGPT review bundle exists and passed secret scan.",
            "ChatGPT review bundle is missing or failed secret scan.",
        ),
        _prod_check(
            "cloud_container_package",
            _all_exist(cloud_root, ["Dockerfile", "docker-compose.yml", ".env.cloud.example", "README.md"]),
            "Container package files are present.",
            "Container package files are incomplete.",
        ),
        _prod_check(
            "cloud_ops_runbook",
            _all_exist(
                cloud_root,
                [
                    "cloud_operator_runbook.md",
                    "incident_playbook.md",
                    "monitoring_policy.md",
                    "backup_restore_commands.md",
                ],
            ),
            "Cloud operations, monitoring, incident, and backup docs are present.",
            "Cloud operations docs are incomplete.",
        ),
        _prod_check(
            "secret_loading_policy",
            _env_template_is_placeholder(cloud_root / ".env.cloud.example"),
            "Secrets are configured as environment/secret-manager values, not committed values.",
            "Cloud env template appears to contain real secrets.",
        ),
        _prod_check(
            "pilot_gate",
            pilot_gate.get("pilot_complete_status") == "PILOT_COMPLETE"
            and pilot_gate.get("production_send") == "blocked",
            "Pilot Complete gate passed and production_send remains blocked.",
            "Pilot Complete gate is missing or unsafe.",
        ),
        _prod_check(
            "owner_approval",
            _owner_approvals_passed(owner_approval),
            "All production owners approved the cutover.",
            "Owner approvals are missing or pending.",
            blocked=True,
        ),
        _prod_check(
            "green_auto_etr_gate",
            _green_gate_passed(green_gate_text, production_gate_text),
            "Auto ETR metric gate passed.",
            "Auto ETR metric gate is blocked; keep customer-facing ETR sends disabled.",
            blocked=True,
        ),
    ]

    cloud_package_ready = all(
        check["status"] == "PASS"
        for check in checks
        if check["name"] in {"cloud_container_package", "cloud_ops_runbook", "secret_loading_policy"}
    )
    infra_ready = all(check["status"] == "PASS" for check in checks if check["name"] != "green_auto_etr_gate")
    auto_etr_ready = all(check["status"] == "PASS" for check in checks)
    report = {
        "generated_at": _utc_now_iso(),
        "mode": "shadow",
        "production_send": "blocked",
        "cloud_endpoint_ready": "READY_FOR_DEPLOYMENT_PACKAGE" if cloud_package_ready else "BLOCKED_PACKAGE_INCOMPLETE",
        "production_infra_ready": "READY_FOR_OWNER_CUTOVER" if infra_ready else "BLOCKED_PENDING_OWNER_OR_CONTROL",
        "auto_etr_ready": "READY_FOR_GREEN_LANE_OWNER_REVIEW" if auto_etr_ready else "BLOCKED_GREEN_GATE",
        "checks": checks,
        "operator_next_step": _production_next_step(cloud_package_ready, infra_ready, auto_etr_ready),
        "artifacts": {
            "cloud_dir": str(cloud_root),
            "sanitized_manifest": str(_resolve(root, sanitized_manifest)),
            "pilot_gate_file": str(_resolve(root, pilot_gate_file)),
            "green_gate_file": str(_resolve(root, green_gate_file)),
            "production_gate_file": str(_resolve(root, production_gate_file)),
            "owner_approval_file": str(_resolve(root, owner_approval_file)),
        },
    }

    markdown_path = _resolve(root, output_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_production_readiness_markdown(report), encoding="utf-8")
    json_path = _resolve(root, output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["output_markdown"] = str(markdown_path)
    report["output_json"] = str(json_path)
    return report


def _resolve(root: Path, path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else root / path


def _assert_safe_workspace_child(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise ValueError(f"Refusing to replace path outside workspace: {path}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _should_include_for_chatgpt(source: Path, root: Path) -> tuple[bool, str]:
    rel = source.relative_to(root)
    rel_text = rel.as_posix()
    parts = set(rel.parts)
    upper_name = source.name.upper()
    suffix = source.suffix.lower()
    if parts & EXCLUDED_DIR_PARTS:
        return False, "excluded directory"
    if len(rel.parts) >= 2 and rel.parts[0] == "runtime" and rel.parts[1] in EXCLUDED_RUNTIME_DIRS:
        return False, "excluded runtime directory"
    if suffix in EXCLUDED_SUFFIXES:
        return False, "excluded binary/runtime suffix"
    if source.name.lower() in {".env", "webex_oauth_token.json"}:
        return False, "excluded secret-like file"
    if rel.parts[0] in {"ais_etr", "tests"}:
        return suffix == ".py", "source/test python" if suffix == ".py" else "non-python source fixture excluded"
    if rel.parts[0] == "runtime":
        if len(rel.parts) >= 2 and rel.parts[1] in {"cloud_pilot", "ais_inbound_test_kit"}:
            return _is_text_candidate(source), "runtime allowlisted directory"
        return upper_name in RUNTIME_ALLOWLIST, "runtime top-level allowlist" if upper_name in RUNTIME_ALLOWLIST else "runtime file not allowlisted"
    if rel_text in {"AGENTS.md", "README_AIS_ETR_MVP.md", ".dockerignore"}:
        return True, "root allowlist"
    return False, "not in ChatGPT source bundle scope"


def _should_record_exclusion(rel_path: str) -> bool:
    return any(marker in rel_path.lower() for marker in ("private", "token", "key", "sqlite", "jsonl", "chrome", "snapshot"))


def _is_text_candidate(source: Path) -> bool:
    if source.name in {"Dockerfile", ".dockerignore"}:
        return True
    return source.suffix.lower() in TEXT_EXTENSIONS


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sanitize_text(text: str) -> tuple[str, int]:
    redactions = 0
    sanitized = text.replace("verbatim WebEx", "verbatim WebEx")
    for pattern in SECRET_VALUE_PATTERNS:
        sanitized, count = pattern.subn(_secret_replacement, sanitized)
        redactions += count
    for pattern in IDENTIFIER_VALUE_PATTERNS:
        sanitized, count = pattern.subn(_identifier_replacement, sanitized)
        redactions += count
    return sanitized, redactions


def _secret_replacement(match: re.Match[str]) -> str:
    if match.re.pattern.startswith("sk-"):
        return "<REDACTED_SECRET>"
    if "loca.lt" in match.group(0):
        return "https://<REDACTED_TUNNEL>"
    if match.group(0).startswith("Y2lz"):
        return "<REDACTED_ROOM_ID>"
    if match.lastindex and match.lastindex >= 1:
        return f"{match.group(1)}\"<REDACTED_SECRET>\""
    return "<REDACTED_SECRET>"


def _identifier_replacement(match: re.Match[str]) -> str:
    prefix = match.group(1)
    if "room" in prefix.lower():
        return f'{prefix}"<REDACTED_ROOM_ID>"'
    return f'{prefix}"<REDACTED_METER_REF>"'


def _scan_sanitized_text(text: str) -> list[str]:
    issues = []
    for pattern in FORBIDDEN_AFTER_SANITIZE:
        if pattern.search(text):
            issues.append(pattern.pattern)
    return issues


def _write_chatgpt_prompt(prompt_path: Path, zip_path: Path, manifest_path: Path) -> None:
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        "\n".join(
            [
                "# ChatGPT Production Review Prompt",
                "",
                "You are reviewing a sanitized codebase bundle for PEA API Intellisense.",
                "Please review production architecture, API contract, security/privacy controls, operations runbook, retry/idempotency, monitoring, backup/restore, and test gaps.",
                "",
                "Important constraints:",
                "- Treat the system as shadow mode until the production gate passes.",
                "- `production_send` must remain `blocked` until owner approval and Auto ETR green gate pass.",
                "- AIS outage/restore remains customer-facing truth.",
                "- WebEx is trigger/device evidence only.",
                "- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.",
                "- Do not ask for raw secrets, room ids, meter lists, PEANO lists, raw runtime DB, or verbatim WebEx text.",
                "",
                f"Bundle: `{zip_path}`",
                f"Manifest: `{manifest_path}`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_chatgpt_audit(
    audit_path: Path,
    included: list[SanitizedFile],
    excluded: list[str],
    scan_failures: list[dict[str, str]],
) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ChatGPT Production Review Audit",
        "",
        f"Generated: `{_utc_now_iso()}`",
        "",
        "## Summary",
        "",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        f"- Included files: `{len(included)}`",
        f"- Excluded samples recorded: `{len(excluded)}`",
        f"- Redactions: `{sum(item.redactions for item in included)}`",
        f"- Scan status: `{'PASS' if not scan_failures else 'FAIL'}`",
        "",
        "## Exclusion Policy",
        "",
        "- No runtime private folder, OAuth token file, pilot key, SQLite DB, JSONL logs, browser profile, raw logs, full meter/PEANO list, or customer identity export is included.",
        "- Source code variable names may mention token/key fields, but committed values are redacted or excluded.",
        "",
    ]
    if scan_failures:
        lines.extend(["## Scan Failures", ""])
        for failure in scan_failures:
            lines.append(f"- `{failure['file']}`: `{failure['issue']}`")
        lines.append("")
    audit_path.write_text("\n".join(lines), encoding="utf-8")


def _prod_check(name: str, ok: bool, pass_message: str, fail_message: str, *, blocked: bool = False) -> dict[str, str]:
    return {
        "name": name,
        "status": "PASS" if ok else ("BLOCKED" if blocked else "FAIL"),
        "message": pass_message if ok else fail_message,
    }


def _all_exist(root: Path, names: list[str]) -> bool:
    return all((root / name).exists() for name in names)


def _env_template_is_placeholder(path: Path) -> bool:
    text = _read_text(path)
    if not text:
        return False
    if re.search(r"(?i)(token|secret|api_key|password)\s*=\s*[A-Za-z0-9_\-]{12,}", text):
        return False
    return "AIS_INBOUND_API_KEY=" in text and "<SET_IN_SECRET_MANAGER>" in text


def _owner_approvals_passed(report: dict[str, Any]) -> bool:
    approvals = report.get("approvals")
    if not isinstance(approvals, dict) or not approvals:
        return False
    return all(value is True for value in approvals.values())


def _green_gate_passed(green_gate_text: str, production_gate_text: str) -> bool:
    combined = f"{green_gate_text}\n{production_gate_text}".lower()
    blocked_markers = [
        "blocked",
        "green rows: `0`",
        "current green rows: 0",
        "blocked_too_few_green_rows",
        "blocked_no_green_subset",
    ]
    return bool(combined.strip()) and not any(marker in combined for marker in blocked_markers)


def _production_next_step(cloud_package_ready: bool, infra_ready: bool, auto_etr_ready: bool) -> str:
    if not cloud_package_ready:
        return "Complete the cloud container package before asking AIS to test a cloud endpoint."
    if not infra_ready:
        return "Deploy the package to an approved cloud/VM target, configure secrets, monitoring, backup/restore, and collect owner approvals."
    if not auto_etr_ready:
        return "Run shadow auto-candidate collection until green rows, MAE, coverage, and owner approval pass; keep customer-facing Auto ETR blocked."
    return "Open only the approved green lane first, with rollback and monitoring active."


def _production_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Production Path Readiness Gate",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- Cloud endpoint package: `{report['cloud_endpoint_ready']}`",
        f"- Production infrastructure: `{report['production_infra_ready']}`",
        f"- Auto ETR: `{report['auto_etr_ready']}`",
        f"- Mode: `{report['mode']}`",
        f"- Production send: `{report['production_send']}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Message |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        lines.append(f"| `{check['name']}` | `{check['status']}` | {check['message']} |")
    lines.extend(
        [
            "",
            "## Operator Next Step",
            "",
            report["operator_next_step"],
            "",
            "## Guardrails",
            "",
            "- This gate does not approve customer-facing Auto ETR.",
            "- `production_send` remains `blocked` until green gate and owner approval pass.",
            "- AIS outage/restore remains customer-facing truth.",
            "- WebEx is trigger/device evidence only.",
            "- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.",
            "",
            "## Artifacts",
            "",
        ]
    )
    for name, path in (report.get("artifacts") or {}).items():
        lines.append(f"- {name}: `{path}`")
    lines.append("")
    return "\n".join(lines)
