import { NextResponse } from "next/server";
import { loadIncidentQueueFeed } from "../../../../lib/incident-queue-feed";

export const dynamic = "force-dynamic";

export async function GET() {
  const result = await loadIncidentQueueFeed();
  return NextResponse.json(result, {
    headers: {
      "Cache-Control": "no-store"
    }
  });
}
