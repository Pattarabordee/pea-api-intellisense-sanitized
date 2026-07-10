# PEA-CON Restore Semantic Contract Gate Update

ระบบสำหรับลูกค้าสื่อสารรายสำคัญใช้ observation gate เพื่อตรวจความหมายของรหัสแบบมีโครงสร้างก่อนอนุญาตให้เป็น restoration truth หลักฐานรวมที่ไม่เปิดเผยตัวระบุพบข้อมูล 109 รายการและคู่เหตุการณ์ตามมิเตอร์และลำดับเวลา 35 คู่ โดยไม่พบคู่ที่มีเวลาผิด ข้อมูลระบุตัวตนหรือเวลาขาดหาย หรือความหมายขัดแย้ง จึงเปิด exact mapping `AC_MAIN_RESTORE -> RESTORE` สำหรับข้อมูล prospective v2 เท่านั้น

ข้อมูลก่อน activation ทั้งหมดคงเป็น audit-only และไม่ถูก replay, train, คำนวณ MAE/coverage หรือเพิ่ม green incidents ระบบกำหนด `semantic_mapping_version=alarm_mapping_v2` และอนุญาตให้ RESTORE ปิดเฉพาะ open interval ที่มี mapping version เดียวกัน แนวทางนี้เป็น strict provenance และ model-risk control ไม่ใช่การอ้างว่าระบบพร้อม production โดย `production_send=blocked` ยังคงเดิมจนกว่าจะมีอย่างน้อย 30 เหตุการณ์อิสระและผ่าน accuracy/stability gate
