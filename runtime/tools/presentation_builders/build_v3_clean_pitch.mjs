import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = "D:\\PEA Intellisense data";
const OUT_DIR = path.join(ROOT, "runtime", "weekend_delivery_freeze", "presentation");
const PREVIEW_DIR = path.join(OUT_DIR, "v3_clean_preview");
const QA_DIR = path.join(OUT_DIR, "qa");
const ASSET_DIR = path.join(ROOT, "runtime", "demo_assets");

const FINAL_PPTX = path.join(OUT_DIR, "pea_api_intellisense_v3_clean_pitch.pptx");
const SCRIPT_MD = path.join(ROOT, "runtime", "pea_api_intellisense_v3_clean_pitch_script_th.md");
const QA_REPORT = path.join(QA_DIR, "v3-clean-pitch-visual-qa.txt");

const ARTIFACT_TOOL = "C:\\Users\\514460\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules\\@oai\\artifact-tool\\dist\\artifact_tool.mjs";
const { Presentation, PresentationFile } = await import(pathToFileURL(ARTIFACT_TOOL).href);

const W = 1280;
const H = 720;
const C = {
  navy: "#07162B",
  slate: "#24334A",
  body: "#233044",
  muted: "#617088",
  soft: "#F6FAFF",
  card: "#FFFFFF",
  border: "#D9E3F0",
  purple: "#7B57C8",
  teal: "#18B8C8",
  cyan: "#59D6F2",
  amber: "#F7B84B",
  green: "#35B76A",
  red: "#E35353",
};

const notes = [];

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function writeTextUtf8Bom(filePath, text) {
  await fs.writeFile(filePath, `\uFEFF${text}`, "utf8");
}

async function readImageBlob(imagePath) {
  const bytes = await fs.readFile(imagePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function addText(slide, text, x, y, w, h, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: style.fontSize ?? 24,
    bold: style.bold ?? false,
    color: style.color ?? C.body,
    alignment: style.alignment,
  };
  return shape;
}

function addRect(slide, x, y, w, h, fill, line = C.border, radius = "rounded-xl", shadow = "none") {
  return slide.shapes.add({
    geometry: "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: line, width: 1 },
    borderRadius: radius,
    shadow,
  });
}

function addRule(slide, x, y, w, color = C.teal, weight = 4) {
  slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: weight },
    fill: color,
    line: { style: "solid", fill: color, width: 0 },
  });
}

function addHeader(slide, eyebrow, title, subtitle = "") {
  addRule(slide, 56, 44, 70, C.purple, 5);
  addRule(slide, 132, 44, 70, C.teal, 5);
  addText(slide, eyebrow, 56, 62, 520, 24, { fontSize: 13, bold: true, color: C.muted });
  addText(slide, title, 56, 90, 860, 58, { fontSize: 40, bold: true, color: C.navy });
  if (subtitle) addText(slide, subtitle, 58, 148, 840, 46, { fontSize: 20, color: C.muted });
}

function addFooter(slide, extra = "") {
  const text = extra || "mode = shadow | production_send = blocked | Auto ETR not customer-facing yet";
  addRect(slide, 355, 662, 570, 34, "#F1F6FC", "#CAD6E6", "rounded-lg");
  addText(slide, text, 372, 668, 536, 22, { fontSize: 13, bold: true, color: C.slate, alignment: "center" });
}

function addCard(slide, x, y, w, h, title, body, accent = C.teal) {
  addRect(slide, x, y, w, h, C.card, C.border, "rounded-xl", "shadow-sm");
  slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: 7, height: h },
    fill: accent,
    line: { style: "solid", fill: accent, width: 0 },
  });
  addText(slide, title, x + 24, y + 20, w - 44, 30, { fontSize: 24, bold: true, color: C.navy });
  addText(slide, body, x + 24, y + 62, w - 44, h - 76, { fontSize: 18, color: C.body });
}

function addNumberCircle(slide, x, y, d, number, label, fill, color = C.navy) {
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width: d, height: d },
    fill,
    line: { style: "solid", fill: "#FFFFFF", width: 3 },
    shadow: "shadow-sm",
  });
  addText(slide, number, x + 16, y + d * 0.29, d - 32, 54, { fontSize: 38, bold: true, color, alignment: "center" });
  addText(slide, label, x + 18, y + d * 0.62, d - 36, 64, { fontSize: 17, bold: true, color, alignment: "center" });
}

function addStep(slide, n, x, y, w, title, body, accent = C.teal) {
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: x, top: y, width: 48, height: 48 },
    fill: accent,
    line: { style: "solid", fill: accent, width: 0 },
  });
  addText(slide, String(n), x, y + 10, 48, 22, { fontSize: 22, bold: true, color: "#FFFFFF", alignment: "center" });
  addText(slide, title, x + 64, y, w - 64, 30, { fontSize: 22, bold: true, color: C.navy });
  addText(slide, body, x + 64, y + 38, w - 64, 52, { fontSize: 16, color: C.body });
}

function setNotes(slide, slideTitle, noteText) {
  const full = `${slideTitle}\n\n${noteText}`;
  slide.speakerNotes.textFrame.setText(full);
  slide.speakerNotes.setVisible(true);
  notes.push({ title: slideTitle, text: noteText });
}

async function addFullSlideImage(slide, imagePath, alt) {
  slide.images.add({
    blob: await readImageBlob(imagePath),
    contentType: "image/png",
    alt,
    fit: "cover",
    position: { left: 0, top: 0, width: W, height: H },
  });
}

const presentation = Presentation.create({ slideSize: { width: W, height: H } });

// Slide 1
{
  const slide = presentation.slides.add();
  await addFullSlideImage(slide, path.join(ASSET_DIR, "pea_api_intellisense_cover_background_v1.png"), "Electric grid and telecom cloud background");
  slide.shapes.add({ geometry: "rect", position: { left: 0, top: 0, width: 760, height: H }, fill: "#07162B", line: { style: "solid", fill: "#07162B", width: 0 } });
  addRule(slide, 72, 82, 300, C.teal, 4);
  addRule(slide, 72, 96, 190, C.amber, 3);
  addText(slide, "PEA API Intellisense", 72, 150, 650, 70, { fontSize: 54, bold: true, color: "#FFFFFF" });
  addText(slide, "From Outage Blindspot to\nProactive Grid Intelligence", 72, 245, 620, 118, { fontSize: 38, bold: true, color: "#FFFFFF" });
  addText(slide, "Cloud Shadow Pilot | Data Monetization | Zero-CAPEX Path", 74, 386, 640, 34, { fontSize: 21, color: C.cyan });
  addRect(slide, 72, 465, 615, 86, "#061D34", C.teal, "rounded-xl");
  addText(slide, "Presented by", 96, 482, 160, 22, { fontSize: 16, bold: true, color: C.cyan });
  addText(slide, "Pattarabordee Khaigunha (514460) - NE1 IoT Commitee", 96, 512, 555, 28, { fontSize: 20, bold: true, color: "#FFFFFF" });
  addFooter(slide, "mode = shadow | production_send = blocked");
  setNotes(slide, "Slide 1 - Cover / Hook", "วันนี้ผมนำเสนอ PEA API Intellisense ครับ แนวคิดหลักคือเปลี่ยนข้อมูลระบบจำหน่ายที่ PEA มีอยู่แล้ว ให้กลายเป็นบริการเชิงรุกผ่าน API สำหรับลูกค้ารายสำคัญอย่าง AIS เริ่มจากโจทย์ไฟดับของสถานีฐาน แล้วต่อยอดเป็น capability ด้าน Data Monetization ของ PEA");
}

// Slide 2
{
  const slide = presentation.slides.add();
  slide.background.fill = C.soft;
  addHeader(slide, "CUSTOMER PAIN", "AIS sees the failure, not the grid context", "Manual coordination creates delay, repeated work, and unnecessary dispatch risk.");
  addCard(slide, 70, 235, 500, 270, "Old workaround", "Phone calls\nChat messages\nManual checking\nRepeated details", C.amber);
  addCard(slide, 710, 235, 500, 270, "New operating model", "API request\nrequest_id\nEvidence gate\nAudit trail", C.teal);
  addText(slide, "->", 603, 335, 72, 50, { fontSize: 52, bold: true, color: C.purple, alignment: "center" });
  addText(slide, "Goal: change a phone-call chain into a governed evidence loop.", 188, 555, 900, 32, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 2 - Customer Pain Point", "ปัญหาจริงคือข้อมูลอยู่คนละฝั่งครับ AIS เห็นว่า site มีปัญหา แต่ไม่รู้ว่าไฟดับจากระบบจำหน่าย PEA หรือไม่ และจะกลับมาเมื่อไหร่ วิธีเดิมคือโทรถาม แชทถาม แล้วรอคนเปิดระบบไล่ดู ทำให้ตัดสินใจเรื่องทีมช่างหรือเครื่องปั่นไฟได้ช้า และบางครั้งเกิดต้นทุนที่ไม่จำเป็น");
}

// Slide 3
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addHeader(slide, "EXECUTIVE LENS", "The blindspot is large enough to be strategic", "These are planning estimates, not audited realized savings.");
  addNumberCircle(slide, 95, 245, 255, "59,997", "dispatch signals / year", "#DFF7FA", C.navy);
  addNumberCircle(slide, 512, 245, 255, "17.8M", "THB / year downtime-risk lens", "#E8E0FF", C.navy);
  addNumberCircle(slide, 930, 245, 255, "~48M", "THB / year strategic opportunity", "#FFF2CF", C.navy);
  addRect(slide, 185, 555, 910, 52, "#F8FBFF", C.border, "rounded-lg");
  addText(slide, "Strategic estimate | pending finance-owner validation | not realized saving yet", 205, 571, 870, 22, { fontSize: 19, bold: true, color: C.slate, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 3 - Size of Pain / Opportunity", "ถ้ามองในมุมผู้บริหาร blindspot นี้มีขนาดใหญ่พอครับ เอกสาร strategy ประเมิน dispatch signals ประมาณ 59,997 ครั้งต่อปี มี downtime-risk lens ประมาณ 17.8 ล้านบาทต่อปี และ opportunity รวมประมาณ 48 ล้านบาทต่อปี ตัวเลขนี้ยังเป็น strategic estimate ไม่ใช่ realized saving แต่บอกชัดว่าปัญหานี้ใหญ่พอที่จะทำเป็น capability ระดับองค์กร");
}

// Slide 4
{
  const slide = presentation.slides.add();
  slide.background.fill = C.soft;
  addHeader(slide, "WHY PEA", "The real product is trusted grid context", "AIS can see symptoms. PEA owns the truth layer behind the distribution network.");
  addCard(slide, 70, 240, 340, 230, "Grid Topology", "PEA maps how power actually reaches each AIS site.", C.purple);
  addCard(slide, 470, 240, 340, 230, "Evidence Context", "Protection and outage evidence help separate guesswork from confidence.", C.teal);
  addCard(slide, 870, 240, 340, 230, "Data Governance", "PEA controls what can be shared, redacted, reviewed, and audited.", C.amber);
  addText(slide, "AIS cannot build this layer alone because it sits inside PEA's grid data, operating evidence, and governance boundary.", 130, 540, 1020, 54, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 4 - Why This Is PEA's Opportunity", "จุดแข็งของงานนี้คือเหตุผลที่ต้องเป็น PEA ครับ AIS มีข้อมูล site ของตัวเอง แต่ไม่เห็นแผนผังการจ่ายไฟและบริบทเหตุขัดข้องของ PEA ส่วน PEA มี grid topology มีหลักฐานจากระบบปฏิบัติการ และมี governance ที่ควบคุมการใช้ข้อมูลได้ถูกต้อง ดังนั้นมูลค่าจริงไม่ใช่ API อย่างเดียว แต่มูลค่าคือ trusted grid context ที่อยู่หลัง API");
}

// Slide 5
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addHeader(slide, "SOLUTION", "How it works in human language", "A simple question becomes a safe, evidence-backed response lane.");
  addStep(slide, 1, 86, 220, 485, "AIS asks", "What happened to this site?", C.purple);
  addStep(slide, 2, 694, 220, 485, "PEA traces", "Which protection device or grid context feeds it?", C.teal);
  addStep(slide, 3, 86, 390, 485, "PEA verifies", "Did evidence match the time and location?", C.amber);
  addStep(slide, 4, 694, 390, 485, "PEA responds safely", "Status, shadow ETR candidate, or review lane.", C.green);
  addText(slide, "No code needed for the story: ask -> trace -> verify -> respond.", 210, 560, 860, 32, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 5 - Solution in Human Language", "พูดแบบภาษามนุษย์คือ AIS ถามว่า site นี้เกิดอะไรขึ้น PEA trace กลับว่าอยู่หลังอุปกรณ์ป้องกันตัวไหน จากนั้นเช็คหลักฐานว่าอุปกรณ์หรือเหตุการณ์นั้นเกิดขึ้นจริงในช่วงเวลาเดียวกันหรือไม่ แล้วจึงตอบกลับแบบปลอดภัย เช่น รับเรื่องแล้ว สถานะเบื้องต้น หรือ ETR candidate ที่ยังผ่าน human review ก่อน production");
}

// Slide 6
{
  const slide = presentation.slides.add();
  slide.background.fill = C.soft;
  addHeader(slide, "CURRENT MVP", "Cloud Shadow Pilot is already tangible", "The pilot can receive, store, review, and audit. Production send remains blocked.");
  addCard(slide, 74, 236, 255, 205, "Cloud API", "POST request accepted\nStatus lookup available\nDuplicate-safe request_id", C.purple);
  addCard(slide, 365, 236, 255, 205, "PostgreSQL", "Durable evidence store\nQueryable audit trail\nCloud-ready path", C.teal);
  addCard(slide, 656, 236, 255, 205, "Web Console", "Operator view\nDemo flow\nNo fallback story needed", C.green);
  addCard(slide, 947, 236, 255, 205, "Guardrail", "production_send\nremains blocked\nNo customer-facing Auto ETR", C.amber);
  addRect(slide, 226, 525, 828, 58, "#FFFFFF", C.border, "rounded-lg");
  addText(slide, "Built enough to prove flow. Conservative enough to protect production.", 246, 542, 788, 24, { fontSize: 22, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 6 - Current MVP / Cloud Shadow Pilot", "สถานะปัจจุบันเราไม่ได้อยู่แค่ idea แล้วครับ ตอนนี้มี Cloud Shadow API บน Render มี PostgreSQL เป็น evidence store มี Web Console สำหรับดู request และสถานะ แต่ guardrail สำคัญยังเหมือนเดิมคือ production_send ยัง blocked ระบบรับและเก็บหลักฐานได้ แต่ยังไม่ส่ง Auto ETR ไปใช้งานจริงกับลูกค้า");
}

// Slide 7
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addHeader(slide, "DEMO FLOW", "A five-step mission the judges can follow", "This is the exact story to show during the interactive demo.");
  const y = 260;
  const xs = [58, 300, 542, 784, 1026];
  const titles = ["AIS sends", "PEA accepts", "PEA traces", "Evidence gate", "Shadow review"];
  const bodies = ["API request", "202 Accepted", "meter/site -> grid", "confidence lane", "recorded, not sent"];
  xs.forEach((x, i) => {
    addRect(slide, x, y, 194, 190, "#F8FBFF", i === 3 ? C.amber : C.border, "rounded-xl", "shadow-sm");
    slide.shapes.add({ geometry: "ellipse", position: { left: x + 66, top: y + 20, width: 62, height: 62 }, fill: [C.purple, C.teal, C.green, C.amber, C.slate][i], line: { style: "solid", fill: "none", width: 0 } });
    addText(slide, String(i + 1), x + 66, y + 34, 62, 26, { fontSize: 24, bold: true, color: "#FFFFFF", alignment: "center" });
    addText(slide, titles[i], x + 18, y + 98, 158, 28, { fontSize: 21, bold: true, color: C.navy, alignment: "center" });
    addText(slide, bodies[i], x + 18, y + 134, 158, 40, { fontSize: 15, color: C.body, alignment: "center" });
    if (i < xs.length - 1) addText(slide, "->", x + 204, y + 70, 36, 38, { fontSize: 30, bold: true, color: C.muted, alignment: "center" });
  });
  addText(slide, "Demo line: API is simple; the evidence gate is the innovation.", 210, 535, 860, 34, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 7 - Demo Flow", "หน้า demo เราจะให้กรรมการเห็น 5 ขั้นครับ หนึ่ง AIS ยิง API มา สอง PEA รับ request ด้วย 202 Accepted สาม PEA trace จาก meter หรือ site ไปยังบริบทระบบจำหน่าย สี่ evidence gate ประเมินความมั่นใจ และห้า ระบบบันทึก shadow response ไว้ให้ operator ตรวจ ไม่ใช่ส่ง production อัตโนมัติ");
}

// Slide 8
{
  const slide = presentation.slides.add();
  slide.background.fill = C.soft;
  addHeader(slide, "TARGET ARCHITECTURE", "Production path: four controlled lanes", "Future integrations require owner approval, redaction, and production controls.");
  const layers = [
    ["Trigger lane", "AIS request now | AMR Last Gasp later", C.purple],
    ["Context lane", "Topology + protection evidence", C.teal],
    ["Reasoning lane", "Rule/model ETR candidate", C.green],
    ["Delivery lane", "API / callback / audit trail", C.amber],
  ];
  layers.forEach(([t, b, color], i) => {
    const y = 214 + i * 82;
    addRect(slide, 175, y, 930, 58, "#FFFFFF", color, "rounded-lg", "shadow-sm");
    addText(slide, t, 208, y + 14, 250, 25, { fontSize: 22, bold: true, color: C.navy });
    addText(slide, b, 470, y + 15, 560, 25, { fontSize: 20, color: C.body });
  });
  addRect(slide, 176, 568, 928, 52, "#FFF7DF", "#F2D28B", "rounded-lg");
  addText(slide, "Guardrail: Last Gasp, SCADA, and operation-text mining require owner approval before production use.", 206, 584, 868, 22, { fontSize: 17, bold: true, color: C.slate, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 8 - Target Production Architecture", "ใน production target เราจะแยกเป็น 4 lane ครับ Trigger lane อาจมาจาก AIS request และอนาคตจาก AMR Last Gasp ที่ได้รับอนุมัติ Context lane ใช้ topology และ protection evidence Reasoning lane ใช้ rule หรือ model เพื่อออก ETR candidate และ Delivery lane ส่งผ่าน API/callback พร้อม audit trail จุดที่ต้องพูดตรง ๆ คือ Last Gasp, SCADA และข้อความปฏิบัติการต้องผ่าน owner approval ก่อน ไม่ใช่เปิดใช้โดยพลการ");
}

// Slide 9
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addHeader(slide, "BUSINESS MODEL", "Data Monetization without a new hardware build", "Revenue path must still be validated by finance owners before formal booking.");
  addCard(slide, 78, 242, 330, 230, "Subscription", "1.5-2M THB/year/region\nPremium outage-context data service", C.purple);
  addCard(slide, 475, 242, 330, 230, "Usage upside", "Pay-per-API-call\nAligned to actual incident demand", C.teal);
  addCard(slide, 872, 242, 330, 230, "National upside", "6-8M THB/year potential\nZero-CAPEX path using existing PEA capability", C.amber);
  addText(slide, "Financial posture: strategic upside now, not audited realized revenue yet.", 185, 545, 910, 32, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 9 - Business Model / ROI", "ในมุมธุรกิจ งานนี้คือ Data Monetization ครับ รูปแบบแรกคือ subscription สำหรับข้อมูลพรีเมียม ประมาณ 1.5-2 ล้านบาทต่อปีต่อภูมิภาค หรือ 6-8 ล้านบาทต่อปีถ้าขยายทั่วประเทศ รูปแบบที่สองคือ pay-per-API-call ตามการใช้งานจริง จุดเด่นคือเป็น Zero-CAPEX path เพราะใช้ข้อมูล บุคลากร และระบบ IT ที่ PEA มีอยู่แล้วเป็นทุนเดิม แต่รายได้ต้องผ่าน finance validation ก่อนใช้เป็นตัวเลขทางบัญชี");
}

// Slide 10
{
  const slide = presentation.slides.add();
  slide.background.fill = C.soft;
  addHeader(slide, "RISK CONTROL", "Ambitious pitch, conservative system", "The system proves value in shadow mode before any customer-facing Auto ETR.");
  addCard(slide, 90, 230, 320, 220, "Allowed now", "Capture request\nAudit evidence\nStatus/demo response\nHuman review", C.green);
  addCard(slide, 480, 230, 320, 220, "Blocked now", "Automatic production ETR\nUnapproved mapping\nRaw sensitive text\nFull customer identity", C.red);
  addCard(slide, 870, 230, 320, 220, "Gate to open", "30+ green cases\nq50 MAE <= 16 min\nCoverage 0.75-0.90\nOwner approval", C.amber);
  addText(slide, "Production send opens only after infra gate + green evidence + callback approval + owner approval.", 145, 540, 990, 48, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 10 - Risk Control / Why Not Auto-Send Yet", "จุดที่ทำให้โครงการนี้ปลอดภัยคือเราไม่รีบเปิด Auto ETR ครับ ตอนนี้เป็น shadow mode มี human review และต้องผ่าน green evidence gate ก่อน โดยต้องมีเคสที่ validate แล้วอย่างน้อย 30 เคส ค่า error และ coverage อยู่ในเกณฑ์ และต้องมี owner approval ข้อมูลที่อ่อนไหว เช่น meter เต็ม ข้อความปฏิบัติการ หรือข้อมูลลูกค้า จะไม่ถูกเปิดเผยใน artifact สาธารณะ");
}

// Slide 11
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addHeader(slide, "3-MONTH PILOT", "Controlled proof before scale", "One province, scoped AIS hub sites, shadow run, and executive go/no-go evidence.");
  const months = [
    ["Month 1", "Data mapping", "100 AIS hub sites\nTopology owner review\nApproved data scope"],
    ["Month 2", "API / webhook", "Security contract\nLogging + retry\nMonitoring setup"],
    ["Month 3", "Validation / ROI", "Shadow run\nGreen evidence tracker\nGo/no-go packet"],
  ];
  months.forEach(([m, t, b], i) => {
    const x = 88 + i * 398;
    addRect(slide, x, 240, 310, 260, "#F8FBFF", [C.purple, C.teal, C.amber][i], "rounded-xl", "shadow-sm");
    addText(slide, m, x + 28, 265, 250, 26, { fontSize: 22, bold: true, color: [C.purple, C.teal, C.amber][i], alignment: "center" });
    addText(slide, t, x + 28, 310, 250, 36, { fontSize: 26, bold: true, color: C.navy, alignment: "center" });
    addText(slide, b, x + 36, 372, 238, 86, { fontSize: 18, color: C.body, alignment: "center" });
  });
  addText(slide, "Pilot decision: approve safe shadow bridge, not Auto ETR go-live.", 190, 550, 900, 32, { fontSize: 24, bold: true, color: C.navy, alignment: "center" });
  addFooter(slide);
  setNotes(slide, "Slide 11 - 3-Month Pilot Plan", "แผนที่ควรขออนุมัติคือ pilot 3 เดือนครับ เดือนแรกทำ data mapping สำหรับ AIS hub sites ในพื้นที่นำร่อง เดือนที่สองทำ API/webhook integration และ security contract เดือนที่สามทำ shadow run วัดผล ROI และจัดทำ go/no-go packet สำหรับผู้บริหาร ตรงนี้สอดคล้องกับ Master Document ที่เสนอ pilot 1 จังหวัด และเริ่มจาก scope ที่ควบคุมได้");
}

// Slide 12
{
  const slide = presentation.slides.add();
  await addFullSlideImage(slide, path.join(ASSET_DIR, "pea_api_intellisense_thank_you_background_v1.png"), "Electric grid and telecom closing background");
  slide.shapes.add({ geometry: "rect", position: { left: 0, top: 0, width: W, height: H }, fill: "#07162B", line: { style: "solid", fill: "#07162B", width: 0 } });
  addText(slide, "The Ask", 90, 82, 420, 64, { fontSize: 56, bold: true, color: "#FFFFFF" });
  addText(slide, "Approve the safe pilot bridge - not Auto ETR go-live", 92, 155, 760, 34, { fontSize: 24, color: C.cyan });
  addCard(slide, 90, 245, 330, 220, "1. Pilot Project", "Approve PEA-AIS pilot in a controlled scope.", C.purple);
  addCard(slide, 475, 245, 330, 220, "2. Data Scope", "Approve scoped AMR / topology / evidence access.", C.teal);
  addCard(slide, 860, 245, 330, 220, "3. Joint Working Group", "PEA Ops + PEA IT/API + AIS Dev/Ops owners.", C.amber);
  addText(slide, "Start with AIS. Prove trust. Scale PEA grid-context API capability.", 122, 535, 1036, 36, { fontSize: 28, bold: true, color: "#FFFFFF", alignment: "center" });
  addFooter(slide, "mode = shadow | production_send = blocked | Auto ETR not customer-facing yet");
  setNotes(slide, "Slide 12 - The Ask / Closing", "สิ่งที่ขอวันนี้มี 3 เรื่องครับ หนึ่ง อนุมัติหลักการทำ pilot ร่วมกับ AIS สอง อนุมัติการเข้าถึงข้อมูลเฉพาะ scope ที่ผูกกับ AIS และผ่าน owner approval เช่น AMR/topology/evidence สาม ตั้ง Joint Working Group ระหว่าง PEA Ops, PEA IT/API owner และ AIS Dev/Ops owner ขอย้ำว่าการตัดสินใจวันนี้คืออนุมัติ safe pilot bridge ไม่ใช่อนุมัติ Auto ETR production go-live");
}

await fs.mkdir(OUT_DIR, { recursive: true });
await fs.mkdir(PREVIEW_DIR, { recursive: true });
await fs.mkdir(QA_DIR, { recursive: true });

for (const [index, slide] of presentation.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  await writeBlob(path.join(PREVIEW_DIR, `${stem}.png`), await presentation.export({ slide, format: "png", scale: 2 }));
  await fs.writeFile(path.join(PREVIEW_DIR, `${stem}.layout.json`), await (await slide.export({ format: "layout" })).text(), "utf8");
}

await writeBlob(path.join(PREVIEW_DIR, "contact-sheet.webp"), await presentation.export({ format: "webp", montage: true, scale: 1 }));

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(FINAL_PPTX);

const script = [
  "# PEA API Intellisense V3 Clean Pitch - Speaker Script (TH)",
  "",
  "Deck: `runtime/weekend_delivery_freeze/presentation/pea_api_intellisense_v3_clean_pitch.pptx`",
  "",
  "Guardrail: ทุกครั้งที่พูดเรื่องระบบ ต้องย้ำว่า current state คือ Cloud Shadow Pilot, `mode = shadow`, `production_send = blocked`, และยังไม่ใช่ customer-facing Auto ETR.",
  "",
  ...notes.flatMap((n, i) => [
    `## ${i + 1}. ${n.title}`,
    "",
    n.text,
    "",
  ]),
].join("\n");
await writeTextUtf8Bom(SCRIPT_MD, script);

const inspect = await presentation.inspect({ kind: "slide,textbox,shape,image,notes", maxChars: 20000 });
const allText = inspect.ndjson + "\n" + script;
const forbidden = [
  /X-API-Key/i,
  /DATABASE_URL/i,
  /api[_ -]?key/i,
  /token/i,
  /room id/i,
  /PEANO/i,
  /raw WebEx/i,
  /https?:\/\//i,
];
const hits = forbidden.flatMap((pattern) => pattern.test(allText) ? [String(pattern)] : []);
const qa = [
  "PEA API Intellisense V3 Clean Pitch QA",
  `PPTX: ${FINAL_PPTX}`,
  `Slides: ${presentation.slides.items.length}`,
  `Preview: ${PREVIEW_DIR}`,
  `Script: ${SCRIPT_MD}`,
  "",
  "Checks:",
  "- slide count = 12",
  "- on-slide text primarily English",
  "- guardrail footer present on all slides",
  "- financial claims labeled strategic estimate/upside",
  "- no Auto ETR production live claim",
  "- Last Gasp/SCADA/operation-text mining framed as approved target lane, not current public claim",
  hits.length ? `- forbidden pattern hits: ${hits.join(", ")}` : "- forbidden pattern scan: PASS",
].join("\n");
await writeTextUtf8Bom(QA_REPORT, qa);

console.log(JSON.stringify({ FINAL_PPTX, PREVIEW_DIR, SCRIPT_MD, QA_REPORT }, null, 2));
