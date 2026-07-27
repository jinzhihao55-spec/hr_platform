"""在岗时长 sheet（§3.9）：BU_A..BU_H + 合计。
YTD离职人数按 BU；平均在职(年)=Σ(离职-入职)/离职人数。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core import constants as C
from app.repositories import report_repo
from app.pipeline.calculation.daily import (
    _departure_fact_confirmed,
    _resignations_by_emp,
    _selected_employment_rows,
)
from app.utils.numbers import round_two


def _stats_for_employees(
    sub: pd.DataFrame,
    res_by_emp: dict[str, list[dict]],
    report_date: date,
    year: int,
    included_types: set[str],
) -> tuple[int, int, int, int]:
    """返回 leavers, counted, days_sum, invalid。"""
    leavers = counted = days_sum = invalid = 0
    if sub.empty:
        return leavers, counted, days_sum, invalid
    for _, r in sub.iterrows():
        if str(r.get("employee_type") or "").strip() not in included_types:
            continue
        ld = r.get("leave_date")
        hd = r.get("hire_date")
        if isinstance(ld, date) and ld.year == year and ld <= report_date:
            ok, _ = _departure_fact_confirmed(r, res_by_emp, ld)
            if not ok:
                continue
            leavers += 1
            if isinstance(hd, date) and hd <= ld:
                counted += 1
                days_sum += (ld - hd).days
            else:
                invalid += 1
    return leavers, counted, days_sum, invalid


def _compute_from_snapshot(
    emp: pd.DataFrame,
    res_by_emp: dict[str, list[dict]],
    report_date: date,
    snapshot_date: date,
    snapshot_rows: list[dict],
    included_types: set[str],
    slots: list[str],
    labels: dict[str, str],
) -> dict[str, Any]:
    """沿用已验收的 BU 人数/平均值，只叠加快照后的实际离职。"""
    baseline = {str(row["slot"]): row for row in snapshot_rows}
    increments = {
        slot: {"count": 0, "days": 0, "invalid": 0, "label": None}
        for slot in slots
    }
    unmapped: list[dict[str, Any]] = []

    if not emp.empty:
        for _, row in emp.iterrows():
            if str(row.get("employee_type") or "").strip() not in included_types:
                continue
            leave_date = row.get("leave_date")
            if not isinstance(leave_date, date):
                continue
            first_visible = row.get("leave_first_visible")
            effective_date = (
                first_visible
                if isinstance(first_visible, date) and first_visible > leave_date
                else leave_date
            )
            if effective_date <= snapshot_date or effective_date > report_date:
                continue
            confirmed, _ = _departure_fact_confirmed(row, res_by_emp, leave_date)
            if not confirmed:
                continue
            slot = C.resolve_bu_slot(
                row.get("business_unit"), row.get("business_unit_no")
            )
            if slot not in increments:
                unmapped.append({
                    "emp_no": row.get("emp_no"),
                    "business_unit": row.get("business_unit"),
                    "business_unit_no": row.get("business_unit_no"),
                })
                continue
            increment = increments[slot]
            increment["count"] += 1
            increment["label"] = row.get("business_unit_no") or row.get("business_unit")
            hire_date = row.get("hire_date")
            if isinstance(hire_date, date) and hire_date <= leave_date:
                increment["days"] += (leave_date - hire_date).days
            else:
                increment["invalid"] += 1

    rows: list[dict[str, Any]] = []
    total_leavers = total_invalid = 0
    for slot in slots:
        base = baseline.get(slot) or {}
        base_count = int(base.get("ytd_leavers") or 0)
        base_avg = base.get("avg_tenure_years")
        increment = increments[slot]
        counted = base_count if base_avg is not None else 0
        days = (
            Decimal(str(base_avg or 0)) * Decimal(base_count) * Decimal(365)
            + Decimal(increment["days"])
        )
        counted += increment["count"] - increment["invalid"]
        leavers = base_count + increment["count"]
        invalid = (base_count if base_count and base_avg is None else 0) + increment["invalid"]
        average = (
            float(
                (days / Decimal(counted) / Decimal(365)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
            )
            if counted else None
        )
        rows.append({
            "slot": slot,
            "business_unit": str(
                base.get("business_unit") or increment["label"] or labels.get(slot, slot)
            ),
            "ytd_leavers": leavers,
            "avg_tenure_years": average,
            "_days": float(days),
            "invalid_records": invalid,
        })
        total_leavers += leavers
        total_invalid += invalid

    return {
        "rows": rows,
        "total": {
            "business_unit": "合计",
            "ytd_leavers": total_leavers,
            "avg_tenure_years": None,
            "invalid_records": total_invalid,
        },
        "b10": total_leavers,
        "invalid_records": total_invalid,
        "unmapped_bu": unmapped,
    }


def compute_tenure(
    db: Session | None,
    report_date: date,
    opening_baseline_date: date | None = None,
    opening_rows: list[dict] | None = None,
    *,
    input_frames: Mapping[str, pd.DataFrame] | None = None,
    snapshot_override: tuple[date | None, Sequence[dict]] | None = None,
) -> dict[str, Any]:
    if input_frames is None:
        if db is None:
            raise ValueError("db is required when input_frames are not provided")
        emp = report_repo.load_employees(db)
        res = report_repo.load_resignations(db)
        snapshot_date, snapshot_rows = report_repo.load_tenure_snapshot(db, report_date)
    else:
        emp = input_frames["employees"].copy(deep=True)
        res = input_frames["resignations"].copy(deep=True)
        snapshot_date, provided_rows = snapshot_override or (None, ())
        snapshot_rows = [dict(row) for row in provided_rows]
    emp = _selected_employment_rows(emp)
    res_by_emp = _resignations_by_emp(res)
    year = report_date.year
    included_types = C.get_included_types()
    labels = C.get_tenure_bu_labels()
    slots = C.get_tenure_bu_slots()

    if opening_baseline_date is not None and opening_rows and (
        snapshot_date is None or opening_baseline_date >= snapshot_date
    ):
        snapshot_date = opening_baseline_date
        snapshot_rows = opening_rows
    if snapshot_date is not None and snapshot_rows:
        return _compute_from_snapshot(
            emp, res_by_emp, report_date, snapshot_date, snapshot_rows,
            included_types, slots, labels,
        )

    unmapped: list[dict[str, Any]] = []
    if not emp.empty:
        emp = emp.copy()
        emp["bu_slot"] = emp.apply(
            lambda r: C.resolve_bu_slot(r.get("business_unit"), r.get("business_unit_no")),
            axis=1,
        )
        for _, r in emp.iterrows():
            if str(r.get("employee_type") or "").strip() not in included_types:
                continue
            if r.get("bu_slot") is None:
                unmapped.append({
                    "emp_no": r.get("emp_no"),
                    "business_unit": r.get("business_unit"),
                    "business_unit_no": r.get("business_unit_no"),
                })
    else:
        emp = pd.DataFrame()

    rows: list[dict[str, Any]] = []
    total_leavers = total_days = total_counted = total_invalid = 0

    for slot in slots:
        sub = emp[emp["bu_slot"] == slot] if not emp.empty else emp
        leavers, counted, days_sum, invalid = _stats_for_employees(
            sub, res_by_emp, report_date, year, included_types,
        )
        if not sub.empty:
            bu_label = str(sub.iloc[0].get("business_unit") or labels.get(slot, slot)).strip()
        else:
            bu_label = labels.get(slot, slot)
        avg_years = round_two(days_sum / counted / 365) if counted else None
        rows.append({
            "slot": slot,
            "business_unit": bu_label,
            "ytd_leavers": leavers,
            "avg_tenure_years": avg_years,
            "_days": days_sum,
            "invalid_records": invalid,
        })
        total_leavers += leavers
        total_days += days_sum
        total_counted += counted
        total_invalid += invalid

    total_avg = round_two(total_days / total_counted / 365) if total_counted else None
    total_row = {
        "business_unit": "合计",
        "ytd_leavers": total_leavers,
        "avg_tenure_years": total_avg,
        "invalid_records": total_invalid,
    }

    return {
        "rows": rows,
        "total": total_row,
        "b10": total_leavers,
        "invalid_records": total_invalid,
        "unmapped_bu": unmapped,
    }


def compute_tenure_from_frames(
    *,
    report_date: date,
    employees: pd.DataFrame,
    resignations: pd.DataFrame,
    snapshot_date: date | None = None,
    snapshot_rows: Sequence[dict] = (),
) -> dict[str, Any]:
    return compute_tenure(
        None,
        report_date,
        input_frames={"employees": employees, "resignations": resignations},
        snapshot_override=(snapshot_date, snapshot_rows),
    )
