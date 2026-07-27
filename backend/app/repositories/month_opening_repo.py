"""月初基线持久化：每月一条，保存 HR 确认的 Sheet1/在岗时长快照。"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reports import MonthOpeningBaseline


def save(
    db: Session,
    *,
    report_month: date,
    baseline_date: date,
    source_type: str,
    baseline_rows: dict[int, int],
    tenure_rows: list[dict],
    template_sha256: str,
    confirmed_by: str,
) -> MonthOpeningBaseline:
    obj = db.scalar(
        select(MonthOpeningBaseline).where(
            MonthOpeningBaseline.report_month == report_month,
        )
    )
    if obj is None:
        obj = MonthOpeningBaseline(report_month=report_month)
        db.add(obj)
    obj.baseline_date = baseline_date
    obj.source_type = source_type
    obj.baseline_rows_json = json.dumps(
        {str(row): int(value) for row, value in baseline_rows.items()},
        ensure_ascii=False,
        sort_keys=True,
    )
    obj.tenure_rows_json = json.dumps(tenure_rows, ensure_ascii=False, sort_keys=True)
    obj.template_sha256 = template_sha256
    obj.confirmed_by = confirmed_by
    db.flush()
    return obj


def get(db: Session, report_month: date) -> MonthOpeningBaseline | None:
    return db.scalar(
        select(MonthOpeningBaseline).where(
            MonthOpeningBaseline.report_month == report_month,
            MonthOpeningBaseline.is_deleted == 0,
        )
    )


def decode(obj: MonthOpeningBaseline) -> tuple[dict[int, int], list[dict]]:
    baseline_rows = {
        int(row): int(value)
        for row, value in json.loads(obj.baseline_rows_json).items()
    }
    tenure_rows = json.loads(obj.tenure_rows_json)
    return baseline_rows, tenure_rows
