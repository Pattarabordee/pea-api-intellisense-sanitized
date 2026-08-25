import crypto from "node:crypto";
import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../../../lib/api";
import { sanitizeFeedbackText, verifyTesterAccessCode } from "../../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

const verdicts = new Set(["CORRECT", "INCORRECT", "UNSURE"]);
const sourceTypes = new Set(["POI", "ROAD_SOI"]);

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      accessCode?: string;
      sourceType?: string;
      sourceRef?: string;
      validatorRef?: string;
      verdict?: string;
      selectedTransformer?: string;
      correctionTransformer?: string;
      correctionFeeder?: string;
    };
    if (!verifyTesterAccessCode(body.accessCode)) {
      return NextResponse.json({ error: "INVALID_ACCESS_CODE" }, { status: 401 });
    }
    const sourceType = String(body.sourceType ?? "").toUpperCase();
    const verdict = String(body.verdict ?? "").toUpperCase();
    if (!sourceTypes.has(sourceType) || !verdicts.has(verdict)) {
      return NextResponse.json({ error: "INVALID_VALIDATION" }, { status: 400 });
    }
    const sourceRef = sanitizeFeedbackText(body.sourceRef, 96);
    const validatorRef = sanitizeFeedbackText(body.validatorRef, 96);
    if (!sourceRef || !validatorRef) {
      return NextResponse.json({ error: "SOURCE_REF_REQUIRED" }, { status: 400 });
    }
    const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
    const apiKey = process.env.OUTAGE_INTEGRATION_API_KEY || process.env.AIS_INBOUND_API_KEY;
    if (!baseUrl || !apiKey) {
      return NextResponse.json({ error: "VALIDATION_API_UNAVAILABLE" }, { status: 503 });
    }
    const receiptId = `BKV-${Date.now().toString(36).toUpperCase()}-${crypto.randomBytes(3).toString("hex").toUpperCase()}`;
    const payload = {
      receipt_id: receiptId,
      source_type: sourceType,
      source_ref: sourceRef,
      validator_ref: validatorRef,
      verdict,
      selected_transformer: sanitizeFeedbackText(body.selectedTransformer, 32).toUpperCase(),
      correction_transformer: sanitizeFeedbackText(body.correctionTransformer, 32).toUpperCase(),
      correction_feeder: sanitizeFeedbackText(body.correctionFeeder, 24).toUpperCase()
    };
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/buengkan/secondary-validation`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json({ error: data?.error?.code ?? "VALIDATION_WRITE_FAILED", detail: data?.error?.message ?? "" }, { status: response.status >= 400 && response.status < 500 ? 400 : 502 });
    }
    return NextResponse.json({
      ok: true,
      receiptId,
      selectedTransformer: data.selected_transformer ?? "",
      duplicate: Boolean(data.duplicate),
      autoPromotion: false,
      storage: "postgres",
      mode: "shadow",
      production_send: "blocked"
    });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
