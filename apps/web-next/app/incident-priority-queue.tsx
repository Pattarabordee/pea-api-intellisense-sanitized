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
const statuses: Array<"ALL" | IncidentStatus> = ["ALL", "NEW", "ACKNOWLEDGED", "DISPATCHED", "IN_PROGRESS", "RESTORED"];

type AreaFilter = (typeof areas)[number];
type DetailTab = "DETAIL" | "WORK" | "AI";

const priorityLabels: Record<PriorityLevel, string> = {
  CRITICAL: "วิกฤต",
  HIGH: "เร่งด่วน",
  MEDIUM: "ปานกลาง",
  LOW: "ต่ำ",
  UNRATED: "ยังไม่ประเมิน"
};

// Presentation mapping follows the e-Response Event Management vocabulary where the
// source semantics align. RESTORED remains conservative because it is not equivalent
// to e-Response's completed/closed states.
const statusLabels: Record<IncidentStatus, string> = {
  NEW: "รอแก้ไข",
  ACKNOWLEDGED: "รับทราบ",
  DISPATCHED: "มอบหมายงานแล้ว",
  IN_PROGRESS: "อยู่ระหว่างดำเนินการ",
  RESTORED: "จ่ายไฟคืนแล้ว · รอตรวจสอบ"
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
  const [status, setStatus] = useState<(typeof statuses)[number]>("ALL");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(true);
  const [nativeCondition, setNativeCondition] = useState(true);
  const [detailTab, setDetailTab] = useState<DetailTab>("DETAIL");
  const [activeIncidentId, setActiveIncidentId] = useState(snapshot.items[0]?.incident_id ?? "");

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("th-TH");
    return [...snapshot.items]
      .filter((item) => !nativeCondition || item.status === "NEW")
      .filter((item) => area === "ALL" || item.area === area)
      .filter((item) => level === "ALL" || item.priority_level === level)
      .filter((item) => status === "ALL" || item.status === status)
      .filter((item) => {
        if (!needle) return true;
        return [
          item.incident_id,
          item.area,
          item.area_label,
          item.transformer_id ?? "",
          item.feeder_id ?? "",
          item.ai_summary,
          eventTypeLabel(item.event_type),
          statusLabels[item.status]
        ].join(" ").toLocaleLowerCase("th-TH").includes(needle);
      })
      .sort((a, b) => {
        if (a.status === "RESTORED" && b.status !== "RESTORED") return 1;
        if (a.status !== "RESTORED" && b.status === "RESTORED") return -1;
        const aRank = typeof a.queue_rank === "number" ? a.queue_rank : Number.MAX_SAFE_INTEGER;
        const bRank = typeof b.queue_rank === "number" ? b.queue_rank : Number.MAX_SAFE_INTEGER;
        // queue_rank is area-scoped. Never manufacture a cross-area global rank.
        if (area === "ALL" && a.area !== b.area) return a.area.localeCompare(b.area);
        if (aRank !== bRank) return aRank - bRank;
        const aScore = typeof a.priority_score === "number" ? a.priority_score : Number.NEGATIVE_INFINITY;
        const bScore = typeof b.priority_score === "number" ? b.priority_score : Number.NEGATIVE_INFINITY;
        return bScore - aScore;
      });
  }, [area, level, nativeCondition, search, snapshot.items, status]);

  const selected = snapshot.items.find((item) => item.incident_id === activeIncidentId) ?? filtered[0];
  const activeItems = snapshot.items.filter((item) => item.status !== "RESTORED");
  const waitingCount = snapshot.items.filter((item) => item.status === "NEW").length;
  const criticalHighCount = activeItems.filter((item) => item.priority_level === "CRITICAL" || item.priority_level === "HIGH").length;
  const knownAffected = activeItems.filter((item) => typeof item.affected_customers === "number");
  const affected = knownAffected.reduce((sum, item) => sum + (item.affected_customers ?? 0), 0);
  const reportCount = activeItems.reduce((sum, item) => sum + (item.report_count ?? 0), 0);

  const chooseStatus = (value: string) => {
    const next = value as (typeof statuses)[number];
    setStatus(next);
    if (next !== "ALL") setNativeCondition(false);
  };

  return (
    <main className="command-shell eres-shell">
      <header className="eres-header">
        <div className="eres-brand">
          <span className="eres-pea-mark" aria-hidden="true">PEA</span>
          <div>
            <strong>e-Response</strong>
            <small>OMS · EVENT MANAGEMENT</small>
          </div>
        </div>
        <nav className="eres-main-nav" aria-label="เมนู Event Management">
          <span className="active">เหตุการณ์ทั้งหมด</span>
          <span>แผนดับไฟ</span>
          <span>งาน</span>
        </nav>
        <div className="eres-module-state">
          <span>PEA Intellisense · AI PRIORITY</span>
          <strong><i />{sourceHealthLabel(sourceHealth.status)}</strong>
        </div>
      </header>

      <div className="eres-body">
        <div className="eres-breadcrumb">OMS <b>/</b> Event Management <b>/</b> เหตุการณ์ทั้งหมด <b>/</b> <strong>ลำดับความสำคัญ</strong></div>

        <section className="eres-titlebar">
          <div>
            <p>EVENT MANAGEMENT</p>
            <h1>เหตุการณ์ทั้งหมด</h1>
            <span>มุมมองลำดับความสำคัญช่วยให้ Operator เห็นเหตุที่ควรตรวจสอบก่อน โดยไม่เปลี่ยนขั้นตอนงานเดิมของ e-Response</span>
          </div>
          <div className="eres-safety-badges">
            <span>AI PRIORITY · DECISION SUPPORT</span>
            <span>SHADOW · READ ONLY</span>
          </div>
        </section>

        <section className="eres-toolbar" aria-label="เครื่องมือ Event Management">
          <label className="eres-search">
            <span>ค้นหา</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="รหัสเหตุการณ์, พื้นที่, สายป้อน, หม้อแปลง..."
              aria-label="ค้นหาเหตุการณ์"
            />
          </label>
          <button type="button" className={showFilters ? "eres-tool-button active" : "eres-tool-button"} onClick={() => setShowFilters((value) => !value)}>
            ตัวกรอง
          </button>
          <button type="button" className="eres-tool-button" onClick={() => window.location.reload()}>
            รีเฟรชข้อมูล
          </button>
          <div className="eres-toolbar-spacer" />
          <label className="eres-native-condition" title="ตามรูปแบบ Event Management ในคู่มือ: เงื่อนไขที่กำหนดไว้แสดงเหตุรอแก้ไข">
            <input type="checkbox" checked={nativeCondition} onChange={(event) => { setNativeCondition(event.target.checked); if (event.target.checked) setStatus("ALL"); }} />
            <span>ใช้เงื่อนไขที่กำหนดไว้</span>
            <small>รอแก้ไข</small>
          </label>
        </section>

        {showFilters ? (
          <section className="eres-filter-panel" aria-label="ตัวกรองเหตุการณ์">
            <FilterGroup label="พื้นที่" values={areas} current={area} onChange={(value) => setArea(value as AreaFilter)} />
            <FilterGroup label="ระดับความสำคัญ" values={levels} current={level} onChange={(value) => setLevel(value as (typeof levels)[number])} />
            <FilterGroup label="สถานะ" values={statuses} current={status} onChange={chooseStatus} />
            <div className="eres-filter-summary">
              <span>ผลลัพธ์</span>
              <strong>{filtered.length.toLocaleString("th-TH")} เหตุการณ์</strong>
            </div>
          </section>
        ) : null}

        <section className="eres-summary-grid" aria-label="สรุปเหตุการณ์">
          <SummaryCard value={snapshot.items.length.toLocaleString("th-TH")} label="เหตุการณ์ทั้งหมด" note="ข้อมูลในมุมมองปัจจุบัน" />
          <SummaryCard value={waitingCount.toLocaleString("th-TH")} label="รอแก้ไข" note="สถานะที่ e-Response ใช้ในคิวเริ่มต้น" emphasis="waiting" />
          <SummaryCard value={criticalHighCount.toLocaleString("th-TH")} label="วิกฤต / เร่งด่วน" note="คำแนะนำจาก AI Priority" emphasis="priority" />
          <SummaryCard
            value={knownAffected.length ? affected.toLocaleString("th-TH") : reportCount ? reportCount.toLocaleString("th-TH") : "—"}
            label={knownAffected.length ? "ผู้ใช้ไฟได้รับผลกระทบ" : "รายงานที่รวมได้"}
            note={knownAffected.length ? "เฉพาะจำนวนที่มีข้อมูล" : "จำนวนผู้ใช้ไฟยังไม่ยืนยัน"}
          />
        </section>

        <section className="eres-workspace">
          <div className="eres-event-list">
            <div className="eres-list-heading">
              <div>
                <strong>เหตุการณ์ทั้งหมด</strong>
                <span>เพิ่มคอลัมน์ AI Priority โดยไม่สร้างอันดับรวมข้าม BKN / PKN</span>
              </div>
              <span className="eres-record-count">{filtered.length.toLocaleString("th-TH")} รายการ</span>
            </div>

            <div className="eres-table-head" aria-hidden="true">
              <span>สถานะ</span>
              <span>AI PRIORITY</span>
              <span>เหตุการณ์</span>
              <span>พื้นที่ / อุปกรณ์</span>
              <span>แจ้งเมื่อ / รอ</span>
              <span>ผลกระทบ / หลักฐาน</span>
            </div>

            <div className="eres-event-rows">
              {filtered.map((item, index) => (
                <IncidentRow
                  key={item.incident_id}
                  item={item}
                  rankLabel={item.queue_rank ? `${area === "ALL" ? `${item.area} ` : ""}#${item.queue_rank}` : `${item.area} #${index + 1}`}
                  selected={selected?.incident_id === item.incident_id}
                  onSelect={() => { setActiveIncidentId(item.incident_id); setDetailTab("DETAIL"); }}
                />
              ))}
              {filtered.length === 0 ? <div className="empty-state">ไม่พบเหตุการณ์ตามเงื่อนไขที่เลือก</div> : null}
            </div>
          </div>

          <aside className="eres-detail-panel" aria-live="polite">
            {selected ? (
              <IncidentDetail item={selected} tab={detailTab} onTabChange={setDetailTab} />
            ) : (
              <div className="empty-state">เลือกเหตุการณ์เพื่อดูรายละเอียด</div>
            )}
          </aside>
        </section>

        <section className="eres-integration-note">
          <div>
            <strong>AI Priority เป็นมุมมองเสริมของ Event Management</strong>
            <p>ระบบนี้อ่านข้อมูลเพื่อช่วยจัดลำดับเท่านั้น ขั้นตอน รับทราบ → มอบหมายงาน → อยู่ระหว่างดำเนินการ → เสร็จสิ้น → ปิดงาน ยังคงเป็น workflow ของ e-Response และ Operator</p>
          </div>
          <div className="eres-boundary-tags">
            <span>ไม่เปลี่ยนสถานะ e-Response</span>
            <span>ไม่มอบหมายงานอัตโนมัติ</span>
            <span>ไม่ส่งข้อความลูกค้า</span>
          </div>
        </section>
      </div>

      <footer className="eres-footer">
        <span>e-Response / OMS · Event Management</span>
        <span>PEA Intellisense AI Priority · SHADOW / READ ONLY</span>
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
  const asset = item.transformer_id ?? item.feeder_id ?? "ยังไม่ยืนยันอุปกรณ์";
  const impact = typeof item.affected_customers === "number"
    ? `${item.affected_customers.toLocaleString("th-TH")} ผู้ใช้ไฟ`
    : typeof item.report_count === "number"
      ? `${item.report_count.toLocaleString("th-TH")} รายงาน · ผลกระทบยังไม่ยืนยัน`
      : "ผลกระทบยังไม่ยืนยัน";

  return (
    <button type="button" className={selected ? "eres-event-row selected" : "eres-event-row"} onClick={onSelect}>
      <div className="eres-status-cell"><StatusPill status={item.status} /></div>
      <div className="eres-priority-cell">
        <span className={`eres-priority-dot level-${item.priority_level.toLowerCase()}`} />
        <div>
          <strong>{rankLabel}</strong>
          <span>{priorityLabels[item.priority_level]} · {formatPriorityScore(item, "N/A")}</span>
        </div>
      </div>
      <div className="eres-event-cell">
        <strong>{item.incident_id}</strong>
        <span>{eventTypeLabel(item.event_type)}</span>
      </div>
      <div className="eres-asset-cell">
        <strong>{item.area_label}</strong>
        <span>{item.feeder_id ? `สายป้อน ${item.feeder_id}` : asset}</span>
        {item.transformer_id ? <small>หม้อแปลง {item.transformer_id}</small> : null}
      </div>
      <div className="eres-time-cell">
        <strong>{formatThaiDateTimeShort(item.first_reported_at)}</strong>
        <span>รอ {item.waiting_minutes.toLocaleString("th-TH")} นาที</span>
      </div>
      <div className="eres-impact-cell">
        <strong>{impact}</strong>
        <span>หลักฐาน: {evidenceLabels[item.evidence_strength]}</span>
      </div>
    </button>
  );
}

function IncidentDetail({ item, tab, onTabChange }: { item: IncidentPriorityItem; tab: DetailTab; onTabChange: (tab: DetailTab) => void }) {
  return (
    <div className="eres-detail-content">
      <div className="eres-detail-topline">
        <div>
          <span className="detail-kicker">รายละเอียดเหตุการณ์</span>
          <h2>{item.incident_id}</h2>
          <p>{eventTypeLabel(item.event_type)}</p>
        </div>
        <StatusPill status={item.status} />
      </div>

      <div className="eres-detail-tabs" role="tablist" aria-label="รายละเอียดเหตุการณ์">
        <button type="button" role="tab" aria-selected={tab === "DETAIL"} className={tab === "DETAIL" ? "active" : ""} onClick={() => onTabChange("DETAIL")}>รายละเอียด</button>
        <button type="button" role="tab" aria-selected={tab === "WORK"} className={tab === "WORK" ? "active" : ""} onClick={() => onTabChange("WORK")}>งาน</button>
        <button type="button" role="tab" aria-selected={tab === "AI"} className={tab === "AI" ? "active" : ""} onClick={() => onTabChange("AI")}>AI PRIORITY</button>
      </div>

      {tab === "DETAIL" ? <EventDetailTab item={item} /> : null}
      {tab === "WORK" ? <EventWorkTab item={item} /> : null}
      {tab === "AI" ? <EventAiTab item={item} /> : null}
    </div>
  );
}

function EventDetailTab({ item }: { item: IncidentPriorityItem }) {
  return (
    <div className="eres-tab-panel">
      <section className="eres-detail-section">
        <h3>ข้อมูลเหตุการณ์</h3>
        <div className="detail-facts">
          <Fact label="สถานะ" value={statusLabels[item.status]} />
          <Fact label="พื้นที่" value={`${item.area} / ${item.area_label}`} />
          <Fact label="วันที่ / เวลาแจ้งเหตุ" value={formatThaiDateTime(item.first_reported_at)} />
          <Fact label="เวลารอ" value={`${item.waiting_minutes.toLocaleString("th-TH")} นาที`} />
          <Fact label="สายป้อน" value={item.feeder_id ?? "ยังไม่ยืนยัน"} />
          <Fact label="หม้อแปลง" value={item.transformer_id ?? "ยังไม่ยืนยัน"} />
          <Fact label="ผู้ใช้ไฟได้รับผลกระทบ" value={typeof item.affected_customers === "number" ? `${item.affected_customers.toLocaleString("th-TH")} ราย` : "ยังไม่ยืนยัน"} />
          <Fact label="จำนวนรายงาน" value={typeof item.report_count === "number" ? `${item.report_count.toLocaleString("th-TH")} รายงาน` : "ยังไม่มีข้อมูล"} />
        </div>
      </section>

      <section className="eres-detail-section">
        <h3>ข้อมูลประกอบ</h3>
        <div className="eres-info-list">
          <InfoRow label="ประเภทเหตุ" value={eventTypeLabel(item.event_type)} />
          <InfoRow label="ลูกค้าสำคัญ / พื้นที่เสี่ยง" value={criticalRiskLabel(item.critical_customer_risk)} />
          <InfoRow label="หลักฐาน" value={evidenceLabels[item.evidence_strength]} />
          <InfoRow label="ข้อมูลลูกค้า" value="ไม่แสดงข้อมูลระบุตัวบุคคลในมุมมอง AI Priority" />
        </div>
      </section>
    </div>
  );
}

function EventWorkTab({ item }: { item: IncidentPriorityItem }) {
  const activeIndex = workflowActiveIndex(item.status);
  const workflow = ["รอแก้ไข", "รับทราบ", "มอบหมายงาน", "อยู่ระหว่างดำเนินการ", "เสร็จสิ้น", "ปิดงาน"];

  return (
    <div className="eres-tab-panel">
      <section className="eres-detail-section">
        <h3>สถานะการดำเนินงาน</h3>
        <div className="eres-workflow">
          {workflow.map((label, index) => (
            <div key={label} className={index < activeIndex ? "done" : index === activeIndex ? "current" : "future"}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{label}</strong>
            </div>
          ))}
        </div>
        {item.status === "RESTORED" ? <p className="eres-work-note">PEA Intellisense ทราบเพียงว่ามีหลักฐานการจ่ายไฟคืน จึงยังไม่ถือว่าเท่ากับ “เสร็จสิ้น” หรือ “ปิดงาน” ใน e-Response</p> : null}
      </section>

      <section className="eres-detail-section">
        <h3>มอบหมายงาน</h3>
        <div className="eres-assignment-card">
          <label>
            <span>ทีมงานของฉัน</span>
            <select disabled aria-label="ทีมงานของฉัน"><option>ยังไม่อ่านข้อมูลทีมจาก e-Response</option></select>
          </label>
          <button type="button" disabled>ยืนยันมอบหมายงาน</button>
          <p>โหมดเดโมเป็น Read Only จึงไม่เปลี่ยนสถานะ ไม่เลือกทีม และไม่ส่งงานจริง</p>
        </div>
      </section>

      <section className="eres-detail-section">
        <h3>เมนูเหตุการณ์</h3>
        <div className="eres-event-actions" aria-label="ตัวอย่างเมนูเหตุการณ์ e-Response">
          {["รับทราบ", "อยู่ระหว่างดำเนินการ", "เสร็จสิ้น", "ปิดงาน", "ยกเลิก", "ย้ายไป", "สร้างเหตุการณ์ต่อเนื่อง"].map((label) => <button type="button" key={label} disabled>{label}</button>)}
        </div>
      </section>
    </div>
  );
}

function EventAiTab({ item }: { item: IncidentPriorityItem }) {
  return (
    <div className="eres-tab-panel">
      <section className="eres-ai-score-panel">
        <div>
          <span>ลำดับแนะนำ</span>
          <strong>{item.queue_rank ? `${item.area} #${item.queue_rank}` : "ยังไม่มีอันดับ"}</strong>
          <small>อันดับแยกตามพื้นที่ ไม่ใช่อันดับรวม BKN / PKN</small>
        </div>
        <div>
          <span>ระดับความสำคัญ</span>
          <strong className={`text-${item.priority_level.toLowerCase()}`}>{priorityLabels[item.priority_level]}</strong>
          <small>คะแนน {formatPriorityScore(item)}</small>
        </div>
      </section>

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

      <div className="eres-ai-boundary">
        <strong>AI ช่วยจัดลำดับ · Operator เป็นผู้ตัดสินใจ</strong>
        <span>ข้อมูลที่ไม่ยืนยันจะคงเป็น “ไม่ทราบ / ยังไม่ประเมิน” และไม่ถูกเติมขึ้นเอง</span>
      </div>
    </div>
  );
}

function DetailSection({ label, children }: { label: string; children: React.ReactNode }) {
  return <section className="detail-section"><span className="section-label">{label}</span>{children}</section>;
}

function SummaryCard({ label, value, note, emphasis }: { label: string; value: string; note: string; emphasis?: "waiting" | "priority" }) {
  return <article className={emphasis ? `summary-card ${emphasis}` : "summary-card"}><strong>{value}</strong><div><span>{label}</span><small>{note}</small></div></article>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className="eres-info-row"><span>{label}</span><strong>{value}</strong></div>;
}

function StatusPill({ status }: { status: IncidentPriorityItem["status"] }) {
  return <span className={`status-pill status-${status.toLowerCase()}`} title={status}>{statusLabels[status]}</span>;
}

function filterValueLabel(value: string) {
  if (value === "ALL") return "ทั้งหมด";
  if (value in priorityLabels) return priorityLabels[value as PriorityLevel];
  if (value in statusLabels) return statusLabels[value as IncidentStatus];
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
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok"
  }).format(date) + " น.";
}

function formatThaiDateTimeShort(value: string) {
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

function workflowActiveIndex(status: IncidentStatus) {
  switch (status) {
    case "NEW": return 0;
    case "ACKNOWLEDGED": return 1;
    case "DISPATCHED": return 2;
    case "IN_PROGRESS": return 3;
    case "RESTORED": return 3;
  }
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
