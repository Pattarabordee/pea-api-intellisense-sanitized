import csv
import json
import tempfile
import unittest
from pathlib import Path

from ais_etr.reportpo_model_inventory import build_reportpo_model_inventory


class ReportPoModelInventoryTests(unittest.TestCase):
    def test_inventory_extracts_partial_schema_and_visual_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            network = root / "network.json"
            querydata = root / "querydata.json"
            output = root / "inventory.csv"
            candidates = root / "candidates.csv"
            visuals = root / "visuals.csv"
            markdown = root / "inventory.md"

            truncated_schema = (
                '{"schemas":[{"modelId":1,"schema":{"Entities":['
                '{"Name":"PO","EdmName":"Sandbox.PO","Properties":['
                '{"Name":"EventID","DataType":1,"Column":{}},'
                '{"Name":"IPdateTime","DataType":7,"FormatString":"%d/%M/yyyy HH:mm:ss","Column":{}}'
                ']},'
                '{"Name":"NotifyStatusTable","EdmName":"Sandbox.NotifyStatusTable","Properties":['
                '{"Name":"Description","DataType":1,"Column":{}}'
            )
            network.write_text('[{"body": ' + json.dumps(truncated_schema) + '} invalid tail', encoding="utf-8")
            querydata.write_text(
                json.dumps(
                    [
                        {
                            "tab": "ETR",
                            "status": 200,
                            "request": json.dumps(
                                {
                                    "queries": [
                                        _query(
                                            "visual-etr",
                                            [
                                                ("e", "ETR_OU", "EVENT_ID"),
                                                ("e", "ETR_OU", "EVENT_START_TIME"),
                                                ("e", "ETR_OU", "FIRST_RESTORE_TIME"),
                                                ("e", "ETR_OU", "DEVICE_NAME"),
                                            ],
                                        )
                                    ]
                                }
                            ),
                        },
                        {
                            "tab": "Pending",
                            "status": 200,
                            "request": json.dumps(
                                {
                                    "queries": [
                                        _query(
                                            "visual-pending",
                                            [
                                                ("p", "Pending", "EVENT_ID"),
                                                ("p", "Pending", "DEVICE_NAME"),
                                                ("p", "Pending", "EVENT_STATUS2"),
                                            ],
                                        )
                                    ]
                                }
                            ),
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = build_reportpo_model_inventory(network, querydata, output, candidates, visuals, markdown)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                inventory_rows = list(csv.DictReader(handle))
            with candidates.open(encoding="utf-8-sig", newline="") as handle:
                candidate_rows = list(csv.DictReader(handle))
            markdown_text = markdown.read_text(encoding="utf-8")

            self.assertGreaterEqual(result["unique_fields"], 7)
            self.assertTrue(any(row["entity"] == "PO" and row["property"] == "IPdateTime" for row in inventory_rows))
            self.assertTrue(any(row["entity"] == "ETR_OU" and row["property"] == "FIRST_RESTORE_TIME" for row in inventory_rows))
            pending_status = [
                row
                for row in candidate_rows
                if row["entity"] == "Pending" and row["property"] == "EVENT_STATUS2"
            ]
            self.assertEqual(pending_status[0]["priority"], "high")
            self.assertEqual(pending_status[0]["category"], "status_notification")
            self.assertIn("Recommended Next Probe", markdown_text)
            self.assertNotIn("token", markdown_text.lower())


def _query(visual_id: str, columns: list[tuple[str, str, str]]) -> dict:
    from_rows = []
    seen_sources = set()
    selects = []
    for source_name, entity, property_name in columns:
        if source_name not in seen_sources:
            seen_sources.add(source_name)
            from_rows.append({"Name": source_name, "Entity": entity, "Type": 0})
        selects.append(
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": source_name}},
                    "Property": property_name,
                },
                "Name": f"{entity}.{property_name}",
                "NativeReferenceName": property_name,
            }
        )
    return {
        "Query": {
            "Commands": [
                {
                    "SemanticQueryDataShapeCommand": {
                        "Query": {"Version": 2, "From": from_rows, "Select": selects},
                        "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(selects)))}]}},
                    }
                }
            ]
        },
        "ApplicationContext": {"Sources": [{"VisualId": visual_id}]},
    }


if __name__ == "__main__":
    unittest.main()
