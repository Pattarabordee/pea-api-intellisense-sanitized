import { normalizeIncidentEvidenceEnvelope } from "./shadow-queue-publisher";
import type { PeaIncidentEvidence } from "./incident-priority-compose";

type UnknownRecord = Record<string, unknown>;

export type IncidentAggregateSourceEnvelope = {
  schema_version: "pea-incident-aggregate-source.v0.1";
  mode: "shadow";
  production_send: "blocked";
  authoritative_outage_truth: false;
  generated_at: string;
  source_id: string;
  items: unknown[];
};

export type IncidentEvidenceProjectionResult = {
  status: "ok" | "not_configured" | "upstream_unavailable" | "contract_invalid";
  http_status: 200 | 502 | 503;
  evidence?: {
    schema_version: "pea-incident-evidence.v1";
    mode: "shadow";
    production_send: "blocked";
    authoritative_outage_truth: false;
    generated_at: string;
    source_id: string;
    items: PeaIncidentEvidence[];
  };
  error_code?: string;
  detail: string;
};

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function timeoutMs(): number {
  const raw = Number(process.env.INCIDENT_EVIDENCE_PROJECTION_TIMEOUT_MS || "5000");
  if (!Number.isFinite(raw)) return 5000;
  return Math.min(30000, Math.max(500, Math.round(raw)));
}

async function fetchSource(url: string, apiKey: string): Promise<{ ok: boolean; status: number; body: unknown }> {
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

function normalizeAggregateSource(input: unknown): IncidentAggregateSourceEnvelope | null {
  if (!isRecord(input)) return null;
  if (input.schema_version !== "pea-incident-aggregate-source.v0.1") return null;
  if (input.mode !== "shadow" || input.production_send !== "blocked" || input.authoritative_outage_truth !== false) return null;
  if (typeof input.generated_at !== "string" || Number.isNaN(Date.parse(input.generated_at))) return null;
  if (typeof input.source_id !== "string" || !input.source_id.trim() || input.source_id.length > 120) return null;
  if (!Array.isArray(input.items) || input.items.length > 250) return null;
  return {
    schema_version: "pea-incident-aggregate-source.v0.1",
    mode: "shadow",
    production_send: "blocked",
    authoritative_outage_truth: false,
    generated_at: input.generated_at,
    source_id: input.source_id.trim(),
    items: input.items
  };
}

export function projectAggregateIncidentEvidence(input: unknown) {
  const source = normalizeAggregateSource(input);
  if (!source) return null;

  const projected = normalizeIncidentEvidenceEnvelope({
    schema_version: "pea-incident-evidence.v1",
    mode: "shadow",
    production_send: "blocked",
    authoritative_outage_truth: false,
    generated_at: source.generated_at,
    source_id: `incident-projection:${source.source_id}`,
    items: source.items
  });

  return projected;
}

export async function loadIncidentEvidenceProjection(): Promise<IncidentEvidenceProjectionResult> {
  const url = String(process.env.INCIDENT_EVIDENCE_PROJECTION_SOURCE_URL || "").trim();
  const apiKey = String(process.env.INCIDENT_EVIDENCE_PROJECTION_SOURCE_API_KEY || "").trim();

  if (!url) {
    return {
      status: "not_configured",
      http_status: 503,
      error_code: "INCIDENT_EVIDENCE_SOURCE_NOT_CONFIGURED",
      detail: "No approved read-only aggregate incident source is configured."
    };
  }

  const response = await fetchSource(url, apiKey);
  if (!response.ok) {
    return {
      status: "upstream_unavailable",
      http_status: 502,
      error_code: "INCIDENT_EVIDENCE_SOURCE_UNAVAILABLE",
      detail: response.status ? `Aggregate incident source returned HTTP ${response.status}.` : "Aggregate incident source is unreachable or timed out."
    };
  }

  const evidence = projectAggregateIncidentEvidence(response.body);
  if (!evidence) {
    return {
      status: "contract_invalid",
      http_status: 502,
      error_code: "INCIDENT_EVIDENCE_SOURCE_CONTRACT_INVALID",
      detail: "Aggregate incident source failed shadow/privacy projection validation."
    };
  }

  return {
    status: "ok",
    http_status: 200,
    evidence,
    detail: "Aggregate incident source was projected into pea-incident-evidence.v1 without adding outage truth or priority semantics."
  };
}
