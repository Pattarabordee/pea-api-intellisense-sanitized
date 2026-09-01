import { normalizePriorityAdapterResponse, type PriorityAdapterNormalized } from "./priority-adapter";

export type PrioritySnapshotArea = "BKN" | "PKN";

export type PrioritySnapshotWrapperResult = {
  status: "ok" | "not_configured" | "upstream_unavailable" | "contract_invalid" | "stale";
  http_status: 200 | 502 | 503;
  snapshot?: PriorityAdapterNormalized;
  error_code?: string;
  detail: string;
};

type UnknownRecord = Record<string, unknown>;

const FINAL_NODE_NAMES = ["Normalize Priority Result", "Priority Unavailable", "Priority Input Insufficient"] as const;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function timeoutMs(): number {
  const raw = Number(process.env.PRIORITY_SNAPSHOT_TIMEOUT_MS || "5000");
  if (!Number.isFinite(raw)) return 5000;
  return Math.min(30000, Math.max(500, Math.round(raw)));
}

function maxAgeMs(): number {
  const raw = Number(process.env.PRIORITY_SNAPSHOT_MAX_AGE_MS || "900000");
  if (!Number.isFinite(raw)) return 900000;
  return Math.min(24 * 60 * 60 * 1000, Math.max(60_000, Math.round(raw)));
}

function sourceConfig(area: PrioritySnapshotArea): { url: string; apiKey: string } {
  return {
    url: String(process.env[`PRIORITY_SNAPSHOT_${area}_SOURCE_URL`] || "").trim(),
    apiKey: String(process.env[`PRIORITY_SNAPSHOT_${area}_SOURCE_API_KEY`] || process.env.PRIORITY_SNAPSHOT_SOURCE_API_KEY || "").trim()
  };
}

function n8nConfig(): { baseUrl: string; apiKey: string; workflowId: string } {
  return {
    baseUrl: String(process.env.N8N_PRIORITY_READ_BASE_URL || "").trim().replace(/\/+$/, ""),
    apiKey: String(process.env.N8N_PRIORITY_READ_API_KEY || "").trim(),
    workflowId: String(process.env.N8N_PRIORITY_WORKFLOW_ID || "PEAPriorityAdapterV01").trim()
  };
}

async function fetchSource(url: string, apiKey: string, headerName = "X-API-Key"): Promise<{ ok: boolean; status: number; body: unknown }> {
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (apiKey) headers[headerName] = apiKey;
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

function areaMismatch(area: PrioritySnapshotArea, snapshot: PriorityAdapterNormalized): boolean {
  return snapshot.service_area.trim().toUpperCase() !== area;
}

function directResult(area: PrioritySnapshotArea, body: unknown): PrioritySnapshotWrapperResult {
  const snapshot = normalizePriorityAdapterResponse(body);
  if (snapshot.adapter_status === "contract_invalid" || areaMismatch(area, snapshot)) {
    return {
      status: "contract_invalid",
      http_status: 502,
      error_code: areaMismatch(area, snapshot) ? `PRIORITY_${area}_AREA_MISMATCH` : `PRIORITY_${area}_CONTRACT_INVALID`,
      detail: areaMismatch(area, snapshot)
        ? `Priority snapshot service_area must equal requested area ${area}.`
        : `${area} priority source failed priority-adapter-v0.1 contract validation.`
    };
  }
  return {
    status: "ok",
    http_status: 200,
    snapshot,
    detail: snapshot.adapter_status === "ok"
      ? `${area} read-only priority snapshot is available.`
      : `${area} priority source responded safely with adapter_status=${snapshot.adapter_status}.`
  };
}

function executionTimestamp(execution: UnknownRecord): number | null {
  for (const key of ["stoppedAt", "startedAt", "createdAt"] as const) {
    const value = execution[key];
    if (typeof value !== "string") continue;
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return null;
}

function executionPayloads(execution: UnknownRecord): unknown[] {
  const data = isRecord(execution.data) ? execution.data : null;
  const resultData = data && isRecord(data.resultData) ? data.resultData : null;
  const runData = resultData && isRecord(resultData.runData) ? resultData.runData : null;
  if (!runData) return [];

  const payloads: unknown[] = [];
  for (const nodeName of FINAL_NODE_NAMES) {
    const runs = runData[nodeName];
    if (!Array.isArray(runs)) continue;
    for (let runIndex = runs.length - 1; runIndex >= 0; runIndex -= 1) {
      const run = runs[runIndex];
      if (!isRecord(run) || !isRecord(run.data) || !Array.isArray(run.data.main)) continue;
      const main = run.data.main;
      for (const branch of main) {
        if (!Array.isArray(branch)) continue;
        for (let itemIndex = branch.length - 1; itemIndex >= 0; itemIndex -= 1) {
          const item = branch[itemIndex];
          if (isRecord(item) && "json" in item) payloads.push(item.json);
        }
      }
    }
  }
  return payloads;
}

function n8nExecutionsUrl(baseUrl: string, workflowId: string): string {
  const apiRoot = /\/api\/v1$/i.test(baseUrl) ? baseUrl : `${baseUrl}/api/v1`;
  const query = new URLSearchParams({
    workflowId,
    status: "success",
    includeData: "true",
    limit: "20"
  });
  return `${apiRoot}/executions?${query.toString()}`;
}

async function loadFromN8n(area: PrioritySnapshotArea): Promise<PrioritySnapshotWrapperResult> {
  const { baseUrl, apiKey, workflowId } = n8nConfig();
  if (!baseUrl || !apiKey || !workflowId) {
    return {
      status: "not_configured",
      http_status: 503,
      error_code: `PRIORITY_${area}_N8N_READ_NOT_CONFIGURED`,
      detail: "Read-only n8n execution-history access is not fully configured."
    };
  }

  const response = await fetchSource(n8nExecutionsUrl(baseUrl, workflowId), apiKey, "X-N8N-API-KEY");
  if (!response.ok) {
    return {
      status: "upstream_unavailable",
      http_status: 502,
      error_code: `PRIORITY_${area}_N8N_READ_UNAVAILABLE`,
      detail: response.status ? `n8n execution-history read returned HTTP ${response.status}.` : "n8n execution-history read is unreachable or timed out."
    };
  }
  if (!isRecord(response.body) || !Array.isArray(response.body.data)) {
    return {
      status: "contract_invalid",
      http_status: 502,
      error_code: `PRIORITY_${area}_N8N_EXECUTION_LIST_INVALID`,
      detail: "n8n execution-history response did not match the expected public API list shape."
    };
  }

  const now = Date.now();
  let sawMatchingStale = false;
  for (const rawExecution of response.body.data) {
    if (!isRecord(rawExecution)) continue;
    const timestamp = executionTimestamp(rawExecution);
    for (const payload of executionPayloads(rawExecution)) {
      const normalized = normalizePriorityAdapterResponse(payload);
      if (normalized.adapter_status === "contract_invalid" || areaMismatch(area, normalized)) continue;
      if (timestamp === null || now - timestamp > maxAgeMs() || timestamp - now > 60_000) {
        sawMatchingStale = true;
        continue;
      }
      return {
        status: "ok",
        http_status: 200,
        snapshot: normalized,
        detail: `${area} priority snapshot was read from a fresh successful n8n execution without triggering the workflow.`
      };
    }
  }

  if (sawMatchingStale) {
    return {
      status: "stale",
      http_status: 503,
      error_code: `PRIORITY_${area}_SNAPSHOT_STALE`,
      detail: `Matching ${area} priority execution exists but is older than the configured freshness gate.`
    };
  }
  return {
    status: "not_configured",
    http_status: 503,
    error_code: `PRIORITY_${area}_FRESH_EXECUTION_NOT_FOUND`,
    detail: `No fresh successful ${area} priority-adapter execution is available; the wrapper does not trigger the workflow.`
  };
}

export async function loadPrioritySnapshot(area: PrioritySnapshotArea): Promise<PrioritySnapshotWrapperResult> {
  const { url, apiKey } = sourceConfig(area);
  if (url) {
    const response = await fetchSource(url, apiKey);
    if (!response.ok) {
      return {
        status: "upstream_unavailable",
        http_status: 502,
        error_code: `PRIORITY_${area}_SOURCE_UNAVAILABLE`,
        detail: response.status ? `${area} priority source returned HTTP ${response.status}.` : `${area} priority source is unreachable or timed out.`
      };
    }
    return directResult(area, response.body);
  }
  return loadFromN8n(area);
}
