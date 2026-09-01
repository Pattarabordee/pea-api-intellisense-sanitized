import { NextRequest, NextResponse } from "next/server";
import { loadPrioritySnapshot, type PrioritySnapshotArea } from "../../../../lib/priority-snapshot-wrapper";

export const dynamic = "force-dynamic";

function candidateEnabled(): boolean {
  return String(process.env.SHADOW_CANDIDATE_ENDPOINTS_ENABLED || "").trim().toLowerCase() === "true";
}

function endpointKey(): string {
  return String(process.env.SHADOW_CANDIDATE_ENDPOINT_API_KEY || "").trim();
}

function authorized(request: NextRequest, required: string): boolean {
  return Boolean(required) && request.headers.get("x-api-key") === required;
}

function areaFrom(request: NextRequest): PrioritySnapshotArea | null {
  const area = String(request.nextUrl.searchParams.get("area") || "").trim().toUpperCase();
  return area === "BKN" || area === "PKN" ? area : null;
}

export async function GET(request: NextRequest) {
  if (!candidateEnabled()) {
    return NextResponse.json({
      status: "disabled",
      mode: "shadow",
      production_send: "blocked",
      detail: "Shadow candidate endpoints are disabled by default."
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  const requiredKey = endpointKey();
  if (!requiredKey) {
    return NextResponse.json({
      status: "auth_not_configured",
      mode: "shadow",
      production_send: "blocked",
      detail: "Candidate endpoint key is required when shadow candidate endpoints are enabled."
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  if (!authorized(request, requiredKey)) {
    return NextResponse.json({
      status: "unauthorized",
      mode: "shadow",
      production_send: "blocked"
    }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const area = areaFrom(request);
  if (!area) {
    return NextResponse.json({
      status: "invalid_area",
      mode: "shadow",
      production_send: "blocked",
      detail: "area must be BKN or PKN"
    }, { status: 400, headers: { "Cache-Control": "no-store" } });
  }

  const result = await loadPrioritySnapshot(area);
  return NextResponse.json(result.snapshot ?? {
    status: result.status,
    mode: "shadow",
    production_send: "blocked",
    error_code: result.error_code,
    detail: result.detail
  }, { status: result.http_status, headers: { "Cache-Control": "no-store" } });
}
