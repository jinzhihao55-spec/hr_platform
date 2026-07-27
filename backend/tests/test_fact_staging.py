"""All four formal sources stage into the same run-scoped fact contract."""

import asyncio
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from fastapi import UploadFile

from app.models.facts import ReleaseFact, RunDecision
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunStatus, SourceType
from app.repositories import fact_repo
from app.services.run_source_service import RunSourceService


def _run(db) -> ReportRun:
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.created.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.commit()
    return run


def _xlsx_upload(rows: list[dict], filename: str) -> UploadFile:
    stream = BytesIO()
    pd.DataFrame(rows).to_excel(stream, index=False)
    stream.seek(0)
    return UploadFile(filename=filename, file=stream)


def test_resignation_reuses_personnel_identity_by_certificate(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    personnel = _xlsx_upload(
        [
            {
                "员工类型": "正式员工",
                "工号": "FAKE-E1",
                "员工状态": "在职",
                "事业部编号": "FAKE-BU1",
                "证件类型": "身份证",
                "证件号": "FAKE-CERT-1",
            }
        ],
        "人员表.xlsx",
    )
    resignation = _xlsx_upload(
        [
            {
                "流程单号": "FAKE-P1",
                "流程状态": "已完成",
                "离职方式": "主动离职",
                "工号": "FAKE-E1",
                "员工申请时间": "2026-07-08",
                "最后工作日": "2026-07-31",
                "证件类型": "居民身份证",
                "证件号码": "fake-cert-1",
            }
        ],
        "离职人员报表.xlsx",
    )

    asyncio.run(service.ingest(run.id, SourceType.personnel, personnel))
    asyncio.run(service.ingest(run.id, SourceType.resignation, resignation))

    employment = fact_repo.list_employment_facts(db, run.id)[0]
    resignation_fact = fact_repo.list_resignation_facts(db, run.id)[0]
    assert resignation_fact.person_id == employment.person_id
    assert resignation_fact.application_date == date(2026, 7, 8)
    assert resignation_fact.last_working_day == date(2026, 7, 31)


def test_structured_release_and_recruitment_stage_minimal_values(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    release = _xlsx_upload(
        [
            {
                "单号": "FAKE-O1",
                "申请时间": "2026-07-08",
                "当前状态": "已完成",
                "最后工作日": "2026-07-30",
                "计入Row5": "是",
                "计入Row30": "是",
            }
        ],
        "OA_Release.xlsx",
    )
    recruitment = _xlsx_upload(
        [
            {
                "招聘专员": "测试招聘甲",
                "6月接受offer在7月即将入职": 2,
                "7月接受offer在7月即将入职": 3,
                "7月已入职确认人数": 1,
            },
            {
                "招聘专员": "合计",
                "6月接受offer在7月即将入职": 2,
                "7月接受offer在7月即将入职": 3,
                "7月已入职确认人数": 1,
            },
        ],
        "招聘数据.xlsx",
    )

    asyncio.run(service.ingest(run.id, SourceType.release, release))
    asyncio.run(service.ingest(run.id, SourceType.recruitment, recruitment))

    release_fact = fact_repo.list_release_facts(db, run.id)[0]
    recruitment_facts = fact_repo.list_recruitment_snapshots(db, run.id)
    assert release_fact.order_no == "FAKE-O1"
    assert release_fact.row5_classification == "include"
    assert release_fact.row30_classification == "include"
    assert recruitment_facts[0].previous_month_offer_current_month_onboard == 2
    assert recruitment_facts[0].current_month_offer_current_month_onboard == 3
    assert len(recruitment_facts) == 2
    assert recruitment_facts[1].is_total_row is True


def test_release_detail_excel_auto_classifies_row5_and_row30(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    release = _xlsx_upload(
        [
            {
                "单号": "FAKE-DETAIL-1",
                "申请时间": "2026-07-08",
                "创建人": "测试创建人",
                "被申请人姓名": "测试员工甲",
                "职位": "测试职位",
                "项目名称": "测试项目",
                "入职时间": "2025-01-01",
                "最后工作日": "2026-07-30",
                "在岗时长": 575,
            },
            {
                "单号": "FAKE-DETAIL-2",
                "申请时间": "2026-07-08",
                "创建人": "测试创建人",
                "被申请人姓名": "测试员工乙",
                "职位": "测试职位",
                "项目名称": "测试项目",
                "入职时间": "2025-02-01",
                "最后工作日": "2026-08-14",
                "在岗时长": 559,
            },
        ],
        "Release明细.xlsx",
    )

    result = asyncio.run(service.ingest(run.id, SourceType.release, release))

    facts = fact_repo.list_release_facts(db, run.id)
    assert result.parse_status == "parsed"
    assert [fact.row5_classification for fact in facts] == ["include", "include"]
    assert [fact.row30_classification for fact in facts] == ["include", "exclude"]
    assert db.query(RunDecision).filter_by(run_id=run.id).count() == 0


def test_release_image_stages_review_decision(db, tmp_path, monkeypatch):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    upload = UploadFile(filename="OA_Release.png", file=BytesIO(b"fake-image"))

    def fake_convert(_path, table_type, tmp_dir):
        assert table_type == "agreements"
        target = tmp_path / "release-from-image.xlsx"
        pd.DataFrame(
            [
                {
                    "单号": "FAKE-OCR-O1",
                    "申请时间": "2026-07-08",
                    "当前状态": "等待审批",
                    "最后工作日": "2026-07-31",
                }
            ]
        ).to_excel(target, index=False)
        return str(target)

    monkeypatch.setattr(
        "app.services.run_source_service.image_parser.convert_to_xlsx", fake_convert
    )

    result = asyncio.run(service.ingest(run.id, SourceType.release, upload))

    assert result.parse_status == "needs_review"
    decisions = db.query(RunDecision).filter_by(run_id=run.id).all()
    assert {decision.decision_code for decision in decisions} == {
        "ocr_review_required",
        "release_lwd_missing",
        "release_row5_classification_required",
    }
    release_fact = fact_repo.list_release_facts(db, run.id)[0]
    assert release_fact.row30_classification == "review"
    assert all("fake-image" not in (decision.answer or "") for decision in decisions)


def test_release_image_reuses_published_lwd_for_same_order(db, tmp_path, monkeypatch):
    previous = ReportRun(
        report_date=date(2026, 7, 7),
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(previous)
    db.flush()
    db.add(
        ReleaseFact(
            run_id=previous.id,
            source_row_no=2,
            order_no="FAKE-HISTORY-1",
            application_date=date(2026, 7, 7),
            last_working_day=date(2026, 7, 30),
            first_visible_date=date(2026, 7, 7),
            row5_classification="include",
            row30_classification="include",
        )
    )
    baseline = PublishedReport(
        run_id=previous.id,
        report_kind="daily",
        period_start=previous.report_date,
        period_end=previous.report_date,
        version=1,
        is_current=True,
        snapshot_json="{}",
        snapshot_hash="a" * 64,
        published_by="qa-operator",
        published_at=datetime(2026, 7, 7, 18, 0),
    )
    db.add(baseline)
    db.flush()
    run = ReportRun(
        report_date=date(2026, 7, 8),
        status=RunStatus.created.value,
        rule_version="rules-v1",
        baseline_report_id=baseline.id,
    )
    db.add(run)
    db.commit()
    service = RunSourceService(db, person_key_secret="test-secret")
    upload = UploadFile(filename="OA_Release.png", file=BytesIO(b"fake-image"))

    def fake_convert(_path, _table_type, _tmp_dir):
        target = tmp_path / "release-history-from-image.xlsx"
        pd.DataFrame(
            [
                {
                    "单号": "FAKE-HISTORY-1",
                    "流程名称": "协议签署",
                    "申请时间": "2026-07-07",
                    "当前状态": "审批完成",
                    "最后工作日": "2026-08-31",
                }
            ]
        ).to_excel(target, index=False)
        return str(target)

    monkeypatch.setattr(
        "app.services.run_source_service.image_parser.convert_to_xlsx", fake_convert
    )

    result = asyncio.run(service.ingest(run.id, SourceType.release, upload))

    fact = fact_repo.list_release_facts(db, run.id)[0]
    decisions = db.query(RunDecision).filter_by(run_id=run.id).all()
    assert result.parse_status == "needs_review"
    assert fact.last_working_day == date(2026, 7, 30)
    assert fact.row30_classification == "include"
    assert {decision.decision_code for decision in decisions} == {
        "ocr_review_required"
    }


def test_release_without_lwd_follows_row5_only_rule_without_blocking(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    release = _xlsx_upload(
        [
            {
                "单号": "FAKE-O-NO-LWD",
                "流程名称": "协议签署",
                "申请时间": "2026-07-08",
                "当前状态": "审批完成",
            }
        ],
        "OA_Release.xlsx",
    )

    result = asyncio.run(service.ingest(run.id, SourceType.release, release))

    fact = fact_repo.list_release_facts(db, run.id)[0]
    assert result.parse_status == "parsed"
    assert fact.row5_classification == "include"
    assert fact.row30_classification == "exclude"
    assert db.query(RunDecision).filter_by(run_id=run.id).count() == 0


def test_ambiguous_structured_release_classification_requires_review(db):
    run = _run(db)
    service = RunSourceService(db, person_key_secret="test-secret")
    release = _xlsx_upload(
        [
            {
                "单号": "FAKE-O2",
                "申请时间": "2026-07-08",
                "当前状态": "等待审批",
                "最后工作日": "2026-07-30",
            }
        ],
        "OA_Release.xlsx",
    )

    result = asyncio.run(service.ingest(run.id, SourceType.release, release))

    assert result.parse_status == "needs_review"
    fact = fact_repo.list_release_facts(db, run.id)[0]
    assert fact.row5_classification == "review"
    assert fact.row30_classification == "include"
    decisions = db.query(RunDecision).filter_by(run_id=run.id).all()
    assert {decision.decision_code for decision in decisions} == {
        "release_row5_classification_required"
    }
