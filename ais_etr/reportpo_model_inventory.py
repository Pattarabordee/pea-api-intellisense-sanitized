from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


MODEL_FIELD_COLUMNS = (
    "source",
    "entity",
    "property",
    "role",
    "data_type",
    "data_type_label",
    "format_string",
    "visual_count",
    "visual_ids",
)

VISUAL_QUERY_COLUMNS = (
    "tab",
    "status",
    "visual_id",
    "query_index",
    "entity",
    "property",
    "select_kind",
    "native_reference",
    "source_name",
    "where_properties",
    "order_by_properties",
    "has_etr_event_keys",
    "source_file",
)

CANDIDATE_FIELD_COLUMNS = (
    "category",
    "priority",
    "entity",
    "property",
    "role",
    "source_evidence",
    "visual_count",
    "visual_ids",
    "rationale",
    "caveat",
)

DATA_TYPE_LABELS = {
    "1": "text",
    "2": "decimal",
    "3": "integer",
    "4": "integer",
    "5": "boolean",
    "7": "datetime",
}

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "reference": 3}
CATEGORY_ORDER = {
    "restoration_time": 0,
    "lifecycle_time": 1,
    "status_notification": 2,
    "cause_weather": 3,
    "event_type": 4,
    "topology_device": 5,
    "geography_org": 6,
    "measure": 7,
    "other": 8,
}


def build_reportpo_model_inventory(
    network_capture: str | Path,
    querydata_capture: str | Path,
    output_csv: str | Path,
    candidates_csv: str | Path,
    visuals_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    schema_rows, schema_warnings = _schema_rows_from_network_capture(network_capture)
    visual_rows = _visual_rows_from_querydata_capture(querydata_capture)
    field_rows = _merge_field_rows(schema_rows, visual_rows)
    candidate_rows = _candidate_rows(field_rows)

    _write_csv(output_csv, MODEL_FIELD_COLUMNS, field_rows)
    _write_csv(visuals_csv, VISUAL_QUERY_COLUMNS, visual_rows)
    _write_csv(candidates_csv, CANDIDATE_FIELD_COLUMNS, candidate_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(
            markdown_output,
            network_capture,
            querydata_capture,
            field_rows,
            visual_rows,
            candidate_rows,
            schema_warnings,
        )

    return {
        "network_capture": str(network_capture),
        "querydata_capture": str(querydata_capture),
        "output_csv": str(output_csv),
        "visuals_csv": str(visuals_csv),
        "candidates_csv": str(candidates_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "schema_fields": len(schema_rows),
        "visual_select_fields": len(visual_rows),
        "unique_fields": len(field_rows),
        "candidate_fields": len(candidate_rows),
        "entities": sorted({row["entity"] for row in field_rows if row.get("entity")}),
        "schema_warnings": schema_warnings,
        "markdown": markdown_result,
    }


def _schema_rows_from_network_capture(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    capture = Path(path)
    if not capture.exists():
        return [], [f"network capture not found: {capture}"]
    text = capture.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, str]] = []
    warnings: list[str] = []
    for payload in _extract_schema_payload_strings(text):
        try:
            data = json.loads(payload)
            rows.extend(_schema_rows_from_schema_payload(data, str(capture)))
            continue
        except json.JSONDecodeError:
            warnings.append("schema payload in network capture is truncated; parsed complete entity/property blocks only")
        rows.extend(_schema_rows_from_partial_schema_payload(payload, str(capture)))
    if not rows:
        warnings.append("no schema rows found in network capture")
    return rows, warnings


def _extract_schema_payload_strings(text: str) -> list[str]:
    payloads: list[str] = []
    search_from = 0
    while True:
        marker = text.find('\\"schemas\\"', search_from)
        if marker == -1:
            marker = text.find('"schemas"', search_from)
        if marker == -1:
            break
        body_key = text.rfind('"body"', 0, marker)
        if body_key == -1:
            search_from = marker + 1
            continue
        colon = text.find(":", body_key)
        quote = text.find('"', colon + 1)
        if quote == -1:
            search_from = marker + 1
            continue
        literal, end_index = _read_json_string_literal(text, quote)
        if literal:
            try:
                payloads.append(json.loads(literal))
            except json.JSONDecodeError:
                pass
        search_from = max(end_index + 1, marker + 1)
    return payloads


def _read_json_string_literal(text: str, quote_index: int) -> tuple[str, int]:
    raw: list[str] = []
    escaped = False
    index = quote_index + 1
    while index < len(text):
        char = text[index]
        if escaped:
            raw.append("\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return '"' + "".join(raw) + '"', index
        else:
            raw.append(char)
        index += 1
    return "", index


def _schema_rows_from_schema_payload(data: dict[str, Any], source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for schema in data.get("schemas", []) or []:
        for entity in schema.get("schema", {}).get("Entities", []) or []:
            rows.extend(_schema_rows_from_entity(entity, source))
    return rows


def _schema_rows_from_partial_schema_payload(payload: str, source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entity_name, properties_text in _iter_partial_entity_properties(payload):
        properties = _parse_partial_property_array(properties_text)
        for prop in properties:
            rows.append(_field_row_from_schema_property(source, entity_name, prop))
    return rows


def _iter_partial_entity_properties(payload: str) -> Iterable[tuple[str, str]]:
    pattern = re.compile(r'\{"Name":"([^"]+)","EdmName":"[^"]+","Properties":\[')
    for match in pattern.finditer(payload):
        entity_name = match.group(1)
        properties_start = match.end() - 1
        properties_end = _find_matching_bracket(payload, properties_start)
        if properties_end is None:
            properties_text = payload[properties_start + 1 :]
        else:
            properties_text = payload[properties_start + 1 : properties_end]
        yield entity_name, properties_text


def _find_matching_bracket(text: str, start_index: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _parse_partial_property_array(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    output: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " \r\n\t,":
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        try:
            value, end_index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            output.append(value)
        index = end_index
    return output


def _schema_rows_from_entity(entity: dict[str, Any], source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    entity_name = str(entity.get("Name") or "")
    for prop in entity.get("Properties", []) or []:
        rows.append(_field_row_from_schema_property(source, entity_name, prop))
    return rows


def _field_row_from_schema_property(source: str, entity: str, prop: dict[str, Any]) -> dict[str, str]:
    data_type = "" if prop.get("DataType") is None else str(prop.get("DataType"))
    role = "measure" if "Measure" in prop else "column" if "Column" in prop else "unknown"
    return {
        "source": source,
        "entity": entity,
        "property": str(prop.get("Name") or ""),
        "role": role,
        "data_type": data_type,
        "data_type_label": DATA_TYPE_LABELS.get(data_type, ""),
        "format_string": str(prop.get("FormatString") or ""),
        "visual_count": "0",
        "visual_ids": "",
    }


def _visual_rows_from_querydata_capture(path: str | Path) -> list[dict[str, str]]:
    capture = Path(path)
    if not capture.exists():
        return []
    payload = json.loads(capture.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    if not isinstance(payload, list):
        return rows
    for item_index, item in enumerate(payload):
        if not isinstance(item, dict) or not item.get("request"):
            continue
        try:
            request = json.loads(item["request"]) if isinstance(item["request"], str) else item["request"]
        except (TypeError, json.JSONDecodeError):
            continue
        tab = str(item.get("tab") or "")
        status = str(item.get("status") or "")
        for query_index, query in enumerate(request.get("queries", []) or []):
            command = _semantic_command(query)
            if not command:
                continue
            sources = {
                str(source.get("Name")): str(source.get("Entity") or "")
                for source in command.get("Query", {}).get("From", []) or []
                if isinstance(source, dict) and source.get("Name")
            }
            visual_id = _visual_id(query)
            where_properties = ";".join(_properties_in_tree(command.get("Query", {}).get("Where", []), sources))
            order_by_properties = ";".join(_properties_in_tree(command.get("Query", {}).get("OrderBy", []), sources))
            has_etr_keys = _command_has_etr_keys(command)
            for select in command.get("Query", {}).get("Select", []) or []:
                if not isinstance(select, dict):
                    continue
                row = _visual_select_row(
                    select,
                    sources,
                    tab,
                    status,
                    visual_id,
                    query_index,
                    item_index,
                    where_properties,
                    order_by_properties,
                    has_etr_keys,
                    str(capture),
                )
                if row:
                    rows.append(row)
    return rows


def _semantic_command(query: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return query["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    except (KeyError, IndexError, TypeError):
        return None


def _visual_id(query: dict[str, Any]) -> str:
    try:
        return str(query.get("ApplicationContext", {}).get("Sources", [{}])[0].get("VisualId") or "")
    except (IndexError, AttributeError):
        return ""


def _visual_select_row(
    select: dict[str, Any],
    sources: dict[str, str],
    tab: str,
    status: str,
    visual_id: str,
    query_index: int,
    item_index: int,
    where_properties: str,
    order_by_properties: str,
    has_etr_keys: bool,
    source_file: str,
) -> dict[str, str] | None:
    select_kind = ""
    entity = ""
    property_name = ""
    source_name = ""
    native_reference = str(select.get("NativeReferenceName") or "")
    if isinstance(select.get("Column"), dict):
        select_kind = "column"
        column = select["Column"]
        property_name = str(column.get("Property") or "")
        source_name = str(column.get("Expression", {}).get("SourceRef", {}).get("Source") or "")
        entity = sources.get(source_name, "")
    elif isinstance(select.get("Measure"), dict):
        select_kind = "measure"
        measure = select["Measure"]
        property_name = str(measure.get("Property") or "")
        source_name = str(measure.get("Expression", {}).get("SourceRef", {}).get("Source") or "")
        entity = sources.get(source_name, "")
    if not property_name:
        return None
    return {
        "tab": tab,
        "status": status,
        "visual_id": visual_id,
        "query_index": str(query_index),
        "entity": entity,
        "property": property_name,
        "select_kind": select_kind,
        "native_reference": native_reference,
        "source_name": source_name,
        "where_properties": where_properties,
        "order_by_properties": order_by_properties,
        "has_etr_event_keys": "true" if has_etr_keys else "false",
        "source_file": f"{source_file}#{item_index}",
    }


def _properties_in_tree(value: Any, sources: dict[str, str]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            column = node.get("Column")
            if isinstance(column, dict):
                prop = column.get("Property")
                source = column.get("Expression", {}).get("SourceRef", {}).get("Source")
                entity = sources.get(str(source), "")
                if prop:
                    found.append(f"{entity}.{prop}" if entity else str(prop))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(set(found))


def _command_has_etr_keys(command: dict[str, Any]) -> bool:
    properties = set()
    for select in command.get("Query", {}).get("Select", []) or []:
        if not isinstance(select, dict):
            continue
        for key in ("Column", "Measure"):
            value = select.get(key)
            if isinstance(value, dict) and value.get("Property"):
                properties.add(str(value.get("Property")))
    return {"EVENT_ID", "EVENT_START_TIME", "FIRST_RESTORE_TIME", "DEVICE_NAME"}.issubset(properties)


def _merge_field_rows(schema_rows: list[dict[str, str]], visual_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in schema_rows:
        key = (row["entity"], row["property"], row["role"])
        merged[key] = {column: row.get(column, "") for column in MODEL_FIELD_COLUMNS}

    visual_counts: Counter[tuple[str, str, str]] = Counter()
    visual_ids: dict[tuple[str, str, str], set[str]] = {}
    for row in visual_rows:
        key = (row["entity"], row["property"], row["select_kind"])
        visual_counts[key] += 1
        visual_ids.setdefault(key, set()).add(row.get("visual_id") or "")
        if key not in merged:
            merged[key] = {
                "source": row.get("source_file", ""),
                "entity": row["entity"],
                "property": row["property"],
                "role": row["select_kind"],
                "data_type": "",
                "data_type_label": "",
                "format_string": "",
                "visual_count": "0",
                "visual_ids": "",
            }

    for key, count in visual_counts.items():
        row = merged[key]
        row["visual_count"] = str(count)
        row["visual_ids"] = ";".join(sorted(value for value in visual_ids.get(key, set()) if value))

    return sorted(
        merged.values(),
        key=lambda row: (row["entity"].lower(), row["property"].lower(), row["role"]),
    )


def _candidate_rows(field_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in field_rows:
        category, rationale = _candidate_category(row["entity"], row["property"], row["role"])
        if not category:
            continue
        priority, caveat = _candidate_priority(row["entity"], row["property"], row["role"], category)
        output.append(
            {
                "category": category,
                "priority": priority,
                "entity": row["entity"],
                "property": row["property"],
                "role": row["role"],
                "source_evidence": "visual+schema"
                if row.get("data_type") and int(row.get("visual_count") or 0) > 0
                else "schema"
                if row.get("data_type")
                else "visual",
                "visual_count": row.get("visual_count", "0"),
                "visual_ids": row.get("visual_ids", ""),
                "rationale": rationale,
                "caveat": caveat,
            }
        )
    return sorted(
        output,
        key=lambda row: (
            PRIORITY_ORDER.get(row["priority"], 9),
            CATEGORY_ORDER.get(row["category"], 9),
            row["entity"].lower(),
            row["property"].lower(),
        ),
    )


def _candidate_category(entity: str, property_name: str, role: str) -> tuple[str | None, str]:
    text = f"{entity} {property_name}".lower()
    if role == "measure" or any(token in text for token in ("count", "sum(", "min(", "max(")):
        return "measure", "measure can support aggregate QA but is not an event-level feature by itself"
    if any(token in text for token in ("cause", "fault", "reason", "weather", "storm", "lightning")):
        return "cause_weather", "potential cause or external-condition feature"
    if any(token in text for token in ("first_restore", "lastresto", "restore", "resto", "event_end", "cldatetime", "clear")):
        return "restoration_time", "candidate restoration or close timestamp; must not replace AIS truth without validation"
    if any(
        token in text
        for token in (
            "event_start",
            "event_create",
            "crdatetime",
            "apdatetime",
            "nodatetime",
            "ipdatetime",
            "payloadtimestamp",
            "sched",
            "date",
            "time",
        )
    ):
        return "lifecycle_time", "candidate lifecycle timing feature"
    if any(token in text for token in ("status", "notify", "notified")):
        return "status_notification", "candidate event status or notification process feature"
    if any(token in text for token in ("type", "description", "group", "stdresult")):
        return "event_type", "candidate outage/work type proxy"
    if any(token in text for token in ("device", "feeder", "gis", "transformer", "voltage")):
        return "topology_device", "candidate topology or operating-device feature"
    if any(token in text for token in ("office", "area", "branch", "main", "region")):
        return "geography_org", "candidate organization or geography feature"
    return None, ""


def _candidate_priority(entity: str, property_name: str, role: str, category: str) -> tuple[str, str]:
    entity_norm = entity.lower()
    prop_norm = property_name.lower()
    if category == "measure":
        return "reference", "aggregate measure; do not train event-level model directly on this"
    if entity_norm == "etr_ou" and category in {"restoration_time", "lifecycle_time", "status_notification", "event_type"}:
        return "high", "ETR_OU is the current ReportPO ETR event source; verify semantics before use"
    if entity_norm == "pending" and category in {"status_notification", "event_type", "topology_device"}:
        return "high", "Pending appears in captured visuals and may explain open/active event status"
    if entity_norm == "po" and category in {"restoration_time", "lifecycle_time", "status_notification", "topology_device"}:
        return "medium", "PO lifecycle scraped successfully but direct Webex coverage is sparse"
    if "event_etr" in prop_norm or "etr_first" in prop_norm:
        return "low", "ETR process timestamp, not actual restoration truth"
    if category in {"cause_weather", "restoration_time", "lifecycle_time"}:
        return "medium", "potentially useful if event-grain join can be proven"
    return "low", "supporting dimension; useful after event-grain join is solved"


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _write_markdown(
    path: str | Path,
    network_capture: str | Path,
    querydata_capture: str | Path,
    field_rows: list[dict[str, str]],
    visual_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    warnings: list[str],
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    entity_counts = Counter(row["entity"] for row in field_rows if row.get("entity"))
    category_counts = Counter(row["category"] for row in candidate_rows)
    priority_counts = Counter(row["priority"] for row in candidate_rows)
    high_candidates = [row for row in candidate_rows if row["priority"] == "high"][:20]
    etr_ou_rows = [row for row in candidate_rows if row["entity"] == "ETR_OU"][:20]
    pending_rows = [row for row in candidate_rows if row["entity"] == "Pending"][:20]
    po_rows = [row for row in candidate_rows if row["entity"] == "PO"][:20]

    lines = [
        "# ReportPO Semantic Model Inventory",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Sources",
        "",
        f"- Network capture: `{network_capture}`",
        f"- Visual query capture: `{querydata_capture}`",
        "",
        "## Summary",
        "",
        f"- Unique fields inventoried: {len(field_rows)}",
        f"- Visual select rows: {len(visual_rows)}",
        f"- Candidate fields: {len(candidate_rows)}",
        f"- Entities seen: {len(entity_counts)}",
        f"- Candidate priority counts: {_format_counter(priority_counts)}",
        f"- Candidate category counts: {_format_counter(category_counts)}",
        "",
    ]
    if warnings:
        lines.extend(["## Capture Caveats", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    lines.extend(
        [
            "## Key Findings",
            "",
            "- `ETR_OU` remains the best event-level source for ReportPO ETR timing fields already used by the current provisional truth lane.",
            "- `Pending` is the important newly identified entity for event status/type fields: captured visuals show `EVENT_TYPE`, `EVENT_STATUS`, `EVENT_TYPE2`, `EVENT_STATUS2`, `EVENT_ID`, and `DEVICE_NAME`.",
            "- `PO` has lifecycle fields such as `CRdateTime`, `NOdateTime`, `IPdateTime`, `LastRestoDateTime`, and `CLdateTime`, but the current direct Webex match coverage is sparse.",
            "- No root-cause field was confirmed in the captured model/query inventory. Cause remains an open data-source gap.",
            "",
            "## High-Priority Candidates",
            "",
            _markdown_table(high_candidates, ("entity", "property", "category", "source_evidence", "caveat")),
            "",
            "## ETR_OU Candidates",
            "",
            _markdown_table(etr_ou_rows, ("property", "category", "priority", "caveat")),
            "",
            "## Pending Candidates",
            "",
            _markdown_table(pending_rows, ("property", "category", "priority", "caveat")),
            "",
            "## PO Candidates",
            "",
            _markdown_table(po_rows, ("property", "category", "priority", "caveat")),
            "",
            "## Recommended Next Probe",
            "",
            "Build a small `Pending` probe before adding another model feature: fetch `EVENT_ID`, `DEVICE_NAME`, `EVENT_TYPE`, `EVENT_STATUS`, `EVENT_TYPE2`, and `EVENT_STATUS2`, then test whether it overlaps with ReportPO ETR event numbers or Webex device/time rows. Keep this as audit-only until an event-grain join is proven.",
            "",
            "Production AIS send remains blocked. This inventory contains field names and aggregate metadata only; it does not include raw Webex messages, room identifiers, credentials, meter-id lists, or customer registration names.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _markdown_table(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(_md_cell(row.get(column, "")) for column in columns) + " |")
    return "\n".join([header, sep, *body])


def _md_cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _format_counter(counter: Counter[str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items())) or "none"
