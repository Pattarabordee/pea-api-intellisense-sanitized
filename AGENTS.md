# AIS ETR Agent Rules

This project uses a Ponytail-style rule: build the smallest correct thing, not the flashiest thing.

Before adding code, stop at the first option that works:

1. Do we need to build it at all?
2. Can the Python standard library, PowerShell, SQLite, or the current codebase already do it?
3. Can a small CLI/report cover the need before a service, framework, dashboard, or new dependency?
4. Can the change stay in the existing module and test style?
5. Only then add the minimum new code that works.

Do not cut these guardrails:

- Trust-boundary validation for AIS/WebEx/PowerBI inputs.
- Redaction of full meter numbers, PEANO lists, room ids, tokens, secrets, raw WebEx text, and customer identity.
- `mode = shadow` and `production_send = blocked` until the production gate is explicitly approved.
- AIS outage/restore remains the customer-facing truth source; PEA/SFSD/ReportPO stays context/quarantine unless owner-approved.
- SQLite/runtime evidence must stay queryable after a test request.
- Every non-trivial logic change needs a small runnable test.

Prefer:

- Standard library over new packages.
- SQLite/CSV/Markdown evidence before UI.
- Existing CLI patterns in `ais_etr/cli.py`.
- Existing runtime paths under `runtime/`.
- Small, operator-readable reports over broad abstractions.

Always-on agent skills:

- Apply `grill-me` behavior before committing to a plan or implementation: challenge weak assumptions, ask the hard missing questions, stress-test success criteria, edge cases, rollout risk, and guardrails. Explore repo facts first; do not grill the user about facts discoverable from files or runtime state.
- Apply `caveman` behavior as the default communication style at `lite` intensity for Thai/English project work: concise, low-filler, technically exact, no decorative prose. Drop compression when safety, irreversible actions, multi-step operator instructions, or user confusion needs clearer wording.
- If Codex skills are unavailable in another agent, emulate these two behaviors from this file. `grill-me` sharpens the plan; `caveman-lite` keeps answers short and useful.
- These skills do not override project guardrails: `mode = shadow`, `production_send = blocked`, redaction, trust-boundary validation, queryable SQLite evidence, and small runnable tests still win.

Reference: `runtime/tools/ponytail/AGENTS.md` was reviewed on 2026-06-20 and adapted here for this project.
