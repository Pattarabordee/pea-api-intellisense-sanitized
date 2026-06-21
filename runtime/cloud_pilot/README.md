# PEA API Intellisense Cloud Pilot Package

This folder is a provider-neutral container package for the AIS inbound API.

## Status

- Mode: `shadow`
- Production send: `blocked`
- Customer-facing Auto ETR: blocked until green gate and owner approval pass
- Current package: ready for cloud/VM deployment review, not proof of production approval

## Minimal Local Container Test

1. Copy `.env.cloud.example` to `.env.cloud`.
2. Set `AIS_INBOUND_API_KEY` through a protected local value or secret manager.
3. Put the pilot SQLite DB at `runtime/cloud_pilot/data/ais_etr.sqlite`.
4. Run:

```powershell
docker compose -f runtime/cloud_pilot/docker-compose.yml up --build
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
```

## Production Guardrail

This package does not enable production callbacks or Auto ETR. It only removes the local tunnel dependency when deployed to an approved cloud/VM target.
