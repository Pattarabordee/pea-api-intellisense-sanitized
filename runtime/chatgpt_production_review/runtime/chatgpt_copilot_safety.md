# ChatGPT Co-Pilot Safety Log

## Purpose

Use ChatGPT as a reviewer/product co-pilot for UI, deck, API wording, runbook, and QA checklists. Codex and the operator remain responsible for redaction, implementation, and final acceptance.

## Allowed Uploads

- Sanitized screenshots and contact sheets.
- Redacted API contract text.
- Redacted Markdown summaries.
- Presentation scripts and visual QA summaries.
- Demo screenshots without secrets or customer identifiers.

## Forbidden Uploads

- API key, token, refresh token, client secret, or password.
- WebEx room id or verbatim WebEx message text.
- Full meter number, PEANO list, customer identity, or raw customer asset export.
- Raw runtime SQLite database.
- Private endpoint logs that include secrets.

## Fallback Rule

If ChatGPT browser review stalls twice, stop trying that browser loop, continue with local QA, and record the stall note in the runtime audit. ChatGPT feedback can improve the work, but final acceptance must not depend only on ChatGPT.

## Current Audit

- Round 2 visual/product critique exists and was used to improve the cinematic deck/demo.
- Round 3 browser session stalled; local QA and Codex review remain the final fallback.
- Production review bundle was generated as `runtime/sanitized_codebase_bundle.zip`; browser upload was not performed because the callable browser automation path was unavailable in this turn.
- Production guardrail remains `mode=shadow`, `production_send=blocked`.
