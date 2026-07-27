"""Cleansing Layer（§3.2）。

职责：
  - P/V 及 委托安置 过滤 —— 纳入口径（员工类型异常时硬阻断）
  - 转签识别与留痕（Q11：当前不自动排除）

注意：
  - 项目名称保持原值，清洗层不做 PROJECT_* 脱敏。
  - 历史快照去重已由数据库 UPSERT（按唯一键：工号 / 流程单号 / OA 单号）天然保证，
    不再需要跨 run 的快照比对。

输出：干净但可能仍含非结构化备注文本的 DataFrame（备注由后续提取 Agent 的 LLM 场景处理）。"""
from __future__ import annotations

import pandas as pd

from app.core import constants as C
from app.core.exceptions import InclusionFilterError


def normalize_employee_types(df: pd.DataFrame, *, type_col: str = "员工类型") -> pd.DataFrame:
    """将 Excel 别名（如「外包」）归一为纳入口径标准值。"""
    if type_col not in df.columns:
        return df
    out = df.copy()
    col = out[type_col].astype(str).str.strip()
    out[type_col] = col.replace(C.EMPLOYEE_TYPE_ALIASES)
    return out


# ---------- 纳入口径 ----------
def filter_inclusion(df: pd.DataFrame, *, type_col: str = "员工类型") -> tuple[pd.DataFrame, dict]:
    """只保留纳入口径员工类型；剔除 P/V/委托安置。枚举取值未知时硬阻断，
    让流水线提问而非静默错误归类。"""
    if type_col not in df.columns:
        raise InclusionFilterError(f"缺少 {type_col} 列，无法执行纳入口径过滤")

    included_types = C.get_included_types()
    excluded_types = C.get_excluded_types()
    known = included_types | excluded_types
    seen = set(df[type_col].dropna().astype(str).str.strip())
    unknown = {t for t in seen if t and t not in known}
    if unknown:
        raise InclusionFilterError(
            "员工类型出现未在已确认字典内的取值，需人工归类",
            detail={"unknown_types": sorted(unknown)},
        )

    included = df[df[type_col].astype(str).str.strip().isin(included_types)]
    excluded_n = len(df) - len(included)
    return included.reset_index(drop=True), {"excluded": excluded_n, "kept": len(included)}


# ---------- 转签留痕（Q11）----------
def trace_resign_transfer(df: pd.DataFrame) -> pd.DataFrame:
    """标记转签员工以便留痕；不自动排除（Q11 暂不涉及）。"""
    out = df.copy()
    if "是否转签" in out.columns:
        out["_is_transfer"] = out["是否转签"].astype(str).str.strip().isin(
            {"是", "Y", "true", "True", "1"}
        )
    else:
        out["_is_transfer"] = False
    return out
