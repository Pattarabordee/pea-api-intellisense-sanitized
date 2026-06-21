# ข้อความนัด AIS Test Window

Status: `ready_to_send_to_ais`  
Mode: `shadow`  
Production send: `blocked`

ใช้ข้อความนี้ส่งให้ AIS หลังส่ง `X-API-Key` ผ่านช่องทาง secure/direct แล้วเท่านั้น ห้ามใส่ key ในข้อความนี้

## ข้อความสำหรับส่ง AIS

ทีม PEA เปิด Cloud Shadow API พร้อมให้ทดสอบแล้วครับ

Endpoint:

```http
POST https://pea-api-intellisense-api.onrender.com/api/v1/ais/outage-verifications
```

Headers:

```http
Content-Type: application/json
X-API-Key: <ใช้ cloud pilot key ที่ส่งให้ผ่านช่องทาง secure>
```

ขอให้ทดสอบ 2 ครั้ง:

1. ยิง valid request 1 ครั้ง
2. ยิง `request_id` เดิมซ้ำอีก 1 ครั้ง เพื่อทดสอบ duplicate/idempotency

หลังยิงแล้ว รบกวนแจ้งกลับแค่ 3 ค่า:

- `request_id`
- เวลาที่ยิง
- HTTP status ที่ AIS เห็น เช่น `202`, `400`, `401`

หมายเหตุ: endpoint นี้เป็น `shadow/pilot only` ครับ PEA จะรับ request และเก็บ evidence ฝั่ง cloud แต่ยังไม่ส่ง customer-facing Auto ETR และยังคง `production_send=blocked`

## Expected Result

- Valid request ควรได้ HTTP `202`
- Duplicate `request_id` ต้องไม่ทำ production send ซ้ำ
- ถ้าได้ `401` แปลว่า endpoint ถึงแล้ว แต่ key ไม่ผ่าน
- ถ้าได้ `400` แปลว่า JSON body หรือ timestamp format ยังไม่ถูก
