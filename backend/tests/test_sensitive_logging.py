"""Operational logs must not expose HR values or dataset scale."""

from datetime import date
import json
import logging

import pandas as pd

from app.pipeline.calculation import daily
from app.pipeline.input import image_parser
from app.repositories import input_repo
from app.services import report_service


def _employee_row(employee_no: str, status: str = "在职") -> dict:
    return {
        "工号": employee_no,
        "中文名": "测试员工",
        "员工类型": "正式员工",
        "员工状态": status,
        "入职日期": date(2025, 1, 1),
        "事业部": "测试事业部",
        "事业部编号": "TEST-BU",
        "项目编号": "TEST-P1",
        "项目名称": "测试项目",
    }


def test_daily_logs_omit_recruitment_counts(caplog):
    caplog.set_level(logging.INFO, logger="calc.daily")
    recruitment = pd.DataFrame(
        [
            {"metric": 987654321, "is_total_row": True},
            {"metric": 123456789, "is_total_row": False},
        ]
    )

    daily._recruitment_value(recruitment, "metric")

    assert "987654321" not in caplog.text
    assert "123456789" not in caplog.text


def test_daily_logs_omit_recomputed_baseline_payload(db, caplog):
    caplog.set_level(logging.INFO, logger="calc.daily")

    daily.recompute_chain_baseline(db, date(2026, 7, 7))

    assert "'row8'" not in caplog.text
    assert "'row30'" not in caplog.text


def test_baseline_answer_logs_omit_raw_answer_and_values(db, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="service.report")
    answer = {
        "for_date": "2026-07-07",
        "row8": 987654321,
        "row9": 2,
        "row13": 3,
        "row14": 4,
        "row30": 5,
        "audit_note": "SENSITIVE-BASELINE-ANSWER",
    }
    monkeypatch.setattr(
        report_service.clarify_repo,
        "list_all",
        lambda *_args, **_kwargs: [
            {
                "code": "baseline_missing",
                "status": "answered",
                "answered_at": "1",
                "answer": json.dumps(answer),
            }
        ],
    )

    assert report_service._try_consume_baseline_answer(db, date(2026, 7, 8)) is True

    assert "SENSITIVE-BASELINE-ANSWER" not in caplog.text
    assert "987654321" not in caplog.text


def test_duplicate_snapshot_log_omits_employee_number(db, caplog):
    caplog.set_level(logging.INFO, logger="repo.input")
    employee_no = "SENSITIVE-EMPLOYEE-NUMBER"

    input_repo.upsert_employees(
        db,
        pd.DataFrame([_employee_row(employee_no), _employee_row(employee_no, "离职")]),
        date(2026, 7, 8),
    )

    assert employee_no not in caplog.text


def test_image_logs_omit_filename_and_dataset_dimensions(
    tmp_path, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="pipeline.image_parser")
    image_path = tmp_path / "SENSITIVE-HR-FILENAME.png"
    image_path.write_bytes(b"fake-image")

    class FakeVisionClient:
        vision_enabled = True

        def vision_json_chat(self, **_kwargs):
            return {
                "headers": ["列A"],
                "rows": [{"列A": f"值{index}"} for index in range(37)],
            }

    from app.llm import llm_client

    monkeypatch.setattr(llm_client, "get_llm_client", lambda: FakeVisionClient())
    image_parser.image_to_dataframe(str(image_path), "employees")

    assert image_path.name not in caplog.text
    assert "37 行" not in caplog.text
    assert "37 行 ×" not in caplog.text


def test_image_conversion_log_omits_dataset_dimensions(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="pipeline.image_parser")
    monkeypatch.setattr(
        image_parser,
        "image_to_dataframe",
        lambda *_args: pd.DataFrame([{"列A": index} for index in range(37)]),
    )

    image_parser.convert_to_xlsx("unused.png", "employees", str(tmp_path))

    assert "37 行" not in caplog.text
