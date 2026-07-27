"""工作日 / 节假日辅助，用于触发时机判定（§2.2）与周报窗口。

可用时使用 chinese_calendar（离线法定节假日/调休）。按规范，节假日先自查；
仅当无法确定时才询问用户。"""
from __future__ import annotations

from datetime import date, timedelta

try:
    import chinese_calendar as cn_cal

    _HAS_CN = True
except Exception:  # pragma: no cover
    _HAS_CN = False


def is_workday(d: date) -> bool:
    if _HAS_CN:
        try:
            return cn_cal.is_workday(d)
        except NotImplementedError:
            pass  # 日期超出库范围 -> 回退
    return d.weekday() < 5  # 周一至周五


def week_bounds(d: date) -> tuple[date, date]:
    """d 所在自然周的周一..周五。"""
    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def prev_workday(d: date) -> date:
    """d 之前（不含 d）最近的一个工作日（考虑节假日/调休）。"""
    cur = d - timedelta(days=1)
    for _ in range(30):  # 最长假期兜底
        if is_workday(cur):
            return cur
        cur -= timedelta(days=1)
    return d - timedelta(days=1)


def last_workday_of_week(d: date) -> date:
    """d 所在周的最后一个工作日（考虑节假日）。回退为周五。"""
    monday, friday = week_bounds(d)
    cur = friday
    while cur >= monday:
        if is_workday(cur):
            return cur
        cur -= timedelta(days=1)
    return friday


def is_last_workday_of_week(d: date) -> bool:
    return is_workday(d) and d == last_workday_of_week(d)


def calendar_known(d: date) -> bool:
    """d 的节假日信息是否可得（可得则无需询问用户）。"""
    if not _HAS_CN:
        return False
    try:
        cn_cal.is_workday(d)
        return True
    except NotImplementedError:
        return False
