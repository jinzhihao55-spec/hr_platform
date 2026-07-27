"""计算 Agent：从数据库主表读数 -> 确定性引擎 -> 把日报/周报写回数据库宽表。
Agent 只负责编排（及可选的 LLM 场景②错误诊断），不计算任何数字。"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.domain.fact_bundle import FactBundle
from app.pipeline.calculation import daily as daily_calc
from app.pipeline.calculation import tenure as tenure_calc
from app.pipeline.calculation import validators
from app.pipeline.calculation import weekly as weekly_calc


class CalculationAgent(BaseAgent):
    name = "calculation"

    def run(self, db: Session, report_date: date, **kwargs: Any) -> dict[str, Any]:
        """BaseAgent 入口；默认跑日报。"""
        return self.run_daily(db, report_date)

    def run_daily(
        self,
        db: Session,
        report_date: date,
        baseline_date: date | None = None,
        baseline_override: dict[int, int] | None = None,
        tenure_baseline: dict | None = None,
    ) -> dict[str, Any]:
        ctx = daily_calc.compute_daily(
            db, report_date, baseline_date, baseline_override=baseline_override,
        )
        tenure_baseline = tenure_baseline or {}
        ctx["tenure"] = tenure_calc.compute_tenure(
            db,
            report_date,
            opening_baseline_date=tenure_baseline.get("baseline_date"),
            opening_rows=tenure_baseline.get("rows"),
        )
        ctx["validations"] = validators.run_daily_checks(ctx)
        # 硬阻断时可选用 LLM 场景②做排障解释（不改任何数字，且仅限本 Agent 白名单）
        hard = validators.hard_failures(ctx["validations"])
        if hard:
            ctx["diagnosis"] = self.run_scenario(
                "diagnose_error", {"report_date": str(report_date), "hard_failures": hard}
            )
        return ctx

    def run_weekly(self, db: Session, week_start: date, week_end: date) -> dict[str, Any]:
        ctx = weekly_calc.compute_weekly(db, week_start, week_end)
        ctx["validations"] = validators.run_weekly_checks(ctx)
        return ctx

    def run_daily_bundle(self, bundle: FactBundle) -> dict[str, Any]:
        ctx = daily_calc.compute_daily_from_frames(
            report_date=bundle.report_date,
            baseline_date=bundle.baseline_date,
            baseline_rows=bundle.baseline_rows,
            employees=bundle.employments,
            resignations=bundle.resignations,
            releases=bundle.releases,
            recruitment=bundle.recruitment,
        )
        ctx["tenure"] = tenure_calc.compute_tenure_from_frames(
            report_date=bundle.report_date,
            employees=bundle.employments,
            resignations=bundle.resignations,
            snapshot_date=bundle.tenure_snapshot_date,
            snapshot_rows=bundle.tenure_rows,
        )
        ctx["validations"] = validators.run_daily_checks(ctx)
        return ctx

    def run_weekly_bundle(
        self, bundle: FactBundle, week_start: date, week_end: date
    ) -> dict[str, Any]:
        top3_selections: dict[str, list[str]] = {}
        for decision in bundle.decisions:
            if (
                decision.get("decision_code") != "top3_cutoff_tie"
                or decision.get("status") != "answered"
                or not isinstance(decision.get("answer"), list)
            ):
                continue
            parts = str(decision.get("fact_ref") or "").split(":")
            if len(parts) == 4 and parts[:2] == ["weekly", "top3_cutoff_tie"]:
                top3_selections[f"{parts[2]}:{parts[3]}"] = [
                    str(value) for value in decision["answer"]
                ]
        ctx = weekly_calc.compute_weekly_from_frames(
            employees=bundle.employments,
            resignations=bundle.resignations,
            week_start=week_start,
            week_end=week_end,
            daily_reconciliation=bundle.daily_reconciliation,
            top3_selections=top3_selections,
        )
        ctx["validations"] = validators.run_weekly_checks(ctx)
        return ctx
