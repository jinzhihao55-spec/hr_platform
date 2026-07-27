"""Minimal canonical columns allowed to leave the Excel parsing boundary."""

from __future__ import annotations

import pandas as pd


PERSONNEL_COLUMNS = (
    "员工类型",
    "工号",
    "中文名",
    "英文名",
    "Alias",
    "员工状态",
    "入职日期",
    "离职日期",
    "事业部",
    "事业部编号",
    "部门",
    "部门编号",
    "项目编号",
    "项目名称",
    "合同开始日期",
    "合同结束日期",
    "实习生合同开始日期",
    "实习生合同结束日期",
    "证件类型",
    "证件号",
)

RESIGNATION_COLUMNS = (
    "流程单号",
    "节点名称",
    "流程状态",
    "员工类型",
    "工号",
    "姓名",
    "Alias",
    "入职时间",
    "最后工作日",
    "离职方式",
    "员工申请时间",
    "事业部",
    "部门",
    "项目编号",
    "项目名称",
    "证件类型",
    "证件号",
)


def _project(df: pd.DataFrame, allowed: tuple[str, ...]) -> pd.DataFrame:
    columns = [column for column in allowed if column in df.columns]
    return df.loc[:, columns].copy()


def project_personnel_frame(df: pd.DataFrame) -> pd.DataFrame:
    return _project(df, PERSONNEL_COLUMNS)


def project_resignation_frame(df: pd.DataFrame) -> pd.DataFrame:
    return _project(df, RESIGNATION_COLUMNS)
