# Production Gate Owner Packet

- Generated: `2026-06-22T02:30:08Z`
- Mode: `shadow`
- Production send: `blocked`
- Decision: `AUTO_ETR_NO_GO`

## Gate Snapshot

- Green rows: `0` / `30`
- Additional green rows needed: `30`
- Green q50 MAE: ``
- Green q10-q90 coverage: ``
- Production gate status: `blocked_too_few_green_rows`
- Cloud endpoint: `READY_FOR_DEPLOYMENT_PACKAGE`
- Production infra: `BLOCKED_PENDING_OWNER_OR_CONTROL`
- Auto ETR: `BLOCKED_GREEN_GATE`

## Cloud Evidence

- API: `https://pea-api-intellisense-api.onrender.com`
- Health: `ok`
- Database: `ok`
- Total cloud requests: `5`
- Real AIS cloud requests: `0`
- Latest request: `AIS-CLOUD-SMOKE-20260622061708` / `COMPLETED` / `production_send=blocked`

Smoke/demo requests prove API, DB, and console flow only. They do not count toward green model gate.

## Top Blockers

| Blocker | Rows |
| --- | ---: |
| `no_affected_ais` | 1110 |
| `low_match_confidence` | 1110 |
| `pea_quarantined` | 1063 |
| `missing_prediction_interval` | 842 |
| `missing_prediction` | 842 |
| `missing_ais_truth` | 421 |
| `wide_prediction_interval` | 371 |
| `long_outage_risk` | 245 |
| `no_active_ais_evidence` | 78 |
| `missing_protection_match` | 47 |
| `momentary_webex_requires_review` | 36 |

## Owner Work Queue

| Owner lane | Rows |
| --- | ---: |
| `pea_topology_owner` | 1063 |
| `ais_truth_owner` | 499 |
| `model_owner` | 1 |
| `cloud_ops_owner` | 1 |

## Approval Ask

- AIS truth owner: provide outage/restore truth for prioritized WebEx/protection events.
- PEA topology owner: approve downstream protection mapping; feeder-only stays non-green.
- Model owner: improve uncertainty and validate q50 MAE/coverage on green subset.
- Operations owner: review momentary/long-outage conflicts and approve context use.
- Gateway/security owner: approve auth, monitoring, backup/restore, incident process, and emergency off.

## Guardrails

- Do not enable customer-facing Auto ETR from this packet.
- `production_send` remains `blocked` until infra gate, green model gate, callback approval, and owner approval pass.
- AIS outage/restore remains customer-facing truth.
- Reports must not include API key, DB URL, token, room ID, verbatim WebEx text, full meter/PEANO, or customer identity.

## Outputs

- gap_actions_csv: `D:\PEA Intellisense data\runtime\cloud_pilot\production_gate_gap_actions.csv`
- markdown: `D:\PEA Intellisense data\runtime\cloud_pilot\production_gate_owner_packet.md`
- json: `D:\PEA Intellisense data\runtime\cloud_pilot\production_gate_owner_packet.json`
