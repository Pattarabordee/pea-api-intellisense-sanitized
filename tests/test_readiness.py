import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ais_etr.config import Settings
from ais_etr.readiness import build_shadow_readiness_pack


class ReadinessTests(unittest.TestCase):
    def test_readiness_pack_redacts_payload_and_excludes_no_meter_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            runtime_dir = root / "runtime"
            data_dir.mkdir()
            runtime_dir.mkdir()

            registry = root / "upstream_result.xlsx"
            df = pd.DataFrame(
                [
                    {
                        "PEANO": "6101",
                        "Feeder ID": "PFA02",
                        "TX: FACILITYID": "49-1",
                        "TX: PEANO": "TR49-1",
                        "RC: FACILITYID": "PFA02VR-101",
                        "SW: FACILITYID": "PFA02VF-01",
                        "CB: FACILITYID": "PFA02VB-01",
                        "สถานะ": "OK",
                    },
                    {
                        "PEANO": "6102",
                        "TX: FACILITYID": "NO_METER",
                        "TX: PEANO": "NO_METER",
                        "สถานะ": "NO_METER",
                    },
                ]
            )
            with pd.ExcelWriter(registry) as writer:
                df.to_excel(writer, sheet_name="Upstream Trace", index=False)

            samples = data_dir / "samples.jsonl"
            samples.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": "sample-001",
                                "roomId": "sample-room",
                                "created": "2026-06-17T01:00:00Z",
                                "text": "Outage Recloser PFA02VR-101 trip at 2026-06-17 08:15",
                                "expected": {
                                    "device_id": "PFA02VR-101",
                                    "device_type": "Recloser",
                                    "feeder": "PFA02",
                                    "district": None,
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "id": "sample-002",
                                "roomId": "sample-room",
                                "created": "2026-06-17T01:01:00Z",
                                "text": "weekly coordination note",
                                "expected": {"ignored": True},
                            },
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            model_path = runtime_dir / "model_quantiles.json"
            model_path.write_text(
                json.dumps(
                    {
                        "model_version": "test-model",
                        "estimator": "quantile_baseline",
                        "global": {"q10": 10, "q25": 20, "q50": 30, "q75": 40, "q90": 50},
                        "metrics": {
                            "status": "gate_fail",
                            "q50_mae_minutes": 20,
                            "q10_q90_coverage": 0.8,
                            "gate": {"q50_mae_max": 16, "coverage_min": 0.75, "coverage_max": 0.90},
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = Settings(
                workspace=root,
                registry_path=Path("upstream_result.xlsx"),
                db_path=Path("runtime/missing.sqlite"),
                model_path=Path("runtime/model_quantiles.json"),
                event_file=Path("missing_event.xlsx"),
                distance_file=Path("missing_distance.csv"),
                etr_files=(Path("missing_etr.xlsx"),),
                notification_mode="shadow",
            )

            result = build_shadow_readiness_pack(
                settings,
                samples_path=Path("data/samples.jsonl"),
                output_dir=Path("runtime"),
                env_path=Path(".env"),
            )

            self.assertEqual(result["registry"]["with_transformer"], 1)
            self.assertEqual(result["registry"]["no_meter_backlog"], 1)
            self.assertEqual(result["match_counts"]["recloser"], 1)

            report = Path(result["report_markdown"]).read_text(encoding="utf-8-sig")
            self.assertIn("AIS ETR Shadow Readiness Report", report)
            self.assertNotIn("6101", report)

            payload = json.loads(Path(result["payload_example_json"]).read_text(encoding="utf-8-sig"))
            self.assertEqual(payload["affected_customers"][0]["peano"], "REDACTED")


if __name__ == "__main__":
    unittest.main()
