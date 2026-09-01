export type PriorityAdapterStatus = "ok" | "unavailable" | "input_insufficient" | "contract_invalid";

export type PriorityAdapterQueueSignal = {
  queue_rank: number;
  transformer_id: string;
  feeder_code: string;
  event_type: string;
  event_status: string;
  priority_score: number | string | null;
  raw_priority_score: number | string | null;
  score_max: number | string | null;
  priority_level: string;
  ai_summary: string;
  source: string | null;
};

export type PriorityAdapterNormalized = {
  mode: "shadow";
  production_send: "blocked";
  purpose: "decision_support_only";
  authoritative_outage_truth: false;
  schema_version: "priority-adapter-v0.1";
  adapter_status: PriorityAdapterStatus;
  ticket_id: string;
  service_area: string;
  queue_count: number;
  queues: PriorityAdapterQueueSignal[];
  error_code?: string;
  error_message?: string;
  contract_errors?: string[];
};

type UnknownRecord = Record<string, unknown>;

const MAX_TEXT = 300;
const MAX_ID = 96;
const MAX_QUEUE_ITEMS = 100;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cleanText(value: unknown, maxLength = MAX_TEXT): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return "";
  const text = String(value).trim();
  if (!text || text.toLowerCase() === "null") return "";
  return text.slice(0, maxLength);
}

function cleanScalar(value: unknown): number | string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const text = value.trim();
    return text && text.toLowerCase() !== "null" ? text.slice(0, 64) : null;
  }
  return null;
}

function cleanRank(value: unknown, fallback: number): number {
  const rank = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(rank) || rank < 1 || rank > 100000) return fallback;
  return rank;
}

function invalidContract(errors: string[]): PriorityAdapterNormalized {
  return {
    mode: "shadow",
    production_send: "blocked",
    purpose: "decision_support_only",
    authoritative_outage_truth: false,
    schema_version: "priority-adapter-v0.1",
    adapter_status: "contract_invalid",
    ticket_id: "",
    service_area: "",
    queue_count: 0,
    queues: [],
    error_code: "PRIORITY_ADAPTER_CONTRACT_INVALID",
    contract_errors: errors
  };
}

/**
 * Normalizes the verified n8n `PEAPriorityAdapterV01` output contract for web use.
 *
 * Important: this function deliberately does NOT infer score range, thresholds,
 * priority bands, outage truth, feeder truth, or area-specific semantics.
 * Queue order comes from `queue_rank`; score fields are preserved as opaque
 * decision-support metadata because the upstream calculator is still evolving.
 */
export function normalizePriorityAdapterResponse(input: unknown): PriorityAdapterNormalized {
  if (!isRecord(input)) return invalidContract(["BODY_NOT_OBJECT"]);

  const contractErrors: string[] = [];
  if (input.mode !== "shadow") contractErrors.push("MODE_NOT_SHADOW");
  if (input.production_send !== "blocked") contractErrors.push("PRODUCTION_SEND_NOT_BLOCKED");
  if (input.purpose !== "decision_support_only") contractErrors.push("PURPOSE_NOT_DECISION_SUPPORT_ONLY");
  if (input.authoritative_outage_truth !== false) contractErrors.push("AUTHORITATIVE_OUTAGE_TRUTH_NOT_FALSE");
  if (input.schema_version !== "priority-adapter-v0.1") contractErrors.push("SCHEMA_VERSION_UNSUPPORTED");

  if (contractErrors.length > 0) return invalidContract(contractErrors);

  const upstreamStatus = cleanText(input.adapter_status, 40);
  if (!(["ok", "unavailable", "input_insufficient"] as const).includes(upstreamStatus as "ok" | "unavailable" | "input_insufficient")) {
    return invalidContract(["ADAPTER_STATUS_UNSUPPORTED"]);
  }

  const adapterStatus = upstreamStatus as "ok" | "unavailable" | "input_insufficient";
  const ticketId = cleanText(input.ticket_id, MAX_ID);
  const serviceArea = cleanText(input.service_area, MAX_ID);
  const rawQueues = Array.isArray(input.queues) ? input.queues.slice(0, MAX_QUEUE_ITEMS) : [];

  const queues: PriorityAdapterQueueSignal[] = adapterStatus === "ok"
    ? rawQueues
        .filter(isRecord)
        .map((item, index) => ({
          queue_rank: cleanRank(item.queue_rank, index + 1),
          transformer_id: cleanText(item.transformer_id, MAX_ID),
          feeder_code: cleanText(item.feeder_code, MAX_ID),
          event_type: cleanText(item.event_type, 120),
          event_status: cleanText(item.event_status, 120),
          priority_score: cleanScalar(item.priority_score),
          raw_priority_score: cleanScalar(item.raw_priority_score),
          score_max: cleanScalar(item.score_max),
          priority_level: cleanText(item.priority_level, 64),
          ai_summary: cleanText(item.ai_summary, MAX_TEXT),
          source: cleanText(item.source, 120) || null
        }))
        .sort((a, b) => a.queue_rank - b.queue_rank)
    : [];

  return {
    mode: "shadow",
    production_send: "blocked",
    purpose: "decision_support_only",
    authoritative_outage_truth: false,
    schema_version: "priority-adapter-v0.1",
    adapter_status: adapterStatus,
    ticket_id: ticketId,
    service_area: serviceArea,
    queue_count: queues.length,
    queues,
    ...(adapterStatus === "ok"
      ? {}
      : {
          error_code: cleanText(input.error_code, 120) || (adapterStatus === "unavailable" ? "PRIORITY_SERVICE_UNAVAILABLE" : "PRIORITY_INPUT_INSUFFICIENT"),
          ...(cleanText(input.error_message, MAX_TEXT) ? { error_message: cleanText(input.error_message, MAX_TEXT) } : {})
        })
  };
}
