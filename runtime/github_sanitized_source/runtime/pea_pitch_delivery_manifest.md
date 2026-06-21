# PEA Pitch Delivery Manifest

Generated: 2026-06-20

## Main Deliverables

| Artifact | Use |
| --- | --- |
| `runtime/weekend_delivery_freeze/presentation/ais_etr_competition_6_slide_pitch.pptx` | Main 6-slide competition deck for the 5-7 minute judging format |
| `runtime/pea_pitch_competition_6_slide_script_th.md` | Thai timed script for the 6-slide competition deck |
| `runtime/weekend_delivery_freeze/presentation/ais_etr_ceo_cinematic_pitch.pptx` | CEO cinematic companion deck for executive storytelling, video, and optional Q&A |
| `runtime/pea_pitch_ceo_cinematic_script_th.md` | Thai timed script for the CEO cinematic companion deck |
| `runtime/weekend_delivery_freeze/presentation/ceo_cinematic_preview/deck_montage.webp` | CEO cinematic deck preview montage |
| `runtime/weekend_delivery_freeze/presentation/ais_etr_pea_approval_pitch_v2.pptx` | Main deck for PEA approval pitch |
| `runtime/weekend_delivery_freeze/presentation/preview/slide-06.png` | Live AIS API evidence preview |
| `runtime/weekend_delivery_freeze/presentation/preview/slide-08.png` | Business case preview |
| `runtime/weekend_delivery_freeze/presentation/preview/slide-10.png` | Approval ask preview |
| `runtime/pea_approval_business_case_th.md` | Thai business case, calculation logic, Design Thinking, BMC, Value Proposition |
| `runtime/pea_approval_pitch_addendum.md` | Live API evidence addendum from the AIS inbound pilot |
| `runtime/pea_pitch_strategy_canvas.md` | Strategy canvas and stakeholder framing |
| `runtime/pea_pitch_demo/index.html` | Static Web UI demo cockpit for PEA pitch |
| `runtime/pea_pitch_demo/self_check.ps1` | Runnable self-check for the static demo |
| `runtime/pea_pitch_video_walkthrough_script_th.md` | Thai 5-7 minute video/pitch script |
| `runtime/pea_pitch_demo_run_of_show_th.md` | File-opening order and demo checklist |
| `runtime/PILOT_COMPLETE_README.md` | Operator-first guide for opening, testing, and handing off the pilot |
| `runtime/go_no_go_summary.md` | Clear GO/NO-GO summary for pilot, production infra, and auto ETR |
| `runtime/pilot_completion_gate.md` | Final Pilot Complete gate across API, evidence, security, share pack, and guardrails |
| `runtime/pilot_complete_final_qa.ps1` | One-command final QA runner that keeps production_send blocked |
| `runtime/shareable_pea_pitch_pack.zip` | Final shareable pilot/pitch/demo package |

## Current Evidence Summary

- AIS inbound pilot status: `PILOT_COMPLETE` for controlled shadow pilot
- Pilot/API readiness: `100%`
- Real AIS requests captured: `3`
- Total inbound requests captured: `33`
- Latest real request: `AIS-20260620-0003`
- Endpoint health: `PASS`
- Mode: `shadow`
- Production send: `blocked`
- Production infrastructure: still local tunnel, not production hosting
- Production auto ETR: `BLOCKED_GREEN_GATE`

## Pitch Position

Ask PEA to approve the next controlled pilot step:

1. Continue AIS inbound API as the pilot channel.
2. Move from local tunnel to PEA-approved permanent HTTPS endpoint/API gateway.
3. Keep auto ETR production blocked.
4. Allow only status-only or human-approved responses until the evidence gate passes.
5. Assign owners for topology/GIS, AIS truth feed, and production infrastructure.

## Business Case Numbers

Planning scenarios in the deck and Thai business case:

| Scenario | Estimated annual benefit |
| --- | ---: |
| Conservative | 117,500 THB/year |
| Base case | 780,000 THB/year |
| Upside | 2,550,000 THB/year |

Formula:

```text
Annual benefit =
cases per year x minutes saved per case x people involved x cost per minute
+ avoided escalations
```

These are planning assumptions, not final accounting numbers. Replace them with PEA actual escalation/time-cost data when available.

NotebookLM strategic framing added to the 6-slide competition deck:

- Blindspot opportunity: `~48M THB/year` as strategic estimate/upside.
- API monetization potential: `6-8M THB/year` as subscription-model upside.
- These numbers must not be presented as realized savings until a finance owner validates assumptions.

## QA Completed

- Competition deck generated successfully: `6` slides for 5-7 minute judging format.
- Competition deck visual preview rendered successfully.
- CEO cinematic deck generated successfully: `12` slides for 7-10 minute executive/video storytelling.
- CEO cinematic visual preview and contact sheet rendered successfully.
- CEO cinematic deck uses English on-slide text with Thai spoken script.
- CEO cinematic deck upgraded after Browser ChatGPT visual critique round 2:
  - safety strip made larger and persistent
  - slide 6 demo screenshot enlarged/cropped for readability
  - slide 11/12 decision hierarchy clarified around controlled 3-month shadow pilot
  - estimate/upside labels made explicit and safer
- Browser ChatGPT follow-up round 3 was attempted with updated images and then text-only, but the web session stalled at image/pro thinking. Final acceptance uses rendered-preview QA plus the earlier critique checklist.
- Interactive role-play game demo self-check passed and first viewport fits 1440x810 without page scroll.
- Deck generated successfully: `11` slides
- Preview PNGs rendered successfully
- Visual spot check completed for:
  - Slide 06: live API evidence
  - Slide 08: business case
  - Slide 10: approval ask
- Privacy scan passed:
  - no API key pattern
  - no token/secret pattern
  - no original WebEx message content pattern
  - no full meter number pattern
  - no room id pattern
- Static demo self-check passed:
  - required pitch sections present
  - calculator script present
  - forbidden secret/customer patterns absent
- Video/run-of-show checks passed:
  - timed script present
  - money scenario present
  - local tunnel answer present
  - AIS pilot-test answer present
  - production blocked wording present
- Guardrail wording present:
  - `shadow`
  - `production_send=blocked`
  - local tunnel is not production infrastructure
- Pilot Complete final QA passed:
  - `runtime/pilot_complete_final_qa.ps1`
  - `pilot_complete_status=PILOT_COMPLETE`
  - `production_send=blocked`
  - `production_auto_etr_status=BLOCKED_GREEN_GATE`
  - share pack rebuilt and synced

## Readiness

| Area | Status |
| --- | --- |
| AIS API pilot | `Pilot Complete`, controlled shadow pilot |
| PEA approval pitch deck | `95%` |
| Thai business case | `95%` |
| Static Web UI demo | `95%` |
| Video/pitch runbook | `95%` |
| Demo evidence | `90%` |
| Production infrastructure | `60%`, needs PEA IT approval |
| Auto ETR production | `0%`, `BLOCKED_GREEN_GATE` |

## Remaining Work

Before presenting:

- Open the PPTX once in PowerPoint and confirm font rendering: `5-10 minutes`
- Open the static demo in a browser and test the calculator once: `2-3 minutes`
- Record demo/video walkthrough using the run-of-show: `45-60 minutes`

After PEA approval:

- Stand up permanent HTTPS/API gateway
- Rotate or harden API authentication
- Add production monitoring/restart policy
- Keep shadow/status-only until green lane gate passes
