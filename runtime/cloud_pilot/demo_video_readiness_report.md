# Demo Video Readiness Report

Generated: 2026-06-22

## Status

- Demo console: READY FOR RECORDING
- Cloud API: READY FOR AIS SHADOW PILOT
- PostgreSQL store: READY FOR PILOT EVIDENCE
- Real AIS cloud hit: NOT YET RECEIVED
- Auto ETR production: BLOCKED
- Local shadow model rehearsal: READY_FOR_SHADOW_DEMO

## What Is Ready

- Executive demo path now shows the full story:
  - Manual AIS phone call workflow
  - API request workflow
  - PEA meter-to-feeder trace
  - Protection evidence gate
  - Cause lane
  - ETR candidate
  - Shadow response
- UI remains English-first for recording.
- Demo fallback uses synthetic/redacted data only.
- Guardrails remain visible:
  - `mode = shadow`
  - `production_send = blocked`
  - `Auto ETR not enabled`
  - `AIS outage/restore stays truth`
- Runtime model rehearsal evidence exists at `runtime/ais_inbound_model_demo_rehearsal.md`:
  - AIS request -> protection evidence -> cause lane -> ETR candidate -> shadow callback
  - `production_send=blocked`
  - request type is smoke/demo, not real AIS cloud traffic

## Current Truth

- The cloud endpoint can receive AIS requests.
- The web console can show live API data when configured.
- The first real AIS cloud request is still pending.
- Demo evidence values are synthetic, not production customer or device records.
- Local model rehearsal proves the intended chain can be demonstrated, but it must not be described as a real AIS production case.
- Customer-facing Auto ETR must remain blocked until green-gate metrics and owner approval pass.

## Recording Checklist

- Open `https://pea-api-intellisense-web.onrender.com`.
- Check first viewport has:
  - title: `From phone call to governed API ETR trace`
  - manual vs API workflow
  - guarded trace card
  - production sends = `0`
- Do not open:
  - Render environment variable page
  - private API key file
  - raw database URL
  - verbatim WebEx or customer files
- Use `runtime/cloud_pilot/demo_video_recording_script_th.md` as presenter script.

## Remaining Work After Video

- Wait for AIS real cloud test.
- Capture first real `request_id`, `received_at`, `status`, `callback_status`, `production_send`.
- Build green subset from real pilot cases.
- Harden monitoring, backup/restore drill, and key rotation drill before production approval.
