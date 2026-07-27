"""Run facts inherit first-visible semantics from the published baseline."""

from datetime import date, datetime

from sqlalchemy import select

from app.models.facts import (
    EmploymentFact,
    FactEvent,
    PersonIdentity,
    ReleaseFact,
    ResignationFact,
    decode_json_text,
    encode_json_text,
)
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunStatus
from app.services.fact_history_service import materialize_run_history


def _run(db, report_date: date, *, baseline_report_id: str | None = None):
    run = ReportRun(
        report_date=report_date,
        status=RunStatus.parsing.value,
        rule_version="rules-v1",
        baseline_report_id=baseline_report_id,
    )
    db.add(run)
    db.flush()
    return run


def _published_daily(db, run: ReportRun) -> PublishedReport:
    report = PublishedReport(
        run_id=run.id,
        report_kind="daily",
        period_start=run.report_date,
        period_end=run.report_date,
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="a" * 64,
        published_by="qa-operator",
        published_at=datetime(2026, 7, 10, 18, 0),
    )
    db.add(report)
    db.flush()
    return report


def _person(db, key: str = "a" * 64) -> PersonIdentity:
    person = PersonIdentity(
        person_key=key,
        key_version="v1",
        match_confidence="certificate",
        identity_namespace="certificate",
    )
    db.add(person)
    db.flush()
    return person


def _employment(
    run: ReportRun,
    person: PersonIdentity,
    row: int,
    employee_no: str,
    entry_date: date,
    *,
    first_visible: date | None = None,
) -> EmploymentFact:
    return EmploymentFact(
        run_id=run.id,
        source_row_no=row,
        person_id=person.id,
        employee_no=employee_no,
        employee_type="正式员工",
        status="在职",
        entry_date=entry_date,
        first_visible_dates=(
            encode_json_text({"hire": first_visible.isoformat()})
            if first_visible
            else None
        ),
    )


def test_bootstrap_run_uses_fact_dates_when_imported_baseline_has_no_facts(db):
    imported_run = _run(db, date(2026, 7, 7))
    baseline = _published_daily(db, imported_run)
    current = _run(db, date(2026, 7, 8), baseline_report_id=baseline.id)
    person = _person(db)
    employment = _employment(
        current, person, 2, "FAKE-E1", date(2025, 1, 1)
    )
    release = ReleaseFact(
        run_id=current.id,
        source_row_no=2,
        order_no="FAKE-O1",
        application_date=date(2026, 6, 30),
        row5_classification="include",
        row30_classification="exclude",
    )
    db.add_all([employment, release])
    db.flush()

    materialize_run_history(db, current, baseline)

    assert decode_json_text(employment.first_visible_dates) == {
        "hire": "2025-01-01"
    }
    assert release.first_visible_date == date(2026, 6, 30)


def test_rolling_run_marks_new_late_facts_visible_on_current_report_date(db):
    previous = _run(db, date(2026, 7, 10))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 13), baseline_report_id=baseline.id)
    person = _person(db)
    previous_employment = _employment(
        previous,
        person,
        2,
        "FAKE-OLD",
        date(2025, 1, 1),
        first_visible=date(2025, 1, 1),
    )
    previous_release = ReleaseFact(
        run_id=previous.id,
        source_row_no=2,
        order_no="FAKE-O-OLD",
        application_date=date(2026, 6, 20),
        first_visible_date=date(2026, 6, 20),
        row5_classification="include",
        row30_classification="exclude",
    )
    current_existing = _employment(
        current, person, 2, "FAKE-OLD", date(2025, 1, 1)
    )
    current_duplicate_a = _employment(
        current, person, 3, "FAKE-NEW-A", date(2026, 7, 6)
    )
    current_duplicate_b = _employment(
        current, person, 4, "FAKE-NEW-B", date(2026, 7, 13)
    )
    current_release_old = ReleaseFact(
        run_id=current.id,
        source_row_no=2,
        order_no="FAKE-O-OLD",
        application_date=date(2026, 6, 20),
        row5_classification="include",
        row30_classification="exclude",
    )
    current_release_late = ReleaseFact(
        run_id=current.id,
        source_row_no=3,
        order_no="FAKE-O-LATE",
        application_date=date(2026, 7, 10),
        row5_classification="include",
        row30_classification="exclude",
    )
    current_release_historical = ReleaseFact(
        run_id=current.id,
        source_row_no=4,
        order_no="FAKE-O-HISTORICAL",
        application_date=date(2026, 6, 21),
        row5_classification="include",
        row30_classification="exclude",
    )
    current_resignation_late = ResignationFact(
        run_id=current.id,
        source_row_no=2,
        process_no="FAKE-R-LATE",
        person_id=person.id,
        employee_no="FAKE-OLD",
        application_date=date(2026, 7, 10),
        resignation_type="主动离职",
    )
    db.add_all(
        [
            previous_employment,
            previous_release,
            current_existing,
            current_duplicate_a,
            current_duplicate_b,
            current_release_old,
            current_release_late,
            current_release_historical,
            current_resignation_late,
        ]
    )
    db.flush()

    materialize_run_history(db, current, baseline)

    assert decode_json_text(current_existing.first_visible_dates)["hire"] == (
        "2025-01-01"
    )
    assert decode_json_text(current_duplicate_a.first_visible_dates)["hire"] == (
        "2026-07-13"
    )
    assert decode_json_text(current_duplicate_b.first_visible_dates)["hire"] == (
        "2026-07-13"
    )
    assert current_release_old.first_visible_date == date(2026, 6, 20)
    assert current_release_late.first_visible_date == date(2026, 7, 13)
    assert current_release_historical.first_visible_date == date(2026, 6, 21)
    assert current_resignation_late.first_visible_date == date(2026, 7, 13)
    events = db.scalars(
        select(FactEvent).where(FactEvent.run_id == current.id)
    ).all()
    assert {event.event_type for event in events} >= {
        "hire",
        "release_proposed",
        "resignation_proposed",
    }


def test_materialization_is_idempotent(db):
    previous = _run(db, date(2026, 7, 10))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 13), baseline_report_id=baseline.id)
    person = _person(db)
    db.add(_employment(current, person, 2, "FAKE-E1", date(2026, 7, 13)))
    db.flush()

    materialize_run_history(db, current, baseline)
    first = db.scalars(
        select(FactEvent).where(FactEvent.run_id == current.id)
    ).all()
    materialize_run_history(db, current, baseline)
    second = db.scalars(
        select(FactEvent).where(FactEvent.run_id == current.id)
    ).all()

    assert len(first) == len(second) == 1


def test_missing_employee_is_carried_forward_only_with_effective_resignation(db):
    previous = _run(db, date(2026, 7, 7))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 8), baseline_report_id=baseline.id)
    departed_person = _person(db, "b" * 64)
    current_person = _person(db, "c" * 64)
    previous_departed = _employment(
        previous,
        departed_person,
        2,
        "FAKE-DEPARTED",
        date(2024, 3, 1),
        first_visible=date(2024, 3, 1),
    )
    current_survivor = _employment(
        current,
        current_person,
        2,
        "FAKE-CURRENT",
        date(2025, 5, 1),
    )
    resignation = ResignationFact(
        run_id=current.id,
        source_row_no=2,
        process_no="FAKE-R-EFFECTIVE",
        person_id=departed_person.id,
        employee_no="FAKE-DEPARTED",
        process_status="审批完成",
        application_date=date(2026, 7, 6),
        last_working_day=current.report_date,
        resignation_type="主动离职",
    )
    db.add_all([previous_departed, current_survivor, resignation])
    db.flush()

    materialize_run_history(db, current, baseline)

    carried = db.scalar(
        select(EmploymentFact).where(
            EmploymentFact.run_id == current.id,
            EmploymentFact.employee_no == "FAKE-DEPARTED",
        )
    )
    assert carried is not None
    assert carried.source_row_no < 0
    assert carried.status == "离职"
    assert carried.resign_date == current.report_date
    assert decode_json_text(carried.first_visible_dates) == {
        "hire": "2024-03-01",
        "leave": "2026-07-06",
    }
    event = db.scalar(
        select(FactEvent).where(
            FactEvent.run_id == current.id,
            FactEvent.employment_ref == carried.id,
            FactEvent.event_type == "leave",
        )
    )
    assert event is not None
    assert event.source_type == "personnel_history"


def test_published_late_departure_is_carried_without_resignation_process(db):
    previous = _run(db, date(2026, 7, 8))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 9), baseline_report_id=baseline.id)
    person = _person(db, "e" * 64)
    previous_departed = EmploymentFact(
        run_id=previous.id,
        source_row_no=2,
        person_id=person.id,
        employee_no="FAKE-LATE-DEPARTURE",
        employee_type="正式员工",
        status="离职",
        entry_date=date(2024, 3, 1),
        resign_date=date(2026, 7, 3),
        business_unit="FAKE-BU",
        business_unit_no="FAKE-BU",
        project_code="FAKE-PROJECT",
        project_name="FAKE-PROJECT",
        first_visible_dates=encode_json_text(
            {"hire": "2024-03-01", "leave": "2026-07-08"}
        ),
    )
    db.add(previous_departed)
    db.flush()

    materialize_run_history(db, current, baseline)

    carried = db.scalar(
        select(EmploymentFact).where(
            EmploymentFact.run_id == current.id,
            EmploymentFact.employee_no == "FAKE-LATE-DEPARTURE",
        )
    )
    assert carried is not None
    assert carried.source_row_no < 0
    assert carried.status == "离职"
    assert carried.resign_date == date(2026, 7, 3)
    assert decode_json_text(carried.first_visible_dates) == {
        "hire": "2024-03-01",
        "leave": "2026-07-08",
    }


def test_prior_week_personnel_departure_is_not_carried_forward(db):
    previous = _run(db, date(2026, 7, 10))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 13), baseline_report_id=baseline.id)
    person = _person(db, "f" * 64)
    db.add(
        EmploymentFact(
            run_id=previous.id,
            source_row_no=2,
            person_id=person.id,
            employee_no="FAKE-OLD-DEPARTURE",
            employee_type="正式员工",
            status="离职",
            entry_date=date(2024, 3, 1),
            resign_date=date(2026, 7, 3),
            first_visible_dates=encode_json_text(
                {"hire": "2024-03-01", "leave": "2026-07-08"}
            ),
        )
    )
    db.flush()

    materialize_run_history(db, current, baseline)

    carried = db.scalar(
        select(EmploymentFact).where(
            EmploymentFact.run_id == current.id,
            EmploymentFact.employee_no == "FAKE-OLD-DEPARTURE",
        )
    )
    assert carried is None


def test_missing_employee_is_not_carried_for_pending_resignation(db):
    previous = _run(db, date(2026, 7, 7))
    baseline = _published_daily(db, previous)
    current = _run(db, date(2026, 7, 8), baseline_report_id=baseline.id)
    person = _person(db, "d" * 64)
    db.add_all(
        [
            _employment(
                previous,
                person,
                2,
                "FAKE-PENDING",
                date(2024, 3, 1),
                first_visible=date(2024, 3, 1),
            ),
            ResignationFact(
                run_id=current.id,
                source_row_no=2,
                process_no="FAKE-R-PENDING",
                person_id=person.id,
                employee_no="FAKE-PENDING",
                process_status="审批中",
                application_date=date(2026, 7, 6),
                last_working_day=current.report_date,
                resignation_type="主动离职",
            ),
        ]
    )
    db.flush()

    materialize_run_history(db, current, baseline)

    carried = db.scalar(
        select(EmploymentFact).where(
            EmploymentFact.run_id == current.id,
            EmploymentFact.employee_no == "FAKE-PENDING",
        )
    )
    assert carried is None
