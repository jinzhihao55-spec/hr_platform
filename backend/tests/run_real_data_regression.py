"""
v1_7.21 真实数据回归测试脚本
============================
运行方式: cd v1_7.21/backend && python tests/run_real_data_regression.py

逐日：上传四源 -> 生成日报 -> 对比预期值 -> 报告差异
最后工作日：生成周报 -> 对比预期值

预期值来自 学生测试集 中各日期的「日报执行说明」和「周报执行说明」。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import requests

# ---------- 配置 ----------
BASE_URL = "http://172.17.60.102:8080"
API_BASE = f"{BASE_URL}/api"
TEST_DATA = Path("/Users/jzh/jzh/2026实习/data/学生测试集")

# 如果有 API_AUTH_TOKEN，在这里填
HEADERS = {}  # {"X-API-Token": "your-token"}

# 测试用日期（工作日，按时间顺序）
TEST_DATES = [
    date(2026, 7, 8),
    date(2026, 7, 9),
    date(2026, 7, 10),
    date(2026, 7, 13),
    date(2026, 7, 14),
    date(2026, 7, 15),
    date(2026, 7, 16),
    date(2026, 7, 17),
    date(2026, 7, 20),
]

# 预期值（来自各日报执行说明）
EXPECTED_DAILY = {
    date(2026,7,8):  {2:0,3:3,4:2,5:0,7:-3,8:26,9:5,12:21,13:185,14:128,17:57,30:0,31:4,32:3,33:7,37:26,38:0,39:0,40:26,18:26,19:7,22:19},
    date(2026,7,9):  {2:0,3:0,4:0,5:0,7:0,8:26,9:5,12:21,13:185,14:128,17:57,30:0,31:4,32:3,33:7,37:26,38:0,39:0,40:26,18:26,19:7,22:19},
    date(2026,7,10): {2:0,3:0,4:0,5:0,7:0,8:26,9:5,12:21,13:185,14:128,17:57,30:0,31:4,32:3,33:7,37:26,38:0,39:7,40:33,18:33,19:7,22:26},
    date(2026,7,13): {2:12,3:0,4:0,5:0,7:12,8:38,9:5,12:33,13:197,14:128,17:69,30:0,31:4,32:3,33:7,37:38,38:0,39:7,40:45,18:45,19:7,22:38},
    date(2026,7,14): {2:0,3:1,4:1,5:0,7:-1,8:38,9:6,12:32,13:197,14:129,17:68,30:0,31:6,32:2,33:8,37:38,38:0,39:3,40:41,18:41,19:8,22:33},
    date(2026,7,15): {2:1,3:2,4:0,5:0,7:-1,8:39,9:8,12:31,13:198,14:131,17:67,30:0,31:6,32:2,33:8,37:39,38:0,39:3,40:42,18:42,19:8,22:34},
    date(2026,7,16): {2:0,3:0,4:2,5:0,7:0,8:39,9:8,12:31,13:198,14:131,17:67,30:0,31:8,32:2,33:10,37:39,38:0,39:3,40:42,18:42,19:10,22:32},
    date(2026,7,17): {2:0,3:1,4:0,5:0,7:-1,8:39,9:9,12:30,13:198,14:132,17:66,30:0,31:8,32:2,33:10,37:39,38:0,39:3,40:42,18:42,19:10,22:32},
    date(2026,7,20): {2:3,3:3,4:1,5:0,7:0,8:42,9:12,12:30,13:201,14:135,17:66,30:0,31:8,32:2,33:10,37:42,38:0,39:0,40:42,18:42,19:10,22:32},
}

# 周报预期
EXPECTED_WEEKLY = {
    (date(2026,7,6), date(2026,7,10)): {
        "total_headcount": 479,
        "total_joiners": 22,
        "total_leavers": 3,
    },
    (date(2026,7,13), date(2026,7,17)): {
        "total_headcount": 488,
        "total_joiners": 13,
        "total_leavers": 4,
    },
}


def api(path: str, method="GET", **kwargs):
    url = f"{API_BASE}{path}"
    resp = getattr(requests, method.lower())(url, headers=HEADERS, **kwargs)
    return resp


def upload_ingest(report_date: date, data_dir: Path) -> dict:
    """上传四源到旧路径 POST /ingest"""
    d = data_dir / report_date.strftime("%Y-%m-%d")

    employees = d / f"人员表_{report_date.strftime('%Y%m%d')}.xls"
    resignations = d / f"离职人员报表_{report_date.strftime('%Y%m%d')}.xls"

    # 协议签署可能是 png 或 jpg
    agreements = None
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = d / f"协议签署_{report_date.strftime('%Y%m%d')}{ext}"
        if candidate.exists():
            agreements = candidate
            break

    # 招聘数据通常是 png
    recruitment = None
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = d / f"招聘数据_{report_date.strftime('%Y%m%d')}{ext}"
        if candidate.exists():
            recruitment = candidate
            break

    files = {}
    if employees.exists():
        files["employees"] = (employees.name, open(employees, "rb"),
                              "application/vnd.ms-excel")
    if resignations.exists():
        files["resignations"] = (resignations.name, open(resignations, "rb"),
                                 "application/vnd.ms-excel")
    if agreements and agreements.exists():
        mime = "image/png" if agreements.suffix == ".png" else "image/jpeg"
        files["agreements"] = (agreements.name, open(agreements, "rb"), mime)
    if recruitment and recruitment.exists():
        mime = "image/png" if recruitment.suffix == ".png" else "image/jpeg"
        files["recruitment"] = (recruitment.name, open(recruitment, "rb"), mime)

    data = {"report_date": report_date.isoformat()}

    print(f"\n--- 上传 {report_date} ---")
    print(f"  人员表: {employees.name if employees.exists() else 'MISSING'}")
    print(f"  离职报表: {resignations.name if resignations.exists() else 'MISSING'}")
    print(f"  协议签署: {agreements.name if agreements else 'MISSING'}")
    print(f"  招聘数据: {recruitment.name if recruitment else 'MISSING'}")

    # 图像文件需要特殊处理：先尝试 combined 模式
    use_combined = False
    if (not (employees.exists() and resignations.exists())
            or (agreements and not agreements.suffix.startswith(".xls" if False else ".xls"))
            or (recruitment and not recruitment.suffix.startswith(".xls" if False else ".xls"))):
        pass  # 直接用 POST /ingest

    resp = requests.post(f"{API_BASE}/ingest", data=data, files=files,
                        headers=HEADERS)

    # 清理文件句柄
    for f in files.values():
        f[1].close()

    return resp.json()


def generate_daily(report_date: date) -> dict:
    """POST /reports/daily 生成日报"""
    resp = requests.post(f"{API_BASE}/reports/daily", json={
        "report_date": report_date.isoformat()
    }, headers=HEADERS)
    return resp.json()


def get_daily_view(report_date: date) -> dict:
    """GET /reports/daily/{date}/view 获取日报结构化数据"""
    resp = requests.get(f"{API_BASE}/reports/daily/{report_date.isoformat()}/view",
                       headers=HEADERS)
    return resp.json()


def verify_daily(report_date: date, view: dict) -> list[str]:
    """对比实际值与预期值"""
    expected = EXPECTED_DAILY.get(report_date, {})
    rows = view.get("rows", {})
    errors = []

    for row_num, expected_val in sorted(expected.items()):
        row_data = rows.get(str(row_num), {})
        actual_val = row_data.get("value")
        if actual_val != expected_val:
            errors.append(
                f"  Row{row_num}: expected={expected_val}, actual={actual_val}"
            )

    # 检查硬阻断校验
    validations = view.get("validations", [])
    hard_fails = [v for v in validations
                  if v.get("hard_block") and not v.get("passed")]
    for v in hard_fails:
        errors.append(f"  [HARD BLOCK] {v.get('check')}")

    return errors


def main():
    print("=" * 60)
    print("v1_7.21 真实数据回归测试")
    print("=" * 60)

    # 健康检查
    print("\n--- 健康检查 ---")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"  服务状态: {resp.status_code} {resp.json()}")
    except Exception as e:
        print(f"  服务不可达: {e}")
        print("  请确保服务端已启动 (http://172.17.60.102:8080)")
        sys.exit(1)

    all_errors = {}

    # 逐日测试
    for report_date in TEST_DATES:
        d = TEST_DATA / report_date.strftime("%Y-%m-%d")
        if not d.exists():
            print(f"\n  [SKIP] {report_date}: 测试数据目录不存在")
            continue

        # 1. 上传四源
        ingest_result = upload_ingest(report_date, TEST_DATA)
        status = ingest_result.get("status", "unknown")
        print(f"  入库状态: {status}")
        if status == "needs_clarification":
            print(f"  需要澄清: {ingest_result.get('error', {}).get('message', '')}")
            # 记录但继续尝试生成（如果只是 inclusion_filter 的问题）
            if "unknown_types" in str(ingest_result.get("error", {})):
                print("  纳入口径存在未知类型，尝试继续...")
            else:
                all_errors[str(report_date)] = [f"INGEST: {status}"]
                continue

        # 2. 生成日报
        gen_result = generate_daily(report_date)
        gen_status = gen_result.get("status", "unknown")
        print(f"  生成状态: {gen_status}")
        if gen_status not in ("succeeded",):
            msg = gen_result.get("error", {}).get("message", str(gen_result))
            print(f"  生成失败: {msg}")
            all_errors[str(report_date)] = [f"GENERATE: {msg}"]
            continue

        # 3. 获取结构化视图
        view = get_daily_view(report_date)
        errors = verify_daily(report_date, view)
        if errors:
            print(f"  [FAIL] {len(errors)} 项不匹配:")
            for e in errors:
                print(e)
            all_errors[str(report_date)] = errors
        else:
            print(f"  [PASS] 所有 Row 值与预期一致")

    # 周报测试（只测 W28 和 W29 两个窗口）
    print("\n--- 周报测试 ---")
    weekly_tests = [
        (date(2026, 7, 6), date(2026, 7, 10), "W28"),
        (date(2026, 7, 13), date(2026, 7, 17), "W29"),
    ]
    for week_start, week_end, label in weekly_tests:
        resp = requests.get(
            f"{API_BASE}/reports/weekly/{week_end.isoformat()}/view",
            params={"week_start": week_start.isoformat()},
            headers=HEADERS,
        )
        if resp.status_code != 200:
            print(f"  {label}: 获取失败 {resp.status_code}")
            continue

        data = resp.json()
        actual_total = sum(r["headcount"] for r in data.get("main_rows", []))
        actual_joiners = sum(r["joiners"] for r in data.get("main_rows", []))
        actual_leavers = sum(r["leavers"] for r in data.get("main_rows", []))

        key = (week_start, week_end)
        expected = EXPECTED_WEEKLY.get(key, {})
        errors = []
        if actual_total != expected.get("total_headcount", actual_total):
            errors.append(f"total_headcount: expected={expected['total_headcount']}, actual={actual_total}")
        if actual_joiners != expected.get("total_joiners", actual_joiners):
            errors.append(f"total_joiners: expected={expected['total_joiners']}, actual={actual_joiners}")
        if actual_leavers != expected.get("total_leavers", actual_leavers):
            errors.append(f"total_leavers: expected={expected['total_leavers']}, actual={actual_leavers}")

        if errors:
            print(f"  {label} [FAIL]:")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"  {label} [PASS]: 在职{actual_total} 入职{actual_joiners} 离职{actual_leavers}")

    # 汇总
    print("\n" + "=" * 60)
    total_dates = len(TEST_DATES)
    failed_dates = len(all_errors)
    print(f"已测试 {total_dates} 个日期, {failed_dates} 个失败")
    if all_errors:
        print("\n失败详情:")
        for date_str, errs in all_errors.items():
            print(f"  {date_str}:")
            for e in errs:
                print(f"    {e}")
    else:
        print("所有测试通过!")

    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
