"""Typed contracts for calendar, Run review, preview, and publication APIs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ReportKind = Literal["daily", "weekly"]


class RunCreateRequest(BaseModel):
    report_date: date
    baseline_report_id: str | None = None
    create_new: bool = False


class RunSummary(BaseModel):
    id: str
    report_date: date
    status: str
    rule_version: str
    baseline_report_id: str | None = None
    canonical_run_id: str | None = None


class RunCreateResponse(BaseModel):
    reused: bool
    run: RunSummary


class RunSourceView(BaseModel):
    source_type: str
    original_filename: str | None = None
    sha256: str
    schema_version: str
    parser_version: str
    media_type: str | None = None
    row_count: int
    parse_status: str
    original_extension: str | None = None


class DecisionView(BaseModel):
    id: str
    report_kind: str | None = None
    decision_code: str
    fact_ref: str
    question: str
    options: list[Any] = Field(default_factory=list)
    answer: Any = None
    status: str
    decided_at: datetime | None = None
    operator_ref: str | None = None


class DecisionPreviewColumn(BaseModel):
    key: str
    label: str


class DecisionPreviewResponse(BaseModel):
    kind: Literal["ocr_source"]
    source_type: Literal["release", "recruitment"]
    columns: list[DecisionPreviewColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WeeklyReviewEmployment(BaseModel):
    source_row_no: int
    employee_no: str
    display_name: str | None = None
    entry_date: date | None = None
    business_unit_no: str | None = None
    business_unit: str | None = None
    project_code: str | None = None
    project_name: str | None = None
    employee_type: str
    status: str | None = None
    selected: bool


class WeeklyReviewItem(BaseModel):
    kind: Literal["multiple_active_employments"] = "multiple_active_employments"
    person_ref: str
    severity: Literal["REVIEW", "BLOCK"]
    resolution: Literal["confirm_dedupe", "replace_input"]
    decision_id: str | None = None
    decision_status: str | None = None
    conflicting_dimensions: list[str] = Field(default_factory=list)
    selected_source_row_no: int
    employments: list[WeeklyReviewEmployment] = Field(default_factory=list)


class WeeklyTop3ReviewItem(BaseModel):
    kind: Literal["top3_cutoff_tie"] = "top3_cutoff_tie"
    tie_ref: str
    severity: Literal["REVIEW"]
    resolution: Literal["select_top3_projects"]
    decision_id: str
    decision_status: str
    question: str
    candidates: list[str] = Field(default_factory=list)
    slots: int
    selected_projects: list[str] = Field(default_factory=list)


class WeeklyReviewResponse(BaseModel):
    items: list[WeeklyReviewItem | WeeklyTop3ReviewItem] = Field(
        default_factory=list
    )


class ValidationView(BaseModel):
    report_kind: str
    validation_code: str
    severity: str
    outcome: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class TargetView(BaseModel):
    report_kind: str
    status: str
    preview_hash: str | None = None
    validation_summary: dict[str, Any] | None = None
    published_report_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class RunDetail(RunSummary):
    attempt_no: int
    source_bundle_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    baseline_status: Literal["current", "stale", "missing"] = "missing"
    baseline_period_end: date | None = None
    baseline_version: int | None = None
    latest_baseline_report_id: str | None = None
    latest_baseline_period_end: date | None = None
    latest_baseline_version: int | None = None
    sources: list[RunSourceView] = Field(default_factory=list)
    decisions: list[DecisionView] = Field(default_factory=list)
    validations: list[ValidationView] = Field(default_factory=list)
    targets: list[TargetView] = Field(default_factory=list)


class DecisionAnswerRequest(BaseModel):
    answer: Any
    operator_ref: str = "local-operator"


class PublishRequest(BaseModel):
    report_kinds: list[ReportKind]
    operator_ref: str = "local-operator"


class PreviewResponse(BaseModel):
    run_id: str
    report_kind: str
    period_start: date
    period_end: date
    rule_version: str
    snapshot_hash: str
    publishable: bool
    rows: dict[str, dict[str, Any]] = Field(default_factory=dict)
    main_rows: list[dict[str, Any]] = Field(default_factory=list)
    cc_rows: list[dict[str, Any]] = Field(default_factory=list)
    tenure: dict[str, Any] = Field(default_factory=dict)
    validation_summary: dict[str, Any]


class CalendarDay(BaseModel):
    date: date
    is_workday: bool
    run_id: str | None = None
    run_status: str | None = None
    daily_status: str | None = None
    weekly_status: str | None = None


class CalendarResponse(BaseModel):
    month: str
    days: list[CalendarDay]
