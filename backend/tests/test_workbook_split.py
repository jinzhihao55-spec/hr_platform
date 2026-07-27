"""多 sheet 合一工作簿拆分测试。"""
from pathlib import Path

from openpyxl import Workbook

from app.pipeline.input import workbook_split


def _build_fake_combined_workbook(tmp_path: Path) -> Path:
    path = tmp_path / "输入合集_假数据.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = {
        "人员表": ["工号", "员工状态"],
        "离职人员报表": ["流程单号", "流程状态"],
        "协议签署": ["单号", "流程名称"],
        "招聘数据": ["招聘专员", "7月接受offer在7月即将入职人数"],
    }
    for sheet_name, headers in sheets.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(headers)
        sheet.append(["FAKE-001", "假数据"])
    workbook.save(path)
    return path


def test_is_combined_workbook(tmp_path: Path):
    fixture = _build_fake_combined_workbook(tmp_path)
    assert workbook_split.is_combined_workbook(fixture)


def test_split_combined_workbook(tmp_path):
    fixture = _build_fake_combined_workbook(tmp_path)
    split = workbook_split.split_combined_workbook(fixture, tmp_path / "split")
    assert set(split.keys()) == {
        "employees",
        "resignations",
        "agreements",
        "recruitment",
    }
