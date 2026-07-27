"""Input projections retain rule fields and discard unrelated personal data."""

import pandas as pd

from app.pipeline.input.canonical_projection import (
    PERSONNEL_COLUMNS,
    RESIGNATION_COLUMNS,
    project_personnel_frame,
    project_resignation_frame,
)
from app.pipeline.input.parsers import parse_employees, parse_resignations


def test_personnel_projection_keeps_identity_fields_and_drops_unrelated_pii():
    raw = pd.DataFrame(
        [
            {
                "员工类型": "正式员工",
                "工号": "FAKE-E1",
                "中文名": "测试员工",
                "事业部编号": "FAKE-BU1",
                "证件类型": "身份证",
                "证件号": "FAKE-CERT-1",
                "手机号码": "FAKE-PHONE",
                "员工薪资卡号": "FAKE-CARD",
            }
        ]
    )

    projected = project_personnel_frame(raw)

    assert tuple(projected.columns) == tuple(
        column for column in PERSONNEL_COLUMNS if column in raw.columns
    )
    assert projected.loc[0, "证件号"] == "FAKE-CERT-1"
    assert "手机号码" not in projected.columns
    assert "员工薪资卡号" not in projected.columns


def test_resignation_projection_uses_application_time_not_manager_approval():
    raw = pd.DataFrame(
        [
            {
                "流程单号": "FAKE-P1",
                "流程状态": "已完成",
                "离职方式": "主动离职",
                "员工申请时间": "2026-07-08",
                "项目经理通过时间": "2026-07-09",
            }
        ]
    )

    projected = project_resignation_frame(raw)

    assert tuple(projected.columns) == tuple(
        column for column in RESIGNATION_COLUMNS if column in raw.columns
    )
    assert "员工申请时间" in projected.columns
    assert "项目经理通过时间" not in projected.columns


def test_personnel_parser_normalizes_certificate_alias_and_drops_unknown_columns(
    tmp_path,
):
    source = tmp_path / "fake-personnel.xlsx"
    pd.DataFrame(
        [
            {
                "员工类型": "正式员工",
                "工号": "FAKE-E1",
                "员工状态": "在职",
                "事业部编号": "FAKE-BU1",
                "证件号码": "FAKE-CERT-1",
                "私人邮箱": "fake@example.invalid",
            }
        ]
    ).to_excel(source, index=False)

    parsed = parse_employees(str(source))

    assert parsed.loc[0, "证件号"] == "FAKE-CERT-1"
    assert "证件号码" not in parsed.columns
    assert "私人邮箱" not in parsed.columns


def test_resignation_parser_drops_manager_approval_column(tmp_path):
    source = tmp_path / "fake-resignation.xlsx"
    pd.DataFrame(
        [
            {
                "流程单号": "FAKE-P1",
                "流程状态": "已完成",
                "离职方式": "主动离职",
                "员工申请时间": "2026-07-08 10:00:00",
                "项目经理通过时间": "2026-07-09 10:00:00",
            }
        ]
    ).to_excel(source, index=False)

    parsed = parse_resignations(str(source))

    assert parsed.loc[0, "员工申请时间"] == "2026-07-08 10:00:00"
    assert "项目经理通过时间" not in parsed.columns
