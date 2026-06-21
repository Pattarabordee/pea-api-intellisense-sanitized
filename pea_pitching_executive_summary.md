# PEA API Intellisense - Executive Pitching Summary

> เอกสารนี้สรุปจาก `README_AIS_ETR_MVP.md`, `runtime/PILOT_COMPLETE_README.md`, `runtime/chatgpt_production_review/runtime/go_no_go_summary.md`, และ `runtime/chatgpt_production_review/runtime/pea_pitch_delivery_manifest.md`  
> สถานะปัจจุบัน: controlled shadow pilot เท่านั้น  
> Guardrail สำคัญ: `mode = shadow`, `production_send = blocked`, และยังไม่เปิด customer-facing Auto ETR

## 1. The Pain (ปัญหา)

ก่อนมี PEA API Intellisense การประสานงานกรณี AIS site มีไฟฟ้าขัดข้องยังพึ่งพา manual coordination เป็นหลัก เช่น โทรถาม, แชทถาม, ส่งข้อมูลซ้ำ และรอคนช่วยไล่ตรวจจากหลายแหล่งข้อมูล

Pain point หลักคือ AIS เห็นอาการหน้างาน เช่น AC main fail หรือ site power alarm แต่ไม่เห็น distribution context ของ PEA ว่า meter/site นั้นอยู่หลังอุปกรณ์ป้องกันตัวใด และมี evidence ของเหตุไฟฟ้าในระบบ PEA หรือไม่ ในขณะเดียวกัน PEA มีข้อมูล grid context อยู่แล้ว แต่ยังไม่ได้ถูก package เป็น service ที่ AIS เรียกใช้ได้เร็วและตรวจสอบย้อนหลังได้

ผลกระทบเชิง operation:

- Incident/outage handling ช้าจากการรอคนประสานงาน
- ข้อมูลซ้ำหลายรอบ เช่น meter, เวลา, พื้นที่, device, feeder
- ไม่มี `request_id` กลางสำหรับ track งานและ audit trail
- การตอบขึ้นกับคนรับเรื่อง ทำให้ consistency และ speed ไม่แน่นอน
- ทีมยังแยกกันทำงานเป็น silo ทั้งที่ข้อมูลสามารถเชื่อมกันได้ผ่าน API

ระดับความรุนแรงของ delay ยังไม่มีตัวเลข MTTR ที่วัดจริงในเอกสาร แต่จาก business case ระบุว่า opportunity อยู่ในระดับที่ควรทำ pilot ต่อ:

- Conservative planning benefit: `117,500 THB/year`
- Base case planning benefit: `780,000 THB/year`
- Upside planning benefit: `2,550,000 THB/year`
- Blindspot opportunity: `~48M THB/year` เป็น strategic estimate/upside
- API monetization potential: `6-8M THB/year` เป็น subscription-model upside

ตัวเลขทั้งหมดเป็น planning assumptions / strategic estimate ยังไม่ใช่ realized savings และต้องให้ finance owner validate ก่อนใช้เป็นตัวเลขบัญชีจริง

## 2. The Pilot Result (ผลลัพธ์จากช่วง Pilot)

ผลลัพธ์หลักคือระบบผ่านสถานะ `PILOT_COMPLETE` สำหรับ controlled AIS API shadow pilot แล้ว หมายความว่า AIS สามารถยิง request เข้ามา, PEA รับเรื่อง, เก็บ evidence, ตรวจสอบย้อนหลัง และ export audit ได้ โดยยังไม่เปิด production send

Key success metrics จากเอกสาร:

| Metric | Result | Meaning |
| --- | ---: | --- |
| Controlled AIS API pilot | `GO` | AIS ยิง pilot API request เข้า shadow endpoint ได้ |
| Pilot/API readiness | `100%` | readiness สำหรับ controlled shadow pilot ตาม delivery manifest |
| Endpoint health | `PASS` | endpoint health check ผ่าน |
| Valid authenticated request | `202 Accepted` | request ที่ถูกต้องถูกระบบรับและบันทึก |
| Unauthorized request | `401 Unauthorized` | auth gate ทำงาน |
| Total inbound requests captured | `33` | มี request ถูกเก็บใน evidence store |
| Real AIS requests captured | `3` | มี real AIS pilot request เข้าระบบแล้ว |
| Duplicate `request_id` | safe handling | ไม่ reprocess production send |
| Pilot Complete final QA | `PASS` | final QA script ผ่าน |
| Production send | `blocked` | guardrail ยังทำงาน |
| Production auto ETR | `BLOCKED_GREEN_GATE` | ยังไม่อนุมัติ auto ETR |

เรื่อง MTTR และ accuracy ต้องพูดอย่างระวัง:

- เอกสารยังไม่ได้ claim ว่าลด MTTR ได้กี่นาทีแบบ measured production result
- เอกสารยังไม่ได้ claim model accuracy ว่าพร้อม production
- Auto ETR ยัง `NO_GO` เพราะต้องมี green rows `>=30`, model accuracy/coverage thresholds และ owner approval

ดังนั้นผลลัพธ์ที่จับต้องได้ในช่วง pilot คือ operational readiness และ evidence readiness ไม่ใช่ production model victory:

- จาก manual phone/chat coordination เปลี่ยนเป็น API request ที่มี `request_id`
- จากข้อมูลกระจัดกระจาย เปลี่ยนเป็น SQLite evidence store ที่ query ได้
- จากการตอบแบบไม่มี audit trail เปลี่ยนเป็น request/callback evidence พร้อม redacted export
- จาก demo เฉย ๆ เปลี่ยนเป็น pilot package ที่มี API contract, OpenAPI, Postman, runbook, QA, pitch deck และ web demo

## 3. The Architecture (ภาพรวมสถาปัตยกรรมระดับ High-level)

PEA API Intellisense ทำหน้าที่เป็น semantic layer ระหว่าง AIS incident signal กับ PEA grid context

ภาพรวมการทำงาน:

```text
AIS Site Alarm / AC Main Fail
  -> AIS Inbound API
  -> Request Validation + request_id
  -> Meter / PEANO Registry Lookup
  -> Protection Topology Match
  -> Webex / Outage Evidence Check
  -> ETR Candidate Lane
  -> Shadow Response / Status Lookup / Audit Export
```

องค์ประกอบหลัก:

### AIS Inbound API

AIS ส่ง JSON เข้ามาที่ API เช่น `POST /api/v1/ais/outage-verifications` พร้อม `request_id`, meter/PEANO, timestamp และพื้นที่ ระบบตอบ `202 Accepted` เมื่อ request valid และเก็บ evidence ไว้ตรวจสอบย้อนหลัง

### Topology Registry

ระบบโหลด AIS traced registry จาก `upstream_result.xlsx` แล้วเก็บเป็น runtime registry เพื่อ map meter/PEANO ไปยัง feeder, transformer, switch, recloser และ circuit breaker การ match ใช้ protection hierarchy จาก strongest evidence ไป weakest evidence:

```text
CB -> Recloser -> Switch -> Transformer -> Feeder fallback
```

Feeder-only match ถูกจัดเป็น audit/review lane ไม่ใช่ confident production answer

### Webex Integration และ Evidence Store

ระบบ poll/parse Webex outage messages เพื่อดึง device, feeder, district และ event time แล้วบันทึกเป็น runtime evidence ใน SQLite จากนั้นนำ evidence นี้มาเทียบกับ topology ของ meter ที่ AIS ส่งเข้ามา

### ETR Candidate Lane

ระบบมี quantile baseline model ที่ให้ q10/q25/q50/q75/q90 และ risk level เพื่อใช้เป็น shadow ETR candidate แต่ยังไม่ส่งเป็น customer-facing ETR อัตโนมัติ

### Audit, Security, และ Guardrail

ทุก request/callback ถูกเก็บเป็น evidence แบบ redacted มี audit export, DB snapshot, security/privacy scan และ final QA gate จุดสำคัญคือระบบถูกออกแบบให้ ambitious ทางธุรกิจ แต่ conservative ทาง risk:

- `production_send = blocked`
- Auto ETR ยังไม่ live
- AIS outage/restore ยังเป็น customer-facing truth
- PEA/SFSD/ReportPO ใช้เป็น context/quarantine จนกว่า owner จะ approve

## 4. The Ask (สิ่งที่ต้องการจากการ Pitch)

สิ่งที่ต้องขอจากผู้บริหารไม่ใช่การเปิด Auto ETR ทันที แต่คือการอนุมัติให้ยกระดับจาก controlled shadow pilot ไปสู่ production-grade pilot environment ที่ PEA ควบคุมได้จริง

### 1. Approve controlled production-path pilot

อนุมัติให้ AIS inbound API เป็น pilot channel ต่อ โดยยังคง `production_send = blocked` และให้ตอบได้เฉพาะ status-only หรือ human-approved response จนกว่า evidence gate จะผ่าน

### 2. Approve permanent HTTPS/API gateway

ย้ายจาก local tunnel/shared pilot key/local SQLite ไปสู่ PEA-approved infrastructure:

- Permanent HTTPS endpoint หรือ API Gateway
- Hardened authentication
- Secret rotation
- Monitoring และ restart policy
- Queue/retry/dead-letter policy
- Durable DB, backup และ restore test

### 3. Assign named owners

ต้องมี owner ชัดเจนอย่างน้อย 3 กลุ่ม:

- Topology/GIS owner: รับรอง mapping ระหว่าง meter/site กับ protection device
- AIS truth feed owner: ส่ง outage/restore truth เพื่อ validate model และ green lane
- Production infrastructure owner: ดูแล gateway, auth, monitoring, backup และ incident response

### 4. Approve validation data and governance gate

ขออนุมัติใช้ priority AIS site data สำหรับ pilot validation เพื่อพิสูจน์ว่า system ช่วยลด manual coordination ได้จริง และใช้เป็นฐานคำนวณ ROI ด้วยข้อมูลจริงของ PEA/AIS

Auto ETR จะขอเปิดเฉพาะเมื่อผ่าน gate ต่อไปนี้:

- green rows `>=30`
- q50 MAE `<=16 min`
- q10-q90 coverage `0.75-0.90`
- owner approval
- production infrastructure controls ผ่าน

### 5. Budget / Resource Request

เอกสารต้นทางยังไม่ระบุ budget ตัวเลขแน่นอน ดังนั้นข้อเสนอสำหรับ pitch คือขอ budget envelope และ resource approval สำหรับ 3-month controlled production-path pilot ครอบคลุม:

- API Gateway / hosting
- security hardening และ secret management
- monitoring / backup / restore
- integration support ระหว่าง PEA IT, PEA Ops, GIS/topology owner และ AIS Dev/Ops
- data validation และ finance validation สำหรับ ROI

Executive decision ที่ต้องการ:

> Approve the next controlled pilot step: move AIS API from local pilot setup to PEA-approved production-grade infrastructure, while keeping customer-facing Auto ETR blocked until evidence and owner gates pass.

