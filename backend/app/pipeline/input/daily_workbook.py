"""从定稿日报 xlsx（员工数增减情况日报）解析 Sheet1 Row2–40。

兼容系统导出格式（表头含基线日/报告日列）与 testdata 标准答案格式。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.core.exceptions import DailyImportError
from app.utils.numbers import round_two
from app.core import constants as C
from app.pipeline.calculation.daily import ITEMS

_ITEM_TO_ROW = {v: k for k, v in ITEMS.items()}

# 同一事项名出现多次时按出现顺序映射到 Row 号
_DUP_ITEM_ROWS: dict[str, list[int]] = {
    "本月预估离职人数": [19, 33],
    "MTD转正": [10, 20],
    "MTD微软项目调整至非微软项目": [11, 21],
}

# save_daily 会写入的 Row；解析到则落库
_PERSIST_ROWS = (2, 3, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 30, 33, 38, 39, 40)

def _find_date_columns(df: pd.DataFrame, report_date: date) -> tuple[int | None, int, dict[date, int]]:
    """从表头行解析日期列：curr=报告日列索引。"""
    date_to_col: dict[date, int] = {}
    for row_idx in range(min(5, len(df))):
        for col_idx in range(1, df.shape[1]):
            val = df.iloc[row_idx, col_idx]
            if pd.isna(val):
                continue
            s = str(val).strip()[:10]
            try:
                date_to_col[date.fromisoformat(s)] = col_idx
            except ValueError:
                continue
    curr_col = date_to_col.get(report_date)
    if curr_col is None:
        if date_to_col:
            curr_col = max(date_to_col.values())
        else:
            curr_col = 2 if df.shape[1] > 2 else max(df.shape[1] - 1, 1)
    prev_dates = [d for d in date_to_col if d < report_date]
    prev_col = date_to_col[max(prev_dates)] if prev_dates else None
    return prev_col, curr_col, date_to_col


def _detect_report_date(df: pd.DataFrame, expected: date | None) -> date | None:
    """从表头推断报告日；若与 expected 一致则优先返回 expected。"""
    _, _, date_to_col = _find_date_columns(df, expected or date.today())
    if not date_to_col:
        return expected
    if expected and expected in date_to_col:
        return expected
    return max(date_to_col.keys())


def parse_daily_workbook(path: Path, report_date: date) -> tuple[dict[int, dict], date]:
    """解析日报 xlsx，返回 (rows, 文件内报告日)。

    rows 格式与 save_daily 入参一致：{row_no: {"value": int, "label": str}}。
    """
    if not path.is_file():
        raise DailyImportError(f"文件不存在：{path}")

    try:
        df = pd.read_excel(path, sheet_name="Sheet1", header=None)
    except Exception as exc:
        raise DailyImportError(f"无法读取 Sheet1：{exc}") from exc

    if df.empty:
        raise DailyImportError("Sheet1 为空")

    file_date = _detect_report_date(df, report_date)
    if file_date is None:
        raise DailyImportError("无法从表头识别报告日期，请确认文件格式")
    if file_date != report_date:
        raise DailyImportError(
            f"文件内报告日 {file_date} 与请求日期 {report_date} 不一致",
            detail={"file_date": file_date.isoformat(), "report_date": report_date.isoformat()},
        )

    _, curr_col, _ = _find_date_columns(df, report_date)
    parsed: dict[int, dict] = {}
    seen_items: dict[str, int] = {}

    for _, row in df.iterrows():
        item = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        if not item or item == "事项":
            continue
        if curr_col >= len(row):
            continue
        val = row.iloc[curr_col]
        if pd.isna(val):
            continue
        try:
            ival = int(val)
        except (TypeError, ValueError):
            continue

        if item in _DUP_ITEM_ROWS:
            idx = seen_items.get(item, 0)
            rows_for_item = _DUP_ITEM_ROWS[item]
            if idx >= len(rows_for_item):
                continue
            n = rows_for_item[idx]
            seen_items[item] = idx + 1
        elif item in _ITEM_TO_ROW:
            n = _ITEM_TO_ROW[item]
        else:
            continue
        parsed[n] = {"value": ival, "label": item}

    missing_rows = [n for n in _PERSIST_ROWS if n not in parsed]
    if missing_rows:
        labels = [ITEMS.get(n, str(n)) for n in missing_rows]
        raise DailyImportError(
            f"缺少或无法读取定稿日报行：{', '.join(labels)}"
            f"（Row{','.join(str(n) for n in missing_rows)}）",
            detail={"missing_rows": missing_rows},
        )

    rows = {n: parsed[n] for n in _PERSIST_ROWS}

    return rows, file_date


def parse_tenure_workbook(path: Path, report_date: date) -> list[dict]:
    """从定稿日报的“在岗时长”sheet 读取 8 个已验收 BU 汇总基线。"""
    if not path.is_file():
        raise DailyImportError(f"文件不存在：{path}")
    try:
        frame = pd.read_excel(path, sheet_name="在岗时长", header=None)
    except Exception as exc:
        raise DailyImportError(f"无法读取在岗时长 sheet：{exc}") from exc
    if frame.shape[0] < 10 or frame.shape[1] < 3:
        raise DailyImportError("在岗时长 sheet 缺少 8 个事业部行或合计行")

    file_date = _detect_report_date(frame, report_date)
    if file_date is not None and file_date != report_date:
        raise DailyImportError(
            f"在岗时长报告日 {file_date} 与请求日期 {report_date} 不一致",
            detail={"file_date": file_date.isoformat(), "report_date": report_date.isoformat()},
        )

    rows: list[dict] = []
    slots = C.get_tenure_bu_slots()
    for index, slot in enumerate(slots, start=1):
        label = str(frame.iloc[index, 0]).strip()
        count = frame.iloc[index, 1]
        average = frame.iloc[index, 2]
        if not label or label == "nan" or pd.isna(count):
            raise DailyImportError(f"在岗时长第 {index + 1} 行缺少事业部或 YTD 离职人数")
        # 槽位按行位置绑定：行标签必须能映射回同一槽位，否则基线会跨 BU 错位。
        if C.resolve_bu_slot(label, label) != slot:
            raise DailyImportError(
                f"在岗时长第 {index + 1} 行事业部「{label}」与槽位 {slot} 不匹配，"
                "8 个事业部须按标准顺序排列",
                detail={"check": "tenure_row_slot_mapping",
                        "row_label": label, "slot": slot},
            )
        rows.append({
            "slot": slot,
            "business_unit": label,
            "ytd_leavers": int(count),
            # 统一 2 位（HALF_UP）：MySQL DECIMAL(8,2) 会静默截断而 SQLite 不会，
            # 不取整会让两种库上的链式基线数值不一致。
            "avg_tenure_years": None if pd.isna(average) else round_two(float(average)),
        })

    total = frame.iloc[9, 1]
    if pd.isna(total) or sum(row["ytd_leavers"] for row in rows) != int(total):
        raise DailyImportError(
            "在岗时长 8 个事业部合计与 B10 不一致",
            detail={"check": "sum_bu_equals_b10"},
        )
    return rows
