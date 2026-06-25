# Development Recommendations — 2026-06-25

Scope: workspace review of `D:\PEA Intellisense data`. Source of truth: `AGENTS.md`.
Style: caveman-lite. Guardrails unchanged (`mode=shadow`, `production_send=blocked`).

## Snapshot (verified today)

| Fact | State | Evidence |
| --- | --- | --- |
| Test suite | GREEN — 249 pass, 0 errors | `python -m unittest discover -s tests` |
| Prior 2 failing tests | FIXED | `_owner_response_file_profile` now defined (`shadow_operations.py:1935`) |
| Core package | Mature — 81 modules, 76 test files | `ais_etr/`, `tests/` |
| Git | **0 commits, 96 untracked root entries** | `git log` empty; `git status` |
| Root hygiene | Cluttered — 26 loose `.py`, 16 `.json`, 6 `.csv`, PNGs | `ls *.py *.json *.csv` |
| Stacks | Python core + Go API + Next.js web + static demo_ui | `apps/`, `demo_ui/` |
| Existing roadmap | Good — see overview doc set | `docs/project_overview_2026-06-22/` |

The 2026-06-22 overview is still accurate on architecture/guardrails. This doc adds what changed since (tests now green) and the gaps that doc does not cover (version control + workspace hygiene).

## P0 — Do first (risk, not features)

1. **Commit a baseline.** Nothing is version-controlled. 96 untracked entries = no history, no rollback, no review trail. This contradicts the project's own evidence-trail guardrail.
   - `.gitignore` already covers secrets/runtime/node_modules — good. Verify it ignores `runtime/*.sqlite`, `.env`, oauth tokens (it does) **before** first `git add`.
   - Stage the real package + tests + docs + configs first. Do NOT bulk-add the root scratch files.
   - Confirm no secret slips in: `git status` then spot-check `.env.example` only (never `.env`).

2. **Separate signal from scratch at root.** 26 loose analysis scripts (`analyze_gis_distance_gemini.py`, `inspect_*.py`, `fetch_*.py`, `diagnose_*.py`) and 16 JSON dumps sit beside the package. Move throwaway analysis into `tools/analysis/` or `tmp/` and gitignore the dumps. Keeps the committed tree to code that matters.

3. **Lock the test gate into CI.** Suite is green locally. Confirm `.github/workflows/production-cloud-ci.yml` runs `python -m unittest discover -s tests` (overview says `python-guardrails` job is narrower). A 249-test suite that only runs on a dev laptop will rot.

## P1 — Close the promotion blockers (already defined, still open)

These are unchanged from `09-open-questions-and-next-steps.md`. Restated as the gating path — nothing customer-facing ships until all true:

- Green rows ≥ 30; q50 MAE ≤ 16 min; q10–q90 coverage 0.75–0.90.
- AIS truth owner approves source/semantics. **Owner queue is the critical-path blocker — chase it first.**
- PEA topology owner approves impacted-path/matching.
- Callback/API owner approves contract + retry/idempotency.
- Ops/security owner approves monitoring, backup/restore, key rotation, incident, emergency-off.
- Production infra approved (not local tunnel/demo).

Engineering cannot unblock these — they are owner sign-offs. So P1 engineering work = make sign-off cheap: keep the redacted evidence packets current and the gate refreshable on new truth.

## P2 — Data and model (engineering-controllable)

- Repair `NO_METER` backlog, pilot areas + high-value AIS assets first.
- Add 20–50 real redacted Webex messages to parser/eval (sample rate is 0.958 on 24 — too thin to trust).
- Segment errors by event type, interruption class, match level, active AIS state, feeder, device, duration band.
- Run challenger vs production without overwriting the production artifact until the gate passes.

## P3 — Multi-stack hygiene (after P0)

- **Go API**: `go` not on this shell's PATH — `go test ./...` never ran locally. Either install toolchain or rely solely on the `go-api` CI job, and say which in the README so nobody assumes local coverage.
- **Next.js web + demo_ui**: two UIs exist (`apps/web-next` + static `demo_ui`). Confirm which is canonical; retire or label the other. AGENTS.md prefers CLI/report over UI — don't grow both.
- `.next/` build output appears under `apps/web-next/.next/` — confirm it's gitignored (rule exists) and not committed in the baseline.

## What NOT to do (per AGENTS.md)

- No new dependency/service/framework where stdlib + SQLite + a CLI/report already work.
- No second dashboard.
- Do not relax `shadow` / `production_send=blocked` without an explicit, recorded owner gate approval.
- Do not commit raw Webex text, full meter/PEANO lists, room ids, tokens, or customer identity.

## Suggested order

1. Baseline commit (clean tree, secrets verified out) → 2. Root cleanup + CI runs full suite → 3. AIS truth owner queue → 4. NO_METER repair + real Webex corpus → 5. Refresh green gate → 6. Resolve Go/web stack ownership.

## Daily review (unchanged, keep it)

`runtime/cloud_pilot/mvp_daily_qa_report.md` → `runtime/green_gate_tracker.md` → `python -m ais_etr summary` → local vs cloud inbound divergence → owner-queue/blocker counts → record decisions in Markdown/CSV.
