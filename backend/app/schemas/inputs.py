"""四类输入源的 Pydantic 模型（Input Layer 字段校验，§3.1 / §5.1）。

逐行强制字段完整性。缺失 ★ 字段会触发校验错误，流水线据此转为 ClarificationRequired
而非臆测。
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class EmployeeIn(_Base):
    员工类型: str
    工号: str
    中文名: str | None = None
    员工状态: str
    入职日期: date | None = None
    离职日期: date | None = None
    事业部: str | None = None
    事业部编号: str
    部门: str | None = None
    项目名称: str | None = None
    实习生合同结束日期: date | None = None

    @field_validator("工号", "员工类型", "员工状态", "事业部编号")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if v is None or str(v).strip() == "":
            raise ValueError("关键字段为空")
        return v


class ResignationIn(_Base):
    流程单号: str
    流程状态: str
    姓名: str
    最后工作日: date | None = None
    离职方式: str
    员工申请时间: datetime | None = None


class AgreementIn(_Base):
    单号: str
    流程名称: str | None = None
    流程类型: str | None = None
    申请时间: datetime | None = None
    当前状态: str | None = None
    员工标识: str | None = None
    最后工作日: date | None = None


class RecruitmentIn(_Base):
    招聘专员: str | None = None
    is_total_row: bool = False
    上月接受offer当月预计入职: int | None = None
    当月接受offer当月预计入职: int | None = None
