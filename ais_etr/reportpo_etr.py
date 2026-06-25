from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Iterator

from .evaluation import TRUTH_MAPPING_COLUMNS
from .utils import normalize_device_id, normalize_feeder


REPORTPO_ETR_COLUMNS = (
    "event_number",
    "event_start_time",
    "event_create_time",
    "first_restore_time",
    "event_etr_time",
    "event_end_time",
    "etr_first_time",
    "ip_datetime",
    "device_id",
    "feeder",
    "office",
    "area",
    "event_type",
    "event_status",
    "etr_type",
    "etr_type_description",
    "cause_group",
    "cause_code",
    "work_type",
    "job_status_at_notification",
    "feature_quality",
    "feature_flags",
    "etr_send_count",
    "reportpo_first_restore_minutes",
    "event_end_duration_minutes",
    "actual_restoration_minutes",
    "truth_source",
    "truth_target",
    "truth_definition",
    "truth_quality",
    "truth_flags",
    "source_file",
)

REPORTPO_MATCH_AUDIT_COLUMNS = (
    "webex_message_id",
    "webex_event_time",
    "webex_device_id",
    "webex_feeder",
    "candidate_event_number",
    "candidate_device_id",
    "candidate_event_start_time",
    "actual_restoration_minutes",
    "truth_target",
    "truth_definition",
    "delta_minutes",
    "candidate_count",
    "match_status",
    "match_reason",
    "truth_quality",
)

REPORTPO_ALIAS_COLUMNS = (
    "webex_device_id",
    "reportpo_device_id",
    "reason",
    "status",
    "reviewed_by",
    "reviewed_at",
)

REPORTPO_CANDIDATE_COLUMNS = (
    "webex_message_id",
    "webex_device_id",
    "webex_event_time",
    "candidate_device_id",
    "candidate_event_number",
    "candidate_event_start_time",
    "delta_minutes",
    "match_level",
    "truth_quality",
    "truth_target",
    "truth_definition",
    "reason",
)

REPORTPO_FEATURE_JOIN_COLUMNS = (
    "webex_message_id",
    "webex_event_time",
    "webex_device_id",
    "webex_feeder",
    "event_number",
    "reportpo_device_id",
    "reportpo_event_start_time",
    "delta_minutes",
    "match_status",
    "match_reason",
    "event_type",
    "event_status",
    "etr_type",
    "etr_type_description",
    "ip_datetime",
    "cause_group",
    "cause_code",
    "work_type",
    "job_status_at_notification",
    "feature_quality",
    "feature_flags",
)

DEFAULT_REPORTPO_QUERYDATA_URL = (
    "https://powerbi-report.pea.co.th/powerbi/api/explore/reports/"
    "1dffbf73-a638-49f4-b99d-7319ba300b61/querydata"
)

_EMPTY_VALUES = {"", "-", "nan", "none", "null", "nat"}
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)
_POWERBI_NULL_MASK = "\u00d8"
REPORTPO_TRUTH_SOURCE = "reportpo"
REPORTPO_TRUTH_TARGET = "reportpo_first_restore_minutes"
REPORTPO_TRUTH_DEFINITION = "FIRST_RESTORE_TIME - EVENT_START_TIME"
REPORTPO_EXTRA_SELECTS = (
    ("ETRtype", "Description2", "Description"),
    ("ETR_OU", "Group", "Group"),
)


@dataclass(frozen=True)
class ReportPoEtrRow:
    event_number: str
    event_start_time: datetime | None
    event_create_time: datetime | None
    first_restore_time: datetime | None
    event_etr_time: datetime | None
    event_end_time: datetime | None
    etr_first_time: datetime | None
    ip_datetime: datetime | None
    device_id: str | None
    office: str | None
    area: str | None
    event_type: str | None
    event_status: str | None
    etr_type: str | None
    etr_type_description: str | None
    cause_group: str | None
    cause_code: str | None
    work_type: str | None
    etr_send_count: int | None
    source_file: str

    @property
    def feeder(self) -> str | None:
        return _normalize_reportpo_feeder(self.device_id)

    @property
    def reportpo_first_restore_minutes(self) -> float | None:
        if self.event_start_time is None or self.first_restore_time is None:
            return None
        return round((self.first_restore_time - self.event_start_time).total_seconds() / 60, 2)

    @property
    def event_end_duration_minutes(self) -> float | None:
        if self.event_start_time is None or self.event_end_time is None:
            return None
        return round((self.event_end_time - self.event_start_time).total_seconds() / 60, 2)

    @property
    def actual_restoration_minutes(self) -> float | None:
        return self.reportpo_first_restore_minutes

    @property
    def truth_quality(self) -> str:
        if self.event_start_time is None:
            return "MISSING_START"
        if self.first_restore_time is None:
            return "MISSING_RESTORE"
        actual = self.reportpo_first_restore_minutes
        if actual is None:
            return "MISSING_ACTUAL"
        if actual < 0:
            return "INVALID_NEGATIVE"
        if actual > 1440:
            return "INVALID_LONG"
        if actual <= 5:
            return "REVIEW_SHORT"
        return "OK"

    @property
    def truth_flags(self) -> str:
        flags: list[str] = []
        if self.event_etr_time is not None:
            flags.append("event_etr_time_not_truth")
        if self.event_end_time is not None:
            flags.append("event_end_time_not_truth")
        if self.truth_quality not in {"OK"}:
            flags.append(self.truth_quality.lower())
        return ";".join(flags)

    @property
    def job_status_at_notification(self) -> str:
        return "not_dispatched_yet"

    @property
    def feature_quality(self) -> str:
        if self.cause_group or self.cause_code:
            return "cause_available"
        if self.event_type or self.event_status or self.etr_type or self.etr_type_description:
            return "proxy_only"
        return "feature_missing"

    @property
    def feature_flags(self) -> str:
        flags: list[str] = []
        if not self.cause_group and not self.cause_code:
            flags.append("cause_missing")
        if not self.work_type:
            flags.append("work_type_missing")
        if self.job_status_at_notification == "not_dispatched_yet":
            flags.append("webex_first_notification_status_assumption")
        return ";".join(flags)

    def asdict(self) -> dict[str, str]:
        first_restore_actual = self.reportpo_first_restore_minutes
        event_end_actual = self.event_end_duration_minutes
        return {
            "event_number": self.event_number,
            "event_start_time": _format_dt(self.event_start_time),
            "event_create_time": _format_dt(self.event_create_time),
            "first_restore_time": _format_dt(self.first_restore_time),
            "event_etr_time": _format_dt(self.event_etr_time),
            "event_end_time": _format_dt(self.event_end_time),
            "etr_first_time": _format_dt(self.etr_first_time),
            "ip_datetime": _format_dt(self.ip_datetime),
            "device_id": self.device_id or "",
            "feeder": self.feeder or "",
            "office": self.office or "",
            "area": self.area or "",
            "event_type": self.event_type or "",
            "event_status": self.event_status or "",
            "etr_type": self.etr_type or "",
            "etr_type_description": self.etr_type_description or "",
            "cause_group": self.cause_group or "",
            "cause_code": self.cause_code or "",
            "work_type": self.work_type or "",
            "job_status_at_notification": self.job_status_at_notification,
            "feature_quality": self.feature_quality,
            "feature_flags": self.feature_flags,
            "etr_send_count": "" if self.etr_send_count is None else str(self.etr_send_count),
            "reportpo_first_restore_minutes": "" if first_restore_actual is None else str(first_restore_actual),
            "event_end_duration_minutes": "" if event_end_actual is None else str(event_end_actual),
            "actual_restoration_minutes": "" if first_restore_actual is None else str(first_restore_actual),
            "truth_source": REPORTPO_TRUTH_SOURCE,
            "truth_target": REPORTPO_TRUTH_TARGET,
            "truth_definition": REPORTPO_TRUTH_DEFINITION,
            "truth_quality": self.truth_quality,
            "truth_flags": self.truth_flags,
            "source_file": self.source_file,
        }


def import_reportpo_etr(source: str | Path, output_csv: str | Path) -> dict[str, Any]:
    rows = load_reportpo_etr(source)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_ETR_COLUMNS))
        writer.writeheader()
        writer.writerows(row.asdict() for row in rows)

    quality_counts: dict[str, int] = {}
    feature_quality_counts: dict[str, int] = {}
    event_type_counts: dict[str, int] = {}
    event_status_counts: dict[str, int] = {}
    for row in rows:
        quality_counts[row.truth_quality] = quality_counts.get(row.truth_quality, 0) + 1
        feature_quality_counts[row.feature_quality] = feature_quality_counts.get(row.feature_quality, 0) + 1
        if row.event_type:
            event_type_counts[row.event_type] = event_type_counts.get(row.event_type, 0) + 1
        if row.event_status:
            event_status_counts[row.event_status] = event_status_counts.get(row.event_status, 0) + 1
    return {
        "source": str(source),
        "output_csv": str(output),
        "rows": len(rows),
        "usable_reportpo_first_restore_rows": sum(
            1 for row in rows if row.reportpo_first_restore_minutes is not None
        ),
        "usable_actual_rows": sum(1 for row in rows if row.actual_restoration_minutes is not None),
        "truth_quality": quality_counts,
        "feature_quality": feature_quality_counts,
        "event_type": _top_counts(event_type_counts),
        "event_status": _top_counts(event_status_counts),
    }


def fetch_reportpo_etr_querydata(
    template: str | Path,
    output_json: str | Path,
    request_output: str | Path | None = None,
    headers_output: str | Path | None = None,
    endpoint_url: str = DEFAULT_REPORTPO_QUERYDATA_URL,
    count: int = 100000,
    pages: int = 1,
    curl_path: str = "curl.exe",
) -> dict[str, Any]:
    output = Path(output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    request_path = Path(request_output) if request_output else output.with_name(output.stem + "_request.json")
    headers_path = Path(headers_output) if headers_output else output.with_name(output.stem + "_headers.txt")
    request_path.parent.mkdir(parents=True, exist_ok=True)
    headers_path.parent.mkdir(parents=True, exist_ok=True)

    page_results: list[dict[str, Any]] = []
    restart_tokens = None
    max_pages = max(1, int(pages))
    for page_number in range(1, max_pages + 1):
        page_request_path = _page_path(request_path, page_number, max_pages)
        page_headers_path = _page_path(headers_path, page_number, max_pages)
        page_output_path = _page_path(output, page_number, max_pages)
        request = build_reportpo_etr_query(template, count=count, restart_tokens=restart_tokens)
        page_request_path.write_text(json.dumps(request, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        status_code = _run_curl_query(
            curl_path,
            endpoint_url,
            page_request_path,
            page_headers_path,
            page_output_path,
        )
        response = json.loads(page_output_path.read_text(encoding="utf-8"))
        errors = _find_powerbi_errors(response)
        if errors:
            raise RuntimeError("ReportPO querydata returned semantic error: " + "; ".join(errors[:3]))
        rows = _count_response_rows(response)
        page_results.append(
            {
                "page": page_number,
                "request_json": str(page_request_path),
                "headers_output": str(page_headers_path),
                "output_json": str(page_output_path),
                "http_status": status_code,
                "bytes": page_output_path.stat().st_size,
                "rows": rows,
            }
        )
        restart_tokens = _extract_restart_tokens(response)
        if not restart_tokens:
            break

    if len(page_results) == 1:
        single_output = Path(page_results[0]["output_json"])
        if single_output.resolve() != output.resolve():
            output.write_text(single_output.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        combined = []
        for page in page_results:
            response_text = Path(page["output_json"]).read_text(encoding="utf-8")
            combined.append({"response": response_text})
        output.write_text(json.dumps(combined, ensure_ascii=False), encoding="utf-8")

    return {
        "endpoint_url": endpoint_url,
        "request_json": str(request_path),
        "output_json": str(output),
        "headers_output": str(headers_path),
        "http_status": page_results[-1]["http_status"] if page_results else None,
        "bytes": output.stat().st_size if output.exists() else 0,
        "count_requested": count,
        "pages_requested": max_pages,
        "pages_fetched": len(page_results),
        "page_rows": [page["rows"] for page in page_results],
        "page_outputs": page_results,
    }


def build_reportpo_etr_query(
    template: str | Path,
    count: int = 100000,
    restart_tokens: list[list[Any]] | None = None,
) -> dict[str, Any]:
    path = Path(template)
    payload = json.loads(path.read_text(encoding="utf-8"))
    request = _find_reportpo_etr_request(payload)
    command = request["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    _ensure_reportpo_feature_selects(command)
    binding = command.setdefault("Binding", {})
    reduction = binding.setdefault("DataReduction", {"DataVolume": 3, "Primary": {}})
    reduction.setdefault("DataVolume", 3)
    primary = reduction.setdefault("Primary", {})
    window: dict[str, Any] = {"Count": int(count)}
    if restart_tokens:
        window["RestartTokens"] = restart_tokens
    primary["Window"] = window
    return request


def _ensure_reportpo_feature_selects(command: dict[str, Any]) -> None:
    query = command.setdefault("Query", {})
    select = query.setdefault("Select", [])
    sources = {
        str(item.get("Entity")): str(item.get("Name"))
        for item in query.get("From", []) or []
        if isinstance(item, dict) and item.get("Entity") and item.get("Name")
    }
    existing = set()
    for item in select:
        if not isinstance(item, dict):
            continue
        column = item.get("Column") or {}
        if isinstance(column, dict) and column.get("Property"):
            existing.add(str(column.get("Property")))

    binding = command.setdefault("Binding", {})
    primary = binding.setdefault("Primary", {})
    groupings = primary.setdefault("Groupings", [{"Projections": []}])
    if not groupings:
        groupings.append({"Projections": []})
    projections = groupings[0].setdefault("Projections", [])

    for entity, property_name, native_name in REPORTPO_EXTRA_SELECTS:
        if property_name in existing:
            continue
        source_name = sources.get(entity)
        if not source_name:
            continue
        projection_index = len(select)
        select.append(
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": source_name}},
                    "Property": property_name,
                },
                "Name": f"{entity}.{property_name}",
                "NativeReferenceName": native_name,
            }
        )
        projections.append(projection_index)
        existing.add(property_name)


def load_reportpo_etr(source: str | Path) -> list[ReportPoEtrRow]:
    path = Path(source)
    if path.suffix.lower() == ".csv":
        return list(_load_reportpo_csv(path))
    if path.suffix.lower() == ".json":
        return list(_load_reportpo_querydata_json(path))
    raise ValueError(f"unsupported ReportPO ETR source type: {path.suffix}")


def match_reportpo_truth(
    db_path: str | Path,
    reportpo_csv: str | Path,
    mapping_csv: str | Path,
    audit_csv: str | Path | None = None,
    alias_file: str | Path | None = None,
    candidates_csv: str | Path | None = None,
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
    overwrite: bool = False,
) -> dict[str, Any]:
    runtime_rows = _runtime_webex_rows(db_path)
    reportpo_rows = _load_imported_reportpo_csv(reportpo_csv)
    aliases = _load_approved_aliases(alias_file)
    mapping_rows = _load_or_create_mapping(mapping_csv, runtime_rows)
    mapping_by_message = {row["webex_message_id"]: row for row in mapping_rows}

    audit_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    filled_rows = 0
    preserved_existing_rows = 0
    matched_rows = 0
    ambiguous_rows = 0
    no_match_rows = 0
    invalid_truth_rows = 0
    alias_matched_rows = 0

    for runtime in runtime_rows:
        decision = _match_one_runtime_event(
            runtime,
            reportpo_rows,
            aliases,
            max_window_minutes=max_window_minutes,
            ambiguity_delta_minutes=ambiguity_delta_minutes,
        )
        audit_rows.append(decision)
        if decision["match_status"] != "matched":
            candidate_rows.extend(
                _candidate_rows_for_runtime(
                    runtime,
                    reportpo_rows,
                    aliases,
                    max_window_minutes=max_window_minutes,
                    limit=5,
                    reason=decision["match_reason"],
                )
            )
        status = decision["match_status"]
        if status == "matched":
            matched_rows += 1
            if str(decision.get("match_reason") or "").startswith("approved_alias"):
                alias_matched_rows += 1
        elif status == "ambiguous":
            ambiguous_rows += 1
        elif status == "invalid_truth":
            invalid_truth_rows += 1
        elif status == "no_match":
            no_match_rows += 1

        message_id = runtime.get("webex_message_id") or ""
        mapping = mapping_by_message.get(message_id)
        if mapping is None or status != "matched":
            continue
        if not overwrite and str(mapping.get("actual_restoration_minutes", "")).strip():
            preserved_existing_rows += 1
            continue
        mapping["event_number"] = str(decision.get("candidate_event_number") or "")
        mapping["actual_restoration_minutes"] = str(decision.get("actual_restoration_minutes") or "")
        mapping["truth_source"] = REPORTPO_TRUTH_SOURCE
        mapping["truth_target"] = REPORTPO_TRUTH_TARGET
        mapping["truth_definition"] = REPORTPO_TRUTH_DEFINITION
        mapping["truth_quality"] = str(decision.get("truth_quality") or "")
        mapping["truth_notes"] = str(decision.get("match_reason") or "")
        filled_rows += 1

    _write_mapping(mapping_csv, mapping_rows)
    if audit_csv:
        _write_audit(audit_csv, audit_rows)
    if candidates_csv:
        _write_candidates(candidates_csv, candidate_rows)

    return {
        "db_path": str(db_path),
        "reportpo_csv": str(reportpo_csv),
        "mapping_output": str(mapping_csv),
        "audit_output": str(audit_csv) if audit_csv else None,
        "alias_file": str(alias_file) if alias_file else None,
        "candidates_output": str(candidates_csv) if candidates_csv else None,
        "runtime_events": len(runtime_rows),
        "reportpo_rows": len(reportpo_rows),
        "matched_rows": matched_rows,
        "alias_matched_rows": alias_matched_rows,
        "ambiguous_rows": ambiguous_rows,
        "invalid_truth_rows": invalid_truth_rows,
        "no_match_rows": no_match_rows,
        "candidate_rows": len(candidate_rows),
        "filled_rows": filled_rows,
        "preserved_existing_rows": preserved_existing_rows,
    }


def join_reportpo_features_to_shadow(
    db_path: str | Path,
    reportpo_csv: str | Path,
    output_csv: str | Path,
    alias_file: str | Path | None = None,
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
) -> dict[str, Any]:
    runtime_rows = _runtime_webex_rows(db_path)
    reportpo_rows = _load_imported_reportpo_csv(reportpo_csv)
    aliases = _load_approved_aliases(alias_file)

    output_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    for runtime in runtime_rows:
        decision = _match_one_runtime_feature(
            runtime,
            reportpo_rows,
            aliases,
            max_window_minutes=max_window_minutes,
            ambiguity_delta_minutes=ambiguity_delta_minutes,
        )
        output_rows.append(decision)
        status = str(decision.get("match_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        quality = str(decision.get("feature_quality") or "")
        if quality:
            quality_counts[quality] = quality_counts.get(quality, 0) + 1

    _write_feature_join(output_csv, output_rows)
    return {
        "db_path": str(db_path),
        "reportpo_csv": str(reportpo_csv),
        "output_csv": str(output_csv),
        "alias_file": str(alias_file) if alias_file else None,
        "runtime_events": len(runtime_rows),
        "reportpo_rows": len(reportpo_rows),
        "match_status": dict(sorted(status_counts.items())),
        "feature_quality": dict(sorted(quality_counts.items())),
        "matched_rows": status_counts.get("matched", 0),
    }


def build_reportpo_alias_template(
    candidates_csv: str | Path,
    output_csv: str | Path,
    existing_alias_csv: str | Path | None = None,
) -> dict[str, Any]:
    existing_rows = _load_alias_rows(existing_alias_csv or output_csv)
    existing_keys = {
        (normalize_device_id(row.get("webex_device_id")), normalize_device_id(row.get("reportpo_device_id")))
        for row in existing_rows
    }
    approved_webex = {
        normalize_device_id(row.get("webex_device_id"))
        for row in existing_rows
        if str(row.get("status") or "").strip().lower() == "approved"
    }

    added = 0
    skipped_existing = 0
    skipped_approved = 0
    for candidate in _load_candidate_rows(candidates_csv):
        webex_device = normalize_device_id(candidate.get("webex_device_id"))
        reportpo_device = normalize_device_id(candidate.get("candidate_device_id"))
        match_level = str(candidate.get("match_level") or "").strip().lower()
        if not webex_device or not reportpo_device or webex_device == reportpo_device:
            continue
        if match_level != "feeder":
            continue
        if webex_device in approved_webex:
            skipped_approved += 1
            continue
        key = (webex_device, reportpo_device)
        if key in existing_keys:
            skipped_existing += 1
            continue
        existing_rows.append(
            {
                "webex_device_id": webex_device,
                "reportpo_device_id": reportpo_device,
                "reason": f"candidate_from_{candidate.get('match_level') or 'unknown'}; delta={candidate.get('delta_minutes') or ''}",
                "status": "pending",
                "reviewed_by": "",
                "reviewed_at": "",
            }
        )
        existing_keys.add(key)
        added += 1

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_ALIAS_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REPORTPO_ALIAS_COLUMNS} for row in existing_rows)
    return {
        "candidates_csv": str(candidates_csv),
        "output_csv": str(output_csv),
        "existing_rows": len(existing_rows) - added,
        "added_rows": added,
        "skipped_existing_rows": skipped_existing,
        "skipped_approved_webex_rows": skipped_approved,
        "total_rows": len(existing_rows),
    }


def _load_reportpo_csv(path: Path) -> Iterator[ReportPoEtrRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield _row_from_mapping(row, str(path))


def _load_reportpo_querydata_json(path: Path) -> Iterator[ReportPoEtrRow]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = _find_powerbi_errors(payload)
    if errors:
        raise ValueError("ReportPO querydata contains semantic error: " + "; ".join(errors[:3]))
    for data in _iter_powerbi_data_objects(payload):
        select = data.get("descriptor", {}).get("Select") or []
        if not _looks_like_reportpo_etr_select(select):
            continue
        for raw in _decode_powerbi_rows(data):
            yield _row_from_mapping(raw, str(path))


def _find_reportpo_etr_request(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            request = item.get("request")
            if request:
                candidate = json.loads(request) if isinstance(request, str) else request
                if _request_is_reportpo_etr(candidate):
                    return candidate
        raise ValueError("could not find a ReportPO ETR request in template JSON")
    if isinstance(payload, dict) and _request_is_reportpo_etr(payload):
        return payload
    raise ValueError("could not find a ReportPO ETR request in template JSON")


def _request_is_reportpo_etr(request: dict[str, Any]) -> bool:
    try:
        command = request["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    except (KeyError, IndexError, TypeError):
        return False
    select = command.get("Query", {}).get("Select") or []
    properties = set()
    for item in select:
        if not isinstance(item, dict):
            continue
        column = item.get("Column") or {}
        if isinstance(column, dict):
            property_name = column.get("Property")
            if property_name:
                properties.add(str(property_name))
    return {"EVENT_ID", "EVENT_START_TIME", "FIRST_RESTORE_TIME", "DEVICE_NAME"}.issubset(properties)


def _looks_like_reportpo_etr_select(select: list[dict[str, Any]]) -> bool:
    properties = set()
    for item in select:
        if not isinstance(item, dict):
            continue
        group_keys = item.get("GroupKeys") or [{}]
        if not group_keys or not isinstance(group_keys[0], dict):
            continue
        source = group_keys[0].get("Source") or {}
        if isinstance(source, dict):
            properties.add(str(source.get("Property") or ""))
    return {"EVENT_ID", "EVENT_START_TIME", "FIRST_RESTORE_TIME", "DEVICE_NAME"}.issubset(properties)


def _last_http_status(headers_path: Path) -> int | None:
    if not headers_path.exists():
        return None
    status = None
    for line in headers_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"HTTP/\S+\s+(\d{3})\b", line)
        if match:
            status = int(match.group(1))
    return status


def _run_curl_query(
    curl_path: str,
    endpoint_url: str,
    request_path: Path,
    headers_path: Path,
    output_path: Path,
) -> int | None:
    command = [
        curl_path,
        "--ntlm",
        "--user",
        ":",
        "-sS",
        "-D",
        str(headers_path),
        "-H",
        "Content-Type: application/json;charset=UTF-8",
        "--data-binary",
        f"@{request_path}",
        endpoint_url,
        "-o",
        str(output_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ReportPO querydata fetch failed: {completed.stderr.strip() or completed.stdout.strip()}")
    status_code = _last_http_status(headers_path)
    if status_code is not None and status_code >= 400:
        raise RuntimeError(f"ReportPO querydata fetch returned HTTP {status_code}")
    return status_code


def _extract_restart_tokens(response: dict[str, Any]) -> list[list[Any]] | None:
    try:
        data = response["results"][0]["result"]["data"]
        ds_list = data["dsr"]["DS"]
    except (KeyError, IndexError, TypeError):
        return None
    for ds in ds_list:
        tokens = ds.get("RT") if isinstance(ds, dict) else None
        if tokens:
            return tokens
    return None


def _count_response_rows(response: dict[str, Any]) -> int:
    total = 0
    for data in _iter_powerbi_data_objects(response):
        dsr = data.get("dsr") or {}
        for ds in dsr.get("DS") or []:
            for partition in ds.get("PH") or []:
                for key, compressed_rows in partition.items():
                    if key.startswith("DM") and isinstance(compressed_rows, list):
                        total += len(compressed_rows)
    return total


def _find_powerbi_errors(payload: Any) -> list[str]:
    errors: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            error = value.get("odata.error")
            if isinstance(error, dict):
                message = error.get("message") or {}
                text = message.get("value") if isinstance(message, dict) else None
                if text:
                    errors.append(str(text))
                else:
                    code = error.get("code")
                    if code:
                        errors.append(str(code))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return errors


def _page_path(path: Path, page_number: int, max_pages: int) -> Path:
    if max_pages <= 1:
        return path
    return path.with_name(f"{path.stem}_page{page_number:02d}{path.suffix}")


def _iter_powerbi_data_objects(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            response = item.get("response") if isinstance(item, dict) else None
            if response:
                yield from _iter_powerbi_data_objects(json.loads(response) if isinstance(response, str) else response)
        return
    if not isinstance(payload, dict):
        return
    if "descriptor" in payload and "dsr" in payload:
        yield payload
    for result in payload.get("results", []) or []:
        result_payload = result.get("result") if isinstance(result, dict) else None
        if isinstance(result_payload, dict):
            data = result_payload.get("data")
            if isinstance(data, dict):
                yield from _iter_powerbi_data_objects(data)
    data = payload.get("data")
    if isinstance(data, dict):
        yield from _iter_powerbi_data_objects(data)


def _decode_powerbi_rows(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    descriptor = data.get("descriptor") or {}
    select_by_value = {item.get("Value"): item for item in descriptor.get("Select") or []}
    dsr = data.get("dsr") or {}
    for ds in dsr.get("DS") or []:
        value_dicts = ds.get("ValueDicts") or {}
        for partition in ds.get("PH") or []:
            for key, compressed_rows in partition.items():
                if not key.startswith("DM") or not isinstance(compressed_rows, list) or not compressed_rows:
                    continue
                schema = compressed_rows[0].get("S") or []
                previous: list[Any] = [None] * len(schema)
                for row in compressed_rows:
                    values = _decode_powerbi_compressed_row(row, schema, previous)
                    previous = values
                    output: dict[str, Any] = {}
                    for index, spec in enumerate(schema):
                        select = select_by_value.get(spec.get("N")) or {}
                        column = _select_property_name(select) or str(select.get("Name") or spec.get("N") or "")
                        output[column] = _decode_powerbi_value(values[index], spec, value_dicts)
                    yield output


def _decode_powerbi_compressed_row(
    row: dict[str, Any],
    schema: list[dict[str, Any]],
    previous: list[Any],
) -> list[Any]:
    repeated_mask = int(row.get("R", 0) or 0)
    null_mask = int(row.get(_POWERBI_NULL_MASK, 0) or 0)
    cells = iter(row.get("C") or [])
    values: list[Any] = []
    for position, _spec in enumerate(schema):
        if repeated_mask & (1 << position):
            values.append(previous[position])
        elif null_mask & (1 << position):
            values.append(None)
        else:
            values.append(next(cells))
    return values


def _decode_powerbi_value(value: Any, spec: dict[str, Any], value_dicts: dict[str, list[Any]]) -> Any:
    if value is None:
        return None
    dict_name = spec.get("DN")
    if dict_name and isinstance(value, int):
        entries = value_dicts.get(dict_name) or []
        if 0 <= value < len(entries):
            return entries[value]
    if spec.get("T") == 7 and isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).replace(tzinfo=None)
    return _decode_powerbi_literal(value)


def _decode_powerbi_literal(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("datetime'") and text.endswith("'"):
        return _parse_datetime(text[9:-1])
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if re.fullmatch(r"-?\d+L", text):
        return int(text[:-1])
    return text


def _select_property_name(select: dict[str, Any]) -> str | None:
    group_keys = select.get("GroupKeys") or []
    if group_keys:
        source = group_keys[0].get("Source") or {}
        property_name = source.get("Property")
        if property_name:
            return str(property_name)
    name = str(select.get("Name") or "")
    if "." in name and not name.startswith(("Min(", "Sum(")):
        return name.rsplit(".", 1)[-1]
    return name or None


def _row_from_mapping(row: dict[str, Any], source_file: str) -> ReportPoEtrRow:
    event_number = _text(_first(row, "event_number", "EVENT_ID", "EventID", "ETR_OU.EVENT_ID"))
    event_type = _optional_text(
        _first(
            row,
            "event_type",
            "EVENT_TYPE2",
            "EVENT_TYPE",
            "ETR_OU.EVENT_TYPE2",
            "ETR_OU.EVENT_TYPE",
            "Group",
            "ETR_OU.Group",
        )
    )
    event_status = _optional_text(
        _first(
            row,
            "event_status",
            "EVENT_STATUS2",
            "EVENT_STATUS",
            "ETR_OU.EVENT_STATUS2",
            "ETR_OU.EVENT_STATUS",
            "Description2",
            "ETRtype.Description2",
        )
    )
    explicit_work_type = _optional_text(
        _first(row, "work_type", "WORK_TYPE", "JOB_TYPE", "WorkType", "JobType", "ETR_OU.WORK_TYPE")
    )
    return ReportPoEtrRow(
        event_number=event_number,
        event_start_time=_parse_datetime(_first(row, "event_start_time", "EVENT_START_TIME", "ETR_OU.EVENT_START_TIME")),
        event_create_time=_parse_datetime(_first(row, "event_create_time", "EVENT_CREATE_TIME", "ETR_OU.EVENT_CREATE_TIME")),
        first_restore_time=_parse_datetime(_first(row, "first_restore_time", "FIRST_RESTORE_TIME", "ETR_OU.FIRST_RESTORE_TIME")),
        event_etr_time=_parse_datetime(_first(row, "event_etr_time", "EVENT_ETR_TIME", "ETR_OU.EVENT_ETR_TIME")),
        event_end_time=_parse_datetime(_first(row, "event_end_time", "EVENT_END_TIME", "ETR_OU.EVENT_END_TIME")),
        etr_first_time=_parse_datetime(_first(row, "etr_first_time", "ETR_FIRST_TIME", "ETR_OU.ETR_FIRST_TIME")),
        ip_datetime=_parse_datetime(_first(row, "ip_datetime", "IPdateTime", "IP_DATETIME", "ETR_OU.IPdateTime")),
        device_id=normalize_device_id(_first(row, "device_id", "DEVICE_NAME", "ETR_OU.DEVICE_NAME")),
        office=_optional_text(_first(row, "office", "OfficeName", "ETR_OU.OfficeName")),
        area=_optional_text(_first(row, "area", "AreaName", "ETR_OU.AreaName")),
        event_type=event_type,
        event_status=event_status,
        etr_type=_optional_text(_first(row, "etr_type", "ETRType", "ETR_TYPE", "ETR_OU.ETRType", "Min(ETR_OU.ETRType)")),
        etr_type_description=_optional_text(
            _first(row, "etr_type_description", "Description1", "ETRtype.Description1", "ETR_TYPE_DESCRIPTION")
        ),
        cause_group=_optional_text(
            _first(row, "cause_group", "CAUSE_GROUP", "CauseGroup", "CAUSE", "EVENT_CAUSE", "ETR_OU.CAUSE_GROUP")
        ),
        cause_code=_optional_text(
            _first(row, "cause_code", "CAUSE_CODE", "CauseCode", "ETR_OU.CAUSE_CODE")
        ),
        work_type=explicit_work_type or event_type,
        etr_send_count=_optional_int(_first(row, "etr_send_count", "ETR_SEND_COUNT", "Sum(ETR_OU.ETR_SEND_COUNT)")),
        source_file=source_file,
    )


def _load_imported_reportpo_csv(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            start = _parse_datetime(row.get("event_start_time"))
            rows.append(
                {
                    **row,
                    "device_norm": normalize_device_id(row.get("device_id")),
                    "feeder_norm": _normalize_reportpo_feeder(row.get("feeder") or row.get("device_id")),
                    "event_start_dt": start,
                    "actual_float": _optional_float(
                        row.get("reportpo_first_restore_minutes")
                        or row.get("actual_restoration_minutes")
                    ),
                }
            )
    return rows


def _runtime_webex_rows(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT
                webex_message_id,
                event_time,
                device_id,
                feeder
            FROM outage_events
            WHERE webex_message_id IS NOT NULL
            ORDER BY event_time, webex_message_id
        """
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def _match_one_runtime_event(
    runtime: dict[str, Any],
    reportpo_rows: list[dict[str, Any]],
    aliases: dict[str, str],
    max_window_minutes: float,
    ambiguity_delta_minutes: float,
) -> dict[str, Any]:
    webex_time = _parse_datetime(runtime.get("event_time"))
    webex_device = normalize_device_id(runtime.get("device_id"))
    webex_feeder = normalize_feeder(runtime.get("feeder") or runtime.get("device_id"))
    base = {
        "webex_message_id": runtime.get("webex_message_id") or "",
        "webex_event_time": _format_dt(webex_time),
        "webex_device_id": webex_device or "",
        "webex_feeder": webex_feeder or "",
        "candidate_event_number": "",
        "candidate_device_id": "",
        "candidate_event_start_time": "",
        "actual_restoration_minutes": "",
        "truth_target": REPORTPO_TRUTH_TARGET,
        "truth_definition": REPORTPO_TRUTH_DEFINITION,
        "delta_minutes": "",
        "candidate_count": 0,
        "match_status": "no_match",
        "match_reason": "no exact ReportPO device candidate in time window",
        "truth_quality": "",
    }
    if webex_time is None or webex_device is None:
        return {**base, "match_status": "no_match", "match_reason": "missing Webex event time or device"}

    exact_candidates = _rank_candidates(
        reportpo_rows,
        webex_time,
        max_window_minutes,
        lambda row: row.get("device_norm") == webex_device,
    )
    if exact_candidates:
        return _candidate_decision(base, exact_candidates, ambiguity_delta_minutes, "exact_device_time")

    alias_device = aliases.get(webex_device)
    if alias_device:
        alias_candidates = _rank_candidates(
            reportpo_rows,
            webex_time,
            max_window_minutes,
            lambda row: row.get("device_norm") == alias_device,
        )
        if alias_candidates:
            return _candidate_decision(
                base,
                alias_candidates,
                ambiguity_delta_minutes,
                f"approved_alias_time:{alias_device}",
            )

    feeder_candidates = _rank_candidates(
        reportpo_rows,
        webex_time,
        min(max_window_minutes, 360.0),
        lambda row: bool(webex_feeder and row.get("feeder_norm") == webex_feeder),
    )
    if feeder_candidates:
        decision = _candidate_snapshot(base, feeder_candidates[0], len(feeder_candidates))
        decision["match_status"] = "no_match"
        decision["match_reason"] = "feeder candidate only; not auto-filled"
        return decision
    if alias_device:
        return {**base, "match_reason": "approved alias has no candidate in time window"}
    return base


def _match_one_runtime_feature(
    runtime: dict[str, Any],
    reportpo_rows: list[dict[str, Any]],
    aliases: dict[str, str],
    max_window_minutes: float,
    ambiguity_delta_minutes: float,
) -> dict[str, Any]:
    webex_time = _parse_datetime(runtime.get("event_time"))
    webex_device = normalize_device_id(runtime.get("device_id"))
    webex_feeder = normalize_feeder(runtime.get("feeder") or runtime.get("device_id"))
    base = {
        "webex_message_id": runtime.get("webex_message_id") or "",
        "webex_event_time": _format_dt(webex_time),
        "webex_device_id": webex_device or "",
        "webex_feeder": webex_feeder or "",
        "event_number": "",
        "reportpo_device_id": "",
        "reportpo_event_start_time": "",
        "delta_minutes": "",
        "match_status": "no_match",
        "match_reason": "no exact ReportPO feature candidate in time window",
        "event_type": "",
        "event_status": "",
        "etr_type": "",
        "etr_type_description": "",
        "ip_datetime": "",
        "cause_group": "",
        "cause_code": "",
        "work_type": "",
        "job_status_at_notification": "not_dispatched_yet",
        "feature_quality": "",
        "feature_flags": "",
    }
    if webex_time is None or webex_device is None:
        return {**base, "match_reason": "missing Webex event time or device"}

    exact_candidates = _rank_candidates(
        reportpo_rows,
        webex_time,
        max_window_minutes,
        lambda row: row.get("device_norm") == webex_device,
    )
    if exact_candidates:
        return _feature_decision(base, exact_candidates, ambiguity_delta_minutes, "exact_device_time")

    alias_device = aliases.get(webex_device)
    if alias_device:
        alias_candidates = _rank_candidates(
            reportpo_rows,
            webex_time,
            max_window_minutes,
            lambda row: row.get("device_norm") == alias_device,
        )
        if alias_candidates:
            return _feature_decision(
                base,
                alias_candidates,
                ambiguity_delta_minutes,
                f"approved_alias_time:{alias_device}",
            )
        return {**base, "match_reason": "approved alias has no feature candidate in time window"}

    feeder_candidates = _rank_candidates(
        reportpo_rows,
        webex_time,
        min(max_window_minutes, 360.0),
        lambda row: bool(webex_feeder and row.get("feeder_norm") == webex_feeder),
    )
    if feeder_candidates:
        snapshot = _feature_snapshot(base, feeder_candidates[0], len(feeder_candidates))
        snapshot["match_status"] = "no_match"
        snapshot["match_reason"] = "feeder feature candidate only; not auto-filled"
        return snapshot
    return base


def _feature_decision(
    base: dict[str, Any],
    candidates: list[tuple[float, dict[str, Any]]],
    ambiguity_delta_minutes: float,
    reason: str,
) -> dict[str, Any]:
    best_delta, best = candidates[0]
    decision = _feature_snapshot(base, candidates[0], len(candidates))
    if len(candidates) > 1:
        second_delta, second = candidates[1]
        if second.get("event_number") != best.get("event_number") and second_delta - best_delta <= ambiguity_delta_minutes:
            decision["match_status"] = "ambiguous"
            decision["match_reason"] = f"multiple feature candidates within {ambiguity_delta_minutes:g} minutes"
            return decision
    decision["match_status"] = "matched"
    decision["match_reason"] = reason
    decision["delta_minutes"] = best_delta
    return decision


def _feature_snapshot(
    base: dict[str, Any],
    candidate: tuple[float, dict[str, Any]],
    _candidate_count: int,
) -> dict[str, Any]:
    delta, row = candidate
    return {
        **base,
        "event_number": row.get("event_number") or "",
        "reportpo_device_id": row.get("device_id") or "",
        "reportpo_event_start_time": row.get("event_start_time") or "",
        "delta_minutes": delta,
        "event_type": row.get("event_type") or "",
        "event_status": row.get("event_status") or "",
        "etr_type": row.get("etr_type") or "",
        "etr_type_description": row.get("etr_type_description") or "",
        "ip_datetime": row.get("ip_datetime") or "",
        "cause_group": row.get("cause_group") or "",
        "cause_code": row.get("cause_code") or "",
        "work_type": row.get("work_type") or "",
        "job_status_at_notification": row.get("job_status_at_notification") or "not_dispatched_yet",
        "feature_quality": row.get("feature_quality") or "",
        "feature_flags": row.get("feature_flags") or "",
    }


def _candidate_rows_for_runtime(
    runtime: dict[str, Any],
    reportpo_rows: list[dict[str, Any]],
    aliases: dict[str, str],
    max_window_minutes: float,
    limit: int,
    reason: str,
) -> list[dict[str, Any]]:
    webex_time = _parse_datetime(runtime.get("event_time"))
    webex_device = normalize_device_id(runtime.get("device_id"))
    webex_feeder = normalize_feeder(runtime.get("feeder") or runtime.get("device_id"))
    if webex_time is None or webex_device is None:
        return []

    ranked: list[tuple[str, float, dict[str, Any]]] = []
    exact = _rank_candidates(
        reportpo_rows,
        webex_time,
        max_window_minutes,
        lambda row: row.get("device_norm") == webex_device,
    )
    ranked.extend(("exact", delta, row) for delta, row in exact[:limit])

    alias_device = aliases.get(webex_device)
    if alias_device:
        alias = _rank_candidates(
            reportpo_rows,
            webex_time,
            max_window_minutes,
            lambda row: row.get("device_norm") == alias_device,
        )
        ranked.extend(("alias", delta, row) for delta, row in alias[:limit])

    feeder = _rank_candidates(
        reportpo_rows,
        webex_time,
        min(max_window_minutes, 360.0),
        lambda row: bool(webex_feeder and row.get("feeder_norm") == webex_feeder),
    )
    ranked.extend(("feeder", delta, row) for delta, row in feeder[:limit])

    if not ranked:
        nearby = _rank_candidates(
            reportpo_rows,
            webex_time,
            60.0,
            lambda _row: True,
        )
        ranked.extend(("nearby_time", delta, row) for delta, row in nearby[:limit])

    output = []
    seen: set[tuple[str, str, str]] = set()
    for match_level, delta, row in sorted(ranked, key=lambda item: (item[1], item[0]))[:limit]:
        key = (match_level, str(row.get("event_number") or ""), str(row.get("device_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "webex_message_id": runtime.get("webex_message_id") or "",
                "webex_device_id": webex_device,
                "webex_event_time": _format_dt(webex_time),
                "candidate_device_id": row.get("device_id") or "",
                "candidate_event_number": row.get("event_number") or "",
                "candidate_event_start_time": row.get("event_start_time") or "",
                "delta_minutes": delta,
                "match_level": match_level,
                "truth_quality": row.get("truth_quality") or "",
                "truth_target": row.get("truth_target") or REPORTPO_TRUTH_TARGET,
                "truth_definition": row.get("truth_definition") or REPORTPO_TRUTH_DEFINITION,
                "reason": reason,
            }
        )
    return output


def _rank_candidates(
    rows: list[dict[str, Any]],
    webex_time: datetime,
    max_window_minutes: float,
    predicate,
) -> list[tuple[float, dict[str, Any]]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        start = row.get("event_start_dt")
        if start is None or not predicate(row):
            continue
        delta = abs((start - webex_time).total_seconds() / 60)
        if delta <= max_window_minutes:
            candidates.append((round(delta, 3), row))
    return sorted(candidates, key=lambda item: (item[0], str(item[1].get("event_number") or "")))


def _candidate_decision(
    base: dict[str, Any],
    candidates: list[tuple[float, dict[str, Any]]],
    ambiguity_delta_minutes: float,
    reason: str,
) -> dict[str, Any]:
    best_delta, best = candidates[0]
    decision = _candidate_snapshot(base, candidates[0], len(candidates))
    if len(candidates) > 1:
        second_delta, second = candidates[1]
        if second.get("event_number") != best.get("event_number") and second_delta - best_delta <= ambiguity_delta_minutes:
            decision["match_status"] = "ambiguous"
            decision["match_reason"] = f"multiple exact candidates within {ambiguity_delta_minutes:g} minutes"
            return decision
    if best.get("actual_float") is None or str(best.get("truth_quality") or "").startswith(("MISSING", "INVALID")):
        decision["match_status"] = "invalid_truth"
        decision["match_reason"] = f"{reason}; candidate has no usable actual restoration"
        return decision
    decision["match_status"] = "matched"
    decision["match_reason"] = reason
    decision["delta_minutes"] = best_delta
    return decision


def _candidate_snapshot(
    base: dict[str, Any],
    candidate: tuple[float, dict[str, Any]],
    candidate_count: int,
) -> dict[str, Any]:
    delta, row = candidate
    return {
        **base,
        "candidate_event_number": row.get("event_number") or "",
        "candidate_device_id": row.get("device_id") or "",
        "candidate_event_start_time": row.get("event_start_time") or "",
        "actual_restoration_minutes": "" if row.get("actual_float") is None else row.get("actual_float"),
        "truth_target": row.get("truth_target") or REPORTPO_TRUTH_TARGET,
        "truth_definition": row.get("truth_definition") or REPORTPO_TRUTH_DEFINITION,
        "delta_minutes": delta,
        "candidate_count": candidate_count,
        "truth_quality": row.get("truth_quality") or "",
    }


def _load_or_create_mapping(mapping_path: str | Path, runtime_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    path = Path(mapping_path)
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append({column: (row.get(column) or "") for column in TRUTH_MAPPING_COLUMNS})
    existing = {row["webex_message_id"] for row in rows}
    for row in runtime_rows:
        message_id = row.get("webex_message_id") or ""
        if message_id and message_id not in existing:
            rows.append({column: "" for column in TRUTH_MAPPING_COLUMNS} | {"webex_message_id": message_id})
            existing.add(message_id)
    return rows


def _write_mapping(mapping_path: str | Path, rows: list[dict[str, str]]) -> None:
    output = Path(mapping_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRUTH_MAPPING_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _write_audit(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_MATCH_AUDIT_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REPORTPO_MATCH_AUDIT_COLUMNS} for row in rows)


def _write_candidates(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_CANDIDATE_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REPORTPO_CANDIDATE_COLUMNS} for row in rows)


def _write_feature_join(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_FEATURE_JOIN_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REPORTPO_FEATURE_JOIN_COLUMNS} for row in rows)


def _load_approved_aliases(alias_file: str | Path | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for row in _load_alias_rows(alias_file):
        if str(row.get("status") or "").strip().lower() != "approved":
            continue
        webex_device = normalize_device_id(row.get("webex_device_id"))
        reportpo_device = normalize_device_id(row.get("reportpo_device_id"))
        if not webex_device or not reportpo_device:
            continue
        previous = aliases.get(webex_device)
        if previous and previous != reportpo_device:
            raise ValueError(f"duplicate approved ReportPO alias for {webex_device}: {previous} and {reportpo_device}")
        aliases[webex_device] = reportpo_device
    return aliases


def _load_alias_rows(alias_file: str | Path | None) -> list[dict[str, str]]:
    if not alias_file:
        return []
    path = Path(alias_file)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {column: (row.get(column) or "").strip() for column in REPORTPO_ALIAS_COLUMNS}
            for row in reader
        ]


def _load_candidate_rows(candidates_csv: str | Path) -> list[dict[str, str]]:
    path = Path(candidates_csv)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {column: (row.get(column) or "").strip() for column in REPORTPO_CANDIDATE_COLUMNS}
            for row in reader
        ]


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            value = row.get(key)
            if _has_value(value):
                return value
    lower_map = {str(key).strip().lower(): key for key in row.keys()}
    for key in keys:
        original = lower_map.get(key.lower())
        if original is not None:
            value = row.get(original)
            if _has_value(value):
                return value
    return None


def _normalize_reportpo_feeder(value: Any) -> str | None:
    normalized = normalize_feeder(value)
    if normalized:
        return normalized
    device = normalize_device_id(value)
    if not device:
        return None
    match = re.match(r"([A-Z]{3}\d{2})", device)
    return match.group(1) if match else None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, datetime):
        return True
    return str(value).strip().lower() not in _EMPTY_VALUES


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(_decode_powerbi_literal(value)).strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _optional_text(value: Any) -> str | None:
    if not _has_value(value):
        return None
    return _text(value)


def _optional_int(value: Any) -> int | None:
    if not _has_value(value):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    if not _has_value(value):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not _has_value(value):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).replace(tzinfo=None)
    text = str(_decode_powerbi_literal(value)).strip().replace("T", " ")
    text = re.sub(r"Z$", "", text)
    if "." in text:
        head, tail = text.split(".", 1)
        digits = re.match(r"\d+", tail)
        if digits:
            text = head + "." + digits.group(0)[:6]
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_dt(value: datetime | None) -> str:
    return value.isoformat(sep=" ") if value else ""


def _top_counts(counts: dict[str, int], limit: int = 12) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])
