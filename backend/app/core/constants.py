"""业务字典 / 枚举。集中配置，不得散落硬编码（Q8）。

"可变字典"（纳入口径、离职分类、流程状态、OA 链路、事业部列表）可通过
PUT /config 在线修改，覆盖值存于 Redis；若 Redis 不可达则回退到此处默认值。
"不可变常量"（日报行结构、公式链）写死于此，不受 Redis 影响。
"""
from __future__ import annotations

from typing import Any

# ============================================================
# 默认值（constants.py 作为单一真相来源；Redis 覆盖为可选）
# ============================================================

# ---- 纳入口径（§1.2）----
INCLUDED_EMPLOYEE_TYPES = {"正式员工", "长期实习生", "短期实习生", "劳务人员"}
EXCLUDED_EMPLOYEE_TYPES = {"P-合作伙伴", "V-供应商", "委托安置"}

# Excel 常见别名 → 纳入口径标准值（Q8 枚举映射）
EMPLOYEE_TYPE_ALIASES: dict[str, str] = {
    "外包": "劳务人员",
    "外包人员": "劳务人员",
    "顾问": "劳务人员",  # schema 注释含顾问，周报归入劳务列
}

# ---- 周报员工类型拆分（Q12：长期+短期实习合并为"实习生"）----
TYPE_BUCKET = {
    "正式员工": "正式员工",
    "长期实习生": "实习生",
    "短期实习生": "实习生",
    "劳务人员": "劳务人员",
}

# ---- 离职方式枚举（Q8）：协商一致默认按被动 Release 处理 ----
RESIGNATION_ACTIVE = {"主动", "主动离职", "主动辞职"}  # 两种写法均涵盖，与库内枚举对齐
RESIGNATION_PASSIVE = {"被动", "协商一致"}

# ---- 流程状态：有效 vs 被拒/作废（进/剔 Row31）----
PROCESS_STATUS_VALID = {"进行中", "已完结", "审批中", "已通过", "审批完成", "等待审批"}
PROCESS_STATUS_REJECTED = {"已驳回", "已拒绝", "已作废", "驳回", "撤销", "作废",
                           "经理拒绝离职", "经理拒绝"}   # 离职报表常见拒绝状态
# Row3 / YTD 离职事实：流程仍在审批中 → 不算已离职（LWD 已预填但人仍在职）
PROCESS_STATUS_ROW3_PENDING = {"审批中", "等待审批", "进行中"}

# ---- OA 协议签署：仅"协议签署/人事相关"进入 Release 链路（§1.1）----
OA_RELEASE_FLOW_NAMES = {"协议签署"}
OA_RELEASE_FLOW_TYPES = {"人事相关"}

# ---- 在岗时长 sheet：固定 8 槽位（§3.9）----
TENURE_BU_SLOTS: list[str] = [
    "BU_A", "BU_B", "BU_C", "BU_D",
    "BU_E", "BU_F", "BU_G", "BU_H",
]

DEFAULT_TENURE_BU_LABELS: dict[str, str] = {s: s for s in TENURE_BU_SLOTS}

# 人员表「事业部编号」或「事业部」中文名 → 槽位（两套 testdata 复用槽位，不会同日并存）
DEFAULT_BU_TO_SLOT: dict[str, str] = {
    "01": "BU_A", "02": "BU_B", "03": "BU_C", "04": "BU_D",
    "05": "BU_E", "06": "BU_F", "07": "BU_G", "08": "BU_H",
    "NBJO": "BU_A", "NENT": "BU_B", "NGOV": "BU_C", "NINS": "BU_D",
    "NITL": "BU_E", "NMSI": "BU_F", "NWMT": "BU_G", "NWTS": "BU_H",
    "BU_A": "BU_A", "BU_B": "BU_B", "BU_C": "BU_C", "BU_D": "BU_D",
    "BU_E": "BU_E", "BU_F": "BU_F", "BU_G": "BU_G", "BU_H": "BU_H",
    # testdata 0622
    "产品事业部": "BU_A", "技术事业部": "BU_B", "市场事业部": "BU_C",
    "运营事业部": "BU_D", "销售事业部": "BU_E",
    # testdata expanded (0629+)
    "企业服务事业部": "BU_A", "商业化事业部": "BU_B", "数字医疗事业部": "BU_C",
    "数据智能事业部": "BU_D", "智能制造事业部": "BU_E", "金融科技事业部": "BU_F",
}

# 周报等仍可从配置读取；在岗时长用 TENURE_BU_SLOTS
BUSINESS_UNITS: list[str] = []

# 周报 Sheet2 固定展示顺序；计算优先使用人员表「事业部编号」。
WEEKLY_BUSINESS_UNIT_ORDER: list[str] = [
    "NINS", "NENT", "NITL", "NMSI", "NBJO", "NWTS", "NWMT", "NGOV",
]
WEEKLY_SUBJECT_LABEL = "微\n创\n网\n络"

# 周报项目族规则：按顺序做前缀匹配。cost_center 非空的六组同时进入 Sheet1。
WEEKLY_PROJECT_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "name": "友邦保险系统平台开发及优化项目",
        "prefixes": ("友邦保险系统平台开发及优化项目",),
        "cost_center": "9000",
    },
    {
        "name": "BP Pulse DevOps 项目",
        "prefixes": ("BP Pulse", "BP Lightening", "BP-Lightning", "BP中国"),
        "cost_center": "9300",
    },
    {
        "name": "巨人ITO项目2026",
        "prefixes": ("巨人ITO项目2026",),
        "cost_center": "9300",
    },
    {
        "name": "贝莱德建信理财IT项目",
        "prefixes": ("贝莱德",),
        "cost_center": "9900",
    },
    {
        "name": "ITIL实施交付",
        "prefixes": ("ITIL实施交付",),
        "cost_center": "9900",
    },
    {
        "name": "捷普需求开发项目",
        "prefixes": ("捷普",),
        "cost_center": "9300",
    },
)

# ============================================================
# 不可变结构常量（日报模板行号 / 公式链）—— 不受 Redis 覆盖影响
# ============================================================

# ---- 日报空白行（保持模板空白，不得填值）----
DAILY_BLANK_ROWS = {23, 24, 27, 28, 34, 35}
# 日报区块表头行（复制上一列样式，填报告日期）
DAILY_HEADER_ROWS = {25, 29, 36}
# 派生/公式行（必须用公式算并校验，不得手填）
DAILY_DERIVED_ROWS = {6, 7, 12, 17, 18, 19, 22, 33, 37, 40}


# ============================================================
# 运行时 getter（合并默认值 + Redis 覆盖）
# pipeline 层应使用这些函数而非直接读取上方模块变量，
# 以确保 PUT /config 的修改在下次计算时立即生效。
# ============================================================

def _get(key: str, default: Any) -> Any:
    """从 Redis 读取覆盖值；若不可用则返回 default。"""
    try:
        from app.repositories.config_repo import get_overrides
        overrides = get_overrides()
        if key in overrides:
            return overrides[key]
    except Exception:
        pass
    return default


def get_included_types() -> set[str]:
    return set(_get("inclusion_types", list(INCLUDED_EMPLOYEE_TYPES)))


def get_excluded_types() -> set[str]:
    return set(_get("exclusion_types", list(EXCLUDED_EMPLOYEE_TYPES)))


def get_resignation_active() -> set[str]:
    return set(_get("resignation_active", list(RESIGNATION_ACTIVE)))


def get_resignation_passive() -> set[str]:
    return set(_get("resignation_passive", list(RESIGNATION_PASSIVE)))


def get_process_status_valid() -> set[str]:
    return set(_get("process_status_valid", list(PROCESS_STATUS_VALID)))


def get_process_status_rejected() -> set[str]:
    return set(_get("process_status_rejected", list(PROCESS_STATUS_REJECTED)))


def get_process_status_row3_pending() -> set[str]:
    return set(_get("process_status_row3_pending", list(PROCESS_STATUS_ROW3_PENDING)))


def get_oa_release_flow_names() -> set[str]:
    return set(_get("oa_release_flow_names", list(OA_RELEASE_FLOW_NAMES)))


def get_oa_release_flow_types() -> set[str]:
    return set(_get("oa_release_flow_types", list(OA_RELEASE_FLOW_TYPES)))


def get_business_units() -> list[str]:
    """周报等场景的可配置 BU 列表；在岗时长用 get_tenure_bu_slots()。"""
    return list(_get("business_units", BUSINESS_UNITS))


def get_tenure_bu_slots() -> list[str]:
    return list(TENURE_BU_SLOTS)


def get_tenure_bu_labels() -> dict[str, str]:
    raw = _get("tenure_bu_labels", DEFAULT_TENURE_BU_LABELS)
    return dict(raw) if isinstance(raw, dict) else dict(DEFAULT_TENURE_BU_LABELS)


def get_bu_to_slot_map() -> dict[str, str]:
    raw = _get("bu_to_slot", DEFAULT_BU_TO_SLOT)
    return dict(raw) if isinstance(raw, dict) else dict(DEFAULT_BU_TO_SLOT)


def resolve_bu_slot(bu_name: str | None, bu_code: str | None) -> str | None:
    """人员表一行 → 在岗时长槽位；无法映射返回 None。"""
    m = get_bu_to_slot_map()
    code = str(bu_code or "").strip()
    name = str(bu_name or "").strip()
    if code and code in m:
        return m[code]
    if name and name in m:
        return m[name]
    return None
