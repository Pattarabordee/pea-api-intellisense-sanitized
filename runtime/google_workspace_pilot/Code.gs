const API_VERSION = "v1";
const SCHEMA_VERSION = "2026-06-21-google-workspace-pilot";
const MODE = "shadow";
const PRODUCTION_SEND = "blocked";
const DEFAULT_MATCH_WINDOW_MINUTES = 360;
const REQUEST_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
const METER_RE = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,63}$/;

const SHEETS = {
  settings: "settings",
  inbound: "inbound_requests",
  topology: "topology_lookup",
  evidence: "evidence_events",
  audit: "audit_log",
};

const HEADERS = {
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
  audit: [
    "logged_at",
    "request_id",
    "event",
    "status",
    "message",
    "production_send",
  ],
  settings: [
    "key",
    "value",
    "note",
  ],
};

function doPost(e) {
  try {
    setupPilotSheets();
    const payload = parsePostPayload_(e);
    const pilotKey = getPilotKeyFromRequest_(e, payload);
    if (!isAuthorized_(pilotKey)) {
      return jsonOut_(errorPayload_("UNAUTHORIZED", "pilot_key is missing or invalid", 401));
    }
    const request = normalizeInboundPayload_(payload);
    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      const existing = findInboundByRequestId_(request.request_id);
      if (existing) {
        const duplicateResult = buildDuplicateResult_(request);
        appendAudit_(request.request_id, "duplicate", "DUPLICATE_REQUEST", "request_id already received");
        return jsonOut_(duplicateResult.accepted_response);
      }
      const asset = findTopologyByMeterHash_(request.meter_hash);
      const causeLane = classifyCauseLane_(request);
      const evidence = findEvidence_(asset, request.detected_at);
      const result = buildResult_(request, asset, causeLane, evidence);
      persistInbound_(request, result);
      appendAudit_(request.request_id, "accepted", result.callback_payload.status, result.decision.reason);
      return jsonOut_(result.accepted_response);
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    const message = String(err && err.message ? err.message : err);
    return jsonOut_(errorPayload_("BAD_REQUEST", message, 400));
  }
}

function doGet(e) {
  try {
    setupPilotSheets();
    const params = (e && e.parameter) || {};
    if (params.health === "1" || params.action === "health" || getPathInfo_(e) === "health") {
      return jsonOut_({
        api_version: API_VERSION,
        schema_version: SCHEMA_VERSION,
        mode: MODE,
        status: "OK",
        backend: "google_apps_script",
        production_send: PRODUCTION_SEND,
        generated_at: nowIso_(),
        caveat: "Apps Script direct web app returns Google-managed HTTP status; use JSON http_status fields for pilot checks.",
      });
    }
    const pilotKey = getPilotKeyFromRequest_(e, {});
    if (!isAuthorized_(pilotKey)) {
      return jsonOut_(errorPayload_("UNAUTHORIZED", "pilot_key is missing or invalid", 401));
    }
    const requestId = params.request_id || params.requestId || getPathInfo_(e);
    if (!requestId) {
      return jsonOut_({
        api_version: API_VERSION,
        schema_version: SCHEMA_VERSION,
        mode: MODE,
        status: "READY",
        method: "POST",
        logical_endpoint: "/api/v1/ais/outage-verifications",
        apps_script_endpoint: "Use this web app URL with ?pilot_key=<shared pilot key>",
        production_send: PRODUCTION_SEND,
        generated_at: nowIso_(),
      });
    }
    const row = findInboundByRequestId_(String(requestId));
    if (!row) {
      return jsonOut_(errorPayload_("NOT_FOUND", "request_id not found", 404, String(requestId)));
    }
    return jsonOut_(statusPayloadFromRow_(row));
  } catch (err) {
    const message = String(err && err.message ? err.message : err);
    return jsonOut_(errorPayload_("BAD_REQUEST", message, 400));
  }
}

function setupPilotSheets() {
  const ss = getSpreadsheet_();
  ensureSheet_(ss, SHEETS.settings, HEADERS.settings);
  ensureSheet_(ss, SHEETS.inbound, HEADERS.inbound);
  ensureSheet_(ss, SHEETS.topology, HEADERS.topology);
  ensureSheet_(ss, SHEETS.evidence, HEADERS.evidence);
  ensureSheet_(ss, SHEETS.audit, HEADERS.audit);
  seedSettings_(ss);
}

function hashForSetup(value) {
  Logger.log(sha256Hex_(String(value || "")));
}

function parsePostPayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new Error("JSON body is required");
  }
  const text = String(e.postData.contents || "");
  if (text.length > 1000000) {
    throw new Error("request body exceeds pilot limit");
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (err) {
    throw new Error("invalid JSON body");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("JSON object body is required");
  }
  return payload;
}

function normalizeInboundPayload_(payload) {
  const requestId = validateIdentifier_(
    firstText_(payload, ["request_id", "requestId", "event_id", "eventId", "alarm_id", "alarmId", "ticket_id", "ticketId"]),
    "request_id",
    REQUEST_ID_RE
  );
  const meter = validateIdentifier_(
    firstText_(payload, ["peano", "PEANO", "meter_no", "meterNo", "meter_number", "meterNumber", "meter_id", "meterId", "meter", "pea_meter_no", "peaMeterNo", "pea_no", "peaNo"]),
    "meter_no or peano",
    METER_RE
  );
  const detectedOriginal = firstText_(payload, ["detected_at", "detectedAt", "timestamp", "timeStamp", "event_time", "eventTime", "occurred_at", "occurredAt", "outage_start_time", "outageStartTime"]);
  if (!detectedOriginal) {
    throw new Error("timestamp or detected_at is required");
  }
  const parsed = parseTimestamp_(detectedOriginal);
  return {
    request_id: requestId,
    meter_hash: sha256Hex_(meter).slice(0, 16),
    meter_last4: last4_(meter),
    detected_at: parsed.iso_utc,
    detected_at_original: String(detectedOriginal),
    timestamp_quality: parsed.quality,
    province: boundedText_(firstText_(payload, ["province", "provinceName"]), 120),
    district: boundedText_(firstText_(payload, ["district", "districtName", "amphoe", "amphur"]), 120),
    subdistrict: boundedText_(firstText_(payload, ["subdistrict", "subDistrict", "subdistrictName", "tambon", "tambonName"]), 120),
    alarm_type: boundedText_(firstText_(payload, ["alarm_type", "alarmType", "alarm"]), 240),
    main_cause: boundedText_(firstText_(payload, ["main_cause", "mainCause", "maincause", "MAINCAUSE"]), 240),
    subcause: boundedText_(firstText_(payload, ["subcause", "subCause", "sub_cause", "subcause2", "subCause2", "SUBCAUSE2"]), 240),
    raw: redactPayload_(payload),
  };
}

function findTopologyByMeterHash_(meterHash) {
  const rows = readRows_(SHEETS.topology);
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i].meter_hash || "").trim() === meterHash) {
      return rows[i];
    }
  }
  return null;
}

function findEvidence_(asset, detectedAtIso) {
  if (!asset || !truthy_(asset.confidence_eligible)) {
    return { source: "topology", match_found: false, match_level: "" };
  }
  const detected = new Date(detectedAtIso);
  const evidenceRows = readRows_(SHEETS.evidence);
  const ranked = [];
  for (let i = 0; i < evidenceRows.length; i++) {
    const row = evidenceRows[i];
    const level = assetEventMatchLevel_(asset, row);
    if (!level) continue;
    const eventDate = new Date(String(row.event_time || ""));
    if (isNaN(eventDate.getTime())) continue;
    const delta = Math.abs(eventDate.getTime() - detected.getTime()) / 60000;
    if (delta > DEFAULT_MATCH_WINDOW_MINUTES) continue;
    ranked.push({
      rank: levelRank_(level),
      delta: delta,
      row: row,
      level: level,
    });
  }
  if (!ranked.length) {
    return {
      source: "topology",
      match_found: false,
      match_level: "",
      reason: "meter_in_registry_but_no_recent_evidence_match",
    };
  }
  ranked.sort(function (a, b) {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return a.delta - b.delta;
  });
  const best = ranked[0];
  return {
    source: String(best.row.source || "sheet evidence + topology"),
    match_found: true,
    match_level: best.level,
    match_confidence: matchConfidence_(best.level),
    event_id: best.row.event_id || "",
    event_time: best.row.event_time || "",
    device_type: best.row.device_type || "",
    device_id: best.row.device_id || "",
    feeder: best.row.feeder || "",
    time_delta_minutes: Math.round(best.delta * 100) / 100,
    prediction: {
      etr_minutes_p50: numberOrBlank_(best.row.etr_minutes_p50),
      q10: numberOrBlank_(best.row.q10),
      q90: numberOrBlank_(best.row.q90),
      risk_level: best.row.risk_level || "",
      model_version: "google_workspace_rule_shadow",
    },
  };
}

function buildResult_(request, asset, causeLane, evidence) {
  const statusTuple = verificationStatus_(asset, causeLane, evidence);
  const etr = etrPayload_(statusTuple.status, evidence.prediction);
  const decision = decisionPayload_(statusTuple.status, statusTuple.confidence, statusTuple.reason, etr);
  const callbackPayload = {
    api_version: API_VERSION,
    schema_version: SCHEMA_VERSION,
    mode: MODE,
    request_id: request.request_id,
    status: statusTuple.status,
    confidence: statusTuple.confidence,
    received: {
      meter_ref: { hash: request.meter_hash, last4: request.meter_last4 },
      detected_at: request.detected_at_original,
      detected_at_utc: request.detected_at,
      timestamp_quality: request.timestamp_quality,
      province: request.province,
      district: request.district,
      subdistrict: request.subdistrict,
    },
    decision: decision,
    pea_distribution: {
      status: statusTuple.status,
      reason: statusTuple.reason,
      cause_lane: causeLane,
    },
    evidence: evidence,
    etr: etr,
    generated_at: nowIso_(),
    production_send: PRODUCTION_SEND,
  };
  return {
    accepted_response: acceptedResponse_(request, "CAPTURED_GOOGLE_SHEETS_ONLY", false),
    callback_payload: callbackPayload,
    decision: decision,
  };
}

function buildDuplicateResult_(request) {
  return {
    accepted_response: acceptedResponse_(request, "SKIPPED_DUPLICATE", true),
    callback_payload: {
      api_version: API_VERSION,
      schema_version: SCHEMA_VERSION,
      mode: MODE,
      request_id: request.request_id,
      status: "DUPLICATE_REQUEST",
      confidence: "HIGH",
      decision: {
        pea_distribution_outage: null,
        answer: "duplicate_request_not_reprocessed",
        confidence: "HIGH",
        reason: "request_id_already_received",
        auto_customer_etr_allowed: false,
        production_send: PRODUCTION_SEND,
        next_action: "query_existing_request_status",
      },
      etr: {
        status: "NOT_READY_FOR_AUTO_SEND",
        reason: "duplicate_request_not_reprocessed",
      },
      generated_at: nowIso_(),
      production_send: PRODUCTION_SEND,
    },
  };
}

function persistInbound_(request, result) {
  const p = result.callback_payload;
  const d = p.decision || {};
  const ev = p.evidence || {};
  const etr = p.etr || {};
  const row = [
    result.accepted_response.received_at,
    request.request_id,
    request.meter_hash,
    request.meter_last4,
    request.detected_at,
    request.detected_at_original,
    request.timestamp_quality.status,
    (request.timestamp_quality.flags || []).join(","),
    request.province,
    request.district,
    request.subdistrict,
    result.accepted_response.callback_status,
    p.status,
    p.confidence,
    d.answer || "",
    d.reason || "",
    ev.match_found === true,
    ev.match_level || "",
    ev.match_confidence || "",
    ev.device_type || "",
    ev.device_id || "",
    ev.feeder || "",
    ev.time_delta_minutes || "",
    etr.status || "",
    etr.etr_minutes_p50 || "",
    etr.q10 || "",
    etr.q90 || "",
    etr.risk_level || "",
    PRODUCTION_SEND,
    JSON.stringify(request.raw),
    JSON.stringify(p),
  ];
  getSpreadsheet_().getSheetByName(SHEETS.inbound).appendRow(row);
}

function statusPayloadFromRow_(row) {
  let result = {};
  try {
    result = JSON.parse(row.result_json || "{}");
  } catch (err) {
    result = {};
  }
  return {
    api_version: API_VERSION,
    schema_version: SCHEMA_VERSION,
    mode: MODE,
    request_id: row.request_id,
    status: "COMPLETED",
    request_status: "RECEIVED",
    callback_status: row.callback_status,
    production_send: PRODUCTION_SEND,
    received_at: row.received_at,
    detected_at: row.detected_at,
    detected_at_original: row.detected_at_original,
    timestamp_quality: {
      status: row.timestamp_quality_status,
      flags: String(row.timestamp_quality_flags || "").split(",").filter(Boolean),
    },
    meter: { hash: row.meter_hash, last4: row.meter_last4 },
    area: { province: row.province, district: row.district, subdistrict: row.subdistrict },
    result: result,
  };
}

function verificationStatus_(asset, causeLane, evidence) {
  if (causeLane === "pea_activity") {
    return { status: "PLANNED_OR_PEA_ACTIVITY", confidence: "MEDIUM", reason: "ais_labeled_pea_activity" };
  }
  if (causeLane === "possibly_ais_equipment_or_backup") {
    return { status: "LIKELY_AIS_EQUIPMENT_OR_BACKUP", confidence: "LOW", reason: "ais_subcause_points_to_non_pea_equipment_or_backup" };
  }
  if (!asset) {
    return { status: "NO_PEA_EVIDENCE_FOUND", confidence: "LOW", reason: "meter_not_found_in_runtime_registry" };
  }
  if (!truthy_(asset.confidence_eligible)) {
    return { status: "UNCERTAIN_NEEDS_REVIEW", confidence: "LOW", reason: "meter_mapping_not_confidence_eligible" };
  }
  if (evidence.match_found && ["cb", "recloser", "switch", "transformer"].indexOf(evidence.match_level) >= 0) {
    return { status: "CONFIRMED_PEA_OUTAGE", confidence: "HIGH", reason: "confident_meter_to_protection_and_evidence_match" };
  }
  if (evidence.match_found && evidence.match_level === "feeder") {
    return { status: "UNCERTAIN_NEEDS_REVIEW", confidence: "MEDIUM", reason: "feeder_match_is_audit_only" };
  }
  return { status: "UNCERTAIN_NEEDS_REVIEW", confidence: "MEDIUM", reason: "meter_in_registry_but_no_recent_evidence_match" };
}

function etrPayload_(status, prediction) {
  if (status !== "CONFIRMED_PEA_OUTAGE") {
    return { status: "NOT_READY_FOR_AUTO_SEND", reason: "verification_not_confirmed_for_auto_etr" };
  }
  if (!prediction || prediction.etr_minutes_p50 === "" || prediction.etr_minutes_p50 === null) {
    return { status: "NOT_READY_FOR_AUTO_SEND", reason: "no_shadow_etr_for_matched_event" };
  }
  return {
    status: "SHADOW_ONLY",
    etr_minutes_p50: prediction.etr_minutes_p50,
    q10: prediction.q10,
    q90: prediction.q90,
    risk_level: prediction.risk_level,
    model_version: prediction.model_version,
    production_gate: "blocked_until_green_subset_passes",
  };
}

function decisionPayload_(status, confidence, reason, etr) {
  let peaOutage = null;
  let answer = "uncertain_needs_review";
  let nextAction = "manual_review_required";
  if (status === "CONFIRMED_PEA_OUTAGE") {
    peaOutage = true;
    answer = "confirmed_pea_distribution_outage";
    nextAction = etr.status === "SHADOW_ONLY" ? "shadow_etr_available" : "operator_review_before_etr";
  } else if (status === "LIKELY_AIS_EQUIPMENT_OR_BACKUP") {
    peaOutage = false;
    answer = "not_confirmed_as_pea_distribution_outage";
    nextAction = "ais_internal_or_backup_review";
  } else if (status === "PLANNED_OR_PEA_ACTIVITY") {
    peaOutage = true;
    answer = "pea_activity_or_planned_context";
    nextAction = "confirm_activity_window_before_customer_message";
  } else if (status === "NO_PEA_EVIDENCE_FOUND") {
    answer = "no_pea_evidence_found";
    nextAction = "keep_monitoring_or_manual_review";
  }
  return {
    pea_distribution_outage: peaOutage,
    answer: answer,
    confidence: confidence,
    reason: reason,
    auto_customer_etr_allowed: false,
    production_send: PRODUCTION_SEND,
    next_action: nextAction,
  };
}

function acceptedResponse_(request, callbackStatus, duplicate) {
  return {
    api_version: API_VERSION,
    schema_version: SCHEMA_VERSION,
    mode: MODE,
    status: "RECEIVED",
    http_status: 202,
    request_id: request.request_id,
    duplicate: duplicate === true,
    callback_status: callbackStatus,
    result_path: "?request_id=" + encodeURIComponent(request.request_id),
    production_send: PRODUCTION_SEND,
    received_at: nowIso_(),
    apps_script_caveat: "Google Apps Script direct web apps cannot set custom HTTP 202/401 or read X-API-Key headers; this pilot uses JSON http_status and pilot_key query/body auth.",
  };
}

function errorPayload_(code, message, logicalStatus, requestId) {
  const payload = {
    api_version: API_VERSION,
    schema_version: SCHEMA_VERSION,
    mode: MODE,
    status: "ERROR",
    http_status: logicalStatus,
    error: { code: code, message: message },
    production_send: PRODUCTION_SEND,
    generated_at: nowIso_(),
  };
  if (requestId) payload.request_id = requestId;
  return payload;
}

function classifyCauseLane_(request) {
  const text = String((request.main_cause || "") + " " + (request.subcause || "")).toLowerCase();
  if (text.indexOf("pea activity") >= 0) return "pea_activity";
  if (text.indexOf("pea no back up") >= 0 || text.indexOf("pea no backup") >= 0) return "pea_no_backup";
  if (text.indexOf("faulty ac main") >= 0 || text.indexOf("ac main") >= 0) return "ac_main_uncategorized";
  if (text.trim()) return "possibly_ais_equipment_or_backup";
  return "unknown";
}

function assetEventMatchLevel_(asset, eventRow) {
  const deviceId = normalizeDeviceId_(eventRow.device_id);
  const feeder = normalizeDeviceId_(eventRow.feeder);
  if (deviceId) {
    if (containsId_(asset.cb_ids, deviceId)) return "cb";
    if (containsId_(asset.recloser_ids, deviceId)) return "recloser";
    if (containsId_(asset.switch_ids, deviceId)) return "switch";
    if (deviceId === normalizeDeviceId_(asset.transformer_id) || deviceId === normalizeDeviceId_(asset.transformer_peano)) return "transformer";
  }
  if (feeder && feeder === normalizeDeviceId_(asset.feeder)) return "feeder";
  return "";
}

function containsId_(csv, deviceId) {
  const parts = String(csv || "").split(/[|,;]/);
  for (let i = 0; i < parts.length; i++) {
    if (normalizeDeviceId_(parts[i]) === deviceId) return true;
  }
  return false;
}

function levelRank_(level) {
  const ranks = { cb: 0, recloser: 1, switch: 2, transformer: 3, feeder: 4 };
  return ranks[level] === undefined ? 99 : ranks[level];
}

function matchConfidence_(level) {
  const scores = { cb: 0.95, recloser: 0.9, switch: 0.86, transformer: 0.72, feeder: 0.35 };
  return scores[level] || 0;
}

function readRows_(sheetName) {
  const sheet = getSpreadsheet_().getSheetByName(sheetName);
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];
  const headers = values[0].map(function (h) { return String(h || "").trim(); });
  const rows = [];
  for (let r = 1; r < values.length; r++) {
    const obj = {};
    let hasAny = false;
    for (let c = 0; c < headers.length; c++) {
      obj[headers[c]] = values[r][c];
      if (values[r][c] !== "" && values[r][c] !== null) hasAny = true;
    }
    if (hasAny) rows.push(obj);
  }
  return rows;
}

function findInboundByRequestId_(requestId) {
  const rows = readRows_(SHEETS.inbound);
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i].request_id || "") === requestId) return rows[i];
  }
  return null;
}

function appendAudit_(requestId, event, status, message) {
  getSpreadsheet_().getSheetByName(SHEETS.audit).appendRow([
    nowIso_(),
    requestId || "",
    event || "",
    status || "",
    message || "",
    PRODUCTION_SEND,
  ]);
}

function getPilotKeyFromRequest_(e, payload) {
  const params = (e && e.parameter) || {};
  return String(params.pilot_key || params.api_key || payload.pilot_key || payload.api_key || payload.x_api_key || "");
}

function isAuthorized_(candidate) {
  const expectedHash = getSetting_("pilot_key_sha256") || PropertiesService.getScriptProperties().getProperty("PILOT_KEY_SHA256");
  if (!expectedHash) {
    return false;
  }
  const actualHash = sha256Hex_(String(candidate || ""));
  return timingSafeEquals_(actualHash, String(expectedHash).trim().toLowerCase());
}

function getSetting_(key) {
  const rows = readRows_(SHEETS.settings);
  for (let i = 0; i < rows.length; i++) {
    if (String(rows[i].key || "") === key) return String(rows[i].value || "");
  }
  return "";
}

function seedSettings_(ss) {
  const sheet = ss.getSheetByName(SHEETS.settings);
  const rows = sheet.getDataRange().getValues();
  if (rows.length > 1) return;
  sheet.appendRow(["pilot_key_sha256", "", "Paste SHA-256 of shared pilot key here, not the raw key."]);
  sheet.appendRow(["owner", "PEA API Intellisense pilot", "Internal owner/team."]);
  sheet.appendRow(["production_send", PRODUCTION_SEND, "Do not change until approved production gate."]);
}

function ensureSheet_(ss, name, headers) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  const firstRow = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  const existing = firstRow.map(function (v) { return String(v || ""); }).join("|");
  if (!existing.trim()) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function getSpreadsheet_() {
  const id = PropertiesService.getScriptProperties().getProperty("SPREADSHEET_ID");
  if (id) return SpreadsheetApp.openById(id);
  const active = SpreadsheetApp.getActiveSpreadsheet();
  if (!active) throw new Error("No active spreadsheet. Bind this script to the pilot Google Sheet or set SPREADSHEET_ID.");
  return active;
}

function firstText_(payload, keys) {
  const lower = {};
  Object.keys(payload || {}).forEach(function (k) {
    lower[String(k).toLowerCase()] = payload[k];
  });
  for (let i = 0; i < keys.length; i++) {
    let value = payload[keys[i]];
    if (value === undefined || value === null) value = lower[String(keys[i]).toLowerCase()];
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

function validateIdentifier_(value, fieldName, regex) {
  const text = String(value || "").trim();
  if (!text) throw new Error(fieldName + " is required");
  if (!regex.test(text)) {
    throw new Error(fieldName + " may contain only letters, numbers, dash, underscore, dot, colon, or at sign");
  }
  return text;
}

function boundedText_(value, maxChars) {
  const text = String(value || "").trim();
  if (text.length > maxChars) throw new Error("text field must be " + maxChars + " characters or fewer");
  return text;
}

function parseTimestamp_(value) {
  let text = String(value || "").trim();
  const flags = [];
  if (!text) throw new Error("timestamp is required");
  if (!timestampHasTimezone_(text)) {
    text += "+07:00";
    flags.push("timezone_assumed_bangkok");
  }
  const date = new Date(text);
  if (isNaN(date.getTime())) throw new Error("invalid timestamp: " + value);
  const now = new Date();
  const deltaMinutes = (date.getTime() - now.getTime()) / 60000;
  if (deltaMinutes > 15) flags.push("future_timestamp_review");
  if (deltaMinutes < -(7 * 24 * 60)) flags.push("stale_timestamp_review");
  return {
    iso_utc: toIsoUtc_(date),
    quality: {
      status: flags.length ? "REVIEW" : "OK",
      flags: flags,
      assumption: flags.indexOf("timezone_assumed_bangkok") >= 0 ? "naive_timestamp_treated_as_asia_bangkok" : "",
    },
  };
}

function timestampHasTimezone_(value) {
  const text = String(value || "").trim();
  return /Z$/.test(text) || /[+-]\d{2}:\d{2}$/.test(text);
}

function redactPayload_(value, key) {
  const sensitive = ["access_token", "api_key", "authorization", "client_secret", "pilot_key", "refresh_token", "secret", "token", "x_api_key", "x-api-key"];
  const meterKeys = ["peano", "meter", "meter_id", "meter_no", "meter_number", "pea_meter_no", "pea_no"];
  if (key && sensitive.indexOf(String(key).toLowerCase()) >= 0) return "REDACTED";
  if (key && meterKeys.indexOf(String(key).toLowerCase()) >= 0) {
    return { hash: sha256Hex_(String(value)).slice(0, 16), last4: last4_(String(value)) };
  }
  if (Array.isArray(value)) {
    return value.map(function (item) { return redactPayload_(item, key); });
  }
  if (value && typeof value === "object") {
    const out = {};
    Object.keys(value).forEach(function (name) {
      out[name] = redactPayload_(value[name], name);
    });
    return out;
  }
  return value;
}

function jsonOut_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function sha256Hex_(value) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(value), Utilities.Charset.UTF_8);
  return digest.map(function (b) {
    const v = (b + 256) % 256;
    return ("0" + v.toString(16)).slice(-2);
  }).join("");
}

function timingSafeEquals_(a, b) {
  const left = String(a || "");
  const right = String(b || "");
  let diff = left.length ^ right.length;
  const maxLen = Math.max(left.length, right.length);
  for (let i = 0; i < maxLen; i++) {
    diff |= (left.charCodeAt(i) || 0) ^ (right.charCodeAt(i) || 0);
  }
  return diff === 0;
}

function nowIso_() {
  return toIsoUtc_(new Date());
}

function toIsoUtc_(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

function last4_(value) {
  const text = String(value || "");
  return text.length >= 4 ? text.slice(-4) : text;
}

function normalizeDeviceId_(value) {
  return String(value || "").trim().toUpperCase();
}

function numberOrBlank_(value) {
  if (value === "" || value === null || value === undefined) return "";
  const n = Number(value);
  return isNaN(n) ? "" : n;
}

function truthy_(value) {
  const text = String(value || "").trim().toLowerCase();
  return value === true || value === 1 || ["1", "true", "yes", "y", "eligible"].indexOf(text) >= 0;
}

function getPathInfo_(e) {
  return String((e && e.pathInfo) || "").replace(/^\/+/, "");
}
