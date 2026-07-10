# PEA-CON Evidence Update: Meter-State Truth Governance

ระบบสำหรับลูกค้าสื่อสารรายสำคัญถูกปรับให้แยกการรับข้อมูลจริงออกจากการทำนายอย่างชัดเจน Cloud ทำหน้าที่รับเหตุและสร้าง meter-state interval โดยใช้ข้อมูล OUTAGE/RESTORE ของ AIS เป็น truth หลัก ส่วน Protection, topology, ReportPO, SFSD, WebEx, LINE และ telecom/GIS เป็นบริบทประกอบเท่านั้น ข้อมูลที่ไม่มีลำดับเหตุการณ์และ provenance ครบจะไม่ถูกนำไปฝึกหรือวัดโมเดล

เป้าหมายการประเมินถูกกำหนดเป็นเวลาที่เหลือจากเวลาสร้างคำทำนายจนถึงไฟกลับ และแบ่งข้อมูลตามเหตุไฟดับอิสระเพื่อลดความเสี่ยงจากหลายมิเตอร์ในเหตุเดียวกัน หน้าเว็บสาธารณะใช้ข้อมูลจำลองเท่านั้น ข้อมูลจริงเข้าถึงผ่าน authenticated API หรือรายงาน private แบบ one-shot ระบบยังอยู่ใน shadow และ `production_send=blocked`; ผลปัจจุบันยังไม่ใช่หลักฐานว่า production-ready
