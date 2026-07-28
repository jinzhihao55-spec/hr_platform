"""Typed Run APIs expose workflow metadata without protected fact fields."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.database import get_db
from app.main import app
from app.models.facts import (
    EmploymentFact,
    PersonIdentity,
    ReleaseFact,
    RunDecision,
    encode_json_text,
)
from app.models.publication import PublishedReport
from app.pipeline.calculation.weekly import top3_tie_ref
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
from app.services.run_validation_service import replace_calculation_validations


@pytest.fixture()
def api_client(api_db):
    def override_db():
        yield api_db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _stale_baseline_scenario(api_db, *, status=RunStatus.ready.value):
    def published_daily(report_date, version, hash_char):
        run = ReportRun(
            report_date=report_date,
            status=RunStatus.ready.value,
            rule_version="rules-v1",
        )
        api_db.add(run)
        api_db.flush()
        report = PublishedReport(
            run_id=run.id,
            report_kind="daily",
            period_start=report_date,
            period_end=report_date,
            version=version,
            is_current=True,
            snapshot_json="{}",
            snapshot_hash=hash_char * 64,
            published_by="test-operator",
            published_at=datetime.combine(report_date, datetime.min.time()),
        )
        api_db.add(report)
        api_db.flush()
        return report

    old_baseline = published_daily(date(2026, 7, 21), 1, "a")
    latest_baseline = published_daily(date(2026, 7, 24), 2, "b")
    stale_run = ReportRun(
        report_date=date(2026, 7, 27),
        status=status,
        rule_version="rules-v1",
        baseline_report_id=old_baseline.id,
    )
    api_db.add(stale_run)
    api_db.commit()
    return stale_run, old_baseline, latest_baseline


def test_create_run_then_get_typed_workflow_view(api_client):
    created = api_client.post(
        "/runs", json={"report_date": "2026-07-15"}
    )

    assert created.status_code == 201
    run_id = created.json()["run"]["id"]
    view = api_client.get(f"/runs/{run_id}")

    assert view.status_code == 200
    payload = view.json()
    assert payload["report_date"] == "2026-07-15"
    assert {target["report_kind"] for target in payload["targets"]} == {
        "daily",
        "weekly",
    }
    assert payload["sources"] == []
    assert payload["decisions"] == []


def test_get_release_ocr_decision_preview(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.needs_review.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="ocr_review_required",
        fact_ref="source:release:row:ocr",
        question="请确认 OA/Release 图片识别结果。",
        options=encode_json_text(["确认", "替换输入"]),
        status="pending",
    )
    api_db.add_all(
        [
            decision,
            ReleaseFact(
                run_id=run.id,
                source_row_no=2,
                order_no="FAKE-REL-001",
                employee_no="FAKE-EMP-SECRET",
                application_date=date(2026, 7, 17),
                last_working_day=date(2026, 7, 30),
                process_status="审批中",
                row5_classification="include",
                row30_classification="include",
                ocr_confidence="unreviewed",
            ),
        ]
    )
    api_db.commit()

    response = api_client.get(
        f"/runs/{run.id}/decisions/{decision.id}/preview"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_type"] == "release"
    assert payload["rows"][0]["order_no"] == "FAKE-REL-001"
    assert "FAKE-EMP-SECRET" not in response.text


def test_ocr_decision_preview_maps_missing_facts_to_conflict(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.needs_review.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    decision = RunDecision(
        run_id=run.id,
        report_kind=None,
        decision_code="ocr_review_required",
        fact_ref="source:release:row:ocr",
        question="请确认 OA/Release 图片识别结果。",
        options=encode_json_text(["确认", "替换输入"]),
        status="pending",
    )
    api_db.add(decision)
    api_db.commit()

    response = api_client.get(
        f"/runs/{run.id}/decisions/{decision.id}/preview"
    )

    assert response.status_code == 409
    assert "重新上传" in response.json()["detail"]


def test_ocr_decision_preview_rejects_cross_run_decision(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    other_run = ReportRun(
        report_date=date(2026, 7, 18),
        status=RunStatus.needs_review.value,
        rule_version="rules-v1",
    )
    api_db.add_all([run, other_run])
    api_db.flush()
    decision = RunDecision(
        run_id=other_run.id,
        report_kind=None,
        decision_code="ocr_review_required",
        fact_ref="source:release:row:ocr",
        question="请确认 OA/Release 图片识别结果。",
        options=encode_json_text(["确认", "替换输入"]),
        status="pending",
    )
    api_db.add(decision)
    api_db.commit()

    response = api_client.get(
        f"/runs/{run.id}/decisions/{decision.id}/preview"
    )

    assert response.status_code == 422


def test_get_weekly_duplicate_review_details(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    person = PersonIdentity(
        person_key="fake-person-key",
        key_version="v1",
        match_confidence="fake",
        identity_namespace="test",
    )
    api_db.add_all([run, person])
    api_db.flush()
    api_db.add_all(
        [
            EmploymentFact(
                run_id=run.id,
                source_row_no=7,
                person_id=person.id,
                employee_no="FAKE-E1",
                display_name="测试甲",
                employee_type="正式员工",
                status="active",
                entry_date=date(2025, 1, 1),
                business_unit="网络事业部",
                business_unit_no="NENT",
                project_code="FAKE-P1",
                project_name="测试项目",
            ),
            EmploymentFact(
                run_id=run.id,
                source_row_no=8,
                person_id=person.id,
                employee_no="FAKE-E2",
                display_name="测试甲",
                employee_type="正式员工",
                status="active",
                entry_date=date(2026, 7, 8),
                business_unit="网络事业部",
                business_unit_no="NENT",
                project_code="FAKE-P1",
                project_name="测试项目",
            ),
        ]
    )
    api_db.flush()
    replace_calculation_validations(
        api_db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "multiple_active_employments",
                "severity": "REVIEW",
                "person_ref": "abc123def456",
                "employment_source_row_nos": [7, 8],
                "selected_source_row_no": 8,
                "conflicting_dimensions": [],
            }
        ],
    )

    response = api_client.get(f"/runs/{run.id}/weekly/review")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["resolution"] == "confirm_dedupe"
    assert item["employments"][1]["selected"] is True
    assert "fake-person-key" not in response.text
    assert "person_key" not in response.text


def test_get_weekly_top3_tie_review_options(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    replace_calculation_validations(
        api_db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "top3_cutoff_tie",
                "severity": "REVIEW",
                "business_unit": "FAKE-BU-A",
                "tie_ref": top3_tie_ref("FAKE-BU-A"),
                "candidates": ["AlphaTie", "ZuluTie"],
                "slots": 1,
                "selected_projects": ["AlphaTie"],
            }
        ],
    )

    response = api_client.get(f"/runs/{run.id}/weekly/review")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["kind"] == "top3_cutoff_tie"
    assert item["candidates"] == ["AlphaTie", "ZuluTie"]
    assert item["slots"] == 1


def test_post_weekly_top3_tie_after_daily_publish(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    replace_calculation_validations(
        api_db,
        run.id,
        "weekly",
        checks=[],
        review_items=[
            {
                "code": "top3_cutoff_tie",
                "severity": "REVIEW",
                "business_unit": "FAKE-BU-A",
                "tie_ref": top3_tie_ref("FAKE-BU-A"),
                "candidates": ["AlphaTie", "ZuluTie"],
                "slots": 1,
                "selected_projects": ["AlphaTie"],
            }
        ],
    )
    decision = api_db.query(RunDecision).filter_by(
        run_id=run.id,
        decision_code="top3_cutoff_tie",
    ).one()
    api_db.add(
        RunReportTarget(
            run_id=run.id,
            report_kind="daily",
            status=TargetStatus.published.value,
        )
    )
    api_db.commit()

    response = api_client.post(
        f"/runs/{run.id}/decisions/{decision.id}",
        json={"answer": ["ZuluTie"], "operator_ref": "local-operator"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == ["ZuluTie"]
    assert response.json()["status"] == "answered"
    view = api_client.get(f"/runs/{run.id}").json()
    weekly_target = next(
        target for target in view["targets"] if target["report_kind"] == "weekly"
    )
    assert weekly_target["status"] == TargetStatus.ready.value
    assert weekly_target["validation_summary"]["pending_decision_count"] == 0


def test_same_day_revision_run_does_not_copy_frozen_facts(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 17),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    person = PersonIdentity(
        person_key="fake-person-key",
        key_version="v1",
        match_confidence="fake",
        identity_namespace="test",
    )
    api_db.add_all([run, person])
    api_db.flush()
    api_db.add(
        EmploymentFact(
            run_id=run.id,
            source_row_no=2,
            person_id=person.id,
            employee_no="FAKE-E1",
            employee_type="正式员工",
            status="active",
        )
    )
    api_db.commit()

    response = api_client.post(
        "/runs",
        json={"report_date": "2026-07-17", "create_new": True},
    )

    assert response.status_code == 201
    revision_id = response.json()["run"]["id"]
    assert revision_id != run.id
    assert api_db.query(EmploymentFact).filter_by(run_id=revision_id).count() == 0


def test_stale_baseline_is_visible_and_revision_uses_latest_daily(
    api_db, api_client
):
    stale_run, _, latest_baseline = _stale_baseline_scenario(api_db)

    view = api_client.get(f"/runs/{stale_run.id}")

    assert view.status_code == 200
    payload = view.json()
    assert payload["baseline_status"] == "stale"
    assert payload["baseline_period_end"] == "2026-07-21"
    assert payload["baseline_version"] == 1
    assert payload["latest_baseline_report_id"] == latest_baseline.id
    assert payload["latest_baseline_period_end"] == "2026-07-24"
    assert payload["latest_baseline_version"] == 2

    revision = api_client.post(
        "/runs",
        json={"report_date": "2026-07-27", "create_new": True},
    )

    assert revision.status_code == 201
    assert revision.json()["run"]["baseline_report_id"] == latest_baseline.id


def test_stale_baseline_blocks_source_upload_before_file_is_read(
    api_db, api_client, monkeypatch
):
    stale_run, _, _ = _stale_baseline_scenario(
        api_db,
        status=RunStatus.created.value,
    )
    called = []

    async def should_not_ingest(*_args, **_kwargs):
        called.append(True)

    from app.services.run_source_service import RunSourceService

    monkeypatch.setattr(RunSourceService, "ingest", should_not_ingest)

    response = api_client.put(
        f"/runs/{stale_run.id}/sources/personnel",
        files={"file": ("fake.xlsx", b"must-not-be-read", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert "2026-07-21 v1" in response.json()["detail"]
    assert "2026-07-24 v2" in response.json()["detail"]
    assert called == []


def test_stale_baseline_blocks_unpublished_preview(api_db, api_client):
    stale_run, _, _ = _stale_baseline_scenario(api_db)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/runs/{stale_run.id}/preview/daily")

    assert response.status_code == 409
    assert "创建同日修订 Run" in response.json()["detail"]


def test_report_history_list_does_not_select_snapshot_payload(api_db, api_client):
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(run)
    api_db.flush()
    api_db.add(
        PublishedReport(
            run_id=run.id,
            report_kind="daily",
            period_start=run.report_date,
            period_end=run.report_date,
            version=1,
            is_current=True,
            snapshot_json='{"large":"' + ('x' * 10000) + '"}',
            snapshot_hash="a" * 64,
            published_by="test-operator",
            published_at=datetime(2026, 7, 8, 18, 0),
        )
    )
    api_db.commit()
    statements = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(api_db.bind, "before_cursor_execute", capture_sql)
    try:
        response = api_client.get("/reports/daily")
    finally:
        event.remove(api_db.bind, "before_cursor_execute", capture_sql)

    assert response.status_code == 200
    assert len(response.json()) == 1
    report_queries = [
        statement.lower()
        for statement in statements
        if "from published_reports" in statement.lower()
    ]
    assert report_queries
    assert all("snapshot_json" not in statement for statement in report_queries)


def test_run_view_never_returns_protected_fact_fields(api_db, api_client):
    db = api_db
    run = ReportRun(
        report_date=date(2026, 7, 15),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    person = PersonIdentity(
        person_key="a" * 64,
        key_version="v1",
        match_confidence="certificate",
        identity_namespace="certificate",
    )
    db.add_all([run, person])
    db.flush()
    db.add(
        EmploymentFact(
            run_id=run.id,
            source_row_no=2,
            person_id=person.id,
            employee_no="SECRET-E1",
            display_name="秘密姓名",
            employee_type="正式员工",
        )
    )
    db.add_all(
        [
            RunReportTarget(
                run_id=run.id,
                report_kind=kind,
                status=TargetStatus.draft.value,
            )
            for kind in ("daily", "weekly")
        ]
    )
    db.commit()

    body = api_client.get(f"/runs/{run.id}").text

    assert "SECRET-E1" not in body
    assert "秘密姓名" not in body
    assert "person_key" not in body


def test_unknown_source_type_is_rejected_before_reading_file(
    api_db, api_client, monkeypatch
):
    db = api_db
    run = ReportRun(
        report_date=date(2026, 7, 15),
        status=RunStatus.created.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.commit()
    called = []

    async def should_not_run(*_args, **_kwargs):
        called.append(True)

    from app.services.run_source_service import RunSourceService

    monkeypatch.setattr(RunSourceService, "ingest", should_not_run)
    response = api_client.put(
        f"/runs/{run.id}/sources/unknown",
        files={"file": ("fake.xlsx", b"must-not-be-read", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert called == []


def test_missing_run_returns_404(api_client):
    response = api_client.get("/runs/not-a-real-run")

    assert response.status_code == 404


def test_publish_failure_does_not_expose_internal_exception(api_client, monkeypatch):
    from app.services import publication_service

    secret = "SECRET-SNAPSHOT-CONTENT"

    def fail_publish(*_args, **_kwargs):
        raise publication_service.PublicationFailed(
            f"database rejected snapshot_json containing {secret}"
        )

    monkeypatch.setattr(publication_service, "publish", fail_publish)

    response = api_client.post(
        "/runs/fake-run/publish",
        json={"report_kinds": ["daily"], "operator_ref": "local-operator"},
    )

    assert response.status_code == 409
    assert secret not in response.text
    assert response.json()["detail"] == "报表发布失败，请检查系统状态后重试"


def test_parse_finalizes_four_source_fingerprint_and_marks_run_ready(
    api_db, api_client
):
    db = api_db
    baseline_run = ReportRun(
        report_date=date(2026, 7, 14),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(baseline_run)
    db.flush()
    baseline = PublishedReport(
        run_id=baseline_run.id,
        report_kind="daily",
        period_start=date(2026, 7, 14),
        period_end=date(2026, 7, 14),
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="b" * 64,
        published_by="local-operator",
        published_at=datetime(2026, 7, 14, 18, 0, 0),
    )
    db.add(baseline)
    db.commit()
    created = api_client.post(
        "/runs", json={"report_date": "2026-07-15"}
    ).json()["run"]
    run = db.get(ReportRun, created["id"])
    run.status = RunStatus.parsing.value
    for index, source in enumerate(SourceType):
        db.add(
            RunSource(
                run_id=run.id,
                source_type=source.value,
                sha256=f"{index + 1}" * 64,
                schema_version=f"{source.value}-v1",
                parser_version="test-v1",
                row_count=1,
                parse_status="parsed",
                original_extension=".xlsx",
            )
        )
    db.commit()

    response = api_client.post(f"/runs/{run.id}/parse")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert len(response.json()["source_bundle_hash"]) == 64
    assert response.json()["baseline_report_id"] == baseline.id


def test_parse_is_idempotent_after_run_is_ready(
    api_db, api_client, monkeypatch
):
    baseline_run = ReportRun(
        report_date=date(2026, 7, 14),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(baseline_run)
    api_db.flush()
    baseline = PublishedReport(
        run_id=baseline_run.id,
        report_kind="daily",
        period_start=date(2026, 7, 14),
        period_end=date(2026, 7, 14),
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="b" * 64,
        published_by="local-operator",
        published_at=datetime(2026, 7, 14, 18, 0),
    )
    api_db.add(baseline)
    api_db.flush()
    run = ReportRun(
        report_date=date(2026, 7, 15),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
        source_bundle_hash="c" * 64,
        baseline_report_id=baseline.id,
    )
    api_db.add(run)
    api_db.flush()
    api_db.add_all(
        [
            RunReportTarget(
                run_id=run.id,
                report_kind=kind,
                status=TargetStatus.draft.value,
            )
            for kind in ("daily", "weekly")
        ]
    )
    for index, source in enumerate(SourceType):
        api_db.add(
            RunSource(
                run_id=run.id,
                source_type=source.value,
                sha256=f"{index + 1}" * 64,
                schema_version=f"{source.value}-v1",
                parser_version="test-v1",
                row_count=0,
                parse_status="parsed",
                original_extension=".xlsx",
            )
        )
    api_db.commit()

    def must_not_rematerialize(*_args, **_kwargs):
        raise AssertionError("ready Run history must remain immutable")

    monkeypatch.setattr(
        "app.services.run_workflow_service.materialize_run_history",
        must_not_rematerialize,
    )

    response = api_client.post(f"/runs/{run.id}/parse")

    assert response.status_code == 200
    assert response.json()["status"] == RunStatus.ready.value


def test_initial_baseline_can_be_finalized_from_the_same_run(
    api_client, monkeypatch
):
    from app.services import daily_import_service

    captured = {}

    async def fake_finalize(db, run_id, file, imported_by="local-operator"):
        captured.update(
            {
                "run_id": run_id,
                "filename": file.filename,
                "imported_by": imported_by,
            }
        )
        return {
            "report_date": "2026-07-07",
            "status": "succeeded",
            "overwritten": False,
            "rows_imported": 21,
            "baseline_report_id": "baseline-from-run",
            "kpis": {},
            "cascaded": [],
        }

    monkeypatch.setattr(
        daily_import_service, "finalize_initial_run_baseline", fake_finalize
    )

    response = api_client.post(
        "/runs/run-initial/baseline",
        files={
            "file": (
                "已验收日报.xlsx",
                b"approved",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers={"x-authenticated-user": "qa-operator"},
    )

    assert response.status_code == 200
    assert response.json()["baseline_report_id"] == "baseline-from-run"
    assert captured == {
        "run_id": "run-initial",
        "filename": "已验收日报.xlsx",
        "imported_by": "qa-operator",
    }


def test_pending_review_does_not_materialize_history_repeatedly(
    api_db, api_client, monkeypatch
):
    baseline_run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    api_db.add(baseline_run)
    api_db.flush()
    baseline = PublishedReport(
        run_id=baseline_run.id,
        report_kind="daily",
        period_start=baseline_run.report_date,
        period_end=baseline_run.report_date,
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="b" * 64,
        published_by="local-operator",
        published_at=datetime(2026, 7, 8, 18, 0),
    )
    api_db.add(baseline)
    api_db.flush()
    run = ReportRun(
        report_date=date(2026, 7, 9),
        status=RunStatus.parsing.value,
        rule_version="rules-v1",
        baseline_report_id=baseline.id,
    )
    api_db.add(run)
    api_db.flush()
    for index, source in enumerate(SourceType):
        api_db.add(
            RunSource(
                run_id=run.id,
                source_type=source.value,
                sha256=f"{index + 1}" * 64,
                schema_version=f"{source.value}-v1",
                parser_version="test-v1",
                row_count=1,
                parse_status="parsed",
                original_extension=".xlsx",
            )
        )
    api_db.add(
        RunDecision(
            run_id=run.id,
            report_kind=None,
            decision_code="ocr_review_required",
            fact_ref="source:release:row:ocr",
            question="确认 OCR 结果",
            options='["确认","替换输入"]',
            status="pending",
        )
    )
    api_db.commit()
    calls = []
    monkeypatch.setattr(
        "app.services.run_workflow_service.materialize_run_history",
        lambda *_args, **_kwargs: calls.append(True),
    )

    response = api_client.post(f"/runs/{run.id}/parse")

    assert response.status_code == 200
    assert response.json()["status"] == RunStatus.needs_review.value
    assert calls == []
