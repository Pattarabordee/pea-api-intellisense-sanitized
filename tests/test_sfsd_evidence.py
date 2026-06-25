import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.sfsd_evidence import (
    build_sfsd_event_detail_query,
    build_sfsd_gap_decision_pack,
    build_sfsd_gap_resolution_audit,
    build_sfsd_long_outage_evidence,
    build_sfsd_remaining_gap_review,
    build_sfsd_source_trace_candidates,
    import_sfsd_events,
)


class SfsdEvidenceTests(unittest.TestCase):
    def test_builds_sfsd_event_detail_query_from_models_exploration_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "models.json"
            template.write_text('{"models":[{"id":"169742226"}]}', encoding="utf-8")

            query = build_sfsd_event_detail_query(template, count=50)
            command = query["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
            select_names = [item["Name"] for item in command["Query"]["Select"]]
            where = command["Query"]["Where"][0]["Condition"]["In"]["Values"][0][0]["Literal"]["Value"]

            self.assertEqual(query["modelId"], "169742226")
            self.assertIn("Event.EventNumber", select_names)
            self.assertIn("Event.OutageDateTime", select_names)
            self.assertIn("Min(Event.FirstStepDuration)", select_names)
            self.assertIn("Event.OpDeviceID", select_names)
            self.assertEqual(where, "'ไฟฟ้าขัดข้อง'")
            self.assertEqual(command["Binding"]["DataReduction"]["Primary"]["Window"]["Count"], 50)

    def test_imports_thai_sfsd_export_to_canonical_evidence_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sfsd_export.csv"
            output = root / "sfsd_latest.csv"
            _write_sfsd_source(source)

            result = import_sfsd_events(source, output)
            rows = _read_csv(output)

            self.assertEqual(result["rows"], 2)
            self.assertEqual(rows[0]["event_number"], "6787274286")
            self.assertEqual(rows[0]["feeder"], "WWA10")
            self.assertEqual(rows[0]["device_id"], "WWA10VR-101")
            self.assertEqual(rows[0]["duration_minutes"], "0.08")
            self.assertEqual(rows[0]["evidence_quality"], "PEA_MOMENTARY_OR_SHORT")
            self.assertIn("cause_not_found", rows[0]["evidence_flags"])

    def test_joins_sfsd_to_long_outage_by_event_bridge_without_turning_it_into_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sfsd_source = root / "sfsd_export.csv"
            sfsd_latest = root / "sfsd_latest.csv"
            priority = root / "priority.csv"
            event_bridge = root / "event_bridge.csv"
            output = root / "evidence.csv"
            markdown = root / "evidence.md"
            _write_sfsd_source(sfsd_source)
            import_sfsd_events(sfsd_source, sfsd_latest)
            _write_priority(priority)
            _write_event_bridge(event_bridge)

            result = build_sfsd_long_outage_evidence(
                priority,
                sfsd_latest,
                output,
                markdown,
                event_bridge_csv=event_bridge,
                max_window_minutes=1440,
            )
            rows = _read_csv(output)
            by_ref = {row["event_ref"]: row for row in rows}

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(by_ref["msg-wwa"]["sfsd_match_status"], "matched")
            self.assertEqual(by_ref["msg-wwa"]["sfsd_match_level"], "event_number")
            self.assertEqual(by_ref["msg-wwa"]["sfsd_event_number"], "6787274286")
            self.assertEqual(by_ref["msg-wwa"]["pea_ais_pattern"], "pea_momentary_or_short_ais_long")
            self.assertEqual(by_ref["msg-wwa"]["cause_status"], "cause_not_found")
            self.assertIn("AIS outage/restore remains", markdown.read_text(encoding="utf-8-sig"))
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertNotIn("Y2lzY29", output.read_text(encoding="utf-8-sig"))

    def test_feeder_only_sfsd_candidate_stays_audit_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sfsd_latest = root / "sfsd_latest.csv"
            priority = root / "priority.csv"
            output = root / "evidence.csv"
            _write_rows(
                sfsd_latest,
                [
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
                ],
                [
                    {
                        "event_number": "1001",
                        "outage_time": "2026-03-24 17:34:00",
                        "duration_minutes": "10",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-99",
                        "evidence_quality": "PEA_SUSTAINED",
                    }
                ],
            )
            _write_rows(
                priority,
                [
                    "priority_rank",
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "remaining_actual_minutes",
                    "active_p50",
                    "active_error_minutes",
                ],
                [
                    {
                        "priority_rank": "1",
                        "event_ref": "msg-pfa",
                        "event_time": "2026-03-24T17:34:33",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "remaining_actual_minutes": "811",
                        "active_p50": "36",
                        "active_error_minutes": "775",
                    }
                ],
            )

            build_sfsd_long_outage_evidence(priority, sfsd_latest, output)
            row = _read_csv(output)[0]

            self.assertEqual(row["sfsd_match_status"], "no_match")
            self.assertEqual(row["sfsd_match_level"], "feeder_time_audit_only")
            self.assertEqual(row["pea_ais_pattern"], "sfsd_feeder_candidate_only")

    def test_builds_remaining_gap_review_for_unconfirmed_sfsd_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.csv"
            output = root / "gap.csv"
            markdown = root / "gap.md"
            _write_rows(
                evidence,
                [
                    "priority_rank",
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "remaining_actual_minutes",
                    "active_error_minutes",
                    "sfsd_match_status",
                    "sfsd_match_level",
                    "sfsd_event_number",
                    "sfsd_outage_time",
                    "sfsd_delta_minutes",
                    "sfsd_duration_minutes",
                    "sfsd_feeder",
                    "sfsd_device_id",
                    "sfsd_evidence_quality",
                    "pea_ais_pattern",
                    "recommended_next_action",
                ],
                [
                    {
                        "priority_rank": "1",
                        "event_ref": "msg-confirmed",
                        "event_time": "2026-03-24T17:00:00",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "active_error_minutes": "180",
                        "sfsd_match_status": "matched",
                        "sfsd_match_level": "event_number",
                        "pea_ais_pattern": "pea_sustained_ais_long",
                    },
                    {
                        "priority_rank": "2",
                        "event_ref": "msg-feeder",
                        "event_time": "2026-03-24T17:34:33",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "remaining_actual_minutes": "811",
                        "active_error_minutes": "775",
                        "sfsd_match_status": "no_match",
                        "sfsd_match_level": "feeder_time_audit_only",
                        "sfsd_event_number": "1001",
                        "sfsd_device_id": "PFA09R-99",
                        "sfsd_duration_minutes": "10",
                        "sfsd_evidence_quality": "PEA_SUSTAINED",
                        "pea_ais_pattern": "sfsd_feeder_candidate_only",
                    },
                    {
                        "priority_rank": "3",
                        "event_ref": "msg-none",
                        "event_time": "2026-03-22T15:32:31",
                        "feeder": "SEK06",
                        "device_id": "SEK06VR-104",
                        "remaining_actual_minutes": "200.51",
                        "active_error_minutes": "187.51",
                        "sfsd_match_status": "no_match",
                        "sfsd_match_level": "none",
                        "pea_ais_pattern": "sfsd_no_match",
                    },
                ],
            )

            result = build_sfsd_remaining_gap_review(evidence, output, markdown)
            rows = _read_csv(output)
            by_ref = {row["event_ref"]: row for row in rows}

            self.assertEqual(result["review_rows"], 2)
            self.assertNotIn("msg-confirmed", by_ref)
            self.assertEqual(by_ref["msg-feeder"]["gap_class"], "topology_or_device_bridge_review")
            self.assertEqual(by_ref["msg-feeder"]["model_decision"], "blocked_until_owner_or_topology_approval")
            self.assertEqual(by_ref["msg-none"]["gap_class"], "missing_sfsd_event_or_bridge")
            self.assertIn("missing event bridge", result["recommendation"])
            self.assertNotIn("Y2lzY29", output.read_text(encoding="utf-8-sig"))
            self.assertIn("Feeder-only SFSD candidates are audit-only", markdown.read_text(encoding="utf-8-sig"))

    def test_gap_resolution_audit_checks_registry_overlap_without_exporting_meter_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "runtime.sqlite"
            gap_review = root / "gap_review.csv"
            sfsd = root / "sfsd.csv"
            output = root / "resolution.csv"
            markdown = root / "resolution.md"
            _write_customer_asset_db(db)
            _write_rows(
                gap_review,
                [
                    "review_rank",
                    "priority_rank",
                    "event_ref",
                    "event_time",
                    "feeder",
                    "device_id",
                    "sfsd_candidate_device_id",
                    "gap_class",
                    "review_priority",
                    "remaining_actual_minutes",
                    "active_error_minutes",
                ],
                [
                    {
                        "review_rank": "1",
                        "priority_rank": "2",
                        "event_ref": "msg-topology",
                        "event_time": "2026-03-24T17:34:33",
                        "feeder": "PFA09",
                        "device_id": "PFA09R-03",
                        "sfsd_candidate_device_id": "PFA09F-05/2",
                        "gap_class": "topology_or_device_bridge_review",
                        "review_priority": "P0",
                        "active_error_minutes": "775",
                    },
                    {
                        "review_rank": "2",
                        "priority_rank": "9",
                        "event_ref": "msg-missing",
                        "event_time": "2026-03-22T15:32:31",
                        "feeder": "SEK06",
                        "device_id": "SEK06VR-104",
                        "gap_class": "missing_sfsd_event_or_bridge",
                        "review_priority": "P1",
                        "active_error_minutes": "187",
                    },
                    {
                        "review_rank": "3",
                        "priority_rank": "10",
                        "event_ref": "msg-far",
                        "event_time": "2026-03-18T15:32:31",
                        "feeder": "SEK06",
                        "device_id": "SEK06VR-104",
                        "gap_class": "missing_sfsd_event_or_bridge",
                        "review_priority": "P1",
                        "active_error_minutes": "100",
                    },
                ],
            )
            _write_rows(
                sfsd,
                [
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
                ],
                [
                    {
                        "event_number": "1001",
                        "outage_time": "2026-03-22T15:33:00",
                        "duration_minutes": "30",
                        "feeder": "SEK06",
                        "device_id": "SEK06VR-104",
                        "evidence_quality": "PEA_SUSTAINED",
                    }
                ],
            )

            result = build_sfsd_gap_resolution_audit(gap_review, sfsd, db, output, markdown)
            rows = {row["event_ref"]: row for row in _read_csv(output)}

            self.assertEqual(result["audit_rows"], 3)
            self.assertEqual(rows["msg-topology"]["webex_device_asset_count"], "2")
            self.assertEqual(rows["msg-topology"]["candidate_device_asset_count"], "1")
            self.assertEqual(rows["msg-topology"]["overlap_asset_count"], "0")
            self.assertEqual(rows["msg-topology"]["resolution_status"], "do_not_bridge_different_ais_paths")
            self.assertEqual(rows["msg-missing"]["nearest_same_device_event_number"], "1001")
            self.assertEqual(rows["msg-missing"]["resolution_status"], "same_device_sfsd_candidate_found_review_bridge")
            self.assertEqual(rows["msg-far"]["nearest_same_device_event_number"], "1001")
            self.assertEqual(rows["msg-far"]["resolution_status"], "same_device_far_sfsd_candidate_context_only")
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertIn("PEANO lists are intentionally not exported", markdown.read_text(encoding="utf-8-sig"))

    def test_exports_source_trace_candidates_from_topology_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolution = root / "resolution.csv"
            output = root / "candidates.csv"
            _write_rows(
                resolution,
                [
                    "review_rank",
                    "feeder",
                    "webex_device_id",
                    "sfsd_candidate_device_id",
                    "resolution_status",
                ],
                [
                    {
                        "review_rank": "1",
                        "feeder": "PFA09",
                        "webex_device_id": "PFA09R-03",
                        "sfsd_candidate_device_id": "PFA09F-05/2",
                        "resolution_status": "source_trace_required_for_topology_gap",
                    },
                    {
                        "review_rank": "2",
                        "feeder": "PFA09",
                        "webex_device_id": "PFA09R-03",
                        "sfsd_candidate_device_id": "PFA09F-05/2",
                        "resolution_status": "source_trace_required_for_topology_gap",
                    },
                    {
                        "review_rank": "3",
                        "feeder": "SEK06",
                        "webex_device_id": "SEK06VR-104",
                        "resolution_status": "same_device_far_sfsd_candidate_context_only",
                    },
                ],
            )

            result = build_sfsd_source_trace_candidates(resolution, output)
            rows = {(row["source_gap_role"], row["device_id"]): row for row in _read_csv(output)}

            self.assertEqual(result["rows"], 2)
            self.assertEqual(rows[("webex_device", "PFA09R-03")]["event_count"], "2")
            self.assertEqual(rows[("webex_device", "PFA09R-03")]["device_type"], "Recloser")
            self.assertEqual(rows[("sfsd_candidate_device", "PFA09F-05/2")]["device_type"], "Switch")

    def test_gap_decision_pack_rejects_invalid_sfsd_candidate_when_webex_trace_confirms_ais(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resolution = root / "resolution.csv"
            trace = root / "trace.csv"
            output = root / "decision.csv"
            markdown = root / "decision.md"
            _write_rows(
                resolution,
                [
                    "review_rank",
                    "priority_rank",
                    "event_ref",
                    "event_time",
                    "feeder",
                    "webex_device_id",
                    "sfsd_candidate_device_id",
                    "resolution_status",
                ],
                [
                    {
                        "review_rank": "1",
                        "priority_rank": "1",
                        "event_ref": "msg-pfa09",
                        "event_time": "2026-03-24T17:34:33",
                        "feeder": "PFA09",
                        "webex_device_id": "PFA09R-03",
                        "sfsd_candidate_device_id": "PFA09F-05/2",
                        "resolution_status": "source_trace_required_for_topology_gap",
                    }
                ],
            )
            _write_rows(
                trace,
                ["device_id", "source_trace_result", "ais_confident_hits"],
                [
                    {
                        "device_id": "PFA09R-03",
                        "source_trace_result": "source_trace_confirms_confident_ais_downstream",
                        "ais_confident_hits": "3",
                    },
                    {
                        "device_id": "PFA09F-05/2",
                        "source_trace_result": "source_device_not_found",
                        "ais_confident_hits": "0",
                    },
                ],
            )

            result = build_sfsd_gap_decision_pack(resolution, trace, output, markdown)
            row = _read_csv(output)[0]

            self.assertEqual(result["rows"], 1)
            self.assertEqual(row["final_decision"], "reject_sfsd_candidate_webex_device_confirmed")
            self.assertEqual(row["model_decision"], "blocked_for_model_training")
            self.assertIn("Reject invalid SFSD candidate", result["recommendation"])
            self.assertIn("excludes PEANO lists", markdown.read_text(encoding="utf-8-sig"))


def _write_sfsd_source(path: Path) -> None:
    _write_rows(
        path,
        [
            "หมายเลขเหตุการณ์",
            "ประเภทเหตุการณ์",
            "วันเวลาที่ไฟฟ้าขัดข้อง",
            "ระยะเวลา (นาที)",
            "ฟีดเดอร์",
            "GIS-TAG ของอุปกรณ์ที่ทำงาน",
            "ประเภทของอุปกรณ์ที่ทำงาน",
            "รหัสอุปกรณ์",
            "สถานะการทำงาน",
            "เฟสอุปกรณ์",
            "หน่วยงาน",
            "สภาพอากาศ",
            "พบ/ไม่พบสาเหตุ",
            "สาเหตุหลัก",
        ],
        [
            {
                "หมายเลขเหตุการณ์": "6787274286",
                "ประเภทเหตุการณ์": "ไฟฟ้าขัดข้อง",
                "วันเวลาที่ไฟฟ้าขัดข้อง": "5/13/2026 10:30:06 AM",
                "ระยะเวลา (นาที)": "0.08",
                "ฟีดเดอร์": "WWA10",
                "GIS-TAG ของอุปกรณ์ที่ทำงาน": "2147RC000000039",
                "ประเภทของอุปกรณ์ที่ทำงาน": "Recloser",
                "รหัสอุปกรณ์": "WWA10VR-101",
                "สถานะการทำงาน": "TR1",
                "เฟสอุปกรณ์": "ABC",
                "หน่วยงาน": "กฟภ.",
                "สภาพอากาศ": "อากาศปกติ",
                "พบ/ไม่พบสาเหตุ": "ไม่พบสาเหตุ",
                "สาเหตุหลัก": "สภาพสิ่งแวดล้อม",
            },
            {
                "หมายเลขเหตุการณ์": "999",
                "วันเวลาที่ไฟฟ้าขัดข้อง": "2026-05-13 11:00:00",
                "ระยะเวลา (นาที)": "25",
                "ฟีดเดอร์": "WWA10",
                "รหัสอุปกรณ์": "WWA10VR-102",
                "พบ/ไม่พบสาเหตุ": "พบสาเหตุ",
                "สาเหตุหลัก": "ต้นไม้",
            },
        ],
    )


def _write_priority(path: Path) -> None:
    _write_rows(
        path,
        [
            "priority_rank",
            "event_ref",
            "event_time",
            "feeder",
            "device_id",
            "remaining_actual_minutes",
            "active_p50",
            "active_error_minutes",
        ],
        [
            {
                "priority_rank": "1",
                "event_ref": "msg-wwa",
                "event_time": "2026-05-13T10:30:06.452000",
                "feeder": "WWA10",
                "device_id": "WWA10VR-101",
                "remaining_actual_minutes": "804.48",
                "active_p50": "28",
                "active_error_minutes": "776.48",
            }
        ],
    )


def _write_event_bridge(path: Path) -> None:
    _write_rows(
        path,
        [
            "webex_message_ref",
            "event_time",
            "device_id",
            "feeder",
            "reportpo_etr_match_status",
            "reportpo_etr_event_number",
            "reportpo_etr_device_id",
            "reportpo_etr_event_start_time",
        ],
        [
            {
                "webex_message_ref": "msg-wwa",
                "event_time": "2026-05-13T10:30:06.452000",
                "device_id": "WWA10VR-101",
                "feeder": "WWA10",
                "reportpo_etr_match_status": "matched",
                "reportpo_etr_event_number": "6787274286",
                "reportpo_etr_device_id": "WWA10VR-101",
                "reportpo_etr_event_start_time": "2026-05-13 10:30:06",
            }
        ],
    )


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_customer_asset_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE customer_assets (
            peano TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            feeder TEXT,
            meter_location TEXT,
            transformer_id TEXT,
            transformer_peano TEXT,
            recloser_ids TEXT NOT NULL,
            switch_ids TEXT NOT NULL,
            cb_ids TEXT NOT NULL,
            trace_status TEXT,
            confidence_eligible INTEGER NOT NULL,
            raw_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    rows = [
        ("6101000001", "PFA09", ["PFA09R-03"], [], []),
        ("6101000002", "PFA09", ["PFA09R-03"], [], []),
        ("6101000003", "PFA09", [], ["PFA09F-05/2"], []),
        ("6101000004", "SEK06", ["SEK06VR-104"], [], []),
    ]
    for peano, feeder, reclosers, switches, cbs in rows:
        conn.execute(
            """
            INSERT INTO customer_assets (
                peano, customer, feeder, meter_location, transformer_id, transformer_peano,
                recloser_ids, switch_ids, cb_ids, trace_status, confidence_eligible, raw_json, updated_at
            ) VALUES (?, 'AIS', ?, '', '', '', ?, ?, ?, 'OK', 1, '{}', '2026-06-18T00:00:00')
            """,
            (peano, feeder, json.dumps(reclosers), json.dumps(switches), json.dumps(cbs)),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    unittest.main()
