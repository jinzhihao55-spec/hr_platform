"""Import an approved daily workbook as both projection and formal baseline."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.core.exceptions import DailyImportError
from app.models.facts import RunDecision, encode_json_text
from app.models.publication import PublishedReport, ReportArtifact
from app.models.runs import (
    ReportRun,
    RunReportTarget,
    RunSource,
    RunStatus,
    SourceType,
    TargetStatus,
)
from app.pipeline.input.daily_workbook import parse_daily_workbook, parse_tenure_workbook
from app.repositories import publication_repo, report_repo
from app.services.fact_history_service import materialize_initial_history

log = get_logger("service.daily_import")
_IMPORTED_RULE_VERSION = "imported-baseline-v1"


def _kpis(rows: dict[int, dict]) -> dict[str, int]:
    def _v(n: int) -> int:
        return int((rows.get(n) or {}).get("value") or 0)

    return {
        "row2_今日入职": _v(2),
        "row3_今日离职": _v(3),
        "row7_今日净增": _v(7),
        "row12_MTD净增": _v(12),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_protected_dir(path: Path) -> None:
    output_root = Path(settings.output_dir).resolve()
    shutil.rmtree(path, ignore_errors=True)
    parent = path.parent
    while parent != output_root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _snapshot_json(
    report_date: date,
    rows: dict[int, dict],
    tenure_rows: list[dict],
    *,
    rule_version: str = _IMPORTED_RULE_VERSION,
    source: str = "approved_daily_import",
) -> str:
    return encode_json_text(
        {
            "report_kind": "daily",
            "period_start": report_date.isoformat(),
            "period_end": report_date.isoformat(),
            "rule_version": rule_version,
            "rows": {
                str(number): {
                    "label": info.get("label"),
                    "value": info.get("value"),
                    "is_blank": bool(info.get("is_blank")),
                }
                for number, info in sorted(rows.items())
            },
            "main_rows": [],
            "cc_rows": [],
            "tenure": {"rows": tenure_rows},
            "events": [],
            "validation_summary": {
                "source": source,
                "publishable": True,
            },
        }
    )


def _register_formal_baseline(
    db: Session,
    report_date: date,
    rows: dict[int, dict],
    tenure_rows: list[dict],
    workbook: Path,
    imported_by: str,
    *,
    run: ReportRun | None = None,
    source_bundle_hash: str | None = None,
    source: str = "approved_daily_import",
) -> tuple[PublishedReport, Path]:
    artifact_sha256 = _sha256(workbook)
    version = publication_repo.next_version(
        db, "daily", report_date, report_date
    )
    if run is None:
        fingerprint = hashlib.sha256(
            f"{report_date.isoformat()}:{version}:{artifact_sha256}".encode("utf-8")
        ).hexdigest()
        run = ReportRun(
            report_date=report_date,
            status=RunStatus.ready.value,
            rule_version=_IMPORTED_RULE_VERSION,
            source_bundle_hash=fingerprint,
            baseline_report_id=None,
            attempt_no=0,
        )
        db.add(run)
        db.flush()
    else:
        if run.report_date != report_date:
            raise DailyImportError("初始基线日期必须与当前运行日期一致")
        run.source_bundle_hash = source_bundle_hash or hashlib.sha256(
            f"{run.id}:{artifact_sha256}".encode("utf-8")
        ).hexdigest()
        run.status = RunStatus.ready.value
        db.flush()

    protected_dir = (
        Path(settings.output_dir)
        / "published"
        / "daily"
        / report_date.isoformat()
        / run.id
    ).resolve()
    protected_dir.mkdir(parents=True, exist_ok=False)
    try:
        protected_path = protected_dir / (
            f"员工数增减情况日报_{report_date.isoformat()}.xlsx"
        )
        shutil.copyfile(workbook, protected_path)

        snapshot_json = _snapshot_json(
            report_date,
            rows,
            tenure_rows,
            rule_version=run.rule_version,
            source=source,
        )
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        published_at = datetime.now(timezone.utc).replace(tzinfo=None)
        publication_repo.supersede_current(
            db, "daily", report_date, report_date, published_at
        )
        report = PublishedReport(
            run_id=run.id,
            report_kind="daily",
            period_start=report_date,
            period_end=report_date,
            version=version,
            is_current=True,
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            baseline_report_id=None,
            published_by=imported_by or "local-operator",
            published_at=published_at,
        )
        db.add(report)
        db.flush()
        target = db.scalar(
            select(RunReportTarget).where(
                RunReportTarget.run_id == run.id,
                RunReportTarget.report_kind == "daily",
                RunReportTarget.is_deleted == 0,
            )
        )
        if target is None:
            target = RunReportTarget(run_id=run.id, report_kind="daily")
            db.add(target)
        target.status = TargetStatus.published.value
        target.preview_hash = snapshot_hash
        target.validation_summary = encode_json_text(
            {"publishable": True, "source": source}
        )
        target.published_report_id = report.id
        db.add(
            ReportArtifact(
                report_id=report.id,
                artifact_kind="excel",
                protected_path=str(protected_path),
                sha256=artifact_sha256,
                size_bytes=protected_path.stat().st_size,
            )
        )
        return report, protected_dir
    except Exception:
        _remove_protected_dir(protected_dir)
        raise


def _write_compatibility_copy(workbook: Path, report_date: date) -> None:
    finalized_dir = Path(settings.output_dir) / "finalized"
    finalized_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(
            workbook,
            finalized_dir / f"员工数增减情况日报_{report_date.isoformat()}.xlsx",
        )
    except OSError:
        log.exception("正式基线已登记，但兼容模板副本写入失败: %s", report_date)


def _validate_initial_run(db: Session, run_id: str) -> tuple[ReportRun, list[RunSource]]:
    run = db.get(ReportRun, run_id)
    if run is None or run.is_deleted:
        raise DailyImportError("初始基线运行不存在")
    if run.baseline_report_id is not None:
        raise DailyImportError("只有没有历史基线的首次运行可以建立初始基线")
    if run.source_bundle_hash is not None:
        raise DailyImportError("当前运行输入已经冻结，不能重复建立初始基线")
    sources = db.scalars(
        select(RunSource).where(
            RunSource.run_id == run.id,
            RunSource.is_deleted == 0,
        )
    ).all()
    source_types = {source.source_type for source in sources}
    required = {source.value for source in SourceType}
    if source_types != required:
        raise DailyImportError("建立初始基线前必须完成四项输入")
    pending = db.scalar(
        select(RunDecision.id)
        .where(
            RunDecision.run_id == run.id,
            RunDecision.status != "answered",
            RunDecision.is_deleted == 0,
        )
        .limit(1)
    )
    if pending is not None:
        raise DailyImportError("建立初始基线前必须完成全部人工确认")
    published = db.scalar(
        select(RunReportTarget.id)
        .where(
            RunReportTarget.run_id == run.id,
            RunReportTarget.status == TargetStatus.published.value,
            RunReportTarget.is_deleted == 0,
        )
        .limit(1)
    )
    if published is not None:
        raise DailyImportError("当前运行已经发布，不能重复建立初始基线")
    return run, list(sources)


def _initial_source_bundle_hash(
    run: ReportRun, sources: list[RunSource], artifact_sha256: str
) -> str:
    payload = encode_json_text(
        {
            "report_date": run.report_date.isoformat(),
            "rule_version": run.rule_version,
            "sources": {
                source.source_type: source.sha256
                for source in sorted(sources, key=lambda item: item.source_type)
            },
            "approved_daily": artifact_sha256,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def finalize_initial_run_baseline(
    db: Session,
    run_id: str,
    file: UploadFile,
    imported_by: str = "local-operator",
) -> dict:
    """Freeze a four-source Run with its approved same-day daily workbook."""
    run, sources = _validate_initial_run(db, run_id)
    report_date = run.report_date
    overwritten = report_repo.daily_exists(db, report_date)
    tmp = Path(tempfile.mkdtemp(prefix="hr_initial_baseline_"))
    safe_name = Path(file.filename or "").name or f"daily_{report_date}.xlsx"
    dest = tmp / safe_name
    try:
        with dest.open("wb") as stream:
            shutil.copyfileobj(file.file, stream)
        rows, _ = parse_daily_workbook(dest, report_date)
        tenure_rows = parse_tenure_workbook(dest, report_date)
        tenure_total = sum(row["ytd_leavers"] for row in tenure_rows)
        if tenure_total != int(rows[14]["value"]):
            raise DailyImportError(
                "在岗时长 B10 与 Sheet1 Row14 不一致，拒绝建立初始基线",
                detail={"check": "tenure_b10_equals_row14"},
            )

        protected_dir: Path | None = None
        try:
            materialize_initial_history(db, run)
            report_repo.save_daily(db, report_date, rows, commit=False)
            report_repo.save_tenure_snapshot(
                db, report_date, tenure_rows, commit=False
            )
            baseline, protected_dir = _register_formal_baseline(
                db,
                report_date,
                rows,
                tenure_rows,
                dest,
                imported_by,
                run=run,
                source_bundle_hash=_initial_source_bundle_hash(
                    run, sources, _sha256(dest)
                ),
                source="confirmed_four_source_bootstrap",
            )
            db.commit()
        except Exception:
            db.rollback()
            if protected_dir is not None:
                _remove_protected_dir(protected_dir)
            raise

        _write_compatibility_copy(dest, report_date)
        return {
            "report_date": report_date.isoformat(),
            "status": "succeeded",
            "overwritten": overwritten,
            "rows_imported": len(rows),
            "baseline_report_id": baseline.id,
            "kpis": _kpis(rows),
            "cascaded": [],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def import_daily(
    db: Session,
    report_date: date,
    file: UploadFile,
    regenerate: bool = True,
    imported_by: str = "local-operator",
) -> dict:
    """导入定稿日报到 daily_reports（已存在则覆盖）。

    regenerate=True：导入后按链式基线级联重算 report_date 之后已存在的所有日报
    （及随日报联动的周报）。导入本身即为「插入 + 依赖新基线重算其后报表」的一步。
    数据已在库，级联仅重算派生的日/周报表，不重新拉取原始数据。
    """
    overwritten = report_repo.daily_exists(db, report_date)
    tmp = Path(tempfile.mkdtemp(prefix="hr_daily_import_"))
    # filename 由客户端提供：只取 basename，防止 ../ 写出临时目录
    safe_name = Path(file.filename or "").name or f"daily_{report_date}.xlsx"
    dest = tmp / safe_name
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        rows, _ = parse_daily_workbook(dest, report_date)
        tenure_rows = parse_tenure_workbook(dest, report_date)
        tenure_total = sum(row["ytd_leavers"] for row in tenure_rows)
        if tenure_total != int(rows[14]["value"]):
            raise DailyImportError(
                "在岗时长 B10 与 Sheet1 Row14 不一致，拒绝导入为链式基线",
                detail={"check": "tenure_b10_equals_row14"},
            )
        protected_dir: Path | None = None
        try:
            report_repo.save_daily(db, report_date, rows, commit=False)
            report_repo.save_tenure_snapshot(
                db, report_date, tenure_rows, commit=False,
            )
            baseline, protected_dir = _register_formal_baseline(
                db,
                report_date,
                rows,
                tenure_rows,
                dest,
                imported_by,
            )
            db.commit()
        except Exception:
            db.rollback()
            if protected_dir is not None:
                _remove_protected_dir(protected_dir)
            raise

        # 兼容旧计算入口的模板查找；正式不可变副本由 ReportArtifact 指向。
        _write_compatibility_copy(dest, report_date)

        cascaded: list[dict] = []
        cascade_error: str | None = None
        if regenerate:
            # 延迟导入避免与 report_service 形成循环依赖
            from app.services import report_service
            try:
                cascaded = report_service.cascade_later(db, report_date)
            except Exception:  # noqa: BLE001  级联失败不应回滚已成功的导入
                log.exception("导入 %s 后级联重算失败（导入本身已成功）", report_date)
                cascade_error = "定稿日报已导入，但后续日报级联重算未完成，请查看服务日志后重试"

        result = {
            "report_date": report_date.isoformat(),
            "status": "partial" if cascade_error else "succeeded",
            "overwritten": overwritten,
            "rows_imported": len(rows),
            "baseline_report_id": baseline.id,
            "kpis": _kpis(rows),
            "cascaded": cascaded,
        }
        if cascade_error:
            result["cascade_error"] = cascade_error
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
