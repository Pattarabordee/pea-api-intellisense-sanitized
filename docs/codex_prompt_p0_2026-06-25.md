# Codex Prompt — P0 Workspace Hardening (2026-06-25)

Copy everything below the line into Codex desktop. It is self-contained.

---

You are working in the repo `D:\PEA Intellisense data` (Windows, PowerShell primary, Git Bash available). Read `AGENTS.md` first — it is the source of truth. Apply two modes: `grill-me` (pressure-test before acting) and `caveman-lite` (concise, technically exact).

Hard guardrails — do NOT violate:
- Keep `mode = shadow` and `production_send = blocked`. Touch no gate logic.
- Never stage or commit secrets, `.env`, oauth tokens, `runtime/*.sqlite`, raw Webex text, full meter/PEANO lists, room ids, or customer identity.
- Stdlib/SQLite/CLI over new dependencies. Add no framework, service, or dashboard.

## Context

The repo has **0 commits** but ~96 untracked entries. Test suite is currently green (`python -m unittest discover -s tests` → 249 pass). `.gitignore` already excludes secrets/runtime/node_modules/.next. The root is cluttered with throwaway analysis scripts mixed beside the real `ais_etr/` package.

## Tasks (do in order, stop and report if any precheck fails)

### 1. Verify clean state before touching anything
- Run `python -m unittest discover -s tests` and confirm it still passes. If not, STOP and report — do not proceed.
- Run `git status --porcelain` and `git log --oneline`. Confirm 0 commits.
- Grep the working tree for accidental secrets before any `git add`: scan for `.env` (not `.env.example`), `*oauth_token*`, `*.sqlite`, and obvious key patterns. Report findings; do not stage them.

### 2. Baseline commit — code/tests/docs/config only
- Stage ONLY: `ais_etr/`, `tests/`, `apps/api-go/` (source, not `.next`/`node_modules`), `apps/web-next/` (source only), `demo_ui/`, `docs/`, `runtime/tools/`, `.github/`, `.gitignore`, `.dockerignore`, `.env.example`, `package.json`, `render*.yaml`, `AGENTS.md`, `CLAUDE.md`, `README*.md`.
- Do NOT stage: loose root `*.py` analysis scripts, root `*.json`/`*.csv`/`*.headers` dumps, `*.png`, `tmp/`, `outputs/`, anything under `runtime/` except `runtime/tools/`.
- Before committing, run `git status` and show me the staged file list for confirmation. Re-grep the STAGED set for secrets.
- Commit message: `chore: baseline commit of AIS ETR workspace (code, tests, docs, config)`.

### 3. Root cleanup — separate scratch from signal
- Create `tools/analysis/` if absent.
- Move the loose root analysis scripts there: `analyze_*.py`, `inspect_*.py`, `fetch_*.py`, `diagnose_*.py`, `find_*.py`, `check_*.py`, `count_*.py`, `query_*.py`, `isPEAnetwork.py`, `pea_*.py` (verify each is throwaway analysis, not an entrypoint, before moving — grep for imports of it).
- Move root data dumps (`*.json`, `*.csv`, `*.headers`, `*.png` that are query outputs) into `tmp/` or `outputs/`, and confirm those dirs are gitignored.
- If anything is imported by `ais_etr/` or `tests/`, leave it and report instead.
- Commit moves separately: `chore: move root analysis scripts to tools/analysis, dumps to tmp`.

### 4. CI runs the full suite
- Read `.github/workflows/production-cloud-ci.yml`. Confirm whether the `python-guardrails` job runs the full `python -m unittest discover -s tests`. If it runs a narrower subset, add a step that runs the full discover suite (do not remove existing guardrail steps).
- Commit: `ci: run full unittest discover suite in CI`.

## Acceptance criteria
- `git log` shows 3 clean commits; no secrets in any commit (verify with a final grep over `git show --stat` and tracked content).
- `python -m unittest discover -s tests` still passes after the moves.
- Root no longer mixes analysis scripts with the package; `git status` is clean or only shows intentionally-ignored scratch.
- No change to gate/shadow logic; `mode=shadow` and `production_send=blocked` untouched.

Report back: staged file count per commit, any file you refused to move and why, and the final test result.
