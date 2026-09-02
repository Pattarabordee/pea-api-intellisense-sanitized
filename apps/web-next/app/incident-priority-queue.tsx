"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  EvidenceStrength,
  IncidentPriorityItem,
  IncidentPrioritySnapshot,
  IncidentQueueSourceHealth,
  PriorityLevel
} from "../lib/incident-priority";

const levels: Array<"ALL" | PriorityLevel> = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"];
const areas = ["ALL", "BKN", "PKN"] as const;
const workflowStatuses = ["ALL", "WAITING", "ACKNOWLEDGED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED"] as const;

type AreaFilter = (typeof areas)[number];
type WorkflowStatus = Exclude<(typeof workflowStatuses)[number], "ALL">;
type DetailTab = "DETAIL" | "WORK" | "AI";

type OperatorRecord = {
  incident_id: string;
  workflow_status: WorkflowStatus;
  assigned_team: string | null;
  moved_to: string | null;
  note: string | null;
  updated_at: string;
  timeline: Array<{ action: string; at: string; team?: string; note?: string; moved_to?: string }>;
};

const priorityLabels: Record<PriorityLevel, string> = {
  CRITICAL: "วิกฤต",
  HIGH: "เร่งด่วน",
  MEDIUM: "ปานกลาง",
  LOW: "ต่ำ",
  UNRATED: "ยังไม่ประเมิน"
};

const workflowLabels: Record<WorkflowStatus, string> = {
  WAITING: "รอแก้ไข",
  ACKNOWLEDGED: "รับทราบ",
  ASSIGNED: "มอบหมายงานแล้ว",
  IN_PROGRESS: "อยู่ระหว่างดำเนินการ",
  COMPLETED: "เสร็จสิ้น",
  CLOSED: "ปิดงาน",
  CANCELLED: "ยกเลิก"
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

const defaultTeams = [
  "ทีมแก้ไฟ 1 กฟส.พังโคน",
  "ทีมแก้ไฟ 2 กฟส.พังโคน",
  "ทีมฮอทไลน์ กฟส.พังโคน",
  "ทีมสนับสนุน กฟส.พังโคน",
  "ทีมแก้ไฟ กฟจ.บึงกาฬ"
];

export function IncidentPriorityQueue({ snapshot, sourceHealth }: { snapshot: IncidentPrioritySnapshot; sourceHealth: IncidentQueueSourceHealth }) {
  const [area, setArea] = useState<AreaFilter>("ALL");
  const [level, setLevel] = useState<(typeof levels)[number]>("ALL");
  const [status, setStatus] = useState<(typeof workflowStatuses)[number]>("ALL");
  const [search, setSearch] = useState("");
  const [showFilters, setShowFilters] = useState(true);
  const [nativeCondition, setNativeCondition] = useState(true);
  const [detailTab, setDetailTab] = useState<DetailTab>("DETAIL");
  const [activeIncidentId, setActiveIncidentId] = useState(snapshot.items[0]?.incident_id ?? "");
  const [operatorRecords, setOperatorRecords] = useState<Record<string, OperatorRecord>>({});
  const [teams, setTeams] = useState<string[]>(defaultTeams);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/eresponse/operator-state", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("operator-state")))
      .then((body) => {
        if (cancelled) return;
        if (body?.items && typeof body.items === "object") setOperatorRecords(body.items);
        if (Array.isArray(body?.teams) && body.teams.length) setTeams(body.teams);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const workflowStatus = (item: IncidentPriorityItem): WorkflowStatus => {
    const stored = operatorRecords[item.incident_id]?.workflow_status;
    if (stored) return stored;
    switch (item.status) {
      case "ACKNOWLEDGED": return "ACKNOWLEDGED";
      case "DISPATCHED": return "ASSIGNED";
      case "IN_PROGRESS": return "IN_PROGRESS";
      case "RESTORED": return "COMPLETED";
      default: return "WAITING";
    }
  };

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("th-TH");
    return [...snapshot.items]
      .filter((item) => !nativeCondition || workflowStatus(item) === "WAITING")
      .filter((item) => area === "ALL" || item.area === area)
      .filter((item) => level === "ALL" || item.priority_level === level)
      .filter((item) => status === "ALL" || workflowStatus(item) === status)
      .filter((item) => {
        if (!needle) return true;
        const record = operatorRecords[item.incident_id];
        return [
          item.incident_id,
          item.area,
          item.area_label,
          item.transformer_id ?? "",
          item.feeder_id ?? "",
          item.ai_summary,
          eventTypeLabel(item.event_type),
          workflowLabels[workflowStatus(item)],
          record?.assigned_team ?? ""
        ].join(" ").toLocaleLowerCase("th-TH").includes(needle);
      })
      .sort((a, b) => {
        if (workflowStatus(a) === "CLOSED" && workflowStatus(b) !== "CLOSED") return 1;
        if (workflowStatus(a) !== "CLOSED" && workflowStatus(b) === "CLOSED") return -1;
        const aRank = typeof a.queue_rank === "number" ? a.queue_rank : Number.MAX_SAFE_INTEGER;
        const bRank = typeof b.queue_rank === "number" ? b.queue_rank : Number.MAX_SAFE_INTEGER;
        if (area === "ALL" && a.area !== b.area) return a.area.localeCompare(b.area);
        if (aRank !== bRank) return aRank - bRank;
        const aScore = typeof a.priority_score === "number" ? a.priority_score : Number.NEGATIVE_INFINITY;
        const bScore = typeof b.priority_score === "number" ? b.priority_score : Number.NEGATIVE_INFINITY;
        return bScore - aScore;
      });
  // workflowStatus is deterministic over operatorRecords + item and intentionally kept local to this component.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [area, level, nativeCondition, operatorRecords, search, snapshot.items, status]);

  const selected = snapshot.items.find((item) => item.incident_id === activeIncidentId) ?? filtered[0];
  const waitingCount = snapshot.items.filter((item) => workflowStatus(item) === "WAITING").length;
  const activeItems = snapshot.items.filter((item) => !["CLOSED", "CANCELLED"].includes(workflowStatus(item)));
  const criticalHighCount = activeItems.filter((item) => item.priority_level === "CRITICAL" || item.priority_level === "HIGH").length;
  const knownAffected = activeItems.filter((item) => typeof item.affected_customers === "number");
  const affected = knownAffected.reduce((sum, item) => sum + (item.affected_customers ?? 0), 0);
  const reportCount = activeItems.reduce((sum, item) => sum + (item.report_count ?? 0), 0);

  const chooseStatus = (value: string) => {
    const next = value as (typeof workflowStatuses)[number];
    setStatus(next);
    if (next !== "ALL") setNativeCondition(false);
  };

  const runAction = async (incidentId: string, action: string, extra: Record<string, string> = {}) => {
    setActionBusy(true);
    setActionMessage("กำลังบันทึก...");
    try {
      const response = await fetch("/api/eresponse/operator-state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ incident_id: incidentId, action, ...extra })
      });
      const body = await response.json();
      if (!response.ok || !body?.item) throw new Error(body?.error || "WRITE_FAILED");
      setOperatorRecords((current) => ({ ...current, [incidentId]: body.item }));
      setActionMessage("บันทึกเรียบร้อย");
      return true;
    } catch {
      setActionMessage("บันทึกไม่สำเร็จ กรุณาลองอีกครั้ง");
      return false;
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <main className="command-shell eres-shell">
      <header className="eres-header">
        <div className="eres-brand">
          <span className="eres-pea-mark" aria-hidden="true">PEA</span>
          <div><strong>e-Response</strong><small>OMS · EVENT MANAGEMENT</small></div>
        </div>
        <nav className="eres-main-nav" aria-label="เมนู Event Management">
          <span className="active">เหตุการณ์ทั้งหมด</span><span>แผนดับไฟ</span><span>งาน</span>
        </nav>
        <div className="eres-module-state">
          <span>AI PRIORITY</span>
          <strong><i />{sourceHealthLabel(sourceHealth.status)}</strong>
        </div>
      </header>

      <div className="eres-body">
        <div className="eres-breadcrumb">OMS <b>/</b> Event Management <b>/</b> เหตุการณ์ทั้งหมด <b>/</b> <strong>ลำดับความสำคัญ</strong></div>

        <section className="eres-titlebar">
          <div>
            <p>EVENT MANAGEMENT</p>
            <h1>เหตุการณ์ทั้งหมด</h1>
            <span>จัดลำดับเหตุไฟฟ้าขัดข้องจากข้อมูลเหตุการณ์ หลักฐานโครงข่าย และสถานะหน้างาน เพื่อให้ Operator จัดการงานได้เร็วขึ้น</span>
          </div>
          <div className="eres-safety-badges"><span>AI PRIORITY</span><span>OPERATOR WORKFLOW</span></div>
        </section>

        <section className="eres-toolbar" aria-label="เครื่องมือ Event Management">
          <label className="eres-search"><span>ค้นหา</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="รหัสเหตุการณ์, พื้นที่, สายป้อน, หม้อแปลง, ทีมงาน..." aria-label="ค้นหาเหตุการณ์" /></label>
          <button type="button" className={showFilters ? "eres-tool-button active" : "eres-tool-button"} onClick={() => setShowFilters((value) => !value)}>ตัวกรอง</button>
          <button type="button" className="eres-tool-button" onClick={() => window.location.reload()}>รีเฟรชข้อมูล</button>
          <div className="eres-toolbar-spacer" />
          <label className="eres-native-condition"><input type="checkbox" checked={nativeCondition} onChange={(event) => { setNativeCondition(event.target.checked); if (event.target.checked) setStatus("ALL"); }} /><span>ใช้เงื่อนไขที่กำหนดไว้</span><small>รอแก้ไข</small></label>
        </section>

        {showFilters ? <section className="eres-filter-panel" aria-label="ตัวกรองเหตุการณ์">
          <FilterGroup label="พื้นที่" values={areas} current={area} onChange={(value) => setArea(value as AreaFilter)} />
          <FilterGroup label="ระดับความสำคัญ" values={levels} current={level} onChange={(value) => setLevel(value as (typeof levels)[number])} />
          <FilterGroup label="สถานะ" values={workflowStatuses} current={status} onChange={chooseStatus} />
          <div className="eres-filter-summary"><span>ผลลัพธ์</span><strong>{filtered.length.toLocaleString("th-TH")} เหตุการณ์</strong></div>
        </section> : null}

        <section className="eres-summary-grid" aria-label="สรุปเหตุการณ์">
          <SummaryCard value={snapshot.items.length.toLocaleString("th-TH")} label="เหตุการณ์ทั้งหมด" note="ข้อมูลในมุมมองปัจจุบัน" />
          <SummaryCard value={waitingCount.toLocaleString("th-TH")} label="รอแก้ไข" note="เหตุที่ยังไม่รับทราบ" emphasis="waiting" />
          <SummaryCard value={criticalHighCount.toLocaleString("th-TH")} label="วิกฤต / เร่งด่วน" note="จัดลำดับจาก AI Priority" emphasis="priority" />
          <SummaryCard value={knownAffected.length ? affected.toLocaleString("th-TH") : reportCount ? reportCount.toLocaleString("th-TH") : "—"} label={knownAffected.length ? "ผู้ใช้ไฟได้รับผลกระทบ" : "รายงานที่รวมได้"} note={knownAffected.length ? "จำนวนจากข้อมูลเหตุการณ์" : "รวมรายงานจากช่องทางรับแจ้ง"} />
        </section>

        <section className="eres-workspace">
          <div className="eres-event-list">
            <div className="eres-list-heading"><div><strong>เหตุการณ์ทั้งหมด</strong><span>AI Priority จัดอันดับแยกตามพื้นที่ปฏิบัติงาน</span></div><span className="eres-record-count">{filtered.length.toLocaleString("th-TH")} รายการ</span></div>
            <div className="eres-table-head" aria-hidden="true"><span>สถานะ</span><span>AI PRIORITY</span><span>เหตุการณ์</span><span>พื้นที่ / อุปกรณ์</span><span>แจ้งเมื่อ / รอ</span><span>ผลกระทบ / หลักฐาน</span></div>
            <div className="eres-event-rows">
              {filtered.map((item, index) => <IncidentRow key={item.incident_id} item={item} workflowStatus={workflowStatus(item)} assignedTeam={operatorRecords[item.incident_id]?.assigned_team ?? null} rankLabel={item.queue_rank ? `${area === "ALL" ? `${item.area} ` : ""}#${item.queue_rank}` : `${item.area} #${index + 1}`} selected={selected?.incident_id === item.incident_id} onSelect={() => { setActiveIncidentId(item.incident_id); setDetailTab("DETAIL"); setActionMessage(""); }} />)}
              {filtered.length === 0 ? <div className="empty-state">ไม่พบเหตุการณ์ตามเงื่อนไขที่เลือก</div> : null}
            </div>
          </div>

          <aside className="eres-detail-panel" aria-live="polite">
            {selected ? <IncidentDetail item={selected} workflowStatus={workflowStatus(selected)} record={operatorRecords[selected.incident_id]} teams={teams} tab={detailTab} onTabChange={setDetailTab} onAction={runAction} busy={actionBusy} actionMessage={actionMessage} /> : <div className="empty-state">เลือกเหตุการณ์เพื่อดูรายละเอียด</div>}
          </aside>
        </section>

        <section className="eres-integration-note"><div><strong>Event Management + AI Priority</strong><p>เหตุการณ์ การจัดลำดับ การมอบหมายทีม และสถานะการดำเนินงานอยู่ใน workflow เดียวกัน เพื่อให้ Operator ทำงานจากหน้าจอเดียว</p></div><div className="eres-boundary-tags"><span>เหตุการณ์</span><span>จัดลำดับ</span><span>มอบหมายทีม</span><span>ติดตามสถานะ</span></div></section>
      </div>

      <footer className="eres-footer"><span>e-Response / OMS · Event Management</span><span>PEA · Incident Priority & Dispatch</span></footer>
    </main>
  );
}

function FilterGroup({ label, values, current, onChange }: { label: string; values: readonly string[]; current: string; onChange: (value: string) => void }) {
  return <div className="filter-group"><span>{label}</span><div>{values.map((value) => <button key={value} type="button" className={current === value ? "filter active" : "filter"} onClick={() => onChange(value)}>{filterValueLabel(value)}</button>)}</div></div>;
}

function IncidentRow({ item, workflowStatus, assignedTeam, rankLabel, selected, onSelect }: { item: IncidentPriorityItem; workflowStatus: WorkflowStatus; assignedTeam: string | null; rankLabel: string; selected: boolean; onSelect: () => void }) {
  const asset = item.transformer_id ?? item.feeder_id ?? "ยังไม่ยืนยันอุปกรณ์";
  const impact = typeof item.affected_customers === "number" ? `${item.affected_customers.toLocaleString("th-TH")} ผู้ใช้ไฟ` : typeof item.report_count === "number" ? `${item.report_count.toLocaleString("th-TH")} รายงาน` : "กำลังประเมินผลกระทบ";
  return <button type="button" className={selected ? "eres-event-row selected" : "eres-event-row"} onClick={onSelect}>
    <div className="eres-status-cell"><StatusPill status={workflowStatus} /></div>
    <div className="eres-priority-cell"><span className={`eres-priority-dot level-${item.priority_level.toLowerCase()}`} /><div><strong>{rankLabel}</strong><span>{priorityLabels[item.priority_level]} · {formatPriorityScore(item, "กำลังประเมิน")}</span></div></div>
    <div className="eres-event-cell"><strong>{item.incident_id}</strong><span>{eventTypeLabel(item.event_type)}</span></div>
    <div className="eres-asset-cell"><strong>{item.area_label}</strong><span>{item.feeder_id ? `สายป้อน ${item.feeder_id}` : asset}</span>{item.transformer_id ? <small>หม้อแปลง {item.transformer_id}</small> : null}{assignedTeam ? <small>ทีม: {assignedTeam}</small> : null}</div>
    <div className="eres-time-cell"><strong>{formatThaiDateTimeShort(item.first_reported_at)}</strong><span>รอ {item.waiting_minutes.toLocaleString("th-TH")} นาที</span></div>
    <div className="eres-impact-cell"><strong>{impact}</strong><span>หลักฐาน: {evidenceLabels[item.evidence_strength]}</span></div>
  </button>;
}

function IncidentDetail({ item, workflowStatus, record, teams, tab, onTabChange, onAction, busy, actionMessage }: { item: IncidentPriorityItem; workflowStatus: WorkflowStatus; record?: OperatorRecord; teams: string[]; tab: DetailTab; onTabChange: (tab: DetailTab) => void; onAction: (incidentId: string, action: string, extra?: Record<string, string>) => Promise<boolean>; busy: boolean; actionMessage: string }) {
  return <div className="eres-detail-content">
    <div className="eres-detail-topline"><div><span className="detail-kicker">รายละเอียดเหตุการณ์</span><h2>{item.incident_id}</h2><p>{eventTypeLabel(item.event_type)}</p></div><StatusPill status={workflowStatus} /></div>
    <div className="eres-detail-tabs" role="tablist" aria-label="รายละเอียดเหตุการณ์"><button type="button" role="tab" aria-selected={tab === "DETAIL"} className={tab === "DETAIL" ? "active" : ""} onClick={() => onTabChange("DETAIL")}>รายละเอียด</button><button type="button" role="tab" aria-selected={tab === "WORK"} className={tab === "WORK" ? "active" : ""} onClick={() => onTabChange("WORK")}>งาน</button><button type="button" role="tab" aria-selected={tab === "AI"} className={tab === "AI" ? "active" : ""} onClick={() => onTabChange("AI")}>AI PRIORITY</button></div>
    {tab === "DETAIL" ? <EventDetailTab item={item} workflowStatus={workflowStatus} record={record} /> : null}
    {tab === "WORK" ? <EventWorkTab item={item} workflowStatus={workflowStatus} record={record} teams={teams} onAction={onAction} busy={busy} actionMessage={actionMessage} /> : null}
    {tab === "AI" ? <EventAiTab item={item} /> : null}
  </div>;
}

function EventDetailTab({ item, workflowStatus, record }: { item: IncidentPriorityItem; workflowStatus: WorkflowStatus; record?: OperatorRecord }) {
  return <div className="eres-tab-panel">
    <section className="eres-detail-section"><h3>ข้อมูลเหตุการณ์</h3><div className="detail-facts"><Fact label="สถานะ" value={workflowLabels[workflowStatus]} /><Fact label="พื้นที่" value={`${item.area} / ${item.area_label}`} /><Fact label="วันที่ / เวลาแจ้งเหตุ" value={formatThaiDateTime(item.first_reported_at)} /><Fact label="เวลารอ" value={`${item.waiting_minutes.toLocaleString("th-TH")} นาที`} /><Fact label="สายป้อน" value={item.feeder_id ?? "กำลังตรวจสอบ"} /><Fact label="หม้อแปลง" value={item.transformer_id ?? "กำลังตรวจสอบ"} /><Fact label="ผู้ใช้ไฟได้รับผลกระทบ" value={typeof item.affected_customers === "number" ? `${item.affected_customers.toLocaleString("th-TH")} ราย` : "กำลังประเมิน"} /><Fact label="จำนวนรายงาน" value={typeof item.report_count === "number" ? `${item.report_count.toLocaleString("th-TH")} รายงาน` : "กำลังรวบรวม"} /></div></section>
    <section className="eres-detail-section"><h3>ข้อมูลการปฏิบัติงาน</h3><div className="eres-info-list"><InfoRow label="ประเภทเหตุ" value={eventTypeLabel(item.event_type)} /><InfoRow label="ทีมรับผิดชอบ" value={record?.assigned_team ?? "ยังไม่มอบหมายทีม"} /><InfoRow label="จุดหมายที่ย้ายงาน" value={record?.moved_to ?? "—"} /><InfoRow label="อัปเดตล่าสุด" value={record?.updated_at ? formatThaiDateTime(record.updated_at) : formatThaiDateTime(item.first_reported_at)} /></div></section>
  </div>;
}

function EventWorkTab({ item, workflowStatus, record, teams, onAction, busy, actionMessage }: { item: IncidentPriorityItem; workflowStatus: WorkflowStatus; record?: OperatorRecord; teams: string[]; onAction: (incidentId: string, action: string, extra?: Record<string, string>) => Promise<boolean>; busy: boolean; actionMessage: string }) {
  const [team, setTeam] = useState(record?.assigned_team ?? teams[0] ?? "");
  const [moveTo, setMoveTo] = useState("กฟส.พังโคน");
  const activeIndex = workflowActiveIndex(workflowStatus);
  const workflow = ["รอแก้ไข", "รับทราบ", "มอบหมายงาน", "อยู่ระหว่างดำเนินการ", "เสร็จสิ้น", "ปิดงาน"];
  return <div className="eres-tab-panel">
    <section className="eres-detail-section"><h3>สถานะการดำเนินงาน</h3><div className="eres-workflow">{workflow.map((label, index) => <div key={label} className={index < activeIndex ? "done" : index === activeIndex ? "current" : "future"}><span>{String(index + 1).padStart(2, "0")}</span><strong>{label}</strong></div>)}</div>{workflowStatus === "CANCELLED" ? <p className="eres-work-note">เหตุการณ์นี้ถูกยกเลิกแล้ว</p> : null}</section>
    <section className="eres-detail-section"><h3>มอบหมายงาน</h3><div className="eres-assignment-card"><label><span>ทีมงานของฉัน</span><select value={team} onChange={(event) => setTeam(event.target.value)} aria-label="ทีมงานของฉัน">{teams.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><button type="button" disabled={busy || !team} onClick={() => onAction(item.incident_id, "ASSIGN", { team })}>ยืนยันมอบหมายงาน</button><p>{record?.assigned_team ? `ทีมปัจจุบัน: ${record.assigned_team}` : "เลือกทีมแล้วกดยืนยัน ระบบจะบันทึกลงสถานะงานทันที"}</p></div></section>
    <section className="eres-detail-section"><h3>เมนูเหตุการณ์</h3><div className="eres-event-actions"><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "ACKNOWLEDGE")}>รับทราบ</button><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "START")}>อยู่ระหว่างดำเนินการ</button><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "COMPLETE")}>เสร็จสิ้น</button><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "CLOSE")}>ปิดงาน</button><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "CANCEL")}>ยกเลิก</button></div><div className="eres-move-row"><input value={moveTo} onChange={(event) => setMoveTo(event.target.value)} aria-label="ย้ายไป" /><button type="button" disabled={busy || !moveTo.trim()} onClick={() => onAction(item.incident_id, "MOVE", { moved_to: moveTo })}>ย้ายไป</button><button type="button" disabled={busy} onClick={() => onAction(item.incident_id, "CREATE_CONTINUATION")}>สร้างเหตุการณ์ต่อเนื่อง</button></div>{actionMessage ? <p className="eres-action-message">{actionMessage}</p> : null}</section>
    {record?.timeline?.length ? <section className="eres-detail-section"><h3>ประวัติการดำเนินงาน</h3><div className="eres-timeline">{[...record.timeline].reverse().slice(0, 8).map((entry, index) => <div key={`${entry.at}-${index}`}><strong>{actionLabel(entry.action)}</strong><span>{formatThaiDateTime(entry.at)}{entry.team ? ` · ${entry.team}` : ""}{entry.moved_to ? ` · ${entry.moved_to}` : ""}</span></div>)}</div></section> : null}
  </div>;
}

function EventAiTab({ item }: { item: IncidentPriorityItem }) {
  return <div className="eres-tab-panel"><section className="eres-ai-score-panel"><div><span>ลำดับแนะนำ</span><strong>{item.queue_rank ? `${item.area} #${item.queue_rank}` : "กำลังจัดลำดับ"}</strong><small>จัดอันดับแยกตามพื้นที่ปฏิบัติงาน</small></div><div><span>ระดับความสำคัญ</span><strong className={`text-${item.priority_level.toLowerCase()}`}>{priorityLabels[item.priority_level]}</strong><small>คะแนน {formatPriorityScore(item)}</small></div></section><DetailSection label="คำอธิบายประกอบการตัดสินใจ"><p className="explanation">{item.ai_summary}</p></DetailSection><DetailSection label="เหตุผลการจัดลำดับ">{item.priority_reasons.length ? <ul className="reason-list">{item.priority_reasons.map((reason) => <li key={reason}>{displayPriorityReason(reason)}</li>)}</ul> : <p className="detail-empty-note">กำลังประเมินเหตุผลการจัดลำดับ</p>}</DetailSection><DetailSection label="ที่มาของหลักฐาน">{item.evidence_chain.length ? <div className="evidence-chain">{item.evidence_chain.map((node, index) => <div className="evidence-node" key={`${node}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><strong>{displayEvidenceNode(node)}</strong></div>)}</div> : <p className="detail-empty-note">กำลังรวบรวมหลักฐาน</p>}</DetailSection></div>;
}

function DetailSection({ label, children }: { label: string; children: React.ReactNode }) { return <section className="detail-section"><span className="section-label">{label}</span>{children}</section>; }
function SummaryCard({ label, value, note, emphasis }: { label: string; value: string; note: string; emphasis?: "waiting" | "priority" }) { return <article className={emphasis ? `summary-card ${emphasis}` : "summary-card"}><strong>{value}</strong><div><span>{label}</span><small>{note}</small></div></article>; }
function Fact({ label, value }: { label: string; value: string }) { return <div className="fact"><span>{label}</span><strong>{value}</strong></div>; }
function InfoRow({ label, value }: { label: string; value: string }) { return <div className="eres-info-row"><span>{label}</span><strong>{value}</strong></div>; }
function StatusPill({ status }: { status: WorkflowStatus }) { return <span className={`status-pill status-${status.toLowerCase()}`}>{workflowLabels[status]}</span>; }

function filterValueLabel(value: string) {
  if (value === "ALL") return "ทั้งหมด";
  if (value in priorityLabels) return priorityLabels[value as PriorityLevel];
  if (value in workflowLabels) return workflowLabels[value as WorkflowStatus];
  return value;
}

function sourceHealthLabel(status: IncidentQueueSourceHealth["status"]) {
  switch (status) {
    case "LIVE_SHADOW": return "เชื่อมข้อมูลออนไลน์";
    case "NOT_CONFIGURED": return "กำลังเชื่อมต่อข้อมูล";
    case "UPSTREAM_UNAVAILABLE": return "กำลังเชื่อมต่อใหม่";
    case "CONTRACT_INVALID": return "กำลังตรวจสอบข้อมูล";
  }
}

function eventTypeLabel(eventType: string) { return eventTypeLabels[eventType] ?? humanizeTechnicalText(eventType); }
function formatPriorityScore(item: IncidentPriorityItem, emptyLabel = "กำลังประเมิน") { if (typeof item.priority_score !== "number") return emptyLabel; if (typeof item.score_max === "number" && item.score_max > 0) return `${item.priority_score}/${item.score_max}`; return String(item.priority_score); }
function formatThaiDateTime(value: string) { const date = new Date(value); if (Number.isNaN(date.getTime())) return "—"; return new Intl.DateTimeFormat("th-TH", { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Bangkok" }).format(date) + " น."; }
function formatThaiDateTimeShort(value: string) { const date = new Date(value); if (Number.isNaN(date.getTime())) return "—"; return new Intl.DateTimeFormat("th-TH", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Bangkok" }).format(date) + " น."; }
function workflowActiveIndex(status: WorkflowStatus) { switch (status) { case "WAITING": return 0; case "ACKNOWLEDGED": return 1; case "ASSIGNED": return 2; case "IN_PROGRESS": return 3; case "COMPLETED": return 4; case "CLOSED": return 5; case "CANCELLED": return 0; } }
function actionLabel(action: string) { return ({ ACKNOWLEDGE: "รับทราบ", ASSIGN: "มอบหมายงาน", START: "เริ่มดำเนินการ", COMPLETE: "เสร็จสิ้น", CLOSE: "ปิดงาน", CANCEL: "ยกเลิก", MOVE: "ย้ายงาน", CREATE_CONTINUATION: "สร้างเหตุการณ์ต่อเนื่อง" } as Record<string, string>)[action] ?? action; }

function displayEvidenceNode(value: string) {
  const exact: Record<string, string> = { "Customer reports correlated": "รายงานจากลูกค้ามีความเชื่อมโยงกัน", "Incident correlation": "ระบบรวมรายงานเป็นเหตุการณ์เดียว", "Upstream evidence": "มีหลักฐานจากระบบต้นทางสนับสนุน", "Impact estimate": "ประเมินขอบเขตผลกระทบ", "Multi-channel reports": "พบรายงานจากหลายช่องทาง", "Area correlation": "พบความเชื่อมโยงในพื้นที่", "Candidate transformer": "พบหม้อแปลงที่อาจเกี่ยวข้อง", "Protection evidence pending": "รอหลักฐานจากอุปกรณ์ป้องกัน", "Customer reports": "รายงานจากลูกค้า", "Service point resolution": "ระบุจุดใช้ไฟได้", "Topology confirmed": "ยืนยันความเชื่อมโยงทางระบบไฟ", "Single report": "มีรายงานหนึ่งรายการ", "Candidate service point": "พบจุดใช้ไฟที่อาจเกี่ยวข้อง", "Candidate topology": "พบโครงข่ายที่อาจเกี่ยวข้อง", "Evidence incomplete": "หลักฐานยังไม่ครบ", "No correlated incident": "ยังไม่พบเหตุอื่นที่เชื่อมโยงกัน", "No HV evidence": "ยังไม่พบหลักฐานเหตุแรงสูง", "Review required": "ต้องให้ Operator ตรวจสอบ", "No outage confirmation": "ยังไม่ยืนยันว่าเป็นเหตุไฟฟ้าขัดข้อง", "Restoration evidence": "มีหลักฐานการจ่ายไฟคืน", "Status RESTORED": "สถานะจ่ายไฟคืนแล้ว", "Close-out review": "ตรวจสอบเพื่อปิดเหตุ" };
  if (exact[value]) return exact[value];
  const transformer = value.match(/^Transformer\s+(.+)$/i); if (transformer) return `หม้อแปลง ${transformer[1]}`;
  const feeder = value.match(/^Feeder\s+(.+)$/i); if (feeder) return `สายป้อน ${feeder[1]}`;
  const priority = value.match(/^Priority score\s+(.+)$/i); if (priority) return `คะแนนความสำคัญ ${priority[1]}`;
  return humanizeTechnicalText(value);
}

function displayPriorityReason(value: string) { return value.replace(/Topology confirmed/gi, "ยืนยันความเชื่อมโยงทางระบบไฟแล้ว").replace(/candidate topology/gi, "โครงข่ายที่อาจเกี่ยวข้อง").replace(/correlated reports/gi, "รายงานที่เชื่อมโยงกัน").replace(/upstream evidence/gi, "หลักฐานจากระบบต้นทาง").replace(/HV\/LV outage evidence/gi, "หลักฐานเหตุไฟฟ้าขัดข้องแรงสูง/แรงต่ำ").replace(/dispatch/gi, "มอบหมายทีม").replace(/close-out review/gi, "ตรวจสอบเพื่อปิดเหตุ").replace(/active dispatch priority/gi, "งานที่ต้องมอบหมายในคิวปัจจุบัน").replace(/restored/gi, "จ่ายไฟคืนแล้ว"); }
function humanizeTechnicalText(value: string) { return value.replace(/_/g, " ").replace(/\s+/g, " ").trim(); }
