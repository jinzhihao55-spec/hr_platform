"""日期解析与转换辅助（确定性）。"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from dateutil import parser as dtparser


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "nat", "none", "null"} or s in {"-", "—", "－"}:
        return None
    try:
        return dtparser.parse(s).date()
    except (ValueError, OverflowError):
        return None


def parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "nat", "none", "null"} or s in {"-", "—", "－"}:
        return None
    try:
        return dtparser.parse(s)
    except (ValueError, OverflowError):
        return None


def to_int(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def same_month(d: date | None, ref: date) -> bool:
    return d is not None and d.year == ref.year and d.month == ref.month
