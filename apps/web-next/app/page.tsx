import { MissionControl } from "./mission-control";
import { normaliseApiBaseUrl } from "../lib/api";
import { demoOperatorData, type OperatorData } from "../lib/demo-data";

async function loadOperatorData(): Promise<OperatorData> {
  const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  const apiKey = process.env.AIS_INBOUND_API_KEY;
  if (!baseUrl || !apiKey) {
    return demoOperatorData;
  }
  try {
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/ais/outage-verifications?view=operator&limit=25`, {
      cache: "no-store",
      headers: { "X-API-Key": apiKey }
    });
    if (!response.ok) {
      return { ...demoOperatorData, source: `fallback: API returned ${response.status}` };
    }
    return (await response.json()) as OperatorData;
  } catch (error) {
    return { ...demoOperatorData, source: `fallback: ${(error as Error).message}` };
  }
}

export default async function Page() {
  const data = await loadOperatorData();
  return <MissionControl initialData={data} />;
}
