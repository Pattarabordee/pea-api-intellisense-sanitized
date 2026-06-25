from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
from typing import Any


def build_source_trace_schematic(
    source_trace_audit_csv: str | Path,
    output_markdown: str | Path,
) -> dict[str, Any]:
    rows = _read_csv(source_trace_audit_csv)
    total_candidates = len(rows)
    total_events = sum(_int(row.get("event_count")) for row in rows)
    result_counts = Counter(row.get("source_trace_result") or "<missing>" for row in rows)
    confirmed = [row for row in rows if row.get("source_trace_result") == "source_trace_confirms_confident_ais_downstream"]
    outside = [row for row in rows if row.get("source_trace_result") == "source_trace_no_current_ais_downstream"]
    not_found = [row for row in rows if row.get("source_trace_result") == "source_device_not_found"]
    missing = [row for row in rows if row.get("source_trace_result") == "cannot_trace_missing_device"]
    confirmed_events = sum(_int(row.get("event_count")) for row in confirmed)
    confirmed_ais = sum(_int(row.get("ais_confident_hits")) for row in confirmed)

    content = _render_markdown(
        rows=rows,
        result_counts=result_counts,
        total_candidates=total_candidates,
        total_events=total_events,
        confirmed=confirmed,
        confirmed_events=confirmed_events,
        confirmed_ais=confirmed_ais,
        outside=outside,
        not_found=not_found,
        missing=missing,
    )
    output = Path(output_markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8-sig")
    return {
        "output_markdown": str(output),
        "total_candidates": total_candidates,
        "total_events": total_events,
        "confirmed_ais_downstream_candidates": len(confirmed),
        "confirmed_ais_downstream_events": confirmed_events,
        "confirmed_ais_confident_hits": confirmed_ais,
        "result_counts": dict(sorted(result_counts.items())),
    }


def _render_markdown(
    *,
    rows: list[dict[str, str]],
    result_counts: Counter[str],
    total_candidates: int,
    total_events: int,
    confirmed: list[dict[str, str]],
    confirmed_events: int,
    confirmed_ais: int,
    outside: list[dict[str, str]],
    not_found: list[dict[str, str]],
    missing: list[dict[str, str]],
) -> str:
    key_finding = _key_finding_text(confirmed)
    lines = [
        "# AIS ETR Source Trace Schematic",
        "",
        "Shadow / evidence only. This page summarizes source-system trace results without exposing raw PEANO lists, Webex raw text, room identifiers, credentials, customer registration names, or addresses.",
        "",
        "## What Was Traced",
        "",
        f"- Webex no-match events reviewed: `{total_events}`",
        f"- Grouped source trace candidates: `{total_candidates}`",
        f"- Source trace method: ArcGIS device query plus `TraceDownHV_LV` downstream topology trace",
        f"- Confirmed AIS confident downstream candidates: `{len(confirmed)}`",
        f"- Confirmed AIS confident downstream meters: `{confirmed_ais}`",
        "",
        "## Schematic",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Webex no-match events<br/>54 events"] --> B["Group by device + feeder<br/>10 candidates"]',
        '  B --> C["ArcGIS source query<br/>CB / Recloser / Switch / Transformer"]',
        '  C --> D["TraceDownHV_LV<br/>downstream topology"]',
        '  D --> E["Compare with AIS registry<br/>confident assets only"]',
        f'  E --> F["Confirmed AIS downstream<br/>{len(confirmed)} candidate / {confirmed_events} events"]',
        f'  E --> G["No current AIS downstream<br/>{len(outside)} candidates"]',
        f'  C --> H["Device not found<br/>{len(not_found)} candidates"]',
        f'  B --> I["Missing device<br/>{len(missing)} candidate"]',
        '  F --> J["Secure repair overlay<br/>runtime/private only"]',
        '  J --> K["Replay Webex history<br/>measure no-match reduction"]',
        "```",
        "",
        "## Key Finding",
        "",
        key_finding,
        "",
        "## Candidate Results",
        "",
        "| Result | Candidates | Events | AIS confident hits | Interpretation |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for result, count in result_counts.most_common():
        scoped = [row for row in rows if (row.get("source_trace_result") or "<missing>") == result]
        events = sum(_int(row.get("event_count")) for row in scoped)
        hits = sum(_int(row.get("ais_confident_hits")) for row in scoped)
        lines.append(f"| `{result}` | {count} | {events} | {hits} | {_interpretation(result)} |")

    lines.extend(
        [
            "",
            "## Recommended Next Step",
            "",
            "Apply a secure runtime-only repair for `PFA05VB-01 / PFA05`, then replay Webex history and compare no-match counts before/after. This is the highest-value repair because source topology confirms AIS confident assets downstream and the candidate accounts for 7 Webex events.",
            "",
            "## Safety Notes",
            "",
            "- Do not send production AIS notifications from this evidence alone.",
            "- Keep PEANO-level repair evidence under `runtime/private/` only.",
            "- Do not edit `upstream_result.xlsx` in this batch.",
            "- Treat device-not-found candidates as alias/topology review items, not as confirmed AIS impact.",
        ]
    )
    return "\n".join(lines)


def _key_finding_text(confirmed: list[dict[str, str]]) -> str:
    if not confirmed:
        return "No candidate currently has confirmed AIS confident downstream assets from the source-system trace."
    top = sorted(confirmed, key=lambda row: _int(row.get("event_count")), reverse=True)[0]
    return (
        f"`{top.get('device_id')} / {top.get('feeder')}` is the strongest repair target: "
        f"source trace found `{top.get('ais_confident_hits')}` AIS confident downstream assets and it accounts for "
        f"`{top.get('event_count')}` Webex no-match events."
    )


def _interpretation(result: str) -> str:
    return {
        "source_trace_confirms_confident_ais_downstream": "Repair runtime protection mapping.",
        "source_trace_no_current_ais_downstream": "Likely outside current AIS pilot registry.",
        "source_device_not_found": "Review Webex alias or source GIS FACILITYID.",
        "cannot_trace_missing_device": "Improve parser only if original message contains a real device id.",
    }.get(result, "Review source trace audit.")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
