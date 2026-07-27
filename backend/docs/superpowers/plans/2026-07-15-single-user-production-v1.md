# HR Reporting Agent Single-User Production V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the validated A-group HR reporting code into a deployable single-user application with run-scoped facts, deterministic preview/publish, stable person identity, a B-style calendar entry point, and A-style daily report workflows.

**Architecture:** Keep the 2026-07-12 deterministic calculators and Excel exporters behind a new `FactBundle` interface. Add immutable Run, source, fact, decision, validation, report-target, published-report, and artifact records; only publication updates compatibility projections. Build the UI in the A-group React app, borrowing only the B-group calendar interaction.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, pandas, openpyxl, MySQL 8, Redis, React 19, Vite 8, React Router, Lucide React, Vitest, Testing Library, Playwright, Nginx, Docker Compose.

## Global Constraints

- Backend base is A-group `feature/hr-report-staging-readiness-20260712` at `dd7357d`; do not replace the validated rule engine wholesale.
- Frontend base is A-group `origin/merge_branch` at reviewed commit `9551338`; B-group remains read-only reference code.
- Database base is A-group 2026-07-12 branch at reviewed commit `01eaf08`.
- Use branch `feature/single-user-production-v1` in all three repositories.
- Formal daily inputs are personnel Excel, resignation Excel, OA/Release image or structured Excel, and recruitment image or structured Excel.
- Do not add a formal “离职明细” input.
- Numeric report values must come from deterministic Python rules; LLM output must become reviewable structured facts first.
- Raw uploads are temporary; persist hashes and minimal canonical facts, then delete source bytes in `finally`.
- Derive natural-person identity with HMAC-SHA256 and never persist certificate plaintext.
- Daily and weekly targets validate and publish independently.
- No multi-user, role, tenant, natural-language SQL, or monthly-report implementation in V1.
- Preserve the fixed daily/weekly Excel formats, accumulated daily columns, historical values, styles, and tenure sheet.
- Repository tests use fake data only. Real artifacts from mentor-local `project/日报`, starting 2026-07-08, remain outside Git.
- Node must satisfy Vite's lock-file floor: Node 20.19+ or 22.12+.
- Every task uses red-green-refactor TDD and ends with an independently reviewable commit.

## Repository Preparation

The backend design worktree already exists at `/Users/andrewhua/Desktop/Claude Project/.worktrees/hr-agent-a-single-user-production-v1`. Before the first frontend or database task, create matching isolated worktrees from the reviewed bases:

```bash
git -C "/Users/andrewhua/Desktop/Claude Project/project/暑期实训/12_人事报表智能体启动会/代码仓库/groupA/frontend" \
  worktree add -b feature/single-user-production-v1 \
  "/Users/andrewhua/Desktop/Claude Project/.worktrees/hr-agent-a-frontend-single-user-production-v1" \
  origin/merge_branch

git -C "/Users/andrewhua/Desktop/Claude Project/project/暑期实训/12_人事报表智能体启动会/代码仓库/groupA/database" \
  worktree add -b feature/single-user-production-v1 \
  "/Users/andrewhua/Desktop/Claude Project/.worktrees/hr-agent-a-database-single-user-production-v1" \
  feature/hr-report-staging-readiness-20260712
```

Before each task, run `git status --short --branch` in the affected worktree. Never modify or reset the student branches.

---

### Task 1: Stable Person Identity Service

**Files:**
- Create: `app/domain/__init__.py`
- Create: `app/domain/identity.py`
- Modify: `app/config.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Produces: `DerivedIdentity(person_key: str, key_version: str, confidence: str, namespace: str)`.
- Produces: `derive_person_identity(certificate_type, certificate_number, employee_no, *, secret, key_version="v1") -> DerivedIdentity`.
- Consumes: no database or pandas dependency.

- [x] **Step 1: Write identity tests**

```python
import pytest

from app.domain.identity import derive_person_identity


def test_same_normalized_certificate_produces_same_key():
    left = derive_person_identity("身份证", " AB 123 ", "E-1", secret="test-secret")
    right = derive_person_identity("居民身份证", "ab123", "E-2", secret="test-secret")
    assert left.person_key == right.person_key
    assert left.confidence == "certificate"


def test_missing_certificate_uses_namespaced_employee_fallback():
    value = derive_person_identity(None, None, "E-1", secret="test-secret")
    assert value.confidence == "employee_no_fallback"
    assert value.namespace == "employee_no"


def test_missing_certificate_and_employee_number_is_rejected():
    with pytest.raises(ValueError, match="stable identity"):
        derive_person_identity(None, None, None, secret="test-secret")
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_identity.py -q`
Expected: FAIL because `app.domain.identity` does not exist.

- [x] **Step 3: Implement deterministic HMAC identity**

```python
@dataclass(frozen=True)
class DerivedIdentity:
    person_key: str
    key_version: str
    confidence: str
    namespace: str


def derive_person_identity(certificate_type, certificate_number, employee_no,
                           *, secret: str, key_version: str = "v1") -> DerivedIdentity:
    if not secret:
        raise ValueError("PERSON_KEY_SECRET is required")
    cert_no = _normalize_token(certificate_number)
    if cert_no:
        namespace = "certificate"
        identity = f"{_normalize_certificate_type(certificate_type)}:{cert_no}"
        confidence = "certificate"
    else:
        emp_no = _normalize_token(employee_no)
        if not emp_no:
            raise ValueError("stable identity requires certificate number or employee number")
        namespace = "employee_no"
        identity = f"employee:{emp_no}"
        confidence = "employee_no_fallback"
    digest = hmac.new(secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
    return DerivedIdentity(digest, key_version, confidence, namespace)
```

Add `person_key_secret: str = ""` and `person_key_version: str = "v1"` to `Settings`. Require `PERSON_KEY_SECRET` in non-development environments in the existing secret validator.

- [x] **Step 4: Run focused and configuration tests**

Run: `python -m pytest tests/test_identity.py tests/test_api_guard.py -q`
Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add app/domain app/config.py tests/test_identity.py
git commit -m "feat(identity): add stable HMAC person keys"
```

---

### Task 2: Input Projection and Certificate Minimization

**Files:**
- Modify: `app/pipeline/input/header_map.py`
- Modify: `app/pipeline/input/parsers.py`
- Create: `app/pipeline/input/canonical_projection.py`
- Test: `tests/test_canonical_projection.py`
- Modify: `tests/test_recruitment_parser.py`

**Interfaces:**
- Produces: `project_personnel_frame(df) -> DataFrame` containing only approved personnel columns.
- Produces: `project_resignation_frame(df) -> DataFrame` containing only approved resignation columns.
- Certificate plaintext may exist only in the projected frame until Task 6 derives `person_key`; it must not be returned by any persisted fact serializer.

- [x] **Step 1: Add privacy projection tests**

```python
def test_personnel_projection_keeps_required_identity_and_drops_unrelated_pii():
    raw = pd.DataFrame([{
        "员工类型": "正式员工", "工号": "E1", "中文名": "测试员工",
        "事业部编号": "BU1", "证件类型": "身份证", "证件号": "FAKE-1",
        "手机号码": "FAKE-PHONE", "员工薪资卡号": "FAKE-CARD",
    }])
    out = project_personnel_frame(raw)
    assert "证件号" in out.columns
    assert "手机号码" not in out.columns
    assert "员工薪资卡号" not in out.columns


def test_resignation_projection_uses_application_time_not_manager_approval():
    raw = pd.DataFrame([{
        "流程单号": "P1", "流程状态": "已完成", "离职方式": "主动离职",
        "员工申请时间": "2026-07-08", "项目经理通过时间": "2026-07-09",
    }])
    out = project_resignation_frame(raw)
    assert "员工申请时间" in out.columns
    assert "项目经理通过时间" not in out.columns
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_canonical_projection.py -q`
Expected: FAIL because `canonical_projection` does not exist.

- [x] **Step 3: Implement explicit allowlists**

Define immutable allowlists for every field used by the validated rules. Extend `EMPLOYEE_HEADERS` and `RESIGNATION_HEADERS` with `证件类型` and `证件号`, normalize aliases, and make both parsers return only allowlisted columns. Do not change recruitment label matching or OA fallback behavior.

```python
PERSONNEL_COLUMNS = (
    "员工类型", "工号", "中文名", "英文名", "Alias", "员工状态",
    "入职日期", "离职日期", "事业部", "事业部编号", "部门", "部门编号",
    "项目编号", "项目名称", "合同开始日期", "合同结束日期",
    "实习生合同开始日期", "实习生合同结束日期", "证件类型", "证件号",
)


def _project(df: pd.DataFrame, allowed: tuple[str, ...]) -> pd.DataFrame:
    columns = [column for column in allowed if column in df.columns]
    return df.loc[:, columns].copy()
```

- [x] **Step 4: Run parser and existing pipeline tests**

Run: `python -m pytest tests/test_canonical_projection.py tests/test_pipeline_smoke.py tests/test_recruitment_parser.py tests/test_ingestion_service.py -q`
Expected: all tests PASS; no existing calculation field disappears.

- [x] **Step 5: Commit**

```bash
git add app/pipeline/input tests/test_canonical_projection.py tests/test_recruitment_parser.py
git commit -m "refactor(input): minimize canonical HR fields"
```

---

### Task 3: Run Core ORM and Forward-Only Migration

**Files:**
- Create: `app/models/runs.py`
- Modify: `app/models/__init__.py`
- Create: `scripts/migrations/2026-07-15_add_report_runs.sql`
- Test: `tests/test_run_models.py`
- Modify: `tests/test_migration_ddl.py`
- Database create: `migrations/2026-07-15_01_report_runs.sql`
- Database modify: `schema.sql`

**Interfaces:**
- Produces ORM classes `ReportRun`, `RunSource`, and `RunReportTarget`.
- Produces enums `RunStatus`, `SourceType`, and `TargetStatus` as `str, Enum`.
- `ReportRun.source_bundle_hash` is nullable until all sources and the baseline are fixed.

- [x] **Step 1: Write model-contract tests**

```python
def test_report_run_allows_provisional_run_and_unique_final_fingerprint(db):
    first = ReportRun(report_date=date(2026, 7, 8), status="created", rule_version="v1")
    second = ReportRun(report_date=date(2026, 7, 8), status="created", rule_version="v1")
    db.add_all([first, second])
    db.commit()
    assert first.source_bundle_hash is None
    assert second.source_bundle_hash is None


def test_daily_and_weekly_targets_are_unique_per_run(db):
    run = ReportRun(report_date=date(2026, 7, 10), status="ready", rule_version="v1")
    db.add(run); db.flush()
    db.add_all([
        RunReportTarget(run_id=run.id, report_kind="daily", status="draft"),
        RunReportTarget(run_id=run.id, report_kind="weekly", status="draft"),
    ])
    db.commit()
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_run_models.py -q`
Expected: FAIL because run models do not exist.

- [x] **Step 3: Implement models and matching SQL**

Implement:

```python
class ReportRun(Base, AuditMixin):
    __tablename__ = "report_runs"
    __table_args__ = (UniqueConstraint(
        "report_date", "rule_version", "source_bundle_hash",
        name="uq_report_run_fingerprint",
    ),)
    id = uuid_pk()
    report_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    rule_version: Mapped[str] = mapped_column(String(64))
    source_bundle_hash: Mapped[str | None] = mapped_column(String(64))
    baseline_report_id: Mapped[str | None] = mapped_column(String(36))
    canonical_run_id: Mapped[str | None] = mapped_column(String(36))
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_redacted: Mapped[str | None] = mapped_column(Text)
```

`RunSource` has unique `(run_id, source_type)` and metadata-only fields from the spec. `RunReportTarget` has unique `(run_id, report_kind)` and independent status, preview hash, published report ID, validation summary, and redacted error fields. Add equivalent idempotent MySQL DDL in both repositories.

- [x] **Step 4: Run ORM and migration tests**

Run: `python -m pytest tests/test_run_models.py tests/test_migration_ddl.py -q`
Expected: all tests PASS and every ORM column appears in migration SQL.

- [x] **Step 5: Commit backend and database changes separately**

```bash
git add app/models scripts/migrations tests
git commit -m "feat(run): add run and report-target persistence"

# In the database worktree
git add schema.sql migrations/2026-07-15_01_report_runs.sql
git commit -m "feat(schema): add report run tables"
```

---

### Task 4: Run Fingerprint and State Repository

**Files:**
- Create: `app/domain/run_fingerprint.py`
- Create: `app/repositories/run_repo.py`
- Test: `tests/test_run_repository.py`

**Interfaces:**
- Produces: `compute_source_bundle_hash(source_hashes, baseline_report_id, baseline_sha256) -> str`.
- Produces: `create_provisional_run`, `upsert_source_metadata`, `finalize_run_fingerprint`, `transition_run`, `ensure_report_targets`, and `get_canonical_run`.
- `finalize_run_fingerprint` returns the existing canonical Run when a unique-key race is detected.

- [x] **Step 1: Write deterministic fingerprint and transition tests**

```python
def test_fingerprint_is_order_independent_but_baseline_sensitive():
    a = compute_source_bundle_hash(
        {"personnel": "a", "resignation": "b", "release": "c", "recruitment": "d"},
        "baseline-1", "hash-1",
    )
    b = compute_source_bundle_hash(
        {"recruitment": "d", "release": "c", "resignation": "b", "personnel": "a"},
        "baseline-1", "hash-1",
    )
    c = compute_source_bundle_hash(
        {"personnel": "a", "resignation": "b", "release": "c", "recruitment": "d"},
        "baseline-2", "hash-2",
    )
    assert a == b
    assert a != c


def test_invalid_run_transition_is_rejected(db):
    run = create_provisional_run(db, date(2026, 7, 8), "rules-v1", None)
    with pytest.raises(InvalidRunTransition):
        transition_run(db, run, "published")
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_run_repository.py -q`
Expected: FAIL because repository and fingerprint functions do not exist.

- [x] **Step 3: Implement canonical JSON hashing and explicit transitions**

```python
def compute_source_bundle_hash(
    source_hashes: Mapping[str, str],
    baseline_report_id: str,
    baseline_sha256: str,
) -> str:
    required = {item.value for item in SourceType}
    missing = required - set(source_hashes)
    if missing:
        raise IncompleteSourceBundle(sorted(missing))
    payload = {
        "sources": {key: source_hashes[key] for key in sorted(required)},
        "baseline_report_id": baseline_report_id,
        "baseline_sha256": baseline_sha256,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
```

Use a transition map rather than setting statuses ad hoc. Catch `IntegrityError` during fingerprint finalization, roll back to a savepoint, load the canonical Run, mark the provisional Run `deduplicated`, and delete its duplicate facts in Task 7.

- [x] **Step 4: Run repository tests**

Run: `python -m pytest tests/test_run_repository.py tests/test_run_models.py -q`
Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add app/domain/run_fingerprint.py app/repositories/run_repo.py tests/test_run_repository.py
git commit -m "feat(run): add deterministic fingerprint lifecycle"
```

---

### Task 5: Run-Scoped Canonical Fact Models

**Files:**
- Create: `app/models/facts.py`
- Modify: `app/models/__init__.py`
- Create: `scripts/migrations/2026-07-15_add_run_facts.sql`
- Create: `tests/test_fact_models.py`
- Modify: `tests/test_migration_ddl.py`
- Database create: `migrations/2026-07-15_02_run_facts.sql`
- Database modify: `schema.sql`

**Interfaces:**
- Produces ORM classes `PersonIdentity`, `EmploymentFact`, `ResignationFact`, `ReleaseFact`, `RecruitmentSnapshot`, `FactEvent`, `RunDecision`, and `RunValidation`.
- Facts are immutable by convention after a report target is published.
- Protected display fields remain in the database but never enter ordinary logs.

- [x] **Step 1: Write fact isolation and uniqueness tests**

```python
def test_same_person_can_have_multiple_employment_numbers(db):
    person = PersonIdentity(person_key="a" * 64, key_version="v1",
                            match_confidence="certificate", identity_namespace="certificate")
    db.add(person); db.flush()
    db.add_all([
        EmploymentFact(run_id=run_id, source_row_no=2, person_id=person.id,
                       employee_no="E1", employee_type="正式员工"),
        EmploymentFact(run_id=run_id, source_row_no=3, person_id=person.id,
                       employee_no="E2", employee_type="正式员工"),
    ])
    db.commit()


def test_fact_event_key_is_unique_within_run(db):
    db.add(FactEvent(run_id=run_id, event_key="event-1", event_type="hire",
                     source_type="personnel"))
    db.commit()
    db.add(FactEvent(run_id=run_id, event_key="event-1", event_type="hire",
                     source_type="personnel"))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_fact_models.py -q`
Expected: FAIL because fact models do not exist.

- [x] **Step 3: Implement models and migrations**

Implement all columns and constraints from design sections 8.3-8.10. Use explicit composite unique constraints:

```python
UniqueConstraint("run_id", "source_row_no", name="uq_employment_fact_run_row")
UniqueConstraint("run_id", "process_no", name="uq_resignation_fact_run_process")
UniqueConstraint("run_id", "order_no", name="uq_release_fact_run_order")
UniqueConstraint("run_id", "event_key", name="uq_fact_event_run_key")
```

Store decision options, answers, validation evidence, and minimal event payload as JSON text with structured encode/decode helpers; do not use Python `repr`.

- [x] **Step 4: Run model and migration tests**

Run: `python -m pytest tests/test_fact_models.py tests/test_migration_ddl.py -q`
Expected: all tests PASS.

- [x] **Step 5: Commit backend and database changes separately**

```bash
git add app/models scripts/migrations tests
git commit -m "feat(facts): add run-scoped canonical facts"

# In the database worktree
git add schema.sql migrations/2026-07-15_02_run_facts.sql
git commit -m "feat(schema): add canonical fact tables"
```

---

### Task 6: Source-Specific Fact Staging

**Files:**
- Create: `app/repositories/fact_repo.py`
- Create: `app/services/run_source_service.py`
- Modify: `app/agents/extraction_agent.py`
- Modify: `app/pipeline/input/parsers.py`
- Test: `tests/test_run_source_service.py`
- Test: `tests/test_fact_staging.py`

**Interfaces:**
- Produces: `async RunSourceService.ingest(run_id, source_type, upload_file) -> SourceIngestResult`.
- Produces: `replace_source_facts(db, run_id, source_type, facts)` using one transaction.
- Personnel and resignation staging derive `person_key`, persist or reuse `PersonIdentity`, then discard certificate plaintext before repository calls.

- [x] **Step 1: Write staging tests with fake identifiers**

```python
@pytest.mark.asyncio
async def test_personnel_stage_deduplicates_identity_without_collapsing_employment(db, fake_xlsx):
    result = await service.ingest(run.id, SourceType.personnel, fake_xlsx)
    facts = fact_repo.list_employment_facts(db, run.id)
    assert result.row_count == 2
    assert facts[0].person_id == facts[1].person_id
    assert {fact.employee_no for fact in facts} == {"FAKE-E1", "FAKE-E2"}
    assert "certificate_number" not in result.persisted_fields


@pytest.mark.asyncio
async def test_failed_parse_replaces_neither_existing_facts_nor_source_metadata(db):
    before = fact_repo.list_employment_facts(db, run.id)
    with pytest.raises(SchemaMismatchError):
        await service.ingest(run.id, SourceType.personnel, malformed_xlsx)
    assert fact_repo.list_employment_facts(db, run.id) == before
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_run_source_service.py tests/test_fact_staging.py -q`
Expected: FAIL because run source staging does not exist.

- [x] **Step 3: Implement transactional staging and cleanup**

Use a temporary directory per request, stream the upload while computing SHA-256, parse by explicit source type, convert DataFrame rows to fact DTOs, and replace only that source's facts in a nested transaction. Delete temporary files in `finally`.

```python
try:
    sha256, path = await _stream_to_temp_and_hash(upload_file, temp_dir)
    facts = _parse_and_build_facts(source_type, path, identity_service)
    with db.begin_nested():
        fact_repo.replace_source_facts(db, run_id, source_type, facts)
        run_repo.upsert_source_metadata(db, run_id, source_type, sha256, facts)
    db.commit()
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
```

For OA/Release and recruitment images, call the existing vision adapter, validate the returned JSON schema, and stage `REVIEW` decisions when key fields or labels are uncertain. Structured Excel follows the same fact DTO contract.

- [x] **Step 4: Run staging and privacy tests**

Run: `python -m pytest tests/test_run_source_service.py tests/test_fact_staging.py tests/test_extraction_image_gate.py tests/test_ingestion_service.py -q`
Expected: all tests PASS and no temp files remain.

- [x] **Step 5: Commit**

```bash
git add app/repositories/fact_repo.py app/services/run_source_service.py app/agents/extraction_agent.py app/pipeline/input tests
git commit -m "feat(ingestion): stage minimal facts per run"
```

---

### Task 7: FactBundle and Natural-Person Calculation Adapter

**Files:**
- Create: `app/domain/fact_bundle.py`
- Create: `app/services/fact_bundle_service.py`
- Modify: `app/agents/calculation_agent.py`
- Modify: `app/pipeline/calculation/daily.py`
- Modify: `app/pipeline/calculation/weekly.py`
- Modify: `app/pipeline/calculation/tenure.py`
- Test: `tests/test_fact_bundle.py`
- Test: `tests/test_person_identity_calculation.py`

**Interfaces:**
- Produces immutable `FactBundle` DataFrames for employment, resignation, release, recruitment, events, decisions, baseline, and rule version.
- Produces `CalculationAgent.run_daily_bundle(bundle)` and `run_weekly_bundle(bundle, week_start, week_end)`.
- Keeps legacy database-backed entry points as wrappers until publication migration is complete.

- [x] **Step 1: Lock identity semantics with failing tests**

```python
def test_weekly_headcount_counts_one_person_with_two_active_employee_numbers():
    bundle = fake_bundle(employments=[
        employment("person-1", "E1", active=True, entry="2025-01-01"),
        employment("person-1", "E2", active=True, entry="2026-07-01"),
    ])
    result = run_weekly_bundle(bundle, date(2026, 7, 6), date(2026, 7, 10))
    assert result.total_headcount == 1
    assert result.review_items[0].code == "multiple_active_employments"


def test_distinct_rehire_events_are_not_collapsed():
    bundle = fake_bundle(events=[
        hire_event("person-1", "E1", date(2025, 1, 1)),
        hire_event("person-1", "E2", date(2026, 7, 8)),
    ])
    result = run_daily_bundle(bundle, date(2026, 7, 8))
    assert result.rows[2].value == 1
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_fact_bundle.py tests/test_person_identity_calculation.py -q`
Expected: FAIL because FactBundle entry points do not exist.

- [x] **Step 3: Add FactBundle adapters without rewriting formulas**

Refactor calculators so data-loading and rule evaluation are separate. Preserve the current row formulas and accepted process-status behavior. For active roster dimensions, choose the latest valid active employment deterministically only when dimensions agree; otherwise emit a review item and block weekly publication.

```python
@dataclass(frozen=True)
class FactBundle:
    report_date: date
    baseline_date: date
    rule_version: str
    employments: pd.DataFrame
    resignations: pd.DataFrame
    releases: pd.DataFrame
    recruitment: pd.DataFrame
    events: pd.DataFrame
    decisions: tuple[Decision, ...]
    baseline_rows: Mapping[int, int]
```

- [x] **Step 4: Run all calculation regressions**

Run: `python -m pytest tests/test_fact_bundle.py tests/test_person_identity_calculation.py tests/test_daily_departure_confirmation.py tests/test_weekly_calc.py tests/test_weekly_regression.py tests/test_tenure.py -q`
Expected: all tests PASS with unchanged legacy fixtures.

- [x] **Step 5: Commit**

```bash
git add app/domain/fact_bundle.py app/services/fact_bundle_service.py app/agents/calculation_agent.py app/pipeline/calculation tests
git commit -m "refactor(calc): evaluate reports from FactBundle"
```

---

### Task 8: Decision Queue and Validation Targets

**Files:**
- Create: `app/services/decision_service.py`
- Create: `app/services/run_validation_service.py`
- Modify: `app/pipeline/calculation/validators.py`
- Test: `tests/test_run_decisions.py`
- Test: `tests/test_run_validation.py`

**Interfaces:**
- Produces: `list_decisions(run_id, report_kind=None)`.
- Produces: `answer_decision(run_id, decision_id, answer, operator_ref)`; rejects direct numeric report overrides.
- Produces: `validate_run_target(run_id, report_kind) -> ValidationSummary`.

- [x] **Step 1: Write blocking and target-isolation tests**

```python
def test_weekly_review_does_not_block_daily_target(db):
    add_review(db, run.id, report_kind="weekly", code="weekly_third_place_tie")
    assert validate_run_target(run.id, "daily").publishable is True
    assert validate_run_target(run.id, "weekly").publishable is False


def test_decision_cannot_set_final_row_value(db):
    with pytest.raises(InvalidDecisionAnswer):
        answer_decision(run.id, decision.id, {"row30": 99}, "local-operator")
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_run_decisions.py tests/test_run_validation.py -q`
Expected: FAIL because services do not exist.

- [x] **Step 3: Implement decision schemas and validation summaries**

Use typed decision handlers keyed by `decision_code`; each handler may update a fact classification or relationship only. Rebuild FactBundle and target validations after each accepted answer. Store validation evidence as counts and opaque fact refs, never protected display fields.

- [x] **Step 4: Run decision and existing validator tests**

Run: `python -m pytest tests/test_run_decisions.py tests/test_run_validation.py tests/test_report_persistence_guards.py tests/test_weekly_regression.py -q`
Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add app/services/decision_service.py app/services/run_validation_service.py app/pipeline/calculation/validators.py tests
git commit -m "feat(review): add scoped decisions and validations"
```

---

### Task 9: Preview Snapshots and Atomic Publication

**Files:**
- Create: `app/models/publication.py`
- Modify: `app/models/__init__.py`
- Create: `app/services/preview_service.py`
- Create: `app/services/publication_service.py`
- Create: `app/repositories/publication_repo.py`
- Create: `scripts/migrations/2026-07-15_add_publications.sql`
- Test: `tests/test_preview_service.py`
- Test: `tests/test_publication_service.py`
- Database create: `migrations/2026-07-15_03_publications.sql`
- Database modify: `schema.sql`

**Interfaces:**
- Produces ORM classes `PublishedReport` and `ReportArtifact`.
- Produces: `build_preview(run_id, report_kind) -> PreviewSnapshot`.
- Produces: `publish(run_id, report_kinds, operator_ref) -> list[PublishedReport]`.

- [x] **Step 1: Write no-mutation and atomicity tests**

```python
def test_preview_does_not_write_compatibility_reports(db):
    snapshot = build_preview(run.id, "daily")
    assert snapshot.rows[2].value == 1
    assert db.scalar(select(func.count()).select_from(DailyReport)) == 0


def test_export_failure_leaves_previous_report_current(db, monkeypatch):
    previous = publish_fake_daily(db, report_date, version=1)
    monkeypatch.setattr(exporter, "write", Mock(side_effect=OSError("disk full")))
    with pytest.raises(PublicationFailed):
        publish(run.id, ["daily"], "local-operator")
    assert publication_repo.current_daily(db, report_date).id == previous.id
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_preview_service.py tests/test_publication_service.py -q`
Expected: FAIL because preview/publication services do not exist.

- [x] **Step 3: Implement snapshot hashing and publication recovery record**

Generate artifacts in a same-filesystem staging directory, re-read Excel and compare to preview, write report/artifact metadata and compatibility projections in one transaction, then atomically rename staged files. Persist a publication attempt marker so startup can remove orphan staging files or finish metadata reconciliation after an interrupted rename.

- [x] **Step 4: Run publication and Excel regression tests**

Run: `python -m pytest tests/test_preview_service.py tests/test_publication_service.py tests/test_daily_export_golden.py tests/test_daily_export_layout.py tests/test_calc_log_exporter.py tests/test_weekly_golden.py -q`
Expected: all tests PASS and `PreviewSnapshot == parsed Excel`.

- [x] **Step 5: Commit backend and database changes separately**

```bash
git add app/models app/services app/repositories scripts/migrations tests
git commit -m "feat(publish): add preview and atomic report versions"

# In the database worktree
git add schema.sql migrations/2026-07-15_03_publications.sql
git commit -m "feat(schema): add published report metadata"
```

---

### Task 10: Run, Calendar, Review, and Publication APIs

**Files:**
- Create: `app/schemas/runs.py`
- Create: `app/api/routes/runs.py`
- Create: `app/api/routes/calendar.py`
- Modify: `app/main.py`
- Modify: `app/api/routes/health.py`
- Test: `tests/test_run_api.py`
- Test: `tests/test_calendar_api.py`
- Modify: `tests/test_health.py`

**Interfaces:**
- Implements the API contract in design section 16.
- `GET /api/runs/{id}` returns source, decision, validation, and daily/weekly target status in one typed response.
- `/ready` checks database connectivity, Redis, migration contract, output-directory writeability, and required production secrets.

- [x] **Step 1: Write API contract tests**

```python
def test_calendar_exposes_daily_and_weekly_status(client):
    response = client.get("/api/calendar", params={"month": "2026-07"})
    assert response.status_code == 200
    assert response.json()["days"][0].keys() >= {
        "date", "run_status", "daily_status", "weekly_status"
    }


def test_unknown_source_type_is_rejected_before_reading_file(client):
    response = client.put(f"/api/runs/{run_id}/sources/unknown", files={"file": fake_file})
    assert response.status_code == 422
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_run_api.py tests/test_calendar_api.py tests/test_health.py -q`
Expected: FAIL because routes do not exist.

- [x] **Step 3: Implement thin typed routes**

Routes validate request/response schemas and delegate to services. They must not calculate rows, mutate facts directly, or return protected fact fields in list endpoints. Change startup behavior so deployment configuration errors fail fast; development may start degraded, but `/ready` remains 503 with explicit component statuses.

- [x] **Step 4: Run API and guard tests**

Run: `python -m pytest tests/test_run_api.py tests/test_calendar_api.py tests/test_health.py tests/test_api_guard.py tests/test_upload_gate.py -q`
Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add app/schemas/runs.py app/api/routes app/main.py tests
git commit -m "feat(api): expose calendar and run workflow"
```

---

### Task 11: Frontend Routing and B-Style Calendar Entry

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `src/App.jsx`
- Create: `src/router.jsx`
- Create: `src/pages/CalendarPage.jsx`
- Create: `src/pages/CalendarPage.css`
- Create: `src/services/calendarService.js`
- Modify: `src/components/Sidebar/Sidebar.jsx`
- Modify: `src/components/Sidebar/Sidebar.css`
- Create: `src/test/setup.js`
- Create: `src/pages/CalendarPage.test.jsx`

**Interfaces:**
- Produces routes `/calendar`, `/runs/:runId`, `/reports/daily`, `/reports/weekly`, `/history`, `/settings`, and `/system`.
- Calendar cells navigate to an existing canonical Run or create a provisional Run for the selected workday.

- [x] **Step 1: Add frontend test dependencies and failing calendar test**

Add React Router, Lucide React, Vitest, jsdom, and Testing Library. Add `test` and `test:watch` scripts.

```jsx
it('opens the selected date run from calendar status data', async () => {
  render(<CalendarPage />, { wrapper: TestRouter });
  expect(await screen.findByRole('button', { name: /7月15日.*待确认/ })).toBeVisible();
  await user.click(screen.getByRole('button', { name: /7月15日.*待确认/ }));
  expect(mockNavigate).toHaveBeenCalledWith('/runs/run-15');
});
```

- [x] **Step 2: Run test and verify red**

Run: `npm test -- --run src/pages/CalendarPage.test.jsx`
Expected: FAIL because CalendarPage and router do not exist.

- [x] **Step 3: Implement router and calendar in the A visual system**

Use the B-group interaction only: previous/next month, workday status, daily/weekly badges, and date click. Keep A-group React structure, restrained colors, 8px maximum card radius, Lucide icons, stable calendar cell dimensions, visible focus states, and a mobile navigation trigger.

- [x] **Step 4: Run frontend checks**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: tests, lint, and production build PASS.

- [x] **Step 5: Commit**

```bash
git add package.json package-lock.json src
git commit -m "feat(ui): add calendar-based run navigation"
```

---

### Task 12: A-Style Run Workspace and Review Queue

**Files:**
- Create: `src/pages/RunWorkspacePage.jsx`
- Create: `src/pages/RunWorkspacePage.css`
- Create: `src/pages/RunReviewPage.jsx`
- Create: `src/components/run/RunStepper.jsx`
- Create: `src/components/run/SourceUploadGrid.jsx`
- Create: `src/components/run/SourceSlot.jsx`
- Create: `src/components/run/DecisionList.jsx`
- Create: `src/services/runService.js`
- Test: `src/pages/RunWorkspacePage.test.jsx`
- Test: `src/pages/RunReviewPage.test.jsx`

**Interfaces:**
- Four explicit source slots call `PUT /api/runs/{id}/sources/{source_type}`.
- Review answers call typed decision endpoints, then refresh the whole Run view.
- Chat is optional help and cannot trigger publication.

- [x] **Step 1: Write upload classification and decision tests**

```jsx
it('never assigns an unknown file to the first empty source slot', async () => {
  render(<RunWorkspacePage />);
  await user.upload(screen.getByLabelText('人员表'), unknownFile);
  expect(await screen.findByText('文件结构与人员表不匹配')).toBeVisible();
  expect(screen.getByLabelText('离职人员报表')).toHaveValue('');
});


it('keeps publish disabled until review decisions are resolved', async () => {
  render(<RunReviewPage />);
  expect(await screen.findByRole('button', { name: '继续预览' })).toBeDisabled();
});
```

- [x] **Step 2: Run tests and verify red**

Run: `npm test -- --run src/pages/RunWorkspacePage.test.jsx src/pages/RunReviewPage.test.jsx`
Expected: FAIL because pages and components do not exist.

- [x] **Step 3: Implement focused components**

Split responsibilities so no replacement for the existing 756-line Workbench exceeds 250 lines. Each source slot has its own loading, success, review, and error state. Use server data after refresh rather than optimistic final status. Remove fixed success counts and `dangerouslySetInnerHTML` from the generated-report path.

- [x] **Step 4: Run frontend checks**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all checks PASS.

- [x] **Step 5: Commit**

```bash
git add src/pages src/components/run src/services/runService.js
git commit -m "feat(ui): add guided run and review workflow"
```

---

### Task 13: Preview, Independent Publication, History, and Failure UI

**Files:**
- Create: `src/pages/RunPreviewPage.jsx`
- Create: `src/pages/SystemStatusPage.jsx`
- Modify: `src/pages/DailyReport.jsx`
- Modify: `src/pages/WeeklyReport.jsx`
- Modify: `src/pages/Archive.jsx`
- Modify: `src/services/reportService.js`
- Create: `src/components/ErrorBoundary.jsx`
- Test: `src/pages/RunPreviewPage.test.jsx`
- Test: `src/pages/ReportPeriodRace.test.jsx`
- Test: `src/pages/SystemStatusPage.test.jsx`

**Interfaces:**
- Daily and weekly publication buttons use target-specific status.
- Downloads use immutable `report_id`, never a selected date plus stale path.
- API readiness failures render actionable diagnostics.

- [x] **Step 1: Write race, publication, and error-state tests**

```jsx
it('does not expose stale report data while a new date is loading', async () => {
  render(<DailyReport />);
  await selectDate('2026-07-08');
  await selectDate('2026-07-09');
  expect(screen.getByRole('button', { name: '下载日报' })).toBeDisabled();
  resolveSecondRequest(reportFor('2026-07-09'));
  expect(screen.getByRole('button', { name: '下载日报' })).toBeEnabled();
});


it('allows daily publication while weekly remains in review', async () => {
  render(<RunPreviewPage />);
  expect(await screen.findByRole('button', { name: '发布日报' })).toBeEnabled();
  expect(screen.getByRole('button', { name: '发布周报' })).toBeDisabled();
});
```

- [x] **Step 2: Run tests and verify red**

Run: `npm test -- --run src/pages/RunPreviewPage.test.jsx src/pages/ReportPeriodRace.test.jsx src/pages/SystemStatusPage.test.jsx`
Expected: FAIL before implementation.

- [x] **Step 3: Implement preview diff, safe downloads, and diagnostics**

Clear old report state before each request, use `AbortController` or request sequence IDs, render backend text as React text nodes, and provide retry/configuration actions when `/ready` fails. Preserve dense A-group report tables and add baseline/current/delta columns without nesting cards.

- [x] **Step 4: Run all frontend tests and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all checks PASS.

- [x] **Step 5: Commit**

```bash
git add src
git commit -m "feat(ui): add safe preview publish and recovery states"
```

---

### Task 14: Deployment, Security, and Operational Documentation

**Files:**
- Backend create: `Dockerfile`
- Backend create: `deploy/compose.yaml`
- Backend create: `deploy/nginx.conf`
- Backend create: `deploy/.env.example`
- Backend create: `scripts/check_ready.py`
- Backend modify: `README.md`
- Backend create: `docs/DEPLOYMENT_SINGLE_USER.md`
- Frontend create: `Dockerfile`
- Frontend create: `nginx.conf`
- Database create: `Dockerfile.migrate`
- Test: `tests/test_deploy_contract.py`

**Interfaces:**
- Compose services: `web`, `api`, `mysql`, `redis`, and one-shot `migrate`.
- Only Nginx publishes a host port; API, MySQL, and Redis stay on the Compose network.
- Manual Windows/macOS instructions use the same environment-variable contract.

- [x] **Step 1: Write deployment contract tests**

```python
def test_compose_exposes_only_web_service():
    compose = yaml.safe_load(Path("deploy/compose.yaml").read_text())
    assert "ports" in compose["services"]["web"]
    for service in ("api", "mysql", "redis"):
        assert "ports" not in compose["services"][service]


def test_env_example_contains_names_but_no_secret_values():
    text = Path("deploy/.env.example").read_text()
    for name in ("MYSQL_PASSWORD", "API_AUTH_TOKEN", "PERSON_KEY_SECRET"):
        assert f"{name}=" in text
    assert "sk-" not in text
```

- [x] **Step 2: Run test and verify red**

Run: `python -m pytest tests/test_deploy_contract.py -q`
Expected: FAIL because deployment files do not exist.

- [x] **Step 3: Implement containers and fail-fast configuration**

Build frontend and backend images separately. Configure Nginx same-origin `/api`, protected artifact downloads, upload limits, and Basic Auth or organization gateway integration. Add health checks and make `api` depend on completed migrations and healthy MySQL/Redis. Document backup of MySQL, artifacts, and `PERSON_KEY_SECRET`; never back up temporary uploads.

- [x] **Step 4: Verify deployment**

Run: `python -m pytest tests/test_deploy_contract.py -q`
Run: `docker compose -f deploy/compose.yaml config`
Run: `docker compose -f deploy/compose.yaml up --build -d && python scripts/check_ready.py`
Expected: configuration is valid, services become ready, and a fake-data smoke run can publish and download a report.

- [x] **Step 5: Commit each repository**

```bash
git add Dockerfile deploy scripts/check_ready.py README.md docs tests/test_deploy_contract.py
git commit -m "feat(deploy): package single-user production stack"

# Commit frontend and database Docker assets in their own repositories.
```

---

### Task 15: Full Regression, Privacy Scan, and Release Evidence

**Files:**
- Create: `scripts/run_single_user_regression.py`
- Create: `scripts/scan_sensitive_artifacts.py`
- Create: `docs/TESTING_SINGLE_USER_V1.md`
- Create: `docs/RELEASE_CHECKLIST_SINGLE_USER_V1.md`
- Modify: `README.md`
- Test: `tests/test_regression_harness_contract.py`

**Interfaces:**
- Harness accepts a mentor-local input root and output root; it never copies source files into the repository.
- Harness compares values, date columns, styles, merges, tenure controls, daily/weekly reconciliation, manifest, event ledger, and validation report.
- Privacy scanner fails on configured sensitive header values in logs, traces, Git-tracked fixtures, and failure output.

- [x] **Step 1: Write harness safety tests**

```python
def test_harness_requires_external_input_and_output_directories(tmp_path):
    with pytest.raises(ValueError, match="outside repository"):
        run_regression(REPO_ROOT / "tests", tmp_path)


def test_privacy_scanner_reports_file_and_rule_without_echoing_secret(tmp_path):
    bad = tmp_path / "trace.json"
    bad.write_text('{"证件号":"FAKE-SENSITIVE-VALUE"}')
    findings = scan_paths([tmp_path])
    assert findings[0].path == bad
    assert "FAKE-SENSITIVE-VALUE" not in findings[0].message
```

- [x] **Step 2: Run tests and verify red**

Run: `python -m pytest tests/test_regression_harness_contract.py -q`
Expected: FAIL because harness scripts do not exist.

- [x] **Step 3: Implement fake and mentor-local regression modes**

The committed mode runs fake fixtures. The mentor-local mode walks dated directories from 2026-07-08 through the latest accepted date, creates isolated test databases, executes daily and eligible weekly targets, and writes only a redacted summary outside the repository.

Real replay also locks natural-person deduplication and rolling first-visible semantics discovered on the 2026-07-13 accepted case. Missing OA LWD follows Q5: count Row5, exclude Row30 until a later input supplies an approved date.

- [x] **Step 4: Run release verification**

Run: `python -m pytest -q`
Run: `python scripts/run_single_user_regression.py --mode fake`
Run locally: `python scripts/run_single_user_regression.py --mode mentor-local --input-root "/Users/andrewhua/Desktop/Claude Project/project/日报" --start 2026-07-08 --output-root "/Users/andrewhua/Desktop/Claude Project/output/hr-agent-single-user-regression"`
Run: `python scripts/scan_sensitive_artifacts.py .`
Frontend run: `npm test -- --run && npm run lint && npm run build`
Expected: all automated tests pass; every accepted daily/weekly artifact matches; privacy scan has zero findings.

- [x] **Step 5: Commit release documentation and harness**

```bash
git add scripts docs README.md tests/test_regression_harness_contract.py
git commit -m "test: add production regression and privacy gates"
```

## Final Verification

Run from clean worktrees:

```bash
# Backend
python -m pytest -q

# Frontend
npm ci
npm test -- --run
npm run lint
npm run build

# Database/deployment
docker compose -f deploy/compose.yaml config
docker compose -f deploy/compose.yaml up --build -d
python scripts/check_ready.py

# Privacy and fake-data release evidence
python scripts/run_single_user_regression.py --mode fake
python scripts/scan_sensitive_artifacts.py .
```

Then run the mentor-local 2026-07-08 onward regression outside Git. Do not mark V1 deployable until daily and weekly outputs, execution notes, event ledgers, validation reports, and Excel style checks all pass.
