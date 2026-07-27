"""提取 Agent：上传 Excel -> 解析 -> 写入数据库主表（UPSERT）。

流程：Input Layer 解析 + 纳入口径过滤（硬阻断），随后按唯一键写入
employees / employee_resignations / oa_protocols / recruitment_pipeline。
对自由文本备注里的 LWD 等，可调用 LLM 场景①；不可用时按确定性回退。"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.core.exceptions import InputMissingError
from app.pipeline.cleansing import cleanse
from app.pipeline.input import image_parser, parsers
from app.repositories import input_repo
from app.utils.dates import parse_date


def _deduplicate_personnel_identities(df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility path: select one row per non-empty certificate identity.

    The formal Run path keeps every employment and deduplicates by HMAC person key
    in the calculator. The legacy mutable-table path cannot store that relationship,
    so it deterministically retains the latest employment row instead.
    """
    if df.empty or "证件号" not in df.columns:
        return df

    grouped: dict[str, list[int]] = {}
    selected: set[int] = set()
    for index, row in df.iterrows():
        value = row.get("证件号")
        if value is None or (isinstance(value, float) and pd.isna(value)):
            selected.add(index)
            continue
        identity = "".join(str(value).split()).casefold()
        if not identity:
            selected.add(index)
            continue
        grouped.setdefault(identity, []).append(index)

    for indices in grouped.values():
        selected.add(
            max(
                indices,
                key=lambda index: (
                    parse_date(df.at[index, "入职日期"]) or date.min,
                    index,
                ),
            )
        )
    return df.loc[sorted(selected)].reset_index(drop=True)


class ExtractionAgent(BaseAgent):
    name = "extraction"

    def run(
        self,
        db: Session,
        report_date: date,
        files: dict[str, str],
        tmp_dir: str | None = None,
    ) -> dict[str, int]:
        """files: {'employees': 路径, 'resignations': 路径,
                   'agreements': 路径, 'recruitment': 路径}

        图像输入（JPEG / PNG / BMP / WebP / TIFF）会先经视觉模型转换为临时
        xlsx 文件，再由各 parser 正常处理，不影响后续清洗与写库逻辑。
        tmp_dir 用于存放转换后的临时文件（若为 None 则自动生成）。
        """
        import tempfile
        counts: dict[str, int] = {}
        self.cleanse_stats: dict[str, Any] = {}
        _tmp = tmp_dir or tempfile.mkdtemp(prefix="hr_img_")

        def _resolve_path(key: str, path: str) -> str:
            """若为图像则转换为 xlsx；否则原路返回。

            人员表/离职报表（①②）截图按 input_spec §0.1 须人工确认，
            确认流程上线前 fail-closed：拒绝自动入库，提示改传 Excel。"""
            if not image_parser.is_image(path):
                return path
            if key in ("employees", "resignations"):
                file_name = path.split("/")[-1]
                raise InputMissingError(
                    f"人员表/离职报表截图须人工确认后才能入库（{file_name}）："
                    "请改传 Excel（.xls/.xlsx），或走人工确认流程后再上传。",
                    detail={"source": key, "file": file_name,
                            "code": "ocr_review_required"},
                )
            self.log.info("%s 检测为图像文件，启动视觉识别转换…", key)
            try:
                return image_parser.convert_to_xlsx(path, key, _tmp)
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                raise InputMissingError(
                    f"图像识别失败（{key}）：{exc}",
                    detail={"source": key, "file": path.split("/")[-1]},
                ) from exc

        if files.get("employees"):
            path = _resolve_path("employees", files["employees"])
            df = parsers.parse_employees(path)
            df = cleanse.normalize_employee_types(df)
            # 清洗层：纳入口径过滤（硬阻断）、转签留痕（项目名保持原值，不脱敏）
            df, stats = cleanse.filter_inclusion(df)
            df = _deduplicate_personnel_identities(df)
            df = cleanse.trace_resign_transfer(df)
            self.cleanse_stats["employees"] = stats
            counts["employees"] = input_repo.upsert_employees(db, df, report_date)

        if files.get("resignations"):
            path = _resolve_path("resignations", files["resignations"])
            df = parsers.parse_resignations(path)
            counts["resignations"] = input_repo.upsert_resignations(db, df)

        if files.get("agreements"):
            path = _resolve_path("agreements", files["agreements"])
            df = parsers.parse_agreements(path)
            df = self._resolve_lwd(df)
            df = self._apply_oa_lwd_flags(df, report_date)
            counts["agreements"] = input_repo.upsert_oa(db, df, report_date)

        if files.get("recruitment"):
            path = _resolve_path("recruitment", files["recruitment"])
            df = parsers.parse_recruitment(path, report_date.month)
            counts["recruitment"] = input_repo.upsert_recruitment(db, report_date, df)

        # 事务所有权在调用方（ingestion service 单事务提交业务数据 + 上传记录）
        db.flush()
        return counts

    def _resolve_lwd(self, df: pd.DataFrame) -> pd.DataFrame:
        """对缺失的最后工作日，尽量用 LLM 场景①从备注解析；
        否则置空（库内由 row30_flag 表达是否计入本月，Q5）。"""
        if "最后工作日" not in df.columns:
            df["最后工作日"] = None
        for idx, row in df.iterrows():
            if parse_date(row.get("最后工作日")) is not None:
                continue
            remark = str(row.get("备注") or "")
            if remark.strip():
                out = self.run_scenario("extract_unstructured", "最后工作日(LWD)", remark)
                if out.get("available") and out.get("value"):
                    df.at[idx, "最后工作日"] = parse_date(out["value"])
        return df

    @staticmethod
    def _flag_blank(val: Any) -> bool:
        s = str(val or "").strip()
        return s == "" or s.lower() in {"nan", "none", "null", "-", "—", "－"}

    def _apply_oa_lwd_flags(self, df: pd.DataFrame, report_date: date) -> pd.DataFrame:
        """有 LWD 日期但缺 计入Row30/Row5 时，按报告月自动填标志（Q5）。

        OA 表不存 LWD 日期本身，入库靠 row30_flag；OCR 常能读出日期却漏标志。
        """
        if "计入Row30" not in df.columns:
            df["计入Row30"] = None
        if "计入Row5" not in df.columns:
            df["计入Row5"] = None

        for idx, row in df.iterrows():
            lwd = parse_date(row.get("最后工作日"))
            if lwd is None:
                continue
            if self._flag_blank(row.get("计入Row30")):
                in_month = lwd.year == report_date.year and lwd.month == report_date.month
                df.at[idx, "计入Row30"] = "是" if in_month else "否"
            if self._flag_blank(row.get("计入Row5")):
                # 有明确 LWD 的 Release 默认计入 Row5（显式「否」不覆盖）
                df.at[idx, "计入Row5"] = "是"
        return df
