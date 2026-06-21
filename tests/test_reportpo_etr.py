import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.reportpo_etr import (
    REPORTPO_CANDIDATE_COLUMNS,
    REPORTPO_ETR_COLUMNS,
    build_reportpo_alias_template,
    build_reportpo_etr_query,
    import_reportpo_etr,
    join_reportpo_features_to_shadow,
    match_reportpo_truth,
)
from ais_etr.schemas import OutageDevice, OutageEvent


def _ms(value: str) -> int:
    dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class ReportPoEtrTests(unittest.TestCase):
    def test_build_query_picks_etr_request_and_sets_window_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.json"
            etr_request = _etr_request(count=500)
            other_request = {"version": "1.0.0", "queries": []}
            template.write_text(
                json.dumps(
                    [
                        {"request": json.dumps(other_request)},
                        {"request": json.dumps(etr_request)},
                    ]
                ),
                encoding="utf-8",
            )

            built = build_reportpo_etr_query(template, count=30000, restart_tokens=[["token-1"]])
            command = built["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]

            self.assertEqual(
                command["Binding"]["DataReduction"]["Primary"]["Window"]["Count"],
                30000,
            )
            self.assertEqual(
                command["Binding"]["DataReduction"]["Primary"]["Window"]["RestartTokens"],
                [["token-1"]],
            )
            properties = [
                item["Column"]["Property"]
                for item in command["Query"]["Select"]
            ]
            self.assertIn("FIRST_RESTORE_TIME", properties)
            self.assertIn("Description2", properties)
            self.assertIn("Group", properties)

    def test_import_csv_uses_first_restore_as_actual_not_event_etr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "reportpo.csv"
            output = root / "canonical.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "EVENT_ID",
                        "EVENT_START_TIME",
                        "FIRST_RESTORE_TIME",
                        "EVENT_ETR_TIME",
                        "EVENT_END_TIME",
                        "DEVICE_NAME",
                        "OfficeName",
                        "AreaName",
                        "EVENT_TYPE2",
                        "EVENT_STATUS2",
                        "ETRType",
                        "IPdateTime",
                        "Group",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "EVENT_ID": "6847000001",
                        "EVENT_START_TIME": "2026-06-17 10:00:00",
                        "FIRST_RESTORE_TIME": "2026-06-17 10:30:00",
                        "EVENT_ETR_TIME": "2026-06-17 12:00:00",
                        "EVENT_END_TIME": "2026-06-17 13:00:00",
                        "DEVICE_NAME": "PFA01R-01",
                        "OfficeName": "office",
                        "AreaName": "area",
                        "EVENT_TYPE2": "breaker_trip",
                        "EVENT_STATUS2": "restore_sent",
                        "ETRType": "first_notice",
                        "IPdateTime": "2026-06-17 10:02:00",
                        "Group": "ignored_when_event_type_present",
                    }
                )

            result = import_reportpo_etr(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["rows"], 1)
            self.assertEqual(rows[0]["reportpo_first_restore_minutes"], "30.0")
            self.assertEqual(rows[0]["event_end_duration_minutes"], "180.0")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "30.0")
            self.assertEqual(rows[0]["truth_source"], "reportpo")
            self.assertEqual(rows[0]["truth_target"], "reportpo_first_restore_minutes")
            self.assertIn("event_etr_time_not_truth", rows[0]["truth_flags"])
            self.assertIn("event_end_time_not_truth", rows[0]["truth_flags"])
            self.assertEqual(rows[0]["event_type"], "breaker_trip")
            self.assertEqual(rows[0]["event_status"], "restore_sent")
            self.assertEqual(rows[0]["etr_type"], "first_notice")
            self.assertEqual(rows[0]["ip_datetime"], "2026-06-17 10:02:00")
            self.assertEqual(rows[0]["work_type"], "breaker_trip")
            self.assertEqual(rows[0]["job_status_at_notification"], "not_dispatched_yet")
            self.assertEqual(rows[0]["feature_quality"], "proxy_only")
            self.assertIn("cause_missing", rows[0]["feature_flags"])
            self.assertIn("webex_first_notification_status_assumption", rows[0]["feature_flags"])

    def test_import_querydata_json_decodes_powerbi_compressed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "querydata.json"
            output = root / "canonical.csv"
            select = [
                _select("G0", "EVENT_ID"),
                _select("G1", "EVENT_START_TIME"),
                _select("G7", "FIRST_RESTORE_TIME"),
                _select("G8", "EVENT_ETR_TIME"),
                _select("G13", "DEVICE_NAME"),
            ]
            schema = [
                {"N": "G0", "T": 1, "DN": "D0"},
                {"N": "G1", "T": 7},
                {"N": "G7", "T": 7},
                {"N": "G8", "T": 7},
                {"N": "G13", "T": 1, "DN": "D1"},
            ]
            response = {
                "results": [
                    {
                        "result": {
                            "data": {
                                "descriptor": {"Select": select},
                                "dsr": {
                                    "DS": [
                                        {
                                            "PH": [
                                                {
                                                    "DM0": [
                                                        {
                                                            "S": schema,
                                                            "C": [
                                                                0,
                                                                _ms("2026-06-17T10:00:00"),
                                                                _ms("2026-06-17T10:45:00"),
                                                                _ms("2026-06-17T12:00:00"),
                                                                0,
                                                            ],
                                                        },
                                                        {
                                                            "C": [
                                                                1,
                                                                _ms("2026-06-17T11:00:00"),
                                                                _ms("2026-06-17T13:00:00"),
                                                                1,
                                                            ],
                                                            "\u00d8": 4,
                                                        },
                                                    ]
                                                }
                                            ],
                                            "ValueDicts": {
                                                "D0": ["6847000001", "6847000002"],
                                                "D1": ["PFA01R-01", "PFA02R-02"],
                                            },
                                        }
                                    ]
                                },
                            }
                        }
                    }
                ]
            }
            source.write_text(json.dumps([{"response": json.dumps(response)}]), encoding="utf-8")

            result = import_reportpo_etr(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["rows"], 2)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["feeder"], "PFA01")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")
            self.assertEqual(rows[1]["truth_quality"], "MISSING_RESTORE")

    def test_import_querydata_json_rejects_powerbi_semantic_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "querydata_error.json"
            output = root / "canonical.csv"
            source.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "result": {
                                    "data": {
                                        "dsr": {
                                            "DataShapes": [
                                                {
                                                    "odata.error": {
                                                        "code": "CouldNotResolveSemanticQueryDefinition",
                                                        "message": {
                                                            "value": "Could not resolve QueryDefinition"
                                                        },
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "semantic error"):
                import_reportpo_etr(source, output)

    def test_import_csv_uses_etr_ou_group_as_event_type_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "reportpo.csv"
            output = root / "canonical.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["EVENT_ID", "EVENT_START_TIME", "FIRST_RESTORE_TIME", "DEVICE_NAME", "Group"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "EVENT_ID": "6847000001",
                        "EVENT_START_TIME": "2026-06-17 10:00:00",
                        "FIRST_RESTORE_TIME": "2026-06-17 10:30:00",
                        "DEVICE_NAME": "PFA01R-01",
                        "Group": "outage_group",
                    }
                )

            import_reportpo_etr(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["event_type"], "outage_group")

    def test_match_reportpo_truth_exact_device_fills_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "2026-06-17 10:45:00",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "45.0",
                        "truth_quality": "OK",
                    }
                ],
            )
            mapping = root / "truth.csv"
            audit = root / "audit.csv"

            result = match_reportpo_truth(db.path, reportpo, mapping, audit)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(result["filled_rows"], 1)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")
            self.assertEqual(rows[0]["truth_source"], "reportpo")
            self.assertEqual(rows[0]["truth_target"], "reportpo_first_restore_minutes")
            self.assertEqual(rows[0]["truth_definition"], "FIRST_RESTORE_TIME - EVENT_START_TIME")

    def test_match_reportpo_truth_approved_alias_fills_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "2026-06-17 10:45:00",
                        "device_id": "PFA01R-02",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "45.0",
                        "truth_quality": "OK",
                    }
                ],
            )
            alias = root / "aliases.csv"
            _write_aliases(alias, [{"webex_device_id": "PFA01R-01", "reportpo_device_id": "PFA01R-02", "status": "approved"}])
            mapping = root / "truth.csv"

            result = match_reportpo_truth(db.path, reportpo, mapping, alias_file=alias)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(result["alias_matched_rows"], 1)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")

    def test_match_reportpo_truth_pending_or_rejected_alias_does_not_fill_mapping(self):
        for status in ("pending", "rejected", ""):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
                    reportpo = root / "reportpo.csv"
                    _write_canonical_reportpo(
                        reportpo,
                        [
                            {
                                "event_number": "6847000001",
                                "event_start_time": "2026-06-17 10:00:00",
                                "first_restore_time": "2026-06-17 10:45:00",
                                "device_id": "ZZZ01R-02",
                                "feeder": "ZZZ01",
                                "actual_restoration_minutes": "45.0",
                                "truth_quality": "OK",
                            }
                        ],
                    )
                    alias = root / "aliases.csv"
                    _write_aliases(alias, [{"webex_device_id": "PFA01R-01", "reportpo_device_id": "ZZZ01R-02", "status": status}])
                    mapping = root / "truth.csv"

                    result = match_reportpo_truth(db.path, reportpo, mapping, alias_file=alias)
                    with mapping.open(encoding="utf-8-sig", newline="") as handle:
                        rows = list(csv.DictReader(handle))

                    self.assertEqual(result["matched_rows"], 0)
                    self.assertEqual(result["filled_rows"], 0)
                    self.assertEqual(rows[0]["actual_restoration_minutes"], "")

    def test_match_reportpo_truth_alias_missing_restore_does_not_fill_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "",
                        "device_id": "PFA01R-02",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "",
                        "truth_quality": "MISSING_RESTORE",
                    }
                ],
            )
            alias = root / "aliases.csv"
            _write_aliases(alias, [{"webex_device_id": "PFA01R-01", "reportpo_device_id": "PFA01R-02", "status": "approved"}])
            mapping = root / "truth.csv"

            result = match_reportpo_truth(db.path, reportpo, mapping, alias_file=alias)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["invalid_truth_rows"], 1)
            self.assertEqual(result["filled_rows"], 0)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "")

    def test_match_reportpo_truth_feeder_candidate_exports_but_does_not_fill_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-99")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "2026-06-17 10:45:00",
                        "device_id": "PFA01R-02",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "45.0",
                        "truth_quality": "OK",
                    }
                ],
            )
            mapping = root / "truth.csv"
            candidates = root / "candidates.csv"

            result = match_reportpo_truth(db.path, reportpo, mapping, candidates_csv=candidates)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                mapping_rows = list(csv.DictReader(handle))
            with candidates.open(encoding="utf-8-sig", newline="") as handle:
                candidate_rows = list(csv.DictReader(handle))

            self.assertEqual(result["filled_rows"], 0)
            self.assertEqual(mapping_rows[0]["actual_restoration_minutes"], "")
            self.assertGreaterEqual(result["candidate_rows"], 1)
            self.assertEqual(candidate_rows[0]["match_level"], "feeder")

    def test_match_reportpo_truth_duplicate_approved_alias_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(reportpo, [])
            alias = root / "aliases.csv"
            _write_aliases(
                alias,
                [
                    {"webex_device_id": "PFA01R-01", "reportpo_device_id": "PFA01R-02", "status": "approved"},
                    {"webex_device_id": "PFA01R-01", "reportpo_device_id": "PFA01R-03", "status": "approved"},
                ],
            )

            with self.assertRaises(ValueError):
                match_reportpo_truth(db.path, reportpo, root / "truth.csv", alias_file=alias)

    def test_alias_template_adds_pending_rows_and_preserves_approved_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.csv"
            _write_candidates(
                candidates,
                [
                    {
                        "webex_device_id": "PFA01R-99",
                        "candidate_device_id": "PFA01R-02",
                        "match_level": "feeder",
                        "delta_minutes": "3",
                    },
                    {
                        "webex_device_id": "PFA02R-99",
                        "candidate_device_id": "PFA02R-02",
                        "match_level": "feeder",
                        "delta_minutes": "5",
                    },
                ],
            )
            aliases = root / "aliases.csv"
            _write_aliases(
                aliases,
                [{"webex_device_id": "PFA02R-99", "reportpo_device_id": "PFA02R-02", "status": "approved"}],
            )

            result = build_reportpo_alias_template(candidates, aliases)
            with aliases.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["added_rows"], 1)
            self.assertEqual(len(rows), 2)
            pending = [row for row in rows if row["status"] == "pending"]
            self.assertEqual(pending[0]["webex_device_id"], "PFA01R-99")

    def test_match_reportpo_truth_ambiguous_does_not_fill_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:01:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "2026-06-17 10:30:00",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "30.0",
                        "truth_quality": "OK",
                    },
                    {
                        "event_number": "6847000002",
                        "event_start_time": "2026-06-17 10:02:00",
                        "first_restore_time": "2026-06-17 10:50:00",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "48.0",
                        "truth_quality": "OK",
                    },
                ],
            )
            mapping = root / "truth.csv"

            result = match_reportpo_truth(db.path, reportpo, mapping)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["ambiguous_rows"], 1)
            self.assertEqual(result["filled_rows"], 0)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "")

    def test_match_reportpo_truth_preserves_existing_mapping_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "first_restore_time": "2026-06-17 10:45:00",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "actual_restoration_minutes": "45.0",
                        "truth_quality": "OK",
                    }
                ],
            )
            mapping = root / "truth.csv"
            with mapping.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["webex_message_id", "event_number", "actual_restoration_minutes"])
                writer.writeheader()
                writer.writerow({"webex_message_id": "msg-1", "event_number": "", "actual_restoration_minutes": "99"})

            result = match_reportpo_truth(db.path, reportpo, mapping)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["preserved_existing_rows"], 1)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "99")

    def test_join_reportpo_features_to_shadow_exact_device_exports_feature_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            reportpo = root / "reportpo.csv"
            _write_canonical_reportpo(
                reportpo,
                [
                    {
                        "event_number": "6847000001",
                        "event_start_time": "2026-06-17 10:00:00",
                        "device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "event_type": "breaker_trip",
                        "event_status": "restore_sent",
                        "etr_type": "first_notice",
                        "etr_type_description": "first notice",
                        "ip_datetime": "2026-06-17T10:02:00",
                        "cause_group": "equipment",
                        "work_type": "breaker_trip",
                        "job_status_at_notification": "not_dispatched_yet",
                        "feature_quality": "cause_available",
                        "feature_flags": "webex_first_notification_status_assumption",
                    }
                ],
            )
            output = root / "features.csv"

            result = join_reportpo_features_to_shadow(db.path, reportpo, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(rows[0]["match_status"], "matched")
            self.assertEqual(rows[0]["match_reason"], "exact_device_time")
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["reportpo_device_id"], "PFA01R-01")
            self.assertEqual(rows[0]["event_type"], "breaker_trip")
            self.assertEqual(rows[0]["event_status"], "restore_sent")
            self.assertEqual(rows[0]["work_type"], "breaker_trip")
            self.assertEqual(rows[0]["job_status_at_notification"], "not_dispatched_yet")
            self.assertEqual(rows[0]["feature_quality"], "cause_available")


def _select(name: str, property_name: str) -> dict:
    return {
        "Kind": 1,
        "Value": name,
        "GroupKeys": [
            {
                "Source": {"Entity": "ETR_OU", "Property": property_name},
                "Calc": name,
                "IsSameAsSelect": True,
            }
        ],
        "Name": f"ETR_OU.{property_name}",
    }


def _etr_request(count: int) -> dict:
    select = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "e"}},
                "Property": property_name,
            },
            "Name": f"ETR_OU.{property_name}",
        }
        for property_name in ["EVENT_ID", "EVENT_START_TIME", "FIRST_RESTORE_TIME", "DEVICE_NAME"]
    ]
    return {
        "version": "1.0.0",
        "queries": [
            {
                "Query": {
                    "Commands": [
                        {
                            "SemanticQueryDataShapeCommand": {
                                "Query": {
                                    "Version": 2,
                                    "From": [
                                        {"Name": "e", "Entity": "ETR_OU", "Type": 0},
                                        {"Name": "e1", "Entity": "ETRtype", "Type": 0},
                                    ],
                                    "Select": select,
                                },
                                "Binding": {
                                    "Primary": {"Groupings": [{"Projections": [0, 1, 2, 3]}]},
                                    "DataReduction": {"DataVolume": 3, "Primary": {"Window": {"Count": count}}},
                                    "Version": 1,
                                },
                            }
                        }
                    ]
                }
            }
        ],
    }


def _runtime_db_with_event(root: Path, event_time: str, device_id: str) -> RuntimeDb:
    db = RuntimeDb(root / "runtime.sqlite")
    db.init()
    db.insert_webex_message({"id": "msg-1", "roomId": "<REDACTED_ROOM_ID>", "created": event_time, "text": "event"})
    db.upsert_event(
        OutageEvent(
            event_id="event-1",
            source="webex",
            webex_message_id="msg-1",
            room_id="<REDACTED_ROOM_ID>",
            raw_text="event",
            event_time=event_time,
            outage_device=OutageDevice(device_type="Recloser", device_id=device_id, feeder=device_id[:5]),
        )
    )
    return db


def _write_canonical_reportpo(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_ETR_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REPORTPO_ETR_COLUMNS})


def _write_aliases(path: Path, rows: list[dict[str, str]]) -> None:
    columns = ["webex_device_id", "reportpo_device_id", "reason", "status", "reviewed_by", "reviewed_at"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_CANDIDATE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REPORTPO_CANDIDATE_COLUMNS})


if __name__ == "__main__":
    unittest.main()
