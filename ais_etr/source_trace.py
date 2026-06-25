from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import re
import time
from typing import Any
import urllib.parse
import urllib.request

import pandas as pd

from .registry import REGISTRY_SHEET
from .utils import normalize_device_id, normalize_feeder


DEFAULT_GIS_BASE_URL = "http://172.16.184.233/arcgis/rest/services"
DEFAULT_TRACE_DOWN_URL = (
    "http://172.16.184.233/arcgis/rest/services/PEA/MapServer/exts/TraceDownHV_LV/TraceDownHV_LV"
)

DEVICE_LAYERS = {
    "CB": (11,),
    "RECLOSER": (14,),
    "SWITCH": (16,),
    "TRANSFORMER": (17,),
}
FALLBACK_DEVICE_LAYERS = (11, 14, 16, 17)
LAYER_DEVICE_TYPES = {
    11: "CB",
    14: "Recloser",
    16: "Switch",
    17: "Transformer",
}

SOURCE_TRACE_COLUMNS = [
    "priority_rank",
    "device_type",
    "device_id",
    "feeder",
    "event_count",
    "device_query_status",
    "device_layer_id",
    "device_layer_name",
    "device_found_count",
    "device_feeder",
    "device_location",
    "device_geometry_found",
    "trace_called",
    "trace_status",
    "trace_message",
    "trace_layer_counts",
    "downstream_feature_count",
    "downstream_meter_count",
    "downstream_transformer_count",
    "ais_registry_hits",
    "ais_confident_hits",
    "ais_no_meter_hits",
    "trace_exceeded_threshold_layers",
    "evidence_level",
    "source_trace_result",
    "trace_interpretation",
    "next_action",
    "redacted_trace_path",
]


class ArcGisTraceClient:
    def __init__(
        self,
        base_url: str = DEFAULT_GIS_BASE_URL,
        trace_url: str = DEFAULT_TRACE_DOWN_URL,
        *,
        timeout_seconds: float = 60.0,
        sleep_seconds: float = 0.35,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.trace_url = trace_url
        self.timeout_seconds = timeout_seconds
        self.sleep_seconds = sleep_seconds
        self.retries = retries

    def query_layer(
        self,
        layer_id: int,
        where: str,
        *,
        out_fields: str = "*",
        return_geometry: bool = True,
        result_record_count: int = 10,
    ) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true" if return_geometry else "false",
                "resultRecordCount": str(result_record_count),
                "f": "pjson",
            }
        )
        url = f"{self.base_url}/PEA/MapServer/{layer_id}/query?{params}"
        return self._fetch_json(url)

    def trace_downstream(self, geometry: dict[str, Any]) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "geometry": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
                "f": "pjson",
            }
        )
        return self._fetch_json(f"{self.trace_url}?{params}")

    def _fetch_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(max(1, self.retries)):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "AIS-ETR-SourceTrace/1.0"})
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    text = response.read().decode("utf-8", errors="replace")
                if self.sleep_seconds:
                    time.sleep(self.sleep_seconds)
                return json.loads(text)
            except Exception as exc:  # pragma: no cover - exercised through live CLI only
                last_error = exc
                if attempt + 1 < max(1, self.retries):
                    time.sleep(1.5 * (attempt + 1))
        return {"error": {"message": str(last_error) if last_error else "unknown ArcGIS fetch error"}}


def trace_downstream_peanos_for_device(
    device_type: str,
    device_id: str,
    feeder: str | None,
    *,
    client: ArcGisTraceClient | None = None,
    base_url: str = DEFAULT_GIS_BASE_URL,
    trace_url: str = DEFAULT_TRACE_DOWN_URL,
    timeout_seconds: float = 60.0,
    sleep_seconds: float = 0.35,
) -> dict[str, Any]:
    trace_client = client or ArcGisTraceClient(
        base_url=base_url,
        trace_url=trace_url,
        timeout_seconds=timeout_seconds,
        sleep_seconds=sleep_seconds,
    )
    normalized_device = normalize_device_id(device_id) or ""
    normalized_feeder = normalize_feeder(feeder) or ""
    if not normalized_device:
        return {"status": "missing_device", "peanos": set(), "device": {}, "message": "missing device id"}

    device_match = _find_device(trace_client, device_type, normalized_device, normalized_feeder)
    device_row = device_match.get("row") or {}
    feature = device_match.get("feature")
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if device_row.get("device_query_status") != "found":
        return {
            "status": str(device_row.get("device_query_status") or "not_found"),
            "peanos": set(),
            "device": device_row,
            "message": str(device_row.get("trace_message") or ""),
        }
    if not geometry or "x" not in geometry or "y" not in geometry:
        return {
            "status": "device_without_geometry",
            "peanos": set(),
            "device": device_row,
            "message": "device has no traceable point geometry",
        }

    trace_geometry = {
        "x": geometry["x"],
        "y": geometry["y"],
        "spatialReference": geometry.get("spatialReference") or {"wkid": 102100},
    }
    trace_result = trace_client.trace_downstream(trace_geometry)
    if trace_result.get("error"):
        return {
            "status": "trace_error",
            "peanos": set(),
            "device": device_row,
            "message": _safe_error_message(trace_result.get("error")),
        }
    return {
        "status": "success" if trace_result.get("success") is not False else "not_success",
        "peanos": _extract_trace_peanos(trace_result),
        "device": device_row,
        "message": str(trace_result.get("message") or ""),
    }


def trace_no_match_candidates_from_source_system(
    candidates_csv: str | Path,
    upstream_xlsx: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
    *,
    redacted_dir: str | Path | None = None,
    base_url: str = DEFAULT_GIS_BASE_URL,
    trace_url: str = DEFAULT_TRACE_DOWN_URL,
    timeout_seconds: float = 60.0,
    sleep_seconds: float = 0.35,
    limit: int | None = None,
    client: ArcGisTraceClient | None = None,
) -> dict[str, Any]:
    candidates = _read_candidates(candidates_csv)
    if limit is not None:
        candidates = candidates[: max(0, limit)]
    asset_sets = _load_asset_sets(upstream_xlsx)
    trace_client = client or ArcGisTraceClient(
        base_url=base_url,
        trace_url=trace_url,
        timeout_seconds=timeout_seconds,
        sleep_seconds=sleep_seconds,
    )
    redacted_path = Path(redacted_dir) if redacted_dir else None
    if redacted_path:
        redacted_path.mkdir(parents=True, exist_ok=True)

    rows = []
    for candidate in candidates:
        row, redacted_summary = _trace_candidate(candidate, asset_sets, trace_client)
        if redacted_path:
            summary_file = redacted_path / _redacted_filename(row)
            summary_file.write_text(json.dumps(redacted_summary, ensure_ascii=False, indent=2), encoding="utf-8")
            row["redacted_trace_path"] = str(summary_file)
        rows.append(row)

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_TRACE_COLUMNS)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in SOURCE_TRACE_COLUMNS} for row in rows)

    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(rows), encoding="utf-8-sig")

    return {
        "candidates": len(candidates),
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "redacted_dir": str(redacted_path) if redacted_path else None,
        "source_trace_result_counts": dict(Counter(row["source_trace_result"] for row in rows)),
        "evidence_level_counts": dict(Counter(row["evidence_level"] for row in rows)),
        "ais_confident_hit_candidates": sum(1 for row in rows if int(row["ais_confident_hits"] or 0) > 0),
        "ais_registry_hit_candidates": sum(1 for row in rows if int(row["ais_registry_hits"] or 0) > 0),
    }


def _trace_candidate(
    candidate: dict[str, str],
    asset_sets: dict[str, set[str]],
    client: ArcGisTraceClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    device_type = (candidate.get("device_type") or "").strip()
    device_id = normalize_device_id(candidate.get("device_id")) or ""
    feeder = normalize_feeder(candidate.get("feeder")) or ""
    row: dict[str, Any] = {
        "priority_rank": candidate.get("priority_rank") or "",
        "device_type": device_type,
        "device_id": device_id,
        "feeder": feeder,
        "event_count": _int(candidate.get("event_count")),
        "device_query_status": "",
        "device_layer_id": "",
        "device_layer_name": "",
        "device_found_count": 0,
        "device_feeder": "",
        "device_location": "",
        "device_geometry_found": False,
        "trace_called": False,
        "trace_status": "",
        "trace_message": "",
        "trace_layer_counts": "{}",
        "downstream_feature_count": 0,
        "downstream_meter_count": 0,
        "downstream_transformer_count": 0,
        "ais_registry_hits": 0,
        "ais_confident_hits": 0,
        "ais_no_meter_hits": 0,
        "trace_exceeded_threshold_layers": "",
        "redacted_trace_path": "",
    }

    if not device_id:
        _classify_row(row, "missing_device")
        return row, _redacted_summary(row, None)

    device_match = _find_device(client, device_type, device_id, feeder)
    row.update(device_match["row"])
    feature = device_match.get("feature")
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if not geometry or "x" not in geometry or "y" not in geometry:
        _classify_row(row, "device_without_geometry")
        return row, _redacted_summary(row, None)

    trace_geometry = {
        "x": geometry["x"],
        "y": geometry["y"],
        "spatialReference": geometry.get("spatialReference") or {"wkid": 102100},
    }
    row["trace_called"] = True
    trace_result = client.trace_downstream(trace_geometry)
    if trace_result.get("error"):
        row["trace_status"] = "error"
        row["trace_message"] = _safe_error_message(trace_result.get("error"))
        _classify_row(row, "trace_error")
        return row, _redacted_summary(row, trace_result)

    row["trace_status"] = "success" if trace_result.get("success") is not False else "not_success"
    row["trace_message"] = str(trace_result.get("message") or "")
    summary = _summarize_trace(trace_result, asset_sets)
    row.update(summary["row"])
    _classify_row(row, "trace_success")
    return row, _redacted_summary(row, trace_result, summary["layers"])


def _find_device(
    client: ArcGisTraceClient,
    device_type: str,
    device_id: str,
    feeder: str,
) -> dict[str, Any]:
    ordered_layers = _device_layers_for_search(device_type)
    all_features: list[tuple[int, dict[str, Any]]] = []
    query_errors = []
    for layer_id in ordered_layers:
        data = client.query_layer(layer_id, f"FACILITYID='{_sql_escape(device_id)}'")
        if data.get("error"):
            query_errors.append(f"{layer_id}:{_safe_error_message(data.get('error'))}")
            continue
        for feature in data.get("features") or []:
            all_features.append((layer_id, feature))

    if not all_features:
        status = "not_found" if not query_errors else "error"
        return {
            "row": {
                "device_query_status": status,
                "device_found_count": 0,
                "trace_status": "not_called",
                "trace_message": "; ".join(query_errors),
            },
            "feature": None,
        }

    selected_layer, selected_feature = _select_device_feature(all_features, feeder)
    attrs = selected_feature.get("attributes") or {}
    geom = selected_feature.get("geometry") or {}
    return {
        "row": {
            "device_query_status": "found",
            "device_layer_id": selected_layer,
            "device_layer_name": LAYER_DEVICE_TYPES.get(selected_layer, f"Layer {selected_layer}"),
            "device_found_count": len(all_features),
            "device_feeder": normalize_feeder(attrs.get("FEEDERID")) or _clean(attrs.get("FEEDERID")),
            "device_location": _clean(attrs.get("LOCATION")),
            "device_geometry_found": "x" in geom and "y" in geom,
        },
        "feature": selected_feature,
    }


def _summarize_trace(trace_result: dict[str, Any], asset_sets: dict[str, set[str]]) -> dict[str, Any]:
    layer_counts: Counter[str] = Counter()
    exceeded_layers = []
    downstream_feature_count = 0
    downstream_meter_count = 0
    downstream_transformer_count = 0
    registry_hits: set[str] = set()
    confident_hits: set[str] = set()
    no_meter_hits: set[str] = set()
    layer_summaries: list[dict[str, Any]] = []

    for group in trace_result.get("traceResult") or []:
        if not isinstance(group, dict):
            continue
        name = _short_layer_name(group.get("name") or group.get("id") or "unknown")
        layer_id = group.get("id")
        features = group.get("features") or []
        feature_count = len(features)
        downstream_feature_count += feature_count
        layer_counts[name] += feature_count
        if group.get("exceededThreshold"):
            exceeded_layers.append(name)
        if "TRANSFORMER" in name.upper() or layer_id == 17:
            downstream_transformer_count += feature_count

        peano_count = 0
        for feature in features:
            attrs = feature.get("attributes") or {}
            peano = _normalize_peano(attrs.get("PEANO"))
            if not peano:
                continue
            peano_count += 1
            downstream_meter_count += 1
            if peano in asset_sets["all"]:
                registry_hits.add(peano)
            if peano in asset_sets["confident"]:
                confident_hits.add(peano)
            if peano in asset_sets["no_meter"]:
                no_meter_hits.add(peano)
        layer_summaries.append(
            {
                "id": layer_id,
                "name": name,
                "features": feature_count,
                "peano_features": peano_count,
                "exceeded_threshold": bool(group.get("exceededThreshold")),
            }
        )

    return {
        "row": {
            "trace_layer_counts": json.dumps(dict(layer_counts), ensure_ascii=False, sort_keys=True),
            "downstream_feature_count": downstream_feature_count,
            "downstream_meter_count": downstream_meter_count,
            "downstream_transformer_count": downstream_transformer_count,
            "ais_registry_hits": len(registry_hits),
            "ais_confident_hits": len(confident_hits),
            "ais_no_meter_hits": len(no_meter_hits),
            "trace_exceeded_threshold_layers": ";".join(exceeded_layers),
        },
        "layers": layer_summaries,
    }


def _extract_trace_peanos(trace_result: dict[str, Any]) -> set[str]:
    peanos: set[str] = set()
    for group in trace_result.get("traceResult") or []:
        if not isinstance(group, dict):
            continue
        for feature in group.get("features") or []:
            attrs = feature.get("attributes") or {}
            peano = _normalize_peano(attrs.get("PEANO"))
            if peano:
                peanos.add(peano)
    return peanos


def _classify_row(row: dict[str, Any], state: str) -> None:
    if state == "missing_device":
        row.update(
            {
                "evidence_level": "weak",
                "source_trace_result": "cannot_trace_missing_device",
                "trace_interpretation": "The Webex/parser candidate has no normalized protection device id to query in GIS.",
                "next_action": "Review the original Webex message and add a parser pattern only if the text contains a real device id.",
            }
        )
        return
    if row.get("device_query_status") == "not_found":
        row.update(
            {
                "evidence_level": "source_negative",
                "source_trace_result": "source_device_not_found",
                "trace_interpretation": "The source GIS did not find this FACILITYID in CB/Recloser/Switch/Transformer layers.",
                "next_action": "Check whether Webex uses an alias, typo, or a device family not covered by the current layer search.",
            }
        )
        return
    if row.get("device_query_status") == "error":
        row.update(
            {
                "evidence_level": "weak",
                "source_trace_result": "source_device_query_error",
                "trace_interpretation": "The source GIS query returned an API error before downstream trace could run.",
                "next_action": "Retry from the PEA network or ask the GIS owner to verify ArcGIS service health.",
            }
        )
        return
    if state == "device_without_geometry":
        row.update(
            {
                "evidence_level": "weak",
                "source_trace_result": "source_device_without_geometry",
                "trace_interpretation": "The source GIS found the device but did not return a point geometry for downstream trace.",
                "next_action": "Ask the GIS owner to verify geometry for this device or provide a topology trace from DMS/GIS.",
            }
        )
        return
    if state == "trace_error":
        row.update(
            {
                "evidence_level": "weak",
                "source_trace_result": "source_trace_api_error",
                "trace_interpretation": "The source GIS found the device, but TraceDownHV_LV failed for its geometry.",
                "next_action": "Retry the trace and escalate the error message to the GIS topology owner if it persists.",
            }
        )
        return

    if int(row.get("ais_confident_hits") or 0) > 0:
        row.update(
            {
                "evidence_level": "strong",
                "source_trace_result": "source_trace_confirms_confident_ais_downstream",
                "trace_interpretation": "Live source-system downstream trace found confident AIS registry meters below this device.",
                "next_action": "Repair the AIS protection mapping for these traced meters, rebuild registry, and rerun Webex replay before enabling confident notifications.",
            }
        )
    elif int(row.get("ais_registry_hits") or 0) > 0:
        row.update(
            {
                "evidence_level": "medium",
                "source_trace_result": "source_trace_finds_only_non_confident_ais_downstream",
                "trace_interpretation": "Live source-system downstream trace found AIS registry PEANO values, but not confident OK assets.",
                "next_action": "Prioritize these PEANO values in the NO_METER/data-repair backlog before using them for customer impact matching.",
            }
        )
    elif int(row.get("downstream_meter_count") or 0) > 0:
        row.update(
            {
                "evidence_level": "source_negative",
                "source_trace_result": "source_trace_no_current_ais_downstream",
                "trace_interpretation": "Live source-system downstream trace found downstream meters, but none match the current AIS pilot registry.",
                "next_action": "Treat this device as outside current AIS pilot scope unless AIS provides additional PEANO/site ids.",
            }
        )
    else:
        row.update(
            {
                "evidence_level": "source_negative",
                "source_trace_result": "source_trace_no_downstream_meters",
                "trace_interpretation": "Live source-system trace returned no downstream PEANO-bearing meter features for this device.",
                "next_action": "Verify the device type and topology with GIS/DMS owner if this event should affect AIS.",
            }
        )


def _read_candidates(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_asset_sets(path: str | Path) -> dict[str, set[str]]:
    df = pd.read_excel(path, sheet_name=REGISTRY_SHEET, dtype=str).fillna("")
    status_col = _pick_column(df, ("status", "trace_status"), fallback_index=28)
    all_peanos: set[str] = set()
    confident: set[str] = set()
    no_meter: set[str] = set()
    for _, row in df.iterrows():
        peano = _normalize_peano(row.get("PEANO"))
        if not peano:
            continue
        status = _clean(row.get(status_col)).upper()
        all_peanos.add(peano)
        if status == "OK":
            confident.add(peano)
        elif status == "NO_METER":
            no_meter.add(peano)
    return {"all": all_peanos, "confident": confident, "no_meter": no_meter}


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...], fallback_index: int | None = None) -> str:
    lowered = {str(column).strip().lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    if fallback_index is not None and 0 <= fallback_index < len(df.columns):
        return str(df.columns[fallback_index])
    raise ValueError(f"Could not find any of the columns: {', '.join(candidates)}")


def _device_layers_for_search(device_type: str) -> tuple[int, ...]:
    normalized = normalize_device_id(device_type) or ""
    primary = DEVICE_LAYERS.get(normalized, ())
    return tuple(dict.fromkeys((*primary, *FALLBACK_DEVICE_LAYERS)))


def _select_device_feature(features: list[tuple[int, dict[str, Any]]], feeder: str) -> tuple[int, dict[str, Any]]:
    if feeder:
        for layer_id, feature in features:
            attrs = feature.get("attributes") or {}
            if normalize_feeder(attrs.get("FEEDERID")) == feeder:
                return layer_id, feature
    return features[0]


def _redacted_summary(
    row: dict[str, Any],
    trace_result: dict[str, Any] | None,
    layers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "candidate": {
            "priority_rank": row.get("priority_rank"),
            "device_type": row.get("device_type"),
            "device_id": row.get("device_id"),
            "feeder": row.get("feeder"),
            "event_count": row.get("event_count"),
        },
        "device": {
            "query_status": row.get("device_query_status"),
            "layer_id": row.get("device_layer_id"),
            "layer_name": row.get("device_layer_name"),
            "found_count": row.get("device_found_count"),
            "feeder": row.get("device_feeder"),
            "location": row.get("device_location"),
            "geometry_found": row.get("device_geometry_found"),
        },
        "trace": {
            "called": row.get("trace_called"),
            "status": row.get("trace_status"),
            "message": row.get("trace_message"),
            "success": trace_result.get("success") if isinstance(trace_result, dict) else None,
            "layers": layers or [],
            "downstream_feature_count": row.get("downstream_feature_count"),
            "downstream_meter_count": row.get("downstream_meter_count"),
            "downstream_transformer_count": row.get("downstream_transformer_count"),
            "ais_registry_hits": row.get("ais_registry_hits"),
            "ais_confident_hits": row.get("ais_confident_hits"),
            "ais_no_meter_hits": row.get("ais_no_meter_hits"),
            "exceeded_threshold_layers": row.get("trace_exceeded_threshold_layers"),
        },
        "decision": {
            "evidence_level": row.get("evidence_level"),
            "source_trace_result": row.get("source_trace_result"),
            "trace_interpretation": row.get("trace_interpretation"),
            "next_action": row.get("next_action"),
        },
    }


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    result_counts = Counter(row["source_trace_result"] for row in rows)
    lines = [
        "# Source-System No-match Downstream Trace Audit",
        "",
        "This audit queries the live PEA ArcGIS source system and runs `TraceDownHV_LV` from each no-match protection device geometry.",
        "It reports counts only and intentionally excludes raw PEANO lists, Webex raw text, room ids, and secrets.",
        "",
        "## Summary",
        "",
        "| Source trace result | Candidates | Events | AIS registry hit candidates | AIS confident hit candidates |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for result, count in result_counts.most_common():
        scoped = [row for row in rows if row["source_trace_result"] == result]
        events = sum(int(row["event_count"] or 0) for row in scoped)
        registry_hit_candidates = sum(1 for row in scoped if int(row["ais_registry_hits"] or 0) > 0)
        confident_hit_candidates = sum(1 for row in scoped if int(row["ais_confident_hits"] or 0) > 0)
        lines.append(f"| {result} | {count} | {events} | {registry_hit_candidates} | {confident_hit_candidates} |")

    lines.extend(
        [
            "",
            "## Priority Candidates",
            "",
            "| Rank | Device | Feeder | Events | Device layer | Downstream meters | AIS registry hits | AIS confident hits | Result | Next action |",
            "| ---: | --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in sorted(rows, key=lambda item: int(item["priority_rank"] or 999999)):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["priority_rank"]),
                    str(row["device_id"] or "<missing>"),
                    str(row["feeder"] or "<missing>"),
                    str(row["event_count"] or 0),
                    str(row["device_layer_name"] or "<not found>"),
                    str(row["downstream_meter_count"] or 0),
                    str(row["ais_registry_hits"] or 0),
                    str(row["ais_confident_hits"] or 0),
                    str(row["source_trace_result"]),
                    str(row["next_action"]).replace("|", "\\|"),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Reading Notes",
            "",
            "- `source_trace_confirms_confident_ais_downstream` is the strongest evidence that the current registry protection mapping needs repair.",
            "- `source_trace_finds_only_non_confident_ais_downstream` means the source trace sees AIS PEANO values, but they are still non-confident/backlog in the AIS registry.",
            "- `source_trace_no_current_ais_downstream` means the device has downstream meters in GIS, but none match the current AIS pilot PEANO set.",
            "- The report proves downstream topology for the queried device geometry; it does not claim production readiness or authorize real AIS notification sends.",
        ]
    )
    return "\n".join(lines)


def _redacted_filename(row: dict[str, Any]) -> str:
    rank = re.sub(r"[^A-Za-z0-9_-]+", "_", str(row.get("priority_rank") or "x")).strip("_")
    device = re.sub(r"[^A-Za-z0-9_-]+", "_", str(row.get("device_id") or "missing")).strip("_")
    return f"{rank}_{device}_source_trace_summary.json"


def _short_layer_name(value: Any) -> str:
    text = str(value or "unknown").strip()
    return text.split(":", 1)[0] if ":" in text else text


def _normalize_peano(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if re.fullmatch(r"\d+\\.0", text):
        text = text[:-2]
    return text


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _safe_error_message(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message") or error.get("details") or error
    else:
        message = error
    return str(message)[:300]
