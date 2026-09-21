"""The six tools the Investigator uses to gather evidence (FR-3.3, FR-3.4).

    query_transactions     fetch specific rows with SQL, read-only and capped
    vendor_profile         a supplier's history, totals and billing pattern
    find_similar_invoices  comparable transactions around one row
    policy_lookup          the procurement clause that applies, by id
    benford_stats          first-digit distribution for one supplier
    calculator             arithmetic, so figures are computed and not generated

Every tool returns a plain dictionary and **never raises into the agent loop**:
a failure comes back as ``{"error": ...}`` so the model can read it, correct
itself and carry on. Every tool exposes a JSON schema so the model knows how to
call it.

All of them read ``audit_transactions``, the same view the detectors use. The
injection answer key and the operational tables are unreachable from here.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

import duckdb

from spendguard.config import settings
from spendguard.db.duck import AUDIT_FIELDS, AUDIT_VIEW

__all__ = ["MAX_ROWS", "Tool", "ToolBox", "UnsafeQueryError", "evaluate_expression", "validate_sql"]

MAX_ROWS = 50
MAX_RESULT_CHARS = 8_000


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        """OpenAI tool-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# --------------------------------------------------------------------- SQL guard


class UnsafeQueryError(ValueError):
    """The query is not a plain read of the audit view."""


# Anything that writes, attaches, loads or escapes the sandbox.
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "create", "alter", "truncate", "replace",
    "attach", "detach", "copy", "export", "import", "install", "load", "pragma",
    "call", "set", "begin", "commit", "rollback", "grant", "revoke",
)  # fmt: skip

# Tables that exist but must stay invisible: the answer key and operational state.
FORBIDDEN_TABLES = (
    "transactions", "ground_truth", "injection_runs", "eval_results",
    "dataset_cards", "cases", "runs",
)  # fmt: skip

_TABLE_REFERENCE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)
_CTE_NAME = re.compile(r"\b(\w+)\s+as\s*\(", re.IGNORECASE)


def validate_sql(sql: str) -> str:
    """Return the query if it is a single read of the audit view, else raise.

    Defence in depth: the connection is opened read-only as well. This exists so
    the *reason* is legible to the model, and so a leak attempt is refused rather
    than silently returning nothing.
    """
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise UnsafeQueryError("Empty query.")
    if ";" in statement:
        raise UnsafeQueryError("Only one statement at a time.")
    if not re.match(r"^(with|select)\b", statement, re.IGNORECASE):
        raise UnsafeQueryError("Only SELECT queries are allowed.")

    lowered = statement.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise UnsafeQueryError(f"'{keyword}' is not allowed; this tool only reads.")

    defined = {name.lower() for name in _CTE_NAME.findall(statement)}
    for reference in _TABLE_REFERENCE.findall(statement):
        table = reference.split(".")[-1].lower()
        if table in defined:
            continue
        if table != AUDIT_VIEW:
            hint = f" '{table}' is not readable from here." if table in FORBIDDEN_TABLES else ""
            raise UnsafeQueryError(f"Only {AUDIT_VIEW} may be queried.{hint}")
    return statement


# --------------------------------------------------------------------- calculator

_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def evaluate_expression(expression: str) -> float:
    """Arithmetic only. No names, no calls, no attribute access."""
    if len(expression) > 200:
        raise ValueError("Expression too long.")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, int | float):
                raise ValueError("Only numbers are allowed.")
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 8 or abs(left) > 1e6):
                raise ValueError("Exponent too large.")
            return float(_OPERATORS[type(node.op)](left, right))
        raise ValueError("Only + - * / % ** and parentheses are allowed.")

    return walk(ast.parse(expression.replace(",", "").replace("₹", ""), mode="eval"))


# --------------------------------------------------------------------- the toolbox


class ToolBox:
    """The six tools, bound to one read-only connection and the policy index."""

    ROUND_UNIT: ClassVar[float] = 1_000.0

    def __init__(self, con: duckdb.DuckDBPyConnection, policy_index: Any | None = None) -> None:
        self.con = con
        self._policy_index = policy_index
        self.calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------ plumbing

    @property
    def policy(self) -> Any:
        if self._policy_index is None:
            from spendguard.agent.policy import get_policy_index

            self._policy_index = get_policy_index()
        return self._policy_index

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        return self.con.execute(sql, params or []).pl().to_dicts()

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "query_transactions",
                f"Run a read-only SQL SELECT over the {AUDIT_VIEW} view and return rows. "
                f"Columns: {', '.join(AUDIT_FIELDS)}. Use it to fetch specific transactions "
                f"by row_id, supplier or date. At most {MAX_ROWS} rows are returned.",
                {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": f"A single SELECT statement over {AUDIT_VIEW}.",
                        }
                    },
                    "required": ["sql"],
                },
                self.query_transactions,
            ),
            Tool(
                "vendor_profile",
                "A supplier's payment history: totals, first and last seen, officers and "
                "categories billed, and whether the billing looks like a fixed monthly "
                "contract. Use it to judge whether a pattern is routine business.",
                {
                    "type": "object",
                    "properties": {
                        "vendor_key": {
                            "type": "string",
                            "description": "Normalized supplier key, as it appears on a case.",
                        }
                    },
                    "required": ["vendor_key"],
                },
                self.vendor_profile,
            ),
            Tool(
                "find_similar_invoices",
                "Transactions comparable to one row: the same supplier nearby in time, and "
                "the same commodity at a similar amount. Use it to see whether a "
                "transaction is unusual against its own context.",
                {
                    "type": "object",
                    "properties": {
                        "row_id": {"type": "integer", "description": "The row to compare."},
                        "limit": {
                            "type": "integer",
                            "description": f"Rows per list, default 5, max {MAX_ROWS}.",
                        },
                    },
                    "required": ["row_id"],
                },
                self.find_similar_invoices,
            ),
            Tool(
                "policy_lookup",
                "Search the organization's procurement policy and return the clauses that "
                "apply, each with its clause id (for example SG-PP-3.2). Cite the clause id "
                "in any claim about what the policy requires.",
                {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to look up, in plain language.",
                        },
                        "k": {"type": "integer", "description": "How many clauses, default 3."},
                    },
                    "required": ["query"],
                },
                self.policy_lookup,
            ),
            Tool(
                "benford_stats",
                "First-digit distribution of a supplier's invoice amounts, compared with its "
                "peers in the same categories and with Benford's law. Use it to judge whether "
                "amounts look naturally occurring.",
                {
                    "type": "object",
                    "properties": {"vendor_key": {"type": "string"}},
                    "required": ["vendor_key"],
                },
                self.benford_stats,
            ),
            Tool(
                "calculator",
                "Evaluate an arithmetic expression. Use it for every calculation rather than "
                "working the number out yourself.",
                {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "For example '87450 * 2' or '(120000 - 95000) / 95000'.",
                        }
                    },
                    "required": ["expression"],
                },
                self.calculator,
            ),
        ]

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self.tools()]

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name. Never raises: errors come back as data."""
        tool = next((t for t in self.tools() if t.name == name), None)
        if tool is None:
            return {"error": f"No tool named {name!r}. Available: {[t.name for t in self.tools()]}"}
        try:
            result = tool.run(**arguments)
        except TypeError as exc:
            result = {"error": f"Wrong arguments for {name}: {exc}"}
        except Exception as exc:  # a tool failure must not end the investigation
            result = {"error": f"{type(exc).__name__}: {exc}"}
        self.calls.append({"tool": name, "arguments": arguments})
        return result

    # ------------------------------------------------------------ the tools

    def query_transactions(self, sql: str) -> dict[str, Any]:
        try:
            statement = validate_sql(sql)
        except UnsafeQueryError as exc:
            return {"error": str(exc), "sql": sql}
        try:
            rows = self._rows(f"SELECT * FROM ({statement}) LIMIT {MAX_ROWS + 1}")
        except duckdb.Error as exc:
            return {"error": f"SQL error: {exc}", "sql": statement}

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        payload: dict[str, Any] = {"rows": rows, "row_count": len(rows)}
        if truncated:
            payload["note"] = f"Only the first {MAX_ROWS} rows are shown; narrow the query."
        if len(str(payload)) > MAX_RESULT_CHARS:
            payload["rows"] = rows[:10]
            payload["note"] = "Result truncated to 10 rows; select fewer columns."
        return payload

    def vendor_profile(self, vendor_key: str) -> dict[str, Any]:
        summary = self._rows(
            f"""
            SELECT count(*) AS transactions,
                   sum(amount) AS total_amount,
                   min(txn_date) AS first_seen,
                   max(txn_date) AS last_seen,
                   count(DISTINCT amount) AS distinct_amounts,
                   count(DISTINCT officer_id) AS officers,
                   avg(CASE WHEN amount % {self.ROUND_UNIT} = 0 THEN 1.0 ELSE 0.0 END) AS round_share,
                   any_value(vendor_name) AS vendor_name
            FROM {AUDIT_VIEW} WHERE vendor_key = ?
            """,
            [vendor_key],
        )
        if not summary or not summary[0]["transactions"]:
            return {"vendor_key": vendor_key, "found": False, "note": "No transactions."}

        profile = summary[0]
        profile.update(vendor_key=vendor_key, found=True)
        profile["by_officer"] = self._rows(
            f"SELECT officer_id, count(*) AS transactions, sum(amount) AS total FROM {AUDIT_VIEW} "
            "WHERE vendor_key = ? GROUP BY officer_id ORDER BY total DESC LIMIT 5",
            [vendor_key],
        )
        profile["by_category"] = self._rows(
            f"SELECT item_category, count(*) AS transactions, sum(amount) AS total FROM {AUDIT_VIEW} "
            "WHERE vendor_key = ? GROUP BY item_category ORDER BY total DESC LIMIT 5",
            [vendor_key],
        )
        # A fixed monthly contract: one amount recurring across many months. This is
        # what distinguishes routine billing from a duplicated invoice.
        recurring = self._rows(
            f"""
            SELECT amount, count(*) AS invoices,
                   count(DISTINCT date_trunc('month', txn_date)) AS months,
                   any_value(item_desc) AS item
            FROM {AUDIT_VIEW} WHERE vendor_key = ?
            GROUP BY amount HAVING count(DISTINCT date_trunc('month', txn_date)) >= 6
            ORDER BY months DESC LIMIT 3
            """,
            [vendor_key],
        )
        profile["recurring_monthly_billing"] = recurring
        profile["looks_like_fixed_contract"] = bool(recurring)
        return profile

    def find_similar_invoices(self, row_id: int, limit: int = 5) -> dict[str, Any]:
        limit = max(1, min(int(limit), MAX_ROWS))
        subject = self._rows(f"SELECT * FROM {AUDIT_VIEW} WHERE row_id = ?", [row_id])
        if not subject:
            return {"error": f"No transaction with row_id {row_id}."}
        row = subject[0]

        same_supplier = self._rows(
            f"""
            SELECT row_id, vendor_name, invoice_no, amount, txn_date, officer_id, item_desc
            FROM {AUDIT_VIEW}
            WHERE vendor_key = ? AND row_id <> ?
              AND abs(date_diff('day', txn_date, ?)) <= 90
            ORDER BY abs(date_diff('day', txn_date, ?)), row_id LIMIT ?
            """,
            [row["vendor_key"], row_id, row["txn_date"], row["txn_date"], limit],
        )
        same_commodity = (
            self._rows(
                f"""
                SELECT row_id, vendor_name, amount, unit_price, quantity, txn_date
                FROM {AUDIT_VIEW}
                WHERE item_category = ? AND row_id <> ? AND unit_price IS NOT NULL
                ORDER BY abs(unit_price - ?), row_id LIMIT ?
                """,
                [row["item_category"], row_id, row["unit_price"] or 0, limit],
            )
            if row["item_category"]
            else []
        )
        return {
            "subject": row,
            "same_supplier_within_90_days": same_supplier,
            "same_commodity_closest_unit_price": same_commodity,
        }

    def policy_lookup(self, query: str, k: int = 3) -> dict[str, Any]:
        matches = self.policy.search(query, k=max(1, min(int(k), 5)))
        if not matches:
            return {"query": query, "clauses": [], "note": "Nothing matched."}
        return {"query": query, "clauses": [m.as_dict() for m in matches]}

    def benford_stats(self, vendor_key: str) -> dict[str, Any]:
        import numpy as np

        from spendguard.detectors.d4_vendor import BENFORD, digit_share

        rows = self._rows(
            f"SELECT DISTINCT amount FROM {AUDIT_VIEW} WHERE vendor_key = ? AND amount > 0",
            [vendor_key],
        )
        amounts = np.array([r["amount"] for r in rows], dtype=float)
        if len(amounts) < settings.benford_min_transactions:
            return {
                "vendor_key": vendor_key,
                "distinct_amounts": int(len(amounts)),
                "sufficient_data": False,
                "note": (
                    f"Needs at least {settings.benford_min_transactions} distinct amounts to say "
                    "anything; with fewer, a departure means nothing."
                ),
            }
        observed = digit_share(amounts)
        peers = digit_share(
            np.array(
                [
                    r["amount"]
                    for r in self._rows(
                        f"SELECT DISTINCT amount FROM {AUDIT_VIEW} WHERE amount > 0 "
                        f"AND item_category IN (SELECT DISTINCT item_category FROM {AUDIT_VIEW} "
                        "WHERE vendor_key = ?)",
                        [vendor_key],
                    )
                ],
                dtype=float,
            )
        )
        return {
            "vendor_key": vendor_key,
            "distinct_amounts": int(len(amounts)),
            "sufficient_data": True,
            "digits": [
                {
                    "digit": d + 1,
                    "observed": round(float(observed[d]), 3),
                    "peers_same_categories": round(float(peers[d]), 3),
                    "benford": round(BENFORD[d], 3),
                }
                for d in range(9)
            ],
            "mean_absolute_deviation_vs_peers": round(float(np.abs(observed - peers).mean()), 4),
            "mean_absolute_deviation_vs_benford": round(
                float(np.abs(observed - np.array(BENFORD)).mean()), 4
            ),
            "note": (
                "Peers are the comparison that matters: procurement invoices are quantity times "
                "a near-fixed price and depart from Benford routinely."
            ),
        }

    def calculator(self, expression: str) -> dict[str, Any]:
        try:
            value = evaluate_expression(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            return {"error": f"Cannot evaluate {expression!r}: {exc}"}
        return {"expression": expression, "result": round(value, 4)}
