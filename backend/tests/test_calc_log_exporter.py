"""计算日志导出边界：不得写出人员级在职名单。"""
from datetime import date

from app.pipeline.export.calc_log_exporter import _weekly_trace_lines


def test_weekly_trace_lines_do_not_leak_active_roster():
    """在职 roster（数百工号）没有审计价值且属人员级信息；
    入/离职命中工号保留（解释 Row2/Row3 数字的最小证据）。"""
    ctx = {
        "week_start": date(2026, 7, 6),
        "week_end": date(2026, 7, 10),
        "trace": [{
            "scope": "weekly", "ref": "NINS", "item": "主体×事业部（Sheet2）",
            "headcount": 2, "split": [2, 0, 0],
            "joiners": 1, "leavers": 0,
            "joiners_formal": 1, "leavers_formal": 0,
            "top3": [],
            "source": "s", "formula": "f",
            "hits": {"active": ["AID1", "AID2"], "joiners": ["JID1"], "leavers": []},
        }],
        "cc_rows": [],
        "validations": [],
    }

    text = "\n".join(_weekly_trace_lines(ctx))

    assert "AID1" not in text
    assert "AID2" not in text
    assert "JID1" in text
