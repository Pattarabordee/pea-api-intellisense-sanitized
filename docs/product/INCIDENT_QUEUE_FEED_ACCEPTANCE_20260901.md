# Incident Queue Read-Only Feed Acceptance — 2026-09-01

Status: PASS — CONSUMER/FEED BOUNDARY READY / REAL UPSTREAM NOT YET CONFIGURED

## Implemented

- Stable web endpoint: `GET /api/incidents/feed`.
- Page `/` now loads through the same server-side queue-feed loader instead of hard-coding the synthetic snapshot.
- Upstream contract: `incident-queue-feed.v1`.
- Server-only configuration:
  - `INCIDENT_QUEUE_FEED_URL`
  - optional `INCIDENT_QUEUE_FEED_API_KEY`
  - optional `INCIDENT_QUEUE_FEED_TIMEOUT_MS`
- Browser never receives the upstream URL or API key.
- Feed is read-only and `cache: no-store`.

## Guardrails

A live feed is accepted only when all required contracts remain true:

- `mode=shadow`
- `production_send=blocked`
- `authoritative_outage_truth=false`
- outer schema `incident-queue-feed.v1`
- inner schema `incident-priority.v1`
- inner source `priority_adapter_composed`
- live items must be `source_mode=PRIORITY_ADAPTER`
- duplicate `incident_id` or malformed item invalidates the feed rather than partially accepting it

The feed validator does not invent score thresholds, normalize score ranges, infer outage truth, or fuzzy-match incidents.

## Source health

UI and API expose one of:

- `LIVE_SHADOW`
- `NOT_CONFIGURED`
- `UPSTREAM_UNAVAILABLE`
- `CONTRACT_INVALID`

If a live source is not usable, the page falls back to the existing synthetic demo snapshot and labels the source visibly as fallback. Real and synthetic data are not silently mixed.

## Verification

- Next.js production build: PASS.
- `smoke:incident-feed`: 4/4 PASS
  - valid authenticated synthetic shadow feed -> `LIVE_SHADOW`
  - invalid guardrail -> `CONTRACT_INVALID` + visible synthetic fallback
  - upstream HTTP failure -> `UPSTREAM_UNAVAILABLE` + visible synthetic fallback
  - no configuration -> `NOT_CONFIGURED` + visible synthetic fallback
- `smoke:incident-compose`: 6/6 PASS regression.
- `smoke:priority-adapter`: 5/5 PASS regression.

All smoke sources are synthetic and prove transport/contract behavior only.

## Non-impact boundary

No n8n workflow was activated or modified in this slice. No organization-server runtime, API 18090, GIS, resolver, topology sidecar, firewall, customer send, or production-send state was changed.

## Remaining gate

The real approved shadow queue publisher/source still needs to be selected and exposed as a read-only `incident-queue-feed.v1` endpoint. Until `INCIDENT_QUEUE_FEED_URL` is configured, the operator page intentionally remains on visibly labeled synthetic fallback data.
