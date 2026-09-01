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

  return (
    <main className="command-shell">
      <header className="command-topbar">
        <div className="command-brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span className="brand-word">PEA INTELLISENSE</span>
          <span className="brand-dot" aria-hidden="true" />
        </div>
        <nav className="command-nav" aria-label="สถานะระบบ">
          <span>INCIDENT QUEUE</span>
          <span>OPERATOR VIEW</span>
          <span className="nav-live"><i />{sourceHealth.status.replace(/_/g, " ")}</span>
        </nav>
      </header>

      <section className="hero-panel">
        <div className="hero-copy-block">
          <p className="dot-label"><span /> LIVE DECISION SUPPORT</p>
          <h1>จัดคิวเหตุไฟดับ<br />ให้สิ่งสำคัญขึ้นก่อน.</h1>
          <p className="hero-copy">
            รวมเหตุที่เกี่ยวข้องให้เป็น Incident เดียว จัดลำดับตามหลักฐานและความเร่งด่วน
            แล้วส่งให้ Operator เห็นสิ่งที่ควรตรวจสอบก่อน โดยไม่เดาข้อมูลที่ระบบยังยืนยันไม่ได้
          </p>
          <div className="hero-status-row">
            <span>SHADOW MODE</span>
            <span>PRODUCTION SEND / BLOCKED</span>
            <span>OPERATOR DECIDES</span>
          </div>
        </div>

        <div className="product-visual" aria-label="ภาพรวมสถานะ Incident Queue">
          <div className="visual-top">
            <span>PEA INCIDENT QUEUE / LIVE</span>
            <b>●</b>
          </div>
          <div className="visual-stage">
            <section className="visual-stack">
              <p>INCIDENT SOURCE</p>
              <div className="visual-node active">
                <i />
                <strong>Correlation</strong>
                <span>DURABLE STATE</span>
              </div>
              <div className="visual-node">
                <i />
                <strong>Priority</strong>
                <span>{activeItems.some((item) => item.priority_state === "AVAILABLE") ? "AVAILABLE" : "UNAVAILABLE / STALE"}</span>
              </div>
            </section>
            <div className="visual-route"><i /><span /><em>FEED</em></div>
            <section className="visual-core">
              <small>OPERATOR SURFACE</small>
              <strong>{activeItems.length.toString().padStart(2, "0")} ACTIVE</strong>
              <div className="visual-tool-grid">
                <span>RANK</span><span>FILTER</span><span>EVIDENCE</span><span>REVIEW</span>
              </div>
            </section>
            <div className="visual-route"><i /><span /><em>HUMAN</em></div>
            <section className="visual-stack">
              <p>CONTROL</p>
              <div className="visual-node active-green">
                <i />
                <strong>Operator</strong>
                <span>FINAL DECISION</span>
              </div>
              <div className="visual-node muted-node">
                <i />
                <strong>Auto Send</strong>
                <span>BLOCKED</span>
              </div>
            </section>
          </div>
          <div className="visual-activity">
            <div><b>READ</b><code>incident-queue-feed.v1</code><span>✓</span></div>
            <div><b>SOURCE</b><code>{sourceHealth.source_label}</code><span>{sourceHealth.fallback_active ? "FALLBACK" : "LIVE"}</span></div>
            <div className="running"><b>MODE</b><code>operator decision-support</code><span>ACTIVE</span></div>
          </div>
        </div>
      </section>

      <section className="summary-grid" aria-label="incident summary">
        <SummaryCard value={String(activeItems.length).padStart(2, "0")} label="Active incidents" note="excluding restored" />
        <SummaryCard value={String(criticalCount).padStart(2, "0")} label="Critical" note="active queue" emphasis="critical" />
        <SummaryCard value={String(highCount).padStart(2, "0")} label="High" note="active queue" emphasis="high" />
        <SummaryCard value={knownAffected.length ? affected.toLocaleString("th-TH") : reportCount ? `${reportCount}R` : "—"} label="Known impact" note={knownAffected.length ? "estimated customers" : reportCount ? "reports / impact unknown" : "authoritative count unavailable"} />
      </section>

      <section className="queue-section">
        <div className="section-kicker"><span>001</span><p>OPERATOR QUEUE</p></div>
        <div className="section-title-row">
          <h2>คิวที่ต้องเห็นก่อน.</h2>
          <p>เรียงตามพื้นที่และอันดับที่แหล่งข้อมูลยืนยันได้ ไม่สร้างอันดับข้ามพื้นที่ขึ้นเอง</p>
        </div>

        <div className="filter-row" aria-label="queue filters">
          <FilterGroup label="AREA" values={areas} current={area} onChange={(value) => setArea(value as AreaFilter)} />
          <FilterGroup label="LEVEL" values={levels} current={level} onChange={(value) => setLevel(value as (typeof levels)[number])} />
          <span className="record-count">{filtered.length.toString().padStart(2, "0")} INCIDENTS</span>
        </div>

        <div className="workspace-grid">
          <section className="queue-panel" aria-label="Incident priority queue">
            <div className="queue-column-head">
              <span>RANK</span><span>PRIORITY</span><span>INCIDENT / EVIDENCE</span>
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
              {filtered.length === 0 ? <div className="empty-state">ไม่พบ Incident ตามตัวกรองที่เลือก</div> : null}
            </div>
          </section>

          <aside className="detail-panel" aria-live="polite">
            {selected ? <IncidentDetail item={selected} /> : <div className="empty-state">เลือก Incident เพื่อดูหลักฐาน</div>}
          </aside>
        </div>
      </section>

      <section className="integration-section">
        <div className="integration-inner">
          <div className="section-kicker light"><span>002</span><p>DECISION BOUNDARY</p></div>
          <div className="integration-title">
            <h2>AI ช่วยจัดลำดับ.<br />คนเป็นผู้ตัดสินใจ.</h2>
            <p>ข้อมูลที่ไม่ยืนยันจะคงเป็น Unknown / Unrated แทนการเติมค่าขึ้นมาเอง</p>
          </div>
          <div className="flow-contract">
            <FlowBox index="01" title="Incident evidence" detail="durable correlation state" />
            <FlowBox index="02" title="Priority signal" detail="fresh signal only" />
            <FlowBox index="03" title="Queue model" detail="rank + evidence + state" />
            <FlowBox index="04" title="Operator review" detail="human decision remains final" />
          </div>
        </div>
      </section>

      <footer className="command-footer">
        <span>PEA INTELLISENSE / INCIDENT PRIORITY</span>
        <span>SHADOW / READ ONLY / READY</span>
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
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}

function IncidentRow({ item, rankLabel, selected, onSelect }: { item: IncidentPriorityItem; rankLabel: string; selected: boolean; onSelect: () => void }) {
  const asset = item.transformer_id ?? item.feeder_id ?? "ASSET UNCONFIRMED";
  return (
    <button type="button" className={selected ? "incident-row selected" : "incident-row"} onClick={onSelect}>
      <div className="rank">{rankLabel}</div>
      <div className={`score score-${item.priority_level.toLowerCase()}`}>
        <strong>{item.priority_score ?? "—"}</strong>
        <span>{item.priority_level}</span>
      </div>
      <div className="incident-main">
        <div className="incident-title-line">
          <strong>{item.area} / {asset}</strong>
          <StatusPill status={item.status} />
        </div>
        <p>{item.ai_summary}</p>
        <div className="incident-meta">
          <span>{item.area_label}</span>
          {item.feeder_id ? <span>FDR {item.feeder_id}</span> : null}
          {typeof item.affected_customers === "number" ? <span>{item.affected_customers.toLocaleString("th-TH")} CUSTOMERS</span> : <span>IMPACT UNKNOWN</span>}
          {typeof item.report_count === "number" ? <span>{item.report_count} REPORTS</span> : null}
          <span>{item.waiting_minutes} MIN</span>
          <span>EVIDENCE {item.evidence_strength}</span>
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
          <span className="detail-kicker">SELECTED INCIDENT</span>
          <h3>{item.incident_id}</h3>
        </div>
        <span className={`level-badge level-${item.priority_level.toLowerCase()}`}>{item.priority_level} {item.priority_score ?? "—"}</span>
      </div>

      <div className="detail-facts">
        <Fact label="AREA" value={`${item.area} / ${item.area_label}`} />
        <Fact label="EVENT" value={item.event_type} />
        <Fact label="TRANSFORMER" value={item.transformer_id ?? "UNCONFIRMED"} />
        <Fact label="FEEDER" value={item.feeder_id ?? "UNCONFIRMED"} />
        <Fact label="AFFECTED" value={typeof item.affected_customers === "number" ? `${item.affected_customers.toLocaleString("th-TH")} customers` : "UNKNOWN"} />
        <Fact label="REPORTS" value={typeof item.report_count === "number" ? String(item.report_count) : "—"} />
      </div>

      <DetailSection label="DECISION-SUPPORT EXPLANATION">
        <p className="explanation">{item.ai_summary}</p>
      </DetailSection>

      <DetailSection label="PRIORITY REASONS">
        <ul className="reason-list">{item.priority_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
      </DetailSection>

      <DetailSection label="EVIDENCE CHAIN">
        <div className="evidence-chain">
          {item.evidence_chain.map((node, index) => <div className="evidence-node" key={`${node}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><strong>{node}</strong></div>)}
        </div>
      </DetailSection>

      <div className="operator-gate">
        <div><span>OPERATOR GATE</span><strong>REVIEW ONLY / NO AUTOMATIC DISPATCH</strong></div>
        <button type="button" disabled>REVIEW</button>
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
  return <span className={`status-pill status-${status.toLowerCase()}`}>{status.replace(/_/g, " ")}</span>;
}

function FlowBox({ index, title, detail }: { index: string; title: string; detail: string }) {
  return <article className="flow-box"><span>{index}</span><h3>{title}</h3><p>{detail}</p></article>;
}
