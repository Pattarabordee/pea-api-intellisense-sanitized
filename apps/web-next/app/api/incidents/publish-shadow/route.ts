import { NextResponse } from "next/server";
import { publishShadowIncidentQueue } from "../../../../lib/shadow-queue-publisher";

export const dynamic = "force-dynamic";

export async function GET() {
  const result = await publishShadowIncidentQueue();
  if (result.status === "published" && result.feed) {
    return NextResponse.json(result.feed, {
      status: 200,
      headers: {
        "Cache-Control": "no-store",
        "X-Shadow-Publisher-State": "published"
      }
    });
  }

  return NextResponse.json(
    {
      schema_version: "incident-queue-publisher-status.v1",
      mode: "shadow",
      production_send: "blocked",
      authoritative_outage_truth: false,
      status: result.status,
      source_health: result.source_health,
      error_code: result.error_code,
      detail: result.detail,
      generated_at: new Date().toISOString()
    },
    {
      status: result.http_status,
      headers: {
        "Cache-Control": "no-store",
        "X-Shadow-Publisher-State": result.status
      }
    }
  );
}
