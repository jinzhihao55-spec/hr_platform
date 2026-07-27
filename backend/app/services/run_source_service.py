"""Stream one explicit source into minimal, run-scoped canonical facts."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import InputMissingError, RunInputFrozenError
from app.domain.identity import derive_person_identity
from app.models.facts import ReleaseFact, encode_json_text
from app.models.publication import PublishedReport
from app.models.runs import ReportRun, RunStatus, SourceType
from app.pipeline.input import image_parser, parsers
from app.repositories import fact_repo, run_repo
from app.utils.dates import parse_date, to_int


_EXCEL_EXTENSIONS = {".xlsx", ".xls"}
_IMAGE_EXTENSIONS = image_parser.IMAGE_EXTS
_SCHEMA_VERSIONS = {
    SourceType.personnel: "personnel-v1",
    SourceType.resignation: "resignation-v1",
    SourceType.release: "release-v2",
    SourceType.recruitment: "recruitment-v1",
}
_VISION_TABLE_TYPES = {
    SourceType.release: "agreements",
    SourceType.recruitment: "recruitment",
}
_TRUE_VALUES = {"是", "y", "yes", "true", "1", "include"}
_FALSE_VALUES = {"否", "n", "no", "false", "0", "exclude"}
_RELEASE_DETAIL_HEADERS = {
    "单号",
    "申请时间",
    "创建人",
    "被申请人姓名",
    "职位",
    "项目名称",
    "入职时间",
    "最后工作日",
    "在岗时长",
}


@dataclass(frozen=True)
class SourceIngestResult:
    run_id: str
    source_type: str
    sha256: str
    row_count: int
    parse_status: str
    persisted_fields: tuple[str, ...]


@dataclass(frozen=True)
class _BuiltSource:
    facts: list[dict[str, Any]]
    decisions: list[dict[str, Any]]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _classification(value: Any) -> str:
    normalized = (_text(value) or "").casefold()
    if normalized in _TRUE_VALUES:
        return "include"
    if normalized in _FALSE_VALUES:
        return "exclude"
    return "review"


def _decision(
    source: SourceType,
    row_no: int | str,
    code: str,
    question: str,
    options: list[str],
) -> dict[str, Any]:
    return {
        "report_kind": None,
        "decision_code": code,
        "fact_ref": f"source:{source.value}:row:{row_no}",
        "question": question,
        "options": encode_json_text(options),
        "answer": None,
        "status": "pending",
        "decided_at": None,
        "operator_ref": None,
    }


class RunSourceService:
    def __init__(
        self,
        db: Session,
        *,
        person_key_secret: str | None = None,
        person_key_version: str | None = None,
        parser_version: str = "run-staging-v2",
    ) -> None:
        self.db = db
        self.person_key_secret = (
            settings.person_key_secret
            if person_key_secret is None
            else person_key_secret
        )
        self.person_key_version = person_key_version or settings.person_key_version
        self.parser_version = parser_version

    async def ingest(
        self,
        run_id: str,
        source_type: str | SourceType,
        upload_file: UploadFile,
    ) -> SourceIngestResult:
        source = (
            source_type
            if isinstance(source_type, SourceType)
            else SourceType(source_type)
        )
        run = self.db.get(ReportRun, run_id)
        if run is None or run.is_deleted:
            raise LookupError(f"Run {run_id} was not found")
        if run.source_bundle_hash is not None or run.status in {
            RunStatus.ready.value,
            RunStatus.deduplicated.value,
        }:
            raise RunInputFrozenError(
                "finalized Run inputs are immutable; create a new Run for changed data"
            )
        fact_repo.assert_run_facts_mutable(self.db, run.id)

        temp_dir = tempfile.mkdtemp(prefix="hr_run_source_")
        try:
            sha256, path, extension = await self._stream_upload(
                upload_file, Path(temp_dir), source
            )
            parsed_path, from_image = self._prepare_source(path, temp_dir, source)
            built = self._parse_and_build(parsed_path, source, run, from_image)
            parse_status = "needs_review" if built.decisions else "parsed"

            try:
                with self.db.begin_nested():
                    fact_repo.replace_source_facts(
                        self.db, run.id, source, built.facts
                    )
                    fact_repo.replace_source_review_decisions(
                        self.db, run.id, source, built.decisions
                    )
                    run_repo.upsert_source_metadata(
                        self.db,
                        run.id,
                        source,
                        sha256=sha256,
                        schema_version=_SCHEMA_VERSIONS[source],
                        parser_version=self.parser_version,
                        media_type=upload_file.content_type,
                        row_count=len(built.facts),
                        parse_status=parse_status,
                        original_extension=extension,
                        original_filename=Path(upload_file.filename or "").name,
                    )
                    if run.status == RunStatus.created.value:
                        run_repo.transition_run(self.db, run, RunStatus.parsing)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

            return SourceIngestResult(
                run_id=run.id,
                source_type=source.value,
                sha256=sha256,
                row_count=len(built.facts),
                parse_status=parse_status,
                persisted_fields=fact_repo.persisted_fields_for(source),
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _stream_upload(
        self, upload_file: UploadFile, temp_dir: Path, source: SourceType
    ) -> tuple[str, str, str]:
        extension = Path(upload_file.filename or "").suffix.lower()
        allowed = set(_EXCEL_EXTENSIONS)
        if source in _VISION_TABLE_TYPES:
            allowed |= _IMAGE_EXTENSIONS
        if extension not in allowed:
            expected = "Excel" if source not in _VISION_TABLE_TYPES else "Excel 或图片"
            raise InputMissingError(
                f"{source.value} 输入格式不支持，请上传{expected}文件",
                detail={"source": source.value, "extension": extension},
            )

        path = temp_dir / f"{source.value}{extension}"
        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as stream:
            while chunk := await upload_file.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            raise InputMissingError(
                f"{source.value} 上传文件为空",
                detail={"source": source.value},
            )
        return digest.hexdigest(), str(path), extension

    def _prepare_source(
        self, path: str, temp_dir: str, source: SourceType
    ) -> tuple[str, bool]:
        if not image_parser.is_image(path):
            return path, False
        if source not in _VISION_TABLE_TYPES:
            raise InputMissingError(
                f"{source.value} 正式入口只接受 Excel；图片识别结果不可直接入库",
                detail={"source": source.value, "code": "ocr_review_required"},
            )
        try:
            converted = image_parser.convert_to_xlsx(
                path, _VISION_TABLE_TYPES[source], temp_dir
            )
        except RuntimeError as exc:
            raise InputMissingError(
                f"图像识别失败（{source.value}）：{exc}",
                detail={"source": source.value, "code": "image_parse_failed"},
            ) from exc
        return converted, True

    def _parse_and_build(
        self,
        path: str,
        source: SourceType,
        run: ReportRun,
        from_image: bool,
    ) -> _BuiltSource:
        if source is SourceType.personnel:
            frame = parsers.parse_employees(path)
            built = self._build_personnel(frame)
        elif source is SourceType.resignation:
            frame = parsers.parse_resignations(path)
            built = self._build_resignations(frame)
        elif source is SourceType.release:
            frame = parsers.parse_agreements(path)
            built = self._build_releases(frame, run, from_image)
        else:
            frame = parsers.parse_recruitment(path, run.report_date.month)
            built = self._build_recruitment(frame, run.report_date, from_image)

        for certificate_column in ("证件类型", "证件号"):
            if certificate_column in frame.columns:
                frame.drop(columns=[certificate_column], inplace=True)
        return built

    def _derive_identity(self, row: pd.Series):
        certificate_number = row.get("证件号")
        employee_no = row.get("工号")
        if _text(certificate_number) is None and _text(employee_no) is None:
            return None
        return derive_person_identity(
            row.get("证件类型"),
            certificate_number,
            employee_no,
            secret=self.person_key_secret,
            key_version=self.person_key_version,
        )

    def _build_personnel(self, frame: pd.DataFrame) -> _BuiltSource:
        facts: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            contract_dates = {
                "contract_start": parse_date(row.get("合同开始日期")),
                "contract_end": parse_date(row.get("合同结束日期")),
                "intern_contract_start": parse_date(row.get("实习生合同开始日期")),
                "intern_contract_end": parse_date(row.get("实习生合同结束日期")),
            }
            contract_dates = {
                key: value for key, value in contract_dates.items() if value is not None
            }
            facts.append(
                {
                    "source_row_no": int(index) + 2,
                    "identity": self._derive_identity(row),
                    "employee_no": _text(row.get("工号")),
                    "display_name": _text(row.get("中文名"))
                    or _text(row.get("英文名"))
                    or _text(row.get("Alias")),
                    "employee_type": _text(row.get("员工类型")),
                    "status": _text(row.get("员工状态")),
                    "entry_date": parse_date(row.get("入职日期")),
                    "resign_date": parse_date(row.get("离职日期")),
                    "business_unit": _text(row.get("事业部")),
                    "business_unit_no": _text(row.get("事业部编号")),
                    "project_code": _text(row.get("项目编号")),
                    "project_name": _text(row.get("项目名称")),
                    "contract_dates": (
                        encode_json_text(contract_dates) if contract_dates else None
                    ),
                    "first_visible_dates": None,
                }
            )
        return _BuiltSource(facts=facts, decisions=[])

    def _build_resignations(self, frame: pd.DataFrame) -> _BuiltSource:
        facts: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            application_date = parse_date(row.get("员工申请时间"))
            facts.append(
                {
                    "source_row_no": int(index) + 2,
                    "identity": self._derive_identity(row),
                    "process_no": _text(row.get("流程单号")),
                    "employee_no": _text(row.get("工号")),
                    "process_status": _text(row.get("流程状态")),
                    "application_date": application_date,
                    "last_working_day": parse_date(row.get("最后工作日")),
                    "resignation_type": _text(row.get("离职方式")),
                    "first_visible_date": parse_date(row.get("首次可见日期")),
                }
            )
        return _BuiltSource(facts=facts, decisions=[])

    def _build_releases(
        self, frame: pd.DataFrame, run: ReportRun, from_image: bool
    ) -> _BuiltSource:
        facts: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        is_release_detail = _RELEASE_DETAIL_HEADERS.issubset(set(frame.columns))
        historical_lwds = self._release_lwd_history(run)
        for index, row in frame.iterrows():
            row_no = int(index) + 2
            order_no = _text(row.get("单号"))
            parsed_lwd = parse_date(row.get("最后工作日"))
            last_working_day = (
                historical_lwds.get(order_no)
                if from_image
                else parsed_lwd or historical_lwds.get(order_no)
            )
            row5_classification = _classification(row.get("计入Row5"))
            if row5_classification == "review":
                process_type = _text(row.get("流程类型")) or ""
                process_name = _text(row.get("流程名称")) or ""
                if is_release_detail or process_type in {
                    "离职审批",
                    "协议解除",
                    "人事相关",
                } or (
                    "协议" in process_name
                ):
                    row5_classification = "include"

            row30_classification = _classification(row.get("计入Row30"))
            if row30_classification == "review":
                if last_working_day is None:
                    row30_classification = "review" if from_image else "exclude"
                else:
                    row30_classification = (
                        "include"
                        if (
                            last_working_day.year,
                            last_working_day.month,
                        )
                        == (run.report_date.year, run.report_date.month)
                        else "exclude"
                    )
            facts.append(
                {
                    "source_row_no": row_no,
                    "identity": None,
                    "order_no": order_no,
                    "employee_no": None,
                    "application_date": parse_date(row.get("申请时间")),
                    "last_working_day": last_working_day,
                    "process_status": _text(row.get("当前状态")),
                    "first_visible_date": parse_date(row.get("首次可见批次")),
                    "row5_classification": row5_classification,
                    "row30_classification": row30_classification,
                    "ocr_confidence": "unreviewed" if from_image else None,
                }
            )
            if row5_classification == "review":
                decisions.append(
                    _decision(
                        SourceType.release,
                        row_no,
                        "release_row5_classification_required",
                        "该 OA 记录无法按流程名称或类型判断是否计入 Row5。",
                        ["计入Row5", "不计入Row5", "替换输入"],
                    )
                )
            if from_image and last_working_day is None:
                decisions.append(
                    _decision(
                        SourceType.release,
                        row_no,
                        "release_lwd_missing",
                        (
                            f"OA/Release 来源行 {row_no}（单号 {order_no or '未识别'}）"
                            "缺少最后工作日（LWD），请补充。"
                        ),
                        ["补充最后工作日", "替换输入"],
                    )
                )
        if from_image:
            decisions.insert(
                0,
                _decision(
                    SourceType.release,
                    "ocr",
                    "ocr_review_required",
                    "请确认 OA/Release 图片识别结果。",
                    ["确认", "替换输入"],
                )
            )
        return _BuiltSource(facts=facts, decisions=decisions)

    def _release_lwd_history(self, run: ReportRun | None) -> dict[str, date]:
        if run is None:
            return {}
        history: dict[str, date] = {}
        report_id = run.baseline_report_id
        visited: set[str] = set()
        while report_id and report_id not in visited:
            visited.add(report_id)
            report = self.db.get(PublishedReport, report_id)
            if report is None or report.is_deleted or report.report_kind != "daily":
                break
            facts = self.db.scalars(
                select(ReleaseFact).where(
                    ReleaseFact.run_id == report.run_id,
                    ReleaseFact.last_working_day.is_not(None),
                    ReleaseFact.is_deleted == 0,
                )
            ).all()
            for fact in facts:
                if fact.order_no:
                    history.setdefault(fact.order_no, fact.last_working_day)
            report_id = report.baseline_report_id
        return history

    def _build_recruitment(
        self, frame: pd.DataFrame, report_date, from_image: bool
    ) -> _BuiltSource:
        facts: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            row_no = int(index) + 2
            previous = to_int(row.get("上月接受offer当月预计入职"))
            current = to_int(row.get("当月接受offer当月预计入职"))
            raw = row.get("_raw")
            labels = sorted(str(key) for key in raw) if isinstance(raw, dict) else []
            facts.append(
                {
                    "source_row_no": row_no,
                    "report_date": report_date,
                    "is_total_row": bool(row.get("is_total_row")),
                    "previous_month_offer_current_month_onboard": previous,
                    "current_month_offer_current_month_onboard": current,
                    "recognized_labels": encode_json_text(labels),
                    "ocr_confidence": "unreviewed" if from_image else None,
                }
            )
            if previous is None or current is None:
                decisions.append(
                    _decision(
                        SourceType.recruitment,
                        row_no,
                        "recruitment_label_uncertain",
                        "招聘动态月份列未完整识别，请确认本月两列数值。",
                        ["补充数值", "替换输入"],
                    )
                )
        if from_image:
            decisions.append(
                _decision(
                    SourceType.recruitment,
                    "ocr",
                    "ocr_review_required",
                    "请确认招聘图片识别结果。",
                    ["确认", "替换输入"],
                )
            )
        return _BuiltSource(facts=facts, decisions=decisions)
