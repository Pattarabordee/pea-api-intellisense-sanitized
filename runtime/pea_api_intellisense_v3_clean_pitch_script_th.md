# PEA API Intellisense V3 Clean Pitch - Speaker Script (TH)

Deck: `runtime/weekend_delivery_freeze/presentation/pea_api_intellisense_v3_clean_pitch.pptx`

Guardrail: ทุกครั้งที่พูดเรื่องระบบ ต้องย้ำว่า current state คือ Cloud Shadow Pilot, `mode = shadow`, `production_send = blocked`, และยังไม่ใช่ customer-facing Auto ETR.

## 1. Slide 1 - Cover / Hook

วันนี้ผมนำเสนอ PEA API Intellisense ครับ แนวคิดหลักคือเปลี่ยนข้อมูลระบบจำหน่ายที่ PEA มีอยู่แล้ว ให้กลายเป็นบริการเชิงรุกผ่าน API สำหรับลูกค้ารายสำคัญอย่าง AIS เริ่มจากโจทย์ไฟดับของสถานีฐาน แล้วต่อยอดเป็น capability ด้าน Data Monetization ของ PEA

## 2. Slide 2 - Customer Pain Point

ปัญหาจริงคือข้อมูลอยู่คนละฝั่งครับ AIS เห็นว่า site มีปัญหา แต่ไม่รู้ว่าไฟดับจากระบบจำหน่าย PEA หรือไม่ และจะกลับมาเมื่อไหร่ วิธีเดิมคือโทรถาม แชทถาม แล้วรอคนเปิดระบบไล่ดู ทำให้ตัดสินใจเรื่องทีมช่างหรือเครื่องปั่นไฟได้ช้า และบางครั้งเกิดต้นทุนที่ไม่จำเป็น

## 3. Slide 3 - Size of Pain / Opportunity

ถ้ามองในมุมผู้บริหาร blindspot นี้มีขนาดใหญ่พอครับ เอกสาร strategy ประเมิน dispatch signals ประมาณ 59,997 ครั้งต่อปี มี downtime-risk lens ประมาณ 17.8 ล้านบาทต่อปี และ opportunity รวมประมาณ 48 ล้านบาทต่อปี ตัวเลขนี้ยังเป็น strategic estimate ไม่ใช่ realized saving แต่บอกชัดว่าปัญหานี้ใหญ่พอที่จะทำเป็น capability ระดับองค์กร

## 4. Slide 4 - Why This Is PEA's Opportunity

จุดแข็งของงานนี้คือเหตุผลที่ต้องเป็น PEA ครับ AIS มีข้อมูล site ของตัวเอง แต่ไม่เห็นแผนผังการจ่ายไฟและบริบทเหตุขัดข้องของ PEA ส่วน PEA มี grid topology มีหลักฐานจากระบบปฏิบัติการ และมี governance ที่ควบคุมการใช้ข้อมูลได้ถูกต้อง ดังนั้นมูลค่าจริงไม่ใช่ API อย่างเดียว แต่มูลค่าคือ trusted grid context ที่อยู่หลัง API

## 5. Slide 5 - Solution in Human Language

พูดแบบภาษามนุษย์คือ AIS ถามว่า site นี้เกิดอะไรขึ้น PEA trace กลับว่าอยู่หลังอุปกรณ์ป้องกันตัวไหน จากนั้นเช็คหลักฐานว่าอุปกรณ์หรือเหตุการณ์นั้นเกิดขึ้นจริงในช่วงเวลาเดียวกันหรือไม่ แล้วจึงตอบกลับแบบปลอดภัย เช่น รับเรื่องแล้ว สถานะเบื้องต้น หรือ ETR candidate ที่ยังผ่าน human review ก่อน production

## 6. Slide 6 - Current MVP / Cloud Shadow Pilot

สถานะปัจจุบันเราไม่ได้อยู่แค่ idea แล้วครับ ตอนนี้มี Cloud Shadow API บน Render มี PostgreSQL เป็น evidence store มี Web Console สำหรับดู request และสถานะ แต่ guardrail สำคัญยังเหมือนเดิมคือ production_send ยัง blocked ระบบรับและเก็บหลักฐานได้ แต่ยังไม่ส่ง Auto ETR ไปใช้งานจริงกับลูกค้า

## 7. Slide 7 - Demo Flow

หน้า demo เราจะให้กรรมการเห็น 5 ขั้นครับ หนึ่ง AIS ยิง API มา สอง PEA รับ request ด้วย 202 Accepted สาม PEA trace จาก meter หรือ site ไปยังบริบทระบบจำหน่าย สี่ evidence gate ประเมินความมั่นใจ และห้า ระบบบันทึก shadow response ไว้ให้ operator ตรวจ ไม่ใช่ส่ง production อัตโนมัติ

## 8. Slide 8 - Target Production Architecture

ใน production target เราจะแยกเป็น 4 lane ครับ Trigger lane อาจมาจาก AIS request และอนาคตจาก AMR Last Gasp ที่ได้รับอนุมัติ Context lane ใช้ topology และ protection evidence Reasoning lane ใช้ rule หรือ model เพื่อออก ETR candidate และ Delivery lane ส่งผ่าน API/callback พร้อม audit trail จุดที่ต้องพูดตรง ๆ คือ Last Gasp, SCADA และข้อความปฏิบัติการต้องผ่าน owner approval ก่อน ไม่ใช่เปิดใช้โดยพลการ

## 9. Slide 9 - Business Model / ROI

ในมุมธุรกิจ งานนี้คือ Data Monetization ครับ รูปแบบแรกคือ subscription สำหรับข้อมูลพรีเมียม ประมาณ 1.5-2 ล้านบาทต่อปีต่อภูมิภาค หรือ 6-8 ล้านบาทต่อปีถ้าขยายทั่วประเทศ รูปแบบที่สองคือ pay-per-API-call ตามการใช้งานจริง จุดเด่นคือเป็น Zero-CAPEX path เพราะใช้ข้อมูล บุคลากร และระบบ IT ที่ PEA มีอยู่แล้วเป็นทุนเดิม แต่รายได้ต้องผ่าน finance validation ก่อนใช้เป็นตัวเลขทางบัญชี

## 10. Slide 10 - Risk Control / Why Not Auto-Send Yet

จุดที่ทำให้โครงการนี้ปลอดภัยคือเราไม่รีบเปิด Auto ETR ครับ ตอนนี้เป็น shadow mode มี human review และต้องผ่าน green evidence gate ก่อน โดยต้องมีเคสที่ validate แล้วอย่างน้อย 30 เคส ค่า error และ coverage อยู่ในเกณฑ์ และต้องมี owner approval ข้อมูลที่อ่อนไหว เช่น meter เต็ม ข้อความปฏิบัติการ หรือข้อมูลลูกค้า จะไม่ถูกเปิดเผยใน artifact สาธารณะ

## 11. Slide 11 - 3-Month Pilot Plan

แผนที่ควรขออนุมัติคือ pilot 3 เดือนครับ เดือนแรกทำ data mapping สำหรับ AIS hub sites ในพื้นที่นำร่อง เดือนที่สองทำ API/webhook integration และ security contract เดือนที่สามทำ shadow run วัดผล ROI และจัดทำ go/no-go packet สำหรับผู้บริหาร ตรงนี้สอดคล้องกับ Master Document ที่เสนอ pilot 1 จังหวัด และเริ่มจาก scope ที่ควบคุมได้

## 12. Slide 12 - The Ask / Closing

สิ่งที่ขอวันนี้มี 3 เรื่องครับ หนึ่ง อนุมัติหลักการทำ pilot ร่วมกับ AIS สอง อนุมัติการเข้าถึงข้อมูลเฉพาะ scope ที่ผูกกับ AIS และผ่าน owner approval เช่น AMR/topology/evidence สาม ตั้ง Joint Working Group ระหว่าง PEA Ops, PEA IT/API owner และ AIS Dev/Ops owner ขอย้ำว่าการตัดสินใจวันนี้คืออนุมัติ safe pilot bridge ไม่ใช่อนุมัติ Auto ETR production go-live
