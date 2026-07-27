"""input_spec §0.1：人员表/离职报表截图须人工确认，未确认时禁止自动入库。"""
from datetime import date

import pandas as pd
import pytest

from app.agents.extraction_agent import ExtractionAgent
from app.core.exceptions import InputMissingError
from app.pipeline.input import image_parser


@pytest.mark.parametrize("source", ["employees", "resignations"])
def test_personnel_screenshots_are_rejected_fail_closed(source, tmp_path):
    image = tmp_path / f"{source}.png"
    image.write_bytes(b"fake-png")

    with pytest.raises(InputMissingError) as exc_info:
        ExtractionAgent().run(object(), date(2026, 7, 10), {source: str(image)})

    assert "人工确认" in exc_info.value.message
    assert exc_info.value.detail.get("code") == "ocr_review_required"


def test_agreement_screenshot_still_goes_through_vision(monkeypatch, tmp_path):
    """③④（OA/招聘）截图不受人工确认门禁影响，仍走视觉链路。"""
    image = tmp_path / "agreements.png"
    image.write_bytes(b"fake-png")
    called: dict[str, str] = {}

    def fake_convert(path, table_type, _tmp):
        called["table_type"] = table_type
        raise ValueError("stop-here")

    monkeypatch.setattr(image_parser, "convert_to_xlsx", fake_convert)

    with pytest.raises(InputMissingError) as exc_info:
        ExtractionAgent().run(object(), date(2026, 7, 10), {"agreements": str(image)})

    assert called["table_type"] == "agreements"
    assert "图像识别失败" in exc_info.value.message


def test_oa_lwd_flags_follow_q5_without_overwriting_explicit_values():
    frame = pd.DataFrame(
        [
            {"最后工作日": "2026-07-31", "计入Row5": None, "计入Row30": None},
            {"最后工作日": "2026-08-03", "计入Row5": None, "计入Row30": None},
            {"最后工作日": "2026-07-31", "计入Row5": "否", "计入Row30": "否"},
        ]
    )

    result = ExtractionAgent()._apply_oa_lwd_flags(frame, date(2026, 7, 16))

    assert result.loc[0, ["计入Row5", "计入Row30"]].tolist() == ["是", "是"]
    assert result.loc[1, ["计入Row5", "计入Row30"]].tolist() == ["是", "否"]
    assert result.loc[2, ["计入Row5", "计入Row30"]].tolist() == ["否", "否"]
