# PEA API Intellisense / AIS ETR

This repository is the sanitized source-of-truth export for the PEA API Intellisense / AIS ETR project.

## Current Truth

- Current mode: `shadow`
- Production send: `blocked`
- Controlled AIS API pilot: ready for shadow testing
- Production infrastructure: not yet approved
- Customer-facing Auto ETR: not yet approved

## Start Here

1. `AI_REVIEW_START_HERE.md`
2. `README_AIS_ETR_MVP.md`
3. `pea_pitching_executive_summary.md`
4. `runtime/PILOT_COMPLETE_README.md`
5. `runtime/go_no_go_summary.md`
6. `runtime/production_readiness_gate.md`

## What This Project Does

PEA API Intellisense receives AIS outage-verification requests, checks PEA grid context and evidence, and returns a safe shadow response with a traceable `request_id`.

The pilot proves the API, evidence store, audit trail, and operator handoff. It does not enable production Auto ETR.

## Key Guardrails

- Do not expose API keys, tokens, room ids, raw WebEx text, full meter/PEANO lists, or customer identity.
- Do not enable customer-facing Auto ETR until green-lane evidence, model thresholds, production infrastructure, and owner approval pass.
- AIS outage/restore remains the customer-facing truth source.

