import csv
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ais_etr.line_place_topology import build_line_place_topology_lookup, extract_place_queries


class LinePlaceTopologyTests(unittest.TestCase):
    def test_extract_place_queries_skips_generic_outage_words(self):
        queries = extract_place_queries("รับแจ้งไฟช็อต บ้านนาแยง 093-324-8700")

        self.assertIn("บ้านนาแยง", queries)
        self.assertNotIn("รับแจ้งไฟช็อต", queries)
        self.assertTrue(all("093-324-8700" not in query for query in queries))

    def test_extract_place_queries_splits_route_phrase(self):
        queries = extract_place_queries("ไฟช็อต บ้านนาเหมืองไปหนองหญ้าปล้อง [PHONE_REDACTED]")

        self.assertIn("บ้านนาเหมือง", queries)
        self.assertIn("หนองหญ้าปล้อง", queries)

    def test_lookup_matches_place_and_redacts_private_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.csv"
            with review.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "message_ref",
                        "created",
                        "source_kind",
                        "model_event_probability",
                        "text_sanitized_excerpt",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "message_ref": "msg_place",
                        "created": "2026-06-23T08:00:00+07:00",
                        "source_kind": "line",
                        "model_event_probability": "1.0",
                        "text_sanitized_excerpt": "รับแจ้งไฟช็อต บ้านนาแยง 093-324-8700",
                    }
                )
                writer.writerow(
                    {
                        "message_ref": "msg_feeder",
                        "created": "2026-06-23T08:05:00+07:00",
                        "source_kind": "line",
                        "model_event_probability": "1.0",
                        "text_sanitized_excerpt": "PFA05 T/L Show CG",
                    }
                )

            upstream = root / "upstream.xlsx"
            df = pd.DataFrame(
                [
                    {
                        "peano": "6101000001",
                        "meter_location": "บ้านนาแยง",
                        "feeder": "PFA07",
                        "moo": "1",
                        "subdistrict": "นาแยง",
                        "district": "พังโคน",
                        "tx_facilityid": "51-112062",
                        "tx_feeder": "PFA07",
                        "tx_location": "บ้านนาแยง",
                        "rc_facilityids": "PFA07R-01 | PFA07R-02",
                        "rc_location": "บ้านนาแยง",
                        "sw_facilityids": "PFA07S-01 | PFA07S-02 | PFA07S-03",
                        "sw_location": "บ้านนาแยง",
                        "cb_facilityids": "PFA07VB-01",
                        "cb_location": "สถานี",
                        "status": "OK",
                        "customer_name": "Somchai Secret",
                    },
                    {
                        "peano": "6101000002",
                        "meter_location": "other place",
                        "feeder": "PFA05",
                        "tx_facilityid": "54-000001",
                        "tx_feeder": "PFA05",
                        "rc_facilityids": "PFA05R-01",
                        "sw_facilityids": "",
                        "cb_facilityids": "PFA05VB-01",
                        "status": "OK",
                        "customer_name": "Private Customer",
                    },
                ]
            )
            with pd.ExcelWriter(upstream) as writer:
                df.to_excel(writer, sheet_name="Upstream Trace", index=False)

            output = root / "lookup.csv"
            enriched = root / "enriched.csv"
            markdown = root / "lookup.md"
            owner_review = root / "owner.csv"
            owner_markdown = root / "owner.md"
            result = build_line_place_topology_lookup(
                review_source=review,
                upstream=upstream,
                output=output,
                enriched_output=enriched,
                markdown_output=markdown,
                owner_review_output=owner_review,
                owner_review_markdown_output=owner_markdown,
            )

            self.assertEqual(result["status"], "ok")
            rows = _read_csv(output)
            by_ref = {row["message_ref"]: row for row in rows}
            self.assertEqual(by_ref["msg_place"]["lookup_status"], "matched_local_place")
            self.assertEqual(by_ref["msg_place"]["primary_feeder"], "PFA07")
            self.assertEqual(by_ref["msg_place"]["transformer_ids"], "51-112062")
            self.assertIn("PFA07R-01", by_ref["msg_place"]["recloser_ids"])
            self.assertEqual(by_ref["msg_feeder"]["lookup_status"], "feeder_mentioned_only")
            self.assertEqual(by_ref["msg_feeder"]["primary_feeder"], "PFA05")

            combined = "\n".join(
                path.read_text(encoding="utf-8-sig")
                for path in (output, enriched, markdown, owner_review, owner_markdown)
            )
            self.assertNotIn("6101000001", combined)
            self.assertNotIn("Somchai", combined)
            self.assertNotIn("Private Customer", combined)
            self.assertNotIn("093-324-8700", combined)
            self.assertIn("[PHONE_REDACTED]", combined)
            owner_rows = _read_csv(owner_review)
            self.assertEqual(len(owner_rows), 1)
            self.assertEqual(owner_rows[0]["message_ref"], "msg_feeder")
            self.assertIn("owner_feeder", owner_rows[0])


def _read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
