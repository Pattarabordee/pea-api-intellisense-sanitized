from __future__ import annotations

from collections import Counter
import csv
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.parse
import urllib.request

from .config import load_env_file
from .line_ingest import sanitize_line_text
from .line_place_topology import DEFAULT_LINE_PLACE_OUTPUT, extract_place_queries


DEFAULT_LINE_GOOGLE_GEOCODE_OUTPUT = "runtime/line_place_google_geocode.csv"
DEFAULT_LINE_GOOGLE_GEOCODE_MARKDOWN_OUTPUT = "runtime/line_place_google_geocode.md"
DEFAULT_GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

GEOCODE_COLUMNS = (
    "message_ref",
    "source_lookup_status",
    "text_sanitized_excerpt",
    "place_queries",
    "google_geocode_status",
    "google_response_status",
    "selected_query",
    "attempted_queries",
    "lat",
    "lng",
    "location_type",
    "place_id",
    "formatted_address",
    "result_types",
    "partial_match",
    "result_count",
    "geocode_quality",
    "review_note",
)

_EMBEDDED_PHONE_RE = re.compile(r"(?:\+?66|0)[\s.-]?\d(?:[\s.-]?\d){7,8}")
_GEOCODE_BLOCKLIST = {
    "alarm",
    "lowgasalarm",
    "\u0e1b\u0e31\u0e08\u0e08\u0e38\u0e1a\u0e31\u0e19\u0e44\u0e21\u0e48\u0e21\u0e35",
    "\u0e44\u0e1f\u0e44\u0e21\u0e48\u0e04\u0e23\u0e1a\u0e40\u0e1f\u0e2a",
    "\u0e2a\u0e32\u0e22\u0e2b\u0e25\u0e38\u0e14",
    "\u0e2b\u0e31\u0e27\u0e40\u0e2a\u0e32",
    "\u0e44\u0e2b\u0e21\u0e49",
    "\u0e17\u0e35\u0e48\u0e2b\u0e19\u0e49\u0e32\u0e23\u0e49\u0e32\u0e19",
    "\u0e16\u0e49\u0e32\u0e22\u0e31\u0e07\u0e44\u0e21\u0e48\u0e21\u0e35",
    "\u0e41\u0e01\u0e49\u0e44\u0e1f\u0e14\u0e49\u0e27\u0e22",
    "\u0e2b\u0e49\u0e2d\u0e07\u0e1b\u0e23\u0e30\u0e0a\u0e38\u0e21\u0e0a\u0e31\u0e49\u0e19",
    "\u0e01\u0e49\u0e19\u0e2d\u0e31\u0e19\u0e40\u0e14\u0e2d\u0e23\u0e01\u0e23\u0e32\u0e27",
}


class GoogleGeocodeClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_GOOGLE_GEOCODE_URL,
        timeout_seconds: float = 15.0,
        sleep_seconds: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.sleep_seconds = sleep_seconds

    def geocode(self, query: str) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "address": query,
                "key": self.api_key,
                "language": "th",
                "region": "th",
                "components": "country:TH",
            }
        )
        request = urllib.request.Request(
            f"{self.base_url}?{params}",
            headers={"User-Agent": "AIS-ETR-LinePlaceGeocode/1.0"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return payload


def build_line_google_geocode_missing_places(
    source: str | Path = DEFAULT_LINE_PLACE_OUTPUT,
    output: str | Path = DEFAULT_LINE_GOOGLE_GEOCODE_OUTPUT,
    markdown_output: str | Path | None = DEFAULT_LINE_GOOGLE_GEOCODE_MARKDOWN_OUTPUT,
    *,
    statuses: tuple[str, ...] = ("no_local_match",),
    query_suffix: str = "Sakon Nakhon Thailand",
    api_key_env: str = "GOOGLE_MAPS_API_KEY",
    env_path: str | Path = ".env",
    limit: int | None = None,
    max_candidates_per_row: int = 3,
    timeout_seconds: float = 15.0,
    sleep_seconds: float = 0.2,
    client: Any | None = None,
) -> dict[str, Any]:
    load_env_file(env_path)
    api_key = os.environ.get(api_key_env, "").strip()
    rows = _read_csv(Path(source))
    scoped = [row for row in rows if (row.get("lookup_status") or "") in statuses]
    if limit is not None:
        scoped = scoped[: max(0, limit)]

    geocoder = client
    if geocoder is None and api_key:
        geocoder = GoogleGeocodeClient(
            api_key,
            timeout_seconds=timeout_seconds,
            sleep_seconds=sleep_seconds,
        )

    cache: dict[str, dict[str, Any]] = {}
    output_rows = []
    for row in scoped:
        output_rows.append(
            _geocode_row(
                row,
                geocoder,
                cache,
                api_key_present=bool(api_key) or client is not None,
                query_suffix=query_suffix,
                max_candidates_per_row=max_candidates_per_row,
            )
        )

    _write_csv(output, GEOCODE_COLUMNS, output_rows)
    if markdown_output:
        Path(markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_output).write_text(_render_markdown(output_rows, source, api_key_present=bool(api_key) or client is not None), encoding="utf-8")

    status_counts = Counter(row["google_geocode_status"] for row in output_rows)
    response_counts = Counter(row["google_response_status"] for row in output_rows)
    return {
        "status": "ok" if (api_key or client is not None) else "blocked_missing_google_maps_api_key",
        "mode": "shadow",
        "production_send": "blocked",
        "source": str(source),
        "output": str(output),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "rows_scoped": len(scoped),
        "rows_written": len(output_rows),
        "api_key_env": api_key_env,
        "api_key_present": bool(api_key) or client is not None,
        "unique_google_queries": len(cache),
        "google_geocode_status_counts": dict(sorted(status_counts.items())),
        "google_response_status_counts": dict(sorted(response_counts.items())),
    }


def _geocode_row(
    row: dict[str, str],
    client: Any | None,
    cache: dict[str, dict[str, Any]],
    *,
    api_key_present: bool,
    query_suffix: str,
    max_candidates_per_row: int,
) -> dict[str, Any]:
    excerpt = _sanitize_text(row.get("text_sanitized_excerpt") or "")
    place_queries = _candidate_place_queries(row, excerpt, max_candidates=max_candidates_per_row)
    query_strings = [_query_with_suffix(query, query_suffix) for query in place_queries]
    base = {
        "message_ref": row.get("message_ref") or "",
        "source_lookup_status": row.get("lookup_status") or "",
        "text_sanitized_excerpt": excerpt,
        "place_queries": "; ".join(place_queries),
        "attempted_queries": "; ".join(query_strings),
    }
    if not place_queries:
        return {
            **base,
            **_blank_geocode_fields(
                status="skipped_no_place_query",
                response_status="",
                review_note="No sanitized place query was available; not sending full chat excerpt to Google.",
            ),
        }
    if not api_key_present or client is None:
        return {
            **base,
            **_blank_geocode_fields(
                status="blocked_missing_google_maps_api_key",
                response_status="",
                review_note="Set GOOGLE_MAPS_API_KEY in .env or environment and rerun.",
            ),
        }

    last_status = ""
    last_note = ""
    for query in query_strings:
        try:
            payload = cache.get(query)
            if payload is None:
                payload = client.geocode(query)
                cache[query] = payload
        except Exception as exc:
            return {
                **base,
                **_blank_geocode_fields(
                    status="google_request_error",
                    response_status=type(exc).__name__,
                    selected_query=query,
                    review_note=str(exc)[:220],
                ),
            }
        status = str(payload.get("status") or "")
        last_status = status
        if status == "OK" and payload.get("results"):
            return {**base, **_google_result_fields(query, payload)}
        last_note = str(payload.get("error_message") or "")
        if status in {"OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST"}:
            break

    return {
        **base,
        **_blank_geocode_fields(
            status="google_no_usable_result",
            response_status=last_status,
            selected_query=query_strings[0] if query_strings else "",
            result_count=0,
            review_note=last_note[:220],
        ),
    }


def _google_result_fields(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or []
    first = results[0]
    geometry = first.get("geometry") or {}
    location = geometry.get("location") or {}
    location_type = str(geometry.get("location_type") or "")
    return {
        "google_geocode_status": "geocoded",
        "google_response_status": str(payload.get("status") or ""),
        "selected_query": query,
        "lat": _coord(location.get("lat")),
        "lng": _coord(location.get("lng")),
        "location_type": location_type,
        "place_id": str(first.get("place_id") or ""),
        "formatted_address": _sanitize_text(first.get("formatted_address") or "", limit=220),
        "result_types": ";".join(str(item) for item in first.get("types") or []),
        "partial_match": str(bool(first.get("partial_match"))).lower(),
        "result_count": len(results),
        "geocode_quality": _quality(location_type, bool(first.get("partial_match")), len(results)),
        "review_note": "",
    }


def _blank_geocode_fields(
    *,
    status: str,
    response_status: str,
    selected_query: str = "",
    result_count: int | str = "",
    review_note: str,
) -> dict[str, Any]:
    return {
        "google_geocode_status": status,
        "google_response_status": response_status,
        "selected_query": selected_query,
        "lat": "",
        "lng": "",
        "location_type": "",
        "place_id": "",
        "formatted_address": "",
        "result_types": "",
        "partial_match": "",
        "result_count": result_count,
        "geocode_quality": "none",
        "review_note": review_note,
    }


def _candidate_place_queries(row: dict[str, str], excerpt: str, *, max_candidates: int) -> list[str]:
    raw = row.get("place_queries") or ""
    candidates = [part.strip() for part in raw.split(";") if part.strip()]
    cleaned: list[str] = []
    for candidate in candidates:
        safe = _sanitize_text(candidate, limit=120)
        normalized = _normalize_query(safe)
        if len(normalized) < 4:
            continue
        if _blocked_geocode_query(normalized):
            continue
        if normalized not in {_normalize_query(item) for item in cleaned}:
            cleaned.append(safe)
    return cleaned[:max_candidates]


def _query_with_suffix(query: str, suffix: str) -> str:
    cleaned_suffix = suffix.strip()
    if not cleaned_suffix:
        return query
    return f"{query}, {cleaned_suffix}"


def _quality(location_type: str, partial_match: bool, result_count: int) -> str:
    if partial_match:
        return "review_partial_match"
    if location_type in {"ROOFTOP", "RANGE_INTERPOLATED"} and result_count == 1:
        return "high"
    if location_type in {"GEOMETRIC_CENTER", "APPROXIMATE"}:
        return "review_approximate"
    return "review"


def _sanitize_text(value: Any, limit: int = 180) -> str:
    text = sanitize_line_text(value)[0]
    text = _EMBEDDED_PHONE_RE.sub("[PHONE_REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_query(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u0e00-\u0e7f]+", "", value).lower()


def _blocked_geocode_query(normalized: str) -> bool:
    if normalized in _GEOCODE_BLOCKLIST:
        return True
    if any(blocked and normalized == blocked for blocked in _GEOCODE_BLOCKLIST):
        return True
    return False


def _coord(value: Any) -> str:
    try:
        return f"{float(value):.7f}"
    except (TypeError, ValueError):
        return ""


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


def _render_markdown(rows: list[dict[str, Any]], source: str | Path, *, api_key_present: bool) -> str:
    status_counts = Counter(row["google_geocode_status"] for row in rows)
    lines = [
        "# LINE Place Google Geocode",
        "",
        "Status: `shadow_only`" if api_key_present else "Status: `blocked_missing_google_maps_api_key`",
        "",
        f"- Source: `{source}`",
        "- Method: sanitized place queries only; no raw LINE text, sender ids, room ids, phone numbers, emails, URLs, or PEANO lists are sent or exported.",
        "- Google result coordinates are review evidence only and do not approve customer-facing ETR sends.",
        "",
        "## Summary",
        "",
        "| Google geocode status | Rows |",
        "| --- | ---: |",
    ]
    for status, count in status_counts.most_common():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| Message ref | Status | Query | Lat | Lng | Quality | Excerpt |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows[:60]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row["message_ref"]),
                    _md(row["google_geocode_status"]),
                    _md(row["selected_query"] or row["attempted_queries"]),
                    str(row["lat"]),
                    str(row["lng"]),
                    _md(row["geocode_quality"]),
                    _md(_sanitize_text(row["text_sanitized_excerpt"], limit=90)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
