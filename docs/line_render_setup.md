# LINE Render Setup Runbook

สถานะระบบ: shadow-only. ยังไม่ส่ง production และยังไม่ใช้ LINE text เป็น truth สำหรับลูกค้า

## 1. Deploy service บน Render

ใช้ Blueprint จาก `render.yaml` แล้ว deploy service ชื่อ:

```text
pea-line-webhook
```

หลัง deploy ให้เช็ก health:

```text
https://pea-line-webhook.onrender.com/health
```

ถ้า Render ตั้ง URL คนละชื่อ ให้ใช้ URL ของ service นั้นแทน

## 2. ใส่ Environment Variables ใน Render

ใส่เฉพาะ service `pea-line-webhook`:

```text
LINE_CHANNEL_SECRET=<secret ใหม่จาก LINE>
LINE_ALLOWED_GROUP_IDS=<group id ที่ owner/moderator อนุมัติ>
LINE_CAPTURE_MODE=shadow
```

ถ้ายังไม่รู้ group id แต่ต้องการ deploy ให้ผ่านก่อน ใส่ค่าชั่วคราวนี้ได้:

```text
LINE_ALLOWED_GROUP_IDS=BOOTSTRAP_DO_NOT_CAPTURE
```

ค่าชั่วคราวนี้จะทำให้ service เปิดได้ แต่จะไม่ capture ข้อความจากกลุ่มจริง

ห้ามส่ง `LINE_CHANNEL_SECRET` ในแชทหรือเอกสารแชร์ ให้ใส่ใน Render โดยตรง

## 3. ตั้งค่าใน LINE Official Account Manager

ไปที่:

```text
Settings > Messaging API
```

ใส่ Webhook URL:

```text
https://pea-line-webhook.onrender.com/line/webhook
```

จากนั้นกด Save และ Verify

ถ้า Verify ผ่าน แต่ข้อความจริงยังไม่ถูกเก็บ แปลว่า endpoint ถึงแล้ว แต่ `LINE_ALLOWED_GROUP_IDS` ยังไม่ตรงกับกลุ่มจริง

## 4. เปิดให้ bot เข้า group

ใน LINE Developers Console หรือ OA settings ให้เปิดการใช้งาน group chat สำหรับ Messaging API channel แล้วเพิ่ม Official Account เข้ากลุ่มที่ owner อนุมัติแล้ว

หลังเพิ่ม bot เข้ากลุ่ม ให้ส่งข้อความทดสอบสั้น ๆ:

```text
LINE smoke test no outage
```

ข้อความนี้ควรไม่ใช้ข้อมูลลูกค้า, ไม่ใส่ PEANO list, ไม่ใส่เบอร์โทร, ไม่ใส่ชื่อคน

## 5. ข้อมูลที่ต้องส่งกลับมาให้ Codex

ส่งมาได้:

```text
Render service URL: https://...
LINE webhook Verify: pass/fail
LINE group id status: known/unknown
LINE_ALLOWED_GROUP_IDS set: yes/no
Smoke test sent at: YYYY-MM-DD HH:MM
Render log error, ถ้ามี: copy เฉพาะ error code/status ห้าม copy secret หรือ raw group/user id
```

ห้ามส่งมา:

```text
LINE_CHANNEL_SECRET
raw group id ถ้ายังไม่ได้อนุมัติให้ใช้ในระบบ
sender user id
raw LINE chat ที่มีข้อมูลลูกค้า
PEANO list เต็ม
เบอร์โทร, email, URL ส่วนตัว
```

## 6. ความหมายของ response

`200` พร้อม `accepted > 0`: รับข้อความและบันทึก sanitized evidence แล้ว

`200` พร้อม `accepted = 0`: endpoint ทำงาน แต่ event ถูก reject เช่น group ไม่อยู่ใน allowlist หรือไม่ใช่ text message

`401`: signature ไม่ผ่าน ให้เช็กว่า Render ใช้ `LINE_CHANNEL_SECRET` ใหม่ตรงกับ LINE channel

`413`: body ใหญ่เกิน limit

`503`: config ยังไม่พร้อม เช่น secret ว่าง, allowlist ว่าง, หรือ capture mode ไม่ใช่ shadow

## 7. Bootstrap allowlist without raw group id

Preferred path:

```text
LINE_ALLOWED_GROUP_IDS=BOOTSTRAP_DO_NOT_CAPTURE
LINE_ALLOWED_CHAT_HASHES=
```

Add the bot to the approved LINE group and send:

```text
LINE smoke test no outage
```

Open Render Logs for `pea-line-webhook` and look for:

```text
"event": "line_rejected"
"reason": "group_not_allowlisted"
"chat_id_hash": "chat_..."
```

Copy only the `chat_...` value into Render:

```text
LINE_ALLOWED_CHAT_HASHES=chat_...
```

Keep `LINE_ALLOWED_GROUP_IDS=BOOTSTRAP_DO_NOT_CAPTURE` or clear it later. Do not copy raw group id, raw user id, or raw LINE text into shared reports.
