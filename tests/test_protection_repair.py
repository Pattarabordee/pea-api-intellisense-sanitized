import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.protection_repair import (
    apply_protection_mapping_overrides,
    build_private_protection_mapping_overrides,
)
from ais_etr.schemas import CustomerAsset


class FakeTraceClient:
    def query_layer(self, layer_id, where, **kwargs):
        if layer_id == 11:
            return {
                "features": [
                    {
                        "attributes": {"FACILITYID": "PFA05VB-01", "FEEDERID": "PFA05"},
                        "geometry": {"x": 1, "y": 2, "spatialReference": {"wkid": 102100}},
                    }
                ]
            }
        return {"features": []}

    def trace_downstream(self, geometry):
        return {
            "success": True,
            "traceResult": [
                {
                    "name": "DS_LowVoltageMeter",
                    "id": 25,
                    "features": [
                        {"attributes": {"PEANO": "6101"}},
                        {"attributes": {"PEANO": "6102"}},
                        {"attributes": {"PEANO": "9999"}},
                    ],
                }
            ],
        }


class ProtectionRepairTests(unittest.TestCase):
    def test_build_private_overrides_exports_only_confident_trace_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _db_with_assets(root)
            audit = _write_source_trace_audit(root)

            result = build_private_protection_mapping_overrides(
                db.path,
                audit,
                root / "private" / "overrides.csv",
                device_id="PFA05VB-01",
                status="approved",
                client=FakeTraceClient(),
            )

            self.assertEqual(result["override_rows"], 1)
            rows = _read_csv(root / "private" / "overrides.csv")
            self.assertEqual(rows[0]["peano"], "6101")
            self.assertEqual(rows[0]["device_id"], "PFA05VB-01")
            self.assertEqual(rows[0]["mapping_field"], "cb_ids")
            self.assertEqual(rows[0]["status"], "approved")

    def test_apply_overrides_uses_only_approved_and_dedupes_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _db_with_assets(root)
            overrides = root / "overrides.csv"
            with overrides.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "peano",
                        "feeder",
                        "device_type",
                        "device_id",
                        "mapping_field",
                        "status",
                        "source",
                        "reason",
                        "reviewed_by",
                        "reviewed_at",
                    ],
                )
                writer.writeheader()
                base = {
                    "peano": "6101",
                    "feeder": "PFA05",
                    "device_type": "CB",
                    "device_id": "PFA05VB-01",
                    "mapping_field": "cb_ids",
                    "source": "test",
                }
                writer.writerow({**base, "status": "approved"})
                writer.writerow({**base, "status": "approved"})
                writer.writerow({**base, "device_id": "PFA04VB-01", "status": "pending"})

            result = apply_protection_mapping_overrides(db.path, overrides, audit_output=root / "audit.csv")

            assets = {asset.peano: asset for asset in db.load_customer_assets()}
            self.assertEqual(assets["6101"].cb_ids, ("PFA05VB-01",))
            self.assertEqual(result["assets_updated"], 1)
            actions = [row["action"] for row in _read_csv(root / "audit.csv")]
            self.assertIn("updated", actions)
            self.assertIn("unchanged", actions)
            self.assertIn("skipped", actions)


def _db_with_assets(root: Path) -> RuntimeDb:
    db = RuntimeDb(root / "ais.sqlite")
    db.init()
    db.upsert_customer_assets(
        [
            CustomerAsset(peano="6101", customer="AIS", feeder="PFA05", trace_status="OK", confidence_eligible=True),
            CustomerAsset(peano="6102", customer="AIS", feeder="PFA05", trace_status="NO_METER", confidence_eligible=False),
        ]
    )
    return db


def _write_source_trace_audit(root: Path) -> Path:
    path = root / "source_trace.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["device_type", "device_id", "feeder", "source_trace_result"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "device_type": "CB",
                "device_id": "PFA05VB-01",
                "feeder": "PFA05",
                "source_trace_result": "source_trace_confirms_confident_ais_downstream",
            }
        )
    return path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
