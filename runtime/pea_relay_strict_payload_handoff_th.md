# SUPERSEDED: PEA Relay Strict Payload Handoff

AIS ส่งตรงเข้า Render และไม่ต้องสร้าง `source_event_id` หรือ `site_id` เพื่อให้ผ่าน gate เอกสาร canonical คือ `runtime/ais_inbound_api_contract_v1.md`.

สถานะ: `shadow` เท่านั้น และ `production_send=blocked`.

เอกสารนี้ใช้สำหรับเจ้าของ PEA integration relay. Relay ต้องส่งข้อมูลที่ upstream มีอยู่จริง; ห้ามสร้าง correlation id หรือจับคู่เหตุย้อนหลังเพื่อให้ผ่าน model gate.

## Mapping ที่ต้องส่ง

| API field | OUTAGE | RESTORE | กติกา |
| --- | --- | --- | --- |
| `request_id` | ต้องมี | ต้องมี | idempotency id ต่อ request/retry; RESTORE ใช้ค่าใหม่ได้ |
| `source_event_id` | ต้องมี | ต้องมีค่าเดียวกับ OUTAGE | upstream incident/alarm correlation id; ห้ามสร้างจาก meter หรือเวลา |
| `event_type` | `OUTAGE` | `RESTORE` | ต้องเป็น explicit value |
| `meter_no` | ต้องมี | ต้องตรงกัน | meter/PEANO ของ site เดียวกัน |
| `site_id` หรือ `location_id` | ต้องมี | ต้องตรงกัน | identifier ของ AIS site/location เดียวกัน |
| `timestamp` | ต้องมี | ต้องมี | ISO 8601 พร้อม timezone |
| `outage_at` | ต้องมี | ไม่ต้องส่ง | เวลาไฟดับของ site |
| `restore_at` | ไม่ต้องส่ง | ต้องมี | เวลาไฟกลับของ site |

หาก source ไม่มี timezone ให้ relay normalize เป็น Asia/Bangkok (`+07:00`) พร้อมบันทึกเหตุผลใน log ภายในของ relay. ห้ามเดา `source_event_id` หรือสร้าง OUTAGE/RESTORE synthetic.

## ตรวจ payload ก่อนส่ง

ใช้ validator ใน repository นี้กับ payload จริงเฉพาะใน secure environment:

```powershell
python -m ais_etr.strict_relay_contract --pair-input <private-pair.json>
```

ผล `STRICT_RELAY_READY` หมายถึง payload ผ่าน contract check เท่านั้น ไม่ได้หมายถึงระบบเปิด production. ผล `REVIEW_REQUIRED` ให้แก้ source field ตาม `reason_codes`; output จะแสดงเฉพาะ hash/reference ไม่มี raw identifier.

## อ่านผลหลังเหตุจริง

- `202 Accepted` หมายถึง receiver รับ request ได้ ไม่ได้หมายถึง model-ready.
- หลัง OUTAGE ที่ valid: metrics/interval audit ต้องพบ `STRICT_AWAITING_RESTORE`.
- หลัง RESTORE ที่ valid: ต้องพบ `STRICT_MODEL_READY` หรือ review reason ที่ตรวจสอบได้.
- `truth_validation_counts.REVIEW_IDENTITY_KEY_REQUIRED` ชี้ว่า relay ยังไม่ส่ง stable `source_event_id`.
- `truth_validation_counts.REVIEW_OUTAGE_TIMESTAMP` หรือ `REVIEW_RESTORE_TIMESTAMP` ชี้ว่า event-specific timestamp ยังไม่ครบ.

ห้ามส่ง callback, ETR หรือลูกค้าสื่อสารรายสำคัญจาก flow นี้. การ train/evaluation เริ่มได้เมื่อมี `STRICT_MODEL_READY` อย่างน้อย 30 แถวและผ่าน identity reconciliation เท่านั้น.
