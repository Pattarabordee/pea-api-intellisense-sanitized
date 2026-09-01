import { NextResponse } from "next/server";
import { composeIncidentPrioritySnapshot, type PeaIncidentEvidence } from "../../../../lib/incident-priority-compose";
import { normalizePriorityAdapterResponse } from "../../../../lib/priority-adapter";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      priority?: unknown;
      incidents?: PeaIncidentEvidence[];
      generated_at?: string;
    };

    if (!Array.isArray(body.incidents)) {
      return NextResponse.json({ error: "INCIDENTS_ARRAY_REQUIRED" }, { status: 400 });
    }

    const normalized = normalizePriorityAdapterResponse(body.priority);
    const result = composeIncidentPrioritySnapshot(normalized, body.incidents, body.generated_at || new Date().toISOString());

    return NextResponse.json(
      {
        mode: "shadow",
        production_send: "blocked",
        authoritative_outage_truth: false,
        ...result
      },
      { headers: { "Cache-Control": "no-store" } }
    );
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
