"""Build a redacted, offline quality report for strict AIS relay capture."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


MODEL_READY_THRESHOLD = 30
PRODUCTION_SEND = "blocked"


def build_report(metrics: dict[str, Any], interval_response: dict[str, Any]) -> dict[str, Any]:
    items = interval_response.get("items", [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("interval response must contain an items array")
    if metrics.get("production_send") != PRODUCTION_SEND or interval_response.get("production_send") != PRODUCTION_SEND:
        raise ValueError("production_send must remain blocked")
    bridge_counts = Counter(str(item.get("bridge_status") or "MISSING") for item in items)
    pair_counts = Counter(str(item.get("pair_status") or "MISSING") for item in items)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "interval_rows_reviewed": len(items),
        "bridge_status_counts": dict(sorted(bridge_counts.items())),
        "pair_status_counts": dict(sorted(pair_counts.items())),
        "truth_validation_counts": _safe_counts(metrics.get("truth_validation_counts")),
        "truth_closed_intervals": _safe_int(metrics.get("truth_closed_intervals")),
        "truth_strict_identity_intervals": _safe_int(metrics.get("truth_strict_identity_intervals")),
        "model_ready_clean_truth_rows": _safe_int(metrics.get("model_ready_clean_truth_rows")),
        "model_truth_review_rows": _safe_int(metrics.get("model_truth_review_rows")),
        "production_send": PRODUCTION_SEND,
        "gate_status": (
            "identity_bridge_ready_for_reconciliation"
            if _safe_int(metrics.get("model_ready_clean_truth_rows")) >= MODEL_READY_THRESHOLD
            else "identity_bridge_insufficient_clean_truth"
        ),
        "model_action": "no_train_or_evaluation_until_strict_identity_threshold",
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"strict_payload_quality_{stamp}.json"
    markdown_path = output_dir / f"strict_payload_quality_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Strict AIS Relay Payload Quality",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Rows reviewed: `{report['interval_rows_reviewed']}`",
        f"- Strict model-ready rows: `{report['model_ready_clean_truth_rows']}`",
        f"- Gate: `{report['gate_status']}`",
        f"- Production send: `{PRODUCTION_SEND}`",
        "",
        "## Bridge Status Counts",
        "",
        "| Status | Rows |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in report["bridge_status_counts"].items())
    lines.extend(
        [
            "",
            "Legacy and review rows are audit-only. This report does not train, evaluate, send callbacks, or create truth targets.",
        ]
    )
    return "\n".join(lines) + "\n"


def _safe_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(count) for key, count in sorted(value.items())}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def self_test() -> None:
    metrics = {
        "production_send": "blocked",
        "truth_closed_intervals": 1,
        "truth_strict_identity_intervals": 0,
        "model_ready_clean_truth_rows": 0,
        "model_truth_review_rows": 2,
        "truth_validation_counts": {"REVIEW_IDENTITY_KEY_REQUIRED": 2},
    }
    response = {
        "production_send": "blocked",
        "items": [
            {"bridge_status": "LEGACY_UNVERIFIED", "pair_status": "CLOSED"},
            {"bridge_status": "LEGACY_UNVERIFIED", "pair_status": "OPEN"},
        ],
    }
    report = build_report(metrics, response)
    assert report["bridge_status_counts"] == {"LEGACY_UNVERIFIED": 2}
    assert report["gate_status"] == "identity_bridge_insufficient_clean_truth"
    assert report["truth_validation_counts"]["REVIEW_IDENTITY_KEY_REQUIRED"] == 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline redacted strict relay quality report.")
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--intervals", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/private/ais_truth_protection_challenger"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return
    if not args.metrics or not args.intervals:
        parser.error("--metrics and --intervals are required")
    metrics = json.loads(args.metrics.read_text(encoding="utf-8-sig"))
    intervals = json.loads(args.intervals.read_text(encoding="utf-8-sig"))
    report = build_report(metrics, intervals)
    paths = write_report(report, args.output_dir)
    print(json.dumps({"status": "PASS", "json": str(paths[0]), "markdown": str(paths[1]), "production_send": PRODUCTION_SEND}, ensure_ascii=False))


if __name__ == "__main__":
    main()
