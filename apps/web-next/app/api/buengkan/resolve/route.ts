import crypto from "node:crypto";
import { NextResponse } from "next/server";
import { normaliseApiBaseUrl } from "../../../../lib/api";
import { verifyTesterAccessCode } from "../../../../lib/buengkan-resolver";

export const dynamic = "force-dynamic";

type APITransformer = {
  facility_id?: string;
  feeder_id?: string;
  location?: {
    lat?: number;
    lon?: number;
    crs?: string;
    source?: string;
  };
};

type APIResolution = {
  status?: string;
  supported?: boolean;
  village_key?: string;
  village_name?: string;
  message?: string;
  selected_feeder?: string;
  topology_confidence?: string;
  topology_prior?: Array<{ feeder: string; core_meter_count: number; topology_share: number }>;
  protection_zone?: {
    gate?: string;
    devices?: string[];
    coverage?: number | null;
    downstream_meter_count?: number | null;
  } | null;
  matched_clues?: string[];
  service_inventory?: APITransformer[];
  selected_transformers?: APITransformer[];
  excluded_reason?: string;
  core_coverage?: number | null;
  outage_state?: string;
  required_confirmation?: string[];
  location_evidence?: {
    status?: string;
    used_for_topology?: boolean;
    source?: string;
    accuracy_m?: number;
    search_radius_m?: number;
    candidate_count?: number;
  };
};

function adaptResolution(resolution: APIResolution) {
  const service = resolution.service_inventory ?? [];
  const selected = resolution.selected_transformers ?? [];
  const grouped = new Map<string, string[]>();
  for (const item of service) {
    const feeder = String(item.feeder_id ?? "").trim();
    const facility = String(item.facility_id ?? "").trim();
    if (!feeder || !facility) continue;
    if (!grouped.has(feeder)) grouped.set(feeder, []);
    grouped.get(feeder)?.push(facility);
  }
  const villageTransformerGroups = [...grouped.entries()]
    .map(([feeder, transformers]) => ({ feeder, transformers: [...new Set(transformers)].sort() }))
    .sort((a, b) => a.feeder.localeCompare(b.feeder));

  return {
    status: resolution.status ?? "OUTSIDE_PILOT_SCOPE",
    mode: "shadow",
    production_send: "blocked",
    villageKey: resolution.village_key,
    villageName: resolution.village_name,
    supported: Boolean(resolution.supported),
    message: resolution.message ?? "ไม่สามารถประเมิน topology ได้",
    selectedFeeder: resolution.selected_feeder ?? null,
    selectedTransformerCandidates: selected.map((item) => String(item.facility_id ?? "")).filter(Boolean).sort(),
    selectedTransformerDetails: selected.map((item) => ({
      facilityId: String(item.facility_id ?? ""),
      feederId: String(item.feeder_id ?? ""),
      lat: Number(item.location?.lat ?? 0),
      lon: Number(item.location?.lon ?? 0),
      crs: String(item.location?.crs ?? "EPSG:4326")
    })).filter((item) => item.facilityId),
    villageTransformerCandidates: service.map((item) => String(item.facility_id ?? "")).filter(Boolean).sort(),
    villageTransformerDetails: service.map((item) => ({
      facilityId: String(item.facility_id ?? ""),
      feederId: String(item.feeder_id ?? ""),
      lat: Number(item.location?.lat ?? 0),
      lon: Number(item.location?.lon ?? 0),
      crs: String(item.location?.crs ?? "EPSG:4326")
    })).filter((item) => item.facilityId),
    villageTransformerGroups,
    footprintConfidence: resolution.topology_confidence,
    topologyPrior: resolution.topology_prior ?? [],
    protectionZone: resolution.protection_zone
      ? {
          gate: resolution.protection_zone.gate,
          devices: resolution.protection_zone.devices ?? [],
          coverage: resolution.protection_zone.coverage,
          downstreamMeterCount: resolution.protection_zone.downstream_meter_count
        }
      : null,
    matchedClues: resolution.matched_clues ?? [],
    excludedReason: resolution.excluded_reason,
    coreCoverage: resolution.core_coverage,
    outageLevel: resolution.outage_state ?? "UNDETERMINED",
    requiredConfirmation: resolution.required_confirmation ?? [],
    locationEvidence: resolution.location_evidence
      ? {
          status: resolution.location_evidence.status,
          usedForTopology: Boolean(resolution.location_evidence.used_for_topology),
          source: resolution.location_evidence.source,
          accuracyM: resolution.location_evidence.accuracy_m,
          searchRadiusM: resolution.location_evidence.search_radius_m,
          candidateCount: resolution.location_evidence.candidate_count
        }
      : null
  };
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      accessCode?: string;
      text?: string;
      location?: { lat?: number; lon?: number; accuracyM?: number; source?: string };
    };
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
    let location: { lat: number; lon: number; accuracy_m?: number; source?: string } | undefined;
    if (body.location) {
      const lat = Number(body.location.lat);
      const lon = Number(body.location.lon);
      const accuracyM = body.location.accuracyM == null ? undefined : Number(body.location.accuracyM);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        return NextResponse.json({ error: "INVALID_LOCATION" }, { status: 400 });
      }
      if (accuracyM != null && (!Number.isFinite(accuracyM) || accuracyM < 0 || accuracyM > 100000)) {
        return NextResponse.json({ error: "INVALID_LOCATION_ACCURACY" }, { status: 400 });
      }
      location = {
        lat,
        lon,
        ...(accuracyM == null ? {} : { accuracy_m: accuracyM }),
        source: String(body.location.source ?? "web_tester_location").slice(0, 64)
      };
    }

    const baseUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
    const apiKey = process.env.OUTAGE_INTEGRATION_API_KEY || process.env.AIS_INBOUND_API_KEY;
    if (!baseUrl || !apiKey) {
      return NextResponse.json({ error: "TOPOLOGY_API_UNAVAILABLE" }, { status: 503 });
    }
    const apiBaseUrl = normaliseApiBaseUrl(baseUrl);
    const response = await fetch(`${apiBaseUrl}/api/v1/outage-reports/resolve`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey
      },
      body: JSON.stringify({
        schema_version: "outage-report.v1",
        source: {
          channel: "WEB_TESTER",
          event_id: `webtest-${crypto.randomUUID()}`,
          occurred_at: new Date().toISOString()
        },
        message: { text },
        ...(location ? { location } : {})
      })
    });
    const data = (await response.json().catch(() => ({}))) as { resolution?: APIResolution };
    if (!response.ok || !data.resolution) {
      console.error("buengkan topology API resolve failed", { status: response.status });
      return NextResponse.json({ error: "TOPOLOGY_API_RESOLVE_FAILED" }, { status: 502 });
    }
    return NextResponse.json(adaptResolution(data.resolution), {
      headers: { "Cache-Control": "no-store" }
    });
  } catch {
    return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  }
}
