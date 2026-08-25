import "server-only";

import crypto from "node:crypto";
import registryData from "./buengkan-registry-v4.json";

const DASHBOARD_ACCESS_CODE_HASH = "bd20d696971124bb9c050d47e0c309f0d8fcd49ecbbe582d4f1d21b045dc72a3";
const ACCESS_CODE_HASH = "e0ca8ce0d2a2aa8a3d050cadef0f7cc5831de8c56032d68f2a8f8bcd12fc9188";
const STRONG_ZONE_GATES = new Set([
  "STRONG_LOCAL_ZONE_CANDIDATE",
  "STRONG_PAIR_ZONE_CANDIDATE",
  "STRONG_BOUNDED_ZONE_CANDIDATE"
]);

export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export type TopologyPrior = {
  feeder: string;
  core_meter_count: number;
  topology_share: number;
};

type LandmarkRule = {
  id?: string;
  phrases?: string[];
  feeder?: string;
  transformers?: string[];
  strength?: number;
  generic_ambiguous?: boolean;
  evidence?: string;
};

type ProtectionZone = {
  gate?: string;
  devices?: string[];
  coverage?: number | null;
  downstream_meter_count?: number | null;
  target_transformers?: string[];
};

type Village = {
  village_key: string;
  village_name: string;
  aliases: string[];
  topology_prior?: TopologyPrior[];
  village_transformers?: string[];
  landmark_rules?: LandmarkRule[];
  protection_zones?: Record<string, ProtectionZone>;
};

type ExcludedVillage = {
  village_key: string;
  village_name?: string;
  gate?: string;
  reason?: string;
  core_coverage?: number | null;
};

type Registry = {
  schema_version: number;
  villages: Village[];
  excluded_villages?: ExcludedVillage[];
  guardrails: {
    mode: string;
    production_send: string;
  };
};

const registry = registryData as unknown as Registry;

if (registry.guardrails.mode !== "shadow" || registry.guardrails.production_send !== "blocked") {
  throw new Error("Bueng Kan tester registry guardrail mismatch");
}

export type ResolverStatus =
  | "OUTSIDE_PILOT_SCOPE"
  | "UNSUPPORTED_VILLAGE"
  | "AMBIGUOUS_VILLAGE"
  | "VILLAGE_ONLY_SINGLE_FEEDER"
  | "VILLAGE_ONLY_MULTI_FEEDER"
  | "RESOLVED_FOOTPRINT"
  | "AMBIGUOUS_FOOTPRINT";

export type ResolveResult = {
  status: ResolverStatus;
  mode: "shadow";
  production_send: "blocked";
  villageKey?: string;
  villageName?: string;
  supported: boolean;
  message: string;
  selectedFeeder?: string | null;
  selectedTransformerCandidates: string[];
  footprintConfidence?: Confidence;
  topologyPrior: TopologyPrior[];
  protectionZone?: {
    gate?: string;
    devices: string[];
    coverage?: number | null;
    downstreamMeterCount?: number | null;
  } | null;
  matchedClues: string[];
  excludedReason?: string;
  coreCoverage?: number | null;
  outageLevel: "UNDETERMINED";
  requiredConfirmation: string[];
};

export function verifyDashboardAccessCode(input: unknown): boolean {
  const code = String(input ?? "").trim();
  if (!code) return false;
  const actual = crypto.createHash("sha256").update(code, "utf8").digest("hex");
  const expected = Buffer.from(DASHBOARD_ACCESS_CODE_HASH, "hex");
  const received = Buffer.from(actual, "hex");
  return expected.length === received.length && crypto.timingSafeEqual(expected, received);
}

export function verifyTesterAccessCode(input: unknown): boolean {
  const code = String(input ?? "").trim();
  if (!code) return false;
  const actual = crypto.createHash("sha256").update(code, "utf8").digest("hex");
  const expected = Buffer.from(ACCESS_CODE_HASH, "hex");
  const received = Buffer.from(actual, "hex");
  return expected.length === received.length && crypto.timingSafeEqual(expected, received);
}

export function normalizeText(input: unknown): string {
  let value = String(input ?? "")
    .normalize("NFC")
    .toLowerCase()
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .trim();

  const replacements: Array<[RegExp, string]> = [
    [/เเสน/g, "แสน"],
    [/บิ้ก/g, "บิ๊ก"],
    [/หมู่บ้าน/g, "บ้าน"],
    [/ม\.\s*(\d{1,2})/g, "ม.$1"],
    [/หมู่\s*(\d{1,2})/g, "หมู่$1"],
    [/3r\s*[- ]?\s*01/g, "3r-01"]
  ];
  for (const [pattern, replacement] of replacements) value = value.replace(pattern, replacement);
  return value.replace(/[\n\r\t,;:()[\]{}]+/g, " ").replace(/\s+/g, " ").trim();
}

function contains(normalizedText: string, phrase: unknown): boolean {
  const normalizedPhrase = normalizeText(phrase);
  return Boolean(normalizedPhrase && normalizedText.includes(normalizedPhrase));
}

function candidateVillages(normalizedText: string): Village[] {
  return registry.villages.filter((village) =>
    village.aliases.some((alias) => contains(normalizedText, alias))
  );
}

function excludedVillage(normalizedText: string): ExcludedVillage | undefined {
  return (registry.excluded_villages ?? []).find((item) => {
    const name = String(item.village_name ?? "").trim();
    if (!name) return false;
    const aliases = [name, `บ้าน${name}`, `บ.${name}`];
    return aliases.some((alias) => contains(normalizedText, alias));
  });
}

type MatchedClue = {
  ruleId: string;
  phrase: string;
  feeder: string;
  transformers: string[];
  strength: number;
};

function matchedLandmarkRules(normalizedText: string, village: Village): MatchedClue[] {
  const specificBigSuea = normalizedText.includes("หน้าบิ๊กเสือ") || normalizedText.includes("ตรงข้ามบิ๊กเสือ");
  const matched: MatchedClue[] = [];
  for (const rule of village.landmark_rules ?? []) {
    if (rule.generic_ambiguous && specificBigSuea) continue;
    const phrase = (rule.phrases ?? []).find((item) => contains(normalizedText, item));
    if (!phrase || !rule.feeder) continue;
    matched.push({
      ruleId: String(rule.id ?? "landmark"),
      phrase,
      feeder: rule.feeder,
      transformers: (rule.transformers ?? []).map(String),
      strength: Number(rule.strength ?? 0)
    });
  }
  return matched;
}

function matchedZoneDevices(normalizedText: string, village: Village): MatchedClue[] {
  const matched: MatchedClue[] = [];
  for (const [feeder, zone] of Object.entries(village.protection_zones ?? {})) {
    const gate = String(zone.gate ?? "");
    const strength = STRONG_ZONE_GATES.has(gate) ? 105 : gate === "BROAD_UPSTREAM_ZONE_CANDIDATE" ? 85 : 80;
    for (const device of zone.devices ?? []) {
      if (!contains(normalizedText, device)) continue;
      matched.push({
        ruleId: `registry_device:${device}`,
        phrase: device,
        feeder,
        transformers: (zone.target_transformers ?? []).map(String),
        strength
      });
    }
  }
  return matched;
}

function zoneFor(village: Village, feeder: string): ResolveResult["protectionZone"] {
  const zone = village.protection_zones?.[feeder];
  if (!zone) return null;
  return {
    gate: zone.gate,
    devices: (zone.devices ?? []).map(String),
    coverage: zone.coverage,
    downstreamMeterCount: zone.downstream_meter_count
  };
}

function base(village?: Village): Pick<ResolveResult,
  "mode" | "production_send" | "supported" | "selectedTransformerCandidates" | "topologyPrior" | "matchedClues" | "outageLevel" | "requiredConfirmation"
> & Partial<Pick<ResolveResult, "villageKey" | "villageName">> {
  return {
    mode: "shadow",
    production_send: "blocked",
    supported: Boolean(village),
    villageKey: village?.village_key,
    villageName: village?.village_name,
    selectedTransformerCandidates: [],
    topologyPrior: village?.topology_prior ?? [],
    matchedClues: [],
    outageLevel: "UNDETERMINED",
    requiredConfirmation: ["ReportPO/ETR/OMS", "SCADA/สถานะอุปกรณ์", "การยืนยันจากหน้างาน"]
  };
}

export function resolveBuengKanReport(input: unknown): ResolveResult {
  const normalizedText = normalizeText(input);
  if (!normalizedText) {
    return {
      ...base(),
      status: "OUTSIDE_PILOT_SCOPE",
      supported: false,
      message: "กรุณาระบุชื่อหมู่บ้านหรือจุดสังเกตในพื้นที่ทดสอบ"
    };
  }

  const villages = candidateVillages(normalizedText);
  if (villages.length === 0) {
    const excluded = excludedVillage(normalizedText);
    if (excluded) {
      return {
        ...base(),
        status: "UNSUPPORTED_VILLAGE",
        supported: false,
        villageKey: excluded.village_key,
        villageName: excluded.village_name,
        message: "หมู่บ้านนี้ยังไม่ผ่าน GIS topology gate จึงไม่คาดเดาหม้อแปลง",
        excludedReason: excluded.reason,
        coreCoverage: excluded.core_coverage
      };
    }
    return {
      ...base(),
      status: "OUTSIDE_PILOT_SCOPE",
      supported: false,
      message: "ยังไม่พบหมู่บ้านนี้ในชุดทดสอบบึงกาฬ"
    };
  }

  if (villages.length > 1) {
    return {
      ...base(),
      status: "AMBIGUOUS_VILLAGE",
      supported: false,
      message: "ข้อความตรงกับมากกว่าหนึ่งหมู่บ้าน กรุณาระบุชื่อหมู่บ้านให้ชัดเจน"
    };
  }

  const village = villages[0];
  const clues = [...matchedLandmarkRules(normalizedText, village), ...matchedZoneDevices(normalizedText, village)];
  const resultBase = base(village);

  if (clues.length === 0) {
    const uniqueFeeders = [...new Set((village.topology_prior ?? []).map((item) => item.feeder).filter(Boolean))].sort();
    if (uniqueFeeders.length === 1) {
      const feeder = uniqueFeeders[0];
      return {
        ...resultBase,
        status: "VILLAGE_ONLY_SINGLE_FEEDER",
        message: "ระบุ feeder ได้จาก core topology ของหมู่บ้าน แต่ยังไม่ใช่หลักฐานว่าอุปกรณ์กำลังดับจริง",
        selectedFeeder: feeder,
        selectedTransformerCandidates: (village.village_transformers ?? []).map(String).sort(),
        footprintConfidence: "HIGH",
        protectionZone: zoneFor(village, feeder)
      };
    }
    return {
      ...resultBase,
      status: "VILLAGE_ONLY_MULTI_FEEDER",
      message: "หมู่บ้านนี้กระจายหลาย feeder จึงยังระบุหม้อแปลงลูกเดียวไม่ได้ กรุณาเพิ่มจุดสังเกต/ซอย/ชื่ออุปกรณ์",
      selectedFeeder: null,
      footprintConfidence: "LOW"
    };
  }

  const scores = new Map<string, number>();
  const transformers = new Map<string, Set<string>>();
  for (const clue of clues) {
    scores.set(clue.feeder, (scores.get(clue.feeder) ?? 0) + clue.strength);
    if (!transformers.has(clue.feeder)) transformers.set(clue.feeder, new Set());
    for (const tx of clue.transformers) transformers.get(clue.feeder)?.add(tx);
  }
  const ranked = [...scores.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const [bestFeeder, bestScore] = ranked[0];
  const secondScore = ranked[1]?.[1] ?? 0;
  if (ranked.length > 1 && (bestScore === secondScore || bestScore - secondScore < 25)) {
    return {
      ...resultBase,
      status: "AMBIGUOUS_FOOTPRINT",
      message: "จุดสังเกตยังชี้ได้มากกว่าหนึ่ง feeder กรุณาระบุรายละเอียดเพิ่ม",
      selectedFeeder: null,
      footprintConfidence: "LOW",
      matchedClues: clues.map((item) => item.ruleId)
    };
  }

  const zone = village.protection_zones?.[bestFeeder];
  const gate = String(zone?.gate ?? "");
  const confidence: Confidence = bestScore >= 100 && STRONG_ZONE_GATES.has(gate) ? "HIGH" : "MEDIUM";
  return {
    ...resultBase,
    status: "RESOLVED_FOOTPRINT",
    message: "พบ GIS topology candidate จากข้อมูลหมู่บ้านและจุดสังเกตในข้อความ",
    selectedFeeder: bestFeeder,
    selectedTransformerCandidates: [...(transformers.get(bestFeeder) ?? new Set<string>())].sort(),
    footprintConfidence: confidence,
    protectionZone: zoneFor(village, bestFeeder),
    matchedClues: clues.map((item) => item.ruleId)
  };
}

export function getBuengKanTesterCatalog() {
  return {
    schemaVersion: registry.schema_version,
    supported: registry.villages
      .map((village) => ({ key: village.village_key, name: village.village_name }))
      .sort((a, b) => a.key.localeCompare(b.key)),
    excluded: (registry.excluded_villages ?? [])
      .map((village) => ({ key: village.village_key, name: village.village_name ?? "" }))
      .sort((a, b) => a.key.localeCompare(b.key))
  };
}

export function sanitizeFeedbackText(input: unknown, maxLength = 160): string {
  return String(input ?? "")
    .normalize("NFC")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\b0\d{8,9}\b/g, "[PHONE_REDACTED]")
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[EMAIL_REDACTED]")
    .replace(/\b\d{8,}\b/g, "[NUMBER_REDACTED]")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

export function hashTesterQuery(input: unknown): string {
  return crypto.createHash("sha256").update(normalizeText(input), "utf8").digest("hex").slice(0, 20);
}
