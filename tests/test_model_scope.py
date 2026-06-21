from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ais_etr.db import RuntimeDb
from ais_etr.model import EtrPredictor
from ais_etr.model_scope import (
    compare_model_scopes,
    compare_shadow_models,
    fit_scope_challenger_model,
    review_station_mapping,
    _mapping_ready,
)
from ais_etr.schemas import CustomerAsset, OutageDevice, OutageEvent


class ModelScopeTests(unittest.TestCase):
    def test_compare_model_scopes_reports_pilot_and_expanded_segments(self):
        frame = _training_frame()
        mapping = [
            {"station_prefix": "PFA", "district": "พังโคน", "scope": "pilot_3", "status": "approved"},
            {"station_prefix": "WWA", "district": "วานรนิวาส", "scope": "expanded_6", "status": "approved"},
            {"station_prefix": "UNK", "district": "unknown", "scope": "unknown", "status": "pending"},
        ]

        rows = compare_model_scopes(frame, mapping)

        keys = {(row["model_variant"], row["evaluation_segment"]) for row in rows}
        self.assertIn(("A", "pilot_3"), keys)
        self.assertIn(("B", "expanded_6"), keys)
        self.assertIn(("C", "pilot_3"), keys)
        self.assertIn(("C", "station:PFA"), keys)
        self.assertIn(("C", "station:WWA"), keys)
        self.assertTrue(all(row["eval_scope"] != "unknown" for row in rows))
        self.assertFalse(_mapping_ready(mapping))

    def test_review_station_mapping_keeps_pending_prefixes_for_owner_review(self):
        frame = _review_frame()
        mapping = [
            {"station_prefix": "PFA", "district": "เธเธฑเธเนเธเธ", "scope": "pilot_3", "status": "approved"},
            {"station_prefix": "NPA", "district": "unknown", "scope": "unknown", "status": "pending"},
        ]

        rows = review_station_mapping(frame, mapping, {"PFA": 3, "NPA": 2})

        by_prefix = {row["station_prefix"]: row for row in rows}
        self.assertEqual(by_prefix["PFA"]["recommendation"], "approved_for_scope_calibration")
        self.assertEqual(by_prefix["NPA"]["recommendation"], "owner_review_required")
        self.assertIn("NPA01", by_prefix["NPA"]["top_feeders"])
        self.assertIn("D10105", by_prefix["NPA"]["top_op_device_site_id"])
        self.assertIn("owner", by_prefix["NPA"]["review_note"])

    def test_review_station_mapping_discovers_unmapped_prefixes_as_pending(self):
        frame = _review_frame()
        rows = review_station_mapping(frame, [], {})

        by_prefix = {row["station_prefix"]: row for row in rows}
        self.assertEqual(by_prefix["PFA"]["scope"], "unknown")
        self.assertEqual(by_prefix["PFA"]["status"], "pending")
        self.assertEqual(by_prefix["PFA"]["recommendation"], "owner_review_required")

    def test_fit_scope_challenger_filters_approved_expanded_scope(self):
        frame = _training_frame()
        mapping = [
            {"station_prefix": "PFA", "district": "พังโคน", "scope": "pilot_3", "status": "approved"},
            {"station_prefix": "WWA", "district": "วานรนิวาส", "scope": "expanded_6", "status": "approved"},
        ]

        model, summary = fit_scope_challenger_model(frame, mapping, train_scope="expanded_6")

        self.assertEqual(summary["rows_train_full"], 80)
        self.assertEqual(summary["scope_counts"], {"expanded_6": 40, "pilot_3": 40})
        self.assertEqual(model["model_role"], "shadow_challenger")
        self.assertEqual(model["scope_filter"]["included_scopes"], ["pilot_3", "expanded_6"])
        self.assertNotIn("UNK01", model["by_feeder"])

    def test_compare_shadow_models_reports_error_delta_without_customer_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite"
            db = RuntimeDb(db_path)
            db.init()
            db.upsert_customer_assets(
                [
                    CustomerAsset(
                        peano="<REDACTED_METER_REF>",
                        customer="AIS",
                        feeder="PFA05",
                        cb_ids=("PFA05VB-01",),
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )
            event = OutageEvent(
                event_id="evt-1",
                source="webex",
                webex_message_id="msg-1",
                room_id="<REDACTED_ROOM_ID>",
                raw_text="raw text should not appear",
                outage_device=OutageDevice("CB", "PFA05VB-01", "PFA05"),
                event_time="2026-06-17T10:00:00+07:00",
                district="พังโคน",
                parsed_fields={},
            )
            db.upsert_event(event)
            current = EtrPredictor(
                {
                    "model_version": "current",
                    "global": {"q10": 20, "q25": 30, "q50": 60, "q75": 80, "q90": 100},
                }
            )
            challenger = EtrPredictor(
                {
                    "model_version": "challenger",
                    "global": {"q10": 20, "q25": 30, "q50": 42, "q75": 60, "q90": 90},
                }
            )

            rows = compare_shadow_models(
                db_path,
                current,
                challenger,
                {"msg-1": {"actual_restoration_minutes": 40, "truth_source": "unit_test"}},
            )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["affected_count"], "1")
        self.assertEqual(row["current_absolute_error"], "20.0")
        self.assertEqual(row["challenger_absolute_error"], "2.0")
        self.assertEqual(row["absolute_error_delta_challenger_minus_current"], "-18.0")
        self.assertNotIn("peano", {key.lower() for key in row})
        self.assertNotIn("raw", {key.lower() for key in row})


def _training_frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1)
    rows = []
    for i in range(80):
        feeder = "PFA05" if i % 2 == 0 else "WWA01"
        rows.append(
            {
                "Feeder": feeder,
                "device_type_model": "CB" if i % 3 == 0 else "Recloser",
                "event_start": start + timedelta(hours=i),
                "target_etr_minutes": 30 + (i % 10),
            }
        )
    rows.append(
        {
            "Feeder": "UNK01",
            "device_type_model": "CB",
            "event_start": start + timedelta(hours=100),
            "target_etr_minutes": 300,
        }
    )
    return pd.DataFrame(rows)


def _review_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Feeder": "PFA05",
                "device_type_model": "CB",
                "event_start": datetime(2026, 1, 1),
                "target_etr_minutes": 35,
                "SiteDetail": "site-a",
                "OpDeviceSiteID": "D10001",
                "AffectedSiteID": "D10001",
            },
            {
                "Feeder": "NPA01",
                "device_type_model": "Recloser",
                "event_start": datetime(2026, 1, 2),
                "target_etr_minutes": 55,
                "SiteDetail": "site-b",
                "OpDeviceSiteID": "D10105",
                "AffectedSiteID": "D10105",
            },
            {
                "Feeder": "NPA01",
                "device_type_model": "Recloser",
                "event_start": datetime(2026, 1, 3),
                "target_etr_minutes": 65,
                "SiteDetail": "site-b",
                "OpDeviceSiteID": "D10105",
                "AffectedSiteID": "D10105",
            },
        ]
    )


if __name__ == "__main__":
    unittest.main()
