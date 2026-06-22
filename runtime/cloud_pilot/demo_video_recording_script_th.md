# Demo Video Recording Script: PEA API Intellisense

วันที่จัดทำ: 2026-06-22  
เป้าหมาย: อัดวิดีโอสั้นให้กรรมการเห็นภาพว่า AIS จากเดิมต้องโทรถาม PEA เปลี่ยนเป็น API trace ที่มีหลักฐาน ตรวจสอบย้อนหลังได้ และยังปลอดภัยเพราะเป็น shadow mode

## ก่อนอัด

- เปิด Web Console: https://pea-api-intellisense-web.onrender.com
- เปิด API Health ไว้อีกแท็บ: https://pea-api-intellisense-api.onrender.com/health
- ยืนยันคำสำคัญบนจอ: `mode = shadow`, `production_send = blocked`, `Auto ETR not enabled`
- ห้ามโชว์ API key, Render env, DATABASE_URL, raw meter/PEANO, customer identity, token, room id

## สคริปต์ 4-5 นาที

### 0:00-0:30 Hook

“ปัญหาเดิมคือเวลาสถานี AIS มีไฟดับ ทีม AIS เห็นว่า site fail แต่ไม่เห็น context ของระบบจำหน่าย PEA จึงต้องโทรถาม PEA ด้วยตัวเอง ทำให้ข้อมูลซ้ำซ้อน ช้า และ audit ย้อนหลังยาก”

ชี้บนจอ:
- Manual phone-call workflow
- API workflow

### 0:30-1:20 AIS ยิง API

“แนวทางใหม่คือ AIS ส่ง request เดียวเข้ามาที่ PEA API โดยมี `request_id`, เวลาเกิดเหตุ, meter reference แบบ redacted และพื้นที่เกิดเหตุ ระบบตอบ `202 Accepted` ก่อน แล้วเก็บหลักฐานไว้ในฐานข้อมูล”

ชี้บนจอ:
- Step 1 `AIS request`
- `request_id`
- `202 Accepted`

### 1:20-2:10 PEA trace หาอุปกรณ์ป้องกัน

“ฝั่ง PEA ไม่ตอบจาก meter อย่างเดียว แต่ trace ว่า meter นี้อยู่หลัง feeder และ protection device ตัวไหน ข้อมูลที่โชว์เป็น demo/redacted เพื่อไม่เปิดเผยลูกค้าหรือ meter จริง”

ชี้บนจอ:
- Step 2 `PEA trace`
- `meter ref ending ... -> feeder ...`
- ข้อความ `customer identity hidden`

### 2:10-3:00 เช็ค Evidence

“หลัง trace แล้ว ระบบดู evidence ว่าอุปกรณ์ป้องกันตัวนั้นมี event ในช่วงเวลาใกล้กับ AIS แจ้งมาหรือไม่ ตรงนี้คือหัวใจ: ไม่ใช่แค่เดา แต่มี evidence gate”

ชี้บนจอ:
- Step 3 `Protection evidence`
- `CB DEMO-CB-01`
- time delta จาก AIS timestamp

### 3:00-3:45 Cause และ ETR Candidate

“เมื่อ evidence ผ่าน ระบบสร้าง cause lane และ ETR candidate ได้ เช่น P50 45 นาที พร้อม uncertainty band แต่ยังเป็น candidate เท่านั้น ไม่ใช่ customer-facing Auto ETR”

ชี้บนจอ:
- Step 4 `Cause`
- Step 5 `ETR candidate`
- `shadow P50`

### 3:45-4:30 Shadow Response และ Guardrail

“จุดสำคัญที่สุดคือ production send ยังเป็นศูนย์ ระบบนี้พร้อมเป็น cloud shadow pilot ให้ AIS ยิงจริงได้ แต่ยังไม่เปิด Auto ETR จนกว่าจะผ่าน green gate และ owner approval”

ชี้บนจอ:
- `Production sends = 0`
- `production_send = blocked`
- `AIS outage/restore stays truth`

### 4:30-5:00 Ask

“สิ่งที่ขอจากผู้บริหารคืออนุมัติ cloud shadow pilot ต่อ, ตั้ง owner ของ PEA/AIS API, และอนุมัติการเก็บ real pilot cases เพื่อทำ green subset ก่อนตัดสินใจ production Auto ETR”

ชี้บนจอ:
- Pilot decision frame
- Cloud shadow, not Auto ETR production

## ประโยคสำคัญที่ต้องพูดให้ชัด

- “นี่คือ Cloud Shadow Pilot ไม่ใช่ Auto ETR production live”
- “ข้อมูลบน demo เป็น redacted/synthetic เพื่อรักษาความปลอดภัย”
- “AIS outage/restore ยังเป็น customer-facing truth”
- “PEA API เพิ่ม context, evidence, auditability และ speed”

## ถ้าโดนถามว่าทำไมยังไม่ส่ง ETR จริง

ตอบ:
“เพราะเราตั้ง guardrail ไว้ถูกต้องครับ ต้องมี green rows อย่างน้อย 30 เคส, q50 MAE ไม่เกิน 16 นาที, q10-q90 coverage อยู่ในช่วง 0.75-0.90 และมี owner approval ก่อน จึงจะเปิด customer-facing Auto ETR ได้”
