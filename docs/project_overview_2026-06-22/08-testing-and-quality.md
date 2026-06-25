# Testing And Quality

## Verification Run During This Refresh

Commands run successfully:

```powershell
python -m ais_etr validate-env
python -m ais_etr sample-eval
python -m ais_etr summary
```

Results:

| Check | Result |
| --- | --- |
| Environment validation | `ok: true` |
| Parser sample total | 24 |
| Parser sample parsed | 23 |
| Parser success rate | 0.958 |
| Expectation pass rate | 1.0 |
| Runtime summary | SQLite queryable |

Full test run after creating this handbook:

```text
python -m unittest discover -s tests -v
Ran 214 tests in 20.546s
FAILED (errors=2)
```

Result summary:

| Result | Count |
| --- | ---: |
| Passed | 212 |
| Errors | 2 |

Both errors are in `tests/test_shadow_operations.py` and point to the same runtime issue:

```text
NameError: name '_owner_response_file_profile' is not defined
```

Failing tests:

- `test_owner_response_templates_and_validator_keep_short_truth_out_of_gate`
- `test_simple_ais_mapping_response_validation_only_stages_confirmed_rows`

This refresh only added Markdown handbook files; no production code was changed.

Go API test attempt:

```text
go test ./...
go : The term 'go' is not recognized ...
```

Meaning: Go toolchain is not available in this shell/PATH, so Go tests were not executed locally. Next.js build was not run because this task changed documentation only.

## Test Inventory

The `tests/` directory covers broad behavior, including:

- parser,
- matcher,
- pipeline,
- registry,
- evaluation,
- planned outage,
- Webex export/replay/audit,
- AIS truth import/matching,
- AIS inbound API,
- confidence gate,
- cloud production,
- daily refresh,
- data integrity,
- ReportPO/SFSD context,
- production path sanitized export,
- notification policy/replay/time readiness,
- model scope/challengers.

## CI Quality Gates

`.github/workflows/production-cloud-ci.yml` defines:

| Job | Purpose |
| --- | --- |
| `python-guardrails` | Runs production path guardrail test and sanitized export scan. |
| `go-api` | Runs `go test ./...` in `apps/api-go`. |
| `next-console` | Runs `npm ci`, `npm audit --audit-level=moderate`, and `npm run build`. |

## Quality Expectations For Future Changes

- Small runnable test for every non-trivial logic change.
- Prefer Python standard library, PowerShell, SQLite, CSV, Markdown.
- Keep changes inside existing module style when possible.
- Add broad tests only when touching shared gates, notification behavior, or trust-boundary validation.
- Do not add UI or service complexity when a CLI/report covers the operator need.

## High-Risk Areas To Test Before Changing

| Area | Why risky |
| --- | --- |
| `ais_etr/ais_inbound.py` | Public request boundary, redaction, callback behavior, duplicate/idempotency. |
| `ais_etr/notification_policy.py` | Determines customer-facing gate class. |
| `ais_etr/confidence_gate.py` | Converts readiness/model results into green/amber/red/monitor decisions. |
| `ais_etr/data_integrity.py` | Prevents wrong truth source from entering model/gates. |
| `ais_etr/production_path.py` | Sanitized export and production readiness gate. |
| `apps/api-go/internal/sendcontrol/` | Production-path send decision safety. |
| `apps/api-go/internal/storage/` | Durable cloud evidence. |

## Manual QA Checklist

- Confirm `validate-env` still returns `notification_mode: shadow`.
- Confirm `summary` rows are queryable.
- Confirm green gate still says blocked unless explicitly approved.
- Confirm sanitized export status is PASS before external review.
- Confirm web console does not show secrets, raw Webex, full meter, PEANO list, or customer identity.
- Confirm cloud callback transport is dry-run unless separately approved.
