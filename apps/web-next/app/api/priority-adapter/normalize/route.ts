import { NextResponse } from "next/server";
import { normalizePriorityAdapterResponse } from "../../../../lib/priority-adapter";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as unknown;
    const normalized = normalizePriorityAdapterResponse(body);
    const status = normalized.adapter_status === "contract_invalid" ? 422 : 200;
    return NextResponse.json(normalized, {
      status,
      headers: { "Cache-Control": "no-store" }
    });
  } catch {
    return NextResponse.json(
      {
        mode: "shadow",
        production_send: "blocked",
        purpose: "decision_support_only",
        authoritative_outage_truth: false,
        schema_version: "priority-adapter-v0.1",
        adapter_status: "contract_invalid",
        ticket_id: "",
        service_area: "",
        queue_count: 0,
        queues: [],
        error_code: "PRIORITY_ADAPTER_INVALID_JSON",
        contract_errors: ["INVALID_JSON"]
      },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }
}
