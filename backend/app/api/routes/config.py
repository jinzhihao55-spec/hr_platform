"""口径与设置接口。

GET  /config        读取当前生效配置（constants.py 默认值 + Redis 覆盖，Redis 优先）。
PUT  /config        在线修改可变业务字典，覆盖值持久化到 Redis，立即对下次计算生效。
DELETE /config/{field}  重置单个字段回 constants.py 默认值。
DELETE /config          重置全部字段回默认值。

不可变字段（formula_chain / daily_*_rows）只能读取，不接受修改。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import constants as C
from app.repositories import config_repo

router = APIRouter(prefix="/config", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    """PUT /config 请求体：只需传入要修改的字段（其余字段保持原值）。

    列表字段（inclusion_types 等）传 list[str]；顺序不重要，会去重后保存。
    """
    inclusion_types: list[str] | None = None
    exclusion_types: list[str] | None = None
    resignation_active: list[str] | None = None
    resignation_passive: list[str] | None = None
    process_status_valid: list[str] | None = None
    process_status_rejected: list[str] | None = None
    oa_release_flow_names: list[str] | None = None
    oa_release_flow_types: list[str] | None = None
    business_units: list[str] | None = None
    tenure_bu_labels: dict[str, str] | None = None
    bu_to_slot: dict[str, str] | None = None


def _effective_config() -> dict:
    """返回当前生效配置（合并默认值与 Redis 覆盖）。"""
    return {
        # 可变业务字典（通过 getter 读取，含 Redis 覆盖）
        "inclusion_types": sorted(C.get_included_types()),
        "exclusion_types": sorted(C.get_excluded_types()),
        "type_bucket": C.TYPE_BUCKET,               # 只读，不支持在线修改
        "resignation_active": sorted(C.get_resignation_active()),
        "resignation_passive": sorted(C.get_resignation_passive()),
        "process_status_valid": sorted(C.get_process_status_valid()),
        "process_status_rejected": sorted(C.get_process_status_rejected()),
        "oa_release_flow_names": sorted(C.get_oa_release_flow_names()),
        "oa_release_flow_types": sorted(C.get_oa_release_flow_types()),
        "business_units": C.get_business_units(),
        "tenure_bu_slots": C.get_tenure_bu_slots(),
        "tenure_bu_labels": C.get_tenure_bu_labels(),
        "bu_to_slot": C.get_bu_to_slot_map(),
        # 不可变结构常量
        "daily_blank_rows": sorted(C.DAILY_BLANK_ROWS),
        "daily_header_rows": sorted(C.DAILY_HEADER_ROWS),
        "daily_derived_rows": sorted(C.DAILY_DERIVED_ROWS),
        "formula_chain": {
            "Row6": "Row4 + Row5", "Row7": "Row2 - Row3",
            "Row12": "Row8 - Row9 - Row10 + Row11",
            "Row17": "Row13 - Row14 - Row15 + Row16",
            "Row22": "Row18 - Row19 - Row20 + Row21",
            "Row33": "Row30 + Row31 + Row32",
            "Row19": "= Row33",
            "Row37": "= Row8", "Row40": "Row37 + Row38 + Row39",
            "Row18": "= Row40", "B10": "= Sheet1 Row14",
        },
        # 哪些字段有 Redis 覆盖（供前端高亮"已修改"）
        "_overrides_active": sorted(config_repo.get_overrides().keys()),
    }


@router.get("")
def get_config():
    """读取当前生效配置（默认值 + Redis 覆盖）。"""
    return _effective_config()


@router.put("")
def update_config(req: ConfigUpdateRequest):
    """在线修改可变业务字典，立即对下次计算生效。

    只传需要修改的字段；未传字段保持现有覆盖（或默认值）不变。
    返回修改结果与修改后的完整配置。
    """
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "请求体为空，无字段需要更新。")

    result = config_repo.save_overrides(updates)
    return {
        "saved": result["saved"],
        "ignored": result["ignored"],
        "config": _effective_config(),
    }


@router.delete("/{field}")
def reset_field(field: str):
    """重置单个字段回 constants.py 默认值（删除该字段的 Redis 覆盖）。"""
    if field not in config_repo.MUTABLE_FIELDS:
        raise HTTPException(400, f"字段 '{field}' 不可修改或不存在。")
    config_repo.reset(field)
    return {"reset": field, "config": _effective_config()}


@router.delete("")
def reset_all():
    """重置全部字段回 constants.py 默认值。"""
    config_repo.reset()
    return {"reset": "all", "config": _effective_config()}
