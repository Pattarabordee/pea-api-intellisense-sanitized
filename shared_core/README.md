# Shared Core

`shared_core/` contains reusable components that do not depend on AIS/ETR business semantics.

Current extracted component:
- `shared_core.incident_correlation` — calibration, cluster replay and blind human-review tooling.

Shared-core code must remain domain-neutral, deterministic where required, privacy-safe at its review/export boundary, and covered by tests.
