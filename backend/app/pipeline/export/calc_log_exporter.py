"""计算日志（交付物 C，§7）导出 -> Markdown。逐行 trace + 校验结果。"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


_WEEKLY_SECTION_HEADERS = (
    "## 周报逐行 trace（Sheet2 主体×事业部）",
    "## 周报逐行 trace（Sheet1 成本中心×项目）",
    "## 周报校验清单",
)


def _fmt_ids(ids: Any) -> str:
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if not ids:
        return "—"
    if len(ids) > 20:
        return "、".join(ids[:20]) + f" …（共 {len(ids)}）"
    return "、".join(ids)


def _weekly_trace_lines(weekly_ctx: dict[str, Any]) -> list[str]:
    week_start = weekly_ctx.get("week_start")
    week_end = weekly_ctx.get("week_end")
    ws = week_start.isoformat() if isinstance(week_start, date) else week_start
    we = week_end.isoformat() if isinstance(week_end, date) else week_end

    lines = [
        "## 周报逐行 trace（Sheet2 主体×事业部）",
        f"- 统计窗口：{ws} ~ {we}",
        f"- 报告时点（窗口结束日）：{we}",
        "",
    ]
    for t in weekly_ctx.get("trace", []):
        bu = t.get("ref", "")
        split = t.get("split") or []
        formal, intern, labor = (split + [None, None, None])[:3]
        top3 = t.get("top3") or []
        top3_txt = "、".join(f"{p.get('name')}({p.get('count')})" for p in top3) or "—"
        # 导出边界脱敏：在职 roster 是数百人的人员级名单、无审计价值，
        # 只保留解释 Row2/Row3 数字所需的入/离职命中工号。
        hits = {k: v for k, v in (t.get("hits") or {}).items() if k != "active"}
        lines += [
            f"### {bu}",
            f"- 输入源：{t.get('source', '人员表（窗口结束日在职快照）')}",
            f"- 公式：{t.get('formula', '—')}",
            f"- 在职总数：{t.get('headcount')}（正式={formal} / 实习={intern} / 劳务={labor}）",
            f"- 本周入职：{t.get('joiners')}（正式={t.get('joiners_formal', '—')}）",
            f"- 本周离职：{t.get('leavers')}（正式={t.get('leavers_formal', '—')}）",
            f"- 前三项目：{top3_txt}",
        ]
        if hits:
            lines.append(
                f"- 命中工号：入职={_fmt_ids(hits.get('joiners'))}；"
                f"离职={_fmt_ids(hits.get('leavers'))}"
            )
        redacted = {**t, "hits": hits} if t.get("hits") else t
        lines += [
            "```json",
            json.dumps(redacted, ensure_ascii=False, indent=2, default=str),
            "```",
            "",
        ]

    lines += ["## 周报逐行 trace（Sheet1 成本中心×项目）", ""]
    cc_rows = weekly_ctx.get("cc_rows") or []
    for r in cc_rows:
        proj = r.get("project") or r.get("cost_center") or "—"
        hits = r.get("hits") or {}
        lines += [
            f"### {proj}",
            f"- 成本中心：{r.get('cost_center', '—')}",
            f"- 输入源：{r.get('source', '人员表（按项目归集）')}",
            f"- 公式：{r.get('formula', '—')}",
            f"- 在职人数：{r.get('headcount')}",
            f"- 本周入职：{r.get('joiners')}",
            f"- 本周离职：{r.get('leavers')}",
        ]
        if hits:
            lines.append(
                f"- 命中工号：入职={_fmt_ids(hits.get('joiners'))}；"
                f"离职={_fmt_ids(hits.get('leavers'))}"
            )
        lines += [
            "```json",
            json.dumps(r, ensure_ascii=False, indent=2, default=str),
            "```",
            "",
        ]

    lines += ["## 周报校验清单", ""]
    weekly_vals = weekly_ctx.get("validations") or []
    if not weekly_vals:
        lines.append("- （无周报校验项）")
    else:
        for v in weekly_vals:
            mark = "✅" if v["passed"] else ("❌(硬阻断)" if v.get("hard_block") else "⚠️")
            lines.append(f"- {mark} {v['check']}")
    lines.append("")
    return lines


def _strip_weekly_sections(text: str) -> str:
    for header in _WEEKLY_SECTION_HEADERS:
        pattern = re.compile(
            rf"^{re.escape(header)}.*?(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        text = pattern.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.rstrip() + "\n"


def _insert_weekly_sections(text: str, weekly_lines: list[str]) -> str:
    text = _strip_weekly_sections(text)
    marker = "## 发布前校验清单（日报）"
    block = "\n".join(weekly_lines).rstrip() + "\n\n"
    for m in (marker, "## 发布前校验清单（§5）", "## 发布前校验清单"):
        if m in text:
            return text.replace(m, block + m, 1)
    return text.rstrip() + "\n\n" + block


def merge_weekly_into_calc_log(weekly_ctx: dict[str, Any], out_dir: str) -> str:
    """将周报 trace 合并进 week_end 对应日的计算日志 md（独立生成周报时调用）。"""
    week_end: date = weekly_ctx["week_end"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"计算日志_{week_end.isoformat()}.md"
    weekly_lines = _weekly_trace_lines(weekly_ctx)

    if path.exists():
        text = path.read_text(encoding="utf-8")
        text = _insert_weekly_sections(text, weekly_lines)
    else:
        week_start = weekly_ctx.get("week_start")
        ws = week_start.isoformat() if isinstance(week_start, date) else week_start
        we = week_end.isoformat()
        text = "\n".join([
            f"# 计算日志 {we}",
            "",
            "## 运行元信息",
            f"- 报告日期：{we}",
            f"- 周报窗口：{ws} ~ {we}",
            f"- 是否出周报：是（独立生成）",
            "",
        ]) + "\n".join(weekly_lines)

    path.write_text(text, encoding="utf-8")
    return str(path)


def export_calc_log(
    ctx: dict,
    tenure: dict,
    validations: list[dict],
    out_dir: str,
    *,
    weekly_ctx: dict[str, Any] | None = None,
) -> str:
    report_date: date = ctx["report_date"]
    lines = [
        f"# 计算日志 {report_date.isoformat()}",
        "",
        "## 运行元信息",
        f"- 报告日期：{report_date.isoformat()}",
        f"- 基线日期（昨日已验收日报）：{ctx.get('baseline_date')}",
        f"- run_id：{ctx.get('run_id')}",
    ]
    if weekly_ctx:
        ws = weekly_ctx.get("week_start")
        we = weekly_ctx.get("week_end")
        ws_s = ws.isoformat() if isinstance(ws, date) else ws
        we_s = we.isoformat() if isinstance(we, date) else we
        lines.append(f"- 是否出周报：是")
        lines.append(f"- 周报窗口：{ws_s} ~ {we_s}")
    else:
        lines.append("- 是否出周报：否")
    lines.append("")

    lines += ["## 日报逐行 trace（Row2–Row40）"]
    for t in ctx.get("trace", []):
        lines.append(f"### {t.get('ref')} {t.get('item','')}")
        lines.append("```json")
        lines.append(json.dumps(t, ensure_ascii=False, indent=2, default=str))
        lines.append("```")

    lines += ["", "## 在岗时长逐 BU trace"]
    for r in tenure.get("rows", []):
        slot = r.get("slot", "")
        prefix = f"{slot} " if slot else ""
        lines.append(
            f"- {prefix}{r['business_unit']}: YTD离职={r['ytd_leavers']}, "
            f"平均在职(年)={r['avg_tenure_years']}"
        )
    lines.append(f"- 合计 B10 = {tenure.get('b10')}")
    if tenure.get("unmapped_bu"):
        lines.append(f"- 未映射事业部记录数 = {len(tenure['unmapped_bu'])}")

    if weekly_ctx:
        lines.append("")
        lines.extend(_weekly_trace_lines(weekly_ctx))

    lines += ["", "## 发布前校验清单（日报）"]
    for v in validations:
        mark = "✅" if v["passed"] else ("❌(硬阻断)" if v.get("hard_block") else "⚠️")
        lines.append(f"- {mark} {v['check']}")

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(out_dir) / f"计算日志_{report_date.isoformat()}.md")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path
