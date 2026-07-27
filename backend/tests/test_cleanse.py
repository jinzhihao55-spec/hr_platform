"""员工类型别名归一化等清洗逻辑测试。"""
import pandas as pd
import pytest

from app.core.exceptions import InclusionFilterError
from app.pipeline.cleansing import cleanse


def test_outsource_maps_to_labor():
    df = pd.DataFrame([
        {"员工类型": "外包", "工号": "E1"},
        {"员工类型": "正式员工", "工号": "E2"},
    ])
    norm = cleanse.normalize_employee_types(df)
    out, stats = cleanse.filter_inclusion(norm)
    assert stats["kept"] == 2
    assert set(out["员工类型"]) == {"劳务人员", "正式员工"}


def test_unknown_type_still_blocks():
    df = pd.DataFrame([{"员工类型": "未知类型", "工号": "E1"}])
    with pytest.raises(InclusionFilterError):
        cleanse.filter_inclusion(df)
