# A Group Daily Chain Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the A-group backend safely reproduce the 2026-07-08 and 2026-07-09 daily reports using the finalized 2026-07-07 report as the chain baseline.

**Architecture:** Keep the existing parser, deterministic calculation engine, SQLAlchemy repositories, and Excel exporters. Add validation at the two trust boundaries: finalized baseline import and report persistence. The regression runner uses an isolated SQLite database and local-only HR files, so it does not require or copy production MySQL/Redis data.

**Tech Stack:** Python 3.12, pytest, pandas, SQLAlchemy, openpyxl, xlrd, FastAPI.

## Global Constraints

- Real HR inputs remain local and untracked; no names or row-level source data enter commits or reports.
- The accepted baseline is `project/日报/2026-07-07/员工数增减情况日报-7月_20260707.xlsx`.
- Inputs are the four files in the `2026-07-08` and `2026-07-09` main directories; `_废弃文档` is excluded.
- Expected output is business-value equality for Sheet1 Row2-40, tenure totals and hard checks, not binary workbook equality.
- Changes are backend-only and surgical; authentication and frontend redesign remain out of scope.

---

### Task 1: Reject incomplete finalized daily baselines

**Files:**
- Modify: `app/pipeline/input/daily_workbook.py`
- Create: `tests/test_daily_workbook_import.py`

**Interfaces:**
- Consumes: `parse_daily_workbook(path: Path, report_date: date)`.
- Produces: `DailyImportError` when any persisted business row is absent or non-numeric.

- [x] **Step 1: Write failing tests**

Create a minimal workbook containing only Row8/9/13/14/30 and assert import fails with the missing row numbers. Create a complete persisted-row workbook and assert it succeeds.

- [x] **Step 2: Verify RED**

Run: `python -m pytest tests/test_daily_workbook_import.py -q`

Expected: partial-workbook test fails because current parser accepts five rows.

- [x] **Step 3: Implement minimal validation**

Require every row in `_PERSIST_ROWS`, and report missing rows through `DailyImportError.detail["missing_rows"]`.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_daily_workbook_import.py -q`

Expected: both tests pass.

### Task 2: Never persist a hard-failed report

**Files:**
- Modify: `app/services/report_service.py`
- Create: `tests/test_report_persistence_guards.py`

**Interfaces:**
- Consumes: daily/weekly calculation contexts containing `validations`.
- Produces: `blocked` without writing `daily_reports`, `weekly_reports`, or export files.

- [x] **Step 1: Write failing daily test**

Patch the calculation agent to return a hard-failed context, invoke `generate_daily`, and assert no `DailyReport` exists.

- [x] **Step 2: Verify daily RED**

Run: `python -m pytest tests/test_report_persistence_guards.py::test_daily_hard_failure_is_not_persisted -q`

Expected: failure because `save_daily` currently commits before checking hard failures.

- [x] **Step 3: Write failing weekly test**

Patch weekly calculation to return a failed hard check, invoke `generate_weekly`, and assert status is `blocked` and no weekly row is saved.

- [x] **Step 4: Verify weekly RED**

Run: `python -m pytest tests/test_report_persistence_guards.py::test_weekly_hard_failure_is_not_persisted -q`

Expected: failure because `_run_weekly` currently logs and publishes failed results.

- [x] **Step 5: Implement minimal ordering fix**

Move daily persistence after hard validation. Make `_run_weekly` return a blocked result before persistence/export and keep public status mapping unchanged.

- [x] **Step 6: Verify GREEN**

Run: `python -m pytest tests/test_report_persistence_guards.py -q`

Expected: both tests pass.

### Task 3: Surface incomplete cascade recalculation

**Files:**
- Modify: `app/services/daily_import_service.py`
- Modify: `app/schemas/api.py`
- Create: `tests/test_daily_import_service.py`

**Interfaces:**
- Consumes: `cascade_later` results and exceptions.
- Produces: `status="partial"` plus `cascade_error`, or a non-success cascade entry, instead of silent success.

- [x] **Step 1: Write failing test**

Patch the parser/save boundary and make `cascade_later` raise. Assert import reports a partial outcome and preserves the imported baseline.

- [x] **Step 2: Verify RED**

Run: `python -m pytest tests/test_daily_import_service.py -q`

Expected: failure because current service returns `succeeded` with an empty cascade list.

- [x] **Step 3: Implement minimal status propagation**

Return `partial` with a concise cascade error message; extend the response schema without exposing stack traces.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_daily_import_service.py -q`

Expected: test passes.

### Task 4: Make local startup and legacy `.xls` input reproducible

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`
- Create: `scripts/run_chain_regression.py`
- Create: `docs/REAL_DATA_REGRESSION.md`

**Interfaces:**
- Consumes: baseline xlsx, two dated input directories, two finalized expected xlsx files.
- Produces: local output workbooks and a redacted JSON summary containing row numbers and pass/fail only.

- [x] **Step 1: Add the missing runtime dependency**

Add `xlrd>=2.0.1` because the provided personnel and resignation files are `.xls`.

- [x] **Step 2: Implement the isolated runner**

Use SQLite, import the finalized baseline, ingest the four structured inputs for each day, calculate the report, validate hard checks, and compare only report rows and tenure aggregates against the expected workbook.

- [x] **Step 3: Document startup**

Document Docker MySQL/Redis startup, backend startup, frontend startup, and the SQLite regression command. Keep secrets as placeholders.

- [x] **Step 4: Verify help and failure handling**

Run: `python scripts/run_chain_regression.py --help`

Expected: exit 0 with required path arguments and no data access.

### Task 5: End-to-end verification

**Files:**
- No production changes unless a reproduced defect requires another TDD cycle.

- [x] **Step 1: Run all backend tests**

Run: `python -m pytest -q -rs`

Expected: zero failures; only explicitly missing legacy fixtures may skip.

- [x] **Step 2: Run the real local chain**

Run the regression with 7/7 as baseline, 7/8 and 7/9 as dated inputs, and their finalized workbooks as expected outputs.

Expected: both days match all required rows, tenure totals and hard checks. If not, record only row numbers and mismatch categories, then return to systematic debugging.

- [x] **Step 3: Verify repository state**

Run: `git diff --check`, `git status --short`, and inspect the final diff.

Expected: no whitespace errors, no real data files, no generated reports, and only planned source/test/docs changes.
