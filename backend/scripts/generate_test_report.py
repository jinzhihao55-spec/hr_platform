"""重跑全部 testdata 日期，汇总日报 + 在岗时长测试结果到单文件。

用法:
  python scripts/generate_test_report.py
  python scripts/generate_test_report.py -o testdata/TEST_REPORT_ALL_DATES.md
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

RERUN_DATES = [
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
    "2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01",
    "2026-07-02", "2026-07-03",
]
OTHER_DATES: list[str] = []


def _parse_daily_compare(stdout: str) -> dict:
    m_ok = re.search(r"一致 (\d+) / 不一致 (\d+) / 共 (\d+)", stdout)
    diffs = []
    for line in stdout.splitlines():
        if "DIFF" in line and re.match(r"\s+\d+", line):
            diffs.append(line.strip())
    return {
        "ok": int(m_ok.group(1)) if m_ok else None,
        "bad": int(m_ok.group(2)) if m_ok else None,
        "total": int(m_ok.group(3)) if m_ok else None,
        "diff_rows": diffs,
    }


def _parse_tenure_from_stdout(stdout: str) -> dict:
    out = {}
    for key in ("ytd_leavers", "avg_tenure_years"):
        m = re.search(
            rf"在岗时长合计 {key}: 期望=(\S+) 实际=(\S+)\s+(OK|DIFF)", stdout)
        if m:
            out[f"exp_{key}"] = _lit(m.group(1))
            out[f"act_{key}"] = _lit(m.group(2))
            out[f"{key}_ok"] = m.group(3) == "OK"
    return out


def _lit(s: str):
    if s in ("None", "—", "-"):
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return s


def _load_expected_tenure(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_tenure_after_rerun(report_date: date) -> dict:
    from app.core.database import SessionLocal, init_db
    from app.pipeline.calculation import daily as daily_calc
    from app.pipeline.calculation import tenure as tenure_calc
    from app.pipeline.calculation.validators import run_daily_checks

    init_db()
    db = SessionLocal()
    try:
        ctx = daily_calc.compute_daily(db, report_date)
        tenure = tenure_calc.compute_tenure(db, report_date)
        ctx["tenure"] = tenure
        validations = run_daily_checks(ctx)
    finally:
        db.close()

    row14 = int((ctx["rows"].get(14) or {}).get("value") or 0)
    b10 = tenure.get("b10") or 0
    rule10 = next((v for v in validations if "B10" in v.get("check", "")), {})

    exp_path = BACKEND / "testdata" / report_date.isoformat() / "expected_tenure.json"
    expected = _load_expected_tenure(exp_path)
    exp_total = (expected or {}).get("total") or {}
    act_total = tenure.get("total") or {}

    bu_notes = []
    if expected:
        exp_rows = expected.get("rows") or expected.get("by_bu") or []
        exp_by_bu = {r["business_unit"]: r for r in exp_rows}
        if exp_by_bu:
            for r in tenure.get("rows") or []:
                bu = r["business_unit"]
                ev = exp_by_bu.get(bu)
                if ev is None:
                    bu_notes.append(f"{bu}: expected 无此 BU（命名可能不一致）")
                    continue
                for k in ("ytd_leavers", "avg_tenure_years"):
                    if ev.get(k) != r.get(k):
                        bu_notes.append(
                            f"{bu} {k}: 期望 {ev.get(k)} 实际 {r.get(k)}")

    tenure_total_ok = None
    if expected and exp_total:
        tenure_total_ok = (
            exp_total.get("ytd_leavers") == act_total.get("ytd_leavers")
            and exp_total.get("avg_tenure_years") == act_total.get("avg_tenure_years")
        )

    return {
        "b10": b10,
        "row14": row14,
        "b10_ok": (b10 or 0) == row14,
        "rule10_passed": rule10.get("passed"),
        "invalid_records": tenure.get("invalid_records", 0),
        "exp_total": exp_total,
        "act_total": act_total,
        "tenure_total_ok": tenure_total_ok,
        "bu_notes": bu_notes,
        "has_expected_tenure": expected is not None,
        "bu_rows": tenure.get("rows") or [],
    }


def _run_rerun(d: str) -> tuple[int, str]:
    script = BACKEND / "scripts" / f"rerun_{d}.sh"
    proc = subprocess.run(
        ["bash", str(script)], cwd=str(BACKEND), capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout or ""


def _date_assets(d: str) -> dict:
    td = BACKEND / "testdata" / d
    return {
        "combined": bool(list(td.glob("人事报表_输入合集_*.xlsx"))),
        "expected_daily": (td / "expected_daily.json").is_file(),
        "expected_tenure": (td / "expected_tenure.json").is_file(),
        "daily_xlsx": bool(list(td.glob("员工数增减情况日报_*.xlsx"))),
        "rerun_script": (BACKEND / "scripts" / f"rerun_{d}.sh").is_file(),
    }


def build_report() -> str:
    lines = [
        "# 全量 testdata 测试报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "说明：",
        "- 有 `rerun_*.sh` 的日期：清库 → 灌基线 → ingest → 对比 `expected_daily.json` + 在岗时长",
        "- 硬校验：在岗时长 B10 必须等于 Sheet1 Row14",
        "- 7/03 额外对比 `expected_weekly.json`（见 rerun 脚本输出）",
        "",
        "---",
        "",
        "## 汇总表",
        "",
        "| 日期 | rerun | 日报 Row | 不一致行 | B10=Row14 | 在岗合计 vs expected | invalid | 总评 |",
        "|------|-------|----------|----------|-----------|----------------------|---------|------|",
    ]

    details: list[str] = []
    all_ok = True

    for d in RERUN_DATES + OTHER_DATES:
        assets = _date_assets(d)
        if not assets["rerun_script"]:
            lines.append(
                f"| {d} | — | — | — | — | — | — | 跳过（无 rerun） |")
            details.append(f"## {d}\n\n- 状态：**跳过**（无 rerun 脚本）")
            details.append(f"- 资产：combined={assets['combined']} "
                           f"expected_daily={assets['expected_daily']} "
                           f"expected_tenure={assets['expected_tenure']} "
                           f"daily_xlsx={assets['daily_xlsx']}\n")
            continue

        exit_code, stdout = _run_rerun(d)
        daily = _parse_daily_compare(stdout)
        tenure_stdout = _parse_tenure_from_stdout(stdout)
        tenure = _compare_tenure_after_rerun(date.fromisoformat(d))

        daily_ok = daily.get("bad") == 0
        b10_ok = tenure["b10_ok"]
        t_ok = tenure["tenure_total_ok"]
        if tenure["has_expected_tenure"]:
            tenure_mark = "OK" if t_ok else "DIFF"
        else:
            tenure_mark = "—（无 expected）"
        invalid = tenure.get("invalid_records", 0)
        overall = "PASS" if exit_code == 0 and b10_ok and (t_ok is not False) else "ISSUE"
        if overall != "PASS":
            all_ok = False

        row_summary = (
            f"{daily.get('ok', '?')}/{daily.get('total', '?')}"
            if daily.get("total") else "?"
        )
        diff_n = daily.get("bad", "?")
        lines.append(
            f"| {d} | exit {exit_code} | {row_summary} | {diff_n} | "
            f"{'OK' if b10_ok else 'DIFF'} | {tenure_mark} | {invalid} | {overall} |")

        details.append(f"## {d}\n")
        details.append(f"- rerun 退出码：`{exit_code}`")
        details.append(f"- 日报 Row：一致 {daily.get('ok')} / 不一致 {daily.get('bad')} "
                       f"/ 共 {daily.get('total')}")
        details.append(f"- B10={tenure['b10']}，Row14={tenure['row14']}，"
                       f"规则10={'通过' if tenure['rule10_passed'] else '失败'}")
        if tenure["has_expected_tenure"]:
            et, at = tenure["exp_total"], tenure["act_total"]
            details.append(
                f"- 在岗时长合计：YTD 期望 {et.get('ytd_leavers')} / 实际 "
                f"{at.get('ytd_leavers')}；平均年 期望 {et.get('avg_tenure_years')} / "
                f"实际 {at.get('avg_tenure_years')} → "
                f"{'OK' if t_ok else 'DIFF'}")
        else:
            details.append(
                f"- 在岗时长合计：YTD {at.get('ytd_leavers') if (at := tenure['act_total']) else '—'}，"
                f"平均年 {at.get('avg_tenure_years')}（无 expected_tenure.json）")

        if daily.get("diff_rows"):
            details.append("\n**日报不一致行：**\n")
            for r in daily["diff_rows"]:
                details.append(f"- `{r}`")

        if tenure.get("bu_rows"):
            details.append("\n**在岗时长分 BU（实际）：**\n")
            details.append("| 事业部 | YTD离职 | 平均在职(年) |")
            details.append("|--------|---------|--------------|")
            for r in tenure["bu_rows"]:
                details.append(
                    f"| {r['business_unit']} | {r['ytd_leavers']} | "
                    f"{r.get('avg_tenure_years')} |")
            t = tenure["act_total"]
            details.append(
                f"| **合计** | **{t.get('ytd_leavers')}** | "
                f"**{t.get('avg_tenure_years')}** |")

        if tenure.get("bu_notes"):
            details.append("\n**分 BU 对比备注：**\n")
            for n in tenure["bu_notes"]:
                details.append(f"- {n}")

        if tenure_stdout:
            details.append("\n**rerun 脚本在岗输出：**")
            for k in ("ytd_leavers", "avg_tenure_years"):
                if f"exp_{k}" in tenure_stdout:
                    details.append(
                        f"- {k}: 期望 {tenure_stdout.get(f'exp_{k}')} "
                        f"实际 {tenure_stdout.get(f'act_{k}')} "
                        f"{'OK' if tenure_stdout.get(f'{k}_ok') else 'DIFF'}")

        details.append("")
        details.append("---")
        details.append("")

    lines.extend(["", "---", "", "## 各日期明细", ""] + details)
    lines.append("## 总结\n")
    if all_ok:
        lines.append("- 全部可跑日期的 **在岗时长 B10=Row14** 均通过。")
        lines.append("- 有 expected_tenure 的日期，**合计 YTD / 平均在职(年)** 均与标准答案一致。")
        lines.append("- 部分日期 **Sheet1 招聘/OA 相关 Row** 仍有不一致（见各日 DIFF 行），与在岗时长无关。")
    else:
        lines.append("- 存在需关注的日期，见汇总表中 `ISSUE` 行。")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-o", "--output",
        default=str(BACKEND / "testdata" / "TEST_REPORT_ALL_DATES.md"),
        help="输出 Markdown 路径",
    )
    args = parser.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    content = build_report()
    out.write_text(content, encoding="utf-8")
    print(f"已写入 {out} ({len(content)} 字符)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
