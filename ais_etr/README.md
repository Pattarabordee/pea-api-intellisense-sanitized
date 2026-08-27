# AIS / ETR legacy lane

Everything under `ais_etr/` is AIS/ETR-specific or retained for historical compatibility unless separately classified and extracted into `shared_core/`.

Rules:
- Do not add new PEA Intellisense functionality here.
- Do not import AIS/ETR business semantics into current PEA Intellisense runtime by default.
- Generic reusable code must be moved to `shared_core/` with tests before reuse.
- Removal of remaining AIS/ETR code requires dependency verification; do not delete this lane wholesale.
