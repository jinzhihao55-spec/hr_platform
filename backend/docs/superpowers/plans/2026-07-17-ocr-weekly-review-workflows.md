# OCR And Weekly Review Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give HR an evidence-backed OCR confirmation screen and a complete weekly duplicate-employment review workflow that can unlock non-conflicting weekly reports without weakening conflict blocks.

**Architecture:** Add a narrowly scoped backend review service that returns only whitelisted OCR facts and opaque-evidence-linked weekly employment rows. Convert non-conflicting weekly review items into stable `RunDecision` records, preserve answered decisions across preview recomputation, and let validation summaries treat only the exact approved answer as resolved. The React client consumes those APIs through two focused evidence panels and refreshes the existing Run/preview state after every action.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest, React 18, Vite, Vitest, Testing Library, Axios, lucide-react, Playwright, Docker Compose.

## Global Constraints

- Original Release and recruitment images remain temporary parsing inputs and must never be returned, persisted, logged, backed up, or included in artifacts.
- OCR APIs return only the field allowlists in the approved design; weekly review APIs must never return certificate fields, `person_key`, or database primary keys.
- A non-conflicting duplicate employment can be resolved only by the exact answer `确认按自然人计1人`.
- A conflicting duplicate employment remains `BLOCK`; the current Run cannot override it and the only UI repair action is creating a same-day revision Run.
- Daily and weekly targets remain independently previewable, reviewable, and publishable.
- No database migration or new dependency is permitted for this feature.
- All automated fixtures and browser mutation tests use fake data. The existing real 2026-07-17 Run is view-only during acceptance.
- Desktop and mobile layouts must keep long evidence tables scrollable, labels complete, and controls non-overlapping.

---

### Task 1: Add Safe OCR Decision Preview Contracts

**Files:**
- Create: `app/services/review_service.py`
- Modify: `app/schemas/runs.py`
- Modify: `app/api/routes/runs.py`
- Test: `tests/test_review_service.py`
- Test: `tests/test_run_api.py`

**Interfaces:**
- Consumes: `RunDecision.fact_ref`, `fact_repo.list_release_facts()`, `fact_repo.list_recruitment_snapshots()`.
- Produces: `decision_preview(db: Session, run_id: str, decision_id: str) -> dict[str, Any]` and `GET /runs/{run_id}/decisions/{decision_id}/preview` returning `DecisionPreviewResponse`.

- [ ] **Step 1: Write failing service tests for both OCR sources and the privacy allowlist**

```python
def test_release_ocr_preview_returns_only_whitelisted_fields(db):
    run, decision = stage_release_ocr_decision(db)
    payload = decision_preview(db, run.id, decision.id)
    assert payload["source_type"] == "release"
    assert payload["rows"][0] == {
        "source_row_no": 2,
        "order_no": "FAKE-001",
        "application_date": date(2026, 7, 17),
        "last_working_day": date(2026, 7, 30),
        "process_status": "审批中",
        "row5_classification": "include",
        "row30_classification": "include",
        "ocr_confidence": "unreviewed",
    }
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    for forbidden in ("person_key", "person_id", "employee_no", "certificate", "image"):
        assert forbidden not in serialized


def test_recruitment_ocr_preview_decodes_labels_and_sorts_rows(db):
    run, decision = stage_recruitment_ocr_decision(db)
    payload = decision_preview(db, run.id, decision.id)
    assert [row["source_row_no"] for row in payload["rows"]] == [2, 3]
    assert payload["rows"][0]["recognized_labels"] == ["合计", "当月接受offer当月预计入职"]
```

- [ ] **Step 2: Run the new tests and verify the missing service failure**

Run: `pytest tests/test_review_service.py -q`

Expected: collection/import failure for `app.services.review_service`.

- [ ] **Step 3: Implement the allowlisted service and typed response**

```python
class ReviewEvidenceMissing(RuntimeError):
    pass


def decision_preview(db: Session, run_id: str, decision_id: str) -> dict[str, Any]:
    run = db.get(ReportRun, run_id)
    decision = db.get(RunDecision, decision_id)
    if run is None or run.is_deleted or decision is None or decision.is_deleted:
        raise LookupError("Run or decision was not found")
    if decision.run_id != run_id or decision.decision_code != "ocr_review_required":
        raise ValueError("decision is not an OCR review for this Run")
    parts = decision.fact_ref.split(":")
    if len(parts) != 4 or parts[0] != "source" or parts[2:] != ["row", "ocr"]:
        raise ValueError("OCR decision has an invalid source reference")
    source_type = parts[1]
    if source_type == "release":
        rows = [_release_row(fact) for fact in fact_repo.list_release_facts(db, run_id)]
        columns = RELEASE_COLUMNS
    elif source_type == "recruitment":
        rows = [_recruitment_row(fact) for fact in fact_repo.list_recruitment_snapshots(db, run_id)]
        columns = RECRUITMENT_COLUMNS
    else:
        raise ValueError("unsupported OCR source")
    if not rows:
        raise ReviewEvidenceMissing("OCR facts are no longer available; replace the input")
    return {
        "kind": "ocr_source",
        "source_type": source_type,
        "columns": columns,
        "rows": rows,
        "warnings": ["原始图片按安全策略不留存；请核对结构化结果。"],
    }
```

Define Pydantic models `DecisionPreviewColumn` and `DecisionPreviewResponse`; map `LookupError` to 404, `ValueError` to 422, and `ReviewEvidenceMissing` to 409 in the route.

- [ ] **Step 4: Add API contract tests including mismatched decision and missing evidence**

```python
response = api_client.get(f"/runs/{run.id}/decisions/{decision.id}/preview")
assert response.status_code == 200
assert response.json()["warnings"] == ["原始图片按安全策略不留存；请核对结构化结果。"]

mismatch = api_client.get(f"/runs/{other_run.id}/decisions/{decision.id}/preview")
assert mismatch.status_code == 422
```

- [ ] **Step 5: Run focused backend tests**

Run: `pytest tests/test_review_service.py tests/test_run_api.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the OCR preview backend**

```bash
git add app/services/review_service.py app/schemas/runs.py app/api/routes/runs.py tests/test_review_service.py tests/test_run_api.py
git commit -m "feat: expose safe OCR review evidence"
```

---

### Task 2: Preserve Opaque Weekly Review Evidence

**Files:**
- Modify: `app/services/fact_bundle_service.py`
- Modify: `app/pipeline/calculation/weekly.py`
- Modify: `app/pipeline/calculation/validators.py`
- Test: `tests/test_person_identity_calculation.py`
- Test: `tests/test_run_validation.py`

**Interfaces:**
- Consumes: `EmploymentFact.source_row_no` and weekly `_dedupe_active_people()` groups.
- Produces: review items containing `selected_source_row_no`, `employment_source_row_nos`, and `conflicting_dimensions`; persisted validation refs `person:*`, `source:personnel:row:*`, `employment:selected:*`, and `validation:dimension:*`.

- [ ] **Step 1: Extend the duplicate-employment calculation test with exact evidence assertions**

```python
item = result["review_items"][0]
assert item["employment_source_row_nos"] == [7, 8]
assert item["selected_source_row_no"] == 8
assert item["conflicting_dimensions"] == []
```

- [ ] **Step 2: Run the focused calculation test and verify missing evidence fields**

Run: `pytest tests/test_person_identity_calculation.py -q`

Expected: FAIL with `KeyError: 'employment_source_row_nos'`.

- [ ] **Step 3: Thread source row numbers through the fact bundle and review item**

Add `source_row_no` to `_EMPLOYMENT_COLUMNS` and each `_employment_rows()` record. In `_dedupe_active_people()`, sort integer source rows and record the selected row from the same index selected by the existing `(hire_date, emp_no)` key:

```python
selected_index = max(group.index, key=_selection_key)
selected_indices.append(selected_index)
reviews.append({
    "code": "multiple_active_employments",
    "severity": "BLOCK" if conflicts else "REVIEW",
    "person_ref": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
    "employment_count": len(group),
    "employment_source_row_nos": sorted(
        int(value) for value in group["source_row_no"].dropna().tolist()
    ),
    "selected_source_row_no": int(group.loc[selected_index, "source_row_no"]),
    "conflicting_dimensions": conflicts,
})
```

- [ ] **Step 4: Persist only opaque evidence references**

```python
def review_item_as_check(item: dict[str, Any]) -> dict[str, Any]:
    refs = []
    if item.get("person_ref"):
        refs.append(f"person:{item['person_ref']}")
    refs.extend(
        f"source:personnel:row:{int(row_no)}"
        for row_no in item.get("employment_source_row_nos") or ()
    )
    if item.get("selected_source_row_no") is not None:
        refs.append(f"employment:selected:{int(item['selected_source_row_no'])}")
    refs.extend(
        f"validation:dimension:{dimension}"
        for dimension in item.get("conflicting_dimensions") or ()
    )
    return {
        "check": str(item.get("code") or "manual_review_required"),
        "validation_code": str(item.get("code") or "manual_review_required"),
        "passed": False,
        "hard_block": str(item.get("severity") or "REVIEW").upper() == "BLOCK",
        "severity": str(item.get("severity") or "REVIEW").upper(),
        "evidence_refs": refs,
    }
```

- [ ] **Step 5: Assert evidence is useful but PII-free**

```python
refs = decode_json_text(stored.evidence_refs)
assert refs == [
    "person:fakepersonref",
    "source:personnel:row:7",
    "source:personnel:row:8",
    "employment:selected:8",
]
assert "employee_no" not in stored.evidence_refs
```

- [ ] **Step 6: Run calculation and validation tests**

Run: `pytest tests/test_person_identity_calculation.py tests/test_run_validation.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit opaque evidence persistence**

```bash
git add app/services/fact_bundle_service.py app/pipeline/calculation/weekly.py app/pipeline/calculation/validators.py tests/test_person_identity_calculation.py tests/test_run_validation.py
git commit -m "feat: retain opaque weekly review evidence"
```

---

### Task 3: Synchronize Stable Weekly Decisions And Resolve Validation

**Files:**
- Modify: `app/services/review_service.py`
- Modify: `app/services/run_validation_service.py`
- Modify: `app/services/decision_service.py`
- Modify: `app/api/routes/runs.py`
- Test: `tests/test_run_validation.py`
- Test: `tests/test_decision_service.py`

**Interfaces:**
- Produces: `sync_weekly_review_decisions(db: Session, run_id: str, review_items: Sequence[Mapping[str, Any]]) -> None`.
- Consumes: exact fact ref `weekly:multiple_active_employments:{person_ref}` and exact accepted answer `确认按自然人计1人`.

- [ ] **Step 1: Write failing tests for decision creation, stable replay, and conflict behavior**

```python
replace_calculation_validations(db, run.id, "weekly", checks=[], review_items=[review])
decision = db.query(RunDecision).filter_by(
    run_id=run.id,
    fact_ref="weekly:multiple_active_employments:abc123def456",
).one()
assert decode_json_text(decision.options) == ["确认按自然人计1人"]

answer_decision(db, run.id, decision.id, "确认按自然人计1人", "qa")
replace_calculation_validations(db, run.id, "weekly", checks=[], review_items=[review])
assert db.get(RunDecision, decision.id).status == "answered"
assert validate_run_target(db, run.id, "weekly").review_count == 0

conflict = {**review, "severity": "BLOCK", "conflicting_dimensions": ["project_name"]}
replace_calculation_validations(db, run.id, "weekly", checks=[], review_items=[conflict])
assert validate_run_target(db, run.id, "weekly").block_count == 1
assert db.query(RunDecision).filter_by(run_id=run.id, status="pending").count() == 0
```

- [ ] **Step 2: Run tests and verify the missing weekly decision failure**

Run: `pytest tests/test_run_validation.py tests/test_decision_service.py -q`

Expected: FAIL because no `multiple_active_employments` handler or sync exists.

- [ ] **Step 3: Implement stable decision synchronization**

```python
WEEKLY_DEDUPE_ANSWER = "确认按自然人计1人"


def sync_weekly_review_decisions(db, run_id, review_items):
    existing = list(db.scalars(select(RunDecision).where(
        RunDecision.run_id == run_id,
        RunDecision.report_kind == "weekly",
        RunDecision.decision_code == "multiple_active_employments",
        RunDecision.is_deleted == 0,
    )))
    by_ref = {item.fact_ref: item for item in existing}
    desired = {}
    for item in review_items:
        if item.get("code") != "multiple_active_employments":
            continue
        person_ref = str(item.get("person_ref") or "")
        fact_ref = f"weekly:multiple_active_employments:{person_ref}"
        if item.get("severity") == "REVIEW" and person_ref:
            desired[fact_ref] = item
            if fact_ref not in by_ref:
                db.add(RunDecision(
                    run_id=run_id,
                    report_kind="weekly",
                    decision_code="multiple_active_employments",
                    fact_ref=fact_ref,
                    question="同一自然人存在多条归属维度一致的有效在职记录，请确认按较晚入职记录归属并按1人计数。",
                    options=encode_json_text([WEEKLY_DEDUPE_ANSWER]),
                    status="pending",
                ))
    for decision in existing:
        if decision.fact_ref not in desired and decision.status != "answered":
            db.delete(decision)
    db.flush()
```

Call this function inside `replace_calculation_validations()` before the validation summary is computed.

- [ ] **Step 4: Implement exact-answer resolution and non-mutating decision semantics**

Add `_answer_weekly_dedupe()` to `_HANDLERS`. In `answer_decision()`, return the existing record when an answered decision receives the identical decoded answer; raise `DecisionAnswerConflict` for a different replay; and skip `fact_repo.assert_run_facts_mutable()` only for `multiple_active_employments` because it changes no shared facts.

```python
def _answer_weekly_dedupe(db, run, decision, answer):
    if answer != WEEKLY_DEDUPE_ANSWER:
        raise InvalidDecisionAnswer("weekly duplicate review must use the listed option")
    return "answered"
```

- [ ] **Step 5: Exclude only correctly answered weekly reviews from the readiness summary**

Decode each failed REVIEW validation's `person:*` evidence, match it to an answered decision with the exact fact ref and answer, and remove only that validation from `unresolved_validations`. Compute `review_count`, `blocking_validation_codes`, target status, and `publishable` from the unresolved list.

- [ ] **Step 6: Cover daily-already-published and idempotent-submit regressions**

```python
daily_target.status = TargetStatus.published.value
same = answer_decision(db, run.id, decision.id, WEEKLY_DEDUPE_ANSWER, "qa")
again = answer_decision(db, run.id, decision.id, WEEKLY_DEDUPE_ANSWER, "qa")
assert again.id == same.id
with pytest.raises(DecisionAnswerConflict):
    answer_decision(db, run.id, decision.id, "其他答案", "qa")
```

- [ ] **Step 7: Run decision and validation tests**

Run: `pytest tests/test_run_validation.py tests/test_decision_service.py tests/test_run_api.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit stable weekly decision behavior**

```bash
git add app/services/review_service.py app/services/run_validation_service.py app/services/decision_service.py app/api/routes/runs.py tests/test_run_validation.py tests/test_decision_service.py tests/test_run_api.py
git commit -m "feat: resolve weekly duplicate reviews with stable decisions"
```

---

### Task 4: Expose Weekly Review Details And Revision Contract

**Files:**
- Modify: `app/services/review_service.py`
- Modify: `app/schemas/runs.py`
- Modify: `app/api/routes/runs.py`
- Test: `tests/test_review_service.py`
- Test: `tests/test_run_api.py`

**Interfaces:**
- Produces: `weekly_review(db: Session, run_id: str) -> dict[str, Any]` and `GET /runs/{run_id}/weekly/review` returning `WeeklyReviewResponse`.
- Consumes: opaque validation evidence persisted in Task 2 and stable decisions from Task 3.

- [ ] **Step 1: Write failing tests for REVIEW and BLOCK response shapes**

```python
payload = weekly_review(db, run.id)
item = payload["items"][0]
assert item["resolution"] == "confirm_dedupe"
assert item["decision_id"] == decision.id
assert item["selected_source_row_no"] == 8
assert item["employments"][1]["selected"] is True
assert item["employments"][1]["employee_no"] == "FAKE-002"

serialized = json.dumps(payload, ensure_ascii=False, default=str)
for forbidden in ("person_key", "person_id", "certificate", "id_card"):
    assert forbidden not in serialized

blocked = payload_for_conflict["items"][0]
assert blocked["resolution"] == "replace_input"
assert blocked["decision_id"] is None
assert blocked["conflicting_dimensions"] == ["project_name"]
```

- [ ] **Step 2: Run tests and verify the missing endpoint failure**

Run: `pytest tests/test_review_service.py tests/test_run_api.py -q`

Expected: FAIL because `weekly_review` and the route are absent.

- [ ] **Step 3: Implement evidence parsing and fact lookup with fixed limits**

Read only failed `multiple_active_employments%` validations. Parse `person:*`, `source:personnel:row:*`, `employment:selected:*`, and `validation:dimension:*` refs; require exactly one person ref and at least two source rows. Query `EmploymentFact` by `run_id` and source rows, cap the response at 100 review items and 20 employments per item, sort by `person_ref` then source row, and raise `ReviewEvidenceMissing` if any evidence row is absent.

Each employment row must be exactly:

```python
{
    "source_row_no": fact.source_row_no,
    "employee_no": fact.employee_no,
    "display_name": fact.display_name,
    "entry_date": fact.entry_date,
    "business_unit_no": fact.business_unit_no,
    "business_unit": fact.business_unit,
    "project_code": fact.project_code,
    "project_name": fact.project_name,
    "employee_type": fact.employee_type,
    "status": fact.status,
    "selected": fact.source_row_no == selected_source_row_no,
}
```

- [ ] **Step 4: Add typed API models and route error mapping**

Define `WeeklyReviewEmployment`, `WeeklyReviewItem`, and `WeeklyReviewResponse`. Map missing Run to 404 and missing evidence to 409. Do not extend `RunDetail`.

- [ ] **Step 5: Verify same-day revision Run does not copy facts**

```python
response = api_client.post("/runs", json={"report_date": "2026-07-17", "create_new": True})
assert response.status_code == 201
revision_id = response.json()["run"]["id"]
assert revision_id != original.id
assert response.json()["run"]["baseline_report_id"] == original.baseline_report_id
assert api_db.query(EmploymentFact).filter_by(run_id=revision_id).count() == 0
```

- [ ] **Step 6: Run review and API tests**

Run: `pytest tests/test_review_service.py tests/test_run_api.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit weekly review API**

```bash
git add app/services/review_service.py app/schemas/runs.py app/api/routes/runs.py tests/test_review_service.py tests/test_run_api.py
git commit -m "feat: expose weekly review evidence"
```

---

### Task 5: Add OCR Evidence To The Run Confirmation Page

**Files:**
- Modify: `src/services/runService.js`
- Modify: `src/services/runService.test.js`
- Create: `src/components/run/DecisionEvidence.jsx`
- Modify: `src/components/run/DecisionList.jsx`
- Modify: `src/pages/RunReviewPage.jsx`
- Modify: `src/pages/RunReviewPage.test.jsx`
- Modify: `src/pages/RunWorkspacePage.css`

**Interfaces:**
- Produces: `getDecisionPreview(runId, decisionId)` and `<DecisionEvidence runId decision />`.
- Consumes: `DecisionPreviewResponse` from Task 1.

- [ ] **Step 1: Write failing service and component tests**

```javascript
expect(getDecisionPreview('run-1', 'decision-1')).resolves.toEqual(preview);
expect(apiClient.get).toHaveBeenCalledWith('/runs/run-1/decisions/decision-1/preview');

render(<RunReviewPage run={reviewRun} onRefresh={vi.fn()} onContinue={vi.fn()} />);
expect(await screen.findByRole('table', { name: 'OA/Release 识别结果' })).toBeVisible();
expect(screen.getByText('FAKE-001')).toBeVisible();
expect(screen.getByText('原始图片按安全策略不留存')).toBeVisible();
```

- [ ] **Step 2: Run focused frontend tests and verify failure**

Run: `npm test -- --run src/services/runService.test.js src/pages/RunReviewPage.test.jsx`

Expected: FAIL because `getDecisionPreview` and evidence UI do not exist.

- [ ] **Step 3: Add the service call and evidence component**

`DecisionEvidence` fetches only when `decision_code === 'ocr_review_required'`. Pending decisions render an open `<details>` section; answered decisions render a closed but available “查看识别结果” section. Render API `columns` and `rows` directly in a fixed-header table, format `null` as `—`, render arrays with `、`, and show loading/error states inside the evidence section.

```javascript
export function getDecisionPreview(runId, decisionId) {
  return apiClient.get(`/runs/${runId}/decisions/${decisionId}/preview`);
}
```

- [ ] **Step 4: Wire evidence into every OCR decision without altering answer semantics**

Pass `runId={run.id}` from `RunReviewPage` to `DecisionList`; render `<DecisionEvidence>` after the question and before the existing answer/options. Keep `确认` and `替换输入` wired to `answerRunDecision`.

- [ ] **Step 5: Style stable, scrollable evidence tables**

Use a single un-nested evidence region, `max-height: 300px`, `overflow: auto`, sticky headers, `min-width: 760px`, and a mobile horizontal scrollbar. Keep cards at 8px radius or less and preserve visible focus styles.

- [ ] **Step 6: Run focused frontend tests**

Run: `npm test -- --run src/services/runService.test.js src/pages/RunReviewPage.test.jsx`

Expected: all tests pass.

- [ ] **Step 7: Commit OCR evidence UI**

```bash
git add src/services/runService.js src/services/runService.test.js src/components/run/DecisionEvidence.jsx src/components/run/DecisionList.jsx src/pages/RunReviewPage.jsx src/pages/RunReviewPage.test.jsx src/pages/RunWorkspacePage.css
git commit -m "feat: show OCR evidence before confirmation"
```

---

### Task 6: Add The Weekly Review And Revision Window

**Files:**
- Modify: `src/services/runService.js`
- Modify: `src/services/runService.test.js`
- Create: `src/components/run/WeeklyReviewPanel.jsx`
- Modify: `src/pages/RunPreviewPage.jsx`
- Modify: `src/pages/RunPreviewPage.css`
- Modify: `src/pages/RunPreviewPage.test.jsx`

**Interfaces:**
- Produces: `getWeeklyReview(runId)`, `createRevisionRun(reportDate)`, and `<WeeklyReviewPanel items busyId onConfirm onCreateRevision />`.
- Consumes: `WeeklyReviewResponse`, existing `answerRunDecision()`, and `POST /runs`.

- [ ] **Step 1: Write failing tests for confirmable and blocked items**

```javascript
expect(await screen.findByRole('heading', { name: '周报复核' })).toBeVisible();
expect(screen.getByText('系统采用')).toBeVisible();
await user.click(screen.getByRole('button', { name: '确认按自然人计 1 人' }));
expect(answerRunDecision).toHaveBeenCalledWith(
  'run-preview', 'weekly-decision-1', '确认按自然人计1人',
);

expect(screen.queryByRole('button', { name: '确认按自然人计 1 人' })).not.toBeInTheDocument();
await user.click(screen.getByRole('button', { name: '创建同日修订 Run' }));
expect(createRevisionRun).toHaveBeenCalledWith('2026-07-17');
```

- [ ] **Step 2: Run the preview tests and verify missing workflow failure**

Run: `npm test -- --run src/pages/RunPreviewPage.test.jsx src/services/runService.test.js`

Expected: FAIL because weekly review services and panel do not exist.

- [ ] **Step 3: Add service methods**

```javascript
export function getWeeklyReview(runId) {
  return apiClient.get(`/runs/${runId}/weekly/review`);
}

export function createRevisionRun(reportDate) {
  return apiClient.post('/runs', { report_date: reportDate, create_new: true });
}
```

- [ ] **Step 4: Implement the weekly review panel**

For `resolution === 'confirm_dedupe'`, render every employment row and mark the selected row with “系统采用”; enable the exact confirmation button only for a pending decision. For `resolution === 'replace_input'`, render localized conflict field labels, omit all confirmation controls, and show only “创建同日修订 Run”. Keep employee number and name visible because this page is HR-authorized, but never infer or display hidden identity fields.

- [ ] **Step 5: Integrate state refresh and initial weekly selection**

Load `getWeeklyReview(runId)` with the two previews. If the report date is Friday and weekly `review_count > 0` or `block_count > 0`, select the weekly tab on first load. Confirmation calls `answerRunDecision`, then reloads Run, weekly preview, and weekly review. Revision creation navigates to `/runs/{new_run_id}`. Change the workspace continuation copy to `预览日报与周报`.

- [ ] **Step 6: Verify independent publication behavior**

Tests must keep `发布日报` enabled while weekly review is pending, enable `发布周报` after a successful confirmation refresh, and leave `发布周报` disabled for a conflict item.

- [ ] **Step 7: Add responsive review table styling**

Use a full-width panel above the weekly output, not a card nested inside the report table. Tables use stable columns, `min-width: 860px`, horizontal overflow, and non-wrapping command buttons. On widths below 720px, stack panel actions below the heading and retain full button labels.

- [ ] **Step 8: Run focused frontend tests**

Run: `npm test -- --run src/pages/RunPreviewPage.test.jsx src/pages/RunWorkspacePage.test.jsx src/services/runService.test.js`

Expected: all tests pass.

- [ ] **Step 9: Commit the weekly review UI**

```bash
git add src/services/runService.js src/services/runService.test.js src/components/run/WeeklyReviewPanel.jsx src/pages/RunPreviewPage.jsx src/pages/RunPreviewPage.css src/pages/RunPreviewPage.test.jsx src/pages/RunWorkspacePage.test.jsx
git commit -m "feat: add actionable weekly review window"
```

---

### Task 7: Run Full Automated And Privacy Verification

**Files:**
- Modify only if a test exposes a defect in files already listed above.

**Interfaces:**
- Consumes: complete backend and frontend feature implementations.
- Produces: green test/build logs and a zero-hit privacy scan for forbidden API fields.

- [ ] **Step 1: Run the complete backend suite**

Run: `pytest -q`

Expected: all tests pass with no collection errors.

- [ ] **Step 2: Run the complete frontend suite**

Run: `npm test -- --run`

Expected: all Vitest tests pass.

- [ ] **Step 3: Build the frontend production bundle**

Run: `npm run build`

Expected: Vite exits 0 and writes `dist/`.

- [ ] **Step 4: Scan review responses and client logs for forbidden identity/image fields**

Run: `rg -n 'person_key|certificate|id_card|raw_image|image_base64' app/services/review_service.py app/schemas/runs.py src/components/run`

Expected: no response field or rendered property exposes these values; allow only explicit test assertions or comments that state they are forbidden.

- [ ] **Step 5: Review branch diffs and commit any test-driven corrections**

Run: `git diff --check`

Expected: no whitespace errors.

---

### Task 8: Rebuild Locally And Complete Browser Acceptance

**Files:**
- Modify: `/private/tmp/hr-agent-ui-20260716.env` only to point Docker build contexts at the two feature worktrees.
- Create: `docs/qa/2026-07-17-review-workflows-browser-acceptance.md`
- Create: `output/qa/review-workflows/desktop.png`
- Create: `output/qa/review-workflows/mobile.png`

**Interfaces:**
- Consumes: existing Docker Compose stack, existing database volumes, fake acceptance inputs, and the current single-user gateway token.
- Produces: a locally running feature at `http://127.0.0.1:55479` plus visual evidence and an acceptance record.

- [ ] **Step 1: Rebuild only API and web images without recreating database volumes**

Run: `docker compose --env-file /private/tmp/hr-agent-ui-20260716.env build api web`

Expected: both images build successfully.

- [ ] **Step 2: Restart API and web services against existing data**

Run: `docker compose --env-file /private/tmp/hr-agent-ui-20260716.env up -d api web`

Expected: containers become healthy; database and artifact volumes are unchanged.

- [ ] **Step 3: Execute fake-data OCR acceptance through the browser**

Create a new fake-data Run, upload four fake inputs including Release and recruitment images, verify both structured result tables, confirm both OCR decisions, and reach report preview. Record Run ID and observed state transitions in the QA Markdown file.

- [ ] **Step 4: Execute both fake weekly duplicate paths through the browser**

For a dimension-consistent duplicate, verify the selected newer record, confirm it, and verify `review_count` becomes 0 and weekly publish becomes enabled. For a dimension conflict, verify there is no confirm button, create a same-day revision Run, and verify the new Run contains no copied sources.

- [ ] **Step 5: Inspect desktop and mobile screenshots**

Capture 1440×900 and 390×844 screenshots with Playwright. Verify nonblank tables, no overlaps, complete button labels, visible horizontal scrolling for long evidence, and no raw image preview.

- [ ] **Step 6: Perform non-destructive verification of the existing real Run**

Open the existing 2026-07-17 Run and verify that answered OCR decisions can display their structured facts and that its weekly “需要处理” state now includes a review panel. Do not click any confirmation, revision, or publish action on this Run.

- [ ] **Step 7: Commit QA documentation and screenshots**

```bash
git add docs/qa/2026-07-17-review-workflows-browser-acceptance.md output/qa/review-workflows
git commit -m "test: document review workflow acceptance"
```

---

### Task 9: Publish Both Feature Branches

**Files:**
- No source changes.

**Interfaces:**
- Consumes: clean backend and frontend feature branches with passing verification.
- Produces: remote `feature/review-workflows-v1` branches for both repositories.

- [ ] **Step 1: Verify both worktrees are clean and on the intended branch**

Run in each worktree: `git status --short --branch`

Expected: `## feature/review-workflows-v1` with no uncommitted files.

- [ ] **Step 2: Push the backend branch**

Run: `git push -u origin feature/review-workflows-v1`

Expected: remote branch is created or updated without force.

- [ ] **Step 3: Push the frontend branch**

Run: `git push -u origin feature/review-workflows-v1`

Expected: remote branch is created or updated without force.

- [ ] **Step 4: Record final commit IDs and verification totals**

Run: `git log -1 --oneline`

Expected: the final response can identify exact backend/frontend commit IDs, test totals, local URL, and any residual risk.
