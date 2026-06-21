# Cloud Pilot Key Rotation Drill

Status: `pending_first_ais_success`  
Mode: `shadow`  
Production send: `blocked`

ยังไม่ควร rotate key จนกว่า AIS ยิง cloud endpoint สำเร็จอย่างน้อย 1 ครั้งด้วย key ปัจจุบัน

## When To Run

Run this drill after:

- AIS valid request ได้ HTTP `202`
- PEA real-hit check เห็น `REAL_AIS_HIT_DETECTED`
- Web console เห็น request จริง
- `production_send=blocked` ยังถูกต้อง

## Rotation Steps

1. Generate new pilot key locally or in approved secret workflow.
2. Update `AIS_INBOUND_API_KEY` in Render API service.
3. Update `AIS_INBOUND_API_KEY` in Render Web service if web operator routes require it.
4. Redeploy affected Render services.
5. Run cloud smoke check with the new key.
6. Ask AIS to test with the new key in a short test window.
7. Confirm old key no longer works, but do not paste either key into chat.
8. Record only timestamp, status, and redacted request id in the progress report.

## Expected Checks

- New key valid request returns `202`
- Old key returns `401`
- Duplicate `request_id` remains duplicate-safe
- `production_send=blocked` remains present
- No key appears in GitHub, docs, logs, screenshots, or slide decks

## Rollback

If AIS cannot authenticate after rotation:

1. Keep `production_send=blocked`.
2. Check Render environment variable spelling.
3. Redeploy API and web services.
4. Confirm AIS is using the newest key from secure channel.
5. If needed, temporarily restore the previous key only through Render secret settings, then repeat smoke check.
