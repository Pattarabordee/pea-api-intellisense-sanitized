import { promises as fs } from "node:fs";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ACTIONS = new Set(["ACKNOWLEDGE", "ASSIGN", "START", "COMPLETE", "CLOSE", "CANCEL", "MOVE", "CREATE_CONTINUATION"]);
const TEAMS = new Set([
  "ทีมแก้ไฟ 1 กฟส.พังโคน",
  "ทีมแก้ไฟ 2 กฟส.พังโคน",
  "ทีมฮอทไลน์ กฟส.พังโคน",
  "ทีมสนับสนุน กฟส.พังโคน",
  "ทีมแก้ไฟ กฟจ.บึงกาฬ"
]);

type OperatorRecord = {
  incident_id: string;
  workflow_status: "WAITING" | "ACKNOWLEDGED" | "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CLOSED" | "CANCELLED";
  assigned_team: string | null;
  moved_to: string | null;
  note: string | null;
  updated_at: string;
  timeline: Array<{ action: string; at: string; team?: string; note?: string; moved_to?: string }>;
};

type Store = {
  schema_version: "eresponse-operator-state.v1";
  updated_at: string;
  items: Record<string, OperatorRecord>;
};

const emptyStore = (): Store => ({
  schema_version: "eresponse-operator-state.v1",
  updated_at: new Date(0).toISOString(),
  items: {}
});

function storePath() {
  return process.env.ERESPONSE_OPERATOR_STATE_FILE || path.join(process.cwd(), "runtime", "eresponse-operator-state.json");
}

async function readStore(): Promise<Store> {
  try {
    const raw = await fs.readFile(storePath(), "utf8");
    const parsed = JSON.parse(raw) as Store;
    if (parsed?.schema_version !== "eresponse-operator-state.v1" || typeof parsed.items !== "object" || !parsed.items) return emptyStore();
    return parsed;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return emptyStore();
    throw error;
  }
}

async function writeStore(store: Store) {
  const target = storePath();
  await fs.mkdir(path.dirname(target), { recursive: true });
  const temp = `${target}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(temp, JSON.stringify(store, null, 2), "utf8");
  await fs.rename(temp, target);
}

function cleanText(value: unknown, max = 240) {
  return typeof value === "string" ? value.trim().replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, max) : "";
}

function initialRecord(incidentId: string): OperatorRecord {
  return {
    incident_id: incidentId,
    workflow_status: "WAITING",
    assigned_team: null,
    moved_to: null,
    note: null,
    updated_at: new Date(0).toISOString(),
    timeline: []
  };
}

function nextWorkflowStatus(action: string, current: OperatorRecord["workflow_status"]): OperatorRecord["workflow_status"] {
  switch (action) {
    case "ACKNOWLEDGE": return "ACKNOWLEDGED";
    case "ASSIGN": return "ASSIGNED";
    case "START": return "IN_PROGRESS";
    case "COMPLETE": return "COMPLETED";
    case "CLOSE": return "CLOSED";
    case "CANCEL": return "CANCELLED";
    case "MOVE": return current;
    case "CREATE_CONTINUATION": return current;
    default: return current;
  }
}

export async function GET() {
  try {
    const store = await readStore();
    return NextResponse.json({ ...store, teams: [...TEAMS] }, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "OPERATOR_STATE_UNAVAILABLE" }, { status: 503 });
  }
}

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  const incidentId = cleanText(body.incident_id, 160);
  const action = cleanText(body.action, 40).toUpperCase();
  const team = cleanText(body.team, 120);
  const note = cleanText(body.note, 500);
  const movedTo = cleanText(body.moved_to, 120);

  if (!incidentId || !/^[A-Za-z0-9_.:\/-]{3,160}$/.test(incidentId)) return NextResponse.json({ error: "INVALID_INCIDENT_ID" }, { status: 400 });
  if (!ACTIONS.has(action)) return NextResponse.json({ error: "INVALID_ACTION" }, { status: 400 });
  if (action === "ASSIGN" && !TEAMS.has(team)) return NextResponse.json({ error: "INVALID_TEAM" }, { status: 400 });
  if (action === "MOVE" && !movedTo) return NextResponse.json({ error: "MOVE_DESTINATION_REQUIRED" }, { status: 400 });

  try {
    const store = await readStore();
    const now = new Date().toISOString();
    const current = store.items[incidentId] ?? initialRecord(incidentId);
    const updated: OperatorRecord = {
      ...current,
      workflow_status: nextWorkflowStatus(action, current.workflow_status),
      assigned_team: action === "ASSIGN" ? team : current.assigned_team,
      moved_to: action === "MOVE" ? movedTo : current.moved_to,
      note: note || current.note,
      updated_at: now,
      timeline: [
        ...current.timeline.slice(-99),
        { action, at: now, ...(team ? { team } : {}), ...(note ? { note } : {}), ...(movedTo ? { moved_to: movedTo } : {}) }
      ]
    };
    store.items[incidentId] = updated;
    store.updated_at = now;
    await writeStore(store);
    return NextResponse.json({ status: "OK", item: updated }, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "OPERATOR_STATE_WRITE_FAILED" }, { status: 503 });
  }
}
