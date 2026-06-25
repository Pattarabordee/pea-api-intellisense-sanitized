import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../lib/api";
import { demoOperatorData } from "../../../lib/demo-data";

export async function GET() {
  const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  const apiKey = process.env.AIS_INBOUND_API_KEY;
  if (!baseUrl || !apiKey) {
    return NextResponse.json(demoOperatorData);
  }
  try {
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/ais/outage-verifications?view=operator&limit=50`, {
      cache: "no-store",
      headers: { "X-API-Key": apiKey }
    });
    if (!response.ok) {
      return NextResponse.json({ ...demoOperatorData, source: `fallback: API returned ${response.status}` });
    }
    const data = await response.json();
    const metricsResponse = await fetch(`${apiBaseUrl}/metrics`, {
      cache: "no-store",
      headers: { "X-API-Key": apiKey }
    });
    if (metricsResponse.ok) {
      return NextResponse.json({ ...data, metrics: await metricsResponse.json() });
    }
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ ...demoOperatorData, source: `fallback: ${(error as Error).message}` });
  }
}
