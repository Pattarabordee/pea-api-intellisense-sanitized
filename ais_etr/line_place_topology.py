from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .line_ingest import sanitize_line_text
from .utils import normalize_device_id, normalize_feeder, split_device_list


DEFAULT_LINE_PLACE_REVIEW_SOURCE = "runtime/line_parser_shadow_review_queue_for_labeling.csv"
DEFAULT_LINE_PLACE_OUTPUT = "runtime/line_place_topology_lookup.csv"
DEFAULT_LINE_PLACE_ENRICHED_OUTPUT = "runtime/line_parser_shadow_review_queue_for_labeling_topology.csv"
DEFAULT_LINE_PLACE_MARKDOWN_OUTPUT = "runtime/line_place_topology_lookup.md"
DEFAULT_LINE_PLACE_OWNER_REVIEW_OUTPUT = "runtime/line_place_topology_owner_review_request.csv"
DEFAULT_LINE_PLACE_OWNER_REVIEW_MARKDOWN_OUTPUT = "runtime/line_place_topology_owner_review_request.md"

UPSTREAM_SHEET = "Upstream Trace"
LOOKUP_COLUMNS = (
    "message_ref",
    "created",
    "source_kind",
    "model_event_probability",
    "text_sanitized_excerpt",
    "place_queries",
    "feeder_mentions",
    "device_mentions",
    "lookup_status",
    "topology_evidence_level",
    "matched_place_query",
    "matched_source",
    "matched_assets_count",
    "confident_asset_count",
    "primary_feeder",
    "matched_feeders",
    "transformer_ids",
    "transformer_count",
    "recloser_ids",
    "recloser_count",
    "switch_sample_ids",
    "switch_count",
    "cb_ids",
    "cb_count",
    "match_reason",
)
OWNER_REVIEW_COLUMNS = (
    "review_priority",
    "message_ref",
    "lookup_status",
    "topology_evidence_level",
    "text_sanitized_excerpt",
    "place_queries",
    "feeder_mentions",
    "current_primary_feeder",
    "current_transformer_ids",
    "current_recloser_ids",
    "current_switch_sample_ids",
    "current_cb_ids",
    "owner_verified_status",
    "owner_feeder",
    "owner_transformer_ids",
    "owner_recloser_ids",
    "owner_switch_ids",
    "owner_cb_ids",
    "owner_source_ref",
    "owner_notes",
)

_THAI = "\u0e00-\u0e7f"
_PLACE_TEXT = rf"[{_THAI}A-Za-z0-9./\-\s]{{1,64}}"
_DEVICE_RE = re.compile(r"\b[A-Z]{3}\d{2}(?:[A-Z]{1,4}[-/][A-Z0-9/.-]+)?\b", re.IGNORECASE)
_FEEDER_RE = re.compile(r"\b[A-Z]{3}\d{2}\b", re.IGNORECASE)
_REDACTION_MARKER_RE = re.compile(r"\[[A-Z_]+_REDACTED\]")
_FILE_NOISE_RE = re.compile(r"\b\S+\.(?:csv|docx?|heic|jpe?g|mov|mp4|pdf|png|pptx?|txt|xlsx?)\b", re.IGNORECASE)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_EMBEDDED_PHONE_RE = re.compile(r"(?:\+?66|0)[\s.-]?\d(?:[\s.-]?\d){7,8}")

_LOCATION_MARKERS = (
    "บ้าน",
    "วัด",
    "โรงเรียน",
    "รร",
    "ร้าน",
    "ประปา",
    "สถานีวิทยุ",
    "สถานี",
    "ตลาดสด",
    "ตลาด",
    "ราชมงคล",
    "มทร",
    "คณะ",
    "ป้อมยาม",
    "ป้อมตำรวจ",
    "ป้อม",
    "ฟาร์ม",
    "แพลนท์",
    "เซเว่น",
    "ปตท",
    "สฟฟ",
)
_EXTRA_LOCATION_MARKERS = (
    "\u0e1b\u0e31\u0e49\u0e21",
    "\u0e1b\u0e31\u0e4a\u0e21",
    "\u0e41\u0e1f\u0e25\u0e0a",
    "\u0e19\u0e49\u0e33\u0e43\u0e2a",
    "\u0e04\u0e23\u0e31\u0e27",
    "\u0e2b\u0e08\u0e01",
    "\u0e40\u0e17\u0e28\u0e1a\u0e32\u0e25",
    "\u0e2d\u0e1a\u0e15",
    "\u0e42\u0e23\u0e07\u0e2a\u0e35",
    "\u0e23\u0e35\u0e2a\u0e2d\u0e23\u0e4c\u0e17",
    "\u0e2d\u0e39\u0e48",
    "\u0e2a\u0e23\u0e30\u0e27\u0e48\u0e32\u0e22\u0e19\u0e49\u0e33",
)
_RELATION_MARKERS = ("หน้า", "หลัง", "ตรงข้าม", "ทางเข้า", "ก่อนถึง", "เลย", "เส้น", "แถว", "ที่อยู่")
_PLACE_PATTERNS = tuple(
    re.compile(re.escape(marker) + r"\s*" + _PLACE_TEXT, re.IGNORECASE)
    for marker in (*_LOCATION_MARKERS, *_EXTRA_LOCATION_MARKERS, *_RELATION_MARKERS)
)
_ADDRESS_PATTERNS = (
    re.compile(r"ต\.\s*" + _PLACE_TEXT, re.IGNORECASE),
    re.compile(r"อ\.\s*" + _PLACE_TEXT, re.IGNORECASE),
)

_NOISE_TERMS = (
    "รับแจ้ง",
    "แจ้ง",
    "ไฟช็อต",
    "ไฟไม่ครบเฟส",
    "ไฟดับ",
    "ไฟตก",
    "มีไฟไหม้",
    "สายหลุด",
    "สายขาด",
    "สายแรงสูงขาด",
    "ไลน์เมน",
    "ลูกถ้วย",
    "ก้นดรอป",
    "หม้อแปลง",
    "ชำรุด",
    "ประกาย",
    "เฟส",
    "ผู้แจ้ง",
    "หมายเลขโทรศัพท์ติดต่อกลับ",
    "โทรศัพท์",
    "โทร",
    "เบอร์",
    "ช่าง",
    "แก้ไข",
    "ดำเนินการ",
    "เรียบร้อย",
    "ครับ",
    "ค่ะ",
    "งาน",
    "ติดตั้ง",
    "ทำใบเบิก",
    "ให้ด้วย",
    "ขออนุญาต",
)
_GENERIC_QUERY_TEXTS = (
    "รับแจ้งไฟช็อต",
    "รับแจ้งไฟไม่ครบเฟส",
    "ไฟช็อต",
    "ไฟไม่ครบเฟส",
    "สายหลุด",
    "สายขาด",
        "ไลน์เมน",
        "ร้าน",
        "วัด",
        "บ้าน",
        "ตลาด",
        "สถานี",
        "ป้อม",
        "โรงเรียน",
        "ประปา",
        "ฟาร์ม",
        "แพลนท์",
        "หน้า",
        "หลัง",
        "ตรงข้าม",
        "ทางเข้า",
        "แถว",
        "เส้น",
        "ที่อยู่",
        "ต",
        "อ",
        "สำนักงาน",
    "ติดตั้ง",
    "ผู้แจ้ง",
        "สกลนคร",
        "จ.สกลนคร",
        "พังโคน",
        "วาริชภูมิ",
        "นิคมน้ำอูน",
        "อ.พังโคน",
        "อ.วาริชภูมิ",
        "อ.นิคมน้ำอูน",
)
_BROAD_PREFIXES = ("ต.", "อ.")

_COLUMN_ALIASES = {
    "peano": ("PEANO", "peano"),
    "meter_location": ("สถานที่ Meter", "meter_location", "METER_LOCATION"),
    "feeder": ("Feeder ID", "feeder", "FEEDERID", "METER_FEEDERID"),
    "moo": ("หมู่", "moo", "MOO"),
    "subdistrict": ("ตำบล", "subdistrict", "TUMBOL"),
    "district": ("อำเภอ", "district", "AMPHOE"),
    "tx_id": ("TX: FACILITYID", "tx_facilityid", "TX_FACILITYID"),
    "tx_location": ("TX: สถานที่", "tx_location", "TX_LOCATION"),
    "tx_feeder": ("TX: Feeder", "tx_feeder", "TX_FEEDERID"),
    "rc_ids": ("RC: FACILITYID", "rc_facilityids", "RC_FACILITYIDS"),
    "rc_location": ("RC: สถานที่", "rc_location", "RC_LOCATION"),
    "sw_ids": ("SW: FACILITYID", "sw_facilityids", "SW_FACILITYIDS"),
    "sw_location": ("SW: สถานที่", "sw_location", "SW_LOCATION"),
    "cb_ids": ("CB: FACILITYID", "cb_facilityids", "CB_FACILITYIDS"),
    "cb_location": ("CB: สถานที่", "cb_location", "CB_LOCATION"),
    "status": ("สถานะ", "status", "trace_status", "TRACE_STATUS"),
}
_COLUMN_FALLBACKS = {
    "peano": 0,
    "meter_location": 1,
    "feeder": 2,
    "moo": 6,
    "subdistrict": 7,
    "district": 8,
    "tx_id": 9,
    "tx_feeder": 11,
    "tx_location": 15,
    "rc_ids": 17,
    "rc_location": 18,
    "sw_ids": 21,
    "sw_location": 23,
    "cb_ids": 25,
    "cb_location": 26,
    "status": 28,
}


@dataclass(frozen=True)
class TopologyAsset:
    feeder: str
    transformer_ids: tuple[str, ...]
    recloser_ids: tuple[str, ...]
    switch_ids: tuple[str, ...]
    cb_ids: tuple[str, ...]
    trace_status: str
    search_text: str


@dataclass(frozen=True)
class _Match:
    query: str
    score: int
    assets: tuple[TopologyAsset, ...]
    is_broad_query: bool


def build_line_place_topology_lookup(
    review_source: str | Path = DEFAULT_LINE_PLACE_REVIEW_SOURCE,
    upstream: str | Path = "upstream_result.xlsx",
    output: str | Path = DEFAULT_LINE_PLACE_OUTPUT,
    enriched_output: str | Path | None = DEFAULT_LINE_PLACE_ENRICHED_OUTPUT,
    markdown_output: str | Path | None = DEFAULT_LINE_PLACE_MARKDOWN_OUTPUT,
    owner_review_output: str | Path | None = DEFAULT_LINE_PLACE_OWNER_REVIEW_OUTPUT,
    owner_review_markdown_output: str | Path | None = DEFAULT_LINE_PLACE_OWNER_REVIEW_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    review_rows = _read_csv(Path(review_source))
    assets = _load_topology_assets(Path(upstream))
    lookup_rows = [_lookup_review_row(row, assets, Path(upstream).name) for row in review_rows]

    _write_csv(output, LOOKUP_COLUMNS, lookup_rows)
    if enriched_output:
        _write_enriched_review(enriched_output, review_rows, lookup_rows)
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_markdown(lookup_rows, review_source, upstream), encoding="utf-8")
    owner_review_rows = _owner_review_rows(lookup_rows)
    if owner_review_output:
        _write_csv(owner_review_output, OWNER_REVIEW_COLUMNS, owner_review_rows)
    if owner_review_markdown_output:
        Path(owner_review_markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(owner_review_markdown_output).write_text(
            _render_owner_review_markdown(owner_review_rows, review_source, upstream),
            encoding="utf-8",
        )

    status_counts = Counter(row["lookup_status"] for row in lookup_rows)
    return {
        "status": "ok",
        "mode": "shadow",
        "production_send": "blocked",
        "review_rows": len(review_rows),
        "upstream_assets": len(assets),
        "output": str(output),
        "enriched_output": str(enriched_output) if enriched_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
        "owner_review_output": str(owner_review_output) if owner_review_output else None,
        "owner_review_markdown_output": str(owner_review_markdown_output) if owner_review_markdown_output else None,
        "owner_review_rows": len(owner_review_rows),
        "lookup_status_counts": dict(sorted(status_counts.items())),
        "matched_rows": sum(1 for row in lookup_rows if row["lookup_status"].startswith("matched_")),
        "feeder_only_rows": status_counts.get("feeder_mentioned_only", 0),
    }


def extract_place_queries(text: str, max_queries: int = 8) -> list[str]:
    safe_text, _flags = sanitize_line_text(text)
    source = _strip_operational_noise(safe_text)
    candidates: list[str] = []
    for pattern in _PLACE_PATTERNS:
        candidates.extend(match.group(0) for match in pattern.finditer(source))
    if not candidates:
        for pattern in _ADDRESS_PATTERNS:
            candidates.extend(match.group(0) for match in pattern.finditer(source))

    expanded: list[str] = []
    for candidate in candidates:
        cleaned = _clean_place_phrase(candidate)
        _append_query(expanded, cleaned)
        village = _extract_village_phrase(cleaned)
        if village:
            _append_query(expanded, village)
        subdistrict = _extract_address_phrase(cleaned, "ต.")
        if subdistrict:
            _append_query(expanded, subdistrict)
        for split_query in _split_route_phrase(cleaned):
            _append_query(expanded, split_query)
        tail = _last_meaningful_token(cleaned)
        if tail:
            _append_query(expanded, tail)

    if not expanded:
        for token in _fallback_tokens(source):
            _append_query(expanded, token)
    return expanded[:max_queries]


def _lookup_review_row(row: dict[str, str], assets: list[TopologyAsset], source_name: str) -> dict[str, Any]:
    safe_excerpt = _sanitize_excerpt_value(row.get("text_sanitized_excerpt") or "", limit=10_000)
    feeder_mentions = _extract_feeders(safe_excerpt)
    device_mentions = _extract_devices(safe_excerpt)
    place_queries = extract_place_queries(safe_excerpt)
    match = _match_places(place_queries, feeder_mentions, assets)
    if match:
        status = "matched_local_place_broad" if match.is_broad_query else "matched_local_place"
        reason = "place query matched local upstream trace workbook"
        evidence = "weak" if match.is_broad_query else _evidence_level(match.assets)
        summary = _summarize_assets(match.assets)
        matched_source = f"{source_name}:place"
        matched_query = match.query
    elif feeder_mentions:
        feeder_assets = [asset for asset in assets if asset.feeder in feeder_mentions]
        status = "feeder_mentioned_only"
        reason = "explicit feeder mention only; no local place match"
        evidence = "weak" if feeder_assets else "source_negative"
        summary = _summarize_assets(feeder_assets)
        matched_source = f"{source_name}:feeder"
        matched_query = ""
    else:
        status = "no_local_match"
        reason = "no place or feeder match in local upstream trace workbook"
        evidence = "none"
        summary = _empty_summary()
        matched_source = f"{source_name}:none"
        matched_query = ""

    return {
        "message_ref": row.get("message_ref") or "",
        "created": row.get("created") or "",
        "source_kind": row.get("source_kind") or "",
        "model_event_probability": row.get("model_event_probability") or "",
        "text_sanitized_excerpt": _excerpt(safe_excerpt),
        "place_queries": "; ".join(place_queries),
        "feeder_mentions": "; ".join(feeder_mentions),
        "device_mentions": "; ".join(device_mentions),
        "lookup_status": status,
        "topology_evidence_level": evidence,
        "matched_place_query": matched_query,
        "matched_source": matched_source,
        "matched_assets_count": summary["asset_count"],
        "confident_asset_count": summary["confident_count"],
        "primary_feeder": summary["primary_feeder"],
        "matched_feeders": summary["feeders"],
        "transformer_ids": summary["transformers"],
        "transformer_count": summary["transformer_count"],
        "recloser_ids": summary["reclosers"],
        "recloser_count": summary["recloser_count"],
        "switch_sample_ids": summary["switches"],
        "switch_count": summary["switch_count"],
        "cb_ids": summary["cbs"],
        "cb_count": summary["cb_count"],
        "match_reason": reason,
    }


def _load_topology_assets(path: Path) -> list[TopologyAsset]:
    df = pd.read_excel(path, sheet_name=UPSTREAM_SHEET, dtype=str).fillna("")
    columns = {key: _pick_column(df, key) for key in _COLUMN_ALIASES}
    assets: list[TopologyAsset] = []
    for _, row in df.iterrows():
        feeder = normalize_feeder(_first(row.get(columns["feeder"]), row.get(columns["tx_feeder"]))) or ""
        search_values = [
            row.get(columns["meter_location"]),
            row.get(columns["moo"]),
            row.get(columns["subdistrict"]),
            row.get(columns["district"]),
            row.get(columns["tx_location"]),
            row.get(columns["rc_location"]),
            row.get(columns["sw_location"]),
            row.get(columns["cb_location"]),
        ]
        transformer_ids = tuple(
            item for item in (normalize_device_id(row.get(columns["tx_id"])) or "",) if item
        )
        asset = TopologyAsset(
            feeder=feeder,
            transformer_ids=transformer_ids,
            recloser_ids=split_device_list(row.get(columns["rc_ids"])),
            switch_ids=split_device_list(row.get(columns["sw_ids"])),
            cb_ids=split_device_list(row.get(columns["cb_ids"])),
            trace_status=_clean(row.get(columns["status"])).upper(),
            search_text=_normalize_query_text(" ".join(_clean(value) for value in search_values)),
        )
        if asset.feeder or asset.search_text:
            assets.append(asset)
    return assets


def _match_places(queries: list[str], feeder_mentions: tuple[str, ...], assets: list[TopologyAsset]) -> _Match | None:
    if not queries:
        return None
    matches: list[_Match] = []
    for query in queries:
        normalized = _normalize_query_text(query)
        if not _usable_query(normalized):
            continue
        preferred = [
            asset
            for asset in assets
            if asset.feeder in feeder_mentions and _query_matches_asset(normalized, asset)
        ]
        candidates = preferred or [asset for asset in assets if _query_matches_asset(normalized, asset)]
        if not candidates:
            continue
        score = len(normalized) + (20 if preferred else 0) + min(15, len(candidates))
        is_broad = _is_broad_query(query)
        if is_broad:
            score -= 10
        matches.append(_Match(query=query, score=score, assets=tuple(candidates), is_broad_query=is_broad))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item.score, item.is_broad_query, item.query))
    return matches[0]


def _query_matches_asset(normalized_query: str, asset: TopologyAsset) -> bool:
    if not normalized_query or not asset.search_text:
        return False
    if normalized_query in asset.search_text:
        return True
    return len(asset.search_text) >= 6 and asset.search_text in normalized_query


def _summarize_assets(assets: list[TopologyAsset] | tuple[TopologyAsset, ...]) -> dict[str, Any]:
    if not assets:
        return _empty_summary()
    feeders = Counter(asset.feeder for asset in assets if asset.feeder)
    transformer_ids = _unique_device_ids(device for asset in assets for device in asset.transformer_ids)
    recloser_ids = _unique_device_ids(device for asset in assets for device in asset.recloser_ids)
    switch_ids = _unique_device_ids(device for asset in assets for device in asset.switch_ids)
    cb_ids = _unique_device_ids(device for asset in assets for device in asset.cb_ids)
    return {
        "asset_count": len(assets),
        "confident_count": sum(1 for asset in assets if asset.trace_status == "OK"),
        "primary_feeder": feeders.most_common(1)[0][0] if feeders else "",
        "feeders": _format_counts(feeders),
        "transformers": _format_devices(transformer_ids),
        "transformer_count": len(transformer_ids),
        "reclosers": _format_devices(recloser_ids),
        "recloser_count": len(recloser_ids),
        "switches": _format_devices(switch_ids),
        "switch_count": len(switch_ids),
        "cbs": _format_devices(cb_ids),
        "cb_count": len(cb_ids),
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "asset_count": 0,
        "confident_count": 0,
        "primary_feeder": "",
        "feeders": "",
        "transformers": "",
        "transformer_count": 0,
        "reclosers": "",
        "recloser_count": 0,
        "switches": "",
        "switch_count": 0,
        "cbs": "",
        "cb_count": 0,
    }


def _evidence_level(assets: tuple[TopologyAsset, ...]) -> str:
    feeders = {asset.feeder for asset in assets if asset.feeder}
    confident = any(asset.trace_status == "OK" for asset in assets)
    if confident and len(feeders) == 1:
        return "medium"
    if confident:
        return "weak"
    return "source_negative"


def _write_enriched_review(
    path: str | Path,
    review_rows: list[dict[str, str]],
    lookup_rows: list[dict[str, Any]],
) -> None:
    extra_columns = (
        "topology_lookup_status",
        "topology_evidence_level",
        "topology_place_queries",
        "topology_primary_feeder",
        "topology_transformer_ids",
        "topology_recloser_ids",
        "topology_cb_ids",
        "topology_match_reason",
    )
    base_columns = list(review_rows[0].keys()) if review_rows else []
    lookup_by_ref = {row["message_ref"]: row for row in lookup_rows}
    output_rows = []
    for row in review_rows:
        lookup = lookup_by_ref.get(row.get("message_ref") or "", {})
        output_rows.append(
            {
                **row,
                "text_sanitized_excerpt": _sanitize_excerpt_value(row.get("text_sanitized_excerpt") or ""),
                "topology_lookup_status": lookup.get("lookup_status", ""),
                "topology_evidence_level": lookup.get("topology_evidence_level", ""),
                "topology_place_queries": lookup.get("place_queries", ""),
                "topology_primary_feeder": lookup.get("primary_feeder", ""),
                "topology_transformer_ids": lookup.get("transformer_ids", ""),
                "topology_recloser_ids": lookup.get("recloser_ids", ""),
                "topology_cb_ids": lookup.get("cb_ids", ""),
                "topology_match_reason": lookup.get("match_reason", ""),
            }
        )
    _write_csv(path, tuple([*base_columns, *extra_columns]), output_rows)


def _render_markdown(rows: list[dict[str, Any]], review_source: str | Path, upstream: str | Path) -> str:
    status_counts = Counter(row["lookup_status"] for row in rows)
    lines = [
        "# LINE Place Topology Lookup",
        "",
        "Status: `shadow_only`",
        "",
        "## Sources",
        "",
        f"- Review queue: `{review_source}`",
        f"- Topology workbook: `{upstream}`",
        "- Method: sanitized LINE excerpt -> place phrase -> local upstream trace workbook.",
        "- Guardrail: no raw PEANO list, customer name, sender id, room id, phone, email, URL, or LINE id is exported.",
        "- AIS outage/restore remains the customer-facing truth lane; this file is evidence for review/training only.",
        "",
        "## Summary",
        "",
        "| Lookup status | Rows |",
        "| --- | ---: |",
    ]
    for status, count in status_counts.most_common():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Matched Rows",
            "",
            "| Message ref | Place query | Feeder | TX count | RC count | CB count | Status | Excerpt |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows:
        if row["lookup_status"] not in {"matched_local_place", "matched_local_place_broad"}:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row["message_ref"]),
                    _md(row["matched_place_query"]),
                    _md(row["primary_feeder"]),
                    str(row["transformer_count"]),
                    str(row["recloser_count"]),
                    str(row["cb_count"]),
                    _md(row["lookup_status"]),
                    _md(_excerpt(str(row["text_sanitized_excerpt"]), 96)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _owner_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_rows = []
    for row in rows:
        if row["lookup_status"] == "matched_local_place" and row["topology_evidence_level"] == "medium":
            continue
        priority = "high" if row["lookup_status"] == "no_local_match" and row["place_queries"] else "medium"
        if row["lookup_status"] == "feeder_mentioned_only":
            priority = "medium"
        if row["lookup_status"] == "matched_local_place_broad":
            priority = "medium"
        review_rows.append(
            {
                "review_priority": priority,
                "message_ref": row["message_ref"],
                "lookup_status": row["lookup_status"],
                "topology_evidence_level": row["topology_evidence_level"],
                "text_sanitized_excerpt": row["text_sanitized_excerpt"],
                "place_queries": row["place_queries"],
                "feeder_mentions": row["feeder_mentions"],
                "current_primary_feeder": row["primary_feeder"],
                "current_transformer_ids": row["transformer_ids"],
                "current_recloser_ids": row["recloser_ids"],
                "current_switch_sample_ids": row["switch_sample_ids"],
                "current_cb_ids": row["cb_ids"],
                "owner_verified_status": "",
                "owner_feeder": "",
                "owner_transformer_ids": "",
                "owner_recloser_ids": "",
                "owner_switch_ids": "",
                "owner_cb_ids": "",
                "owner_source_ref": "",
                "owner_notes": "",
            }
        )
    return review_rows


def _render_owner_review_markdown(
    rows: list[dict[str, Any]],
    review_source: str | Path,
    upstream: str | Path,
) -> str:
    priority_counts = Counter(row["review_priority"] for row in rows)
    status_counts = Counter(row["lookup_status"] for row in rows)
    lines = [
        "# LINE Place Topology Owner Review Request",
        "",
        "Status: `needs_owner_review`",
        "",
        f"- Review queue: `{review_source}`",
        f"- Local topology workbook checked: `{upstream}`",
        "- Fill only owner-confirmed topology fields in the CSV. Do not add customer names, PEANO lists, phone numbers, LINE ids, or raw chat text.",
        "- Suggested `owner_verified_status`: `verified`, `not_found`, `ambiguous`, or `outside_scope`.",
        "",
        "## Summary",
        "",
        "| Priority | Rows |",
        "| --- | ---: |",
    ]
    for priority, count in priority_counts.most_common():
        lines.append(f"| `{priority}` | {count} |")
    lines.extend(["", "| Lookup status | Rows |", "| --- | ---: |"])
    for status, count in status_counts.most_common():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Top Review Rows",
            "",
            "| Priority | Message ref | Status | Place queries | Feeder mention | Excerpt |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows[:25]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row["review_priority"]),
                    _md(row["message_ref"]),
                    _md(row["lookup_status"]),
                    _md(_excerpt(str(row["place_queries"]), 80)),
                    _md(row["feeder_mentions"]),
                    _md(_excerpt(str(row["text_sanitized_excerpt"]), 90)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _strip_operational_noise(text: str) -> str:
    value = _REDACTION_MARKER_RE.sub(" ", text)
    value = _FILE_NOISE_RE.sub(" ", value)
    value = _TIME_RE.sub(" ", value)
    value = _DEVICE_RE.sub(" ", value)
    value = re.sub(r"\b(?:show|off|reclose|tl|t/l|pdf|cg)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _clean_place_phrase(value: str) -> str:
    text = sanitize_line_text(value)[0]
    text = _EMBEDDED_PHONE_RE.sub("[PHONE_REDACTED]", text)
    text = _strip_operational_noise(text)
    for term in _NOISE_TERMS:
        text = text.replace(term, " ")
    for marker in _RELATION_MARKERS:
        text = re.sub(rf"^\s*{re.escape(marker)}\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[/|:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-_/")
    return text


def _extract_village_phrase(value: str) -> str:
    match = re.search(r"บ้าน\s*[^\s,;()/\[\]|]{2,48}", value)
    return match.group(0).strip() if match else ""


def _extract_address_phrase(value: str, prefix: str) -> str:
    match = re.search(re.escape(prefix) + r"\s*[^\s,;()/\[\]|]{2,40}", value)
    return match.group(0).strip() if match else ""


def _split_route_phrase(value: str) -> tuple[str, ...]:
    pieces: list[str] = []
    for part in re.split(r"\s*\u0e44\u0e1b\s*", value):
        cleaned = part.strip(" .,-_/")
        if cleaned != value and cleaned:
            pieces.append(cleaned)
            village = _extract_village_phrase(cleaned)
            if village:
                pieces.append(village)
    return tuple(pieces)


def _last_meaningful_token(value: str) -> str:
    parts = [
        part.strip(" .,-_/")
        for part in re.split(r"\s+", value)
        if _usable_query(_normalize_query_text(part))
    ]
    if len(parts) >= 2:
        return parts[-1]
    return ""


def _fallback_tokens(value: str) -> tuple[str, ...]:
    cleaned = _clean_place_phrase(value)
    tokens = []
    for part in re.split(r"\s+", cleaned):
        normalized = _normalize_query_text(part)
        if len(normalized) >= 5 and _usable_query(normalized):
            tokens.append(part)
    return tuple(tokens[:6])


def _append_query(items: list[str], value: str) -> None:
    normalized = _normalize_query_text(value)
    if not _usable_query(normalized):
        return
    if normalized not in {_normalize_query_text(item) for item in items}:
        items.append(value.strip())


def _usable_query(normalized: str) -> bool:
    generic = {_normalize_query_text(term) for term in _GENERIC_QUERY_TEXTS}
    return len(normalized) >= 4 and normalized not in generic


def _is_broad_query(query: str) -> bool:
    compact = query.strip()
    return compact.startswith(_BROAD_PREFIXES)


def _extract_feeders(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _FEEDER_RE.findall(text):
        feeder = normalize_feeder(match)
        if feeder and feeder not in seen:
            seen.append(feeder)
    return tuple(seen)


def _extract_devices(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _DEVICE_RE.findall(text):
        device = normalize_device_id(match)
        feeder = normalize_feeder(match)
        if device and device != feeder and device not in seen:
            seen.append(device)
    return tuple(seen[:8])


def _normalize_query_text(value: Any) -> str:
    text = str(value or "").lower()
    text = _REDACTION_MARKER_RE.sub(" ", text)
    text = re.sub(rf"[^0-9a-z{_THAI}]+", "", text)
    return text


def _pick_column(df: pd.DataFrame, key: str) -> str:
    lowered = {str(column).strip().lower(): column for column in df.columns}
    for alias in _COLUMN_ALIASES[key]:
        found = lowered.get(alias.lower())
        if found is not None:
            return str(found)
    fallback = _COLUMN_FALLBACKS.get(key)
    if fallback is not None and 0 <= fallback < len(df.columns):
        return str(df.columns[fallback])
    raise ValueError(f"Missing required upstream column for {key}")


def _unique_device_ids(values: Any) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        device = normalize_device_id(value)
        if device and device not in seen:
            seen.append(device)
    return tuple(seen)


def _format_devices(values: tuple[str, ...], limit: int = 6) -> str:
    if not values:
        return ""
    sample = list(values[:limit])
    suffix = f"; +{len(values) - limit} more" if len(values) > limit else ""
    return "; ".join(sample) + suffix


def _format_counts(counts: Counter[str], limit: int = 6) -> str:
    if not counts:
        return ""
    parts = [f"{key} ({value})" for key, value in counts.most_common(limit)]
    if len(counts) > limit:
        parts.append(f"+{len(counts) - limit} more")
    return "; ".join(parts)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _first(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _excerpt(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _sanitize_excerpt_value(value: Any, limit: int = 180) -> str:
    text = sanitize_line_text(value)[0]
    text = _EMBEDDED_PHONE_RE.sub("[PHONE_REDACTED]", text)
    return _excerpt(text, limit=limit)


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
