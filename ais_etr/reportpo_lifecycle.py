from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .reportpo_etr import (
    DEFAULT_REPORTPO_QUERYDATA_URL,
    _count_response_rows,
    _decode_powerbi_rows,
    _extract_restart_tokens,
    _find_powerbi_errors,
    _format_dt,
    _iter_powerbi_data_objects,
    _load_approved_aliases,
    _normalize_reportpo_feeder,
    _page_path,
    _parse_datetime,
    _run_curl_query,
    _runtime_webex_rows,
)
from .utils import normalize_device_id, normalize_feeder


REPORTPO_LIFECYCLE_COLUMNS = (
    "event_number",
    "op_device_id",
    "op_device_type",
    "op_device_gis_tag",
    "feeder",
    "office",
    "area",
    "main_office",
    "branch",
    "cr_datetime",
    "ap_datetime",
    "no_datetime",
    "ip_datetime",
    "last_restore_datetime",
    "cl_datetime",
    "start_sched_datetime",
    "end_sched_datetime",
    "date_diff",
    "workingday",
    "notified",
    "notify_in_time",
    "notify_status",
    "is_transformer",
    "group_device_type",
    "voltage_level",
    "std_workingday",
    "std_result",
    "payload_timestamp",
    "lifecycle_quality",
    "lifecycle_flags",
    "source_file",
)

REPORTPO_LIFECYCLE_JOIN_COLUMNS = (
    "webex_message_id",
    "webex_event_time",
    "webex_device_id",
    "webex_feeder",
    "event_number",
    "po_device_id",
    "po_match_time",
    "delta_minutes",
    "match_status",
    "match_reason",
    "cr_datetime",
    "no_datetime",
    "ip_datetime",
    "last_restore_datetime",
    "cl_datetime",
    "job_status_at_notification",
    "minutes_cr_to_ip",
    "minutes_ip_to_restore",
    "lifecycle_quality",
    "lifecycle_flags",
    "op_device_type",
    "group_device_type",
    "voltage_level",
    "notify_status",
    "notified",
    "notify_in_time",
)

PO_SELECTS = (
    "EventID",
    "OpDeviceID",
    "OpDeviceType",
    "OpDeviceGIStag",
    "OfficeName",
    "AreaName",
    "MainName",
    "BranchName",
    "CRdateTime",
    "APdateTime",
    "NOdateTime",
    "IPdateTime",
    "LastRestoDateTime",
    "CLdateTime",
    "StartSchedDateTime",
    "EndSchedDateTime",
    "DateDiff",
    "Workingday",
    "Notified",
    "NotifyInTime",
    "NotifyStatus",
    "IsTransformer",
    "groupdevicetype",
    "voltagelevel",
    "STDworkingday",
    "STDresult",
    "PayloadTimestamp",
)


def build_reportpo_lifecycle_query(
    template: str | Path,
    count: int = 100000,
    restart_tokens: list[list[Any]] | None = None,
) -> dict[str, Any]:
    model_id, locale = _load_model_context(template)
    select = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "p"}},
                "Property": property_name,
            },
            "Name": f"PO.{property_name}",
            "NativeReferenceName": property_name,
        }
        for property_name in PO_SELECTS
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
                                    "From": [{"Name": "p", "Entity": "PO", "Type": 0}],
                                    "Select": select,
                                    "OrderBy": [
                                        {
                                            "Direction": 2,
                                            "Expression": {
                                                "Column": {
                                                    "Expression": {"SourceRef": {"Source": "p"}},
                                                    "Property": "IPdateTime",
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
                "ApplicationContext": {"Sources": [{"VisualId": "ais-etr-po-lifecycle"}]},
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
        "userPreferredLocale": locale,
    }


def fetch_reportpo_lifecycle_querydata(
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
        request = build_reportpo_lifecycle_query(template, count=count, restart_tokens=restart_tokens)
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
            raise RuntimeError("ReportPO lifecycle querydata returned semantic error: " + "; ".join(errors[:3]))
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


def import_reportpo_lifecycle(source: str | Path, output_csv: str | Path) -> dict[str, Any]:
    rows = load_reportpo_lifecycle(source)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_LIFECYCLE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    quality_counts: dict[str, int] = {}
    restore_rows = 0
    ip_rows = 0
    for row in rows:
        quality = str(row.get("lifecycle_quality") or "")
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        if row.get("last_restore_datetime"):
            restore_rows += 1
        if row.get("ip_datetime"):
            ip_rows += 1
    return {
        "source": str(source),
        "output_csv": str(output),
        "rows": len(rows),
        "with_ip_datetime": ip_rows,
        "with_last_restore_datetime": restore_rows,
        "lifecycle_quality": dict(sorted(quality_counts.items())),
    }


def load_reportpo_lifecycle(source: str | Path) -> list[dict[str, str]]:
    path = Path(source)
    if path.suffix.lower() == ".csv":
        return list(_load_lifecycle_csv(path))
    if path.suffix.lower() == ".json":
        return list(_load_lifecycle_querydata_json(path))
    raise ValueError(f"unsupported ReportPO lifecycle source type: {path.suffix}")


def join_reportpo_lifecycle_to_shadow(
    db_path: str | Path,
    lifecycle_csv: str | Path,
    output_csv: str | Path,
    alias_file: str | Path | None = None,
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
) -> dict[str, Any]:
    runtime_rows = _runtime_webex_rows(db_path)
    lifecycle_rows = _load_imported_lifecycle_csv(lifecycle_csv)
    aliases = _load_approved_aliases(alias_file)

    output_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    quality_counts: dict[str, int] = {}
    candidate_job_status_counts: dict[str, int] = {}
    matched_job_status_counts: dict[str, int] = {}
    for runtime in runtime_rows:
        decision = _match_one_runtime_lifecycle(
            runtime,
            lifecycle_rows,
            aliases,
            max_window_minutes=max_window_minutes,
            ambiguity_delta_minutes=ambiguity_delta_minutes,
        )
        output_rows.append(decision)
        status = str(decision.get("match_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        quality = str(decision.get("lifecycle_quality") or "")
        if quality:
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
        job_status = str(decision.get("job_status_at_notification") or "")
        if job_status:
            candidate_job_status_counts[job_status] = candidate_job_status_counts.get(job_status, 0) + 1
            if status == "matched":
                matched_job_status_counts[job_status] = matched_job_status_counts.get(job_status, 0) + 1

    _write_lifecycle_join(output_csv, output_rows)
    return {
        "db_path": str(db_path),
        "lifecycle_csv": str(lifecycle_csv),
        "output_csv": str(output_csv),
        "alias_file": str(alias_file) if alias_file else None,
        "runtime_events": len(runtime_rows),
        "lifecycle_rows": len(lifecycle_rows),
        "match_status": dict(sorted(status_counts.items())),
        "lifecycle_quality": dict(sorted(quality_counts.items())),
        "matched_job_status_at_notification": dict(sorted(matched_job_status_counts.items())),
        "candidate_job_status_at_notification": dict(sorted(candidate_job_status_counts.items())),
        "matched_rows": status_counts.get("matched", 0),
    }


def _load_model_context(template: str | Path) -> tuple[str, str]:
    path = Path(template)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or not item.get("request"):
                continue
            try:
                request = json.loads(item["request"]) if isinstance(item["request"], str) else item["request"]
            except (TypeError, json.JSONDecodeError):
                continue
            model_id = str(request.get("modelId") or "")
            if model_id:
                return model_id, str(request.get("userPreferredLocale") or "en-US")
    if isinstance(payload, dict):
        model_id = str(payload.get("modelId") or "")
        if model_id:
            return model_id, str(payload.get("userPreferredLocale") or "en-US")
    return "205564749", "en-US"


def _load_lifecycle_querydata_json(path: Path) -> Iterator[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = _find_powerbi_errors(payload)
    if errors:
        raise ValueError("ReportPO lifecycle querydata contains semantic error: " + "; ".join(errors[:3]))
    for data in _iter_powerbi_data_objects(payload):
        select = data.get("descriptor", {}).get("Select") or []
        if not _looks_like_lifecycle_select(select):
            continue
        for raw in _decode_powerbi_rows(data):
            yield _lifecycle_row_from_mapping(raw, str(path))


def _load_lifecycle_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield _lifecycle_row_from_mapping(row, str(path))


def _looks_like_lifecycle_select(select: list[dict[str, Any]]) -> bool:
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
    return {"EventID", "OpDeviceID", "IPdateTime"}.issubset(properties)


def _lifecycle_row_from_mapping(row: dict[str, Any], source_file: str) -> dict[str, str]:
    cr_dt = _parse_datetime(_first(row, "cr_datetime", "CRdateTime", "PO.CRdateTime"))
    ip_dt = _parse_datetime(_first(row, "ip_datetime", "IPdateTime", "PO.IPdateTime"))
    restore_dt = _parse_datetime(_first(row, "last_restore_datetime", "LastRestoDateTime", "PO.LastRestoDateTime"))
    cl_dt = _parse_datetime(_first(row, "cl_datetime", "CLdateTime", "PO.CLdateTime"))
    device_id = normalize_device_id(_first(row, "op_device_id", "OpDeviceID", "PO.OpDeviceID"))
    output = {
        "event_number": _text(_first(row, "event_number", "EventID", "PO.EventID")),
        "op_device_id": device_id or "",
        "op_device_type": _text(_first(row, "op_device_type", "OpDeviceType", "PO.OpDeviceType")),
        "op_device_gis_tag": _text(_first(row, "op_device_gis_tag", "OpDeviceGIStag", "PO.OpDeviceGIStag")),
        "feeder": _normalize_reportpo_feeder(device_id) or "",
        "office": _text(_first(row, "office", "OfficeName", "PO.OfficeName")),
        "area": _text(_first(row, "area", "AreaName", "PO.AreaName")),
        "main_office": _text(_first(row, "main_office", "MainName", "PO.MainName")),
        "branch": _text(_first(row, "branch", "BranchName", "PO.BranchName")),
        "cr_datetime": _format_dt(cr_dt),
        "ap_datetime": _format_dt(_parse_datetime(_first(row, "ap_datetime", "APdateTime", "PO.APdateTime"))),
        "no_datetime": _format_dt(_parse_datetime(_first(row, "no_datetime", "NOdateTime", "PO.NOdateTime"))),
        "ip_datetime": _format_dt(ip_dt),
        "last_restore_datetime": _format_dt(restore_dt),
        "cl_datetime": _format_dt(cl_dt),
        "start_sched_datetime": _format_dt(
            _parse_datetime(_first(row, "start_sched_datetime", "StartSchedDateTime", "PO.StartSchedDateTime"))
        ),
        "end_sched_datetime": _format_dt(
            _parse_datetime(_first(row, "end_sched_datetime", "EndSchedDateTime", "PO.EndSchedDateTime"))
        ),
        "date_diff": _text(_first(row, "date_diff", "DateDiff", "PO.DateDiff")),
        "workingday": _text(_first(row, "workingday", "Workingday", "PO.Workingday")),
        "notified": _text(_first(row, "notified", "Notified", "PO.Notified")),
        "notify_in_time": _text(_first(row, "notify_in_time", "NotifyInTime", "PO.NotifyInTime")),
        "notify_status": _text(_first(row, "notify_status", "NotifyStatus", "PO.NotifyStatus")),
        "is_transformer": _text(_first(row, "is_transformer", "IsTransformer", "PO.IsTransformer")),
        "group_device_type": _text(_first(row, "group_device_type", "groupdevicetype", "PO.groupdevicetype")),
        "voltage_level": _text(_first(row, "voltage_level", "voltagelevel", "PO.voltagelevel")),
        "std_workingday": _text(_first(row, "std_workingday", "STDworkingday", "PO.STDworkingday")),
        "std_result": _text(_first(row, "std_result", "STDresult", "PO.STDresult")),
        "payload_timestamp": _format_dt(
            _parse_datetime(_first(row, "payload_timestamp", "PayloadTimestamp", "PO.PayloadTimestamp"))
        ),
        "source_file": source_file,
    }
    quality, flags = _lifecycle_quality_flags(output)
    output["lifecycle_quality"] = quality
    output["lifecycle_flags"] = flags
    return output


def _load_imported_lifecycle_csv(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            match_times = [
                _parse_datetime(row.get("ip_datetime")),
                _parse_datetime(row.get("no_datetime")),
                _parse_datetime(row.get("cr_datetime")),
            ]
            rows.append(
                {
                    **row,
                    "device_norm": normalize_device_id(row.get("op_device_id")),
                    "feeder_norm": _normalize_reportpo_feeder(row.get("feeder") or row.get("op_device_id")),
                    "match_times": [value for value in match_times if value is not None],
                    "cr_dt": _parse_datetime(row.get("cr_datetime")),
                    "no_dt": _parse_datetime(row.get("no_datetime")),
                    "ip_dt": _parse_datetime(row.get("ip_datetime")),
                    "restore_dt": _parse_datetime(row.get("last_restore_datetime")),
                    "cl_dt": _parse_datetime(row.get("cl_datetime")),
                }
            )
    return rows


def _match_one_runtime_lifecycle(
    runtime: dict[str, Any],
    lifecycle_rows: list[dict[str, Any]],
    aliases: dict[str, str],
    max_window_minutes: float,
    ambiguity_delta_minutes: float,
) -> dict[str, Any]:
    webex_time = _parse_datetime(runtime.get("event_time"))
    webex_device = normalize_device_id(runtime.get("device_id"))
    webex_feeder = normalize_feeder(runtime.get("feeder")) or _normalize_reportpo_feeder(runtime.get("device_id"))
    base = {
        "webex_message_id": runtime.get("webex_message_id") or "",
        "webex_event_time": _format_dt(webex_time),
        "webex_device_id": webex_device or "",
        "webex_feeder": webex_feeder or "",
        "event_number": "",
        "po_device_id": "",
        "po_match_time": "",
        "delta_minutes": "",
        "match_status": "no_match",
        "match_reason": "no exact ReportPO PO lifecycle candidate in time window",
        "cr_datetime": "",
        "no_datetime": "",
        "ip_datetime": "",
        "last_restore_datetime": "",
        "cl_datetime": "",
        "job_status_at_notification": "",
        "minutes_cr_to_ip": "",
        "minutes_ip_to_restore": "",
        "lifecycle_quality": "",
        "lifecycle_flags": "",
        "op_device_type": "",
        "group_device_type": "",
        "voltage_level": "",
        "notify_status": "",
        "notified": "",
        "notify_in_time": "",
    }
    if webex_time is None or webex_device is None:
        return {**base, "match_reason": "missing Webex event time or device"}

    exact = _rank_lifecycle_candidates(
        lifecycle_rows,
        webex_time,
        max_window_minutes,
        lambda row: row.get("device_norm") == webex_device,
    )
    if exact:
        return _lifecycle_decision(base, exact, webex_time, ambiguity_delta_minutes, "exact_device_time")

    alias_device = aliases.get(webex_device)
    if alias_device:
        alias = _rank_lifecycle_candidates(
            lifecycle_rows,
            webex_time,
            max_window_minutes,
            lambda row: row.get("device_norm") == alias_device,
        )
        if alias:
            return _lifecycle_decision(
                base,
                alias,
                webex_time,
                ambiguity_delta_minutes,
                f"approved_alias_time:{alias_device}",
            )
        return {**base, "match_reason": "approved alias has no PO lifecycle candidate in time window"}

    feeder = _rank_lifecycle_candidates(
        lifecycle_rows,
        webex_time,
        min(max_window_minutes, 360.0),
        lambda row: bool(webex_feeder and row.get("feeder_norm") == webex_feeder),
    )
    if feeder:
        snapshot = _lifecycle_snapshot(base, feeder[0], webex_time, len(feeder))
        snapshot["match_status"] = "no_match"
        snapshot["match_reason"] = "feeder PO lifecycle candidate only; not auto-filled"
        return snapshot
    return base


def _rank_lifecycle_candidates(
    rows: list[dict[str, Any]],
    webex_time: datetime,
    max_window_minutes: float,
    predicate,
) -> list[tuple[float, datetime, dict[str, Any]]]:
    candidates: list[tuple[float, datetime, dict[str, Any]]] = []
    for row in rows:
        if not predicate(row):
            continue
        best: tuple[float, datetime] | None = None
        for match_time in row.get("match_times") or []:
            delta = abs((match_time - webex_time).total_seconds() / 60)
            if delta <= max_window_minutes and (best is None or delta < best[0]):
                best = (round(delta, 3), match_time)
        if best:
            candidates.append((best[0], best[1], row))
    return sorted(candidates, key=lambda item: (item[0], str(item[2].get("event_number") or "")))


def _lifecycle_decision(
    base: dict[str, Any],
    candidates: list[tuple[float, datetime, dict[str, Any]]],
    webex_time: datetime,
    ambiguity_delta_minutes: float,
    reason: str,
) -> dict[str, Any]:
    best_delta, _best_time, best = candidates[0]
    decision = _lifecycle_snapshot(base, candidates[0], webex_time, len(candidates))
    if len(candidates) > 1:
        second_delta, _second_time, second = candidates[1]
        if second.get("event_number") != best.get("event_number") and second_delta - best_delta <= ambiguity_delta_minutes:
            decision["match_status"] = "ambiguous"
            decision["match_reason"] = f"multiple PO lifecycle candidates within {ambiguity_delta_minutes:g} minutes"
            return decision
    decision["match_status"] = "matched"
    decision["match_reason"] = reason
    return decision


def _lifecycle_snapshot(
    base: dict[str, Any],
    candidate: tuple[float, datetime, dict[str, Any]],
    webex_time: datetime,
    _candidate_count: int,
) -> dict[str, Any]:
    delta, match_time, row = candidate
    return {
        **base,
        "event_number": row.get("event_number") or "",
        "po_device_id": row.get("op_device_id") or "",
        "po_match_time": _format_dt(match_time),
        "delta_minutes": delta,
        "cr_datetime": row.get("cr_datetime") or "",
        "no_datetime": row.get("no_datetime") or "",
        "ip_datetime": row.get("ip_datetime") or "",
        "last_restore_datetime": row.get("last_restore_datetime") or "",
        "cl_datetime": row.get("cl_datetime") or "",
        "job_status_at_notification": _job_status_at(row, webex_time),
        "minutes_cr_to_ip": _duration_minutes(row.get("cr_dt"), row.get("ip_dt")),
        "minutes_ip_to_restore": _duration_minutes(row.get("ip_dt"), row.get("restore_dt")),
        "lifecycle_quality": row.get("lifecycle_quality") or "",
        "lifecycle_flags": row.get("lifecycle_flags") or "",
        "op_device_type": row.get("op_device_type") or "",
        "group_device_type": row.get("group_device_type") or "",
        "voltage_level": row.get("voltage_level") or "",
        "notify_status": row.get("notify_status") or "",
        "notified": row.get("notified") or "",
        "notify_in_time": row.get("notify_in_time") or "",
    }


def _job_status_at(row: dict[str, Any], when: datetime) -> str:
    cr_dt = row.get("cr_dt")
    no_dt = row.get("no_dt")
    ip_dt = row.get("ip_dt")
    restore_dt = row.get("restore_dt")
    cl_dt = row.get("cl_dt")
    if cr_dt and when < cr_dt:
        return "before_cr"
    if cl_dt and when >= cl_dt:
        return "closed"
    if restore_dt and when >= restore_dt:
        return "restored_not_closed"
    if ip_dt and when >= ip_dt:
        return "in_progress"
    if no_dt and when >= no_dt:
        return "notified_before_ip"
    if cr_dt and when >= cr_dt:
        return "created_before_no"
    return "unknown"


def _lifecycle_quality_flags(row: dict[str, str]) -> tuple[str, str]:
    flags: list[str] = []
    if not row.get("ip_datetime"):
        flags.append("ip_datetime_missing")
    if not row.get("last_restore_datetime"):
        flags.append("last_restore_missing")
    cr_dt = _parse_datetime(row.get("cr_datetime"))
    ip_dt = _parse_datetime(row.get("ip_datetime"))
    restore_dt = _parse_datetime(row.get("last_restore_datetime"))
    cl_dt = _parse_datetime(row.get("cl_datetime"))
    if cr_dt and ip_dt and ip_dt < cr_dt:
        flags.append("ip_before_cr")
    if ip_dt and restore_dt and restore_dt < ip_dt:
        flags.append("restore_before_ip")
    if restore_dt and cl_dt and cl_dt < restore_dt:
        flags.append("close_before_restore")
    if any(flag.endswith("_before_cr") or flag.startswith(("restore_before", "close_before")) for flag in flags):
        return "invalid_sequence", ";".join(flags)
    if row.get("ip_datetime") and row.get("last_restore_datetime"):
        return "restore_available", ";".join(flags)
    if row.get("ip_datetime"):
        return "lifecycle_only", ";".join(flags)
    return "missing_lifecycle_time", ";".join(flags)


def _write_lifecycle_join(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_LIFECYCLE_JOIN_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in REPORTPO_LIFECYCLE_JOIN_COLUMNS} for row in rows)


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


def _duration_minutes(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return ""
    return str(round((end - start).total_seconds() / 60, 2))
