"""§5 发布前校验清单。★ = 硬阻断。每项校验返回 通过/失败 + 明细，并写入计算日志。
任一硬阻断失败即停止交付。"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core import constants as C


def _v(row: dict, n: int) -> float:
    info = row.get(n)
    return (info or {}).get("value") or 0


def run_daily_checks(ctx: dict[str, Any]) -> list[dict]:
    rows = ctx["rows"]
    tenure = ctx.get("tenure", {})
    results: list[dict] = []

    def check(name, ok, hard, **detail):
        results.append({"check": name, "passed": bool(ok), "hard_block": hard, **detail})

    # 9 ★ 公式链校验
    check("Row6=Row4+Row5", _v(rows, 6) == _v(rows, 4) + _v(rows, 5), True,
          left=_v(rows, 6), right=_v(rows, 4) + _v(rows, 5))
    check("Row7=Row2-Row3", _v(rows, 7) == _v(rows, 2) - _v(rows, 3), True)
    check("Row12=Row8-Row9-Row10+Row11",
          _v(rows, 12) == _v(rows, 8) - _v(rows, 9) - _v(rows, 10) + _v(rows, 11), True)
    check("Row17=Row13-Row14-Row15+Row16",
          _v(rows, 17) == _v(rows, 13) - _v(rows, 14) - _v(rows, 15) + _v(rows, 16), True)
    check("Row22=Row18-Row19-Row20+Row21",
          _v(rows, 22) == _v(rows, 18) - _v(rows, 19) - _v(rows, 20) + _v(rows, 21), True)
    check("Row33=Row30+Row31+Row32",
          _v(rows, 33) == _v(rows, 30) + _v(rows, 31) + _v(rows, 32), True,
          row33=_v(rows, 33), sum=_v(rows, 30) + _v(rows, 31) + _v(rows, 32))
    check("Row19=Row33", _v(rows, 19) == _v(rows, 33), True,
          row19=_v(rows, 19), row33=_v(rows, 33))
    check("Row40=Row37+Row38+Row39",
          _v(rows, 40) == _v(rows, 37) + _v(rows, 38) + _v(rows, 39), True)
    check("Row37=Row8(MTD入职)", _v(rows, 37) == _v(rows, 8), True,
          row37=_v(rows, 37), row8=_v(rows, 8))
    check("Row18=Row40", _v(rows, 18) == _v(rows, 40), True,
          left=_v(rows, 18), right=_v(rows, 40))

    # 10 ★ 在岗时长校验：Σ(BU YTD) = B10 = Sheet1 Row14
    b10 = tenure.get("b10")
    row14 = _v(rows, 14)
    bu_rows = tenure.get("rows") or []
    bu_sum = sum(int(r.get("ytd_leavers") or 0) for r in bu_rows)

    check(
        "在岗时长 Σ(BU YTD) = B10",
        bu_sum == (b10 or 0),
        True,
        bu_sum=bu_sum,
        b10=b10,
    )
    check(
        "在岗时长 B10 = Sheet1 Row14",
        (b10 or 0) == row14,
        True,
        b10=b10,
        row14=row14,
        bu_diffs=[
            {
                "slot": r.get("slot"),
                "business_unit": r.get("business_unit"),
                "ytd_leavers": r.get("ytd_leavers"),
            }
            for r in bu_rows
        ],
    )

    # 规则 8 / Q7 ★：招聘合计 vs 逐行不一致阻断
    for n in (38, 39):
        trace = next((t for t in ctx.get("trace", []) if t.get("ref") == f"Row{n}"), {})
        check(
            f"招聘取数一致(Row{n})",
            not trace.get("conflict", False),
            True,
            total=trace.get("total_row"),
            rowsum=trace.get("rowsum"),
        )

    # 软校验：在岗时长数据缺陷（hire_date 缺失，或 leave_date < hire_date）。
    # 这些记录已被 tenure.compute_tenure 从平均值分子分母中剔除，不会静默拉低
    # avg_tenure_years，但需要在计算日志里可见，提示人工核对源数据。
    invalid = tenure.get("invalid_records", 0)
    check("在岗时长数据完整性(无缺失/异常 hire_date)", invalid == 0, False,
          invalid_records=invalid)

    return results


def run_weekly_checks(ctx: dict[str, Any]) -> list[dict]:
    results = [{
        "check": "周报窗口末人员快照存在",
        "passed": bool(ctx.get("snapshot_found")),
        "hard_block": True,
        "week_end": ctx.get("week_end"),
    }]
    for r in ctx.get("main_rows", []):
        ok = (r["cnt_formal"] + r["cnt_intern"] + r["cnt_labor"]) == r["headcount"]
        results.append({
            "check": f"{r['business_unit']} 类型拆分=在职总数",
            "passed": ok, "hard_block": True,
            "split_sum": r["cnt_formal"] + r["cnt_intern"] + r["cnt_labor"],
            "headcount": r["headcount"],
        })

    expected_sheet1 = [
        (str(family.get("cost_center") or ""), str(family["name"]))
        for family in C.WEEKLY_PROJECT_FAMILIES
        if family.get("cost_center")
    ]
    actual_sheet1 = [
        (str(row.get("cost_center") or ""), str(row.get("project") or ""))
        for row in ctx.get("cc_rows", [])
    ]
    results.append({
        "check": "Sheet1项目族与配置一致",
        "passed": actual_sheet1 == expected_sheet1,
        "hard_block": True,
        "expected": expected_sheet1,
        "actual": actual_sheet1,
    })

    # 前缀归并冲突会让成本中心归属取决于配置顺序，不能继续交付周报。
    conflicts = ctx.get("project_family_conflicts") or []
    results.append({
        "check": "项目族前缀归并无冲突",
        "passed": not conflicts,
        "hard_block": True,
        "conflicts": conflicts,
    })

    daily = ctx.get("daily_reconciliation") or {}
    if daily.get("complete"):
        weekly_joiners = sum(int(r.get("joiners") or 0) for r in ctx.get("main_rows", []))
        weekly_leavers = sum(int(r.get("leavers") or 0) for r in ctx.get("main_rows", []))
        results.extend([
            {
                "check": "周报本周入职=日报Row2合计",
                "passed": weekly_joiners == int(daily.get("joiners") or 0),
                "hard_block": False,
                "weekly": weekly_joiners,
                "daily_sum": int(daily.get("joiners") or 0),
                "report_dates": daily.get("report_dates", []),
            },
            {
                "check": "周报本周离职=日报Row3合计",
                "passed": weekly_leavers == int(daily.get("leavers") or 0),
                "hard_block": False,
                "weekly": weekly_leavers,
                "daily_sum": int(daily.get("leavers") or 0),
                "report_dates": daily.get("report_dates", []),
            },
        ])
    else:
        results.append({
            "check": "周报与日报入离职交叉校验可执行",
            "passed": False,
            "hard_block": False,
            "reason": "周报窗口内日报不完整，跳过 Row2/Row3 合计对账",
            "report_dates": daily.get("report_dates", []),
            "expected_dates": daily.get("expected_dates", []),
        })
    return results


def hard_failures(results: list[dict]) -> list[dict]:
    return [r for r in results if r.get("hard_block") and not r.get("passed")]


_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_OPAQUE_REF = re.compile(
    r"^(?:source|fact|event|employment|person|validation):"
    r"[A-Za-z0-9_.:-]{1,110}$"
)


def _stable_validation_code(name: str, explicit: Any = None) -> str:
    candidate = str(explicit or "").strip().casefold()
    if _SAFE_CODE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return f"calc_{digest}"


def persisted_validation_record(check: dict[str, Any]) -> dict[str, Any]:
    """Reduce calculator output to a stable, PII-safe validation record."""
    name = str(check.get("check") or check.get("code") or "calculation_check")
    severity = str(
        check.get("severity") or ("BLOCK" if check.get("hard_block") else "INFO")
    ).upper()
    if severity not in {"BLOCK", "REVIEW", "INFO"}:
        severity = "REVIEW"
    passed = bool(check.get("passed", False))
    raw_refs = check.get("evidence_refs") or ()
    refs = [
        str(ref)
        for ref in raw_refs
        if _OPAQUE_REF.fullmatch(str(ref)) is not None
    ]
    return {
        "validation_code": _stable_validation_code(
            name, check.get("validation_code") or check.get("code")
        ),
        "severity": severity,
        "outcome": "PASS" if passed else "FAIL",
        "message": name[:1000],
        "evidence_refs": refs,
    }


def review_item_as_check(item: dict[str, Any]) -> dict[str, Any]:
    severity = str(item.get("severity") or "REVIEW").upper()
    if item.get("code") == "top3_cutoff_tie":
        tie_ref = str(item.get("tie_ref") or "").strip()
        slots = item.get("slots")
        refs = (
            [f"fact:weekly_top3:{tie_ref}:{slots}"]
            if tie_ref and isinstance(slots, int)
            else []
        )
        return {
            "check": "top3_cutoff_tie",
            "validation_code": "top3_cutoff_tie",
            "passed": False,
            "hard_block": False,
            "severity": severity,
            "evidence_refs": refs,
        }
    person_ref = item.get("person_ref")
    refs = [f"person:{person_ref}"] if person_ref else []
    refs.extend(
        f"source:personnel:row:{int(row_no)}"
        for row_no in item.get("employment_source_row_nos") or ()
    )
    selected_source_row = item.get("selected_source_row_no")
    if selected_source_row is not None:
        refs.append(f"employment:selected:{int(selected_source_row)}")
    refs.extend(
        f"validation:dimension:{dimension}"
        for dimension in item.get("conflicting_dimensions") or ()
    )
    return {
        "check": str(item.get("code") or "manual_review_required"),
        "validation_code": str(item.get("code") or "manual_review_required"),
        "passed": False,
        "hard_block": severity == "BLOCK",
        "severity": severity,
        "evidence_refs": refs,
    }
