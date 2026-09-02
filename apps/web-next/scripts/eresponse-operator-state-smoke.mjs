import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";

const port = 3114;
const stateFile = path.join(os.tmpdir(), `eresponse-operator-state-smoke-${process.pid}.json`);
const baseUrl = `http://127.0.0.1:${port}`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(url) {
  let lastError;
  for (let i = 0; i < 60; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }
  throw lastError || new Error(`server not ready: ${url}`);
}

async function stopChild(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), delay(1500)]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

async function post(payload) {
  const response = await fetch(`${baseUrl}/api/eresponse/operator-state`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  let body = {};
  try { body = await response.json(); } catch {}
  return { response, body };
}

await fs.rm(stateFile, { force: true });
const child = spawn(process.execPath, [".next/standalone/server.js"], {
  cwd: process.cwd(),
  env: { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1", ERESPONSE_OPERATOR_STATE_FILE: stateFile },
  stdio: ["ignore", "pipe", "pipe"]
});

try {
  await waitFor(`${baseUrl}/api/eresponse/operator-state`);

  const initial = await (await fetch(`${baseUrl}/api/eresponse/operator-state`)).json();
  assert(initial.schema_version === "eresponse-operator-state.v1", "operator-state schema mismatch");
  assert(Object.keys(initial.items || {}).length === 0, "initial operator state must be empty");
  assert(Array.isArray(initial.teams) && initial.teams.length >= 4, "team catalog missing");

  const incidentId = "INC-PKN-OPERATOR-SMOKE-001";
  let result = await post({ incident_id: incidentId, action: "ACKNOWLEDGE" });
  assert(result.response.status === 200, `ACK expected 200, got ${result.response.status}`);
  assert(result.body.item?.workflow_status === "ACKNOWLEDGED", "ACK state mismatch");

  result = await post({ incident_id: incidentId, action: "ASSIGN", team: "ทีมแก้ไฟ 1 กฟส.พังโคน" });
  assert(result.response.status === 200, `ASSIGN expected 200, got ${result.response.status}`);
  assert(result.body.item?.workflow_status === "ASSIGNED", "ASSIGN state mismatch");
  assert(result.body.item?.assigned_team === "ทีมแก้ไฟ 1 กฟส.พังโคน", "assigned team mismatch");

  result = await post({ incident_id: incidentId, action: "START" });
  assert(result.body.item?.workflow_status === "IN_PROGRESS", "START state mismatch");

  result = await post({ incident_id: incidentId, action: "COMPLETE" });
  assert(result.body.item?.workflow_status === "COMPLETED", "COMPLETE state mismatch");

  result = await post({ incident_id: incidentId, action: "CLOSE" });
  assert(result.body.item?.workflow_status === "CLOSED", "CLOSE state mismatch");

  const persisted = await (await fetch(`${baseUrl}/api/eresponse/operator-state`)).json();
  assert(persisted.items?.[incidentId]?.workflow_status === "CLOSED", "GET did not preserve state");
  assert(persisted.items?.[incidentId]?.timeline?.length === 5, "timeline length mismatch");

  result = await post({ incident_id: "INC-PKN-INVALID-TEAM", action: "ASSIGN", team: "ทีมที่ไม่มีในระบบ" });
  assert(result.response.status === 400 && result.body.error === "INVALID_TEAM", "invalid team must fail closed");

  result = await post({ incident_id: "INC-PKN-MOVE-001", action: "MOVE", moved_to: "กฟส.พังโคน" });
  assert(result.response.status === 200 && result.body.item?.moved_to === "กฟส.พังโคน", "MOVE persistence mismatch");

  console.log("ERESPONSE_OPERATOR_STATE_SMOKE_PASS");
  console.log(JSON.stringify({ cases: 8, persistence: true, actions: ["ACKNOWLEDGE", "ASSIGN", "START", "COMPLETE", "CLOSE", "MOVE"], invalid_team: "blocked" }));
} finally {
  await stopChild(child);
  await fs.rm(stateFile, { force: true });
}
