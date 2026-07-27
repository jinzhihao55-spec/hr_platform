"""多 sheet 合一工作簿：识别四类 sheet 并拆成临时单表文件。

供 ingestion / CLI 在「输入合集.xlsx」场景下复用既有 parsers（单表路径）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# sheet 名关键词 → ingestion 源键（与 ingestion_service.SOURCE_KEYS 一致）
# 顺序重要：更具体的模式放前面（如「离职人员」先于「人员」）
SHEET_PATTERNS: list[tuple[str, list[str]]] = [
    ("resignations", ["离职人员", "离职报表", "resignation"]),
    ("employees", ["人员表", "personnel", "employee"]),
    ("agreements", ["协议签署", "协议", "release", "oa"]),
    ("recruitment", ["招聘数据", "招聘", "recruitment"]),
]

# 拆分写出时使用的 canonical sheet 名（与 parsers 默认读取一致）
CANONICAL_SHEET: dict[str, str] = {
    "employees": "人员表",
    "resignations": "离职人员报表",
    "agreements": "协议签署",
    "recruitment": "招聘数据",
}

# 单文件上传时按文件名猜测（非合一工作簿）
FILE_PATTERNS: dict[str, list[str]] = {
    "employees": ["人员", "personnel", "employee"],
    "resignations": ["离职", "resignation"],
    "agreements": ["oa", "协议", "release"],
    "recruitment": ["招聘", "recruitment"],
}


def guess_source_key(name: str, patterns: list[tuple[str, list[str]]] | None = None) -> str | None:
    lower = name.lower()
    items = patterns or SHEET_PATTERNS
    for source_key, keywords in items:
        if any(k.lower() in lower for k in keywords):
            return source_key
    return None


def is_combined_workbook(path: str | Path) -> bool:
    """至少匹配 2 个不同源 sheet 则视为合一工作簿。"""
    p = Path(path)
    if p.suffix.lower() not in {".xlsx", ".xls"}:
        return False
    xl = pd.ExcelFile(p)
    if len(xl.sheet_names) < 2:
        return False
    matched = {guess_source_key(s) for s in xl.sheet_names}
    matched.discard(None)
    return len(matched) >= 2


def split_combined_workbook(path: str | Path, out_dir: str | Path) -> dict[str, str]:
    """
    将合一 xlsx 按 sheet 拆成临时单表文件。
    返回 {employees|resignations|agreements|recruitment: 临时路径}。
    """
    p = Path(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    xl = pd.ExcelFile(p)
    result: dict[str, str] = {}

    for sheet in xl.sheet_names:
        source_key = guess_source_key(sheet)
        if not source_key or source_key in result:
            continue
        df = pd.read_excel(p, sheet_name=sheet, dtype=object)
        dest = out / f"{source_key}.xlsx"
        sheet_name = CANONICAL_SHEET.get(source_key, sheet)
        with pd.ExcelWriter(dest, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        result[source_key] = str(dest)

    return result


def expand_provided_files(provided: dict[str, str], work_dir: str | Path) -> dict[str, str]:
    """
    扫描已落盘的 provided 路径；若发现合一工作簿则拆分并合并进 provided。
    合一文件所在键会被移除，由拆分后的各源键替代。
    """
    expanded = dict(provided)
    work = Path(work_dir)

    for key, fpath in list(provided.items()):
        if not is_combined_workbook(fpath):
            continue
        split_dir = work / f"split_{key}"
        split = split_combined_workbook(fpath, split_dir)
        del expanded[key]
        for sk, sp in split.items():
            expanded[sk] = sp

    return expanded
