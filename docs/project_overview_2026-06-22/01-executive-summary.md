# Executive Summary

## One Sentence

PEA API Intellisense / AIS ETR is a shadow-first pilot that turns AIS/Webex outage evidence into traceable grid context, AIS impact matching, and ETR candidates, while keeping production customer sends blocked until truth, model, topology, infrastructure, and owner gates pass.

## What The Project Is

This project has grown from a local Python MVP into a broader pilot system:

- Local Python package `ais_etr/` for Webex polling/replay, parsing, matching, quantile ETR prediction, AIS truth import, ReportPO/SFSD context, readiness reports, and gate packs.
- Runtime SQLite database at `runtime/ais_etr.sqlite` for queryable evidence.
- AIS inbound verification API in Python for local/shadow testing.
- Production-path Go API under `apps/api-go/` with PostgreSQL storage and send-control policy.
- Next.js operator/demo console under `apps/web-next/`.
- Render cloud blueprint in `render.yaml`.
- Runtime evidence packs under `runtime/` and `runtime/cloud_pilot/`.

## What It Is Not Yet

- Not a production Auto ETR sender.
- Not a replacement for AIS outage/restore truth.
- Not approved to use feeder fallback as customer-facing impact truth.
- Not approved to treat ReportPO/SFSD/PEA context as customer restoration truth.
- Not allowed to expose raw Webex text, room ids, PEANO lists, or customer identity.

## Current Readiness

| Lane | Status | Meaning |
| --- | --- | --- |
| Local shadow pipeline | Working | Webex messages, parsed events, predictions, and shadow notifications exist in SQLite. |
| AIS registry | Partial | 271 confidence-eligible assets, 119 `NO_METER` backlog rows. |
| Parser sample corpus | Passing sample eval | 24 sample cases, 23 parsed, expectation pass rate 1.0. |
| Baseline model | Gate fail | q50 MAE 19.82 min, target <= 16 min. |
| Green Auto ETR gate | Blocked | 0 green rows, target 30 minimum. |
| Local inbound API | Shadow pilot evidence exists | 35 inbound requests in SQLite, 4 non-smoke. |
| Cloud endpoint | Package ready, real traffic not proven | Cloud health/database ok, but cloud non-smoke count is 0 in latest cloud report. |
| Production infra | Blocked | Owner approval and ops drills still pending. |
| Customer-facing Auto ETR | Blocked | Gate and owner approvals not met. |

## Business Goal

The business goal is to reduce manual back-and-forth when AIS reports AC main fail or outage impact:

1. AIS sends a governed request or PEA sees a Webex outage signal.
2. PEA resolves grid context without exposing raw customer identity.
3. The system checks protection/device evidence and affected AIS assets.
4. The system produces a shadow response and ETR candidate with uncertainty.
5. Operators and owners evaluate evidence before any production customer send.

## Key Tension

The system can already produce plausible ETR candidates, but governance correctly blocks production because:

- AIS truth coverage is still incomplete.
- Current green subset is too small.
- Model MAE gate is not met.
- Some rows depend on feeder fallback, missing active AIS evidence, momentary Webex operations, or PEA context that is not approved as truth.
- Cloud operations still need owner approval, backup/restore drill, and permanent production controls.

## Hard Rules

- Keep `mode = shadow`.
- Keep `production_send = blocked`.
- Use AIS outage/restore as customer-facing truth.
- Treat Webex as trigger/device evidence.
- Treat PEA/SFSD/ReportPO as context/quarantine unless approved.
- Every non-trivial logic change needs a small runnable test.

