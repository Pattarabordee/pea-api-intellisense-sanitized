import { composeIncidentPrioritySnapshot, type PeaIncidentEvidence } from "./incident-priority-compose";
import type { IncidentQueueFeedEnvelope } from "./incident-queue-feed";
import { normalizePriorityAdapterResponse, type PriorityAdapterNormalized } from "./priority-adapter";

export type PublisherSourceState = "OK" | "UNAVAILABLE" | "CONTRACT_INVALID" | "NOT_CONFIGURED";

export type ShadowQueuePublisherResult = {
  status: "published" | "blocked";
  http_status: 200 | 502 | 503;
  feed?: IncidentQueueFeedEnvelope;
  source_health: {
    incident_source: PublisherSourceState;
    priority_source: PublisherSourceState;
  };
  error_code?: string;
  detail: string;
};

type UnknownRecord = Record<string, unknown>;

type IncidentEvidenceEnvelope = {
  schema_version: "pea-incident-evidence.v1";
  mode: "shadow";
  production_send: "blocked";
  authoritative_outage_truth: false;
  generated_at: string;
  source_id: string;
  items: PeaIncidentEvidence[];
};

const AREA = new Set(["BKN", "PKN"]);
const EVIDENCE = new Set(["STRONG", "MODERATE", "LIMITED"]);
const STATUS = new Set(["NEW", "ACKNOWLEDGED", "DISPATCHED", "IN_PROGRESS", "RESTORED"]);
const FORBIDDEN_ITEM_KEYS = new Set([
  "customer_name",
  "customer_phone",
  "phone",
  "mobile",
  "email",
  "meter_no",
  "meter_number",
  "peano",
  "raw_message",
  "raw_text",
  "chatinput",
  "coordinates",
  "lat",
  "lon",
  "latitude",
  "longitude"
]);
const SENSITIVE_TEXT = /(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|(?<!\d)\d{9,}(?!\d))/i;
const MAX_INCIDENTS = 250;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, max = 600): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned ? cleaned.slice(0, max) : null;
}

function safeText(value: unknown, max = 600): string | null {
  const cleaned = text(value, max);
  if (!cleaned || SENSITIVE_TEXT.test(cleaned)) return null;
  return cleaned;
}

function nonNegativeInt(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function safeStringArray(value: unknown, maxItems = 24): string[] | null {
  if (!Array.isArray(value) || value.length > maxItems) return null;
  const result: string[] = [];
  for (const entry of value) {
    const cleaned = safeText(entry, 300);
    if (!cleaned) return null;
    result.push(cleaned);
  }
  return result;
}

function containsForbiddenKeys(item: UnknownRecord): boolean {
  return Object.keys(item).some((key) => FORBIDDEN_ITEM_KEYS.has(key.trim().toLowerCase()));
}

function normalizeIncidentEvidenceItem(input: unknown): PeaIncidentEvidence | null {
  if (!isRecord(input) || containsForbiddenKeys(input)) return null;

  const incidentId = text(input.incident_id, 96);
  const area = text(input.area, 8);
  const areaLabel = safeText(input.area_label, 80);
  const transformerId = text(input.transformer_id, 96);
  const feederId = text(input.feeder_id, 96);
  const affectedCustomers = nonNegativeInt(input.affected_customers);
  const criticalRisk = safeText(input.critical_customer_risk, 300);
  const evidenceStrength = text(input.evidence_strength, 32);
  const firstReportedAt = text(input.first_reported_at, 64);
  const waitingMinutes = nonNegativeInt(input.waiting_minutes);
  const status = text(input.status, 32);
  const eventType = safeText(input.event_type, 120);
  const aiSummary = input.ai_summary === undefined ? undefined : safeText(input.ai_summary, 600);
  const priorityReasons = input.priority_reasons === undefined ? undefined : safeStringArray(input.priority_reasons);
  const evidenceChain = input.evidence_chain === undefined ? undefined : safeStringArray(input.evidence_chain);

  if (!incidentId || !area || !AREA.has(area) || !areaLabel || !transformerId || !feederId) return null;
  if (affectedCustomers === null || !criticalRisk || !evidenceStrength || !EVIDENCE.has(evidenceStrength)) return null;
  if (!firstReportedAt || Number.isNaN(Date.parse(firstReportedAt)) || waitingMinutes === null) return null;
  if (!status || !STATUS.has(status) || !eventType) return null;
  if (input.ai_summary !== undefined && !aiSummary) return null;
  if (input.priority_reasons !== undefined && !priorityReasons) return null;
  if (input.evidence_chain !== undefined && !evidenceChain) return null;

  return {
    incident_id: incidentId,
    area: area as PeaIncidentEvidence["area"],
    area_label: areaLabel,
    transformer_id: transformerId,
    feeder_id: feederId,
    affected_customers: affectedCustomers,
    critical_customer_risk: criticalRisk,
    evidence_strength: evidenceStrength as PeaIncidentEvidence["evidence_strength"],
    first_reported_at: firstReportedAt,
    waiting_minutes: waitingMinutes,
    status: status as PeaIncidentEvidence["status"],
    event_type: eventType,
    ...(aiSummary ? { ai_summary: aiSummary } : {}),
    ...(priorityReasons ? { priority_reasons: priorityReasons } : {}),
    ...(evidenceChain ? { evidence_chain: evidenceChain } : {})
  };
}

export function normalizeIncidentEvidenceEnvelope(input: unknown): IncidentEvidenceEnvelope | null {
  if (!isRecord(input)) return null;
  if (input.schema_version !== "pea-incident-evidence.v1") return null;
  if (input.mode !== "shadow" || input.production_send !== "blocked" || input.authoritative_outage_truth !== false) return null;

  const generatedAt = text(input.generated_at, 64);
  const sourceId = text(input.source_id, 120);
  if (!generatedAt || Number.isNaN(Date.parse(generatedAt)) || !sourceId) return null;
  if (!Array.isArray(input.items) || input.items.length > MAX_INCIDENTS) return null;

  const items: PeaIncidentEvidence[] = [];
  const seen = new Set<string>();
  for (const raw of input.items) {
    const item = normalizeIncidentEvidenceItem(raw);
    if (!item || seen.has(item.incident_id)) return null;
    seen.add(item.incident_id);
    items.push(item);
  }

  return {
    schema_version: "pea-incident-evidence.v1",
    mode: "shadow",
    production_send: "blocked",
    authoritative_outage_truth: false,
    generated_at: generatedAt,
    source_id: sourceId,
    items
  };
}

function timeoutMs(): number {
  const raw = Number(process.env.SHADOW_QUEUE_PUBLISH_TIMEOUT_MS || "5000");
  if (!Number.isFinite(raw)) return 5000;
  return Math.min(30000, Math.max(500, Math.round(raw)));
}

async function fetchJson(url: string, apiKey: string): Promise<{ ok: boolean; status: number; body: unknown }> {
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (apiKey) headers["X-API-Key"] = apiKey;
    const response = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(timeoutMs())
    });
    return { ok: response.ok, status: response.status, body: await response.json().catch(() => null) };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

function unavailablePriority(serviceArea = ""): PriorityAdapterNormalized {
  return {
    mode: "shadow",
    production_send: "blocked",
    purpose: "decision_support_only",
    authoritative_outage_truth: false,
    schema_version: "priority-adapter-v0.1",
    adapter_status: "unavailable",
    ticket_id: "",
    service_area: serviceArea,
    queue_count: 0,
    queues: [],
    error_code: "PRIORITY_SERVICE_UNAVAILABLE"
  };
}

export async function publishShadowIncidentQueue(): Promise<ShadowQueuePublisherResult> {
  const incidentUrl = String(process.env.SHADOW_QUEUE_INCIDENT_SOURCE_URL || "").trim();
  const priorityUrl = String(process.env.SHADOW_QUEUE_PRIORITY_SOURCE_URL || "").trim();
  const incidentKey = String(process.env.SHADOW_QUEUE_INCIDENT_SOURCE_API_KEY || "").trim();
  const priorityKey = String(process.env.SHADOW_QUEUE_PRIORITY_SOURCE_API_KEY || "").trim();

  if (!incidentUrl) {
    return {
      status: "blocked",
      http_status: 503,
      source_health: { incident_source: "NOT_CONFIGURED", priority_source: priorityUrl ? "OK" : "NOT_CONFIGURED" },
      error_code: "INCIDENT_SOURCE_NOT_CONFIGURED",
      detail: "Read-only incident evidence source is required before a live shadow feed can be published."
    };
  }

  const [incidentResponse, priorityResponse] = await Promise.all([
    fetchJson(incidentUrl, incidentKey),
    priorityUrl ? fetchJson(priorityUrl, priorityKey) : Promise.resolve({ ok: false, status: 0, body: null })
  ]);

  if (!incidentResponse.ok) {
    return {
      status: "blocked",
      http_status: 502,
      source_health: { incident_source: "UNAVAILABLE", priority_source: priorityUrl ? "UNAVAILABLE" : "NOT_CONFIGURED" },
      error_code: "INCIDENT_SOURCE_UNAVAILABLE",
      detail: incidentResponse.status ? `Incident source returned HTTP ${incidentResponse.status}.` : "Incident source is unreachable or timed out."
    };
  }

  const incidents = normalizeIncidentEvidenceEnvelope(incidentResponse.body);
  if (!incidents) {
    return {
      status: "blocked",
      http_status: 502,
      source_health: { incident_source: "CONTRACT_INVALID", priority_source: priorityUrl ? "UNAVAILABLE" : "NOT_CONFIGURED" },
      error_code: "INCIDENT_SOURCE_CONTRACT_INVALID",
      detail: "Incident evidence source failed strict shadow/privacy contract validation."
    };
  }

  let priorityState: PublisherSourceState = "NOT_CONFIGURED";
  let priority = unavailablePriority();
  if (priorityUrl) {
    if (!priorityResponse.ok) {
      priorityState = "UNAVAILABLE";
    } else {
      const normalized = normalizePriorityAdapterResponse(priorityResponse.body);
      if (normalized.adapter_status === "contract_invalid") {
        priorityState = "CONTRACT_INVALID";
      } else {
        priorityState = normalized.adapter_status === "unavailable" ? "UNAVAILABLE" : "OK";
        priority = normalized;
      }
    }
  }

  const composed = composeIncidentPrioritySnapshot(priority, incidents.items);
  const now = new Date().toISOString();
  const feed: IncidentQueueFeedEnvelope = {
    schema_version: "incident-queue-feed.v1",
    mode: "shadow",
    production_send: "blocked",
    authoritative_outage_truth: false,
    generated_at: now,
    source_id: `shadow-publisher:${incidents.source_id}`,
    upstream_health: {
      incident_source: "OK",
      priority_source: priorityState
    },
    snapshot: composed.snapshot
  };

  return {
    status: "published",
    http_status: 200,
    feed,
    source_health: {
      incident_source: "OK",
      priority_source: priorityState
    },
    detail: priorityState === "OK"
      ? "Incident evidence and priority decision-support were composed into a read-only shadow feed."
      : "Incident evidence was published with UNRATED priority because the priority source is not safely usable."
  };
}
