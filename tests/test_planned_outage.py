import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ais_etr.config import Settings
from ais_etr.db import RuntimeDb
from ais_etr.pipeline import AisEtrPipeline
from ais_etr.planned_outage import (
    COL_BUSINESS_DAYS,
    COL_CONTACT_CENTER_SENT_AT,
    COL_DEVICE_ID,
    COL_EVENT_NUMBER,
    COL_NOTICE_STATUS,
    COL_NOTICE_TIME,
    COL_OPERATION_TIME,
    COL_REGION,
    COL_RESPONSIBLE_OFFICE,
    COL_SCHEDULED_START,
    COL_SEND_STATUS,
    COL_WORK_CENTER,
    pick_planned_area,
)
from ais_etr.schemas import CustomerAsset, NotificationRecord


class CaptureNotifier:
    def __init__(self):
        self.payloads = []

    def send(self, payload):
        self.payloads.append(payload)
        return NotificationRecord(payload=payload, status="CAPTURED")


class PlannedOutageTests(unittest.TestCase):
    def test_pick_planned_area_prefers_responsible_office(self):
        districts = ("พังโคน", "วาริชภูมิ", "นิคมน้ำอูน")
        self.assertEqual(
            pick_planned_area(
                {
                    COL_WORK_CENTER: "กฟอ.พังโคน",
                    COL_RESPONSIBLE_OFFICE: "กฟอ.วาริชภูมิ",
                },
                districts,
            ),
            "วาริชภูมิ",
        )
        self.assertIsNone(
            pick_planned_area(
                {
                    COL_WORK_CENTER: "กฟอ.พังโคน",
                    COL_RESPONSIBLE_OFFICE: "กฟอ.วานรนิวาส",
                },
                districts,
            )
        )
        self.assertEqual(
            pick_planned_area(
                {
                    COL_WORK_CENTER: "กฟอ.พังโคน",
                    COL_RESPONSIBLE_OFFICE: "",
                },
                districts,
            ),
            "พังโคน",
        )

    def test_notify_planned_outages_filters_area_lead_and_ais_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "planned.csv"
            self._write_csv(
                csv_path,
                [
                    self._row("1001", "กฟอ.พังโคน", "49-100001", "2026-06-21 08:00:00"),
                    self._row("1002", "กฟอ.วาริชภูมิ", "49-100001", "2026-06-19 08:00:00"),
                    self._row("1003", "กฟอ.วานรนิวาส", "49-100001", "2026-06-21 08:00:00"),
                    self._row("1004", "กฟอ.นิคมน้ำอูน", "49-999999", "2026-06-21 08:00:00"),
                ],
            )
            settings = Settings(
                workspace=tmp_path,
                db_path=Path("runtime/test.sqlite"),
                planned_outage_file=csv_path,
                planned_notice_min_days=3,
                notification_mode="shadow",
                mock_webhook_url=None,
            )
            db = RuntimeDb(settings.resolve(settings.db_path))
            db.init()
            db.upsert_customer_assets(
                [
                    CustomerAsset(
                        peano="6101",
                        feeder="PFA02",
                        transformer_id="49-100001",
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )

            notifier = CaptureNotifier()
            pipeline = AisEtrPipeline(settings, db=db, notifier=notifier)
            first = pipeline.notify_planned_outages(reference_time=datetime(2026, 6, 17, 8, 0, 0))
            second = pipeline.notify_planned_outages(reference_time=datetime(2026, 6, 17, 8, 0, 0))

            self.assertEqual(first.target_area_rows, 3)
            self.assertEqual(first.eligible_rows, 2)
            self.assertEqual(first.notifications, 1)
            self.assertEqual(first.skipped_too_soon, 1)
            self.assertEqual(first.skipped_no_match, 1)
            self.assertEqual(second.notifications, 0)
            self.assertEqual(second.skipped_existing, 1)

            payload = notifier.payloads[0]
            self.assertEqual(payload["type"], "planned_outage")
            self.assertEqual(payload["area"]["district"], "พังโคน")
            self.assertEqual(payload["planned_outage"]["minimum_lead_days"], 3)
            self.assertEqual(payload["affected_customers"][0]["peano"], "6101")

    def _write_csv(self, path, rows):
        columns = [
            COL_EVENT_NUMBER,
            COL_REGION,
            COL_WORK_CENTER,
            COL_RESPONSIBLE_OFFICE,
            COL_DEVICE_ID,
            COL_SCHEDULED_START,
            COL_NOTICE_TIME,
            COL_OPERATION_TIME,
            COL_BUSINESS_DAYS,
            COL_NOTICE_STATUS,
            COL_SEND_STATUS,
            COL_CONTACT_CENTER_SENT_AT,
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def _row(self, event_number, responsible_office, device_id, scheduled_start):
        return {
            COL_EVENT_NUMBER: event_number,
            COL_REGION: "กฟฉ.1",
            COL_WORK_CENTER: "กฟอ.พังโคน",
            COL_RESPONSIBLE_OFFICE: responsible_office,
            COL_DEVICE_ID: device_id,
            COL_SCHEDULED_START: scheduled_start,
            COL_NOTICE_TIME: "2026-06-01 08:00:00",
            COL_OPERATION_TIME: "",
            COL_BUSINESS_DAYS: "10",
            COL_NOTICE_STATUS: "แจ้งทันกำหนด",
            COL_SEND_STATUS: "ส่งแล้ว",
            COL_CONTACT_CENTER_SENT_AT: "2026-06-01 08:01:00",
        }


if __name__ == "__main__":
    unittest.main()
