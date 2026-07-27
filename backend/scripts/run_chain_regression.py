"""用本地日报目录重放链式日报，并输出不含人员数据的比较摘要。"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  注册 ORM 表
from app.agents.extraction_agent import ExtractionAgent
from app.core import constants as C
from app.core.database import Base
from app.pipeline.calculation import daily as daily_calc
from app.pipeline.calculation import tenure as tenure_calc
from app.pipeline.calculation import validators
from app.pipeline.export import daily_exporter
from app.pipeline.input.daily_workbook import (
    _find_date_columns,
    parse_daily_workbook,
    parse_tenure_workbook,
)
from app.repositories import report_repo


BUSINESS_ROWS = tuple(sorted(set(daily_calc.ITEMS) - C.DAILY_HEADER_ROWS))
SOURCE_SPECS = {
    "employees": ("人员表", {".xls", ".xlsx"}),
    "resignations": ("离职人员报表", {".xls", ".xlsx"}),
    "agreements": ("协议签署", {".xls", ".xlsx", ".png", ".jpg", ".jpeg"}),
    "recruitment": ("招聘数据", {".xls", ".xlsx", ".png", ".jpg", ".jpeg"}),
}


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期必须为 YYYY-MM-DD：{raw}") from exc


def _find_one(directory: Path, stem: str, suffixes: set[str], compact_date: str) -> Path:
    matches = sorted(
        path for path in directory.iterdir()
        if path.is_file()
        and path.name.startswith(stem)
        and compact_date in path.name
        and path.suffix.lower() in suffixes
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"{directory.name} 中 {stem} 应有且仅有一个输入文件，实际找到 {len(matches)} 个"
        )
    return matches[0]


def _structured_override(structured_dir: Path | None, report_date: date, stem: str) -> Path | None:
    if structured_dir is None:
        return None
    compact = report_date.strftime("%Y%m%d")
    candidates = (
        structured_dir / report_date.isoformat() / f"{stem}_{compact}.xlsx",
        structured_dir / f"{stem}_{compact}.xlsx",
    )
    return next((path for path in candidates if path.is_file()), None)


def discover_inputs(
    data_root: Path,
    report_date: date,
    structured_image_dir: Path | None,
) -> dict[str, str]:
    date_dir = data_root / report_date.isoformat()
    if not date_dir.is_dir():
        raise RuntimeError(f"日报目录不存在：{report_date.isoformat()}")
    compact = report_date.strftime("%Y%m%d")
    files: dict[str, str] = {}
    for key, (stem, suffixes) in SOURCE_SPECS.items():
        override = _structured_override(structured_image_dir, report_date, stem)
        files[key] = str(override or _find_one(date_dir, stem, suffixes, compact))
    return files


def discover_finalized_workbook(data_root: Path, report_date: date) -> Path:
    date_dir = data_root / report_date.isoformat()
    return _find_one(
        date_dir,
        "员工数增减情况日报",
        {".xlsx"},
        report_date.strftime("%Y%m%d"),
    )


def load_expected(workbook: Path, report_date: date) -> tuple[dict[int, int], list[dict]]:
    summary = pd.read_excel(workbook, sheet_name="Sheet1", header=None)
    _, report_col, _ = _find_date_columns(summary, report_date)
    expected_rows: dict[int, int] = {}
    for row_no in BUSINESS_ROWS:
        value = summary.iloc[row_no - 1, report_col]
        if pd.isna(value):
            raise RuntimeError(f"定稿日报 Row{row_no} 在报告日列为空")
        expected_rows[row_no] = int(value)

    return expected_rows, parse_tenure_workbook(workbook, report_date)


def compare_result(
    *,
    actual_rows: dict[int, dict],
    expected_rows: dict[int, int],
    actual_tenure_total: int,
    expected_tenure_total: int,
    actual_tenure_rows: list[dict],
    expected_tenure_rows: list[dict],
    validations: list[dict[str, Any]],
) -> dict[str, Any]:
    """只返回行号和错误类别，避免把真实人事数字写入共享结果。"""
    row_mismatches: list[dict[str, Any]] = []
    for row_no, expected in sorted(expected_rows.items()):
        info = actual_rows.get(row_no)
        if info is None or info.get("value") is None:
            row_mismatches.append({"row": row_no, "kind": "missing_actual"})
            continue
        if int(info["value"]) != expected:
            row_mismatches.append({"row": row_no, "kind": "value_mismatch"})

    hard_failures = [
        str(item.get("check") or "unnamed hard check")
        for item in validators.hard_failures(validations)
    ]
    tenure_total_match = actual_tenure_total == expected_tenure_total
    actual_by_slot = {str(row.get("slot")): row for row in actual_tenure_rows}
    tenure_row_mismatches: list[dict[str, str]] = []
    for expected in expected_tenure_rows:
        slot = str(expected.get("slot"))
        actual = actual_by_slot.get(slot)
        if actual is None:
            tenure_row_mismatches.append({"slot": slot, "kind": "missing_actual"})
            continue
        if str(actual.get("business_unit")) != str(expected.get("business_unit")):
            tenure_row_mismatches.append({"slot": slot, "kind": "label_mismatch"})
        if int(actual.get("ytd_leavers") or 0) != int(expected.get("ytd_leavers") or 0):
            tenure_row_mismatches.append({"slot": slot, "kind": "count_mismatch"})
        if actual.get("avg_tenure_years") != expected.get("avg_tenure_years"):
            tenure_row_mismatches.append({"slot": slot, "kind": "average_mismatch"})
    return {
        "passed": (
            not row_mismatches
            and tenure_total_match
            and not tenure_row_mismatches
            and not hard_failures
        ),
        "row_mismatches": row_mismatches,
        "tenure_total_match": tenure_total_match,
        "tenure_row_mismatches": tenure_row_mismatches,
        "hard_failures": hard_failures,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="以定稿日报为基线，重放后续日期输入并生成脱敏比较摘要。",
    )
    parser.add_argument("--data-root", type=Path, required=True, help="包含 YYYY-MM-DD 子目录的日报根目录")
    parser.add_argument("--baseline-date", type=_parse_date, required=True, help="已定稿基线日")
    parser.add_argument("--dates", type=_parse_date, nargs="+", required=True, help="按顺序重放的报告日")
    parser.add_argument(
        "--structured-image-dir",
        type=Path,
        help="可选：经批准的截图结构化 xlsx 目录；未提供时直接走视觉 LLM",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="生成报表和脱敏 JSON 的目录")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    dates = list(args.dates)
    if dates != sorted(dates) or any(day <= args.baseline_date for day in dates):
        raise RuntimeError("--dates 必须严格晚于基线日并按升序提供")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    summary: dict[str, Any] = {
        "baseline_date": args.baseline_date.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_tenure_match": False,
        "cases": [],
    }

    with Session() as db, tempfile.TemporaryDirectory(prefix="hr_chain_regression_") as tmp:
        extractor = ExtractionAgent()
        baseline_inputs = discover_inputs(
            args.data_root, args.baseline_date, args.structured_image_dir,
        )
        extractor.run(db, args.baseline_date, baseline_inputs, tmp_dir=tmp)
        db.commit()  # agent 只 flush，事务由调用方提交

        baseline_workbook = discover_finalized_workbook(args.data_root, args.baseline_date)
        baseline_rows, _ = parse_daily_workbook(baseline_workbook, args.baseline_date)
        report_repo.save_daily(db, args.baseline_date, baseline_rows)
        report_repo.save_tenure_snapshot(
            db,
            args.baseline_date,
            parse_tenure_workbook(baseline_workbook, args.baseline_date),
        )
        _, expected_baseline_tenure_rows = load_expected(
            baseline_workbook, args.baseline_date,
        )
        expected_baseline_tenure = sum(
            row["ytd_leavers"] for row in expected_baseline_tenure_rows
        )
        actual_baseline_tenure = tenure_calc.compute_tenure(db, args.baseline_date)["b10"]
        summary["baseline_tenure_match"] = actual_baseline_tenure == expected_baseline_tenure
        if not summary["baseline_tenure_match"]:
            return summary

        previous_date = args.baseline_date
        for report_date in dates:
            files = discover_inputs(args.data_root, report_date, args.structured_image_dir)
            extractor.run(db, report_date, files, tmp_dir=tmp)
            db.commit()  # 同上：调用方持有事务

            ctx = daily_calc.compute_daily(db, report_date, previous_date)
            ctx["tenure"] = tenure_calc.compute_tenure(db, report_date)
            ctx["validations"] = validators.run_daily_checks(ctx)
            expected_rows, expected_tenure_rows = load_expected(
                discover_finalized_workbook(args.data_root, report_date), report_date,
            )
            expected_tenure = sum(row["ytd_leavers"] for row in expected_tenure_rows)
            comparison = compare_result(
                actual_rows=ctx["rows"],
                expected_rows=expected_rows,
                actual_tenure_total=int(ctx["tenure"]["b10"] or 0),
                expected_tenure_total=expected_tenure,
                actual_tenure_rows=ctx["tenure"]["rows"],
                expected_tenure_rows=expected_tenure_rows,
                validations=ctx["validations"],
            )
            summary["cases"].append({"report_date": report_date.isoformat(), **comparison})
            if not comparison["passed"]:
                break

            report_repo.save_daily(db, report_date, ctx["rows"])
            baseline_values = report_repo.get_baseline_rows(db, report_date, previous_date)
            daily_exporter.export_daily(
                ctx, ctx["tenure"], str(args.output_dir), baseline_values,
                # 以前一日定稿为续列模板，产出与人工定稿同版式的工作簿
                template_path=str(
                    discover_finalized_workbook(args.data_root, previous_date)
                ),
            )
            previous_date = report_date

    return summary


def main() -> int:
    args = _build_parser().parse_args()
    summary = run(args)
    summary_path = args.output_dir / "chain_regression_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if not summary["baseline_tenure_match"]:
        print("BASELINE FAIL: tenure_total_mismatch")
        print(f"Redacted summary: {summary_path}")
        return 1
    for case in summary["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        rows = ",".join(str(item["row"]) for item in case["row_mismatches"]) or "none"
        print(f"{case['report_date']} {status}: mismatch_rows={rows}")
    print(f"Redacted summary: {summary_path}")
    return 0 if summary["cases"] and all(case["passed"] for case in summary["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
