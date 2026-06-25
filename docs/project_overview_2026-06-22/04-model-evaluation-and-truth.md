# Model, Evaluation, And Truth

## Current Model Artifact

Artifact: `runtime/model_quantiles.json`

| Field | Value |
| --- | --- |
| Model version | `baseline-quantile-20260616174734` |
| Estimator | `quantile_baseline` |
| Training row count in artifact | 4,603 |
| Holdout train rows | 3,682 |
| Holdout test rows | 921 |
| q50 MAE | 19.82 min |
| q10-q90 coverage | 0.754 |
| Gate status | `gate_fail` |

Gate target:

| Metric | Target | Current |
| --- | ---: | ---: |
| q50 MAE | <= 16 min | 19.82 min |
| q10-q90 coverage | 0.75-0.90 | 0.754 |

Global quantiles:

| Quantile | Minutes |
| --- | ---: |
| q10 | 14 |
| q25 | 24 |
| q50 | 36 |
| q75 | 50 |
| q90 | 71 |

## Why It Is A Baseline

`ais_etr/model.py` uses a dependency-light quantile baseline:

- Grouped quantiles by feeder.
- Grouped quantiles by device type.
- Grouped quantiles by feeder + device type.
- Global fallback quantiles.

The public prediction shape is intentionally close to a future quantile model:

- `etr_minutes_p50`
- `q10`, `q25`, `q75`, `q90`
- `risk_level`
- `model_version`

## Truth Hierarchy

| Source | Allowed use |
| --- | --- |
| AIS site/meter outage/restore | Preferred customer-facing truth and model evaluation truth. |
| AIS Add Field / AC main fail truth imports | Candidate AIS truth after validation, rejects, and short-duration review. |
| ReportPO first restore | Provisional PEA event-level context or fallback evaluation, not preferred AIS customer truth. |
| ReportPO `EVENT_ETR_TIME` | Process/forecast behavior only, not actual restoration truth. |
| ReportPO `EVENT_END_TIME` / ticket close | Blocked as customer restoration truth. |
| Webex | Trigger/device/time evidence, not restoration truth. |
| SFSD/PEA lifecycle | Context only unless owner-approved; still not AIS outage/restore truth. |

## Current Green Gate

Source: `runtime/green_gate_tracker.md`

| Metric | Value |
| --- | ---: |
| AIS truth metric rows | 79 |
| Current green rows | 0 |
| Minimum green rows target | 30 |
| Additional green rows needed | 30 |
| Gate status | `blocked_too_few_green_rows` |

Meaning:

- The project has AIS-truth rows for backtest work.
- None currently meet green automatic ETR eligibility.
- Auto ETR production remains blocked even if cloud API is healthy.

## Customer-Facing Gate

`ais_etr/notification_policy.py` classifies payloads as:

- `shadow_etr_candidate`: confident protection match plus sustained-like Webex state or active AIS confirmation.
- `review_only`: no match, feeder fallback, momentary/short Webex operation without active AIS confirmation, or insufficient state.

Important rules:

- Feeder fallback is review-only.
- Momentary <=1 minute and short <=5 minute Webex operations require active AIS outage confirmation.
- A confident match alone is not enough when Webex state is momentary/short.

## Challenger And Diagnostic Lanes

The repo contains multiple model/evaluation diagnostics:

- `ais_only_remaining_time_challenger`
- `ais_only_lifecycle_challenger`
- `ais_history_challenger`
- `active_state_remaining_challenger`
- `webex_elapsed_challenger`
- `long_outage_challenger`
- `truth_quality_audit`
- `shadow_error_diagnostics`
- `incident_clustering`

These are useful for learning why the baseline fails, especially for:

- long outages,
- active AIS alarms,
- missing lifecycle/cause fields,
- repeated Webex updates,
- event clustering,
- short/momentary events near the sustained-outage threshold.

## Known Model Risks

- Current q50 MAE misses the <=16 minute gate.
- Coverage only barely clears the lower bound and may hide wide intervals.
- Historical ETR timestamp is default/process-heavy, especially 90/120/180 minute patterns, so it must not become the target label.
- Short and momentary events can distort MAE and customer-facing relevance.
- Missing AIS active outage confirmation blocks many otherwise tempting candidates.
- PEA context can improve features, but using it as truth would break the trust boundary.

## Promotion Bar

Before any customer-facing Auto ETR:

1. AIS truth rows must be sufficient and validated.
2. Green rows must reach the minimum evidence count.
3. q50 MAE and q10-q90 coverage must pass on the green subset.
4. Topology owner must approve downstream mapping where needed.
5. Callback/API contract owner must approve.
6. Production owner must approve.
7. `production_send` must move only through an explicit gate, not by config drift.

