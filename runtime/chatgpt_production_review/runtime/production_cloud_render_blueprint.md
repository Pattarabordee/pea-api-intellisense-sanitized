# Render Blueprint Notes

File: `render.yaml`

## Services

- `pea-api-intellisense-api`: Go API, Docker runtime, health check `/health`
- `pea-api-intellisense-web`: Next.js operator/demo console
- `pea-api-intellisense-postgres`: managed PostgreSQL store

## Required Manual Secrets

```text
AIS_INBOUND_API_KEY
```

`DATABASE_URL` is injected from Render Postgres. Do not put it in GitHub.

## AIS Endpoint After Deploy

```http
POST https://<render-api-host>/api/v1/ais/outage-verifications
GET  https://<render-api-host>/api/v1/ais/outage-verifications/{request_id}
GET  https://<render-api-host>/health
```

## Current Safety Position

Cloud endpoint can accept AIS shadow traffic after smoke test passes. Customer-facing Auto ETR remains blocked.
