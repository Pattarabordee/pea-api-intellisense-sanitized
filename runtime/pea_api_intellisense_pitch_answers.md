# PEA API Intellisense - Executive Q&A

> ใช้สำหรับตอบกรรมการ/ผู้บริหารแบบสั้น กระชับ และไม่ overclaim  
> สถานะระบบ: `shadow mode` และ `production_send = blocked`  
> ตัวเลขด้านการเงินด้านล่างเป็น `planning scenario / strategic estimate` ยังไม่ใช่ realized saving

## 1. ปัญหา (Problem)

โปรเจคนี้แก้ปัญหา "AIS เห็นว่า site ไฟดับ แต่ไม่เห็นบริบทของระบบจำหน่าย PEA"

ปัจจุบันเมื่อ AIS เจอ alarm เช่นไฟ AC main fail หรือ site ใช้ไฟไม่ได้ ทีม AIS ต้องโทรหรือแชทมาถาม PEA เองว่าเกี่ยวกับไฟฟ้า PEA หรือไม่ ต้องส่งเลข meter, เวลา, จังหวัด, อำเภอ, ตำบล และรอคนช่วยตรวจ

ถ้าไม่ทำโปรเจคนี้ต่อ จะยังมีปัญหาเดิม:

- ประสานงานช้า
- ส่งข้อมูลซ้ำหลายรอบ
- dispatch หรือ follow-up เกินจำเป็น
- ตรวจย้อนหลังยาก เพราะไม่มี `request_id` และ audit trail ที่เป็นระบบ
- PEA เสียโอกาสเปลี่ยนข้อมูล grid ที่มีอยู่แล้วให้เป็นบริการข้อมูลมูลค่าสูงสำหรับ key accounts

## 2. โซลูชัน (Solution)

ระบบนี้เปลี่ยนจาก "โทรถามคน" เป็น "ยิง API มาถาม PEA"

ภาพง่าย ๆ คือ:

1. AIS ส่งข้อมูลเหตุการณ์เข้ามา
2. PEA รับเรื่องและออก `request_id`
3. PEA trace ว่า meter/site นั้นอยู่หลังอุปกรณ์ป้องกันตัวไหน
4. PEA ดู evidence ว่าอุปกรณ์นั้นมีเหตุการณ์ทำงานจริงไหม
5. ระบบส่งสถานะหรือ ETR ที่ผ่าน gate กลับไปให้ AIS

พูดแบบภาษามนุษย์:

> AIS ไม่ต้องไล่โทรถามทีละเคส ส่วน PEA ไม่ต้องเริ่มตรวจจากศูนย์ทุกครั้ง ระบบช่วยรับเรื่อง เก็บหลักฐาน และตอบกลับแบบมีเลขอ้างอิง

ตอนนี้ยังเป็น `shadow mode` คือระบบรับและตรวจได้ แต่ยังไม่ส่ง production ETR อัตโนมัติ

## 3. ประโยชน์ / ค่าใช้จ่าย (Impact / ROI)

ตัวเลขชุดนี้ใช้สำหรับ framing ทางธุรกิจ ต้องระบุว่าเป็น estimate จนกว่า finance owner จะ validate

### Planning scenario

- Conservative: ประมาณ `117,500 บาท/ปี`
- Base case: ประมาณ `780,000 บาท/ปี`
- Upside: ประมาณ `2,550,000 บาท/ปี`

### Strategic estimate

- มี dispatch signals ประมาณ `59,997 ครั้ง/ปี`
- หากลดงาน manual ได้ 2-10 นาทีต่อเคส จะเท่ากับลดเวลาประมาณ `2,000-10,000 ชั่วโมง/ปี`
- มี downtime-risk lens ประมาณ `17.8M บาท/ปี`
- มี protected opportunity ประมาณ `~48M บาท/ปี`

### Revenue upside

- หากต่อยอดเป็นบริการ API สำหรับ key accounts อาจสร้างรายได้แบบ subscription ได้ประมาณ `6-8M บาท/ปี`
- ยังมี upside เพิ่มจากโมเดล pay-per-API call

คำที่ควรใช้บนเวที:

> ตัวเลขนี้ยังไม่ใช่เงินที่ประหยัดได้จริงแล้ว แต่เป็นขนาดของโอกาสที่ควรทำ pilot เพื่อพิสูจน์

## 4. ผู้ใช้งาน (Target Audience)

ผู้ใช้งานหลักมี 2 กลุ่ม

### ฝั่ง AIS

- Network Operation
- Field Operation
- Dev/API Integration team
- ทีมที่ต้องตัดสินใจว่า site มีปัญหาจากไฟฟ้า PEA หรือจากอุปกรณ์ฝั่ง AIS

### ฝั่ง PEA

- Operation / Control team
- IT / API owner
- GIS / topology owner
- ทีมบริหาร key accounts หรือ strategic customers

AIS ได้คำตอบเร็วขึ้น ส่วน PEA ได้ระบบรับ request, เก็บ evidence, คุม risk และต่อยอดเป็น data product ได้

## 5. สถานะปัจจุบัน (Current Status)

สถานะปัจจุบันคือ **Pilot ready / shadow mode**

สิ่งที่ทำได้แล้ว:

- API endpoint รับ request ได้
- Auth smoke ผ่าน: request มี key ตอบ `202 Accepted`
- Request ไม่มี key ตอบ `401 Unauthorized`
- มี real AIS request เข้ามาแล้ว
- ระบบเก็บ request history และ audit evidence ได้
- Duplicate `request_id` ไม่ควร reprocess
- มี OpenAPI, Postman, handoff note, runbook, deck และ demo support

สถานะจาก hit check ล่าสุด:

- `total_requests = 34`
- `non_smoke_requests = 4`
- latest real/non-smoke `request_id = AIS-20260621-0001`
- latest status = `RECEIVED`
- callback status = `CAPTURED_NO_CALLBACK_URL`

ข้อจำกัดที่ต้องพูดให้ชัด:

- ยังไม่ใช่ production live
- ยังพึ่ง local tunnel / pilot endpoint
- `production_send = blocked`
- ยังไม่เปิด automatic production ETR
- Auto ETR ต้องรอ green-lane evidence, model metric และ owner approval

## 6. คู่แข่ง / ทางเลือกเดิม (Alternatives)

ทางเลือกเดิมคือ manual coordination

AIS ต้องโทรหรือแชทมาถาม PEA แล้วคนต้องช่วยไล่ดู:

- meter หรือ site อยู่ตรงไหน
- อยู่หลังอุปกรณ์ป้องกันตัวใด
- ช่วงเวลานั้นมีเหตุไฟฟ้าหรือไม่
- ควรตอบ AIS อย่างไร

ข้อเสียของวิธีเดิม:

- ช้า
- ซ้ำ
- audit ยาก
- คุณภาพคำตอบขึ้นกับคนที่รับเรื่อง
- ไม่มี `request_id`
- ไม่มี idempotency หรือ duplicate-safe behavior

โปรเจคนี้ดีกว่าเพราะ:

- AIS ส่งข้อมูลเข้ามาทาง API ได้ทันที
- PEA ได้ request ที่มีรูปแบบเดียวกัน
- มี `request_id` ใช้ตามงานได้
- มี audit trail
- มี evidence gate ก่อนตอบ
- คุม production risk ได้ เพราะยัง `production_send = blocked`

## 7. สิ่งที่ต้องการจากผู้บริหาร (The Ask)

ขอผู้บริหารอนุมัติ 3 เรื่อง

### 1. Joint task force

ตั้งทีมร่วม PEA Ops, PEA IT, GIS/topology owner และ AIS Dev/Ops

เป้าหมาย:

- ล็อก scope pilot
- กำหนด owner ชัด
- ตัดสินใจเรื่อง field mapping และ response policy

### 2. Priority-site data sharing

อนุมัติให้ใช้ข้อมูล priority AIS sites สำหรับ pilot 3 เดือน

เป้าหมาย:

- map meter/site กับ topology
- validate ว่าระบบ trace ได้ถูกต้อง
- วัด impact จริงจากเคสที่เกิดขึ้น

### 3. PEA-approved API gateway owner

แต่งตั้ง owner สำหรับ endpoint production-grade

เป้าหมาย:

- ย้ายจาก local tunnel ไป cloud/API gateway ที่ PEA อนุมัติ
- ทำ monitoring, backup, secret rotation, incident playbook
- เตรียม production readiness gate

## One-line Closing

PEA API Intellisense ไม่ใช่แค่ demo API แต่เป็นก้าวแรกของการเปลี่ยน grid context ของ PEA ให้เป็น data product ที่ปลอดภัย ตรวจสอบได้ และต่อยอดเชิงธุรกิจได้ โดยยังคุมความเสี่ยงด้วย `shadow mode` และ `production_send = blocked`
