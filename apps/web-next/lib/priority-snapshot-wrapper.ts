import { normalizePriorityAdapterResponse, type PriorityAdapterNormalized } from "./priority-adapter";

export type PrioritySnapshotArea = "BKN" | "PKN";

export type PrioritySnapshotWrapperResult = {
  status: "ok" | "not_configured" | "upstream_unavailable" | "contract_invalid";
  http_status: 200 | 502 | 503;
  snapshot?: PriorityAdapterNormalized;
  error_code?: string;
  detail: string;
};

function timeoutMs(): number {
  const raw = Number(process.env.PRIORITY_SNAPSHOT_TIMEOUT_MS || "5000");
  if (!Number.isFinite(raw)) return 5000;
  return Math.min(30000, Math.max(500, Math.round(raw)));
}

function sourceConfig(area: PrioritySnapshotArea): { url: string; apiKey: string } {
  return {
    url: String(process.env[`PRIORITY_SNAPSHOT_${area}_SOURCE_URL`] || "").trim(),
    apiKey: String(process.env[`PRIORITY_SNAPSHOT_${area}_SOURCE_API_KEY`] || process.env.PRIORITY_SNAPSHOT_SOURCE_API_KEY || "").trim()
  };
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

function areaMismatch(area: PrioritySnapshotArea, snapshot: PriorityAdapterNormalized): boolean {
  return snapshot.service_area.trim().toUpperCase() !== area;
}

export async function loadPrioritySnapshot(area: PrioritySnapshotArea): Promise<PrioritySnapshotWrapperResult> {
  const { url, apiKey } = sourceConfig(area);
  if (!url) {
    return {
      status: "not_configured",
      http_status: 503,
      error_code: `PRIORITY_${area}_SOURCE_NOT_CONFIGURED`,
      detail: `No approved read-only ${area} priority snapshot source is configured.`
    };
  }

  const response = await fetchSource(url, apiKey);
  if (!response.ok) {
    return {
      status: "upstream_unavailable",
      http_status: 502,
      error_code: `PRIORITY_${area}_SOURCE_UNAVAILABLE`,
      detail: response.status ? `${area} priority source returned HTTP ${response.status}.` : `${area} priority source is unreachable or timed out.`
    };
  }

  const snapshot = normalizePriorityAdapterResponse(response.body);
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
