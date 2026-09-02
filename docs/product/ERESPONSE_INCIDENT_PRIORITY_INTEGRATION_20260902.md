# e-Response × Incident Priority Queue Integration — 2026-09-02

Status: DEMO-PRODUCTION OPERATOR WORKFLOW / REAL DEMO STATE WRITES / LIVE DEMO CHAT PATH INTEGRATION IN PROGRESS

## Purpose

Make Incident Priority feel and behave like an e-Response / OMS Event Management capability rather than a separate PEA Intellisense dashboard.

The presentation surface is production-realistic. Engineering provenance remains documented here so the demo does not need to expose internal implementation labels.

## Source manuals reviewed

Owner-provided Google Drive manuals reviewed for terminology, workflow, interaction, and visual language:

1. `คู่มือOMS_eRespond_ไฟฟ้าขัดข้อง(ล่าสุด).pdf`
2. `คู่มือOMS_eRespond_ไฟฟ้าขัดข้อง จากรับแจ้งปัญหา...._Meter_SMP.pdf`
3. `คู่มือ ประมาณการเวลาจ่ายไฟ.pdf`
4. `คู่มือOMS_eRespond_แผนดับไฟ_Transformer.pdf`
5. `วิธีค้นหาเหตุการณ์ และตั้งเงื่อนไข.pdf`

These are end-user manuals, not API/integration specifications. They support UI/workflow alignment but do not establish an official e-Response write API contract.

## e-Response concepts used

Event Management vocabulary and flow used by this module:

- `เหตุการณ์ทั้งหมด`
- `ค้นหา`
- `ตัวกรอง`
- `รีเฟรชข้อมูล`
- `ใช้เงื่อนไขที่กำหนดไว้`
- `รายละเอียด`
- `งาน`
- `มอบหมายงาน`
- `ทีมงานของฉัน`
- `ยืนยันมอบหมายงาน`
- `รับทราบ`
- `อยู่ระหว่างดำเนินการ`
- `เสร็จสิ้น`
- `ปิดงาน`
- `ยกเลิก`
- `ย้ายไป`
- `สร้างเหตุการณ์ต่อเนื่อง`

Primary lifecycle shown in the operator surface:

`รอแก้ไข -> รับทราบ -> มอบหมายงาน -> อยู่ระหว่างดำเนินการ -> เสร็จสิ้น -> ปิดงาน`

## Current implementation

### Presentation / information architecture

- Product identity is `e-Response / OMS · Event Management`.
- Main route remains `/incident-priority` but presents as an Event Management module.
- AI Priority is a column and detail tab inside the event workflow.
- Search, filters, defined-condition view, event list, detail, work, and AI reasoning are integrated into one screen.
- Visual language follows the reviewed e-Response manuals: enterprise blue header, light grey/white work surfaces, compact table layout, orange waiting/work states, green completion states.
- Presentation UI intentionally does not expose implementation labels such as `SHADOW`, `READ ONLY`, `production_send`, or `dry_run`.

### Real operator actions in the demo module

A durable operator-state endpoint exists at:

`/api/eresponse/operator-state`

Supported real demo actions:

- acknowledge event;
- assign a team;
- start work;
- complete work;
- close work;
- cancel event;
- move event;
- create continuation-event action record.

Writes are persisted server-side using schema `eresponse-operator-state.v1`. Reloading the browser preserves state and action timeline.

The operator-state route validates incident IDs, action names, team selection, and move destinations. Invalid team values fail closed.

### Demo team catalog

Current demo team choices are intentionally realistic operational values:

- ทีมแก้ไฟ 1 กฟส.พังโคน
- ทีมแก้ไฟ 2 กฟส.พังโคน
- ทีมฮอทไลน์ กฟส.พังโคน
- ทีมสนับสนุน กฟส.พังโคน
- ทีมแก้ไฟ กฟจ.บึงกาฬ

These are the demo application's operational team catalog; they are not claimed to have been retrieved from an official e-Response team API.

## Live demo messaging path

The project already has a separately controlled STEP 61 demo-production LINE transport path on PEA Server. It provides real inbound/outbound LINE transport for the designated demo account with destination allowlist, idempotency, durable queue/trace evidence, CA resolution and topology lookup.

Current adapter identity:

- service: `step61-demo-transport-adapter`
- loopback port: `18142`
- provider: LINE
- route: `line:pangkhon:reply-token-bound`
- webhook path: `ai_bot_pangkhon_step61`
- mode: `DEMO-PRODUCTION`

This path must be reused rather than creating a second competing LINE transport implementation.

At the latest pre-deployment check the LINE destination allowlist was not yet locked because the first controlled live inbound demo message had not yet established the reply-token-bound chat identity. Real outbound must use the existing route once that allowlist is established.

## Official e-Response backend boundary

No official e-Response API endpoint, API credential, or write integration specification has yet been found in the reviewed manuals or approved local/server project sources.

Therefore:

- the operator workflow is a real persistent workflow in the demo module;
- the LINE demo messaging path is a real transport path where STEP 61 proves it;
- the UI may use realistic mock/synthetic operational values where source data is missing;
- this document does not claim that these state writes have been accepted by the organization's canonical e-Response database;
- if an official e-Response endpoint/credential is later discovered and verified, this same operator-state interface should become the adapter boundary for that integration.

## Ranking semantics

BKN and PKN ranks remain area-scoped. The module must not create a false global rank from non-comparable area-specific priority scores.

## Validation

Required validation for this phase:

- Next.js build passes;
- existing feed/priority/compose/publisher/source-candidate contracts remain green;
- operator-state GET/POST persistence passes;
- valid operator actions persist through reload;
- invalid team assignment is rejected;
- public demo exposes only the web functionality required by the presentation workflow;
- STEP 61 live LINE path remains the single transport authority for real demo messaging;
- official e-Response backend write is not claimed without a verified API contract.
