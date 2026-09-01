# Incident Priority Queue — LIVE_SHADOW Read-Only Runtime Acceptance — 2026-09-01

Status: `LIVE_SHADOW_READ_ONLY_ACCEPTED / NOT_PROMOTED / FRESH_PRIORITY_PATH_NOT_YET_PROVEN`

## Scope

This acceptance closes the isolated read-only runtime gate for the Incident Priority Queue on the current PEA Intellisense baseline. It proves that a real durable Incident Correlation incident can reach the operator queue through the server-side shadow feed without synthetic fallback, while stale priority evidence fails closed to `UNRATED` instead of being fabricated.

This is NOT a canonical-runtime promotion and does NOT prove the fresh real-priority path yet.

Code lane:
- worktree: `D:\PEA-Intellisense-priority-queue-current`
- branch: `feat/incident-priority-queue-current-20260901`
- runtime-tested web code commit: `a4e085bebcd53e91d9372758a69a39bb8b47b6bb`
- read-only correlation-worker control introduced at commit `e3c4220`
- `report_count` feed-preservation fix: `19ef153`
- temporary CI Windows-artifact step removed by `a4e085b`

## Final code CI before runtime acceptance closure

Production Cloud CI run: `33531582851`

PASS:
- Go API tests
- Python guardrails + sanitized export
- Next.js install/audit/build

The Node.js 20 deprecation messages from GitHub Actions are non-failing upstream action warnings.

## Isolated runtime topology

Candidate-only loopback ports were used temporarily:
- API candidate: `127.0.0.1:18092`
- web candidate: `127.0.0.1:18131`
- n8n read-only execution-history proxy: `127.0.0.1:18140`

Canonical runtime remained unchanged at `127.0.0.1:18090`.

Candidate API guardrails:
- `RUNTIME_PROFILE=pea-current`
- `mode=shadow`
- `production_send=blocked`
- `RUN_DB_MIGRATIONS=false`
- `INCIDENT_CORRELATION_MODE=shadow`
- `INCIDENT_CORRELATION_WORKER_ENABLED=false`
- loopback only

No new scheduled task/service, firewall rule, public ingress or persistent deployment was created for this acceptance.

## Real durable incident result

The read-only aggregate projection returned one real durable correlated incident candidate from PostgreSQL-backed Incident Correlation state:

- area: `BKN`
- feeder: `BUA03`
- `report_count=4`
- transformer: `null` because a unique transformer is not proven
- affected customers: `null` because Incident Correlation v1 has no authoritative impact count
- evidence strength: `MODERATE`
- status: `NEW`

The queue/feed preserved `report_count=4`. It did not reinterpret report count as affected-customer count.

Raw ticket identifiers and raw internal cluster identifiers were not exposed by the aggregate contract. The emitted incident reference remained the privacy-safe correlation incident identifier.

## Priority result — correct stale fail-closed behavior

The latest available successful `PEAPriorityAdapterV01` execution was execution `515`.

At final acceptance it was approximately 477 minutes old, while the freshness gate was 15 minutes.

Therefore the priority source correctly became stale/unavailable:
- `priority_level=UNRATED`
- `priority_score=null`
- `priority_state=UNAVAILABLE`
- no new n8n execution was triggered
- no priority score was manufactured to make the demo appear live

This proves the stale-priority safety path, not the fresh-priority path.

## Feed/UI result

`incident-queue-feed.v1` acceptance:
- source health: `LIVE_SHADOW`
- incident source: healthy real durable shadow evidence
- priority source: unavailable because stale
- synthetic fallback: `false`
- real incident rendered at `/incident-priority`
- root `/` remained the existing Mission Control page

`LIVE_SHADOW` in this milestone means the incident feed itself is genuinely reading shadow operational evidence. It does not mean every optional decision-support source is fresh.

## Safety verification

Acceptance confirmed:
- customer send enabled: `false`
- crew dispatch enabled: `false`
- n8n workflow triggered by acceptance: `false`
- n8n SQLite access: read-only
- correlation worker in candidate: `false`
- DB migrations: `false`
- firewall changed: `false`
- public ingress changed: `false`
- candidate ports closed after test: `true`

After candidate teardown:
- canonical API: `ok / shadow / blocked`
- n8n readiness: `ok`

## Canonical runtime evidence

Acceptance artifact:

`E:\PEA-Intellisense\artifacts\acceptance\INCIDENT_PRIORITY_LIVE_SHADOW_RUNTIME_ACCEPTANCE_2026-09-01.json`

SHA-256:

`E69F0518A345C77724CAF56F401335DA471601973855BD88D4D5EBFD48759A0B`

Artifact records:
- runtime-tested web commit `a4e085b...`
- CI run `33531582851`
- `report_count=4`
- stale priority execution `515`
- `LIVE_SHADOW`
- no synthetic fallback
- candidate ports closed after teardown
- canonical API and n8n healthy after teardown

## Milestone decision

Milestone is now:

`LIVE_SHADOW_READ_ONLY_ACCEPTED`

This milestone allows the project to proceed to the next validation gate. It does NOT authorize persistent deployment or canonical runtime promotion.

## Remaining gate before Persistent Shadow Pilot

Obtain a naturally occurring fresh successful `PEAPriorityAdapterV01` execution and rerun the same read-only E2E without triggering the workflow solely for test data.

Acceptance should prove:
1. real durable incident evidence;
2. fresh `priority-adapter-v0.1` execution;
3. exact compatible service area;
4. freshness gate PASS;
5. upstream `queue_rank` preserved;
6. no invented score scale or cross-area BKN/PKN global ranking;
7. `/incident-priority` renders the real fresh priority signal;
8. shadow/blocked/no-send/no-dispatch guardrails remain intact.

Only after that gate should a persistent Shadow Pilot runtime be considered.
