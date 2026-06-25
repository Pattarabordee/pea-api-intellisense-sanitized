"use client";

import { useMemo, useState } from "react";
import type { OperatorData, OperatorItem } from "../lib/demo-data";

const missionSteps = [
  {
    id: "ais",
    title: "AIS request",
    shortTitle: "AIS request",
    detail: "AIS posts one governed outage verification request with request_id, detected time, and redacted meter reference.",
    metric: "202 Accepted"
  },
  {
    id: "trace",
    title: "PEA trace",
    shortTitle: "PEA trace",
    detail: "PEA resolves the request into feeder and protection context without exposing customer identity.",
    metric: "Grid context"
  },
  {
    id: "evidence",
    title: "Protection evidence",
    shortTitle: "Evidence",
    detail: "Device action and operator evidence are checked before cause or ETR is treated as usable.",
    metric: "Shadow evidence"
  },
  {
    id: "cause",
    title: "Cause",
    shortTitle: "Cause",
    detail: "Cause is shown as candidate context only until evidence is complete and owner-approved.",
    metric: "Candidate only"
  },
  {
    id: "etr",
    title: "ETR candidate",
    shortTitle: "ETR",
    detail: "ETR remains a candidate while AIS outage/restore stays the customer-facing truth source.",
    metric: "production_send = blocked"
  },
  {
    id: "shadow",
    title: "Shadow response",
    shortTitle: "Shadow",
    detail: "Response is recorded for review and callback audit. No Auto ETR production send is enabled.",
    metric: "Operator review"
  }
];

const manualWorkflow = [
  "Phone call starts with repeated site/time",
  "PEA searches grid context by hand",
  "Cause and ETR are relayed verbally",
  "Notes become the audit trail"
];

const apiWorkflow = [
  "AIS sends one governed request_id",
  "PEA stores redacted request evidence",
  "Trace links protection and cause context",
  "Shadow response becomes queryable"
];

const guardrails = [
  "mode = shadow",
  "production_send = blocked",
  "Auto ETR not enabled",
  "callback dry-run only",
  "AIS outage/restore stays truth"
];

const executiveBeats = [
  { label: "Manual", value: "Call + notes", note: "slow, variable audit" },
  { label: "API", value: "One request", note: "repeatable evidence chain" },
  { label: "Pilot", value: "Shadow only", note: "no customer auto-send" }
];

export function MissionControl({ initialData }: { initialData: OperatorData }) {
  const [activeStep, setActiveStep] = useState(0);
  const latest = initialData.items?.[0];
  const counts = useMemo(() => summarize(initialData.items || []), [initialData.items]);
  const story = useMemo(() => buildTraceStory(latest), [latest]);
  const step = missionSteps[activeStep];
  const mvp = initialData.mvp;
  const green = mvp?.green_gate || {};
  const queues = mvp?.owner_queues || {};
  const ops = mvp?.ops_controls || {};
  const readiness = mvp?.readiness || {};

  return (
    <main className="shell">
      <header className="topbar" aria-label="demo status">
        <div>
          <span>PEA API Intellisense</span>
          <strong>AIS ETR executive demo</strong>
        </div>
        <div className="topbar-status">
          <span>Shadow pilot</span>
          <span>Recording-ready demo</span>
          <span>Thai context: สาธิตเท่านั้น</span>
        </div>
      </header>

      <section className="demo-stage" aria-labelledby="page-title">
        <div className="stage-copy">
          <div>
            <p className="eyebrow">PEA x AIS shadow demo</p>
            <h1 id="page-title">From phone call to governed API ETR trace</h1>
            <p className="lede">Demo path: AIS request &rarr; PEA trace &rarr; protection evidence &rarr; cause &rarr; ETR candidate &rarr; shadow response. Customer-facing truth remains AIS outage/restore.</p>
          </div>
          <div className="beat-row" aria-label="executive demo beats">
            {executiveBeats.map((item) => (
              <div className="beat" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <em>{item.note}</em>
              </div>
            ))}
          </div>
          <div className="guardrail-strip" aria-label="shadow guardrails">
            {guardrails.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </div>

        <div className="workflow-compare" aria-label="manual workflow compared with api workflow">
          <WorkflowLane title="Manual phone-call workflow" label="Current" tone="manual" items={manualWorkflow} />
          <WorkflowLane title="API workflow" label="Shadow demo" tone="api" items={apiWorkflow} />
        </div>

        <div className="trace-card" aria-label="six step api trace">
          <div className="panel-head row">
            <div>
              <p className="eyebrow">Governed trace</p>
              <h2>{latest?.request_id || "Waiting for AIS request"}</h2>
            </div>
            <span className="source">{initialData.source || "live API when configured"}</span>
          </div>
          <div className="flow-line" role="tablist" aria-label="AIS request to shadow response">
            {missionSteps.map((item, index) => (
              <button
                key={item.id}
                className={index === activeStep ? "flow-step active" : "flow-step"}
                onClick={() => setActiveStep(index)}
                type="button"
                aria-selected={index === activeStep}
              >
                <span>{index + 1}</span>
                <strong>{item.shortTitle}</strong>
              </button>
            ))}
          </div>
          <div className="selected-step">
            <span>{step.metric}</span>
            <strong>{step.title}</strong>
            <p>{step.detail}</p>
          </div>
          <div className="shadow-preview" aria-label="shadow response summary">
            <div>
              <span>Request</span>
              <strong>{latest?.request_id || "AIS request pending"}</strong>
              <em>{story[0].body}</em>
            </div>
            <div>
              <span>Candidate</span>
              <strong>{story[4].body}</strong>
              <em>{story[3].body}</em>
            </div>
            <div>
              <span>Send gate</span>
              <strong>Blocked</strong>
              <em>{story[5].body}</em>
            </div>
          </div>
        </div>
      </section>

      <section className="metric-row" aria-label="shadow run metrics">
        <Metric label="Inbound requests" value={String(initialData.metrics?.total_requests ?? counts.total)} note="redacted store" />
        <Metric label="Real AIS hits" value={String(counts.real)} note="excludes smoke IDs" />
        <Metric label="ETR candidate" value={formatEtrMetricValue(latest)} note={formatEtrMetricNote(latest)} />
        <Metric label="Production sends" value="0" note="blocked by design" />
        <Metric label="Dry-run outbox" value={String(initialData.metrics?.outbox_dry_run_held ?? counts.outboxHeld)} note="no network send" />
      </section>

      <section className="panel mvp-panel" aria-labelledby="mvp-gate-title">
        <div className="panel-head row">
          <div>
            <p className="eyebrow">Production gate MVP</p>
            <h2 id="mvp-gate-title">What can move today without waiting</h2>
          </div>
          <span className="source">Auto ETR remains blocked</span>
        </div>
        <div className="mvp-grid" aria-label="production gate and owner evidence work">
          <GateCard
            tone="blocked"
            label="Green gate"
            value={`${green.green_rows ?? 0}/${green.min_green_rows ?? 30}`}
            detail={`${green.additional_green_rows_needed ?? 30} more validated green rows needed`}
          />
          <GateCard
            tone="ready"
            label="AIS truth queue"
            value={String(queues.ais_truth_owner_rows ?? 30)}
            detail="active outage confirmation rows ready for AIS owner"
          />
          <GateCard
            tone="ready"
            label="PEA topology queue"
            value={String(queues.pea_topology_owner_rows ?? 30)}
            detail="downstream protection approval rows ready for PEA owner"
          />
          <GateCard
            tone="blocked"
            label="Ops drill"
            value={formatShortStatus(ops.backup_restore_drill)}
            detail={formatMissingList(ops.missing_tools, "missing local PostgreSQL tools")}
          />
        </div>
        <div className="mvp-status-row" aria-label="production readiness split">
          <StatusChip label="Cloud shadow" value={readiness.cloud_endpoint_ready || "READY_FOR_DEPLOYMENT_PACKAGE"} />
          <StatusChip label="Production infra" value={readiness.production_infra_ready || "BLOCKED_PENDING_OWNER_OR_CONTROL"} />
          <StatusChip label="Auto ETR" value={readiness.auto_etr_ready || "BLOCKED_GREEN_GATE"} />
          <StatusChip label="Key rotation" value={ops.key_rotation_drill || "DEFER_UNTIL_FIRST_REAL_AIS_HIT"} />
        </div>
      </section>

      <section className="panel trace">
        <div className="panel-head row">
          <div>
          <p className="eyebrow">Request evidence chain</p>
            <h2>{latest?.request_id || "Waiting for request"}</h2>
          </div>
          <span className="source">{initialData.source || "live/postgres when configured"}</span>
        </div>
        <div className="trace-rail" aria-label="AIS request to shadow response trace">
          {story.map((node) => (
            <TraceNode key={node.title} title={node.title} body={node.body} meta={node.meta} />
          ))}
        </div>
      </section>

      <section className="grid main-grid">
        <div className="panel response">
          <div className="panel-head">
            <p className="eyebrow">Shadow response preview</p>
            <h2>Operator-visible answer, not customer auto-send</h2>
          </div>
          <div className="response-body">
            <div>
              <span>Cause</span>
              <strong>{story[3].body}</strong>
            </div>
            <div>
              <span>ETR candidate</span>
              <strong>{story[4].body}</strong>
            </div>
            <div>
              <span>Shadow response</span>
              <strong>{story[5].body}</strong>
            </div>
            <div>
              <span>Eligibility</span>
              <strong>{formatEligibility(latest)}</strong>
            </div>
            <div>
              <span>Callback outbox</span>
              <strong>{formatOutbox(latest)}</strong>
            </div>
          </div>
        </div>

        <div className="panel ask">
          <div className="panel-head">
            <p className="eyebrow">Pilot decision frame</p>
            <h2>Approve cloud shadow, not Auto ETR production</h2>
          </div>
          <ul>
            <li>Render-managed HTTPS endpoint and PostgreSQL.</li>
            <li>Named PEA/AIS API owners for pilot cutover.</li>
            <li>Green-gate evidence collection before any production ETR step.</li>
          </ul>
        </div>
      </section>

      <section className="panel table-panel">
        <div className="panel-head row">
          <div>
            <p className="eyebrow">Operator queue</p>
            <h2>Recent AIS verification requests</h2>
          </div>
          <span className="source">{initialData.count ?? initialData.items?.length ?? 0} records visible</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>request_id</th>
                <th>received_at</th>
                <th>status</th>
                <th>callback</th>
                <th>send decision</th>
                <th>outbox</th>
                <th>meter_ref</th>
                <th>production</th>
              </tr>
            </thead>
            <tbody>
              {(initialData.items || []).slice(0, 8).map((item) => (
                <tr key={item.request_id}>
                  <td>{item.request_id}</td>
                  <td>{item.received_at}</td>
                  <td>{item.status}</td>
                  <td>{item.callback_status}</td>
                  <td>{formatSendDecision(item)}</td>
                  <td>{formatOutbox(item)}</td>
                  <td>{item.meter?.last4 ? `***${item.meter.last4}` : "redacted"}</td>
                  <td>{item.production_send}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function WorkflowLane({
  title,
  label,
  tone,
  items
}: {
  title: string;
  label: string;
  tone: "manual" | "api";
  items: string[];
}) {
  return (
    <section className={`workflow-lane ${tone}`} aria-labelledby={`${tone}-workflow`}>
      <div className="lane-head">
        <span>{label}</span>
        <h2 id={`${tone}-workflow`}>{title}</h2>
      </div>
      <ol>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ol>
    </section>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{note}</em>
    </div>
  );
}

function TraceNode({ title, body, meta }: { title: string; body: string; meta: string }) {
  return (
    <div className="trace-node">
      <span>{title}</span>
      <strong>{body}</strong>
      <em>{meta}</em>
    </div>
  );
}

function GateCard({
  label,
  value,
  detail,
  tone
}: {
  label: string;
  value: string;
  detail: string;
  tone: "ready" | "blocked";
}) {
  return (
    <div className={`gate-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-chip">
      <span>{label}</span>
      <strong>{formatShortStatus(value)}</strong>
    </div>
  );
}

function summarize(items: OperatorItem[]) {
  return {
    total: items.length,
    real: items.filter((item) => !item.request_id.includes("SMOKE") && !item.request_id.includes("DEMO")).length,
    outboxHeld: items.filter((item) => item.callback_outbox?.status === "DRY_RUN_HELD").length
  };
}

function buildTraceStory(latest?: OperatorItem) {
  const evidence = latest?.result?.evidence;
  const distribution = latest?.result?.pea_distribution;
  const evidenceReason = evidence?.reason || "worker pending";
  const evidenceReady =
    evidence?.match_found === true || !/pending|no_evidence|cloud_shadow|duplicate|already_received/i.test(evidenceReason);
  const callback = latest?.callback_status === "SKIPPED_DUPLICATE" ? "duplicate captured; no resend" : "captured for audit";
  const feeder = evidence?.feeder ? `feeder ${evidence.feeder}` : "feeder pending";
  const protection = evidence?.device_id ? `${evidence.device_type || "Device"} ${evidence.device_id}` : evidenceReason;
  const protectionMeta =
    typeof evidence?.time_delta_minutes === "number"
      ? `${formatTimestamp(evidence.event_time)}; ${evidence.time_delta_minutes} min from AIS timestamp`
      : evidenceReady
        ? "evidence available"
        : "evidence gate not green";
  const cause = distribution?.cause_lane
    ? `shadow lane: ${formatCauseLane(distribution.cause_lane)}`
    : evidenceReady
      ? "candidate cause ready for owner review"
      : "cause held pending evidence";

  return [
    {
      title: "AIS request",
      body: formatTimestamp(latest?.detected_at) || "No live timestamp yet",
      meta: latest?.request_id || "request_id pending"
    },
    {
      title: "PEA trace",
      body: latest?.meter?.last4 ? `redacted meter ref ending ${latest.meter.last4}; ${feeder}` : `redacted meter reference; ${feeder}`,
      meta: "customer identity hidden"
    },
    {
      title: "Protection evidence",
      body: protection,
      meta: protectionMeta
    },
    {
      title: "Cause",
      body: cause,
      meta: "not customer-facing truth"
    },
    {
      title: "ETR candidate",
      body: formatEtrCandidate(latest),
      meta: latest?.result?.etr?.production_gate || "candidate only"
    },
    {
      title: "Shadow response",
      body: `${callback}; ${formatSendDecision(latest)}`,
      meta: formatOutbox(latest)
    }
  ];
}

function formatCauseLane(value: string) {
  return value.replace(/_/g, " ");
}

function formatEtrMetricValue(item?: OperatorItem) {
  const p50 = item?.result?.etr?.etr_minutes_p50;
  return typeof p50 === "number" ? `${p50} min` : item?.etr_status || "blocked";
}

function formatEtrMetricNote(item?: OperatorItem) {
  const etr = item?.result?.etr;
  if (typeof etr?.q10 === "number" && typeof etr.q90 === "number") {
    return `shadow P50; ${etr.q10}-${etr.q90} min band`;
  }
  return "shadow only";
}

function formatEtrCandidate(item?: OperatorItem) {
  const etr = item?.result?.etr;
  if (typeof etr?.etr_minutes_p50 === "number") {
    const band =
      typeof etr.q10 === "number" && typeof etr.q90 === "number" ? ` (${etr.q10}-${etr.q90} min band)` : "";
    return `${etr.etr_minutes_p50} min P50${band}`;
  }
  return item?.etr_status || "NOT_READY_FOR_AUTO_SEND";
}

function formatEligibility(item?: OperatorItem) {
  return item?.send_control?.eligibility_status || "red_blocked";
}

function formatSendDecision(item?: OperatorItem) {
  const decision = item?.send_control?.decision || "blocked";
  const mode = item?.send_control?.effective_mode || "blocked";
  return `${decision} (${mode})`;
}

function formatOutbox(item?: OperatorItem) {
  const outbox = item?.callback_outbox;
  if (!outbox?.status) {
    return "not queued";
  }
  const attempts = typeof outbox.attempts === "number" ? `; attempts ${outbox.attempts}` : "";
  return `${outbox.status}; ${outbox.transport || "dry_run"}${attempts}`;
}

function formatShortStatus(value?: string) {
  if (!value) {
    return "pending";
  }
  return value.replace(/_/g, " ").toLowerCase();
}

function formatMissingList(values?: string[], fallback = "no blocker reported") {
  if (!values || values.length === 0) {
    return fallback;
  }
  return values.join(", ");
}

function formatTimestamp(value?: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Bangkok",
    timeZoneName: "short"
  }).format(date);
}
