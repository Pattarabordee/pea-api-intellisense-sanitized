# Shadow Send Eligibility

This report gates shadow ETR sends by confidence. It does not send production AIS notifications and does not update model artifacts.

## Summary

- Rows: 1563
- AIS truth matched rows: 79
- Green auto candidates: 0
- Amber human review: 1
- Red blocked: 1141
- Monitor only: 421
- Green q50 MAE:  min
- Green q10-q90 coverage: 
- Production gate status: blocked_no_green_subset

## Eligibility Mix

| Status | Rows | MAE | Coverage | High-error | Auto p50 rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| `red_blocked` | 1141 | 111.77 | 0.564 | 54 | 0 |
| `monitor_only` | 421 |  |  | 0 | 0 |
| `amber_human_review` | 1 | 59.47 | 1 | 0 | 0 |

## Highest-Risk Backtest Rows

| Event | Time | Feeder | Device | Status | Stage | Error | Reasons |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| msg-1764c29edd61 | 2026-03-24T17:34:33.871000 | PFA09 | PFA09R-03 | red_blocked | long_outage_risk | 671.69 | no_active_ais_evidence;wide_prediction_interval;long_outage_risk |
| msg-40006145f105 | 2026-03-24T17:47:27.281000 | PFA09 | PFA09R-03 | red_blocked | long_outage_risk | 671.53 | no_active_ais_evidence;wide_prediction_interval;long_outage_risk |
| msg-344281582c47 | 2026-05-13T10:30:06.452000 | WWA10 | WWA10VR-101 | red_blocked | long_outage_risk | 622.48 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |
| msg-cfe8250368b3 | 2026-04-28T23:27:43.734000 | SEK06 | SEK06VR-105 | red_blocked | long_outage_risk | 349.4 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |
| msg-6670f07a83e9 | 2026-04-28T23:35:37.952000 | SEK06 | SEK06VR-105 | red_blocked | long_outage_risk | 298.99 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |
| msg-303722e13bdd | 2026-05-29T08:18:42.310000 | PFA03 | PFA03VB-01 | red_blocked | long_outage_risk | 265.91 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |
| msg-46137577f230 | 2026-05-22T00:37:52.056000 | SEK05 | SEK05VR-101 | red_blocked | long_outage_risk | 233.19 | no_active_ais_evidence;wide_prediction_interval;long_outage_risk |
| msg-b433e80664c7 | 2026-04-30T03:29:28.791000 | SEK06 | SEK06VR-105 | red_blocked | long_outage_risk | 212.86 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |
| msg-109e4578b33b | 2026-05-21T23:51:18.090000 | SEK05 | SEK05VR-101 | red_blocked | long_outage_risk | 206.96 | no_active_ais_evidence;wide_prediction_interval;long_outage_risk |
| msg-57f46317368a | 2026-04-29T07:04:14.370000 | SEK06 | SEK06VR-105 | red_blocked | long_outage_risk | 192.52 | no_active_ais_evidence;momentary_webex_requires_review;wide_prediction_interval;long_outage_risk |

## Guardrails

- AIS outage/restore remains the only customer-facing truth label.
- WebEx is trigger/device evidence only.
- PEA/SFSD/ReportPO quarantine rows are not used in metrics, features, fallback, or truth.
- No production AIS send is performed by these commands.
- Outputs omit source chat bodies, room identifiers, credentials, customer meter identifier lists, and customer identity fields.
