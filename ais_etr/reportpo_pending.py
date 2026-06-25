from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator

from .reportpo_etr import (
    DEFAULT_REPORTPO_QUERYDATA_URL,
    _count_response_rows,
    _decode_powerbi_rows,
    _extract_restart_tokens,
    _find_powerbi_errors,
    _iter_powerbi_data_objects,
    _normalize_reportpo_feeder,
    _page_path,
    _run_curl_query,
    _runtime_webex_rows,
)
from .reportpo_lifecycle import _load_model_context
from .utils import normalize_device_id


PENDING_COLUMNS = (
    "event_number",
    "device_id",
    "feeder",
    "yyyy",
    "yyyy_mm",
    "office",
    "area",
    "region",
    "region2",
    "event_type",
    "event_status",
    "event_type2",
    "event_status2",
    "source_file",
)

PENDING_OVERLAP_COLUMNS = (
    "pending_event_number",
    "pending_device_id",
    "pending_feeder",
    "yyyy",
    "yyyy_mm",
    "event_type",
    "event_status",
    "event_type2",
    "event_status2",
    "overlap_status",
    "webex_message_id",
    "webex_device_id",
    "feature_match_status",
    "match_note",
)

PENDING_SELECTS = (
    "EVENT_ID",
    "DEVICE_NAME",
    "YYYY",
    "YYYY_MM",
    "OfficeName",
    "AreaName",
    "REGION",
    "Region2",
    "EVENT_TYPE",
    "EVENT_STATUS",
    "EVENT_TYPE2",
    "EVENT_STATUS2",
)


def build_reportpo_pending_query(
    template: str | Path,
    count: int = 30000,
    restart_tokens: list[list[Any]] | None = None,
) -> dict[str, Any]:
    model_id, locale = _load_model_context(template)
    select = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "p"}},
                "Property": property_name,
            },
            "Name": f"Pending.{property_name}",
            "NativeReferenceName": property_name,
        }
        for property_name in PENDING_SELECTS
    ]
    window: dict[str, Any] = {"Count": int(count)}
    if restart_tokens:
        window["RestartTokens"] = restart_tokens
    return {
        "version": "1.0.0",
        "queries": [
            {
                "Query": {
                    "Commands": [
                        {
                            "SemanticQueryDataShapeCommand": {
                                "Query": {
                                    "Version": 2,
                                    "From": [{"Name": "p", "Entity": "Pending", "Type": 0}],
                                    "Select": select,
                                    "OrderBy": [
                                        {
                                            "Direction": 2,
                                            "Expression": {
                                                "Column": {
                                                    "Expression": {"SourceRef": {"Source": "p"}},
                                                    "Property": "YYYY_MM",
                                                }
                                            },
                                        }
                                    ],
                                },
                                "Binding": {
                                    "Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                                    "DataReduction": {
                                        "DataVolume": 3,
                                        "Primary": {"Window": window},
                                    },
                                    "Version": 1,
                                },
                                "ExecutionMetricsKind": 1,
                            }
                        }
                    ]
                },
                "QueryId": "",
                "ApplicationContext": {"Sources": [{"VisualId": "ais-etr-pending-probe"}]},
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
        "userPreferredLocale": locale,
    }


def fetch_reportpo_pending_querydata(
    template: str | Path,
    output_json: str | Path,
    request_output: str | Path | None = None,
    headers_output: str | Path | None = None,
    endpoint_url: str = DEFAULT_REPORTPO_QUERYDATA_URL,
    count: int = 30000,
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
        request = build_reportpo_pending_query(template, count=count, restart_tokens=restart_tokens)
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
            raise RuntimeError("ReportPO Pending querydata returned semantic error: " + "; ".join(errors[:3]))
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


def import_reportpo_pending(source: str | Path, output_csv: str | Path) -> dict[str, Any]:
    rows = load_reportpo_pending(source)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PENDING_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "source": str(source),
        "output_csv": str(output),
        "rows": len(rows),
        "with_event_number": sum(1 for row in rows if row.get("event_number")),
        "with_device": sum(1 for row in rows if row.get("device_id")),
        "with_status": sum(1 for row in rows if row.get("event_status") or row.get("event_status2")),
    }


def load_reportpo_pending(source: str | Path) -> list[dict[str, str]]:
    path = Path(source)
    if path.suffix.lower() == ".csv":
        return list(_load_pending_csv(path))
    if path.suffix.lower() == ".json":
        return list(_load_pending_querydata_json(path))
    raise ValueError(f"unsupported ReportPO Pending source type: {path.suffix}")


def audit_reportpo_pending_overlap(
    db_path: str | Path,
    pending_csv: str | Path,
    feature_audit_csv: str | Path,
    output_csv: str | Path,
) -> dict[str, Any]:
    pending_rows = _load_imported_pending_csv(pending_csv)
    feature_rows_by_event = _load_feature_rows_by_event(feature_audit_csv)
    webex_devices = {
        normalize_device_id(row.get("device_id"))
        for row in _runtime_webex_rows(db_path)
        if normalize_device_id(row.get("device_id"))
    }
    output_rows: list[dict[str, str]] = []
    overlap_counts: dict[str, int] = {}
    for pending in pending_rows:
        event_number = pending.get("event_number") or ""
        device = normalize_device_id(pending.get("device_id"))
        feature_rows = feature_rows_by_event.get(event_number, [])
        if feature_rows:
            for feature in feature_rows:
                output = _pending_overlap_row(
                    pending,
                    "event_number_overlap",
                    feature.get("webex_message_id") or "",
                    feature.get("webex_device_id") or "",
                    feature.get("match_status") or "",
                    "Pending EVENT_ID exists in ReportPO ETR feature join audit",
                )
                output_rows.append(output)
                overlap_counts[output["overlap_status"]] = overlap_counts.get(output["overlap_status"], 0) + 1
            continue
        if device and device in webex_devices:
            output = _pending_overlap_row(
                pending,
                "device_seen_in_webex_shadow",
                "",
                device,
                "",
                "Device appears in Webex shadow corpus but no event-number bridge is available",
            )
        else:
            output = _pending_overlap_row(
                pending,
                "no_overlap",
                "",
                "",
                "",
                "No event-number or device overlap with current shadow corpus",
            )
        output_rows.append(output)
        overlap_counts[output["overlap_status"]] = overlap_counts.get(output["overlap_status"], 0) + 1

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PENDING_OVERLAP_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in PENDING_OVERLAP_COLUMNS} for row in output_rows)
    return {
        "db_path": str(db_path),
        "pending_csv": str(pending_csv),
        "feature_audit_csv": str(feature_audit_csv),
        "output_csv": str(output),
        "pending_rows": len(pending_rows),
        "overlap_rows": len(output_rows),
        "overlap_status": dict(sorted(overlap_counts.items())),
    }


def _load_pending_querydata_json(path: Path) -> Iterator[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = _find_powerbi_errors(payload)
    if errors:
        raise ValueError("ReportPO Pending querydata contains semantic error: " + "; ".join(errors[:3]))
    for data in _iter_powerbi_data_objects(payload):
        select = data.get("descriptor", {}).get("Select") or []
        if not _looks_like_pending_select(select):
            continue
        for raw in _decode_powerbi_rows(data):
            yield _pending_row_from_mapping(raw, str(path))


def _load_pending_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield _pending_row_from_mapping(row, str(path))


def _looks_like_pending_select(select: list[dict[str, Any]]) -> bool:
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
    return {"EVENT_ID", "DEVICE_NAME"}.issubset(properties) and (
        "EVENT_STATUS" in properties or "EVENT_STATUS2" in properties
    )


def _pending_row_from_mapping(row: dict[str, Any], source_file: str) -> dict[str, str]:
    device_id = normalize_device_id(_first(row, "device_id", "DEVICE_NAME", "Pending.DEVICE_NAME"))
    return {
        "event_number": _text(_first(row, "event_number", "EVENT_ID", "Pending.EVENT_ID")),
        "device_id": device_id or "",
        "feeder": _normalize_reportpo_feeder(device_id) or "",
        "yyyy": _text(_first(row, "yyyy", "YYYY", "Pending.YYYY")),
        "yyyy_mm": _text(_first(row, "yyyy_mm", "YYYY_MM", "Pending.YYYY_MM")),
        "office": _text(_first(row, "office", "OfficeName", "Pending.OfficeName")),
        "area": _text(_first(row, "area", "AreaName", "Pending.AreaName")),
        "region": _text(_first(row, "region", "REGION", "Pending.REGION")),
        "region2": _text(_first(row, "region2", "Region2", "Pending.Region2")),
        "event_type": _text(_first(row, "event_type", "EVENT_TYPE", "Pending.EVENT_TYPE")),
        "event_status": _text(_first(row, "event_status", "EVENT_STATUS", "Pending.EVENT_STATUS")),
        "event_type2": _text(_first(row, "event_type2", "EVENT_TYPE2", "Pending.EVENT_TYPE2")),
        "event_status2": _text(_first(row, "event_status2", "EVENT_STATUS2", "Pending.EVENT_STATUS2")),
        "source_file": source_file,
    }


def _load_imported_pending_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [{column: row.get(column, "") for column in PENDING_COLUMNS} for row in csv.DictReader(handle)]


def _load_feature_rows_by_event(path: str | Path) -> dict[str, list[dict[str, str]]]:
    feature_path = Path(path)
    if not feature_path.exists():
        return {}
    output: dict[str, list[dict[str, str]]] = {}
    with feature_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            event_number = row.get("event_number") or ""
            if event_number:
                output.setdefault(event_number, []).append(row)
    return output


def _pending_overlap_row(
    pending: dict[str, str],
    overlap_status: str,
    webex_message_id: str,
    webex_device_id: str,
    feature_match_status: str,
    match_note: str,
) -> dict[str, str]:
    return {
        "pending_event_number": pending.get("event_number") or "",
        "pending_device_id": pending.get("device_id") or "",
        "pending_feeder": pending.get("feeder") or "",
        "yyyy": pending.get("yyyy") or "",
        "yyyy_mm": pending.get("yyyy_mm") or "",
        "event_type": pending.get("event_type") or "",
        "event_status": pending.get("event_status") or "",
        "event_type2": pending.get("event_type2") or "",
        "event_status2": pending.get("event_status2") or "",
        "overlap_status": overlap_status,
        "webex_message_id": webex_message_id,
        "webex_device_id": webex_device_id,
        "feature_match_status": feature_match_status,
        "match_note": match_note,
    }


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip().lower() not in {"", "nan", "none", "null", "nat"}:
            return value
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text
