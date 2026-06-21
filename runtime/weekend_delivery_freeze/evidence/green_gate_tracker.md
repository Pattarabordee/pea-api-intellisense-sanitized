# Green Gate Tracker

This tracker answers how close the green subset is to production-gate evidence. It does not approve production sends.

- AIS truth metric rows: 79
- Current green rows: 0
- Minimum green rows target: 30
- Additional green rows needed: 30
- Green q50 MAE:  minutes
- Green q10-q90 coverage: 
- Gate status: `blocked_too_few_green_rows`
- Best threshold variant: ``

## Gate Checks

|metric|value|status|note|
|---|---|---|---|
|ais_truth_metric_rows|79|info|AIS outage/restore rows available for backtest.|
|green_rows|0|blocked|Rows currently eligible for automatic ETR backtest.|
|additional_green_rows_needed|30|blocked|Target minimum is 30 green rows.|
|green_q50_mae_minutes||blocked|Target <= 16 minutes.|
|green_q10_q90_coverage||blocked|Target 0.75-0.9.|
|green_high_error_rows|0|pass|High error threshold is >=60 minutes.|
|production_gate_status|blocked_too_few_green_rows|blocked|Human approval is still required even if metric gate passes.|
|best_shadow_policy_variant||unknown|Best threshold-calibration variant from the latest report.|

## Recommendation

- Keep automatic ETR blocked until enough fresh green AIS-truth rows pass both MAE and coverage gates.
- Treat this as a shadow evidence tracker, not a production approval.
