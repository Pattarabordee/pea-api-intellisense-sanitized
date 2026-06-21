from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any, Iterable

from .reportpo_etr import (
    _count_response_rows,
    _decode_powerbi_rows,
    _extract_restart_tokens,
    _find_powerbi_errors,
    _format_dt,
    _iter_powerbi_data_objects,
    _page_path,
    _parse_datetime,
    _run_curl_query,
)
from .utils import normalize_device_id, normalize_feeder


DEFAULT_SFSD_REPORT_ID = "29200b27-195f-4b28-b702-5c0c45296473"
DEFAULT_SFSD_MODELS_URL = (
    f"https://powerbi-report.pea.co.th/powerbi/api/explore/reports/"
    f"{DEFAULT_SFSD_REPORT_ID}/modelsAndExploration?preferReadOnlySession=true"
)
DEFAULT_SFSD_QUERYDATA_URL = (
    f"https://powerbi-report.pea.co.th/powerbi/api/explore/reports/{DEFAULT_SFSD_REPORT_ID}/querydata"
)

SFSD_EVENT_COLUMNS = (
    "event_number",
    "event_type",
    "outage_time",
    "duration_minutes",
    "feeder",
    "gis_tag",
    "device_type",
    "device_id",
    "operation_status",
    "phase",
    "owner",
    "weather",
    "cause_found",
    "main_cause",
    "sub_cause",
    "pea_duration_class",
    "evidence_quality",
    "evidence_flags",
    "source_file",
)

SFSD_EVIDENCE_COLUMNS = (
    "priority_rank",
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "remaining_actual_minutes",
    "active_p50",
    "active_error_minutes",
    "sfsd_match_status",
    "sfsd_match_level",
    "sfsd_event_number",
    "sfsd_outage_time",
    "sfsd_delta_minutes",
    "sfsd_duration_minutes",
    "sfsd_feeder",
    "sfsd_device_id",
    "sfsd_gis_tag",
    "sfsd_device_type",
    "sfsd_operation_status",
    "sfsd_phase",
    "sfsd_weather",
    "sfsd_cause_found",
    "sfsd_main_cause",
    "sfsd_sub_cause",
    "sfsd_evidence_quality",
    "sfsd_evidence_flags",
    "sfsd_source_file",
    "bridge_event_number",
    "bridge_source",
    "pea_ais_pattern",
    "cause_status",
    "recommended_next_action",
)

SFSD_GAP_REVIEW_COLUMNS = (
    "review_rank",
    "priority_rank",
    "event_ref",
    "event_time",
    "feeder",
    "device_id",
    "remaining_actual_minutes",
    "active_error_minutes",
    "sfsd_match_status",
    "sfsd_match_level",
    "pea_ais_pattern",
    "sfsd_candidate_event_number",
    "sfsd_candidate_outage_time",
    "sfsd_candidate_delta_minutes",
    "sfsd_candidate_duration_minutes",
    "sfsd_candidate_feeder",
    "sfsd_candidate_device_id",
    "sfsd_candidate_quality",
    "gap_class",
    "review_priority",
    "recommended_owner_question",
    "recommended_next_action",
    "model_decision",
)

SFSD_GAP_RESOLUTION_COLUMNS = (
    "review_rank",
    "priority_rank",
    "event_ref",
    "event_time",
    "feeder",
    "webex_device_id",
    "sfsd_candidate_device_id",
    "gap_class",
    "review_priority",
    "webex_device_asset_count",
    "webex_device_match_level",
    "candidate_device_asset_count",
    "candidate_device_match_level",
    "overlap_asset_count",
    "feeder_asset_count",
    "topology_support",
    "nearest_same_device_event_number",
    "nearest_same_device_time",
    "nearest_same_device_delta_minutes",
    "nearest_same_device_duration_minutes",
    "nearest_same_device_quality",
    "nearest_same_feeder_event_number",
    "nearest_same_feeder_time",
    "nearest_same_feeder_device_id",
    "nearest_same_feeder_delta_minutes",
    "nearest_same_feeder_duration_minutes",
    "nearest_same_feeder_quality",
    "resolution_status",
    "recommended_next_action",
    "model_decision",
)

SFSD_SOURCE_TRACE_CANDIDATE_COLUMNS = (
    "priority_rank",
    "device_type",
    "device_id",
    "feeder",
    "event_count",
    "source_gap_status",
    "source_gap_role",
)

SFSD_GAP_DECISION_COLUMNS = (
    "review_rank",
    "priority_rank",
    "event_ref",
    "event_time",
    "feeder",
    "webex_device_id",
    "sfsd_candidate_device_id",
    "resolution_status",
    "source_webex_trace_result",
    "source_webex_ais_confident_hits",
    "source_candidate_trace_result",
    "source_candidate_ais_confident_hits",
    "nearest_same_device_delta_minutes",
    "nearest_same_feeder_delta_minutes",
    "final_decision",
    "final_action",
    "model_decision",
)

_EVENT_NUMBER_ALIASES = (
    "event_number",
    "eventnumber",
    "event_id",
    "eventid",
    "EVENT_ID",
    "EventNumber",
    "Event.EventNumber",
    "หมายเลขเหตุการณ์",
)
_EVENT_TYPE_ALIASES = ("event_type", "ประเภทเหตุการณ์", "EVENT_TYPE", "eventtype", "EventType", "Event.EventType")
_OUTAGE_TIME_ALIASES = (
    "outage_time",
    "event_start_time",
    "EVENT_START_TIME",
    "OutageDateTime",
    "Event.OutageDateTime",
    "วันเวลาที่ไฟฟ้าขัดข้อง",
    "วันเวลาไฟฟ้าขัดข้อง",
)
_DURATION_ALIASES = (
    "duration_minutes",
    "duration",
    "DURATION_MINUTES",
    "FirstStepDuration",
    "Event.FirstStepDuration",
    "Sum(Event.FirstStepDuration)",
    "Min(Event.FirstStepDuration)",
    "ระยะเวลา (นาที)",
    "ระยะเวลา",
)
_FEEDER_ALIASES = ("feeder", "ฟีดเดอร์", "FEEDER", "Feeder", "Event.Feeder")
_GIS_TAG_ALIASES = (
    "gis_tag",
    "GIS-TAG ของอุปกรณ์ที่ทำงาน",
    "GIS_TAG",
    "gistag",
    "OpDeviceGIStag",
    "Event.OpDeviceGIStag",
)
_DEVICE_TYPE_ALIASES = (
    "device_type",
    "ประเภทของอุปกรณ์ที่ทำงาน",
    "DEVICE_TYPE",
    "อุปกรณ์ที่ทำงาน",
    "OpDeviceType",
    "Event.OpDeviceType",
    "groupdevicetype",
    "Event.groupdevicetype",
)
_DEVICE_ID_ALIASES = ("device_id", "รหัสอุปกรณ์", "DEVICE_ID", "device", "OpDeviceID", "Event.OpDeviceID")
_OPERATION_STATUS_ALIASES = (
    "operation_status",
    "สถานะการทำงาน",
    "STATUS",
    "status",
    "OpDeviceStatus",
    "Event.OpDeviceStatus",
)
_PHASE_ALIASES = ("phase", "เฟสอุปกรณ์", "PHASE", "OpDevicePhase", "Event.OpDevicePhase")
_OWNER_ALIASES = ("owner", "หน่วยงาน", "office", "OfficeName", "OwnerEdit", "Event.OwnerEdit")
_WEATHER_ALIASES = ("weather", "สภาพอากาศ", "WEATHER", "Weather", "Event.Weather")
_CAUSE_FOUND_ALIASES = (
    "cause_found",
    "พบ/ไม่พบสาเหตุ",
    "CAUSE_FOUND",
    "KnowUnknowCause",
    "Event.KnowUnknowCause",
)
_MAIN_CAUSE_ALIASES = ("main_cause", "สาเหตุหลัก", "CAUSE_GROUP", "CauseGroup", "CauseType", "Event.CauseType")
_SUB_CAUSE_ALIASES = ("sub_cause", "สาเหตุย่อย", "CAUSE_CODE", "CauseCode", "SubCauseType", "Event.SubCauseType")

_SFSD_EVENT_SELECTS: tuple[tuple[str, str, str], ...] = (
    ("column", "EventNumber", "หมายเลขเหตุการณ์"),
    ("column", "EventType", "ประเภทเหตุการณ์"),
    ("column", "OutageDateTime", "วันเวลาที่ไฟฟ้าขัดข้อง"),
    ("min", "FirstStepDuration", "ระยะเวลา (นาที)"),
    ("column", "Feeder", "ฟีดเดอร์"),
    ("column", "OpDeviceGIStag", "GIS-TAG ของอุปกรณ์ที่ทำงาน"),
    ("column", "OpDeviceType", "ประเภทของอุปกรณ์ที่ทำงาน"),
    ("column", "OpDeviceID", "รหัสอุปกรณ์"),
    ("column", "OpDeviceStatus", "สถานะการทำงาน"),
    ("column", "OpDevicePhase", "เฟสอุปกรณ์"),
    ("column", "OwnerEdit", "หน่วยงาน"),
    ("column", "Weather", "สภาพอากาศ"),
    ("column", "KnowUnknowCause", "พบ/ไม่พบสาเหตุ"),
    ("column", "CauseType", "สาเหตุหลัก"),
    ("column", "SubCauseType", "สาเหตุย่อย"),
    ("column", "FaultDeviceType", "ประเภทอุปกรณ์ที่เกิดเหตุ"),
    ("column", "FaultDevice", "อุปกรณ์ที่เกิดเหตุ"),
    ("column", "FaultDeviceCondition", "สภาพอุปกรณ์ที่เกิดเหตุ"),
    ("column", "FaultDetail", "รายละเอียดไฟฟ้าขัดข้อง"),
    ("column", "SiteDetail", "รายละเอียดสถานที่จุดเกิดเหตุ"),
    ("column", "Detail", "รายละเอียดปลีกย่อย"),
    ("column", "WorkOrderID", "หมายเลขใบสั่งงาน"),
    ("aggregation", "AffectedCustomer", "ผชฟ.ถูกกระทบรวม"),
)


@dataclass(frozen=True)
class SfsdEventRow:
    event_number: str
    event_type: str
    outage_time: Any
    duration_minutes: float | None
    feeder: str
    gis_tag: str
    device_type: str
    device_id: str
    operation_status: str
    phase: str
    owner: str
    weather: str
    cause_found: str
    main_cause: str
    sub_cause: str
    source_file: str

    @property
    def outage_dt(self):
        return _parse_sfsd_datetime(self.outage_time)

    @property
    def feeder_norm(self) -> str:
        return normalize_feeder(self.feeder or self.device_id) or ""

    @property
    def device_norm(self) -> str:
        return normalize_device_id(self.device_id) or ""

    @property
    def pea_duration_class(self) -> str:
        if self.duration_minutes is None:
            return "missing_duration"
        if self.duration_minutes < 0:
            return "invalid_negative"
        if self.duration_minutes <= 1:
            return "momentary_micro_review"
        if self.duration_minutes <= 5:
            return "short_interruption_review"
        return "sustained_outage_evidence"

    @property
    def evidence_quality(self) -> str:
        if not self.outage_dt:
            return "MISSING_EVENT_TIME"
        if not self.device_norm:
            return "MISSING_DEVICE"
        if self.duration_minutes is None:
            return "MISSING_DURATION"
        if self.duration_minutes < 0:
            return "INVALID_NEGATIVE"
        if self.duration_minutes <= 5:
            return "PEA_MOMENTARY_OR_SHORT"
        return "PEA_SUSTAINED"

    @property
    def evidence_flags(self) -> str:
        flags: list[str] = []
        if self.event_number == "":
            flags.append("event_number_missing")
        if not self.feeder_norm:
            flags.append("feeder_missing_or_unparsed")
        if _is_cause_not_found(self.cause_found, self.main_cause, self.sub_cause):
            flags.append("cause_not_found")
        if self.evidence_quality not in {"PEA_SUSTAINED"}:
            flags.append(self.evidence_quality.lower())
        return ";".join(_dedupe(flags))

    def asdict(self) -> dict[str, str]:
        duration = self.duration_minutes
        return {
            "event_number": self.event_number,
            "event_type": self.event_type,
            "outage_time": _format_dt(self.outage_dt),
            "duration_minutes": "" if duration is None else str(round(duration, 3)),
            "feeder": self.feeder_norm or self.feeder,
            "gis_tag": self.gis_tag,
            "device_type": self.device_type,
            "device_id": self.device_norm or self.device_id,
            "operation_status": self.operation_status,
            "phase": self.phase,
            "owner": self.owner,
            "weather": self.weather,
            "cause_found": self.cause_found,
            "main_cause": self.main_cause,
            "sub_cause": self.sub_cause,
            "pea_duration_class": self.pea_duration_class,
            "evidence_quality": self.evidence_quality,
            "evidence_flags": self.evidence_flags,
            "source_file": self.source_file,
        }


def import_sfsd_events(source: str | Path, output_csv: str | Path) -> dict[str, Any]:
    rows = load_sfsd_events(source)
    _write_csv(output_csv, SFSD_EVENT_COLUMNS, [row.asdict() for row in rows])
    quality = Counter(row.evidence_quality for row in rows)
    duration_class = Counter(row.pea_duration_class for row in rows)
    return {
        "source": str(source),
        "output_csv": str(output_csv),
        "rows": len(rows),
        "with_event_number": sum(1 for row in rows if row.event_number),
        "with_device_time": sum(1 for row in rows if row.device_norm and row.outage_dt),
        "evidence_quality": dict(sorted(quality.items())),
        "pea_duration_class": dict(sorted(duration_class.items())),
    }


def fetch_sfsd_models_and_exploration(
    output_json: str | Path,
    *,
    endpoint_url: str = DEFAULT_SFSD_MODELS_URL,
    headers_output: str | Path | None = None,
    curl_path: str = "curl.exe",
) -> dict[str, Any]:
    output = Path(output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    headers = Path(headers_output) if headers_output else output.with_name(output.stem + ".headers")
    headers.parent.mkdir(parents=True, exist_ok=True)
    command = [
        curl_path,
        "--ntlm",
        "--user",
        ":",
        "-sS",
        "-D",
        str(headers),
        endpoint_url,
        "-o",
        str(output),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"SFSD model fetch failed: {completed.stderr.strip() or completed.stdout.strip()}")
    status_code = _last_http_status(headers)
    if status_code is not None and status_code >= 400:
        raise RuntimeError(f"SFSD model fetch returned HTTP {status_code}")
    payload = json.loads(output.read_text(encoding="utf-8"))
    model_id, locale = _load_sfsd_model_context(output)
    return {
        "endpoint_url": endpoint_url,
        "output_json": str(output),
        "headers_output": str(headers),
        "http_status": status_code,
        "bytes": output.stat().st_size,
        "model_id": model_id,
        "locale": locale,
        "sections": len((payload.get("exploration") or {}).get("sections") or []) if isinstance(payload, dict) else 0,
    }


def build_sfsd_event_detail_query(
    template: str | Path,
    count: int = 30000,
    restart_tokens: list[list[Any]] | None = None,
    *,
    event_type: str | None = "ไฟฟ้าขัดข้อง",
) -> dict[str, Any]:
    model_id, locale = _load_sfsd_model_context(template)
    select: list[dict[str, Any]] = []
    projections: list[int] = []
    for index, (kind, property_name, native_name) in enumerate(_SFSD_EVENT_SELECTS):
        if kind in {"aggregation", "min"}:
            select.append(
                {
                    "Aggregation": {
                        "Expression": {
                            "Column": {
                                "Expression": {"SourceRef": {"Source": "e"}},
                                "Property": property_name,
                            }
                        },
                        "Function": 3 if kind == "min" else 0,
                    },
                    "Name": f"{'Min' if kind == 'min' else 'Sum'}(Event.{property_name})",
                    "NativeReferenceName": native_name,
                }
            )
        else:
            select.append(
                {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": "e"}},
                        "Property": property_name,
                    },
                    "Name": f"Event.{property_name}",
                    "NativeReferenceName": native_name,
                }
            )
        projections.append(index)
    query: dict[str, Any] = {
        "Version": 2,
        "From": [{"Name": "e", "Entity": "Event", "Type": 0}],
        "Select": select,
        "OrderBy": [
            {
                "Direction": 2,
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": "e"}},
                        "Property": "OutageDateTime",
                    }
                },
            }
        ],
    }
    if event_type:
        query["Where"] = [
            {
                "Condition": {
                    "In": {
                        "Expressions": [
                            {
                                "Column": {
                                    "Expression": {"SourceRef": {"Source": "e"}},
                                    "Property": "EventType",
                                }
                            }
                        ],
                        "Values": [[{"Literal": {"Value": f"'{event_type}'"}}]],
                    }
                }
            }
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
                                "Query": query,
                                "Binding": {
                                    "Primary": {"Groupings": [{"Projections": projections}]},
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
                "ApplicationContext": {"Sources": [{"VisualId": "ais-etr-sfsd-event-detail"}]},
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
        "userPreferredLocale": locale,
    }


def fetch_sfsd_event_detail_querydata(
    template: str | Path,
    output_json: str | Path,
    request_output: str | Path | None = None,
    headers_output: str | Path | None = None,
    *,
    endpoint_url: str = DEFAULT_SFSD_QUERYDATA_URL,
    count: int = 30000,
    pages: int = 1,
    curl_path: str = "curl.exe",
    event_type: str | None = "ไฟฟ้าขัดข้อง",
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
        request = build_sfsd_event_detail_query(
            template,
            count=count,
            restart_tokens=restart_tokens,
            event_type=event_type,
        )
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
            raise RuntimeError("SFSD event detail querydata returned semantic error: " + "; ".join(errors[:3]))
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
        "event_type": event_type or "",
    }


def refresh_sfsd_long_outage_evidence(
    template: str | Path,
    querydata_output: str | Path,
    canonical_output: str | Path,
    evidence_output: str | Path,
    markdown_output: str | Path | None = None,
    *,
    request_output: str | Path | None = None,
    headers_output: str | Path | None = None,
    endpoint_url: str = DEFAULT_SFSD_QUERYDATA_URL,
    priority_csv: str | Path = "runtime/long_outage_root_cause_priority.csv",
    event_bridge_csv: str | Path | None = "runtime/reportpo_event_bridge_audit.csv",
    feature_audit_csv: str | Path | None = "runtime/reportpo_feature_join_audit.csv",
    count: int = 30000,
    pages: int = 1,
    curl_path: str = "curl.exe",
    event_type: str | None = "ไฟฟ้าขัดข้อง",
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
) -> dict[str, Any]:
    fetch_result = fetch_sfsd_event_detail_querydata(
        template,
        querydata_output,
        request_output,
        headers_output,
        endpoint_url=endpoint_url,
        count=count,
        pages=pages,
        curl_path=curl_path,
        event_type=event_type,
    )
    import_result = import_sfsd_events(querydata_output, canonical_output)
    evidence_result = build_sfsd_long_outage_evidence(
        priority_csv,
        canonical_output,
        evidence_output,
        markdown_output,
        event_bridge_csv=event_bridge_csv,
        feature_audit_csv=feature_audit_csv,
        max_window_minutes=max_window_minutes,
        ambiguity_delta_minutes=ambiguity_delta_minutes,
    )
    return {"fetch": fetch_result, "import": import_result, "evidence": evidence_result}


def load_sfsd_events(source: str | Path) -> list[SfsdEventRow]:
    path = Path(source)
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        rows: list[dict[str, Any]] = []
        for data in _iter_powerbi_data_objects(payload):
            rows.extend(_decode_powerbi_rows(data))
        return [_row_from_mapping(row, str(path)) for row in rows if _looks_like_sfsd_row(row)]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [_row_from_mapping(dict(row), str(path)) for row in csv.DictReader(handle)]


def build_sfsd_long_outage_evidence(
    priority_csv: str | Path,
    sfsd_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    event_bridge_csv: str | Path | None = None,
    feature_audit_csv: str | Path | None = None,
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
) -> dict[str, Any]:
    priority_rows = _read_csv(priority_csv)
    sfsd_rows = _load_canonical_sfsd_csv(sfsd_csv)
    bridge_index = _BridgeIndex(event_bridge_csv, feature_audit_csv)
    evidence_rows = [
        _build_evidence_row(
            row,
            sfsd_rows,
            bridge_index,
            max_window_minutes=max_window_minutes,
            ambiguity_delta_minutes=ambiguity_delta_minutes,
        )
        for row in priority_rows
    ]
    _write_csv(output_csv, SFSD_EVIDENCE_COLUMNS, evidence_rows)
    summary = _evidence_summary(priority_rows, sfsd_rows, evidence_rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, evidence_rows), encoding="utf-8-sig")
    return {
        **summary,
        "priority_csv": str(priority_csv),
        "sfsd_csv": str(sfsd_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def build_sfsd_remaining_gap_review(
    evidence_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    include_matched_momentary: bool = False,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    evidence_rows = _read_csv(evidence_csv)
    review_candidates = [
        row
        for row in evidence_rows
        if _is_gap_review_row(row, include_matched_momentary=include_matched_momentary)
    ]
    review_candidates = sorted(
        review_candidates,
        key=lambda row: (
            -(_optional_float(row.get("active_error_minutes")) or 0.0),
            _to_sort_int(row.get("priority_rank")),
            row.get("event_time") or "",
            row.get("event_ref") or "",
        ),
    )
    review_rows = [
        _gap_review_row(row, rank=index, high_error_minutes=high_error_minutes)
        for index, row in enumerate(review_candidates, start=1)
    ]
    _write_csv(output_csv, SFSD_GAP_REVIEW_COLUMNS, review_rows)
    summary = _gap_review_summary(evidence_rows, review_rows, include_matched_momentary)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_gap_review_markdown(summary, review_rows), encoding="utf-8-sig")
    return {
        **summary,
        "evidence_csv": str(evidence_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def build_sfsd_gap_resolution_audit(
    gap_review_csv: str | Path,
    sfsd_csv: str | Path,
    db_path: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    nearest_window_minutes: float = 10080.0,
    bridge_window_minutes: float = 1440.0,
) -> dict[str, Any]:
    gap_rows = _read_csv(gap_review_csv)
    sfsd_rows = _load_canonical_sfsd_csv(sfsd_csv)
    asset_index = _CustomerAssetIndex(db_path)
    audit_rows = [
        _gap_resolution_row(
            row,
            sfsd_rows,
            asset_index,
            nearest_window_minutes=nearest_window_minutes,
            bridge_window_minutes=bridge_window_minutes,
        )
        for row in gap_rows
    ]
    _write_csv(output_csv, SFSD_GAP_RESOLUTION_COLUMNS, audit_rows)
    summary = _gap_resolution_summary(audit_rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_gap_resolution_markdown(summary, audit_rows), encoding="utf-8-sig")
    return {
        **summary,
        "gap_review_csv": str(gap_review_csv),
        "sfsd_csv": str(sfsd_csv),
        "db_path": str(db_path),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "nearest_window_minutes": nearest_window_minutes,
        "bridge_window_minutes": bridge_window_minutes,
    }


def build_sfsd_source_trace_candidates(
    gap_resolution_csv: str | Path,
    output_csv: str | Path,
    *,
    statuses: tuple[str, ...] = ("source_trace_required_for_topology_gap",),
) -> dict[str, Any]:
    rows = _read_csv(gap_resolution_csv)
    selected_statuses = set(statuses)
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        status = row.get("resolution_status") or ""
        if status not in selected_statuses:
            continue
        feeder = normalize_feeder(row.get("feeder")) or row.get("feeder", "")
        for role, field in (("webex_device", "webex_device_id"), ("sfsd_candidate_device", "sfsd_candidate_device_id")):
            device_id = normalize_device_id(row.get(field)) or row.get(field, "")
            if not device_id:
                continue
            key = (role, device_id, feeder)
            current = grouped.setdefault(
                key,
                {
                    "priority_rank": row.get("review_rank") or row.get("priority_rank") or "",
                    "device_type": _infer_device_type(device_id),
                    "device_id": device_id,
                    "feeder": feeder,
                    "event_count": 0,
                    "source_gap_status": status,
                    "source_gap_role": role,
                },
            )
            current["event_count"] = int(current.get("event_count") or 0) + 1
            current["priority_rank"] = _min_rank(current.get("priority_rank"), row.get("review_rank") or row.get("priority_rank"))
    candidate_rows = sorted(
        grouped.values(),
        key=lambda row: (
            _to_sort_int(row.get("priority_rank")),
            row.get("feeder") or "",
            row.get("source_gap_role") or "",
            row.get("device_id") or "",
        ),
    )
    _write_csv(output_csv, SFSD_SOURCE_TRACE_CANDIDATE_COLUMNS, candidate_rows)
    return {
        "input_csv": str(gap_resolution_csv),
        "output_csv": str(output_csv),
        "rows": len(candidate_rows),
        "roles": dict(Counter(row["source_gap_role"] for row in candidate_rows)),
        "statuses": dict(Counter(row["source_gap_status"] for row in candidate_rows)),
    }


def build_sfsd_gap_decision_pack(
    gap_resolution_csv: str | Path,
    source_trace_audit_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    gap_rows = _read_csv(gap_resolution_csv)
    trace_rows = _source_trace_by_device(source_trace_audit_csv)
    decision_rows = [_gap_decision_row(row, trace_rows) for row in gap_rows]
    _write_csv(output_csv, SFSD_GAP_DECISION_COLUMNS, decision_rows)
    summary = _gap_decision_summary(decision_rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_gap_decision_markdown(summary, decision_rows), encoding="utf-8-sig")
    return {
        **summary,
        "gap_resolution_csv": str(gap_resolution_csv),
        "source_trace_audit_csv": str(source_trace_audit_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


class _BridgeIndex:
    def __init__(self, event_bridge_csv: str | Path | None, feature_audit_csv: str | Path | None) -> None:
        self.by_ref: dict[str, tuple[str, str]] = {}
        self.rows: list[dict[str, Any]] = []
        for source, path in (("reportpo_event_bridge", event_bridge_csv), ("reportpo_feature_audit", feature_audit_csv)):
            if not path or not Path(path).exists():
                continue
            for row in _read_csv(path):
                mapped = _bridge_row(row, source)
                if not mapped:
                    continue
                ref = mapped.get("event_ref") or ""
                event_number = mapped.get("event_number") or ""
                if ref and event_number:
                    self.by_ref.setdefault(ref, (event_number, source))
                self.rows.append(mapped)

    def event_numbers_for(self, priority: dict[str, str], *, max_window_minutes: float = 60.0) -> list[tuple[str, str]]:
        output: list[tuple[str, str]] = []
        explicit = _clean_text(priority.get("event_number"))
        if explicit:
            output.append((explicit, "priority_event_number"))
        ref = priority.get("event_ref") or ""
        if ref in self.by_ref:
            output.append(self.by_ref[ref])
        event_dt = _parse_datetime(priority.get("event_time"))
        device_norm = normalize_device_id(priority.get("device_id")) or ""
        feeder_norm = normalize_feeder(priority.get("feeder") or priority.get("device_id")) or ""
        if event_dt and device_norm:
            for row in self.rows:
                if row.get("device_norm") != device_norm:
                    continue
                if feeder_norm and row.get("feeder_norm") and row.get("feeder_norm") != feeder_norm:
                    continue
                delta = abs((row["event_dt"] - event_dt).total_seconds() / 60)
                if delta <= max_window_minutes and row.get("event_number"):
                    output.append((str(row["event_number"]), str(row.get("source") or "bridge_time")))
        return _dedupe_pairs(output)


def _build_evidence_row(
    priority: dict[str, str],
    sfsd_rows: list[dict[str, Any]],
    bridge_index: _BridgeIndex,
    *,
    max_window_minutes: float,
    ambiguity_delta_minutes: float,
) -> dict[str, str]:
    event_dt = _parse_sfsd_datetime(priority.get("event_time"))
    device_norm = normalize_device_id(priority.get("device_id")) or ""
    feeder_norm = normalize_feeder(priority.get("feeder") or priority.get("device_id")) or ""
    bridge_numbers = bridge_index.event_numbers_for(priority)
    candidate: dict[str, Any] | None = None
    status = "no_match"
    level = "none"
    bridge_event_number = ""
    bridge_source = ""

    for event_number, source in bridge_numbers:
        exact = [row for row in sfsd_rows if row.get("event_number") == event_number]
        if exact:
            picked, pick_status = _pick_closest(exact, event_dt, ambiguity_delta_minutes)
            candidate = picked
            status = pick_status
            level = "event_number"
            bridge_event_number = event_number
            bridge_source = source
            break

    if candidate is None and event_dt and device_norm:
        exact_device = [
            row
            for row in sfsd_rows
            if row.get("device_norm") == device_norm
            and (not feeder_norm or not row.get("feeder_norm") or row.get("feeder_norm") == feeder_norm)
            and row.get("outage_dt") is not None
            and abs((row["outage_dt"] - event_dt).total_seconds() / 60) <= max_window_minutes
        ]
        if exact_device:
            candidate, status = _pick_closest(exact_device, event_dt, ambiguity_delta_minutes)
            level = "device_time"

    if candidate is None and event_dt and feeder_norm:
        feeder_candidates = [
            row
            for row in sfsd_rows
            if row.get("feeder_norm") == feeder_norm
            and row.get("outage_dt") is not None
            and abs((row["outage_dt"] - event_dt).total_seconds() / 60) <= max_window_minutes
        ]
        if feeder_candidates:
            candidate, _ = _pick_closest(feeder_candidates, event_dt, ambiguity_delta_minutes)
            status = "no_match"
            level = "feeder_time_audit_only"

    if status == "matched" and candidate is not None:
        if level == "device_time":
            bridge_source = "sfsd_device_time"
        elif not bridge_source:
            bridge_source = "sfsd_event_number"
    elif status == "ambiguous":
        bridge_source = bridge_source or "sfsd_ambiguous"

    base = {
        "priority_rank": priority.get("priority_rank", ""),
        "event_ref": priority.get("event_ref", ""),
        "event_time": priority.get("event_time", ""),
        "feeder": feeder_norm or priority.get("feeder", ""),
        "device_id": device_norm or priority.get("device_id", ""),
        "remaining_actual_minutes": priority.get("remaining_actual_minutes", ""),
        "active_p50": priority.get("active_p50", ""),
        "active_error_minutes": priority.get("active_error_minutes", ""),
        "sfsd_match_status": status,
        "sfsd_match_level": level,
        "bridge_event_number": bridge_event_number,
        "bridge_source": bridge_source,
    }
    evidence = _candidate_fields(candidate, event_dt)
    pattern = _pea_ais_pattern(status, level, candidate, _to_float(priority.get("remaining_actual_minutes")))
    cause_status = _cause_status(candidate)
    return {
        **base,
        **evidence,
        "pea_ais_pattern": pattern,
        "cause_status": cause_status,
        "recommended_next_action": _recommended_action(pattern, cause_status, status, level),
    }


def _candidate_fields(candidate: dict[str, Any] | None, event_dt: Any) -> dict[str, str]:
    if not candidate:
        return {
            "sfsd_event_number": "",
            "sfsd_outage_time": "",
            "sfsd_delta_minutes": "",
            "sfsd_duration_minutes": "",
            "sfsd_feeder": "",
            "sfsd_device_id": "",
            "sfsd_gis_tag": "",
            "sfsd_device_type": "",
            "sfsd_operation_status": "",
            "sfsd_phase": "",
            "sfsd_weather": "",
            "sfsd_cause_found": "",
            "sfsd_main_cause": "",
            "sfsd_sub_cause": "",
            "sfsd_evidence_quality": "",
            "sfsd_evidence_flags": "",
            "sfsd_source_file": "",
        }
    outage_dt = candidate.get("outage_dt")
    delta = None
    if event_dt and outage_dt:
        delta = round((outage_dt - event_dt).total_seconds() / 60, 3)
    duration = candidate.get("duration_minutes")
    return {
        "sfsd_event_number": str(candidate.get("event_number") or ""),
        "sfsd_outage_time": _format_dt(outage_dt),
        "sfsd_delta_minutes": "" if delta is None else str(delta),
        "sfsd_duration_minutes": "" if duration is None else str(duration),
        "sfsd_feeder": str(candidate.get("feeder") or ""),
        "sfsd_device_id": str(candidate.get("device_id") or ""),
        "sfsd_gis_tag": str(candidate.get("gis_tag") or ""),
        "sfsd_device_type": str(candidate.get("device_type") or ""),
        "sfsd_operation_status": str(candidate.get("operation_status") or ""),
        "sfsd_phase": str(candidate.get("phase") or ""),
        "sfsd_weather": str(candidate.get("weather") or ""),
        "sfsd_cause_found": str(candidate.get("cause_found") or ""),
        "sfsd_main_cause": str(candidate.get("main_cause") or ""),
        "sfsd_sub_cause": str(candidate.get("sub_cause") or ""),
        "sfsd_evidence_quality": str(candidate.get("evidence_quality") or ""),
        "sfsd_evidence_flags": str(candidate.get("evidence_flags") or ""),
        "sfsd_source_file": str(candidate.get("source_file") or ""),
    }


def _row_from_mapping(row: dict[str, Any], source_file: str) -> SfsdEventRow:
    return SfsdEventRow(
        event_number=_clean_text(_first(row, *_EVENT_NUMBER_ALIASES)),
        event_type=_clean_text(_first(row, *_EVENT_TYPE_ALIASES)),
        outage_time=_first(row, *_OUTAGE_TIME_ALIASES),
        duration_minutes=_optional_float(_first(row, *_DURATION_ALIASES)),
        feeder=_clean_text(_first(row, *_FEEDER_ALIASES)),
        gis_tag=_clean_text(_first(row, *_GIS_TAG_ALIASES)),
        device_type=_clean_text(_first(row, *_DEVICE_TYPE_ALIASES)),
        device_id=_clean_text(_first(row, *_DEVICE_ID_ALIASES)),
        operation_status=_clean_text(_first(row, *_OPERATION_STATUS_ALIASES)),
        phase=_clean_text(_first(row, *_PHASE_ALIASES)),
        owner=_clean_text(_first(row, *_OWNER_ALIASES)),
        weather=_clean_text(_first(row, *_WEATHER_ALIASES)),
        cause_found=_clean_text(_first(row, *_CAUSE_FOUND_ALIASES)),
        main_cause=_clean_text(_first(row, *_MAIN_CAUSE_ALIASES)),
        sub_cause=_clean_text(_first(row, *_SUB_CAUSE_ALIASES)),
        source_file=source_file,
    )


def _looks_like_sfsd_row(row: dict[str, Any]) -> bool:
    return bool(
        _first(row, *_EVENT_NUMBER_ALIASES)
        or _first(row, *_OUTAGE_TIME_ALIASES)
        or _first(row, *_DEVICE_ID_ALIASES)
        or _first(row, *_GIS_TAG_ALIASES)
    )


def _load_canonical_sfsd_csv(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for row in _read_csv(path):
        outage_dt = _parse_sfsd_datetime(row.get("outage_time"))
        rows.append(
            {
                **row,
                "event_number": _clean_text(row.get("event_number")),
                "outage_dt": outage_dt,
                "duration_minutes": _optional_float(row.get("duration_minutes")),
                "feeder_norm": normalize_feeder(row.get("feeder") or row.get("device_id")) or "",
                "device_norm": normalize_device_id(row.get("device_id")) or "",
            }
        )
    return rows


def _bridge_row(row: dict[str, str], source: str) -> dict[str, Any] | None:
    event_number = _clean_text(
        row.get("reportpo_etr_event_number") or row.get("event_number") or row.get("candidate_event_number")
    )
    if not event_number:
        return None
    event_time = _parse_sfsd_datetime(
        row.get("event_time")
        or row.get("webex_event_time")
        or row.get("reportpo_etr_event_start_time")
        or row.get("reportpo_event_start_time")
    )
    if event_time is None:
        return None
    return {
        "event_ref": row.get("webex_message_ref") or row.get("event_ref") or "",
        "event_number": event_number,
        "event_dt": event_time,
        "device_norm": normalize_device_id(
            row.get("device_id") or row.get("webex_device_id") or row.get("reportpo_etr_device_id")
        )
        or "",
        "feeder_norm": normalize_feeder(row.get("feeder") or row.get("webex_feeder") or row.get("device_id")) or "",
        "source": source,
    }


def _pick_closest(
    candidates: list[dict[str, Any]],
    event_dt: Any,
    ambiguity_delta_minutes: float,
) -> tuple[dict[str, Any], str]:
    if not candidates:
        raise ValueError("candidates must not be empty")
    if event_dt is None:
        return candidates[0], "ambiguous" if len(candidates) > 1 else "matched"
    ordered = sorted(
        candidates,
        key=lambda row: (
            abs((row["outage_dt"] - event_dt).total_seconds() / 60) if row.get("outage_dt") else 10**9,
            row.get("event_number") or "",
        ),
    )
    best = ordered[0]
    best_delta = abs((best["outage_dt"] - event_dt).total_seconds() / 60) if best.get("outage_dt") else 10**9
    near = [
        row
        for row in ordered
        if row.get("outage_dt")
        and abs(abs((row["outage_dt"] - event_dt).total_seconds() / 60) - best_delta) <= ambiguity_delta_minutes
    ]
    distinct_keys = {(row.get("event_number"), row.get("device_id"), _format_dt(row.get("outage_dt"))) for row in near}
    return best, "ambiguous" if len(distinct_keys) > 1 else "matched"


def _pea_ais_pattern(
    status: str,
    level: str,
    candidate: dict[str, Any] | None,
    remaining_actual_minutes: float | None,
) -> str:
    if status == "ambiguous":
        return "sfsd_ambiguous"
    if status != "matched":
        if level == "feeder_time_audit_only":
            return "sfsd_feeder_candidate_only"
        return "sfsd_no_match"
    duration = _optional_float(candidate.get("duration_minutes") if candidate else None)
    if duration is None:
        return "sfsd_duration_missing"
    if remaining_actual_minutes is not None and remaining_actual_minutes <= 5:
        return "not_customer_long_outage"
    if duration <= 5 and (remaining_actual_minutes is None or remaining_actual_minutes > 5):
        return "pea_momentary_or_short_ais_long"
    if duration > 5 and (remaining_actual_minutes is None or remaining_actual_minutes > 5):
        return "pea_sustained_ais_long"
    return "sfsd_context_only"


def _cause_status(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "not_available"
    if _is_cause_not_found(candidate.get("cause_found"), candidate.get("main_cause"), candidate.get("sub_cause")):
        return "cause_not_found"
    if candidate.get("main_cause") or candidate.get("sub_cause"):
        return "cause_available"
    return "cause_missing"


def _is_cause_not_found(*values: Any) -> bool:
    joined = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if not joined:
        return False
    return "ไม่พบ" in joined or "not found" in joined or "unknown" in joined


def _recommended_action(pattern: str, cause_status: str, status: str, level: str) -> str:
    if status == "ambiguous":
        return "Review SFSD candidate manually before using as lifecycle/cause evidence."
    if pattern == "sfsd_no_match":
        return "Import wider SFSD detail or check event/device key; keep this case in lifecycle review queue."
    if pattern == "sfsd_feeder_candidate_only":
        return "Use feeder candidate for context only; do not treat it as device-confirmed evidence."
    if pattern == "pea_momentary_or_short_ais_long":
        if cause_status == "cause_not_found":
            return "Treat as PEA momentary plus AIS sustained gap; request downstream/site-side cause evidence before model tuning."
        return "Use SFSD as context only and inspect why AIS remained active after short PEA device operation."
    if pattern == "pea_sustained_ais_long":
        return "Use as owner-reviewed lifecycle/cause feature candidate; still keep AIS outage/restore as truth."
    return "Keep as shadow evidence only; no production/model promotion decision from this row."


def _evidence_summary(
    priority_rows: list[dict[str, str]],
    sfsd_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, str]],
) -> dict[str, Any]:
    match_status = Counter(row.get("sfsd_match_status") or "unknown" for row in evidence_rows)
    match_level = Counter(row.get("sfsd_match_level") or "unknown" for row in evidence_rows)
    pattern = Counter(row.get("pea_ais_pattern") or "unknown" for row in evidence_rows)
    cause_status = Counter(row.get("cause_status") or "unknown" for row in evidence_rows)
    top_devices = Counter(row.get("device_id") or "unknown" for row in evidence_rows if row.get("pea_ais_pattern") != "sfsd_no_match")
    return {
        "priority_rows": len(priority_rows),
        "sfsd_rows": len(sfsd_rows),
        "matched_rows": match_status.get("matched", 0),
        "ambiguous_rows": match_status.get("ambiguous", 0),
        "no_match_rows": match_status.get("no_match", 0),
        "feeder_candidate_only_rows": match_level.get("feeder_time_audit_only", 0),
        "no_evidence_rows": match_level.get("none", 0),
        "match_status": dict(sorted(match_status.items())),
        "match_level": dict(sorted(match_level.items())),
        "pea_ais_pattern": dict(sorted(pattern.items())),
        "cause_status": dict(sorted(cause_status.items())),
        "top_matched_devices": dict(top_devices.most_common(10)),
        "decision": _summary_decision(pattern, match_status),
    }


def _summary_decision(pattern: Counter[str], match_status: Counter[str]) -> str:
    if not sum(match_status.values()):
        return "no_priority_rows"
    if match_status.get("matched", 0) == 0:
        return "need_sfsd_export_or_key_discovery"
    if pattern.get("pea_momentary_or_short_ais_long", 0):
        return "review_pea_momentary_ais_long_before_model_tuning"
    if pattern.get("pea_sustained_ais_long", 0):
        return "use_sfsd_context_after_owner_review"
    return "keep_shadow_evidence_only"


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    top_rows = rows[:10]
    lines = [
        "# SFSD Long-Outage Evidence Pack",
        "",
        "Purpose: compare SFSD PowerBI event evidence against AIS customer-facing long-outage misses without treating SFSD as AIS restoration truth.",
        "",
        "## Summary",
        "",
        f"- Priority long-outage rows: {summary['priority_rows']}",
        f"- Canonical SFSD rows available: {summary['sfsd_rows']}",
        f"- Matched rows: {summary['matched_rows']}",
        f"- Feeder-only audit candidates: {summary['feeder_candidate_only_rows']}",
        f"- No SFSD evidence rows: {summary['no_evidence_rows']}",
        f"- Ambiguous rows: {summary['ambiguous_rows']}",
        f"- Total rows not accepted as device-confirmed match: {summary['no_match_rows']}",
        f"- Decision: `{summary['decision']}`",
        "",
        "## Pattern Counts",
        "",
    ]
    for key, value in summary["pea_ais_pattern"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Cause Status", ""])
    for key, value in summary["cause_status"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Top Evidence Rows",
            "",
            "| rank | event_ref | feeder | device | SFSD event | SFSD duration | pattern | action |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in top_rows:
        lines.append(
            "| {rank} | `{event_ref}` | {feeder} | {device_id} | {sfsd_event_number} | {duration} | `{pattern}` | {action} |".format(
                rank=row.get("priority_rank", ""),
                event_ref=row.get("event_ref", ""),
                feeder=row.get("feeder", ""),
                device_id=row.get("device_id", ""),
                sfsd_event_number=row.get("sfsd_event_number", ""),
                duration=row.get("sfsd_duration_minutes", ""),
                pattern=row.get("pea_ais_pattern", ""),
                action=row.get("recommended_next_action", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- SFSD is lifecycle/cause evidence only unless a data owner approves a stronger semantic mapping.",
            "- `cl_datetime`, ticket close time, and ETR timestamps are not used as restoration truth.",
            "- Production AIS delivery and model artifact overwrite remain blocked.",
        ]
    )
    return "\n".join(lines) + "\n"


def _is_gap_review_row(row: dict[str, str], *, include_matched_momentary: bool) -> bool:
    level = row.get("sfsd_match_level") or ""
    pattern = row.get("pea_ais_pattern") or ""
    if level in {"", "none", "feeder_time_audit_only"}:
        return True
    if row.get("sfsd_match_status") == "ambiguous":
        return True
    return include_matched_momentary and pattern == "pea_momentary_or_short_ais_long"


def _gap_review_row(row: dict[str, str], *, rank: int, high_error_minutes: float) -> dict[str, str]:
    gap_class = _gap_class(row)
    return {
        "review_rank": str(rank),
        "priority_rank": row.get("priority_rank", ""),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "remaining_actual_minutes": row.get("remaining_actual_minutes", ""),
        "active_error_minutes": row.get("active_error_minutes", ""),
        "sfsd_match_status": row.get("sfsd_match_status", ""),
        "sfsd_match_level": row.get("sfsd_match_level", ""),
        "pea_ais_pattern": row.get("pea_ais_pattern", ""),
        "sfsd_candidate_event_number": row.get("sfsd_event_number", ""),
        "sfsd_candidate_outage_time": row.get("sfsd_outage_time", ""),
        "sfsd_candidate_delta_minutes": row.get("sfsd_delta_minutes", ""),
        "sfsd_candidate_duration_minutes": row.get("sfsd_duration_minutes", ""),
        "sfsd_candidate_feeder": row.get("sfsd_feeder", ""),
        "sfsd_candidate_device_id": row.get("sfsd_device_id", ""),
        "sfsd_candidate_quality": row.get("sfsd_evidence_quality", ""),
        "gap_class": gap_class,
        "review_priority": _review_priority(row, gap_class, high_error_minutes),
        "recommended_owner_question": _gap_owner_question(row, gap_class),
        "recommended_next_action": _gap_next_action(row, gap_class),
        "model_decision": _gap_model_decision(gap_class),
    }


def _gap_class(row: dict[str, str]) -> str:
    status = row.get("sfsd_match_status") or ""
    level = row.get("sfsd_match_level") or ""
    pattern = row.get("pea_ais_pattern") or ""
    if status == "ambiguous":
        return "ambiguous_sfsd_candidate_review"
    if level == "feeder_time_audit_only":
        candidate_device = row.get("sfsd_device_id") or ""
        if candidate_device and candidate_device != (row.get("device_id") or ""):
            return "topology_or_device_bridge_review"
        return "feeder_only_bridge_review"
    if pattern == "pea_momentary_or_short_ais_long":
        return "pea_short_ais_long_site_side_review"
    if level in {"", "none"}:
        return "missing_sfsd_event_or_bridge"
    return "unconfirmed_sfsd_context_review"


def _review_priority(row: dict[str, str], gap_class: str, high_error_minutes: float) -> str:
    active_error = _optional_float(row.get("active_error_minutes")) or 0.0
    remaining = _optional_float(row.get("remaining_actual_minutes")) or 0.0
    if active_error >= 180 or remaining >= 480:
        return "P0"
    if gap_class in {"missing_sfsd_event_or_bridge", "topology_or_device_bridge_review"} and active_error >= high_error_minutes:
        return "P1"
    if active_error >= high_error_minutes:
        return "P2"
    return "P3"


def _gap_owner_question(row: dict[str, str], gap_class: str) -> str:
    event_time = row.get("event_time") or "<event_time>"
    feeder = row.get("feeder") or "<feeder>"
    device = row.get("device_id") or "<device>"
    candidate_event = row.get("sfsd_event_number") or "<no SFSD event>"
    candidate_device = row.get("sfsd_device_id") or "<no SFSD device>"
    if gap_class == "topology_or_device_bridge_review":
        return (
            f"At {event_time}, does Webex device {device} on feeder {feeder} map to SFSD event "
            f"{candidate_event} / device {candidate_device}, or is this an upstream/downstream topology difference?"
        )
    if gap_class == "feeder_only_bridge_review":
        return (
            f"At {event_time}, which protection device actually interrupted AIS sites on feeder {feeder}; "
            "can the exact SFSD event number/device be confirmed?"
        )
    if gap_class == "missing_sfsd_event_or_bridge":
        return (
            f"At {event_time}, is there an SFSD/ReportPO event for {device} on feeder {feeder}; "
            "if yes, what event number or work-order key should bridge Webex to SFSD?"
        )
    if gap_class == "pea_short_ais_long_site_side_review":
        return (
            f"SFSD shows short PEA operation for {device}; why did AIS remain interrupted after PEA restoration?"
        )
    if gap_class == "ambiguous_sfsd_candidate_review":
        return f"Which of the multiple SFSD candidates around {event_time} is the owner-approved event for {device}?"
    return f"Please review SFSD context for {device} on {feeder} at {event_time} before model use."


def _gap_next_action(row: dict[str, str], gap_class: str) -> str:
    if gap_class == "topology_or_device_bridge_review":
        return "Run source topology trace for Webex device and candidate SFSD device; approve only if both protect the same AIS affected path."
    if gap_class == "feeder_only_bridge_review":
        return "Keep feeder candidate as context only; find exact device/event key or request operator confirmation."
    if gap_class == "missing_sfsd_event_or_bridge":
        return "Search SFSD/ReportPO by event time, feeder, and device; if still missing, keep in AIS-side outage review queue."
    if gap_class == "pea_short_ais_long_site_side_review":
        return "Use AIS alarm/tower evidence to explain site-side remaining outage; do not tune model from this row alone."
    if gap_class == "ambiguous_sfsd_candidate_review":
        return "Owner must choose one candidate before it can become lifecycle/cause feature evidence."
    return row.get("recommended_next_action") or "Keep as shadow review evidence only."


def _gap_model_decision(gap_class: str) -> str:
    if gap_class in {"topology_or_device_bridge_review", "feeder_only_bridge_review", "ambiguous_sfsd_candidate_review"}:
        return "blocked_until_owner_or_topology_approval"
    if gap_class == "missing_sfsd_event_or_bridge":
        return "blocked_until_bridge_or_ais_side_review"
    if gap_class == "pea_short_ais_long_site_side_review":
        return "do_not_train_as_pea_duration; use_site_side_feature_only_after_review"
    return "shadow_context_only"


def _gap_review_summary(
    evidence_rows: list[dict[str, str]],
    review_rows: list[dict[str, str]],
    include_matched_momentary: bool,
) -> dict[str, Any]:
    gap_counts = Counter(row.get("gap_class") or "unknown" for row in review_rows)
    priority_counts = Counter(row.get("review_priority") or "unknown" for row in review_rows)
    model_decisions = Counter(row.get("model_decision") or "unknown" for row in review_rows)
    return {
        "evidence_rows": len(evidence_rows),
        "review_rows": len(review_rows),
        "include_matched_momentary": include_matched_momentary,
        "gap_class_counts": dict(gap_counts.most_common()),
        "review_priority_counts": dict(priority_counts.most_common()),
        "model_decision_counts": dict(model_decisions.most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in review_rows).most_common(8)),
        "top_devices": dict(Counter(row.get("device_id") or "<blank>" for row in review_rows).most_common(8)),
        "recommendation": _gap_summary_recommendation(gap_counts),
    }


def _gap_summary_recommendation(gap_counts: Counter[str]) -> str:
    if not gap_counts:
        return "No remaining SFSD gap rows found. Move to reviewed lifecycle/cause feature challenger."
    if gap_counts.get("missing_sfsd_event_or_bridge", 0):
        return "First resolve missing event bridge/SFSD evidence rows before tuning the model."
    if gap_counts.get("topology_or_device_bridge_review", 0) or gap_counts.get("feeder_only_bridge_review", 0):
        return "First verify topology or exact device-event mapping; feeder-only context is not enough for model features."
    if gap_counts.get("pea_short_ais_long_site_side_review", 0):
        return "Separate PEA short operations from AIS site-side long outages before any model tuning."
    return "Keep the rows in shadow review until owner-approved context is available."


def _render_gap_review_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# SFSD Remaining Gap Review Pack",
        "",
        "Purpose: isolate SFSD rows that are not device-confirmed evidence for AIS customer-facing long-outage misses.",
        "",
        "## Summary",
        "",
        f"- Evidence rows reviewed: {summary['evidence_rows']}",
        f"- Remaining review rows: {summary['review_rows']}",
        f"- Include matched PEA-short/AIS-long rows: {summary['include_matched_momentary']}",
        f"- Recommendation: {summary['recommendation']}",
        "- Production send remains blocked.",
        "",
        "## Gap Classes",
        "",
        "| Gap class | Rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["gap_class_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Review Priority", "", "| Priority | Rows |", "| --- | ---: |"])
    for key, value in summary["review_priority_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Top Feeders", "", "| Feeder | Rows |", "| --- | ---: |"])
    for key, value in summary["top_feeders"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Rows To Review",
            "",
            "| Review | Priority | Event ref | Time | Feeder | Device | Error | Gap | Next action |",
            "| ---: | --- | --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in rows[:20]:
        lines.append(
            "| {rank} | {priority} | `{ref}` | {time} | {feeder} | {device} | {error} | `{gap}` | {action} |".format(
                rank=row.get("review_rank", ""),
                priority=row.get("review_priority", ""),
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                error=row.get("active_error_minutes", ""),
                gap=row.get("gap_class", ""),
                action=row.get("recommended_next_action", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- Feeder-only SFSD candidates are audit-only and cannot become confirmed device evidence without owner/topology approval.",
            "- SFSD/ReportPO close timestamps and ETR timestamps are not used as actual restoration truth.",
            "- This pack intentionally avoids PEANO lists, raw Webex text, room IDs, tokens, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


class _CustomerAssetIndex:
    def __init__(self, db_path: str | Path) -> None:
        self.rows = self._load_assets(db_path)
        self.by_feeder: dict[str, set[str]] = {}
        for row in self.rows:
            feeder = row.get("feeder") or ""
            if feeder:
                self.by_feeder.setdefault(feeder, set()).add(row["peano"])

    def device_assets(self, device_id: str) -> tuple[set[str], str]:
        device_norm = normalize_device_id(device_id) or ""
        if not device_norm:
            return set(), ""
        for level, field in (
            ("cb", "cb_ids"),
            ("recloser", "recloser_ids"),
            ("switch", "switch_ids"),
        ):
            matches = {row["peano"] for row in self.rows if device_norm in row.get(field, set())}
            if matches:
                return matches, level
        matches = {
            row["peano"]
            for row in self.rows
            if device_norm in {row.get("transformer_id", ""), row.get("transformer_peano", "")}
        }
        if matches:
            return matches, "transformer"
        return set(), ""

    def feeder_assets(self, feeder: str) -> set[str]:
        return set(self.by_feeder.get(normalize_feeder(feeder) or "", set()))

    @staticmethod
    def _load_assets(db_path: str | Path) -> list[dict[str, Any]]:
        path = Path(db_path)
        if not path.exists():
            return []
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT peano, feeder, transformer_id, transformer_peano,
                       recloser_ids, switch_ids, cb_ids
                FROM customer_assets
                WHERE confidence_eligible = 1
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        output = []
        for row in rows:
            output.append(
                {
                    "peano": str(row["peano"] or ""),
                    "feeder": normalize_feeder(row["feeder"]) or "",
                    "transformer_id": normalize_device_id(row["transformer_id"]) or "",
                    "transformer_peano": normalize_device_id(row["transformer_peano"]) or "",
                    "recloser_ids": _json_device_set(row["recloser_ids"]),
                    "switch_ids": _json_device_set(row["switch_ids"]),
                    "cb_ids": _json_device_set(row["cb_ids"]),
                }
            )
        return output


def _gap_resolution_row(
    row: dict[str, str],
    sfsd_rows: list[dict[str, Any]],
    asset_index: _CustomerAssetIndex,
    *,
    nearest_window_minutes: float,
    bridge_window_minutes: float,
) -> dict[str, str]:
    event_dt = _parse_sfsd_datetime(row.get("event_time"))
    feeder = normalize_feeder(row.get("feeder")) or row.get("feeder", "")
    webex_device = normalize_device_id(row.get("device_id") or row.get("webex_device_id")) or row.get("device_id", "")
    candidate_device = normalize_device_id(row.get("sfsd_candidate_device_id") or row.get("sfsd_device_id")) or (
        row.get("sfsd_candidate_device_id") or row.get("sfsd_device_id") or ""
    )
    webex_assets, webex_level = asset_index.device_assets(webex_device)
    candidate_assets, candidate_level = asset_index.device_assets(candidate_device)
    feeder_assets = asset_index.feeder_assets(feeder)
    overlap = webex_assets & candidate_assets
    topology_support = _topology_support(
        webex_assets,
        candidate_assets,
        overlap,
        feeder_assets,
        row.get("gap_class") or "",
        candidate_device,
    )
    nearest_device = _nearest_sfsd_candidate(
        sfsd_rows,
        event_dt,
        device_norm=webex_device,
        feeder_norm=feeder,
        max_window_minutes=nearest_window_minutes,
    )
    nearest_feeder = _nearest_sfsd_candidate(
        sfsd_rows,
        event_dt,
        feeder_norm=feeder,
        max_window_minutes=nearest_window_minutes,
    )
    resolution_status = _resolution_status(
        row,
        topology_support,
        nearest_device,
        nearest_feeder,
        bridge_window_minutes=bridge_window_minutes,
    )
    return {
        "review_rank": row.get("review_rank", ""),
        "priority_rank": row.get("priority_rank", ""),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": feeder,
        "webex_device_id": webex_device,
        "sfsd_candidate_device_id": candidate_device,
        "gap_class": row.get("gap_class", ""),
        "review_priority": row.get("review_priority", ""),
        "webex_device_asset_count": str(len(webex_assets)),
        "webex_device_match_level": webex_level,
        "candidate_device_asset_count": str(len(candidate_assets)),
        "candidate_device_match_level": candidate_level,
        "overlap_asset_count": str(len(overlap)),
        "feeder_asset_count": str(len(feeder_assets)),
        "topology_support": topology_support,
        **_nearest_fields("nearest_same_device", nearest_device, event_dt),
        **_nearest_fields("nearest_same_feeder", nearest_feeder, event_dt),
        "resolution_status": resolution_status,
        "recommended_next_action": _resolution_action(row, resolution_status, topology_support),
        "model_decision": _resolution_model_decision(resolution_status),
    }


def _json_device_set(value: Any) -> set[str]:
    try:
        raw = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        raw = []
    if not isinstance(raw, list):
        return set()
    return {normalized for item in raw if (normalized := normalize_device_id(item))}


def _topology_support(
    webex_assets: set[str],
    candidate_assets: set[str],
    overlap: set[str],
    feeder_assets: set[str],
    gap_class: str,
    candidate_device: str,
) -> str:
    if gap_class != "topology_or_device_bridge_review":
        return "not_topology_gap"
    if not candidate_device:
        return "missing_candidate_device"
    if webex_assets and candidate_assets and overlap:
        return "same_ais_path_supported_by_registry"
    if webex_assets and candidate_assets and not overlap:
        return "different_ais_paths_in_registry"
    if webex_assets and not candidate_assets:
        return "candidate_device_not_in_ais_registry"
    if candidate_assets and not webex_assets:
        return "webex_device_not_in_ais_registry"
    if feeder_assets:
        return "same_feeder_only_registry_trace_needed"
    return "no_registry_assets_on_feeder"


def _nearest_sfsd_candidate(
    sfsd_rows: list[dict[str, Any]],
    event_dt: Any,
    *,
    device_norm: str | None = None,
    feeder_norm: str | None = None,
    max_window_minutes: float,
) -> dict[str, Any] | None:
    if event_dt is None:
        return None
    device = normalize_device_id(device_norm) if device_norm else ""
    feeder = normalize_feeder(feeder_norm) if feeder_norm else ""
    candidates = []
    for row in sfsd_rows:
        outage_dt = row.get("outage_dt")
        if outage_dt is None:
            continue
        if device and row.get("device_norm") != device:
            continue
        if feeder and row.get("feeder_norm") != feeder:
            continue
        delta = (outage_dt - event_dt).total_seconds() / 60
        if abs(delta) > max_window_minutes:
            continue
        candidates.append((abs(delta), delta, row))
    if not candidates:
        return None
    _, delta, row = sorted(
        candidates,
        key=lambda item: (item[0], item[2].get("event_number") or "", item[2].get("device_id") or ""),
    )[0]
    return {**row, "delta_minutes": round(delta, 3)}


def _nearest_fields(prefix: str, candidate: dict[str, Any] | None, event_dt: Any) -> dict[str, str]:
    if not candidate:
        if prefix == "nearest_same_device":
            return {
                "nearest_same_device_event_number": "",
                "nearest_same_device_time": "",
                "nearest_same_device_delta_minutes": "",
                "nearest_same_device_duration_minutes": "",
                "nearest_same_device_quality": "",
            }
        return {
            "nearest_same_feeder_event_number": "",
            "nearest_same_feeder_time": "",
            "nearest_same_feeder_device_id": "",
            "nearest_same_feeder_delta_minutes": "",
            "nearest_same_feeder_duration_minutes": "",
            "nearest_same_feeder_quality": "",
        }
    duration = candidate.get("duration_minutes")
    if prefix == "nearest_same_device":
        return {
            "nearest_same_device_event_number": str(candidate.get("event_number") or ""),
            "nearest_same_device_time": _format_dt(candidate.get("outage_dt")),
            "nearest_same_device_delta_minutes": str(candidate.get("delta_minutes", "")),
            "nearest_same_device_duration_minutes": "" if duration is None else str(duration),
            "nearest_same_device_quality": str(candidate.get("evidence_quality") or ""),
        }
    return {
        "nearest_same_feeder_event_number": str(candidate.get("event_number") or ""),
        "nearest_same_feeder_time": _format_dt(candidate.get("outage_dt")),
        "nearest_same_feeder_device_id": str(candidate.get("device_id") or ""),
        "nearest_same_feeder_delta_minutes": str(candidate.get("delta_minutes", "")),
        "nearest_same_feeder_duration_minutes": "" if duration is None else str(duration),
        "nearest_same_feeder_quality": str(candidate.get("evidence_quality") or ""),
    }


def _resolution_status(
    row: dict[str, str],
    topology_support: str,
    nearest_device: dict[str, Any] | None,
    nearest_feeder: dict[str, Any] | None,
    *,
    bridge_window_minutes: float,
) -> str:
    gap_class = row.get("gap_class") or ""
    if gap_class == "topology_or_device_bridge_review":
        if topology_support == "same_ais_path_supported_by_registry":
            return "topology_supported_pending_owner_approval"
        if topology_support == "different_ais_paths_in_registry":
            return "do_not_bridge_different_ais_paths"
        return "source_trace_required_for_topology_gap"
    if gap_class == "missing_sfsd_event_or_bridge":
        if nearest_device and abs(_optional_float(nearest_device.get("delta_minutes")) or 0.0) <= bridge_window_minutes:
            return "same_device_sfsd_candidate_found_review_bridge"
        if nearest_device:
            return "same_device_far_sfsd_candidate_context_only"
        if nearest_feeder and abs(_optional_float(nearest_feeder.get("delta_minutes")) or 0.0) <= bridge_window_minutes:
            return "same_feeder_sfsd_candidate_found_audit_only"
        if nearest_feeder:
            return "same_feeder_far_sfsd_candidate_context_only"
        return "no_near_sfsd_candidate_found"
    if gap_class == "pea_short_ais_long_site_side_review":
        return "site_side_long_outage_review"
    return "manual_review_required"


def _resolution_action(row: dict[str, str], status: str, topology_support: str) -> str:
    if status == "topology_supported_pending_owner_approval":
        return "Ask topology owner to approve same AIS path before using SFSD cause/lifecycle context."
    if status == "do_not_bridge_different_ais_paths":
        return "Do not bridge this SFSD candidate to the Webex event; find exact event key or keep AIS-side review."
    if status == "source_trace_required_for_topology_gap":
        return "Run source GIS trace for Webex and candidate SFSD devices; registry alone is insufficient."
    if status == "same_device_sfsd_candidate_found_review_bridge":
        return "Review nearest same-device SFSD candidate and approve event bridge only if event semantics match."
    if status == "same_feeder_sfsd_candidate_found_audit_only":
        return "Use same-feeder SFSD row for context only; keep searching for exact device/event bridge."
    if status == "same_device_far_sfsd_candidate_context_only":
        return "Nearest same-device SFSD candidate is too far from Webex time; do not bridge without owner evidence."
    if status == "same_feeder_far_sfsd_candidate_context_only":
        return "Nearest same-feeder SFSD candidate is too far from Webex time; keep as context only."
    if status == "no_near_sfsd_candidate_found":
        return "Treat as AIS-side or missing-source event until SFSD/ReportPO owner provides an event/work-order key."
    if status == "site_side_long_outage_review":
        return "Explain AIS site-side remaining outage separately from PEA device duration."
    return row.get("recommended_next_action") or "Manual review required."


def _resolution_model_decision(status: str) -> str:
    if status in {
        "topology_supported_pending_owner_approval",
        "same_device_sfsd_candidate_found_review_bridge",
    }:
        return "candidate_feature_after_owner_approval"
    if status == "site_side_long_outage_review":
        return "site_side_feature_after_review_only"
    return "blocked_for_model_training"


def _gap_resolution_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    statuses = Counter(row.get("resolution_status") or "unknown" for row in rows)
    topology = Counter(row.get("topology_support") or "unknown" for row in rows)
    model_decisions = Counter(row.get("model_decision") or "unknown" for row in rows)
    return {
        "audit_rows": len(rows),
        "resolution_status_counts": dict(statuses.most_common()),
        "topology_support_counts": dict(topology.most_common()),
        "model_decision_counts": dict(model_decisions.most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(8)),
        "top_devices": dict(Counter(row.get("webex_device_id") or "<blank>" for row in rows).most_common(8)),
        "recommendation": _gap_resolution_recommendation(statuses),
    }


def _gap_resolution_recommendation(statuses: Counter[str]) -> str:
    if not statuses:
        return "No unresolved SFSD gap rows remain."
    if statuses.get("do_not_bridge_different_ais_paths", 0):
        return "Do not approve feeder-only SFSD candidates with different AIS asset paths; search for exact event bridge."
    if statuses.get("source_trace_required_for_topology_gap", 0):
        return "Run GIS source trace for topology gaps before approving SFSD context."
    if statuses.get("same_device_far_sfsd_candidate_context_only", 0) or statuses.get(
        "same_feeder_far_sfsd_candidate_context_only", 0
    ):
        return "Nearest SFSD candidates are outside the bridge window; ask source owner for event/work-order bridge."
    if statuses.get("no_near_sfsd_candidate_found", 0):
        return "Ask source owner for event/work-order bridge or treat these as AIS-side missing-source cases."
    return "Only reviewed/approved candidates should be used as shadow-only lifecycle/cause features."


def _render_gap_resolution_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# SFSD Gap Resolution Audit",
        "",
        "Purpose: reduce the remaining SFSD evidence gaps by checking AIS registry topology overlap and nearest SFSD event candidates.",
        "",
        "## Summary",
        "",
        f"- Audit rows: {summary['audit_rows']}",
        f"- Recommendation: {summary['recommendation']}",
        "- Production send remains blocked.",
        "",
        "## Resolution Status",
        "",
        "| Status | Rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["resolution_status_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Topology Support", "", "| Topology support | Rows |", "| --- | ---: |"])
    for key, value in summary["topology_support_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Audit Rows",
            "",
            "| Rank | Priority | Feeder | Webex device | SFSD candidate | Webex assets | Candidate assets | Overlap | Status | Next action |",
            "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows[:20]:
        lines.append(
            "| {rank} | {priority} | {feeder} | {webex} | {candidate} | {webex_count} | {candidate_count} | {overlap} | `{status}` | {action} |".format(
                rank=row.get("review_rank", ""),
                priority=row.get("review_priority", ""),
                feeder=row.get("feeder", ""),
                webex=row.get("webex_device_id", ""),
                candidate=row.get("sfsd_candidate_device_id", ""),
                webex_count=row.get("webex_device_asset_count", ""),
                candidate_count=row.get("candidate_device_asset_count", ""),
                overlap=row.get("overlap_asset_count", ""),
                status=row.get("resolution_status", ""),
                action=row.get("recommended_next_action", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Counts are aggregate only; PEANO lists are intentionally not exported.",
            "- Feeder-only SFSD candidates remain audit-only unless topology owner approves the exact AIS path.",
            "- SFSD nearest candidates are context for investigation, not restoration truth.",
            "- Do not overwrite the model artifact or send production AIS notifications from this audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def _source_trace_by_device(path: str | Path) -> dict[str, dict[str, str]]:
    output = {}
    for row in _read_csv(path):
        device = normalize_device_id(row.get("device_id")) or ""
        if device:
            output[device] = row
    return output


def _gap_decision_row(row: dict[str, str], trace_rows: dict[str, dict[str, str]]) -> dict[str, str]:
    webex_device = normalize_device_id(row.get("webex_device_id")) or row.get("webex_device_id", "")
    candidate_device = normalize_device_id(row.get("sfsd_candidate_device_id")) or row.get("sfsd_candidate_device_id", "")
    webex_trace = trace_rows.get(webex_device, {})
    candidate_trace = trace_rows.get(candidate_device, {})
    final_decision = _final_gap_decision(row, webex_trace, candidate_trace)
    return {
        "review_rank": row.get("review_rank", ""),
        "priority_rank": row.get("priority_rank", ""),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "feeder": row.get("feeder", ""),
        "webex_device_id": webex_device,
        "sfsd_candidate_device_id": candidate_device,
        "resolution_status": row.get("resolution_status", ""),
        "source_webex_trace_result": webex_trace.get("source_trace_result", ""),
        "source_webex_ais_confident_hits": webex_trace.get("ais_confident_hits", ""),
        "source_candidate_trace_result": candidate_trace.get("source_trace_result", ""),
        "source_candidate_ais_confident_hits": candidate_trace.get("ais_confident_hits", ""),
        "nearest_same_device_delta_minutes": row.get("nearest_same_device_delta_minutes", ""),
        "nearest_same_feeder_delta_minutes": row.get("nearest_same_feeder_delta_minutes", ""),
        "final_decision": final_decision,
        "final_action": _final_gap_action(final_decision),
        "model_decision": _final_gap_model_decision(final_decision),
    }


def _final_gap_decision(
    row: dict[str, str],
    webex_trace: dict[str, str],
    candidate_trace: dict[str, str],
) -> str:
    status = row.get("resolution_status") or ""
    webex_result = webex_trace.get("source_trace_result") or ""
    candidate_result = candidate_trace.get("source_trace_result") or ""
    webex_hits = _to_sort_int(webex_trace.get("ais_confident_hits"))
    candidate_hits = _to_sort_int(candidate_trace.get("ais_confident_hits"))
    if (
        status == "source_trace_required_for_topology_gap"
        and webex_result == "source_trace_confirms_confident_ais_downstream"
        and candidate_result == "source_device_not_found"
    ):
        return "reject_sfsd_candidate_webex_device_confirmed"
    if status == "source_trace_required_for_topology_gap" and webex_hits > 0 and candidate_hits == 0:
        return "prefer_webex_device_need_exact_sfsd_bridge"
    if status == "topology_supported_pending_owner_approval":
        return "topology_supported_owner_approval_needed"
    if status in {"same_device_far_sfsd_candidate_context_only", "same_feeder_far_sfsd_candidate_context_only"}:
        return "do_not_bridge_time_gap_too_large"
    if status == "same_device_sfsd_candidate_found_review_bridge":
        return "same_device_bridge_review_needed"
    if status == "same_feeder_sfsd_candidate_found_audit_only":
        return "same_feeder_context_only"
    return "manual_review_required"


def _final_gap_action(decision: str) -> str:
    actions = {
        "reject_sfsd_candidate_webex_device_confirmed": (
            "Do not bridge the SFSD candidate device to this Webex event; keep AIS truth on the Webex device and request the exact SFSD/event key."
        ),
        "prefer_webex_device_need_exact_sfsd_bridge": (
            "Use Webex/AIS path as the stronger topology evidence and request owner-provided SFSD bridge before using SFSD cause fields."
        ),
        "topology_supported_owner_approval_needed": (
            "Ask topology owner to approve the SFSD candidate as same AIS path before using it as lifecycle/cause context."
        ),
        "do_not_bridge_time_gap_too_large": (
            "Do not bridge the nearest SFSD row because the time delta is outside the bridge window; keep as AIS-side/source-missing review."
        ),
        "same_device_bridge_review_needed": (
            "Review the same-device candidate with the source owner before accepting it as context."
        ),
        "same_feeder_context_only": (
            "Use as feeder-level context only; continue searching for exact device/event key."
        ),
    }
    return actions.get(decision, "Manual source-owner review required before model use.")


def _final_gap_model_decision(decision: str) -> str:
    if decision in {"topology_supported_owner_approval_needed", "same_device_bridge_review_needed"}:
        return "candidate_feature_after_owner_approval"
    return "blocked_for_model_training"


def _gap_decision_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    final_decisions = Counter(row.get("final_decision") or "unknown" for row in rows)
    model_decisions = Counter(row.get("model_decision") or "unknown" for row in rows)
    return {
        "rows": len(rows),
        "final_decision_counts": dict(final_decisions.most_common()),
        "model_decision_counts": dict(model_decisions.most_common()),
        "top_feeders": dict(Counter(row.get("feeder") or "<blank>" for row in rows).most_common(8)),
        "recommendation": _gap_decision_recommendation(final_decisions),
    }


def _gap_decision_recommendation(decisions: Counter[str]) -> str:
    if decisions.get("reject_sfsd_candidate_webex_device_confirmed", 0):
        return "Reject invalid SFSD candidate bridge rows first; request exact SFSD/event key from source owner."
    if decisions.get("do_not_bridge_time_gap_too_large", 0):
        return "Do not use far SFSD candidates as lifecycle features; keep AIS-side/source-missing review open."
    if decisions.get("topology_supported_owner_approval_needed", 0):
        return "Approve only the topology-supported rows before using SFSD cause/lifecycle context."
    return "Keep all rows shadow-only until owner approval is recorded."


def _render_gap_decision_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# SFSD Gap Decision Pack",
        "",
        "Purpose: combine SFSD gap resolution with live source trace evidence into final shadow-only review decisions.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- Recommendation: {summary['recommendation']}",
        "- Production send remains blocked.",
        "",
        "## Final Decisions",
        "",
        "| Final decision | Rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["final_decision_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Decision Rows",
            "",
            "| Rank | Feeder | Webex device | SFSD candidate | Webex trace | Candidate trace | Final decision | Final action |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows[:20]:
        lines.append(
            "| {rank} | {feeder} | {webex} | {candidate} | {webex_trace} | {candidate_trace} | `{decision}` | {action} |".format(
                rank=row.get("review_rank", ""),
                feeder=row.get("feeder", ""),
                webex=row.get("webex_device_id", ""),
                candidate=row.get("sfsd_candidate_device_id", ""),
                webex_trace=row.get("source_webex_trace_result", ""),
                candidate_trace=row.get("source_candidate_trace_result", ""),
                decision=row.get("final_decision", ""),
                action=row.get("final_action", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- AIS outage/restore remains the customer-facing truth source.",
            "- Source trace confirms topology context only; it does not create production send approval.",
            "- This report excludes PEANO lists, raw Webex text, room IDs, tokens, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


def _infer_device_type(device_id: str) -> str:
    normalized = normalize_device_id(device_id) or ""
    if "VB" in normalized or normalized.endswith("CB"):
        return "CB"
    if "VR" in normalized or re.search(r"R-\d+", normalized):
        return "Recloser"
    if "VS" in normalized or "VF" in normalized or re.search(r"F[-/]\d+", normalized):
        return "Switch"
    if normalized.startswith("TR") or re.search(r"\d{2}-\d+", normalized):
        return "Transformer"
    return "Unknown"


def _min_rank(left: Any, right: Any) -> str:
    left_int = _to_sort_int(left)
    right_int = _to_sort_int(right)
    if left_int == 0:
        return str(right or "")
    if right_int == 0:
        return str(left or "")
    return str(min(left_int, right_int))


def _first(row: dict[str, Any], *aliases: str) -> Any:
    normalized = {_normalize_key(key): value for key, value in row.items()}
    suffix = {}
    for key, value in row.items():
        short = str(key).rsplit(".", 1)[-1]
        suffix[_normalize_key(short)] = value
    for alias in aliases:
        if alias in row:
            return row[alias]
        key = _normalize_key(alias)
        if key in normalized:
            return normalized[key]
        if key in suffix:
            return suffix[key]
    return None


def _parse_sfsd_datetime(value: Any):
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed
    text = _clean_text(value)
    if not text:
        return None
    for fmt in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %I:%M:%S %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _load_sfsd_model_context(template: str | Path) -> tuple[str, str]:
    path = Path(template)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            request = item.get("request")
            if not request:
                continue
            try:
                request_payload = json.loads(request) if isinstance(request, str) else request
            except (TypeError, json.JSONDecodeError):
                continue
            model_id = _clean_text(request_payload.get("modelId"))
            if model_id:
                return model_id, _clean_text(request_payload.get("userPreferredLocale")) or "en-US"
    if isinstance(payload, dict):
        model_id = _clean_text(payload.get("modelId"))
        if model_id:
            return model_id, _clean_text(payload.get("userPreferredLocale")) or "en-US"
        models = payload.get("models")
        if isinstance(models, list):
            for model in models:
                if isinstance(model, dict) and model.get("id"):
                    return str(model["id"]), _clean_text(payload.get("userPreferredLocale")) or "en-US"
        exploration = payload.get("exploration")
        if isinstance(exploration, dict) and exploration.get("id"):
            return str(exploration["id"]), _clean_text(payload.get("userPreferredLocale")) or "en-US"
    return "169742226", "en-US"


def _last_http_status(headers_path: Path) -> int | None:
    if not headers_path.exists():
        return None
    status = None
    for line in headers_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
    return status


def _normalize_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _optional_float(value: Any) -> float | None:
    text = _clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    return _optional_float(value)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _dedupe(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _dedupe_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    seen = set()
    for event_number, source in values:
        key = (event_number, source)
        if event_number and key not in seen:
            output.append(key)
            seen.add(key)
    return output


def _to_sort_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0
