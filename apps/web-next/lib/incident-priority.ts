export type PriorityLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNRATED";
export type IncidentStatus = "NEW" | "ACKNOWLEDGED" | "DISPATCHED" | "IN_PROGRESS" | "RESTORED";
export type EvidenceStrength = "STRONG" | "MODERATE" | "LIMITED";
export type PriorityState = "AVAILABLE" | "UNMATCHED" | "UNAVAILABLE" | "INPUT_INSUFFICIENT" | "CONTRACT_INVALID";
export type IncidentQueueSourceHealthStatus = "LIVE_SHADOW" | "NOT_CONFIGURED" | "UPSTREAM_UNAVAILABLE" | "CONTRACT_INVALID";
export type IncidentQueueSourceHealth = {
  status: IncidentQueueSourceHealthStatus;
  checked_at: string;
  source_label: string;
  fallback_active: boolean;
  detail: string;
};

export type IncidentPriorityItem = {
  incident_id: string;
  area: "BKN" | "PKN";
  area_label: string;
  queue_rank?: number;
  priority_score: number | null;
  raw_priority_score?: number | string | null;
  score_max?: number | null;
  priority_level: PriorityLevel;
  priority_state?: PriorityState;
  event_type: string;
  transformer_id: string | null;
  feeder_id: string | null;
  affected_customers: number | null;
  report_count?: number;
  critical_customer_risk: string;
  evidence_strength: EvidenceStrength;
  first_reported_at: string;
  waiting_minutes: number;
  status: IncidentStatus;
  ai_summary: string;
  priority_reasons: string[];
  evidence_chain: string[];
  source_mode: "MOCK_CONTRACT" | "PRIORITY_ADAPTER";
};

export type IncidentPrioritySnapshot = {
  schema_version: "incident-priority.v1";
  generated_at: string;
  mode: "shadow";
  production_send: "blocked";
  source: "synthetic_demo" | "priority_adapter_composed";
  items: IncidentPriorityItem[];
};

export const incidentPriorityDemo: IncidentPrioritySnapshot = {
  schema_version: "incident-priority.v1",
  generated_at: "2026-09-01T14:55:00+07:00",
  mode: "shadow",
  production_send: "blocked",
  source: "synthetic_demo",
  items: [
    {
      incident_id: "INC-BKN-20260901-001",
      area: "BKN",
      area_label: "บึงกาฬ",
      priority_score: 92,
      priority_level: "CRITICAL",
      event_type: "SUSPECTED_HV_OUTAGE",
      transformer_id: "63-006344",
      feeder_id: "BUA03",
      affected_customers: 135,
      critical_customer_risk: "มีโหลดสำคัญในพื้นที่ตรวจสอบ",
      evidence_strength: "STRONG",
      first_reported_at: "2026-09-01T14:17:00+07:00",
      waiting_minutes: 38,
      status: "ACKNOWLEDGED",
      ai_summary: "หลายรายงานสัมพันธ์กันในขอบเขตไฟฟ้าเดียวกันและมีหลักฐาน upstream สนับสนุน ควรตรวจสอบก่อนเหตุอื่น",
      priority_reasons: ["หลายช่องทางแจ้งเหตุสัมพันธ์กัน", "ผลกระทบผู้ใช้ไฟประมาณ 135 ราย", "มีหลักฐาน upstream สนับสนุน", "มีโหลดสำคัญที่ต้องตรวจสอบ"],
      evidence_chain: ["Customer reports correlated", "Incident correlation", "Transformer 63-006344", "Feeder BUA03", "Upstream evidence", "Impact estimate", "Priority score 92"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-PKN-20260901-004",
      area: "PKN",
      area_label: "พังโคน",
      priority_score: 84,
      priority_level: "HIGH",
      event_type: "MULTI_REPORT_OUTAGE",
      transformer_id: "PKN-TX-014",
      feeder_id: "PKN02",
      affected_customers: 98,
      critical_customer_risk: "ยังไม่พบ critical customer ที่ยืนยันแล้ว",
      evidence_strength: "MODERATE",
      first_reported_at: "2026-09-01T14:09:00+07:00",
      waiting_minutes: 46,
      status: "NEW",
      ai_summary: "มีรายงานหลายจุดในบริเวณใกล้เคียงและเวลารอสูง แต่หลักฐาน protection ยังไม่ครบ จัดเป็น High และให้ operator ตรวจสอบ",
      priority_reasons: ["รายงานหลายจุดในช่วงเวลาเดียวกัน", "เวลารอ 46 นาที", "ผลกระทบประมาณ 98 ราย", "หลักฐาน protection ยังไม่ครบ"],
      evidence_chain: ["Multi-channel reports", "Area correlation", "Candidate transformer", "Impact estimate", "Protection evidence pending", "Priority score 84"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-BKN-20260901-003",
      area: "BKN",
      area_label: "บึงกาฬ",
      priority_score: 76,
      priority_level: "HIGH",
      event_type: "LV_AREA_OUTAGE",
      transformer_id: "64-016689",
      feeder_id: "BKN04",
      affected_customers: 72,
      critical_customer_risk: "ไม่พบข้อมูลโหลดสำคัญ",
      evidence_strength: "STRONG",
      first_reported_at: "2026-09-01T14:31:00+07:00",
      waiting_minutes: 24,
      status: "DISPATCHED",
      ai_summary: "ขอบเขตหม้อแปลงมีหลักฐาน topology ชัดและมีผู้ใช้ไฟได้รับผลกระทบหลายราย ปัจจุบันอยู่ระหว่างส่งทีมตรวจสอบ",
      priority_reasons: ["Topology confirmed", "ผลกระทบประมาณ 72 ราย", "มีการ dispatch ทีมแล้ว", "หลักฐานเหตุระดับพื้นที่ค่อนข้างชัด"],
      evidence_chain: ["Customer reports", "Service point resolution", "Transformer 64-016689", "Topology confirmed", "Impact estimate", "Priority score 76"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-PKN-20260901-002",
      area: "PKN",
      area_label: "พังโคน",
      priority_score: 63,
      priority_level: "MEDIUM",
      event_type: "SINGLE_AREA_REPORT",
      transformer_id: "PKN-TX-007",
      feeder_id: "PKN01",
      affected_customers: 41,
      critical_customer_risk: "ไม่พบข้อมูลโหลดสำคัญ",
      evidence_strength: "MODERATE",
      first_reported_at: "2026-09-01T14:39:00+07:00",
      waiting_minutes: 16,
      status: "NEW",
      ai_summary: "มีขอบเขตพื้นที่ที่เป็นไปได้และผลกระทบระดับกลาง แต่ยังขาดหลักฐานร่วมจากหลายรายงาน จึงยังไม่ควรยกระดับเป็น High",
      priority_reasons: ["ผลกระทบประมาณ 41 ราย", "มี candidate topology", "ยังมีรายงานไม่เพียงพอสำหรับยืนยัน incident", "เวลารอยังไม่สูง"],
      evidence_chain: ["Single report", "Candidate service point", "Candidate topology", "Impact estimate", "Evidence incomplete", "Priority score 63"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-BKN-20260901-006",
      area: "BKN",
      area_label: "บึงกาฬ",
      priority_score: 48,
      priority_level: "MEDIUM",
      event_type: "CUSTOMER_SPECIFIC_UNRESOLVED",
      transformer_id: "BKN-TX-021",
      feeder_id: "BKN07",
      affected_customers: 1,
      critical_customer_risk: "ลูกค้ารายเดียว",
      evidence_strength: "LIMITED",
      first_reported_at: "2026-09-01T14:26:00+07:00",
      waiting_minutes: 29,
      status: "IN_PROGRESS",
      ai_summary: "ยังไม่พบ evidence ว่าเป็นเหตุระดับระบบ อาจเป็น customer-specific supply หรือปัญหาภายในบ้าน ต้องตรวจสอบโดยไม่เดาสถานะ outage",
      priority_reasons: ["ลูกค้ารายเดียว", "ไม่มี correlated reports", "ยังไม่มี HV/LV outage evidence", "เวลารอเพิ่มขึ้น"],
      evidence_chain: ["Single report", "Service point candidate", "No correlated incident", "No HV evidence", "Review required", "Priority score 48"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-PKN-20260901-005",
      area: "PKN",
      area_label: "พังโคน",
      priority_score: 31,
      priority_level: "LOW",
      event_type: "CUSTOMER_INTERNAL_SUSPECTED",
      transformer_id: "PKN-TX-003",
      feeder_id: "PKN03",
      affected_customers: 1,
      critical_customer_risk: "ลูกค้ารายเดียว",
      evidence_strength: "LIMITED",
      first_reported_at: "2026-09-01T14:48:00+07:00",
      waiting_minutes: 7,
      status: "NEW",
      ai_summary: "ไม่มีรายงานอื่นในขอบเขตเดียวกันและไม่มีหลักฐาน upstream สนับสนุน จึงวางไว้ท้ายคิวเพื่อให้ operator ตรวจสอบ customer-specific/internal cause",
      priority_reasons: ["ลูกค้ารายเดียว", "ไม่มี correlated reports", "ไม่มี upstream evidence", "เวลารอต่ำ"],
      evidence_chain: ["Single report", "No related reports", "Topology context only", "No outage confirmation", "Priority score 31"],
      source_mode: "MOCK_CONTRACT"
    },
    {
      incident_id: "INC-BKN-20260901-000",
      area: "BKN",
      area_label: "บึงกาฬ",
      priority_score: 18,
      priority_level: "LOW",
      event_type: "RESTORED_REVIEW",
      transformer_id: "BKN-TX-002",
      feeder_id: "BKN02",
      affected_customers: 22,
      critical_customer_risk: "ไม่พบข้อมูลโหลดสำคัญ",
      evidence_strength: "STRONG",
      first_reported_at: "2026-09-01T13:42:00+07:00",
      waiting_minutes: 73,
      status: "RESTORED",
      ai_summary: "เหตุอยู่ในสถานะ restored สำหรับการติดตามหลักฐานปิดงาน จึงไม่ควรแซงเหตุ active แม้เวลาตั้งแต่รับแจ้งจะสูง",
      priority_reasons: ["สถานะ restored", "เก็บไว้เพื่อ close-out review", "ไม่ใช่ active dispatch priority"],
      evidence_chain: ["Incident confirmed earlier", "Restoration evidence", "Status RESTORED", "Close-out review", "Priority score 18"],
      source_mode: "MOCK_CONTRACT"
    }
  ]
};
