"""The six agent tools (FR-3.3, FR-3.4) - and the guard that keeps them read-only."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from spendguard.agent.tools import (
    MAX_ROWS,
    ToolBox,
    UnsafeQueryError,
    evaluate_expression,
    validate_sql,
)
from spendguard.config import settings
from spendguard.db.duck import AUDIT_VIEW, HIDDEN_FROM_DETECTORS
from spendguard.eval.injection import InjectionResult

from .conftest import build_db

DAY0 = date(2025, 4, 1)


class FakePolicyIndex:
    """Stands in for the embedding index so tool tests need no model."""

    class _Match:
        def __init__(self, clause_id: str) -> None:
            self.clause_id = clause_id

        def as_dict(self) -> dict[str, Any]:
            return {"clause_id": self.clause_id, "title": "T", "section": "S", "text": "body"}

    def search(self, query: str, k: int = 3) -> list[Any]:
        return [self._Match(f"SG-PP-{i + 1}.0") for i in range(k)]


@pytest.fixture
def box(tmp_path: Path) -> ToolBox:
    rows = [
        {
            "vendor_name": "Sharma Traders",
            "amount": 5_000.0 + i,
            "unit_price": 500.0 + i,
            "quantity": 10.0,
            "txn_date": DAY0 + timedelta(days=i * 3),
            "invoice_no": f"INV-{i:05d}",
            "item_category": "Paper",
            "item_desc": "A4 Paper Ream",
        }
        for i in range(40)
    ]
    return ToolBox(build_db(tmp_path / "t.duckdb", rows), policy_index=FakePolicyIndex())


# ---------------------------------------------------------------- the SQL guard


def test_a_plain_select_is_allowed() -> None:
    assert validate_sql(f"SELECT row_id FROM {AUDIT_VIEW} WHERE amount > 10;").startswith("SELECT")


def test_a_common_table_expression_is_allowed() -> None:
    validate_sql(f"WITH big AS (SELECT * FROM {AUDIT_VIEW} WHERE amount > 1) SELECT * FROM big")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE transactions",
        "DELETE FROM cases",
        "UPDATE audit_transactions SET amount = 0",
        "INSERT INTO cases VALUES (1)",
        "ATTACH 'other.duckdb'",
        "COPY audit_transactions TO 'out.csv'",
        "PRAGMA database_list",
        "SELECT 1; DELETE FROM cases",
    ],
)
def test_anything_that_is_not_a_read_is_refused(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


@pytest.mark.parametrize("table", ["transactions", "ground_truth", "injection_runs", "cases"])
def test_the_answer_key_and_operational_tables_are_unreachable(table: str) -> None:
    with pytest.raises(UnsafeQueryError, match="audit_transactions"):
        validate_sql(f"SELECT * FROM {table}")


def test_empty_query_is_refused() -> None:
    with pytest.raises(UnsafeQueryError):
        validate_sql("   ")


def test_hidden_columns_are_not_even_in_the_view(box: ToolBox) -> None:
    for column in sorted(HIDDEN_FROM_DETECTORS):
        result = box.run("query_transactions", {"sql": f"SELECT {column} FROM {AUDIT_VIEW}"})
        assert "error" in result, column


# ---------------------------------------------------------------- query_transactions


def test_query_returns_rows(box: ToolBox) -> None:
    result = box.run("query_transactions", {"sql": f"SELECT row_id, amount FROM {AUDIT_VIEW}"})
    assert result["row_count"] > 0
    assert set(result["rows"][0]) == {"row_id", "amount"}


def test_query_is_row_capped(box: ToolBox) -> None:
    """A broad query must not flood the model's context."""
    result = box.run("query_transactions", {"sql": f"SELECT * FROM {AUDIT_VIEW}"})
    assert result["row_count"] <= MAX_ROWS


def test_malformed_sql_returns_an_error_not_an_exception(box: ToolBox) -> None:
    result = box.run("query_transactions", {"sql": "SELECT nonexistent FROM audit_transactions"})
    assert "error" in result and "SQL error" in result["error"]


# ---------------------------------------------------------------- the other tools


def test_vendor_profile(box: ToolBox) -> None:
    profile = box.run("vendor_profile", {"vendor_key": "sharma"})
    assert profile["found"] and profile["transactions"] == 40
    assert profile["by_officer"] and profile["by_category"]


def test_vendor_profile_on_an_unknown_supplier_says_so(box: ToolBox) -> None:
    profile = box.run("vendor_profile", {"vendor_key": "nobody"})
    assert profile["found"] is False and "note" in profile


def test_vendor_profile_recognises_a_fixed_monthly_contract(tmp_path: Path) -> None:
    """The evidence that lets the agent dismiss a duplicate as routine billing."""
    rows = [
        {
            "vendor_name": "Security Services Co",
            "amount": 145_000.0,
            "unit_price": 145_000.0,
            "quantity": 1.0,
            "txn_date": date(2025, 4 + (i % 9), 5),
            "item_desc": "Security Guard Services",
        }
        for i in range(9)
    ]
    box = ToolBox(build_db(tmp_path / "c.duckdb", rows))
    profile = box.run("vendor_profile", {"vendor_key": "security services"})
    assert profile["looks_like_fixed_contract"] is True
    assert profile["recurring_monthly_billing"][0]["months"] >= 6


def test_find_similar_invoices(box: ToolBox) -> None:
    result = box.run("find_similar_invoices", {"row_id": 5, "limit": 4})
    assert result["subject"]["row_id"] == 5
    assert 0 < len(result["same_supplier_within_90_days"]) <= 4


def test_find_similar_invoices_on_a_bad_row_id(box: ToolBox) -> None:
    assert "error" in box.run("find_similar_invoices", {"row_id": 999_999})


def test_policy_lookup_returns_citable_clause_ids(box: ToolBox) -> None:
    result = box.run("policy_lookup", {"query": "splitting purchases", "k": 2})
    assert [c["clause_id"] for c in result["clauses"]] == ["SG-PP-1.0", "SG-PP-2.0"]


def test_benford_stats_needs_enough_data(tmp_path: Path) -> None:
    rows = [{"vendor_name": "Tiny Co", "amount": float(1_000 * i)} for i in range(1, 6)]
    box = ToolBox(build_db(tmp_path / "b.duckdb", rows))
    result = box.run("benford_stats", {"vendor_key": "tiny"})
    assert result["sufficient_data"] is False
    assert str(settings.benford_min_transactions) in result["note"]


def test_benford_stats_reports_peers_and_benford(box: ToolBox) -> None:
    result = box.run("benford_stats", {"vendor_key": "sharma"})
    assert result["sufficient_data"] is True
    assert len(result["digits"]) == 9
    assert result["digits"][0]["benford"] == pytest.approx(0.301, abs=0.001)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [("87450 * 2", 174_900), ("(120000 - 95000) / 95000", 0.2632), ("2 ** 8", 256), ("-5 + 3", -2)],
)
def test_calculator(expression: str, expected: float) -> None:
    assert evaluate_expression(expression) == pytest.approx(expected, abs=0.001)


def test_calculator_strips_currency_and_grouping() -> None:
    assert evaluate_expression("₹2,50,000 - 50000") == pytest.approx(200_000)


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('dir')", "open('x')", "9**999", "amount * 2", "1/0"],
)
def test_calculator_refuses_anything_but_arithmetic(expression: str) -> None:
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError)):
        evaluate_expression(expression)


# ---------------------------------------------------------------- the toolbox


def test_every_tool_exposes_a_valid_schema(box: ToolBox) -> None:
    schemas = box.schemas()
    assert len(schemas) == 6
    for schema in schemas:
        function = schema["function"]
        assert schema["type"] == "function"
        assert function["description"].strip()
        assert function["parameters"]["type"] == "object"
        assert function["parameters"]["required"]
        json.dumps(schema)  # must be serializable for the API call


def test_unknown_tool_is_reported_not_raised(box: ToolBox) -> None:
    assert "error" in box.run("no_such_tool", {})


def test_wrong_arguments_are_reported_not_raised(box: ToolBox) -> None:
    assert "error" in box.run("vendor_profile", {"wrong": "arg"})


def test_calls_are_recorded_for_the_trace(box: ToolBox) -> None:
    box.run("calculator", {"expression": "1 + 1"})
    box.run("vendor_profile", {"vendor_key": "sharma"})
    assert [c["tool"] for c in box.calls] == ["calculator", "vendor_profile"]


def test_tools_work_against_a_real_injected_database(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        box = ToolBox(con, policy_index=FakePolicyIndex())
        result = box.run(
            "query_transactions",
            {
                "sql": f"SELECT row_id, vendor_name, amount FROM {AUDIT_VIEW} ORDER BY row_id LIMIT 5"
            },
        )
    assert result["row_count"] == 5
