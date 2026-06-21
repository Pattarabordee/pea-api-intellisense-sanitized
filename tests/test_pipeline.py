import tempfile
import unittest
from pathlib import Path

from ais_etr.config import Settings
from ais_etr.db import RuntimeDb
from ais_etr.pipeline import AisEtrPipeline
from ais_etr.schemas import CustomerAsset, NotificationRecord
from ais_etr.webex import NullWebexClient


class CaptureNotifier:
    def __init__(self):
        self.payloads = []

    def send(self, payload):
        self.payloads.append(payload)
        return NotificationRecord(payload=payload, status="CAPTURED")


class PipelineTests(unittest.TestCase):
    def test_poll_once_idempotent_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = Settings(
                workspace=tmp_path,
                db_path=Path("runtime/test.sqlite"),
                model_path=Path("runtime/missing_model.json"),
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
                        recloser_ids=("PFA02VR-101",),
                        trace_status="OK",
                        confidence_eligible=True,
                    )
                ]
            )
            messages = [
                {
                    "id": "m1",
                    "roomId": "<REDACTED_ROOM_ID>",
                    "created": "2026-06-17T10:00:00Z",
                    "text": "ไฟดับ Recloser PFA02VR-101 อ.พังโคน",
                }
            ]
            notifier = CaptureNotifier()
            pipeline = AisEtrPipeline(
                settings,
                db=db,
                webex_client=NullWebexClient(messages),
                notifier=notifier,
            )
            first = pipeline.poll_once()
            second = pipeline.poll_once()
            self.assertEqual(first.notifications, 1)
            self.assertEqual(second.notifications, 0)
            self.assertEqual(len(notifier.payloads), 1)
            self.assertEqual(notifier.payloads[0]["mode"], "shadow")
            self.assertEqual(notifier.payloads[0]["affected_customers"][0]["peano"], "6101")


if __name__ == "__main__":
    unittest.main()

