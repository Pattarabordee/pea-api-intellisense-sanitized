"use client";

import { useMemo, useState } from "react";
import type { OperatorData, OperatorItem } from "../lib/demo-data";

const missionSteps = [
  {
    id: "ais",
    title: "AIS sends outage signal",
    detail: "AIS posts request_id, meter_no, timestamp, and area context to the PEA endpoint.",
    metric: "202 Accepted"
  },
  {
    id: "trace",
    title: "PEA traces grid context",
    detail: "PEA maps the redacted meter reference to feeder and protection-device context.",
    metric: "Topology lane"
  },
  {
    id: "evidence",
    title: "Evidence gate checks device action",
    detail: "The system compares detected time with WebEx/protection evidence before any answer is trusted.",
    metric: "Shadow evidence"
  },
  {
    id: "etr",
    title: "ETR candidate stays blocked",
    detail: "ETR is generated as a candidate only. Customer-facing auto send waits for green gate and approval.",
    metric: "production_send = blocked"
  }
];

export function MissionControl({ initialData }: { initialData: OperatorData }) {
  const [activeStep, setActiveStep] = useState(0);
  const latest = initialData.items?.[0];
  const counts = useMemo(() => summarize(initialData.items || []), [initialData.items]);
  const step = missionSteps[activeStep];

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">PEA x AIS Production Cloud Shadow</p>
          <h1>Grid Intelligence Mission Control</h1>
          <p className="lede">
            Turn AIS outage calls into an auditable API workflow: receive signal, trace PEA grid context,
            check evidence, and keep ETR safely blocked until the gate passes.
          </p>
        </div>
        <div className="status-strip" aria-label="guardrails">
          <span>mode: shadow</span>
          <span>production_send: blocked</span>
          <span>Auto ETR: gated</span>
        </div>
      </section>

      <section className="grid two">
        <div className="panel mission">
          <div className="panel-head">
            <p className="eyebrow">Interactive demo</p>
            <h2>{step.title}</h2>
          </div>
          <p className="mission-detail">{step.detail}</p>
          <div className="mission-metric">{step.metric}</div>
          <div className="stepper" role="tablist" aria-label="mission steps">
            {missionSteps.map((item, index) => (
              <button
                key={item.id}
                className={index === activeStep ? "step active" : "step"}
                onClick={() => setActiveStep(index)}
                type="button"
              >
                <span>{index + 1}</span>
                {item.id}
              </button>
            ))}
          </div>
        </div>

        <div className="panel comparison">
          <div className="panel-head">
            <p className="eyebrow">Before vs API</p>
            <h2>Manual call becomes traceable data product</h2>
          </div>
          <div className="lanes">
            <div>
              <h3>Old workflow</h3>
              <p>AIS operator calls PEA, repeats site details, waits for context, then records status manually.</p>
              <strong>Slow, unstructured, hard to audit</strong>
            </div>
            <div>
              <h3>API workflow</h3>
              <p>AIS sends one request_id. PEA captures evidence, traces context, and exposes status lookup.</p>
              <strong>Fast, durable, governed</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="grid four">
        <Metric label="Inbound requests" value={String(counts.total)} note="redacted store" />
        <Metric label="Real AIS hits" value={String(counts.real)} note="excludes smoke IDs" />
        <Metric label="Latest callback" value={latest?.callback_status || "N/A"} note="shadow only" />
        <Metric label="Production sends" value="0" note="blocked by design" />
      </section>

      <section className="grid main-grid">
        <div className="panel trace">
          <div className="panel-head">
            <p className="eyebrow">Latest trace</p>
            <h2>{latest?.request_id || "Waiting for request"}</h2>
          </div>
          <div className="trace-rail">
            <TraceNode title="AIS Signal" body={latest?.detected_at || "No live timestamp yet"} />
            <TraceNode title="Meter Ref" body={latest?.meter?.last4 ? `hash + last4 ${latest.meter.last4}` : "redacted only"} />
            <TraceNode title="Evidence" body={latest?.result?.evidence?.reason || "worker pending"} />
            <TraceNode title="ETR Gate" body={latest?.etr_status || "NOT_READY_FOR_AUTO_SEND"} />
          </div>
        </div>

        <div className="panel ask">
          <div className="panel-head">
            <p className="eyebrow">CEO ask</p>
            <h2>Approve cloud shadow production path</h2>
          </div>
          <ul>
            <li>Render-managed HTTPS endpoint and PostgreSQL.</li>
            <li>Named PEA/AIS API owners for pilot cutover.</li>
            <li>Green-gate evidence collection before Auto ETR.</li>
          </ul>
        </div>
      </section>

      <section className="panel table-panel">
        <div className="panel-head row">
          <div>
            <p className="eyebrow">Operator queue</p>
            <h2>Recent AIS verification requests</h2>
          </div>
          <span className="source">{initialData.source || "live/postgres when configured"}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>request_id</th>
                <th>received_at</th>
                <th>status</th>
                <th>callback</th>
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

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{note}</em>
    </div>
  );
}

function TraceNode({ title, body }: { title: string; body: string }) {
  return (
    <div className="trace-node">
      <span>{title}</span>
      <strong>{body}</strong>
    </div>
  );
}

function summarize(items: OperatorItem[]) {
  return {
    total: items.length,
    real: items.filter((item) => !item.request_id.includes("SMOKE") && !item.request_id.includes("DEMO")).length
  };
}
