# MVP Demo Recording Pack

- Generated: `2026-06-22T03:05:47Z`
- Target length: `4-5 minutes`
- UI language: English first
- Spoken script: Thai
- Mode: `shadow`
- Production send: `blocked`

## Before Recording

- Open web console: `https://pea-api-intellisense-web.onrender.com`
- Keep API health tab optional: `https://pea-api-intellisense-api.onrender.com/health`
- Do not show Render env, API key, DB URL, verbatim WebEx, full meter/PEANO, or customer identity.
- Point to visible guardrails: `mode = shadow`, `production_send = blocked`, `Auto ETR not enabled`.

## Current Evidence To Mention

- Cloud health/database: `ok` / `ok`
- Real AIS cloud requests: `0`
- Green rows: `0` / `30`
- AIS truth owner queue: `30` rows
- PEA topology owner queue: `30` rows

## Spoken Script

### 0:00-0:30 Hook

ปัญหาเดิมคือเวลา site ของ AIS มีไฟดับ ทีม AIS เห็นว่า site fail แต่ไม่เห็น grid context ของ PEA จึงต้องโทรถามกันเอง ข้อมูลกระจัดกระจาย ช้า และ audit ย้อนหลังยาก.

### 0:30-1:20 API Request

แนวทางใหม่คือ AIS ส่ง request เดียวเข้ามาที่ PEA API พร้อม `request_id`, timestamp, meter reference และพื้นที่ ระบบตอบ `202 Accepted` แล้วเก็บหลักฐานแบบ redacted ใน cloud.

### 1:20-2:10 PEA Trace

ฝั่ง PEA ไม่ได้ตอบจาก meter อย่างเดียว แต่ trace ว่า meter นั้นอยู่หลัง feeder และ protection device ตัวไหน โดยยังซ่อน customer identity และไม่โชว์เลข meter จริง.

### 2:10-3:00 Evidence Gate

ระบบตรวจต่อว่า protection device มีเหตุการณ์ในช่วงเวลาใกล้กับ AIS แจ้งมาหรือไม่ จุดนี้สำคัญ เพราะเราไม่เดา เราใช้ evidence gate ก่อนให้ cause หรือ ETR มีน้ำหนัก.

### 3:00-3:45 ETR Candidate

เมื่อ evidence เพียงพอ ระบบสร้าง cause lane และ ETR candidate พร้อม uncertainty band แต่ยังเป็น shadow candidate เท่านั้น AIS outage/restore ยังเป็น truth สำหรับวัดผล.

### 3:45-4:30 Guardrail

ตอนนี้ cloud shadow pilot พร้อมรับ request จริงแล้ว แต่ Auto ETR production ยังไม่เปิด เพราะ green rows ยังไม่ถึง 30 และยังต้องมี owner approval. ดังนั้น `production_send` ยังถูก block.

### 4:30-5:00 Ask

สิ่งที่ต้องขอคือให้ AIS ยิง cloud pilot จริง, ให้ owner ช่วยยืนยัน AIS truth และ PEA topology จาก queue ที่เตรียมไว้, แล้วค่อยใช้หลักฐานนี้ตัดสิน production Auto ETR แบบปลอดภัย.

## One-Line Close

โปรเจกต์นี้เปลี่ยนงานโทรถามแบบ manual ให้เป็น API trace ที่มีหลักฐาน ตรวจสอบได้ และคุมความเสี่ยงก่อนเปิด production.
