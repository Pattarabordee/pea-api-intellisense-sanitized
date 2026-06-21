from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from .reportpo_etr import (
    _candidate_rows_for_runtime,
    _load_approved_aliases,
    _load_imported_reportpo_csv,
    _normalize_reportpo_feeder,
    _runtime_webex_rows,
)
from .utils import normalize_feeder


GAP_CANDIDATE_COLUMNS = (
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "webex_device_id",
    "webex_feeder",
    "actual_restoration_minutes",
    "current_absolute_error",
    "reportpo_feature_match_status",
    "gap_bucket",
    "candidate_rank",
    "candidate_match_level",
    "candidate_event_number",
    "candidate_device_id",
    "candidate_feeder",
    "candidate_event_start_time",
    "delta_minutes",
    "truth_quality",
    "same_feeder",
    "same_station_prefix",
    "recommended_action",
    "reason",
)

GAP_SUMMARY_COLUMNS = (
    "gap_bucket",
    "events",
    "truth_rows",
    "candidate_rows",
    "top_devices",
    "top_feeders",
    "top_candidate_levels",
    "recommended_action",
)


def build_reportpo_feature_gap_audit(
    db_path: str | Path,
    reportpo_csv: str | Path,
    proxy_challenger_csv: str | Path,
    output_csv: str | Path,
    summary_csv: str | Path,
    markdown_output: str | Path | None = None,
    alias_file: str | Path | None = None,
    *,
    max_window_minutes: float = 1440.0,
    limit: int = 5,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    runtime_by_ref = {_redacted_ref(row.get("webex_message_id")): row for row in _runtime_webex_rows(db_path)}
    reportpo_rows = _load_imported_reportpo_csv(reportpo_csv)
    aliases = _load_approved_aliases(alias_file)
    target_rows = [
        row
        for row in _read_csv(proxy_challenger_csv)
        if row.get("actual_restoration_minutes")
        and row.get("proxy_source") == "no_prediction"
        and row.get("reportpo_feature_match_status") == "no_match"
    ]

    output_rows: list[dict[str, str]] = []
    for target in target_rows:
        runtime = runtime_by_ref.get(target.get("webex_message_ref") or "")
        if not runtime:
            output_rows.append(_base_gap_row(target, "runtime_event_missing", 1, {}, "Find runtime row before candidate audit"))
            continue
        candidates = _candidate_rows_for_runtime(
            runtime,
            reportpo_rows,
            aliases,
            max_window_minutes=max_window_minutes,
            limit=limit,
            reason="feature no-match with truth and no proxy prediction",
        )
        if not candidates:
            output_rows.append(
                _base_gap_row(
                    target,
                    "no_reportpo_candidate_near_time",
                    1,
                    {},
                    "Find an event-level bridge such as event number, job id, ticket id, or a broader ReportPO source",
                )
            )
            continue
        bucket = _gap_bucket(target, candidates)
        for rank, candidate in enumerate(candidates, start=1):
            output_rows.append(
                _candidate_gap_row(
                    target,
                    bucket,
                    rank,
                    candidate,
                    _recommended_action(bucket),
                )
            )

    summary_rows = _summary_rows(target_rows, output_rows)
    _write_csv(output_csv, GAP_CANDIDATE_COLUMNS, output_rows)
    _write_csv(summary_csv, GAP_SUMMARY_COLUMNS, summary_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(markdown_output, proxy_challenger_csv, reportpo_csv, target_rows, summary_rows)
    return {
        "db_path": str(db_path),
        "reportpo_csv": str(reportpo_csv),
        "proxy_challenger_csv": str(proxy_challenger_csv),
        "alias_file": str(alias_file) if alias_file else None,
        "output_csv": str(output_csv),
        "summary_csv": str(summary_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "target_truth_no_match_rows": len(target_rows),
        "candidate_rows": len(output_rows),
        "gap_buckets": dict(Counter(row.get("gap_bucket") or "<blank>" for row in output_rows)),
        "markdown": markdown_result,
    }


def _base_gap_row(
    target: dict[str, str],
    bucket: str,
    rank: int,
    candidate: dict[str, Any],
    recommended_action: str,
) -> dict[str, str]:
    webex_feeder = target.get("feeder") or ""
    candidate_device = str(candidate.get("candidate_device_id") or "")
    candidate_feeder = normalize_feeder(candidate.get("candidate_feeder")) or _normalize_reportpo_feeder(candidate_device) or ""
    return {
        "webex_message_ref": target.get("webex_message_ref") or "",
        "event_time": target.get("event_time") or "",
        "district": target.get("district") or "",
        "device_type": target.get("device_type") or "",
        "webex_device_id": target.get("device_id") or "",
        "webex_feeder": webex_feeder,
        "actual_restoration_minutes": target.get("actual_restoration_minutes") or "",
        "current_absolute_error": target.get("current_absolute_error") or "",
        "reportpo_feature_match_status": target.get("reportpo_feature_match_status") or "",
        "gap_bucket": bucket,
        "candidate_rank": str(rank),
        "candidate_match_level": str(candidate.get("match_level") or ""),
        "candidate_event_number": str(candidate.get("candidate_event_number") or ""),
        "candidate_device_id": candidate_device,
        "candidate_feeder": candidate_feeder,
        "candidate_event_start_time": str(candidate.get("candidate_event_start_time") or ""),
        "delta_minutes": str(candidate.get("delta_minutes") or ""),
        "truth_quality": str(candidate.get("truth_quality") or ""),
        "same_feeder": _bool_text(bool(webex_feeder and candidate_feeder == webex_feeder)),
        "same_station_prefix": _bool_text(bool(_station_prefix(webex_feeder) and _station_prefix(webex_feeder) == _station_prefix(candidate_feeder))),
        "recommended_action": recommended_action,
        "reason": str(candidate.get("reason") or ""),
    }


def _candidate_gap_row(
    target: dict[str, str],
    bucket: str,
    rank: int,
    candidate: dict[str, Any],
    recommended_action: str,
) -> dict[str, str]:
    return _base_gap_row(target, bucket, rank, candidate, recommended_action)


def _gap_bucket(target: dict[str, str], candidates: list[dict[str, Any]]) -> str:
    levels = {str(row.get("match_level") or "") for row in candidates}
    if "exact" in levels:
        return "exact_candidate_not_auto_matched"
    if "alias" in levels:
        return "alias_candidate_not_auto_matched"
    if "feeder" in levels:
        return "feeder_only_candidate_review"
    webex_feeder = target.get("feeder") or ""
    candidate_feeders = {
        normalize_feeder(row.get("candidate_feeder")) or _normalize_reportpo_feeder(row.get("candidate_device_id")) or ""
        for row in candidates
    }
    if webex_feeder and webex_feeder in candidate_feeders:
        return "same_feeder_nearby_time_review"
    if _station_prefix(webex_feeder) and _station_prefix(webex_feeder) in {_station_prefix(value) for value in candidate_feeders}:
        return "same_station_nearby_time_review"
    if candidates:
        return "nearby_time_only_different_device"
    return "no_reportpo_candidate_near_time"


def _recommended_action(bucket: str) -> str:
    if bucket in {"exact_candidate_not_auto_matched", "alias_candidate_not_auto_matched"}:
        return "Review ambiguity/time-window logic before allowing auto-match"
    if bucket == "feeder_only_candidate_review":
        return "Review feeder-level candidate manually; do not auto-fill truth without event key"
    if bucket in {"same_feeder_nearby_time_review", "same_station_nearby_time_review"}:
        return "Check device naming/alias and event start semantics"
    if bucket == "nearby_time_only_different_device":
        return "Find event-level bridge; nearby-time alone is too weak"
    return "Find event-level bridge such as event number, job id, ticket id, or source export with Webex reference"


def _summary_rows(target_rows: list[dict[str, str]], candidate_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_ref = {row.get("webex_message_ref") or "": row for row in target_rows}
    refs_by_bucket: dict[str, set[str]] = {}
    candidates_by_bucket: Counter[str] = Counter()
    devices_by_bucket: dict[str, Counter[str]] = {}
    feeders_by_bucket: dict[str, Counter[str]] = {}
    levels_by_bucket: dict[str, Counter[str]] = {}
    for row in candidate_rows:
        bucket = row.get("gap_bucket") or "<blank>"
        ref = row.get("webex_message_ref") or ""
        refs_by_bucket.setdefault(bucket, set()).add(ref)
        candidates_by_bucket[bucket] += 1
        devices_by_bucket.setdefault(bucket, Counter())[row.get("webex_device_id") or ""] += 1
        feeders_by_bucket.setdefault(bucket, Counter())[row.get("webex_feeder") or ""] += 1
        levels_by_bucket.setdefault(bucket, Counter())[row.get("candidate_match_level") or "<none>"] += 1
    output = []
    for bucket in sorted(refs_by_bucket):
        refs = refs_by_bucket[bucket]
        output.append(
            {
                "gap_bucket": bucket,
                "events": str(len(refs)),
                "truth_rows": str(sum(1 for ref in refs if rows_by_ref.get(ref, {}).get("actual_restoration_minutes"))),
                "candidate_rows": str(candidates_by_bucket[bucket]),
                "top_devices": _format_counter(devices_by_bucket.get(bucket, Counter())),
                "top_feeders": _format_counter(feeders_by_bucket.get(bucket, Counter())),
                "top_candidate_levels": _format_counter(levels_by_bucket.get(bucket, Counter())),
                "recommended_action": _recommended_action(bucket),
            }
        )
    return sorted(output, key=lambda row: (-int(row["events"]), row["gap_bucket"]))


def _write_markdown(
    path: str | Path,
    proxy_challenger_csv: str | Path,
    reportpo_csv: str | Path,
    target_rows: list[dict[str, str]],
    summary_rows: list[dict[str, str]],
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ReportPO Feature Gap Audit",
        "",
        "This report explains why truth rows still lack a safe ReportPO feature/proxy match. It is audit-only and does not auto-fill truth.",
        "",
        "## Sources",
        "",
        f"- Proxy challenger: `{proxy_challenger_csv}`",
        f"- ReportPO feature CSV: `{reportpo_csv}`",
        "",
        "## Summary",
        "",
        f"- Truth rows with no ReportPO feature/proxy prediction: {len(target_rows)}",
        f"- Gap buckets: {len(summary_rows)}",
        "",
        "| Gap bucket | Events | Candidate rows | Top feeders | Candidate levels | Recommended action |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['gap_bucket']} | {row['events']} | {row['candidate_rows']} | "
            f"{_md_cell(row['top_feeders'])} | {_md_cell(row['top_candidate_levels'])} | {_md_cell(row['recommended_action'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Feeder-only or nearby-time candidates are not reliable enough to fill truth automatically.",
            "- The safest next improvement is an event-level bridge such as event number, job id, ticket id, or a ReportPO/eRespond export that carries a Webex/event reference.",
            "- Device alias repair should be limited to cases with topology or source-system evidence.",
            "",
            "## Privacy Note",
            "",
            "This report uses redacted message references and aggregate counts. It omits message bodies, room identifiers, credentials, meter lists, and customer registration names.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _redacted_ref(value: str | None) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


def _station_prefix(feeder: str | None) -> str:
    text = str(feeder or "").strip().upper()
    return "".join(ch for ch in text[:3] if ch.isalpha())


def _bool_text(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _format_counter(counter: Counter[str], limit: int = 5) -> str:
    cleaned = Counter({key or "<blank>": value for key, value in counter.items()})
    return "; ".join(f"{key}={count}" for key, count in cleaned.most_common(limit))


def _md_cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ")
