# PEA Intellisense

This repository contains the sanitized application and evaluation code used by the current PEA Intellisense project.

## Current project boundary

PEA Intellisense is not the AIS/ETR project. AIS/ETR code remains in this repository only as a clearly isolated legacy/reference lane until its dependency removal is completed.

Current PEA Intellisense scope includes:
- customer-service chatbot report intake and safe status readback;
- Bueng Kan place/GIS resolution and electrical topology evidence;
- Incident Correlation shadow runtime and its n8n read contract;
- blind human review, calibration and cluster-replay tooling;
- shadow-mode safety controls and deployment/integration tests.

## Source lanes

- `apps/` — current PEA Intellisense application/runtime code.
- `shared_core/` — reusable code that has no AIS/ETR business semantics.
- `docs/architecture`, `docs/evaluation`, `docs/integrations` — current design and validation contracts.
- `ais_etr/` — AIS/ETR-specific legacy/reference lane. Do not treat it as a current PEA Intellisense requirement.
- `docs/legacy/ais-etr/` — AIS/ETR historical documentation.

## Safety state

- Incident Correlation remains shadow-only unless explicitly promoted through approved gates.
- Production send remains blocked unless separately authorized.
- GIS/topology is evidence/context, not customer-facing outage truth.
- AIS/ETR requirements must not be inherited into PEA Intellisense unless explicitly adopted as a shared capability.

## Development authority

The organization Server is the current Development / Integration Authority. Runtime Authority cutover is a separate migration gate.
