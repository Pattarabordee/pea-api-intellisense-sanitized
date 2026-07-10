# PEA-CON Restore Semantic Contract Gate Update

ระบบสำหรับลูกค้าสื่อสารรายสำคัญตรวจพบรหัสแบบมีโครงสร้าง `AC_MAIN_RESTORE` ซึ่งมีแนวโน้มหมายถึงไฟกลับ แต่ระบบยังไม่เปิดใช้รหัสดังกล่าวเป็น restoration truth ทันที การเปิด mapping ต้องผ่าน observation gate และ same-meter chronological pair audit ก่อน ข้อมูลคู่ที่เกิดก่อน activation ถูกเก็บเป็น audit-only และไม่ถูกนำไป train คำนวณ MAE/coverage หรือเพิ่ม green rows แนวทางนี้แยกการค้นพบ semantic signal ออกจากการอนุมัติ model truth อย่างชัดเจน และคง `production_send=blocked` จนกว่าหลักฐาน prospective และ production gate จะครบถ้วน
