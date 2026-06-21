# Google Workspace Pilot Sheet Schema

ทุก tab เป็น private operational data store สำหรับ pilot เท่านั้น ห้าม publish public

## `settings`

| Column | Meaning |
| --- | --- |
| `key` | Setting name |
| `value` | Setting value |
| `note` | Human note |

Required row:

| key | value | note |
| --- | --- | --- |
| `pilot_key_sha256` | `<sha256 of shared pilot key>` | Store hash only, not raw key |
| `production_send` | `blocked` | Must remain blocked |

## `inbound_requests`

เก็บทุก request ที่ AIS ยิงเข้ามา และผลลัพธ์ shadow verification

| Column | Meaning |
| --- | --- |
| `received_at` | เวลาที่ Apps Script รับ request |
| `request_id` | Unique AIS event/alarm id |
| `meter_hash` | SHA-256 prefix ของ meter/PEANO |
| `meter_last4` | เลขท้าย 4 ตัว ใช้ตรวจสอบแบบไม่เปิดเลขเต็ม |
| `detected_at` | timestamp แปลงเป็น UTC |
| `detected_at_original` | timestamp ที่ AIS ส่งมา |
| `timestamp_quality_status` | `OK` หรือ `REVIEW` |
| `timestamp_quality_flags` | เช่น `timezone_assumed_bangkok` |
| `province`, `district`, `subdistrict` | พื้นที่ |
| `callback_status` | ในเวอร์ชันนี้เป็น `CAPTURED_GOOGLE_SHEETS_ONLY` หรือ `SKIPPED_DUPLICATE` |
| `verification_status` | เช่น `CONFIRMED_PEA_OUTAGE`, `UNCERTAIN_NEEDS_REVIEW` |
| `confidence` | `HIGH`, `MEDIUM`, `LOW` |
| `decision_answer` | คำตอบเชิง machine-readable |
| `decision_reason` | เหตุผล |
| `match_found`, `match_level`, `match_confidence` | ผล evidence matching |
| `device_type`, `device_id`, `feeder` | อุปกรณ์/feeder ที่ match |
| `etr_status` | `SHADOW_ONLY` หรือ `NOT_READY_FOR_AUTO_SEND` |
| `etr_minutes_p50`, `q10`, `q90`, `risk_level` | shadow ETR estimate |
| `production_send` | ต้องเป็น `blocked` |
| `request_json_redacted` | request แบบ redacted |
| `result_json` | result payload แบบ redacted |

## `topology_lookup`

ตาราง map meter hash ไปยังอุปกรณ์ในระบบจำหน่าย

| Column | Meaning |
| --- | --- |
| `meter_hash` | SHA-256 prefix 16 ตัวแรกของ meter/PEANO |
| `meter_last4` | เลขท้าย 4 ตัว สำหรับตรวจสอบ |
| `feeder` | Feeder id |
| `transformer_id` | Transformer id |
| `transformer_peano` | Transformer PEANO ถ้ามี |
| `cb_ids` | CB ids คั่นด้วย comma หรือ pipe |
| `recloser_ids` | Recloser ids คั่นด้วย comma หรือ pipe |
| `switch_ids` | Switch ids คั่นด้วย comma หรือ pipe |
| `confidence_eligible` | `TRUE` เมื่อ mapping ผ่าน review |
| `trace_status` | เช่น `reviewed`, `needs_review` |
| `updated_at` | เวลา update |
| `note` | หมายเหตุ |

## `evidence_events`

ตาราง event evidence แบบ sanitized ห้ามใส่ verbatim WebEx text หรือ room id

| Column | Meaning |
| --- | --- |
| `event_id` | Internal event id |
| `event_time` | เวลา event |
| `device_type` | `CB`, `RECLOSER`, `SWITCH`, `TRANSFORMER` |
| `device_id` | Device id |
| `feeder` | Feeder id |
| `etr_minutes_p50`, `q10`, `q90`, `risk_level` | Shadow ETR estimate |
| `source` | เช่น `sanitized WebEx + topology` |
| `evidence_note` | note แบบไม่ใส่ raw message |

## `audit_log`

| Column | Meaning |
| --- | --- |
| `logged_at` | เวลา log |
| `request_id` | request id |
| `event` | เช่น `accepted`, `duplicate` |
| `status` | verification status |
| `message` | short message |
| `production_send` | ต้องเป็น `blocked` |
