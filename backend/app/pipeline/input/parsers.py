"""Input Layer（§3.1）：接收文件 -> 解析 Excel（4 类源）-> 标准 DataFrame。

纯确定性 pandas，无模型参与。表头与模板不符时抛 SchemaMismatchError（流水线停下提问）。"""
from __future__ import annotations

import re

import pandas as pd

from app.core.exceptions import SchemaMismatchError
from app.pipeline.input import header_map as hm
from app.pipeline.input.canonical_projection import (
    project_personnel_frame,
    project_resignation_frame,
)

# 招聘数据动态月份列，如 "5月接受offer在6月即将入职"（捕获 offer月、join月）
_OFFER_RE = re.compile(r"(\d+)月接受offer在(\d+)月即将入职")


def _read(path: str, sheet=0) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, dtype=object)


def parse_employees(path: str) -> pd.DataFrame:
    df = _read(path)
    lk = hm.build_lookup(list(df.columns), hm.EMPLOYEE_HEADERS)
    required = {"员工类型", "工号", "员工状态", "事业部编号"}
    missing = required - set(lk)
    if missing:
        raise SchemaMismatchError(
            f"人员表缺少关键表头: {missing}", detail={"found": list(df.columns)}
        )
    out = df.rename(columns={v: k for k, v in lk.items()})
    # 去掉模板说明行（"仅表头模板..."）
    out = out[~out["工号"].astype(str).str.contains("仅表头模板", na=False)]
    out = project_personnel_frame(out)
    return out.dropna(how="all").reset_index(drop=True)


def parse_resignations(path: str) -> pd.DataFrame:
    df = _read(path)
    lk = hm.build_lookup(list(df.columns), hm.RESIGNATION_HEADERS)
    required = {"流程单号", "流程状态", "离职方式"}
    missing = required - set(lk)
    if missing:
        raise SchemaMismatchError(
            f"离职人员报表缺少关键表头: {missing}", detail={"found": list(df.columns)}
        )
    out = df.rename(columns={v: k for k, v in lk.items()})
    out = out[~out["流程单号"].astype(str).str.contains("仅表头模板", na=False)]
    out = project_resignation_frame(out)
    return out.dropna(how="all").reset_index(drop=True)


def _read_sheet(path: str, sheet_names: list[str | int]) -> pd.DataFrame:
    """按序尝试 sheet 名，均失败则用第一个 sheet。"""
    last_err: Exception | None = None
    for sn in sheet_names:
        try:
            return pd.read_excel(path, sheet_name=sn, dtype=object)
        except Exception as e:
            last_err = e
    if last_err:
        return pd.read_excel(path, sheet_name=0, dtype=object)
    return pd.read_excel(path, dtype=object)


def parse_agreements(path: str) -> pd.DataFrame:
    # OA：协议签署 / 协议签署Release 等
    df = _read_sheet(path, ["协议签署", "协议签署Release", "Release", 0])
    lk = hm.build_lookup(list(df.columns), hm.AGREEMENT_HEADERS)
    required = {"单号"}
    missing = required - set(lk)
    if missing:
        raise SchemaMismatchError(
            f"协议签署/OA 缺少关键表头: {missing}", detail={"found": list(df.columns)}
        )
    out = df.rename(columns={v: k for k, v in lk.items()})
    return out.dropna(how="all").reset_index(drop=True)


def _read_recruitment_df(path: str) -> pd.DataFrame:
    """读取招聘 sheet；兼容视觉模型扁平表头与原始 Excel 双层表头。"""
    for sheet in ("招聘数据", 0):
        try:
            flat_df = pd.read_excel(path, sheet_name=sheet, header=0, dtype=object)
            flat_columns = [hm.normalize(str(column)) for column in flat_df.columns]
            has_recruiter = any("招聘专员" in column for column in flat_columns)
            has_dynamic_offer = any(
                _OFFER_RE.search(column.replace("\n", ""))
                for column in flat_columns
            )
            if has_recruiter and has_dynamic_offer:
                flat_df.columns = flat_columns
                return flat_df.dropna(how="all").reset_index(drop=True)
        except Exception:
            pass

        try:
            df = pd.read_excel(path, sheet_name=sheet, header=[0, 1], dtype=object)
            flat = []
            for parts in df.columns:
                segs = []
                for p in parts:
                    s = str(p).strip()
                    if not s or s.lower().startswith("unnamed") or s == "nan":
                        continue
                    segs.append(hm.normalize(s))
                flat.append(" ".join(segs) if segs else hm.normalize(str(parts[-1])))
            df.columns = flat
            return df.dropna(how="all").reset_index(drop=True)
        except Exception:
            continue
    return _read(path)


def _match_offer_columns(cols: list[str], target: int) -> tuple[str | None, str | None]:
    """识别 Row38/39 动态月份列（offer月 → join月=target）。"""
    prev_month = 12 if target == 1 else target - 1
    prev_col = curr_col = None
    for c in cols:
        nc = hm.normalize(c)
        m = _OFFER_RE.search(nc.replace("\n", ""))
        if not m:
            continue
        offer_m, join_m = int(m.group(1)), int(m.group(2))
        if join_m != target:
            continue
        if offer_m == target:
            curr_col = c
        elif offer_m == prev_month:
            prev_col = c
    return prev_col, curr_col


def parse_recruitment(path: str, report_month: int) -> pd.DataFrame:
    """招聘数据：按表头识别动态月份列（不依赖固定列字母，§1.1 ④）。

    report_month：报告月份(1-12)，用于识别"当月 offer 当月入职""上月 offer 当月入职"。
    返回规范化后的 frame：招聘专员、is_total_row、
    上月接受offer当月预计入职、当月接受offer当月预计入职，并保留原始列。
    """
    df = _read_recruitment_df(path)

    cols = [hm.normalize(str(c)) for c in df.columns]
    col_map = dict(zip(cols, df.columns))

    matched_join = set()
    for c in cols:
        m = _OFFER_RE.search(c.replace("\n", ""))
        if m:
            matched_join.add(int(m.group(2)))

    if report_month in matched_join:
        target = report_month
    elif matched_join:
        target = max(matched_join)
    else:
        target = report_month

    prev_key, curr_key = _match_offer_columns(cols, target)
    prev_col = col_map.get(prev_key) if prev_key else None
    curr_col = col_map.get(curr_key) if curr_key else None

    onboard_col = None
    for c in cols:
        if "待入职" in c or "offer" in c.lower():
            continue
        if "已入职" not in c:
            continue
        if f"{target}月" in c or "已入职邀约" in c or "已入职确认" in c:
            onboard_col = col_map[c]
            break

    recruiter_col = next((col_map[c] for c in cols if "招聘专员" in c), None)

    rows = []
    for _, r in df.iterrows():
        recruiter = r.get(recruiter_col) if recruiter_col else None
        rtext = str(recruiter or "")
        if rtext.strip() == "" or "仅表头模板" in rtext:
            continue
        is_total = ("合计" in rtext) or ("总计" in rtext)
        if not is_total and re.search(r"\d\s+\d\s+\d", rtext):
            continue  # OCR 误识别整行数据为专员名
        rows.append(
            {
                "招聘专员": recruiter,
                "is_total_row": is_total,
                "当月已入职总数": r.get(onboard_col) if onboard_col else None,
                "上月接受offer当月预计入职": r.get(prev_col) if prev_col else None,
                "当月接受offer当月预计入职": r.get(curr_col) if curr_col else None,
                "_raw": {str(k): r.get(k) for k in cols},
            }
        )
    return pd.DataFrame(rows)
