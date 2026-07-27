"""Published report views must remain tied to their immutable snapshots."""

from datetime import date, datetime

from app.models.facts import RunValidation, encode_json_text
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunStatus
from app.services import view_service


def _published_report(db, *, kind: str, start: date, end: date, snapshot: dict):
    run = ReportRun(
        report_date=end,
        status=RunStatus.ready.value,
        rule_version="rules-v1",
    )
    db.add(run)
    db.flush()
    report = PublishedReport(
        run_id=run.id,
        report_kind=kind,
        period_start=start,
        period_end=end,
        version=1,
        is_current=True,
        snapshot_json=encode_json_text(snapshot),
        snapshot_hash="a" * 64,
        published_by="qa-operator",
        published_at=datetime(2026, 7, 23, 9, 0, 0),
    )
    db.add(report)
    db.flush()
    return run, report


def test_daily_view_uses_published_values_and_run_validations(db, monkeypatch):
    report_date = date(2026, 7, 23)
    run, _report = _published_report(
        db,
        kind="daily",
        start=report_date,
        end=report_date,
        snapshot={
            "rows": {
                "2": {"label": "今日入职", "value": 0, "is_blank": False},
                "4": {
                    "label": "今日提出离职数（主动）",
                    "value": 7,
                    "is_blank": False,
                },
            },
            "tenure": {"b10": 137, "rows": []},
        },
    )
    db.add(
        RunValidation(
            run_id=run.id,
            report_kind="daily",
            validation_code="row6_formula",
            severity="BLOCK",
            outcome="PASS",
            message="Row6=Row4+Row5",
            evidence_refs="[]",
        )
    )
    db.commit()

    monkeypatch.setattr(
        view_service._agent,
        "run_daily",
        lambda *_args, **_kwargs: {
            "rows": {4: {"item": "旧值", "value": 999}},
            "trace": [
                {
                    "ref": "Row4",
                    "source": "离职人员报表",
                    "formula": "COUNT(今日首次可见且主动)",
                }
            ],
            "tenure": {"b10": 999},
            "validations": [],
        },
    )

    result = view_service.daily_view(db, report_date)
    rows = {row["row"]: row for row in result["rows"]}

    assert rows[4]["value"] == 7
    assert rows[4]["source"] == "离职人员报表"
    assert rows[4]["formula"] == "COUNT(今日首次可见且主动)"
    assert result["tenure"] == {"b10": 137, "rows": []}
    assert result["validations"] == [
        {
            "check": "Row6=Row4+Row5",
            "validation_code": "row6_formula",
            "passed": True,
            "resolved_by_review": False,
            "hard_block": True,
            "severity": "BLOCK",
        }
    ]


def test_weekly_view_uses_published_snapshot_without_recalculation(db, monkeypatch):
    week_start = date(2026, 7, 13)
    week_end = date(2026, 7, 17)
    run, _report = _published_report(
        db,
        kind="weekly",
        start=week_start,
        end=week_end,
        snapshot={
            "main_rows": [
                {
                    "business_unit": "FAKE-BU",
                    "headcount": 25,
                    "cnt_formal": 20,
                    "cnt_intern": 5,
                    "cnt_labor": 0,
                    "joiners": 2,
                    "leavers": 1,
                    "top3_projects": [{"name": "FAKE-PROJECT", "count": 10}],
                }
            ],
            "cc_rows": [
                {
                    "cost_center": "9000",
                    "project": "FAKE-PROJECT",
                    "headcount": 10,
                    "joiners": 1,
                    "leavers": 0,
                }
            ],
        },
    )
    db.add(
        RunValidation(
            run_id=run.id,
            report_kind="weekly",
            validation_code="weekly_split",
            severity="BLOCK",
            outcome="PASS",
            message="类型拆分=在职总数",
            evidence_refs="[]",
        )
    )
    db.commit()

    monkeypatch.setattr(
        view_service._agent,
        "run_weekly",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("published weekly view must not recalculate")
        ),
    )

    result = view_service.weekly_view(db, week_start, week_end)

    assert result["sheet2"]["rows"][0]["headcount"] == 25
    assert result["sheet1"]["rows"][0]["headcount"] == 10
    assert result["traces"][0]["ref"] == "FAKE-BU"
    assert result["validations"][0]["check"] == "类型拆分=在职总数"


def test_published_review_validation_is_presented_as_resolved(db):
    week_start = date(2026, 7, 13)
    week_end = date(2026, 7, 17)
    run, _report = _published_report(
        db,
        kind="weekly",
        start=week_start,
        end=week_end,
        snapshot={"main_rows": [], "cc_rows": []},
    )
    db.add(
        RunValidation(
            run_id=run.id,
            report_kind="weekly",
            validation_code="top3_cutoff_tie:fake",
            severity="REVIEW",
            outcome="FAIL",
            message="top3_cutoff_tie",
            evidence_refs="[]",
        )
    )
    db.commit()

    result = view_service.weekly_view(db, week_start, week_end)

    assert result["validations"] == [
        {
            "check": "前三项目截止位并列",
            "validation_code": "top3_cutoff_tie:fake",
            "passed": True,
            "resolved_by_review": True,
            "hard_block": False,
            "severity": "REVIEW",
        }
    ]
