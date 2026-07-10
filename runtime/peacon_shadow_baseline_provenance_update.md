# PEA-CON Shadow Baseline Provenance Update

ระบบสำหรับลูกค้าสื่อสารรายสำคัญบันทึกค่าคาดการณ์ benchmark ก่อนทราบเวลาไฟกลับ เพื่อป้องกันการคำนวณความแม่นยำย้อนหลังหลังเห็นผลจริง โดย OUTAGE ใหม่ใน prospective v2 ที่ผ่านการตรวจ ledger จะได้รับค่า `fixed_naive_60m_v1` ณ เวลารับคำขอ ค่า 60 นาทีเป็น naive research baseline ที่ประกาศล่วงหน้า ไม่ได้ train จากข้อมูล v1 หรือข้อมูลที่มีความไม่แน่นอน และไม่ถือเป็นโมเดล production

Prediction snapshot ถูกเก็บใน private operator ledger เท่านั้น ไม่ถูกใส่ใน callback/outbox และไม่ถูกส่งให้ลูกค้า การประเมิน MAE ในอนาคตจะใช้เฉพาะ snapshot ที่เกิดก่อน RESTORE และ clean AIS event-remaining truth หลังรวม meter intervals ที่เริ่มใกล้กันภายในกรอบ 5 นาทีแบบ conservative เป็นเหตุการณ์เดียว และต้องมีอย่างน้อย 30 เหตุการณ์อิสระ ระบบยังอยู่ใน shadow mode และ `production_send=blocked`

การรายงานระดับ incident ใช้ค่ากลางเพื่อไม่ให้อุปกรณ์จำนวนมากในเหตุเดียวเพิ่มน้ำหนักเกินจริง พร้อมรายงาน worst-meter absolute error เป็น guardrail แยกต่างหาก เพื่อไม่ให้ผลกระทบสูงของลูกค้าบางจุดถูกซ่อนด้วยค่ากลางของกลุ่ม ข้อมูล legacy/non-v2 ถูกนับเป็น audit exclusion ไม่ใช่ model rejection
