"""定稿日报导入的完整性契约。"""
from datetime import date

import pandas as pd
import pytest

from app.core.exceptions import DailyImportError
from app.pipeline.calculation.daily import ITEMS
from app.pipeline.input.daily_workbook import parse_daily_workbook, parse_tenure_workbook


PERSISTED_ROWS = (
    2, 3, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 30, 33, 38, 39, 40,
)


def _daily_frame(report_date: date, rows: tuple[int, ...]) -> pd.DataFrame:
    data = [["事项", report_date.isoformat()]]
    data.extend([ITEMS[row_no], row_no] for row_no in rows)
    return pd.DataFrame(data)


def _patch_workbook(monkeypatch, frame: pd.DataFrame) -> None:
    monkeypatch.setattr(
        "app.pipeline.input.daily_workbook.pd.read_excel",
        lambda *_args, **_kwargs: frame,
    )


def test_partial_chain_only_workbook_is_rejected(monkeypatch, tmp_path):
    report_date = date(2026, 7, 7)
    workbook = tmp_path / "partial.xlsx"
    workbook.touch()
    _patch_workbook(monkeypatch, _daily_frame(report_date, (8, 9, 13, 14, 30)))

    with pytest.raises(DailyImportError) as exc_info:
        parse_daily_workbook(workbook, report_date)

    assert exc_info.value.detail == {
        "missing_rows": [row_no for row_no in PERSISTED_ROWS if row_no not in (8, 9, 13, 14, 30)]
    }


def test_complete_persisted_rows_workbook_is_accepted(monkeypatch, tmp_path):
    report_date = date(2026, 7, 7)
    workbook = tmp_path / "complete.xlsx"
    workbook.touch()
    _patch_workbook(monkeypatch, _daily_frame(report_date, PERSISTED_ROWS))

    rows, parsed_date = parse_daily_workbook(workbook, report_date)

    assert parsed_date == report_date
    assert set(rows) == set(PERSISTED_ROWS)


def test_tenure_sheet_with_reordered_bu_rows_is_rejected(monkeypatch, tmp_path):
    """行序错乱时按位置绑定槽位会跨 BU 污染链式基线，必须拒绝导入。"""
    report_date = date(2026, 7, 7)
    workbook = tmp_path / "daily.xlsx"
    workbook.touch()
    frame = pd.DataFrame([
        ["事业部", "YTD离职人数", "平均在职（年）", report_date.isoformat()],
        ["NINS", 1, 1.5, None],
        ["NBJO", 2, 2.0, None],
        ["NGOV", 0, None, None],
        ["NENT", 0, None, None],
        ["NITL", 0, None, None],
        ["NMSI", 0, None, None],
        ["NWMT", 0, None, None],
        ["NWTS", 0, None, None],
        ["合计", 3, None, None],
    ])
    _patch_workbook(monkeypatch, frame)

    with pytest.raises(DailyImportError) as exc_info:
        parse_tenure_workbook(workbook, report_date)

    assert exc_info.value.detail.get("check") == "tenure_row_slot_mapping"


def test_tenure_sheet_is_imported_as_eight_slot_snapshot(monkeypatch, tmp_path):
    report_date = date(2026, 7, 7)
    workbook = tmp_path / "daily.xlsx"
    workbook.touch()
    frame = pd.DataFrame([
        ["事业部", "YTD离职人数", "平均在职（年）", report_date.isoformat()],
        ["NBJO", 1, 1.5, None],
        ["NENT", 2, 2.0, None],
        ["NGOV", 0, None, None],
        ["NINS", 0, None, None],
        ["NITL", 0, None, None],
        ["NMSI", 0, None, None],
        ["NWMT", 0, None, None],
        ["NWTS", 0, None, None],
        ["合计", 3, None, None],
    ])
    _patch_workbook(monkeypatch, frame)

    rows = parse_tenure_workbook(workbook, report_date)

    assert len(rows) == 8
    assert rows[0] == {
        "slot": "BU_A",
        "business_unit": "NBJO",
        "ytd_leavers": 1,
        "avg_tenure_years": 1.5,
    }
    assert sum(row["ytd_leavers"] for row in rows) == 3


def test_tenure_average_is_quantized_to_two_decimals_at_import(monkeypatch, tmp_path):
    """MySQL DECIMAL(8,2) 会静默截断，SQLite 不会；导入时统一取 2 位，
    保证两种库上的链式基线数值一致。"""
    report_date = date(2026, 7, 7)
    workbook = tmp_path / "daily.xlsx"
    workbook.touch()
    frame = pd.DataFrame([
        ["事业部", "YTD离职人数", "平均在职（年）", report_date.isoformat()],
        ["NBJO", 1, 1.8512, None],
        ["NENT", 0, None, None],
        ["NGOV", 0, None, None],
        ["NINS", 0, 2.005, None],
        ["NITL", 0, None, None],
        ["NMSI", 0, None, None],
        ["NWMT", 0, None, None],
        ["NWTS", 0, None, None],
        ["合计", 1, None, None],
    ])
    _patch_workbook(monkeypatch, frame)

    rows = parse_tenure_workbook(workbook, report_date)

    assert rows[0]["avg_tenure_years"] == 1.85
    assert rows[3]["avg_tenure_years"] == 2.01
