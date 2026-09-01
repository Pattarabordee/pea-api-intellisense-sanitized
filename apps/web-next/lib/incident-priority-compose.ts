import type { IncidentPriorityItem, IncidentPrioritySnapshot, PriorityLevel } from "./incident-priority";
import type { PriorityAdapterNormalized, PriorityAdapterQueueSignal } from "./priority-adapter";

export type PeaIncidentEvidence = {
  incident_id: string;
  area: "BKN" | "PKN";
  area_label: string;
  transformer_id: string | null;
  feeder_id: string | null;
  affected_customers: number | null;
  report_count?: number;
  critical_customer_risk: string;
  evidence_strength: "STRONG" | "MODERATE" | "LIMITED";
  first_reported_at: string;
  waiting_minutes: number;
  status: "NEW" | "ACKNOWLEDGED" | "DISPATCHED" | "IN_PROGRESS" | "RESTORED";
  event_type: string;
  ai_summary?: string;
  priority_reasons?: string[];
  evidence_chain?: string[];
};

export type ComposeResult = {
  snapshot: IncidentPrioritySnapshot;
  adapter_status: PriorityAdapterNormalized["adapter_status"];
  matched_signal_count: number;
  unmatched_signal_count: number;
  unmatched_incident_count: number;
  warnings: string[];
};

const KNOWN_LEVELS = new Set<PriorityLevel>(["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNRATED"]);

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function priorityLevel(value: string): PriorityLevel {
  const normalized = value.trim().toUpperCase() as PriorityLevel;
  return KNOWN_LEVELS.has(normalized) ? normalized : "UNRATED";
}

function sameArea(adapterArea: string, incidentArea: PeaIncidentEvidence["area"]): boolean {
  if (!adapterArea.trim()) return true;
  return adapterArea.trim().toUpperCase() === incidentArea;
}

function activeRank(item: IncidentPriorityItem): number {
  if (typeof item.queue_rank === "number" && Number.isFinite(item.queue_rank)) return item.queue_rank;
  return Number.MAX_SAFE_INTEGER;
}

function numericScore(item: IncidentPriorityItem): number {
  return typeof item.priority_score === "number" && Number.isFinite(item.priority_score)
    ? item.priority_score
    : Number.NEGATIVE_INFINITY;
}

function sortItems(items: IncidentPriorityItem[]): IncidentPriorityItem[] {
  return [...items].sort((a, b) => {
    if (a.status === "RESTORED" && b.status !== "RESTORED") return 1;
    if (a.status !== "RESTORED" && b.status === "RESTORED") return -1;
    if (a.area !== b.area) return a.area.localeCompare(b.area);
    const rankDiff = activeRank(a) - activeRank(b);
    if (rankDiff !== 0) return rankDiff;
    return numericScore(b) - numericScore(a);
  });
}

function signalFacts(signal: PriorityAdapterQueueSignal): string[] {
  const facts = [`Priority Adapter queue rank ${signal.queue_rank}`];
  const score = finiteNumber(signal.priority_score);
  const scoreMax = finiteNumber(signal.score_max);
  if (score !== null) facts.push(scoreMax !== null ? `Priority score observed ${score}/${scoreMax}` : `Priority score observed ${score}`);
  if (signal.priority_level) facts.push(`Priority level observed ${signal.priority_level}`);
  return facts;
}

function composeMatched(incident: PeaIncidentEvidence, signal: PriorityAdapterQueueSignal): IncidentPriorityItem {
  const score = finiteNumber(signal.priority_score);
  const scoreMax = finiteNumber(signal.score_max);
  const reasons = [...(incident.priority_reasons ?? [])];
  if (signal.ai_summary) reasons.push(signal.ai_summary);

  const evidenceChain = [...(incident.evidence_chain ?? []), ...signalFacts(signal)];

  return {
    incident_id: incident.incident_id,
    area: incident.area,
    area_label: incident.area_label,
    queue_rank: signal.queue_rank,
    priority_score: score,
    raw_priority_score: signal.raw_priority_score,
    score_max: scoreMax,
    priority_level: priorityLevel(signal.priority_level),
    priority_state: "AVAILABLE",
    event_type: incident.event_type || signal.event_type,
    transformer_id: incident.transformer_id,
    feeder_id: incident.feeder_id || signal.feeder_code || null,
    affected_customers: incident.affected_customers,
    ...(incident.report_count === undefined ? {} : { report_count: incident.report_count }),
    critical_customer_risk: incident.critical_customer_risk,
    evidence_strength: incident.evidence_strength,
    first_reported_at: incident.first_reported_at,
    waiting_minutes: incident.waiting_minutes,
    status: incident.status,
    ai_summary: signal.ai_summary || incident.ai_summary || "Priority signal available; operator review required.",
    priority_reasons: reasons,
    evidence_chain: evidenceChain,
    source_mode: "PRIORITY_ADAPTER"
  };
}

function composeUnrated(incident: PeaIncidentEvidence, state: IncidentPriorityItem["priority_state"]): IncidentPriorityItem {
  return {
    incident_id: incident.incident_id,
    area: incident.area,
    area_label: incident.area_label,
    priority_score: null,
    raw_priority_score: null,
    score_max: null,
    priority_level: "UNRATED",
    priority_state: state,
    event_type: incident.event_type,
    transformer_id: incident.transformer_id,
    feeder_id: incident.feeder_id,
    affected_customers: incident.affected_customers,
    ...(incident.report_count === undefined ? {} : { report_count: incident.report_count }),
    critical_customer_risk: incident.critical_customer_risk,
    evidence_strength: incident.evidence_strength,
    first_reported_at: incident.first_reported_at,
    waiting_minutes: incident.waiting_minutes,
    status: incident.status,
    ai_summary: incident.ai_summary || "Priority signal unavailable; preserve incident for operator review without inventing a score.",
    priority_reasons: incident.priority_reasons ?? [],
    evidence_chain: incident.evidence_chain ?? [],
    source_mode: "PRIORITY_ADAPTER"
  };
}

export function composeIncidentPrioritySnapshot(
  priority: PriorityAdapterNormalized,
  incidents: PeaIncidentEvidence[],
  generatedAt = new Date().toISOString()
): ComposeResult {
  const warnings: string[] = [];
  const transformerMap = new Map<string, PeaIncidentEvidence[]>();
  for (const incident of incidents) {
    const transformer = incident.transformer_id?.trim() || "";
    if (!transformer) continue;
    const group = transformerMap.get(transformer) ?? [];
    group.push(incident);
    transformerMap.set(transformer, group);
  }

  const matches = new Map<string, PriorityAdapterQueueSignal>();
  let unmatchedSignalCount = 0;

  if (priority.adapter_status === "ok") {
    for (const signal of priority.queues) {
      const transformer = signal.transformer_id.trim();
      if (!transformer) {
        unmatchedSignalCount += 1;
        warnings.push(`QUEUE_${signal.queue_rank}_TRANSFORMER_MISSING`);
        continue;
      }
      const candidates = (transformerMap.get(transformer) ?? []).filter((incident) => sameArea(priority.service_area, incident.area));
      if (candidates.length !== 1) {
        unmatchedSignalCount += 1;
        warnings.push(candidates.length === 0 ? `QUEUE_${signal.queue_rank}_NO_INCIDENT_MATCH` : `QUEUE_${signal.queue_rank}_AMBIGUOUS_INCIDENT_MATCH`);
        continue;
      }
      const incident = candidates[0];
      if (matches.has(incident.incident_id)) {
        unmatchedSignalCount += 1;
        warnings.push(`INCIDENT_${incident.incident_id}_MULTIPLE_PRIORITY_SIGNALS`);
        continue;
      }
      matches.set(incident.incident_id, signal);
    }
  }

  const fallbackState: IncidentPriorityItem["priority_state"] =
    priority.adapter_status === "unavailable"
      ? "UNAVAILABLE"
      : priority.adapter_status === "input_insufficient"
        ? "INPUT_INSUFFICIENT"
        : priority.adapter_status === "contract_invalid"
          ? "CONTRACT_INVALID"
          : "UNMATCHED";

  const items = incidents.map((incident) => {
    const signal = matches.get(incident.incident_id);
    return signal ? composeMatched(incident, signal) : composeUnrated(incident, fallbackState);
  });

  const sorted = sortItems(items);
  return {
    snapshot: {
      schema_version: "incident-priority.v1",
      generated_at: generatedAt,
      mode: "shadow",
      production_send: "blocked",
      source: "priority_adapter_composed",
      items: sorted
    },
    adapter_status: priority.adapter_status,
    matched_signal_count: matches.size,
    unmatched_signal_count: unmatchedSignalCount,
    unmatched_incident_count: incidents.length - matches.size,
    warnings
  };
}
