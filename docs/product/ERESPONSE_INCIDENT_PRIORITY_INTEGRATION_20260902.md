# e-Response × Incident Priority Queue Integration — 2026-09-02

Status: UI/UX INTEGRATION CANDIDATE / SHADOW READ-ONLY / NO e-RESPONSE WRITE

## Purpose

Reframe PEA Intellisense Incident Priority Queue as an additive decision-support view inside the mental model of e-Response / OMS Event Management, rather than presenting it as a separate standalone product.

This change is presentation/workflow integration only. It does not claim a technical write integration with e-Response.

## Source manuals reviewed

The following manuals were read from the owner-provided Google Drive folder:

1. `คู่มือOMS_eRespond_ไฟฟ้าขัดข้อง(ล่าสุด).pdf` — 51 pages
2. `คู่มือOMS_eRespond_ไฟฟ้าขัดข้อง จากรับแจ้งปัญหา...._Meter_SMP.pdf` — 41 pages
3. `คู่มือ ประมาณการเวลาจ่ายไฟ.pdf` — 6 pages
4. `คู่มือOMS_eRespond_แผนดับไฟ_Transformer.pdf` — 48 pages
5. `วิธีค้นหาเหตุการณ์ และตั้งเงื่อนไข.pdf` — 9 pages

The manuals are screenshot-heavy; text and visual workflow cues were used only where they were clear enough to support a product decision.

## e-Response concepts grounded in the manuals

### Event Management surface

The manuals explicitly use:
- `รายการงาน`
- `เหตุการณ์ทั้งหมด`
- `ค้นหา`
- `ตัวกรอง`
- `เมนู`
- `เพิ่มเติม`
- `รีเฟรชข้อมูล`
- `ใช้เงื่อนไขที่กำหนดไว้`
- `สลับแถบเงื่อนไข`
- `เพิ่มเงื่อนไข`
- `ใช้เงื่อนไขชั่วคราว`

The defined-condition view is shown as enabled by default and filters to `รอแก้ไข` in the documented Event Management flow.

### Event workflow / status language

Documented event-management states/actions include:
- `รอแก้ไข` — orange/yellow
- `รับทราบ` — orange/yellow
- `อยู่ระหว่างดำเนินการ` — orange/yellow
- `เสร็จสิ้น` — green
- `ปิดงาน` — grey

Documented event actions include:
- `รับทราบ`
- `อยู่ระหว่างดำเนินการ`
- `เสร็จสิ้น`
- `ปิดงาน`
- `ยกเลิก`
- `ย้ายไป`
- `สร้างเหตุการณ์ต่อเนื่อง`

### Dispatch / work assignment

The documented Dispatch flow uses:
- event detail -> `งาน`
- `มอบหมายงาน`
- `ทีมงานของฉัน`
- `ยืนยันมอบหมายงาน`

MWM then continues with:
- `รับงาน`
- `งานของฉัน`
- `เริ่มเดินทาง`
- `ถึงสถานที่ทำงาน`
- `เริ่มงาน`
- `เสร็จ`
- cause and corrective-action capture

### Device-status context

The Meter/SMP manual documents `ตรวจสถานะอุปกรณ์` through an MDM web service and states:
- `Normal` = meter still has electricity
- `Outage` = meter has no electricity

The manual also documents nearby-device checks and PEANO/Transformer search.

## UI integration decisions

The Incident Priority page now follows the Event Management model:

1. Primary product identity is `e-Response / OMS · Event Management`.
2. The main page title is `เหตุการณ์ทั้งหมด`.
3. AI Priority is an additive module/view, not a replacement workflow.
4. Search, filters, refresh, and `ใช้เงื่อนไขที่กำหนดไว้` are first-class controls.
5. The defined-condition toggle maps to the documented `รอแก้ไข` view.
6. The event table adds an `AI PRIORITY` column while retaining event status, event identity, area/assets, time/waiting, impact/evidence.
7. Detail uses `รายละเอียด`, `งาน`, and `AI PRIORITY` tabs.
8. The Work tab shows the documented e-Response workflow and assignment vocabulary, but all write actions are disabled in the demo.
9. AI reasoning/evidence is isolated in the AI Priority tab so the base event workflow remains recognizable.
10. BKN and PKN queue ranks remain area-scoped. No global cross-area rank is fabricated.

## Status presentation mapping

Backend status -> UI presentation:

- `NEW` -> `รอแก้ไข`
- `ACKNOWLEDGED` -> `รับทราบ`
- `DISPATCHED` -> `มอบหมายงานแล้ว`
- `IN_PROGRESS` -> `อยู่ระหว่างดำเนินการ`
- `RESTORED` -> `จ่ายไฟคืนแล้ว · รอตรวจสอบ`

Important: `RESTORED` is intentionally **not** mapped to e-Response `เสร็จสิ้น` or `ปิดงาน`. The current PEA Intellisense source does not prove those native e-Response lifecycle states.

## Explicit non-integrations / no-fabrication rules

The UI does **not** claim or fabricate the following:

- no real e-Response status write;
- no real team lookup or work assignment;
- no MWM job creation/update;
- no ETR write/control or estimated-restoration field because the current queue feed does not provide an accepted ETR contract and the reviewed ETR manual is insufficient to infer one safely;
- no MDM `Normal/Outage` device status because the current queue feed has no accepted MDM source;
- no raw customer identity/phone/address;
- no planned-outage lifecycle inference from unplanned-outage evidence;
- no automatic `เสร็จสิ้น` / `ปิดงาน` promotion;
- no customer send or crew dispatch.

## Guardrails retained

- `mode=shadow`
- `production_send=blocked`
- browser does not call n8n directly
- public `/api/*` remains blocked by the demo public gate
- priority is decision support only
- missing/stale priority remains `UNRATED`
- missing operational facts remain unknown/unconfirmed
- queue ranking is area-scoped
- no customer-facing outage truth is promoted from AI/topology alone

## Acceptance target

The public demo should feel like an e-Response Event Management extension while remaining technically isolated/read-only:

`e-Response Event Management -> AI Priority view -> Operator reviews -> native e-Response workflow remains authoritative for actions`
