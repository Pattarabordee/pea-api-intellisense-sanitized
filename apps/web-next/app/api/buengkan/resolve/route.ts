import { NextResponse } from "next/server";
import { resolveBuengKanReport, verifyTesterAccessCode } from "../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { accessCode?: string; text?: string };
    if (!verifyTesterAccessCode(body.accessCode)) {
      return NextResponse.json({ error: "INVALID_ACCESS_CODE" }, { status: 401 });
    }
    const text = String(body.text ?? "").trim();
    if (!text) {
      return NextResponse.json({ error: "TEXT_REQUIRED" }, { status: 400 });
    }
    if (text.length > 500) {
      return NextResponse.json({ error: "TEXT_TOO_LONG" }, { status: 400 });
    }
    return NextResponse.json(resolveBuengKanReport(text), {
      headers: { "Cache-Control": "no-store" }
    });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
