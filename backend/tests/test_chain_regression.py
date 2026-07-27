"""真实链式回归的脱敏比较结果。"""

from scripts.run_chain_regression import compare_result


def test_compare_result_reports_only_row_numbers_and_categories():
    result = compare_result(
        actual_rows={2: {"value": 1}, 3: {"value": 0}},
        expected_rows={2: 2, 3: 0},
        actual_tenure_total=8,
        expected_tenure_total=9,
        actual_tenure_rows=[{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 8, "avg_tenure_years": 1.2,
        }],
        expected_tenure_rows=[{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 9, "avg_tenure_years": 1.3,
        }],
        validations=[{
            "check": "synthetic hard failure",
            "passed": False,
            "hard_block": True,
        }],
    )

    assert result == {
        "passed": False,
        "row_mismatches": [{"row": 2, "kind": "value_mismatch"}],
        "tenure_total_match": False,
        "tenure_row_mismatches": [
            {"slot": "BU_A", "kind": "count_mismatch"},
            {"slot": "BU_A", "kind": "average_mismatch"},
        ],
        "hard_failures": ["synthetic hard failure"],
    }
    serialized = str(result)
    assert "actual" not in serialized
    assert "expected" not in serialized


def test_compare_result_passes_when_business_values_match():
    result = compare_result(
        actual_rows={2: {"value": 1}, 3: {"value": 0}},
        expected_rows={2: 1, 3: 0},
        actual_tenure_total=8,
        expected_tenure_total=8,
        actual_tenure_rows=[{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 8, "avg_tenure_years": 1.2,
        }],
        expected_tenure_rows=[{
            "slot": "BU_A", "business_unit": "NBJO",
            "ytd_leavers": 8, "avg_tenure_years": 1.2,
        }],
        validations=[{"check": "ok", "passed": True, "hard_block": True}],
    )

    assert result["passed"] is True
    assert result["row_mismatches"] == []
    assert result["tenure_row_mismatches"] == []
    assert result["hard_failures"] == []
