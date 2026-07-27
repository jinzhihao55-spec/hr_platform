"""每日上传门禁：必须按「报告日 + 数据源」判定，不得用全库行数兜底。"""
from datetime import date

import pandas as pd

from app.repositories import input_repo, source_status_repo
from app.services import report_service


def _seed_historical_employees(db) -> None:
    input_repo.upsert_employees(db, pd.DataFrame([{
        "工号": "E1", "中文名": "甲", "员工类型": "正式员工", "员工状态": "在职",
        "入职日期": date(2025, 1, 1), "离职日期": None,
        "事业部": "NINS", "事业部编号": "NINS",
        "项目编号": "P1", "项目名称": "P1",
    }]), date(2026, 7, 9))
    db.commit()


def test_historical_rows_do_not_satisfy_daily_gate(db, monkeypatch):
    """库里有历史人员数据、但 2026-07-10 没有任何上传记录时，
    人员表必须仍被判定为缺失——旧数据不能顶替当日输入。"""
    monkeypatch.setattr(source_status_repo, "load", lambda *_args, **_kwargs: {})
    _seed_historical_employees(db)

    missing = report_service._missing_uploads(date(2026, 7, 10), db)

    assert "人员表" in missing
    assert len(missing) == 4


def test_persisted_upload_record_satisfies_gate_without_redis(db, monkeypatch):
    """Redis 过期后，MySQL 上传记录仍能证明该报告日已上传。"""
    monkeypatch.setattr(source_status_repo, "load", lambda *_args, **_kwargs: {})
    report_date = date(2026, 7, 10)
    source_status_repo.save_db(db, report_date, {
        "employees": {"action": "updated", "rows_upserted": 5},
        "resignations": {"action": "updated", "rows_upserted": 1},
        "agreements": {"action": "updated", "rows_upserted": 2},
        "recruitment": {"action": "updated", "rows_upserted": 3},
    })
    db.commit()

    assert report_service._missing_uploads(report_date, db) == []
    # 相邻日期不受影响：昨天的记录不能顶替今天
    assert len(report_service._missing_uploads(date(2026, 7, 13), db)) == 4


def test_save_db_upsert_roundtrip(db):
    report_date = date(2026, 7, 10)
    source_status_repo.save_db(db, report_date, {
        "employees": {"action": "reused", "rows_upserted": None},
    })
    source_status_repo.save_db(db, report_date, {
        "employees": {"action": "updated", "rows_upserted": 7},
    })
    db.commit()

    stored = source_status_repo.load_db(db, report_date)
    assert stored["employees"]["action"] == "updated"
    assert stored["employees"]["rows_upserted"] == 7


def test_redis_alone_cannot_satisfy_gate(db, monkeypatch):
    """MySQL 是门禁唯一权威：Redis 声称四类已上传、MySQL 无记录时必须全部判缺失。"""
    monkeypatch.setattr(
        source_status_repo, "load",
        lambda *_args, **_kwargs: {
            key: {"action": "updated"}
            for key in ("employees", "resignations", "agreements", "recruitment")
        },
    )

    missing = report_service._missing_uploads(date(2026, 7, 10), db)

    assert len(missing) == 4
