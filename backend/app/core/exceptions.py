"""领域异常。流水线遇到缺数据/歧义时必须"停下来提问"而非臆测——
这些异常类型让该行为显式且可被程序识别。"""
from typing import Any


class HRAgentError(Exception):
    """异常基类。"""

    code = "hr_agent_error"

    def __init__(self, message: str, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class InputMissingError(HRAgentError):
    """必需输入源缺失 / 不可读。"""

    code = "input_missing"


class SchemaMismatchError(HRAgentError):
    """Excel 表头与预期模板不一致。"""

    code = "schema_mismatch"


class InclusionFilterError(HRAgentError):
    """硬阻断：违反员工类型纳入口径。"""

    code = "inclusion_filter"


class BaselineMissingError(HRAgentError):
    """缺少昨日已验收日报（链式基线）。"""

    code = "baseline_missing"


class DailyImportError(HRAgentError):
    """定稿日报 xlsx 解析/校验失败。"""

    code = "daily_import_invalid"


class DailyTemplateMissingError(HRAgentError):
    """缺少可承袭的日报工作簿（已验收定稿/此前生成），禁止凭空造模板。"""

    code = "daily_template_missing"


class MonthOpeningBaselineError(HRAgentError):
    """月初基线文件或确认内容不符合契约。"""

    code = "month_opening_baseline_invalid"


class MonthOpeningBaselineMissingError(HRAgentError):
    """跨月生成前尚未由 HR 确认或上传月初基线。"""

    code = "month_opening_baseline_missing"


class ClarificationRequired(HRAgentError):
    """必须由人工先行澄清的歧义。

    `questions` 遵循 §9 提问模板结构，便于 API/前端展示。
    """

    code = "clarification_required"

    def __init__(self, message: str, questions: list[dict] | None = None):
        super().__init__(message, detail=questions)
        self.questions = questions or []


class ValidationBlockError(HRAgentError):
    """§5 发布前校验中某项未通过（硬阻断）。"""

    code = "validation_block"


class RunInputFrozenError(HRAgentError):
    """A fingerprinted/ready Run cannot accept replacement source data."""

    code = "run_input_frozen"


class SQLGuardError(HRAgentError):
    """模型产出的 SQL 未通过安全校验（非只读、含危险语句、或多语句注入等）。"""

    code = "sql_guard"
