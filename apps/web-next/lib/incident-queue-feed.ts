import { incidentPriorityDemo, type IncidentPriorityItem, type IncidentPrioritySnapshot, type IncidentQueueSourceHealth } from "./incident-priority";

export type IncidentQueueFeedEnvelope = {
  schema_version: "incident-queue-feed.v1";
  mode: "shadow";
  production_send: "blocked";
  authoritative_outage_truth: false;
  generated_at: string;
  source_id: string;
  snapshot: IncidentPrioritySnapshot;
};

export type IncidentQueueFeedLoadResult = {
  snapshot: IncidentPrioritySnapshot;
  source_health: IncidentQueueSourceHealth;
};

type UnknownRecord = Record<string, unknown>;

const AREAS = new Set(["BKN", "PKN"]);
const LEVELS = new Set(["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"]);
const STATES = new Set(["AVAILABLE", "UNMATCHED", "UNAVAILABLE", "INPUT_INSUFFICIENT", "CONTRACT_INVALID"]);
const EVIDENCE = new Set(["STRONG", "MODERATE", "LIMITED"]);
const INCIDENT_STATUS = new Set(["NEW", "ACKNOWLEDGED", "DISPATCHED", "IN_PROGRESS", "RESTORED"]);
const SOURCE_MODES = new Set(["PRIORITY_ADAPTER"]);
const MAX_ITEMS = 250;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, max = 300): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  return text.slice(0, max);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return Number.isInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function positiveInteger(value: unknown): number | undefined {
  return Number.isInteger(value) && Number(value) > 0 ? Number(value) : undefined;
}

function stringArray(value: unknown, maxItems = 24): string[] | null {
  if (!Array.isArray(value) || value.length > maxItems) return null;
  const result: string[] = [];
  for (const entry of value) {
    const text = stringValue(entry, 300);
    if (text === null) return null;
    result.push(text);
  }
  return result;
}

function normalizeItem(input: unknown): IncidentPriorityItem | null {
  if (!isRecord(input)) return null;

  const incidentId = stringValue(input.incident_id, 96);
  const area = stringValue(input.area, 8);
  const areaLabel = stringValue(input.area_label, 80);
  const priorityLevel = stringValue(input.priority_level, 32);
  const eventType = stringValue(input.event_type, 120);
  const transformerId = stringValue(input.transformer_id, 96);
  const feederId = stringValue(input.feeder_id, 96);
  const criticalRisk = stringValue(input.critical_customer_risk, 300);
  const evidenceStrength = stringValue(input.evidence_strength, 32);
  const firstReportedAt = stringValue(input.first_reported_at, 64);
  const status = stringValue(input.status, 32);
  const aiSummary = stringValue(input.ai_summary, 600);
  const sourceMode = stringValue(input.source_mode, 40);
  const reasons = stringArray(input.priority_reasons);
  const evidenceChain = stringArray(input.evidence_chain);
  const affectedCustomers = nonNegativeInteger(input.affected_customers);
  const waitingMinutes = nonNegativeInteger(input.waiting_minutes);

  if (!incidentId || !area || !AREAS.has(area) || !areaLabel || !priorityLevel || !LEVELS.has(priorityLevel)) return null;
  if (!eventType || !transformerId || !feederId || !criticalRisk || !evidenceStrength || !EVIDENCE.has(evidenceStrength)) return null;
  if (!firstReportedAt || Number.isNaN(Date.parse(firstReportedAt)) || !status || !INCIDENT_STATUS.has(status)) return null;
  if (!aiSummary || !sourceMode || !SOURCE_MODES.has(sourceMode) || !reasons || !evidenceChain) return null;
  if (affectedCustomers === null || waitingMinutes === null) return null;

  const priorityScore = input.priority_score === null ? null : finiteNumber(input.priority_score);
  if (input.priority_score !== null && priorityScore === null) return null;

  const scoreMax = input.score_max === undefined || input.score_max === null ? null : finiteNumber(input.score_max);
  if (input.score_max !== undefined && input.score_max !== null && scoreMax === null) return null;

  const rawPriorityScore = input.raw_priority_score;
  if (rawPriorityScore !== undefined && rawPriorityScore !== null && typeof rawPriorityScore !== "string" && finiteNumber(rawPriorityScore) === null) return null;

  const priorityState = input.priority_state === undefined ? undefined : stringValue(input.priority_state, 40);
  if (priorityState !== undefined && (priorityState === null || !STATES.has(priorityState))) return null;

  return {
    incident_id: incidentId,
    area: area as IncidentPriorityItem["area"],
    area_label: areaLabel,
    ...(positiveInteger(input.queue_rank) ? { queue_rank: positiveInteger(input.queue_rank) } : {}),
    priority_score: priorityScore,
    ...(rawPriorityScore === undefined ? {} : { raw_priority_score: rawPriorityScore as number | string | null }),
    score_max: scoreMax,
    priority_level: priorityLevel as IncidentPriorityItem["priority_level"],
    ...(priorityState ? { priority_state: priorityState as IncidentPriorityItem["priority_state"] } : {}),
    event_type: eventType,
    transformer_id: transformerId,
    feeder_id: feederId,
    affected_customers: affectedCustomers,
    critical_customer_risk: criticalRisk,
    evidence_strength: evidenceStrength as IncidentPriorityItem["evidence_strength"],
    first_reported_at: firstReportedAt,
    waiting_minutes: waitingMinutes,
    status: status as IncidentPriorityItem["status"],
    ai_summary: aiSummary,
    priority_reasons: reasons,
    evidence_chain: evidenceChain,
    source_mode: sourceMode as IncidentPriorityItem["source_mode"]
  };
}

export function normalizeIncidentQueueFeed(input: unknown): IncidentQueueFeedEnvelope | null {
  if (!isRecord(input)) return null;
  if (input.schema_version !== "incident-queue-feed.v1") return null;
  if (input.mode !== "shadow" || input.production_send !== "blocked" || input.authoritative_outage_truth !== false) return null;

  const generatedAt = stringValue(input.generated_at, 64);
  const sourceId = stringValue(input.source_id, 120);
  if (!generatedAt || Number.isNaN(Date.parse(generatedAt)) || !sourceId) return null;
  if (!isRecord(input.snapshot)) return null;

  const snapshot = input.snapshot;
  if (snapshot.schema_version !== "incident-priority.v1" || snapshot.mode !== "shadow" || snapshot.production_send !== "blocked") return null;
  if (snapshot.source !== "priority_adapter_composed") return null;
  const snapshotGeneratedAt = stringValue(snapshot.generated_at, 64);
  if (!snapshotGeneratedAt || Number.isNaN(Date.parse(snapshotGeneratedAt))) return null;
  if (!Array.isArray(snapshot.items) || snapshot.items.length > MAX_ITEMS) return null;

  const items: IncidentPriorityItem[] = [];
  const seen = new Set<string>();
  for (const raw of snapshot.items) {
    const item = normalizeItem(raw);
    if (!item || seen.has(item.incident_id)) return null;
    seen.add(item.incident_id);
    items.push(item);
  }

  return {
    schema_version: "incident-queue-feed.v1",
    mode: "shadow",
    production_send: "blocked",
    authoritative_outage_truth: false,
    generated_at: generatedAt,
    source_id: sourceId,
    snapshot: {
      schema_version: "incident-priority.v1",
      generated_at: snapshotGeneratedAt,
      mode: "shadow",
      production_send: "blocked",
      source: "priority_adapter_composed",
      items
    }
  };
}

function fallback(status: IncidentQueueSourceHealth["status"], detail: string, checkedAt: string): IncidentQueueFeedLoadResult {
  return {
    snapshot: incidentPriorityDemo,
    source_health: {
      status,
      checked_at: checkedAt,
      source_label: "synthetic fallback",
      fallback_active: true,
      detail
    }
  };
}

function timeoutMs(): number {
  const raw = Number(process.env.INCIDENT_QUEUE_FEED_TIMEOUT_MS || "5000");
  if (!Number.isFinite(raw)) return 5000;
  return Math.min(30000, Math.max(500, Math.round(raw)));
}

export async function loadIncidentQueueFeed(): Promise<IncidentQueueFeedLoadResult> {
  const checkedAt = new Date().toISOString();
  const url = String(process.env.INCIDENT_QUEUE_FEED_URL || "").trim();
  if (!url) return fallback("NOT_CONFIGURED", "Approved read-only shadow feed is not configured.", checkedAt);

  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    const apiKey = String(process.env.INCIDENT_QUEUE_FEED_API_KEY || "").trim();
    if (apiKey) headers["X-API-Key"] = apiKey;

    const response = await fetch(url, {
      method: "GET",
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(timeoutMs())
    });

    if (!response.ok) {
      return fallback("UPSTREAM_UNAVAILABLE", `Shadow feed returned HTTP ${response.status}.`, checkedAt);
    }

    const body = await response.json().catch(() => null);
    const normalized = normalizeIncidentQueueFeed(body);
    if (!normalized) return fallback("CONTRACT_INVALID", "Shadow feed contract validation failed closed.", checkedAt);

    return {
      snapshot: normalized.snapshot,
      source_health: {
        status: "LIVE_SHADOW",
        checked_at: checkedAt,
        source_label: normalized.source_id,
        fallback_active: false,
        detail: "Read-only shadow queue feed is healthy."
      }
    };
  } catch {
    return fallback("UPSTREAM_UNAVAILABLE", "Shadow feed is unreachable or timed out.", checkedAt);
  }
}
