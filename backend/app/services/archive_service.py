"""归档列表：扫描导出目录，按报告日期归类产物文件（日报/周报/计算日志）。
文件名内含日期（导出时约定），据此归类，对应前端「归档」页。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import settings

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _kind(name: str) -> str:
    if name.startswith("员工数增减情况日报") or "日报" in name:
        return "daily"
    if name.startswith("员工数增减周报") or "周报" in name:
        return "weekly"
    if "计算日志" in name:
        return "calc_log"
    return "other"


def find_export_paths(report_date: "date", kinds: list[str]) -> dict[str, str | None]:
    """按报告日期和文件类型查找已导出文件的路径。

    Args:
        report_date: 报告日期，用于匹配文件名中的日期字符串。
        kinds:       要查找的文件类型列表，如 ["daily", "calc_log", "weekly"]。

    Returns:
        {kind: path_or_None}，未找到的类型值为 None。
    """
    from datetime import date as _date
    date_str = report_date.isoformat() if not isinstance(report_date, str) else report_date
    out_dir = Path(settings.output_dir)
    result: dict[str, str | None] = {k: None for k in kinds}
    if not out_dir.exists():
        return result
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        if date_str not in p.name:
            continue
        k = _kind(p.name)
        if k in result and result[k] is None:
            result[k] = str(p)
    return result


def list_archive(kind: str | None = None) -> list[dict[str, Any]]:
    out_dir = Path(settings.output_dir)
    groups: dict[str, list[dict]] = {}
    if out_dir.exists():
        for p in sorted(out_dir.iterdir()):
            if not p.is_file():
                continue
            m = _DATE_RE.search(p.name)
            day = m.group(1) if m else "未分类"
            k = _kind(p.name)
            if kind and kind != "all" and k != kind:
                continue
            groups.setdefault(day, []).append({
                "name": p.name, "kind": k, "path": str(p),
                "size_kb": round(p.stat().st_size / 1024, 1),
            })
    return [{"date": d, "files": groups[d]} for d in sorted(groups, reverse=True)]
