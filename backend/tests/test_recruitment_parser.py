from __future__ import annotations

import pandas as pd

from app.pipeline.input.parsers import parse_recruitment


def test_parse_recruitment_preserves_first_row_from_flat_vision_xlsx(tmp_path) -> None:
    path = tmp_path / "recruitment_from_vision.xlsx"
    pd.DataFrame(
        [
            ["Recruiter A", 1, 0, 0, 0, 2, 0, 0, 0, 2],
            ["合计", 1, 0, 0, 0, 2, 0, 0, 0, 2],
        ],
        columns=[
            "招聘专员（网络上海）",
            "当日入职数",
            "当日offer数",
            "当日发offer并在当日接受offer数",
            "当日接受offer总数（前一列+之前offer但在今天接受offer数）",
            "7月已入职人数_已入职确认人数",
            "7月已入职人数_猎头/RPO形式入职客户方正式入职人数",
            "7月待入职人数_7月接受offer在7月即将入职人数",
            "7月待入职人数_6月接受offer在7月即将入职人数",
            "7月已确定入职人数_已入职确认人数+待入职人数",
        ],
    ).to_excel(path, index=False)

    result = parse_recruitment(str(path), report_month=7)

    assert len(result) == 2
    assert result["招聘专员"].tolist() == ["Recruiter A", "合计"]
    assert result["is_total_row"].tolist() == [False, True]
