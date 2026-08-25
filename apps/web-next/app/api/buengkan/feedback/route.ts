import crypto from "node:crypto";
import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../../lib/api";
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

    const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
    const apiKey = process.env.AIS_INBOUND_API_KEY;
    if (!baseUrl || !apiKey) {
      return NextResponse.json({ error: "DURABLE_FEEDBACK_UNAVAILABLE" }, { status: 503 });
    }

    const receiptId = `BKT-${Date.now().toString(36).toUpperCase()}-${crypto.randomBytes(3).toString("hex").toUpperCase()}`;
    const payload = {
      receipt_id: receiptId,
      query_hash: hashTesterQuery(body.query),
      verdict,
      village_key: sanitizeFeedbackText(body.villageKey, 32),
      resolver_status: sanitizeFeedbackText(body.status, 48),
      selected_feeder: sanitizeFeedbackText(body.selectedFeeder, 24).toUpperCase(),
      transformer_candidates: (body.transformerCandidates ?? []).slice(0, 12).map((item) => sanitizeFeedbackText(item, 32).toUpperCase()),
      correction_feeder: sanitizeFeedbackText(body.correctFeeder, 24).toUpperCase(),
      correction_transformer: sanitizeFeedbackText(body.correctTransformer, 32).toUpperCase()
    };

    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/buengkan/tester-feedback`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey
      },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      console.error("buengkan durable feedback write failed", { status: response.status, receiptId });
      return NextResponse.json({ error: "DURABLE_FEEDBACK_WRITE_FAILED" }, { status: 502 });
    }

    return NextResponse.json({
      ok: true,
      receiptId,
      duplicate: Boolean(data.duplicate),
      storage: "postgres",
      mode: "shadow",
      production_send: "blocked"
    });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
