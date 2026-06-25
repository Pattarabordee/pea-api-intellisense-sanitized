# Claude Project Instructions

Read `AGENTS.md` first and follow it as the source of truth for this project.

Always apply the same two working modes requested by the project owner:

- `grill-me`: pressure-test plans, assumptions, edge cases, risk, and acceptance criteria before doing meaningful work.
- `caveman-lite`: keep communication concise, low-filler, and technically exact. Use fuller wording only when safety, operator steps, or ambiguity requires it.

Do not bypass AIS ETR guardrails: keep `mode = shadow` and `production_send = blocked` until an explicit production gate approval exists; redact secrets, room ids, raw WebEx text, full meter/PEANO lists, and customer identity.
