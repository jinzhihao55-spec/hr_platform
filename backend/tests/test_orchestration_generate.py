from datetime import date

from app.services import orchestration_service


def _stub_generation(monkeypatch, result):
    monkeypatch.setattr(
        orchestration_service.report_repo,
        "count_inputs",
        lambda _db: {"employees": 1},
    )
    monkeypatch.setattr(
        orchestration_service.report_service,
        "generate_daily_cascade",
        lambda *_args, **_kwargs: result,
    )


def test_generate_message_surfaces_automatic_weekly_block(monkeypatch):
    _stub_generation(monkeypatch, {
        "status": "succeeded",
        "daily_xlsx": "daily.xlsx",
        "weekly_status": "blocked",
        "weekly_hard_failures": [{"check": "周报窗口末人员快照存在"}],
    })

    out = orchestration_service._handle_generate(
        None, date(2026, 7, 10), "session"
    )

    assert "日报已生成" in out["message"]
    assert "自动周报被阻断" in out["message"]
    assert "周报窗口末人员快照存在" in out["message"]


def test_generate_message_surfaces_cascaded_weekly_block(monkeypatch):
    _stub_generation(monkeypatch, {
        "status": "succeeded",
        "daily_xlsx": "daily.xlsx",
        "cascaded": [{
            "report_date": "2026-07-10",
            "status": "succeeded",
            "weekly_status": "blocked",
        }],
    })

    out = orchestration_service._handle_generate(
        None, date(2026, 7, 9), "session"
    )

    assert "2026-07-10" in out["message"]
    assert "级联日报成功，但自动周报被阻断" in out["message"]

