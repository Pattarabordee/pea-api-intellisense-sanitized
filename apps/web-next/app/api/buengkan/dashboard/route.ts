import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../../lib/api";
import { verifyDashboardAccessCode } from "../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { accessCode?: string; limit?: number };
    if (!verifyDashboardAccessCode(body.accessCode)) {
      return NextResponse.json({ error: "INVALID_DASHBOARD_ACCESS_CODE" }, { status: 401 });
    }

    const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
    const apiKey = process.env.AIS_INBOUND_API_KEY;
    if (!baseUrl || !apiKey) {
      return NextResponse.json({ error: "DASHBOARD_DATA_UNAVAILABLE" }, { status: 503 });
    }

    const limit = Math.min(Math.max(Number(body.limit) || 500, 1), 1000);
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/buengkan/tester-feedback?limit=${limit}`, {
      cache: "no-store",
      headers: { "X-API-Key": apiKey }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json({ error: "DASHBOARD_DATA_FETCH_FAILED" }, { status: 502 });
    }
    return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
