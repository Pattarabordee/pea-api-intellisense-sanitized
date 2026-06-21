import crypto from "node:crypto";
import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/PEA Intellisense data/runtime/google_workspace_pilot";
const outputPath = `${outputDir}/pea_api_intellisense_google_workspace_pilot.xlsx`;
const previewDir = `${outputDir}/preview`;

const meter = "PEA_SAMPLE_METER_0001";
const meterHash = crypto.createHash("sha256").update(meter, "utf8").digest("hex").slice(0, 16);
const meterLast4 = meter.slice(-4);

const headers = {
  settings: ["key", "value", "note"],
  inbound: [
    "received_at",
    "request_id",
    "meter_hash",
    "meter_last4",
    "detected_at",
    "detected_at_original",
    "timestamp_quality_status",
    "timestamp_quality_flags",
    "province",
    "district",
    "subdistrict",
    "callback_status",
    "verification_status",
    "confidence",
    "decision_answer",
    "decision_reason",
    "match_found",
    "match_level",
    "match_confidence",
    "device_type",
    "device_id",
    "feeder",
    "time_delta_minutes",
    "etr_status",
    "etr_minutes_p50",
    "q10",
    "q90",
    "risk_level",
    "production_send",
    "request_json_redacted",
    "result_json",
  ],
  topology: [
    "meter_hash",
    "meter_last4",
    "feeder",
    "transformer_id",
    "transformer_peano",
    "cb_ids",
    "recloser_ids",
    "switch_ids",
    "confidence_eligible",
    "trace_status",
    "updated_at",
    "note",
  ],
  evidence: [
    "event_id",
    "event_time",
    "device_type",
    "device_id",
    "feeder",
    "etr_minutes_p50",
    "q10",
    "q90",
    "risk_level",
    "source",
    "evidence_note",
  ],
  audit: ["logged_at", "request_id", "event", "status", "message", "production_send"],
};

function writeHeader(sheet, range, values) {
  const r = sheet.getRange(range);
  r.values = [values];
  r.format = {
    fill: "#1F4E79",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
}

function styleUsed(sheet, range) {
  sheet.getRange(range).format.borders = { preset: "outside", style: "thin", color: "#D9E2F3" };
}

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const workbook = Workbook.create();

const dashboard = workbook.worksheets.add("Dashboard");
dashboard.showGridLines = false;
dashboard.getRange("A1:H1").merge();
dashboard.getRange("A1").values = [["PEA API Intellisense - Google Workspace Pilot"]];
dashboard.getRange("A1").format = {
  fill: "#17365D",
  font: { bold: true, color: "#FFFFFF", size: 16 },
};
dashboard.getRange("A3:B8").values = [
  ["Mode", "shadow"],
  ["Production send", "blocked"],
  ["Total inbound requests", ""],
  ["Confirmed PEA outage", ""],
  ["Needs review", ""],
  ["Last received at", ""],
];
dashboard.getRange("B5").formulas = [["=COUNTA('inbound_requests'!B2:B1001)"]];
dashboard.getRange("B6").formulas = [["=COUNTIF('inbound_requests'!M2:M1001,\"CONFIRMED_PEA_OUTAGE\")"]];
dashboard.getRange("B7").formulas = [["=COUNTIF('inbound_requests'!M2:M1001,\"UNCERTAIN_NEEDS_REVIEW\")"]];
dashboard.getRange("B8").formulas = [["=IFERROR(MAX('inbound_requests'!A2:A1001),\"\")"]];
dashboard.getRange("A3:A8").format = { fill: "#EAF2F8", font: { bold: true } };
dashboard.getRange("B3:B8").format = { fill: "#F8FBFD" };
dashboard.getRange("A1:A13").format.columnWidthPx = 190;
dashboard.getRange("B1:H13").format.columnWidthPx = 105;
dashboard.getRange("A3:B13").format.wrapText = true;
dashboard.getRange("A10:H13").values = [
  ["Pilot caveat", "Apps Script cannot read X-API-Key headers or force HTTP 202/401. Use pilot_key query/body and JSON http_status.", "", "", "", "", "", ""],
  ["Guardrail", "All outputs remain shadow mode with production_send=blocked.", "", "", "", "", "", ""],
  ["Next production step", "Move to approved API gateway/cloud runtime when funded.", "", "", "", "", "", ""],
  ["Data privacy", "Use meter_hash + last4. Do not store verbatim WebEx text, tokens, room ids, or public PEANO lists.", "", "", "", "", "", ""],
];
dashboard.getRange("A10:A13").format = { fill: "#FFF2CC", font: { bold: true } };
dashboard.getRange("B10:H13").merge(true);
dashboard.getRange("B10:B13").format = { wrapText: true };
dashboard.getRange("A10:A13").format.columnWidthPx = 190;
dashboard.getRange("B10:H13").format.columnWidthPx = 105;
styleUsed(dashboard, "A3:B8");
styleUsed(dashboard, "A10:H13");

const settings = workbook.worksheets.add("settings");
writeHeader(settings, "A1:C1", headers.settings);
settings.getRange("A2:C4").values = [
  ["pilot_key_sha256", "", "Paste SHA-256 of shared pilot key here, not raw key."],
  ["owner", "PEA API Intellisense pilot", "Internal owner/team."],
  ["production_send", "blocked", "Do not change until approved production gate."],
];
styleUsed(settings, "A1:C4");
settings.getRange("A1:A4").format.columnWidthPx = 180;
settings.getRange("B1:B4").format.columnWidthPx = 240;
settings.getRange("C1:C4").format.columnWidthPx = 360;
settings.getRange("A1:C4").format.wrapText = true;

const inbound = workbook.worksheets.add("inbound_requests");
writeHeader(inbound, "A1:AE1", headers.inbound);
inbound.getRange("A2:AE2").values = [[
  "",
  "AIS-20260621-GWS-0001",
  meterHash,
  meterLast4,
  "",
  "2026-06-21T14:30:00+07:00",
  "",
  "",
  "Sakon Nakhon",
  "Phang Khon",
  "Demo",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "",
  "blocked",
  "",
  "",
]];
styleUsed(inbound, "A1:AE2");
inbound.getRange("A1:AE2").format.wrapText = true;

const topology = workbook.worksheets.add("topology_lookup");
writeHeader(topology, "A1:L1", headers.topology);
topology.getRange("A2:L2").values = [[
  meterHash,
  meterLast4,
  "PFA03",
  "TX-DEMO-01",
  "",
  "PFA03VB-01",
  "PFA03R-01",
  "",
  true,
  "sample_reviewed",
  "2026-06-21T00:00:00+00:00",
  "Sample hashed meter. Replace with reviewed topology export.",
]];
styleUsed(topology, "A1:L2");
topology.getRange("A1:L2").format.wrapText = true;

const evidence = workbook.worksheets.add("evidence_events");
writeHeader(evidence, "A1:K1", headers.evidence);
evidence.getRange("A2:K2").values = [[
  "EVT-GWS-DEMO-001",
  "2026-06-21T07:25:00+00:00",
  "CB",
  "PFA03VB-01",
  "PFA03",
  45,
  20,
  95,
  "LOW",
  "sanitized evidence + topology",
  "Sample event only. No verbatim WebEx text.",
]];
styleUsed(evidence, "A1:K2");
evidence.getRange("A1:K2").format.wrapText = true;

const audit = workbook.worksheets.add("audit_log");
writeHeader(audit, "A1:F1", headers.audit);
audit.getRange("A2:F2").values = [["", "", "", "", "", "blocked"]];
styleUsed(audit, "A1:F2");
audit.getRange("A1:F2").format.wrapText = true;

for (const sheetName of ["settings", "inbound_requests", "topology_lookup", "evidence_events", "audit_log"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  sheet.freezePanes.freezeRows(1);
  sheet.getUsedRange().format.autofitColumns();
}

const overview = await workbook.inspect({
  kind: "sheet,table",
  tableMaxRows: 3,
  tableMaxCols: 8,
  maxChars: 6000,
});
console.log(overview.ndjson);

for (const sheetName of ["Dashboard", "settings", "topology_lookup", "evidence_events"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(`${previewDir}/${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`saved ${outputPath}`);
