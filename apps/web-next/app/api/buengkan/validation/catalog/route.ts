import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../../../lib/api";
import { verifyTesterAccessCode } from "../../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { accessCode?: string };
    if (!verifyTesterAccessCode(body.accessCode)) {
      return NextResponse.json({ error: "INVALID_ACCESS_CODE" }, { status: 401 });
    }
    const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
    const apiKey = process.env.OUTAGE_INTEGRATION_API_KEY || process.env.AIS_INBOUND_API_KEY;
    if (!baseUrl || !apiKey) {
      return NextResponse.json({ error: "VALIDATION_API_UNAVAILABLE" }, { status: 503 });
    }
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const headers = { "X-API-Key": apiKey };
    const [catalogResponse, validationResponse] = await Promise.all([
      fetch(`${apiBaseUrl}/api/v1/buengkan/secondary-validation/catalog`, { cache: "no-store", headers }),
      fetch(`${apiBaseUrl}/api/v1/buengkan/secondary-validation?limit=2000`, { cache: "no-store", headers })
    ]);
    const catalogData = await catalogResponse.json().catch(() => ({}));
    const validationData = await validationResponse.json().catch(() => ({}));
    if (!catalogResponse.ok || !validationResponse.ok) {
      console.error("buengkan validation catalog proxy failed", { catalogStatus: catalogResponse.status, validationStatus: validationResponse.status });
      return NextResponse.json({ error: "VALIDATION_API_READ_FAILED" }, { status: 502 });
    }
    return NextResponse.json({
      catalog: catalogData.catalog,
      validations: validationData.items ?? [],
      summary: validationData.summary ?? { total: 0, correct: 0, incorrect: 0, unsure: 0 },
      mode: "shadow",
      production_send: "blocked",
      auto_promotion: false
    }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
