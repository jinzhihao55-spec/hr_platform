"""Run fingerprinting, lifecycle, deduplication, and source metadata tests."""

from datetime import date

import pytest
from sqlalchemy import select

from app.domain.run_fingerprint import (
    IncompleteSourceBundle,
    UnexpectedSourceBundleKeys,
    compute_source_bundle_hash,
)
from app.models.runs import ReportRun, RunReportTarget, RunStatus, SourceType
from app.repositories.run_repo import (
    InvalidRunTransition,
    create_provisional_run,
    ensure_report_targets,
    finalize_run_fingerprint,
    get_canonical_run,
    transition_run,
    upsert_source_metadata,
)


SOURCE_HASHES = {
    "personnel": "a" * 64,
    "resignation": "b" * 64,
    "release": "c" * 64,
    "recruitment": "d" * 64,
}


def test_fingerprint_is_order_independent_but_baseline_sensitive():
    forward = compute_source_bundle_hash(
        SOURCE_HASHES, "baseline-1", "e" * 64
    )
    reverse = compute_source_bundle_hash(
        dict(reversed(list(SOURCE_HASHES.items()))), "baseline-1", "e" * 64
    )
    different_baseline = compute_source_bundle_hash(
        SOURCE_HASHES, "baseline-2", "f" * 64
    )

    assert forward == reverse
    assert forward != different_baseline
    assert len(forward) == 64


def test_fingerprint_rejects_incomplete_source_bundle():
    incomplete = dict(SOURCE_HASHES)
    incomplete.pop("release")

    with pytest.raises(IncompleteSourceBundle) as caught:
        compute_source_bundle_hash(incomplete, "baseline-1", "e" * 64)

    assert caught.value.missing == ("release",)


def test_fingerprint_rejects_unexpected_source_keys():
    source_hashes = {**SOURCE_HASHES, "unapproved": "f" * 64}

    with pytest.raises(UnexpectedSourceBundleKeys) as caught:
        compute_source_bundle_hash(source_hashes, "baseline-1", "e" * 64)

    assert caught.value.unexpected == ("unapproved",)


def test_invalid_run_transition_is_rejected(db):
    run = create_provisional_run(db, date(2026, 7, 8), "rules-v1", None)

    with pytest.raises(InvalidRunTransition, match="created.*published"):
        transition_run(db, run, "published")


def test_allowed_run_transitions_are_explicit(db):
    run = create_provisional_run(db, date(2026, 7, 8), "rules-v1", None)

    transition_run(db, run, RunStatus.parsing)
    transition_run(db, run, RunStatus.needs_review)
    transition_run(db, run, RunStatus.ready)

    assert run.status == RunStatus.ready.value


def test_source_metadata_upsert_reuses_one_row_per_type(db):
    run = create_provisional_run(db, date(2026, 7, 8), "rules-v1", None)
    source = upsert_source_metadata(
        db,
        run.id,
        SourceType.personnel,
        sha256="a" * 64,
        schema_version="personnel-v1",
        parser_version="parser-v1",
        media_type="application/vnd.fake.sheet",
        row_count=2,
        parse_status="parsed",
        original_extension=".xlsx",
        original_filename="人员表_初版.xlsx",
    )
    updated = upsert_source_metadata(
        db,
        run.id,
        SourceType.personnel,
        sha256="b" * 64,
        schema_version="personnel-v1",
        parser_version="parser-v2",
        media_type="application/vnd.fake.sheet",
        row_count=3,
        parse_status="parsed",
        original_extension=".xlsx",
        original_filename="人员表_修订版.xlsx",
    )

    assert updated.id == source.id
    assert updated.sha256 == "b" * 64
    assert updated.row_count == 3
    assert updated.original_filename == "人员表_修订版.xlsx"


def test_report_targets_are_created_once_and_returned_in_fixed_order(db):
    run = create_provisional_run(db, date(2026, 7, 8), "rules-v1", None)

    first = ensure_report_targets(db, run.id)
    second = ensure_report_targets(db, run.id)

    assert [target.report_kind for target in first] == ["daily", "weekly"]
    assert [target.id for target in second] == [target.id for target in first]
    assert len(
        db.scalars(
            select(RunReportTarget).where(RunReportTarget.run_id == run.id)
        ).all()
    ) == 2


def test_finalizing_duplicate_run_returns_canonical_and_marks_provisional(db):
    canonical = create_provisional_run(
        db, date(2026, 7, 8), "rules-v1", "baseline-1"
    )
    transition_run(db, canonical, RunStatus.parsing)
    returned = finalize_run_fingerprint(
        db,
        canonical,
        SOURCE_HASHES,
        baseline_report_id="baseline-1",
        baseline_sha256="e" * 64,
    )
    assert returned.id == canonical.id

    provisional = create_provisional_run(
        db, date(2026, 7, 8), "rules-v1", "baseline-1"
    )
    transition_run(db, provisional, RunStatus.parsing)
    duplicate_result = finalize_run_fingerprint(
        db,
        provisional,
        SOURCE_HASHES,
        baseline_report_id="baseline-1",
        baseline_sha256="e" * 64,
    )

    assert duplicate_result.id == canonical.id
    assert provisional.status == RunStatus.deduplicated.value
    assert provisional.canonical_run_id == canonical.id
    assert provisional.source_bundle_hash is None
    assert get_canonical_run(db, provisional).id == canonical.id


def test_finalized_run_can_be_loaded_by_its_fingerprint(db):
    run = create_provisional_run(db, date(2026, 7, 9), "rules-v1", "baseline-1")
    transition_run(db, run, RunStatus.parsing)
    finalize_run_fingerprint(
        db,
        run,
        SOURCE_HASHES,
        baseline_report_id="baseline-1",
        baseline_sha256="e" * 64,
    )
    db.commit()

    loaded = db.scalar(select(ReportRun).where(ReportRun.id == run.id))
    assert loaded is not None
    assert loaded.source_bundle_hash == compute_source_bundle_hash(
        SOURCE_HASHES, "baseline-1", "e" * 64
    )
