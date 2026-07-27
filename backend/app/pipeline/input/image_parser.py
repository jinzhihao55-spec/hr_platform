"""图像解析器：将截图 / 图片格式的人事报表转换为标准 DataFrame。

支持两类真实输入图像：
  1. 协议签署_OA假截图_模拟系统页面.png
     —— OA 系统 Web UI 截图（带导航侧边栏 + 筛选表单 + 数据表格）。
  2. 招聘数据_假截图_模拟Excel区域.png
     —— Excel 区域截图，表头占 4 行（合并单元格）+ 数据行 + 合计行。

解析方式：视觉 LLM（需 .env 中 LLM_VISION_API_KEY + LLM_VISION_BASE_URL +
LLM_VISION_MODEL）。未配置时抛 RuntimeError，提示上传 Excel 代替。

（曾尝试本地 PaddleOCR 3.x PP-StructureV3 作为无需 API key 的首选方案，但在实测中
安装/依赖不稳定、且对 OA 截图这类"表单+表格"混合版面的表格提取不可靠，已移除。
如需恢复，可在 git 历史中找回 PPStructureV3 相关代码。）
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.logging import get_logger

log = get_logger("pipeline.image_parser")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}

_MIME: dict[str, str] = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".bmp": "image/bmp",
    ".webp": "image/webp", ".tiff": "image/tiff", ".tif": "image/tiff",
}

# LLM 视觉提示词
_VISION_PROMPTS: dict[str, str] = {
    "employees": (
        "你是人事数据提取助手。图像是人员花名册 Excel 截图。"
        "请提取为 JSON：{\"headers\": [\"列名\",...], \"rows\": [{\"列名\":\"值\",...},...]}。"
        "规则：headers 使用图中实际中文列名；空单元格用 null；忽略仅说明性文字行。"
    ),
    "resignations": (
        "你是人事数据提取助手。图像是离职人员报表 Excel 截图。"
        "请提取为 JSON：{\"headers\": [...], \"rows\": [{...},...]}。"
        "规则：headers 使用图中实际中文列名；空单元格 null；日期保留原始字符串。"
    ),
    "agreements": (
        "你是人事数据提取助手。图像是 OA 系统[流程高级查询]页面截图，"
        "页面包含顶部筛选表单和底部数据列表。"
        "请只提取底部数据表格（忽略侧边导航栏和顶部筛选表单），"
        "输出为 JSON：{\"headers\": [\"任务号\",\"单号\",\"流程名称\",\"创建人\","
        "\"申请时间\",\"当前状态\",\"员工标识\",\"最后工作日\",\"计入Row5\","
        "\"计入Row30\",\"备注\"], \"rows\": [{...},...]}。"
        "规则：图中有的列必须输出；空单元格、短横线「-」用 null；"
        "时间与日期保留原始字符串；不得编造看不见的值。"
    ),
    "recruitment": (
        "你是人事数据提取助手。图像是招聘漏斗统计表截图（常有深绿标题栏+多级表头+黄色合计行）。"
        "请按图中可见列原样提取，多级表头用下划线拼接父子标题，例如："
        "「6月已入职人数_已入职人数总数」「6月待入职人数_6月接受offer但在本月并未入职人数」"
        "「6月待入职人数_5月接受offer在6月即将入职人数」。"
        "输出 JSON：{\"headers\":[完整中文列名...],\"rows\":[{列名:值,...},...]}。"
        "规则：必须保留每位招聘专员行 + 合计行；数值必须与图中单元格一致，禁止估算；"
        "空单元格用 null；备注列原文保留；不得编造看不见的行或数字。"
    ),
}

# OA 截图期望列（缺则打日志，不阻断——图中可能确实没有）
_AGREEMENT_EXPECTED = (
    "单号", "申请时间", "当前状态", "最后工作日", "计入Row5", "计入Row30",
)
_EMPTY_CELL = re.compile(r"^(?:|-|—|－|none|null|nan)$", re.I)


# ──────────────────────────────────────────────────────────────
# 公共 API
# ──────────────────────────────────────────────────────────────

def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def image_to_dataframe(path: str, table_type: str) -> pd.DataFrame:
    """将图像文件解析为 DataFrame（列名为图中原始中文列名）。"""
    p = Path(path)
    log.info("图像解析开始（类型=%s）", table_type)

    from app.llm.llm_client import get_llm_client
    client = get_llm_client()

    if not client.vision_enabled:
        raise RuntimeError(
            f"无法解析图像文件（{p.name}）：视觉 LLM 未配置。\n\n"
            "解决方案：\n"
            "  A. 在 .env 中配置 LLM_VISION_API_KEY + LLM_VISION_BASE_URL + "
            "LLM_VISION_MODEL（默认使用阿里云百炼官方 "
            "qwen3.7-plus）；\n"
            "  B. 或改用 Excel 文件（.xlsx）上传代替图像截图，无需任何额外配置。"
        )

    log.info("使用视觉 LLM 解析图像…")
    try:
        return _extract_with_llm_vision(path, table_type, client)
    except Exception as exc:
        raise RuntimeError(
            f"图像解析失败（{p.name}）：视觉模型未能从图像中提取到有效数据"
            f"（{exc}）。\n\n"
            "请改用 Excel 文件（.xlsx）上传代替此截图/图片（PNG/JPG 等），"
            "以避免视觉识别的不确定性。"
        ) from exc


def convert_to_xlsx(path: str, table_type: str, tmp_dir: str) -> str:
    """将图像解析结果保存为临时 xlsx，返回路径供 parsers.py 正常处理。"""
    df = image_to_dataframe(path, table_type)
    out = Path(tmp_dir) / f"{table_type}_from_image.xlsx"
    df.to_excel(str(out), index=False)
    log.info("图像已转存为临时 xlsx")
    return str(out)


# ──────────────────────────────────────────────────────────────
# 共用后处理
# ──────────────────────────────────────────────────────────────

def _postprocess(df: pd.DataFrame, table_type: str) -> pd.DataFrame:
    """展平 MultiIndex 列、去除全空行/列、统一列名为字符串、归一空值。"""
    if hasattr(df.columns, "levels"):
        new_cols = []
        for col in df.columns:
            parts = [str(s).strip() for s in col
                     if str(s).strip() and "Unnamed" not in str(s) and str(s) != "nan"]
            deduped: list[str] = []
            for p in parts:
                if not deduped or p != deduped[-1]:
                    deduped.append(p)
            new_cols.append("_".join(deduped) if deduped else "")
        df.columns = new_cols
    else:
        df.columns = [
            str(c).strip() if "Unnamed" not in str(c) and str(c) != "nan" else ""
            for c in df.columns
        ]

    if table_type == "recruitment":
        df = _maybe_promote_header_row(df)

    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    df.columns = [c if c else f"col_{i}" for i, c in enumerate(df.columns)]
    df = _normalize_empty_cells(df)
    _warn_missing_columns(df, table_type)
    return df


def _normalize_empty_cells(df: pd.DataFrame) -> pd.DataFrame:
    """把 OCR 常见占位（-、空串、null）统一成真正的空值。"""
    def _cell(v: Any) -> Any:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if _EMPTY_CELL.match(s):
            return None
        return v

    return df.apply(lambda col: col.map(_cell))


def _warn_missing_columns(df: pd.DataFrame, table_type: str) -> None:
    if table_type != "agreements":
        return
    found = {str(c) for c in df.columns}
    missing = [c for c in _AGREEMENT_EXPECTED if c not in found]
    if missing:
        log.warning(
            "OA 截图 OCR 缺少期望列 %s（已提取列=%s）。"
            "缺最后工作日时入库后 row30_flag 可能为空（Q5：只进 Row5）。",
            missing, sorted(found),
        )


def _maybe_promote_header_row(df: pd.DataFrame) -> pd.DataFrame:
    """招聘数据专用：将误入数据区的表头文本行拼入列名后删除。"""
    header_kw = re.compile(r"offer|月|招聘|入职|离职|人数", re.IGNORECASE)
    number_re = re.compile(r"^\d+(\.\d+)?$")

    new_cols: list[str] = list(df.columns)
    rows_to_drop: list[int] = []

    for idx in df.index:
        row_vals = [str(df.iloc[idx, i]).strip() for i in range(len(new_cols))]
        non_empty = [v for v in row_vals if v and v != "nan"]
        if not non_empty:
            continue
        all_non_numeric = all(not number_re.match(v) for v in non_empty)
        has_header_kw = any(header_kw.search(v) for v in non_empty)
        if all_non_numeric and has_header_kw:
            for col_idx, cell in enumerate(row_vals):
                if cell and cell != "nan":
                    cur = new_cols[col_idx]
                    new_cols[col_idx] = f"{cur}_{cell}" if cur and not cur.startswith("col_") else cell
            rows_to_drop.append(idx)
        else:
            break

    if rows_to_drop:
        df = df.drop(index=rows_to_drop).reset_index(drop=True)
        df.columns = new_cols

    return df


# ──────────────────────────────────────────────────────────────
# 视觉 LLM 提取
# ──────────────────────────────────────────────────────────────

def _extract_with_llm_vision(path: str, table_type: str, client: Any) -> pd.DataFrame:
    """视觉 LLM 提取：把图像发给多模态模型，要求按固定 JSON 结构输出表头+数据行。"""
    p = Path(path)
    mime = _MIME.get(p.suffix.lower(), "image/jpeg")
    img_b64 = base64.b64encode(p.read_bytes()).decode()
    prompt = _VISION_PROMPTS.get(table_type, _VISION_PROMPTS["employees"])

    result = client.vision_json_chat(
        system_prompt=prompt,
        image_b64=img_b64,
        image_mime=mime,
    )

    headers: list[str] = result.get("headers") or []
    raw_rows: list[dict] = result.get("rows") or []

    if not headers:
        raise ValueError(
            f"视觉 LLM 未能提取表头（table_type={table_type}，"
            f"文件={p.name}）。请确认图像清晰。"
        )
    if not raw_rows:
        raise ValueError(f"视觉 LLM 未能提取数据行（table_type={table_type}）。")

    df = pd.DataFrame(raw_rows, columns=headers)
    df = _postprocess(df, table_type)
    log.info("视觉 LLM 提取完成")
    return df
