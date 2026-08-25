import crypto from "node:crypto";
import { NextResponse } from "next/server";
import {
  hashTesterQuery,
  sanitizeFeedbackText,
  verifyTesterAccessCode
} from "../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

const verdicts = new Set(["CORRECT", "INCORRECT", "UNSURE"]);

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      accessCode?: string;
      query?: string;
      verdict?: string;
      villageKey?: string;
      status?: string;
      selectedFeeder?: string | null;
      transformerCandidates?: string[];
      correctFeeder?: string;
      correctTransformer?: string;
    };

    if (!verifyTesterAccessCode(body.accessCode)) {
      return NextResponse.json({ error: "INVALID_ACCESS_CODE" }, { status: 401 });
    }

    const verdict = String(body.verdict ?? "").toUpperCase();
    if (!verdicts.has(verdict)) {
      return NextResponse.json({ error: "INVALID_VERDICT" }, { status: 400 });
    }

    const safeFeeder = sanitizeFeedbackText(body.correctFeeder, 24).toUpperCase();
    const safeTransformer = sanitizeFeedbackText(body.correctTransformer, 32).toUpperCase();
    const receiptId = `BKT-${Date.now().toString(36).toUpperCase()}-${crypto.randomBytes(3).toString("hex").toUpperCase()}`;

    const record = {
      event: "BUENGKAN_TESTER_FEEDBACK",
      receipt_id: receiptId,
      recorded_at: new Date().toISOString(),
      query_hash: hashTesterQuery(body.query),
      verdict,
      village_key: sanitizeFeedbackText(body.villageKey, 32),
      resolver_status: sanitizeFeedbackText(body.status, 48),
      selected_feeder: sanitizeFeedbackText(body.selectedFeeder, 24),
      transformer_candidates: (body.transformerCandidates ?? []).slice(0, 12).map((item) => sanitizeFeedbackText(item, 32)),
      correction_feeder: safeFeeder,
      correction_transformer: safeTransformer,
      mode: "shadow",
      production_send: "blocked"
    };

    // Render retains stdout logs for this bounded tester pilot. Raw query text and access code are never logged.
    console.info(JSON.stringify(record));

    return NextResponse.json({
      ok: true,
      receiptId,
      storage: "sanitized_server_log",
      mode: "shadow",
      production_send: "blocked"
    });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
