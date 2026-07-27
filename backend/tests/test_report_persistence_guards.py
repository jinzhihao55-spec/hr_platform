"""硬阻断校验失败时，报表不得入库或导出。"""
from datetime import date

from sqlalchemy import select

from app.models.reports import DailyReport, WeeklyReport
from app.services import report_service


HARD_FAILURE = {
    "check": "synthetic hard failure",
    "passed": False,
    "hard_block": True,
}


def _disable_job_storage(monkeypatch) -> None:
    monkeypatch.setattr(report_service.job_repo, "create", lambda *_args, **_kwargs: "job-1")
    monkeypatch.setattr(report_service.job_repo, "update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        report_service.clarify_repo,
        "add",
        lambda *_args, **_kwargs: "clarification-1",
    )
    monkeypatch.setattr(
        report_service.month_opening_service,
        "prepare_generation",
        lambda *_args, **_kwargs: {
            "baseline_date": None,
            "baseline_override": None,
            "tenure_baseline": None,
            "export_baseline_rows": {},
            "template_path": "template.xlsx",
        },
    )


def test_daily_hard_failure_is_not_persisted(db, monkeypatch):
    report_date = date(2026, 7, 8)
    _disable_job_storage(monkeypatch)
    monkeypatch.setattr(report_service, "_missing_uploads", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        report_service.report_repo,
        "count_inputs",
        lambda *_args, **_kwargs: {"employees": 1},
    )
    monkeypatch.setattr(
        report_service._agent,
        "run_daily",
        lambda *_args, **_kwargs: {
            "rows": {2: {"value": 1, "label": "今日入职"}},
            "tenure": {},
            "validations": [HARD_FAILURE],
        },
    )

    result = report_service.generate_daily(db, report_date)

    assert result["status"] == "blocked"
    assert db.scalar(select(DailyReport).where(DailyReport.report_date == report_date)) is None


def test_missing_month_opening_is_not_persisted(db, monkeypatch):
    """跨月缺 HR 月初确认时，在计算和日报落库前 fail-closed。"""
    report_date = date(2026, 8, 3)
    _disable_job_storage(monkeypatch)
    monkeypatch.setattr(report_service, "_missing_uploads", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        report_service.report_repo,
        "count_inputs",
        lambda *_args, **_kwargs: {"employees": 1},
    )
    from app.core.exceptions import MonthOpeningBaselineMissingError

    monkeypatch.setattr(
        report_service.month_opening_service,
        "prepare_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MonthOpeningBaselineMissingError("HR 尚未确认")
        ),
    )
    called = []
    monkeypatch.setattr(
        report_service._agent,
        "run_daily",
        lambda *_args, **_kwargs: called.append(True),
    )

    result = report_service.generate_daily(db, report_date)

    assert result["status"] == "needs_clarification"
    assert result["error"]["code"] == "month_opening_baseline_missing"
    assert called == []
    assert db.scalar(select(DailyReport).where(DailyReport.report_date == report_date)) is None


def test_weekly_hard_failure_is_not_persisted_or_exported(db, monkeypatch):
    week_start = date(2026, 7, 6)
    week_end = date(2026, 7, 10)
    exported: list[str] = []
    monkeypatch.setattr(
        report_service._agent,
        "run_weekly",
        lambda *_args, **_kwargs: {
            "main_rows": [{
                "business_unit": "BU_A",
                "headcount": 2,
                "cnt_formal": 1,
                "cnt_intern": 0,
                "cnt_labor": 0,
                "joiners": 0,
                "leavers": 0,
            }],
            "validations": [HARD_FAILURE],
        },
    )
    monkeypatch.setattr(
        report_service.weekly_exporter,
        "export_weekly",
        lambda *_args, **_kwargs: exported.append("xlsx") or "weekly.xlsx",
    )
    monkeypatch.setattr(
        report_service.calc_log_exporter,
        "merge_weekly_into_calc_log",
        lambda *_args, **_kwargs: exported.append("log") or "calc-log.md",
    )

    result = report_service.generate_weekly(db, week_start, week_end)

    assert result["status"] == "blocked"
    assert db.scalar(select(WeeklyReport).where(WeeklyReport.week_start == week_start)) is None
    assert exported == []


def test_daily_job_succeeds_when_automatic_weekly_report_fails(db, monkeypatch):
    report_date = date(2026, 7, 10)
    _disable_job_storage(monkeypatch)
    monkeypatch.setattr(report_service, "_missing_uploads", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        report_service.report_repo,
        "count_inputs",
        lambda *_args, **_kwargs: {"employees": 1},
    )
    monkeypatch.setattr(
        report_service._agent,
        "run_daily",
        lambda *_args, **_kwargs: {
            "rows": {2: {"value": 0, "label": "今日入职"}},
            "tenure": {},
            "validations": [],
        },
    )
    monkeypatch.setattr(report_service.cal, "is_last_workday_of_week", lambda *_args: True)
    monkeypatch.setattr(
        report_service.daily_exporter,
        "export_daily",
        lambda *_args, **_kwargs: "daily.xlsx",
    )
    monkeypatch.setattr(
        report_service,
        "_run_weekly",
        lambda *_args, **_kwargs: (
            None,
            None,
            {"validations": [HARD_FAILURE], "hard_failures": [HARD_FAILURE]},
        ),
    )
    calc_logs: list[str] = []
    monkeypatch.setattr(
        report_service.calc_log_exporter,
        "export_calc_log",
        lambda *_args, **_kwargs: calc_logs.append("log") or "calc-log.md",
    )

    result = report_service.generate_daily(db, report_date)

    assert result["status"] == "succeeded"
    assert result["daily_xlsx"] == "daily.xlsx"
    assert result["weekly_status"] == "blocked"
    assert result["weekly_hard_failures"] == [HARD_FAILURE]
    assert result["calc_log_md"] == "calc-log.md"
    assert calc_logs == ["log"]


def test_cascade_entries_surface_weekly_status(db, monkeypatch):
    """导入定稿触发的级联重算里，周五周报被硬阻断必须对调用方可见。"""
    monkeypatch.setattr(
        report_service.report_repo,
        "list_daily_dates",
        lambda *_args, **_kwargs: [{"report_date": "2026-07-10"}],
    )
    monkeypatch.setattr(
        report_service,
        "generate_daily",
        lambda *_args, **_kwargs: {"status": "succeeded", "weekly_status": "blocked"},
    )

    cascaded = report_service.cascade_later(db, date(2026, 7, 9))

    assert cascaded == [{
        "report_date": "2026-07-10",
        "status": "succeeded",
        "weekly_status": "blocked",
    }]
