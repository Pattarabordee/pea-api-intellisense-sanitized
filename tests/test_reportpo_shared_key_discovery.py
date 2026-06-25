import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_shared_key_discovery import (
    build_reportpo_shared_key_discovery,
    load_approved_manual_bridge_rows,
)


class ReportpoSharedKeyDiscoveryTests(unittest.TestCase):
    def test_discovers_candidates_and_overlap_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "inventory.csv"
            visuals = root / "visuals.csv"
            features = root / "features.csv"
            lifecycle = root / "lifecycle.csv"
            bridge = root / "bridge.csv"
            candidates = root / "candidates.csv"
            overlap = root / "overlap.csv"
            markdown = root / "discovery.md"
            pathfinding = root / "pathfinding.md"
            manual = root / "manual.csv"
            _write_inventory(inventory)
            _write_visuals(visuals)
            _write_features_with_job(features)
            _write_lifecycle_with_job(lifecycle)
            _write_bridge(bridge)

            result = build_reportpo_shared_key_discovery(
                inventory,
                visuals,
                features,
                lifecycle,
                bridge,
                candidates,
                overlap,
                markdown,
                manual,
                pathfinding,
            )
            candidate_rows = _read_csv(candidates)
            overlap_rows = _read_csv(overlap)
            statuses = {row["status"] for row in overlap_rows}
            job_row = _find_overlap(overlap_rows, "job_id", "job_id")
            event_row = _find_overlap(overlap_rows, "event_number", "event_number")
            device_row = _find_overlap(overlap_rows, "device_id", "op_device_id")
            missing_row = _find_overlap(overlap_rows, "shared_job_id_or_ticket_id", "shared_job_id_or_ticket_id")

            self.assertTrue(result["shared_key_found"])
            self.assertFalse(manual.exists())
            self.assertIn("exact_match", statuses)
            self.assertIn("no_overlap", statuses)
            self.assertIn("missing_field", statuses)
            self.assertIn("ambiguous_duplicate", statuses)
            self.assertEqual(job_row["status"], "exact_match")
            self.assertEqual(job_row["key_strength"], "strong_shared_key_candidate")
            self.assertEqual(job_row["focus_overlap_values"], "1")
            self.assertEqual(event_row["status"], "no_overlap")
            self.assertEqual(device_row["status"], "ambiguous_duplicate")
            self.assertEqual(missing_row["status"], "missing_field")
            self.assertTrue(any(row["property"] == "EVENT_ID" for row in candidate_rows))
            self.assertTrue(any(row["property"] == "JOB_ID" for row in candidate_rows))
            self.assertTrue(any(row["property"] == "TicketNo" for row in candidate_rows))
            self.assertTrue(any(row["property"] == "WorkOrderNo" for row in candidate_rows))
            self.assertIn("shared_key_found", markdown.read_text(encoding="utf-8-sig"))
            self.assertIn("ReportPO/eRespond Shared-Key Discovery Decision", pathfinding.read_text(encoding="utf-8-sig"))
            self.assertNotIn("raw-message", markdown.read_text(encoding="utf-8-sig"))

    def test_creates_manual_template_when_no_strong_key_found_and_loads_only_approved_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "inventory.csv"
            visuals = root / "visuals.csv"
            features = root / "features.csv"
            lifecycle = root / "lifecycle.csv"
            bridge = root / "bridge.csv"
            candidates = root / "candidates.csv"
            overlap = root / "overlap.csv"
            markdown = root / "discovery.md"
            manual = root / "manual.csv"
            _write_inventory(inventory)
            _write_visuals(visuals)
            _write_features_without_job(features)
            _write_lifecycle_without_job(lifecycle)
            _write_bridge(bridge)

            result = build_reportpo_shared_key_discovery(
                inventory,
                visuals,
                features,
                lifecycle,
                bridge,
                candidates,
                overlap,
                markdown,
                manual,
            )
            manual_rows = _read_csv(manual)

            self.assertFalse(result["shared_key_found"])
            self.assertEqual(manual_rows[0]["review_status"], "pending")
            self.assertEqual(load_approved_manual_bridge_rows(manual), [])

            manual_rows[0]["review_status"] = "approved"
            manual_rows[0]["shared_job_id_or_ticket_id"] = "JOB-1"
            manual_rows.append(
                {
                    "webex_message_ref": "msg-safe-2",
                    "reportpo_etr_event_number": "E2",
                    "shared_job_id_or_ticket_id": "",
                    "po_event_number": "PO-2",
                    "review_status": "rejected",
                    "reviewed_by": "tester",
                    "reviewed_at": "2026-06-18",
                    "notes": "",
                }
            )
            _write_dict_rows(manual, list(manual_rows[0].keys()), manual_rows)

            approved = load_approved_manual_bridge_rows(manual)
            self.assertEqual(len(approved), 1)
            self.assertEqual(approved[0]["shared_job_id_or_ticket_id"], "JOB-1")
            self.assertIn("shared_key_not_found", markdown.read_text(encoding="utf-8-sig"))


def _write_inventory(path: Path) -> None:
    columns = [
        "source",
        "entity",
        "property",
        "role",
        "data_type",
        "data_type_label",
        "format_string",
        "visual_count",
        "visual_ids",
    ]
    rows = [
        ["network.json", "ETR_OU", "EVENT_ID", "column", "1", "string", "", "2", "v1;v2"],
        ["network.json", "ETR_OU", "JOB_ID", "column", "1", "string", "", "1", "v1"],
        ["network.json", "ETR_OU", "TicketNo", "column", "1", "string", "", "0", ""],
        ["network.json", "ETR_OU", "WorkOrderNo", "column", "1", "string", "", "0", ""],
        ["network.json", "PO", "EventID", "column", "1", "string", "", "1", "v3"],
        ["network.json", "PO", "JOB_ID", "column", "1", "string", "", "1", "v3"],
        ["network.json", "PO", "OpDeviceID", "column", "1", "string", "", "1", "v3"],
        ["network.json", "Pending", "RequestID", "column", "1", "string", "", "1", "v4"],
    ]
    _write_rows(path, columns, rows)


def _write_visuals(path: Path) -> None:
    columns = [
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
    ]
    rows = [["tab", "200", "visual-1", "0", "ETR_OU", "JOB_ID", "column", "JOB_ID", "e1", "", "", "true", "file"]]
    _write_rows(path, columns, rows)


def _write_features_with_job(path: Path) -> None:
    columns = ["event_number", "job_id", "device_id", "feeder"]
    rows = [
        ["E1", "JOB-1", "DEV-1", "SEK06"],
        ["E1DUP", "JOB-2", "DEV-1", "SEK06"],
    ]
    _write_rows(path, columns, rows)


def _write_lifecycle_with_job(path: Path) -> None:
    columns = ["event_number", "job_id", "op_device_id", "feeder"]
    rows = [
        ["PO-1", "JOB-1", "DEV-1", "SEK06"],
        ["PO-2", "JOB-3", "DEV-1", "SEK06"],
    ]
    _write_rows(path, columns, rows)


def _write_features_without_job(path: Path) -> None:
    columns = ["event_number", "device_id", "feeder"]
    rows = [["E1", "DEV-1", "SEK06"]]
    _write_rows(path, columns, rows)


def _write_lifecycle_without_job(path: Path) -> None:
    columns = ["event_number", "op_device_id", "feeder"]
    rows = [["PO-1", "DEV-1", "SEK06"]]
    _write_rows(path, columns, rows)


def _write_bridge(path: Path) -> None:
    columns = ["webex_message_ref", "reportpo_etr_event_number", "reportpo_etr_device_id", "device_id", "feeder"]
    rows = [["msg-safe-1", "E1", "DEV-1", "DEV-1", "SEK06"]]
    _write_rows(path, columns, rows)


def _find_overlap(rows: list[dict[str, str]], left: str, right: str) -> dict[str, str]:
    for row in rows:
        if row["left_field"] == left and row["right_field"] == right:
            return row
    raise AssertionError(f"Missing overlap row {left}->{right}")


def _write_rows(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(columns, row)))


def _write_dict_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
