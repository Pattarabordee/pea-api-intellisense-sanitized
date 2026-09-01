"use client";

import { useMemo, useState } from "react";
import type { IncidentPriorityItem, IncidentPrioritySnapshot, IncidentQueueSourceHealth, PriorityLevel } from "../lib/incident-priority";

const levels: Array<"ALL" | PriorityLevel> = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"];
const areas = ["ALL", "BKN", "PKN"] as const;

type AreaFilter = (typeof areas)[number];

export function IncidentPriorityQueue({ snapshot, sourceHealth }: { snapshot: IncidentPrioritySnapshot; sourceHealth: IncidentQueueSourceHealth }) {
  const [area, setArea] = useState<AreaFilter>("ALL");
  const [level, setLevel] = useState<(typeof levels)[number]>("ALL");
  const [activeIncidentId, setActiveIncidentId] = useState(snapshot.items[0]?.incident_id ?? "");

  const filtered = useMemo(() => {
    return [...snapshot.items]
      .filter((item) => (area === "ALL" ? true : item.area === area))
      .filter((item) => (level === "ALL" ? true : item.priority_level === level))
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
  const affected = activeItems.reduce((sum, item) => sum + item.affected_customers, 0);

  return (
    <main className="command-shell">
      <header className="command-topbar">
        <div>
          <span className="brand-kicker">PEA INTELLISENSE</span>
          <strong>Incident Command Center</strong>
        </div>
        <div className="mode-strip" aria-label="runtime guardrails">
          <span>SHADOW MODE</span>
          <span>production_send = blocked</span>
          <span>{snapshot.source === "synthetic_demo" ? "synthetic demo data" : "priority adapter + PEA evidence"}</span>
          <span className={`source-indicator source-${sourceHealth.status.toLowerCase().replace(/_/g, "-")}`} title={sourceHealth.detail}>
            SOURCE {sourceHealth.status.replace(/_/g, " ")}
          </span>
        </div>
      </header>

      <section className="hero-panel">
        <div>
          <p className="eyebrow">Operator decision-support</p>
          <h1>จัดคิวงานแก้ไฟตามความสำคัญของ Incident</h1>
          <p className="hero-copy">
            รวมเหตุจากหลายรายงาน แล้วจัดลำดับด้วยผลกระทบ ความเสี่ยง ความแข็งแรงของหลักฐาน และสถานะการปฏิบัติงาน
            โดย operator ยังเป็นผู้ตัดสินใจสุดท้าย
          </p>
        </div>
        <div className="schema-card">
          <span>Canonical contract</span>
          <strong>{snapshot.schema_version}</strong>
          <small>Frontend ไม่ผูกกับ BKN/PKN n8n flow โดยตรง</small>
          <small>Queue source: {sourceHealth.source_label}{sourceHealth.fallback_active ? " (fallback)" : ""}</small>
        </div>
      </section>

      <section className="summary-grid" aria-label="incident summary">
        <SummaryCard label="Critical" value={String(criticalCount)} note="active incidents" emphasis="critical" />
        <SummaryCard label="High" value={String(highCount)} note="active incidents" emphasis="high" />
        <SummaryCard label="Active" value={String(activeItems.length)} note="excluding restored" />
        <SummaryCard label="Affected scope" value={affected.toLocaleString("th-TH")} note="estimated customers" />
      </section>

      <section className="workspace-grid">
        <section className="queue-panel" aria-labelledby="queue-title">
          <div className="panel-heading queue-heading">
            <div>
              <p className="eyebrow">Incident priority queue</p>
              <h2 id="queue-title">คิวที่ operator ต้องเห็นก่อน</h2>
            </div>
            <span className="record-count">{filtered.length} incidents</span>
          </div>

          <div className="filter-row" aria-label="queue filters">
            <div className="filter-group">
              <span>พื้นที่</span>
              {areas.map((item) => (
                <button key={item} type="button" className={area === item ? "filter active" : "filter"} onClick={() => setArea(item)}>
                  {item === "ALL" ? "ทั้งหมด" : item}
                </button>
              ))}
            </div>
            <div className="filter-group">
              <span>ระดับ</span>
              {levels.map((item) => (
                <button key={item} type="button" className={level === item ? "filter active" : "filter"} onClick={() => setLevel(item)}>
                  {item === "ALL" ? "ทั้งหมด" : item}
                </button>
              ))}
            </div>
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
            {filtered.length === 0 ? <div className="empty-state">ไม่พบ incident ตาม filter ที่เลือก</div> : null}
          </div>
        </section>

        <aside className="detail-panel" aria-live="polite">
          {selected ? <IncidentDetail item={selected} /> : <div className="empty-state">เลือก incident เพื่อดูหลักฐาน</div>}
        </aside>
      </section>

      <section className="contract-panel" aria-labelledby="contract-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Integration boundary</p>
            <h2 id="contract-title">Mock-first UI วันนี้ → verified Priority Adapter boundary พร้อมเชื่อม</h2>
          </div>
        </div>
        <div className="flow-contract">
          <FlowBox title="PEAPriorityAdapterV01" detail="shadow / blocked / multi-area signal" />
          <span className="arrow">→</span>
          <FlowBox title="Web normalizer" detail="validate guardrails + preserve queue_rank" />
          <span className="arrow">→</span>
          <FlowBox title="Incident view model" detail="join priority signal + PEA evidence" />
          <span className="arrow">→</span>
          <FlowBox title="Operator Queue" detail="read-only decision support" />
        </div>
      </section>
    </main>
  );
}

function IncidentRow({ item, rankLabel, selected, onSelect }: { item: IncidentPriorityItem; rankLabel: string; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" className={selected ? "incident-row selected" : "incident-row"} onClick={onSelect}>
      <div className="rank">{rankLabel}</div>
      <div className={`score score-${item.priority_level.toLowerCase()}`}>
        <strong>{item.priority_score ?? "—"}</strong>
        <span>{item.priority_level}</span>
      </div>
      <div className="incident-main">
        <div className="incident-title-line">
          <strong>{item.area_label} · {item.transformer_id}</strong>
          <StatusPill status={item.status} />
        </div>
        <p>{item.ai_summary}</p>
        <div className="incident-meta">
          <span>{item.feeder_id}</span>
          <span>{item.affected_customers.toLocaleString("th-TH")} ราย</span>
          <span>รอ {item.waiting_minutes} นาที</span>
          <span>Evidence {item.evidence_strength}</span>
          {item.priority_state && item.priority_state !== "AVAILABLE" ? <span>Priority {item.priority_state}</span> : null}
        </div>
      </div>
    </button>
  );
}

function IncidentDetail({ item }: { item: IncidentPriorityItem }) {
  return (
    <div>
      <div className="panel-heading detail-heading">
        <div>
          <p className="eyebrow">Selected incident</p>
          <h2>{item.incident_id}</h2>
        </div>
        <span className={`level-badge level-${item.priority_level.toLowerCase()}`}>{item.priority_level} {item.priority_score ?? "—"}</span>
      </div>

      <div className="detail-facts">
        <Fact label="พื้นที่" value={item.area_label} />
        <Fact label="เหตุการณ์" value={item.event_type} />
        <Fact label="Transformer" value={item.transformer_id} />
        <Fact label="Feeder" value={item.feeder_id} />
        <Fact label="Affected scope" value={`${item.affected_customers.toLocaleString("th-TH")} ราย`} />
        <Fact label="Evidence" value={item.evidence_strength} />
      </div>

      <div className="detail-section">
        <span className="section-label">AI explanation</span>
        <p className="explanation">{item.ai_summary}</p>
      </div>

      <div className="detail-section">
        <span className="section-label">เหตุผลที่ได้ลำดับนี้</span>
        <ul className="reason-list">
          {item.priority_reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      </div>

      <div className="detail-section">
        <span className="section-label">Evidence chain</span>
        <div className="evidence-chain">
          {item.evidence_chain.map((node, index) => (
            <div className="evidence-node" key={`${node}-${index}`}>
              <span>{index + 1}</span>
              <strong>{node}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="operator-gate">
        <div>
          <span>Operator gate</span>
          <strong>Review only — ไม่มีการสั่งทีมช่างจริง</strong>
        </div>
        <button type="button" disabled>Operator Review</button>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, note, emphasis }: { label: string; value: string; note: string; emphasis?: "critical" | "high" }) {
  return (
    <div className={emphasis ? `summary-card ${emphasis}` : "summary-card"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function StatusPill({ status }: { status: IncidentPriorityItem["status"] }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{status.replace(/_/g, " ")}</span>;
}

function FlowBox({ title, detail }: { title: string; detail: string }) {
  return <div className="flow-box"><strong>{title}</strong><span>{detail}</span></div>;
}
