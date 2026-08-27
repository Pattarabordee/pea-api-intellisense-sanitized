# PEA Current Runtime Profile

`RUNTIME_PROFILE=pea-current` is the on-prem PEA Intellisense runtime boundary.

It deliberately excludes AIS/ETR legacy behavior while leaving `legacy-full` as the backward-compatible default for existing CI/Render paths.

## pea-current rules

- requires `OUTAGE_INTEGRATION_API_KEY`;
- does not require `AIS_INBOUND_API_KEY`;
- hides AIS inbound, AIS truth-interval, and legacy AIS metrics routes;
- defaults the HTTP listener to `127.0.0.1` during `pea-current` pre-cutover runtime;
- `LISTEN_ADDRESS` is an explicit operator override; do not expose a non-loopback listener before the network/cutover gate authorizes it;
- applies only current PEA migrations:
  - Bueng Kan tester feedback;
  - outage resolution;
  - secondary validation;
  - unknown-place queue;
  - planned-outage shadow;
  - Incident Correlation shadow + jobs;
- preserves shadow/fail-closed semantics;
- does not authorize production send or Runtime Authority cutover.

On-prem staging must select this profile explicitly. Do not infer it from hostname or environment.

## Least-privilege database startup

Use the one-shot `cmd/pea-db-migrate` command with the migration-owner credential.
For long-lived on-prem processes, secrets may be supplied through ACL-restricted files using
`OUTAGE_INTEGRATION_API_KEY_FILE` and `DATABASE_URL_FILE`; direct environment values still take precedence
for backward compatibility. An unreadable/missing secret file fails closed at configuration validation.
Run the long-lived API with the application credential and `RUN_DB_MIGRATIONS=false`.
The default remains `RUN_DB_MIGRATIONS=true` for backward compatibility with existing legacy-full deployments.
