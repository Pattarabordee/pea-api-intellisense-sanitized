"use client";

import { useMemo, useState } from "react";
import type {
  EvidenceStrength,
  IncidentPriorityItem,
  IncidentPrioritySnapshot,
  IncidentQueueSourceHealth,
  IncidentStatus,
  PriorityLevel
} from "../lib/incident-priority";

const levels: Array<"ALL" | PriorityLevel> = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"];
const areas = ["ALL", "BKN", "PKN"] as const;
type AreaFilter = (typeof areas)[number];

const priorityLabels: Record<PriorityLevel, string> = {
  CRITICAL: "วิกฤต",
  HIGH: "เร่งด่วน",
  MEDIUM: "ปานกลาง",
  LOW: "ต่ำ",
  UNRATED: "ยังไม่ประเมิน"
};

const statusLabels: Record<IncidentStatus, string> = {
  NEW: "ใหม่",
  ACKNOWLEDGED: "รับทราบแล้ว",
  DISPATCHED: "มอบหมายแล้ว",
  IN_PROGRESS: "กำลังดำเนินการ",
  RESTORED: "จ่ายไฟคืนแล้ว"
};

const evidenceLabels: Record<EvidenceStrength, string> = {
  STRONG: "แข็งแรง",
  MODERATE: "ปานกลาง",
  LIMITED: "จำกัด"
};

const eventTypeLabels: Record<string, string> = {
  SUSPECTED_HV_OUTAGE: "สงสัยเหตุไฟฟ้าขัดข้องแรงสูง",
  MULTI_REPORT_OUTAGE: "มีรายงานเหตุหลายจุด",
  LV_AREA_OUTAGE: "เหตุไฟฟ้าขัดข้องแรงต่ำในพื้นที่",
  SINGLE_AREA_REPORT: "รายงานเหตุจุดเดียวในพื้นที่",
  CUSTOMER_SPECIFIC_UNRESOLVED: "ปัญหาเฉพาะราย ยังไม่ยืนยันสาเหตุ",
  CUSTOMER_INTERNAL_SUSPECTED: "สงสัยปัญหาภายในผู้ใช้ไฟ",
  RESTORED_REVIEW: "จ่ายไฟคืนแล้ว รอตรวจสอบ",
  SUSPECTED_RELATED: "หลายรายงานน่าจะเกี่ยวข้องกัน",
  NO_CLUSTER: "ยังไม่พบเหตุอื่นที่เชื่อมโยงกัน",
  MULTIPLE_CLUSTER_CANDIDATES: "พบเหตุที่อาจเกี่ยวข้องมากกว่าหนึ่งกลุ่ม",
  PLANNED_OUTAGE_LINKED: "เชื่อมโยงกับแผนดับไฟ",
  PENDING: "กำลังตรวจสอบความเชื่อมโยง",
  UNAVAILABLE: "ข้อมูลความเชื่อมโยงยังไม่พร้อม",
  NOT_FOUND: "ยังไม่พบข้อมูลเหตุการณ์"
};

export function IncidentPriorityQueue({ snapshot, sourceHealth }: { snapshot: IncidentPrioritySnapshot; sourceHealth: IncidentQueueSourceHealth }) {
  const [area, setArea] = useState<AreaFilter>("ALL");
  const [level, setLevel] = useState<(typeof levels)[number]>("ALL");
  const [activeIncidentId, setActiveIncidentId] = useState(snapshot.items[0]?.incident_id ?? "");

  const filtered = useMemo(() => {
    return [...snapshot.items]
      .filter((item) => area === "ALL" || item.area === area)
      .filter((item) => level === "ALL" || item.priority_level === level)
      .sort((a, b) => {
        if (a.status === "RESTORED" && b.status !== "RESTORED") return 1;
        if (a.status !== "RESTORED" && b.status === "RESTORED") return -1;
        const aRank = typeof a.queue_rank === "number" ? a.queue_rank : Number.MAX_SAFE_INTEGER;
        const bRank = typeof b.queue_rank === "number" ? b.queue_rank : Number.MAX_SAFE_INTEGER;
        if (area === "ALL" && a.area !== b.area) return a.area.localeCompare(b.area);
        if (aRank !== bRank) return aRank - bRank;
        const aScore = typeof a.priority_score === "number" ? a.priority_score : Number.NEGATIVE_INFINITY;
        const bScore = typeof b.priority_score === "number" ? b.priority_score : Number.NEGATIVE_INFINITY;
        return bScore - aScore;
      });
  }, [area, level, snapshot.items]);

  const selected = snapshot.items.find((item) => item.incident_id === activeIncidentId) ?? filtered[0];
  const activeItems = snapshot.items.filter((item) => item.status !== "RESTORED");
  const criticalCount = activeItems.filter((item) => item.priority_level === "CRITICAL").length;
  const highCount = activeItems.filter((item) => item.priority_level === "HIGH").length;
  const knownAffected = activeItems.filter((item) => typeof item.affected_customers === "number");
  const affected = knownAffected.reduce((sum, item) => sum + (item.affected_customers ?? 0), 0);
  const reportCount = activeItems.reduce((sum, item) => sum + (item.report_count ?? 0), 0);
  const hasFreshPriority = activeItems.some((item) => item.priority_state === "AVAILABLE");

  return (
    <main className="command-shell">
      <header className="command-topbar">
        <div className="command-brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span className="brand-word">PEA INTELLISENSE</span>
          <span className="brand-dot" aria-hidden="true" />
        </div>
        <nav className="command-nav" aria-label="สถานะและมุมมองของระบบ">
          <span>คิวเหตุการณ์</span>
          <span>หน้า OPERATOR</span>
          <span className="nav-live"><i />{sourceHealthLabel(sourceHealth.status)}</span>
        </nav>
      </header>

      <section className="hero-panel">
        <div className="hero-copy-block">
          <p className="dot-label"><span /> ระบบสนับสนุนการตัดสินใจ · LIVE</p>
          <h1>จัดลำดับเหตุไฟฟ้าขัดข้อง<br />ให้เหตุเร่งด่วนขึ้นก่อน</h1>
          <p className="hero-copy">
            รวมรายงานที่เกี่ยวข้องให้เป็น Incident เดียว ประเมินความเร่งด่วนจากหลักฐานที่มี
            และช่วยให้ Operator เห็นว่างานใดควรตรวจสอบก่อน โดยข้อมูลที่ยังยืนยันไม่ได้จะคงสถานะว่า
            ไม่ทราบหรือยังไม่ประเมิน แทนการคาดเดา
          </p>
          <div className="hero-status-row">
            <span>โหมดเฝ้าดู · SHADOW</span>
            <span>ไม่ส่งคำสั่งอัตโนมัติ</span>
            <span>OPERATOR ตัดสินใจ</span>
          </div>
        </div>

        <div className="product-visual" aria-label="ภาพรวมการทำงานของ Incident Queue">
          <div className="visual-top">
            <span>PEA INCIDENT QUEUE / LIVE</span>
            <b>●</b>
          </div>
          <div className="visual-stage">
            <section className="visual-stack">
              <p>แหล่งข้อมูล</p>
              <div className="visual-node active">
                <i />
                <strong>รวมเหตุการณ์</strong>
                <span>สถานะที่บันทึกแล้ว</span>
              </div>
              <div className="visual-node">
                <i />
                <strong>ความสำคัญ</strong>
                <span>{hasFreshPriority ? "พร้อมใช้" : "ยังไม่พร้อม / ข้อมูลเก่า"}</span>
              </div>
            </section>
            <div className="visual-route"><i /><span /><em>ข้อมูล</em></div>
            <section className="visual-core">
              <small>OPERATOR VIEW</small>
              <strong>{activeItems.length.toString().padStart(2, "0")} เหตุที่กำลังดำเนินการ</strong>
              <div className="visual-tool-grid">
                <span>ลำดับ</span><span>ตัวกรอง</span><span>หลักฐาน</span><span>ตรวจสอบ</span>
              </div>
            </section>
            <div className="visual-route"><i /><span /><em>คน</em></div>
            <section className="visual-stack">
              <p>การควบคุม</p>
              <div className="visual-node active-green">
                <i />
                <strong>Operator</strong>
                <span>ตัดสินใจขั้นสุดท้าย</span>
              </div>
              <div className="visual-node muted-node">
                <i />
                <strong>สั่งงานอัตโนมัติ</strong>
                <span>ปิดอยู่</span>
              </div>
            </section>
          </div>
          <div className="visual-activity">
            <div><b>ข้อมูล</b><code>incident-queue-feed.v1</code><span>พร้อม</span></div>
            <div><b>แหล่ง</b><code>{sourceHealth.source_label}</code><span>{sourceHealth.fallback_active ? "สำรอง" : "LIVE"}</span></div>
            <div className="running"><b>โหมด</b><code>สนับสนุนการตัดสินใจ</code><span>ทำงาน</span></div>
          </div>
        </div>
      </section>

      <section className="summary-grid" aria-label="สรุปสถานการณ์เหตุการณ์">
        <SummaryCard value={String(activeItems.length).padStart(2, "0")} label="เหตุที่กำลังดำเนินการ" note="ไม่นับเหตุที่จ่ายไฟคืนแล้ว" />
        <SummaryCard value={String(criticalCount).padStart(2, "0")} label="วิกฤต" note="ในคิวปัจจุบัน" emphasis="critical" />
        <SummaryCard value={String(highCount).padStart(2, "0")} label="เร่งด่วน" note="ในคิวปัจจุบัน" emphasis="high" />
        <SummaryCard
          value={knownAffected.length ? affected.toLocaleString("th-TH") : reportCount ? reportCount.toLocaleString("th-TH") : "ยังไม่มีข้อมูล"}
          label={knownAffected.length ? "ผลกระทบที่ทราบ" : "รายงานที่รับ"}
          note={knownAffected.length ? "จำนวนผู้ใช้ไฟจากข้อมูลปัจจุบัน" : reportCount ? "จำนวนผู้ใช้ไฟยังไม่ยืนยัน" : "ยังไม่มีข้อมูลยืนยัน"}
        />
      </section>

      <section className="queue-section">
        <div className="section-kicker"><span>001</span><p>คิวเหตุการณ์ · OPERATOR</p></div>
        <div className="section-title-row">
          <h2>เหตุที่ควรตรวจสอบก่อน</h2>
          <p>แต่ละพื้นที่จัดอันดับแยกกันตามข้อมูลที่แหล่งต้นทางยืนยันได้ จึงไม่สร้างอันดับรวมข้ามพื้นที่ขึ้นเอง</p>
        </div>

        <div className="filter-row" aria-label="ตัวกรองคิวเหตุการณ์">
          <FilterGroup label="พื้นที่ · AREA" values={areas} current={area} onChange={(value) => setArea(value as AreaFilter)} />
          <FilterGroup label="ระดับ · LEVEL" values={levels} current={level} onChange={(value) => setLevel(value as (typeof levels)[number])} />
          <span className="record-count">{filtered.length.toString().padStart(2, "0")} เหตุการณ์</span>
        </div>

        <div className="workspace-grid">
          <section className="queue-panel" aria-label="คิวจัดลำดับเหตุการณ์">
            <div className="queue-column-head">
              <span>ลำดับ</span><span>ระดับ</span><span>เหตุการณ์ / หลักฐาน</span>
            </div>
            <div className="queue-list">
              {filtered.map((item, index) => (
                <IncidentRow
                  key={item.incident_id}
                  item={item}
                  rankLabel={item.queue_rank ? `${area === "ALL" ? `${item.area} ` : ""}#${item.queue_rank}` : `#${index + 1}`}
                  selected={selected?.incident_id === item.incident_id}
                  onSelect={() => setActiveIncidentId(item.incident_id)}
                />
              ))}
              {filtered.length === 0 ? <div className="empty-state">ไม่พบเหตุการณ์ตามตัวกรองที่เลือก</div> : null}
            </div>
          </section>

          <aside className="detail-panel" aria-live="polite">
            {selected ? <IncidentDetail item={selected} /> : <div className="empty-state">เลือกเหตุการณ์เพื่อดูรายละเอียดและหลักฐาน</div>}
          </aside>
        </div>
      </section>

      <section className="integration-section">
        <div className="integration-inner">
          <div className="section-kicker light"><span>002</span><p>ขอบเขตการตัดสินใจ</p></div>
          <div className="integration-title">
            <h2>AI ช่วยจัดลำดับ<br />Operator ตัดสินใจขั้นสุดท้าย</h2>
            <p>ข้อมูลที่ยังยืนยันไม่ได้จะแสดงว่า “ไม่ทราบ” หรือ “ยังไม่ประเมิน” แทนการคาดเดา</p>
          </div>
          <div className="flow-contract">
            <FlowBox index="01" title="หลักฐานเหตุการณ์" detail="รวมข้อมูลที่เชื่อมโยงกันโดยไม่ยืนยันเกินกว่าหลักฐาน" />
            <FlowBox index="02" title="สัญญาณความสำคัญ" detail="ใช้เฉพาะข้อมูลที่ยังสดและผ่านการตรวจสอบรูปแบบ" />
            <FlowBox index="03" title="คิวงาน" detail="จัดอันดับแยกตามพื้นที่ พร้อมสถานะและหลักฐาน" />
            <FlowBox index="04" title="Operator ตรวจสอบ" detail="การตัดสินใจและการมอบหมายงานยังเป็นของคน" />
          </div>
        </div>
      </section>

      <footer className="command-footer">
        <span>PEA INTELLISENSE / INCIDENT PRIORITY</span>
        <span>โหมดเฝ้าดู · ดูข้อมูลเท่านั้น · ไม่สั่งงานอัตโนมัติ</span>
      </footer>
    </main>
  );
}

function FilterGroup({ label, values, current, onChange }: { label: string; values: readonly string[]; current: string; onChange: (value: string) => void }) {
  return (
    <div className="filter-group">
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <button key={value} type="button" className={current === value ? "filter active" : "filter"} onClick={() => onChange(value)}>
            {filterValueLabel(value)}
          </button>
        ))}
      </div>
    </div>
  );
}

function IncidentRow({ item, rankLabel, selected, onSelect }: { item: IncidentPriorityItem; rankLabel: string; selected: boolean; onSelect: () => void }) {
  const asset = item.transformer_id ?? item.feeder_id ?? "อุปกรณ์ยังไม่ยืนยัน";
  return (
    <button type="button" className={selected ? "incident-row selected" : "incident-row"} onClick={onSelect}>
      <div className="rank">{rankLabel}</div>
      <div className={`score score-${item.priority_level.toLowerCase()}`} title={item.priority_level}>
        <strong>{formatPriorityScore(item, "N/A")}</strong>
        <span>{priorityLabels[item.priority_level]}</span>
      </div>
      <div className="incident-main">
        <div className="incident-title-line">
          <strong>{item.area} / {asset}</strong>
          <StatusPill status={item.status} />
        </div>
        <p>{item.ai_summary}</p>
        <div className="incident-meta">
          <span>{item.area_label}</span>
          <span>{eventTypeLabel(item.event_type)}</span>
          {item.feeder_id ? <span>สายป้อน {item.feeder_id}</span> : null}
          {typeof item.affected_customers === "number" ? <span>{item.affected_customers.toLocaleString("th-TH")} ผู้ใช้ไฟ</span> : <span>ผลกระทบยังไม่ยืนยัน</span>}
          {typeof item.report_count === "number" ? <span>{item.report_count.toLocaleString("th-TH")} รายงาน</span> : null}
          <span>รอ {item.waiting_minutes.toLocaleString("th-TH")} นาที</span>
          <span>หลักฐาน: {evidenceLabels[item.evidence_strength]}</span>
        </div>
      </div>
    </button>
  );
}

function IncidentDetail({ item }: { item: IncidentPriorityItem }) {
  return (
    <div className="detail-content">
      <div className="detail-topline">
        <div>
          <span className="detail-kicker">เหตุการณ์ที่เลือก · INCIDENT</span>
          <h3>{item.incident_id}</h3>
        </div>
        <span className={`level-badge level-${item.priority_level.toLowerCase()}`} title={item.priority_level}>
          {priorityLabels[item.priority_level]} {formatPriorityScore(item)}
        </span>
      </div>

      <div className="detail-facts">
        <Fact label="พื้นที่" value={`${item.area} / ${item.area_label}`} />
        <Fact label="ประเภทเหตุ" value={eventTypeLabel(item.event_type)} />
        <Fact label="สถานะ" value={statusLabels[item.status]} />
        <Fact label="แจ้งเหตุครั้งแรก" value={formatThaiDateTime(item.first_reported_at)} />
        <Fact label="รอมาแล้ว" value={`${item.waiting_minutes.toLocaleString("th-TH")} นาที`} />
        <Fact label="หม้อแปลง" value={item.transformer_id ?? "ยังไม่ยืนยัน"} />
        <Fact label="สายป้อน" value={item.feeder_id ?? "ยังไม่ยืนยัน"} />
        <Fact label="ผู้ใช้ไฟที่ได้รับผลกระทบ" value={typeof item.affected_customers === "number" ? `${item.affected_customers.toLocaleString("th-TH")} ราย` : "ยังไม่ยืนยัน"} />
        <Fact label="จำนวนรายงาน" value={typeof item.report_count === "number" ? `${item.report_count.toLocaleString("th-TH")} รายงาน` : "ยังไม่มีข้อมูล"} />
        <Fact label="ลูกค้าสำคัญ / พื้นที่เสี่ยง" value={criticalRiskLabel(item.critical_customer_risk)} />
        <Fact label="ความแข็งแรงของหลักฐาน" value={evidenceLabels[item.evidence_strength]} />
      </div>

      <DetailSection label="คำอธิบายประกอบการตัดสินใจ">
        <p className="explanation">{item.ai_summary}</p>
      </DetailSection>

      <DetailSection label="เหตุผลการจัดลำดับ">
        {item.priority_reasons.length ? (
          <ul className="reason-list">{item.priority_reasons.map((reason) => <li key={reason}>{displayPriorityReason(reason)}</li>)}</ul>
        ) : (
          <p className="detail-empty-note">ยังไม่มีเหตุผลการจัดลำดับที่ยืนยันได้</p>
        )}
      </DetailSection>

      <DetailSection label="ที่มาของหลักฐาน">
        {item.evidence_chain.length ? (
          <div className="evidence-chain">
            {item.evidence_chain.map((node, index) => (
              <div className="evidence-node" key={`${node}-${index}`}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{displayEvidenceNode(node)}</strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="detail-empty-note">ยังไม่มีลำดับหลักฐานเพิ่มเติม</p>
        )}
      </DetailSection>

      <div className="operator-gate">
        <div>
          <span>การตัดสินใจของ OPERATOR</span>
          <strong>ดูข้อมูลเพื่อประกอบการตัดสินใจเท่านั้น · ระบบไม่มอบหมายงานอัตโนมัติ</strong>
        </div>
        <span className="gate-state" title="ฟังก์ชันมอบหมายงานยังไม่เปิดในโหมดเดโม">DEMO · NO DISPATCH</span>
      </div>
    </div>
  );
}

function DetailSection({ label, children }: { label: string; children: React.ReactNode }) {
  return <section className="detail-section"><span className="section-label">{label}</span>{children}</section>;
}

function SummaryCard({ label, value, note, emphasis }: { label: string; value: string; note: string; emphasis?: "critical" | "high" }) {
  return <article className={emphasis ? `summary-card ${emphasis}` : "summary-card"}><strong>{value}</strong><div><span>{label}</span><small>{note}</small></div></article>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function StatusPill({ status }: { status: IncidentPriorityItem["status"] }) {
  return <span className={`status-pill status-${status.toLowerCase()}`} title={status}>{statusLabels[status]}</span>;
}

function FlowBox({ index, title, detail }: { index: string; title: string; detail: string }) {
  return <article className="flow-box"><span>{index}</span><h3>{title}</h3><p>{detail}</p></article>;
}

function filterValueLabel(value: string) {
  if (value === "ALL") return "ทั้งหมด";
  if (value in priorityLabels) return priorityLabels[value as PriorityLevel];
  return value;
}

function sourceHealthLabel(status: IncidentQueueSourceHealth["status"]) {
  switch (status) {
    case "LIVE_SHADOW": return "เชื่อมข้อมูลจริง · SHADOW";
    case "NOT_CONFIGURED": return "ยังไม่เชื่อมข้อมูล";
    case "UPSTREAM_UNAVAILABLE": return "แหล่งข้อมูลขัดข้อง";
    case "CONTRACT_INVALID": return "ข้อมูลไม่ผ่านการตรวจสอบ";
  }
}

function eventTypeLabel(eventType: string) {
  return eventTypeLabels[eventType] ?? humanizeTechnicalText(eventType);
}

function criticalRiskLabel(value: string) {
  const normalized = value.trim().toUpperCase();
  if (!value.trim() || normalized === "NOT_EVALUATED") return "ยังไม่ได้ประเมิน";
  if (normalized === "UNKNOWN" || normalized === "UNCONFIRMED") return "ยังไม่ยืนยัน";
  return displayPriorityReason(value);
}

function formatPriorityScore(item: IncidentPriorityItem, emptyLabel = "ยังไม่ประเมิน") {
  if (typeof item.priority_score !== "number") return emptyLabel;
  if (typeof item.score_max === "number" && item.score_max > 0) return `${item.priority_score}/${item.score_max}`;
  return String(item.priority_score);
}

function formatThaiDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "ยังไม่ยืนยัน";
  return new Intl.DateTimeFormat("th-TH", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok"
  }).format(date) + " น.";
}

function displayEvidenceNode(value: string) {
  const exact: Record<string, string> = {
    "Customer reports correlated": "รายงานจากลูกค้ามีความเชื่อมโยงกัน",
    "Incident correlation": "ระบบรวมรายงานเป็นเหตุการณ์เดียว",
    "Upstream evidence": "มีหลักฐานจากระบบต้นทางสนับสนุน",
    "Impact estimate": "ประเมินขอบเขตผลกระทบ",
    "Multi-channel reports": "พบรายงานจากหลายช่องทาง",
    "Area correlation": "พบความเชื่อมโยงในพื้นที่",
    "Candidate transformer": "พบหม้อแปลงที่อาจเกี่ยวข้อง",
    "Protection evidence pending": "รอหลักฐานจากอุปกรณ์ป้องกัน",
    "Customer reports": "รายงานจากลูกค้า",
    "Service point resolution": "ระบุจุดใช้ไฟได้",
    "Topology confirmed": "ยืนยันความเชื่อมโยงทางระบบไฟ",
    "Single report": "มีรายงานหนึ่งรายการ",
    "Candidate service point": "พบจุดใช้ไฟที่อาจเกี่ยวข้อง",
    "Candidate topology": "พบโครงข่ายที่อาจเกี่ยวข้อง",
    "Evidence incomplete": "หลักฐานยังไม่ครบ",
    "Service point candidate": "พบจุดใช้ไฟที่อาจเกี่ยวข้อง",
    "No correlated incident": "ยังไม่พบเหตุอื่นที่เชื่อมโยงกัน",
    "No HV evidence": "ยังไม่พบหลักฐานเหตุแรงสูง",
    "Review required": "ต้องให้ Operator ตรวจสอบ",
    "No related reports": "ยังไม่พบรายงานที่เกี่ยวข้อง",
    "Topology context only": "มีข้อมูลโครงข่ายเป็นบริบทเท่านั้น",
    "No outage confirmation": "ยังไม่ยืนยันว่าเป็นเหตุไฟฟ้าขัดข้อง",
    "Incident confirmed earlier": "เหตุการณ์เคยได้รับการยืนยันก่อนหน้านี้",
    "Restoration evidence": "มีหลักฐานการจ่ายไฟคืน",
    "Status RESTORED": "สถานะจ่ายไฟคืนแล้ว",
    "Close-out review": "รอตรวจสอบเพื่อปิดเหตุ"
  };

  if (exact[value]) return exact[value];
  const transformer = value.match(/^Transformer\s+(.+)$/i);
  if (transformer) return `หม้อแปลง ${transformer[1]}`;
  const feeder = value.match(/^Feeder\s+(.+)$/i);
  if (feeder) return `สายป้อน ${feeder[1]}`;
  const priority = value.match(/^Priority score\s+(.+)$/i);
  if (priority) return `คะแนนความสำคัญ ${priority[1]}`;
  return humanizeTechnicalText(value);
}

function displayPriorityReason(value: string) {
  return value
    .replace(/Topology confirmed/gi, "ยืนยันความเชื่อมโยงทางระบบไฟแล้ว")
    .replace(/candidate topology/gi, "โครงข่ายที่อาจเกี่ยวข้อง")
    .replace(/correlated reports/gi, "รายงานที่เชื่อมโยงกัน")
    .replace(/upstream evidence/gi, "หลักฐานจากระบบต้นทาง")
    .replace(/HV\/LV outage evidence/gi, "หลักฐานเหตุไฟฟ้าขัดข้องแรงสูง/แรงต่ำ")
    .replace(/dispatch/gi, "มอบหมายทีม")
    .replace(/close-out review/gi, "ตรวจสอบเพื่อปิดเหตุ")
    .replace(/active dispatch priority/gi, "งานที่ต้องมอบหมายในคิวปัจจุบัน")
    .replace(/restored/gi, "จ่ายไฟคืนแล้ว");
}

function humanizeTechnicalText(value: string) {
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}
