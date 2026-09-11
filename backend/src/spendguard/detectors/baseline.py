"""Rule-based baseline - the benchmark every ML detector must beat (FR-2.10).

Deliberately naive: these are the fixed rules a conventional ERP control or a
first-pass audit script applies. They are not straw men - each is a real,
commonly used test - but none normalizes names, learns a distribution, or looks
at more than one transaction at a time. That is exactly what the detectors in
Phases 3-4 must prove is worth doing.

    duplicate    same supplier name, same invoice number, same amount
    split        amount within 10% below the approval threshold
    inflation    unit price above twice the category mean
    vendor_flag  most of a supplier's invoices are exact multiples of Rs 1,000

Every rule is binary, so every case scores 1.0. A rule engine says yes or no; it
does not rank.
"""

from __future__ import annotations

from typing import ClassVar

import duckdb

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.detectors.base import AUDIT_VIEW


class BaselineDetector:
    name: ClassVar[str] = "baseline"
    anomaly_types: ClassVar[tuple[AnomalyType, ...]] = tuple(AnomalyType)

    NEAR_THRESHOLD_BAND: ClassVar[float] = 0.10
    INFLATION_MULTIPLE: ClassVar[float] = 2.0
    ROUND_UNIT: ClassVar[float] = 1_000.0
    ROUND_SHARE: ClassVar[float] = 0.50
    ROUND_MIN_TRANSACTIONS: ClassVar[int] = 10

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        return [
            *self._exact_duplicates(con),
            *self._near_threshold(con),
            *self._inflated(con),
            *self._round_number_vendors(con),
        ]

    def _case(self, kind: AnomalyType, rule: str, **fields: object) -> Case:
        return Case.build(
            detector=self.name,
            anomaly_type=kind,
            detector_score=1.0,
            metadata={"rule": rule},
            **fields,  # type: ignore[arg-type]
        )

    def _exact_duplicates(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        rows = con.execute(
            f"""
            SELECT list(row_id ORDER BY row_id), any_value(vendor_key), amount, count(*)
            FROM {AUDIT_VIEW}
            WHERE invoice_no IS NOT NULL
            GROUP BY lower(trim(vendor_name)), invoice_no, amount
            HAVING count(*) > 1
            """
        ).fetchall()
        return [
            self._case(
                AnomalyType.DUPLICATE,
                "same supplier name, invoice number and amount",
                row_ids=ids,
                vendor_key=key,
                amount_at_risk=amount * (n - 1),
            )
            for ids, key, amount, n in rows
        ]

    def _near_threshold(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        threshold = settings.approval_threshold
        rows = con.execute(
            f"SELECT row_id, vendor_key, amount FROM {AUDIT_VIEW} "
            "WHERE amount >= ? AND amount < ? ORDER BY row_id",
            [threshold * (1 - self.NEAR_THRESHOLD_BAND), threshold],
        ).fetchall()
        return [
            self._case(
                AnomalyType.SPLIT,
                f"amount within {self.NEAR_THRESHOLD_BAND:.0%} below the approval threshold",
                row_ids=[row_id],
                vendor_key=key,
                amount_at_risk=amount,
            )
            for row_id, key, amount in rows
        ]

    def _inflated(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        rows = con.execute(
            f"""
            WITH norms AS (
                SELECT item_category, avg(unit_price) AS mean_price
                FROM {AUDIT_VIEW}
                WHERE unit_price IS NOT NULL AND item_category IS NOT NULL
                GROUP BY item_category
                HAVING count(*) >= 2
            )
            SELECT t.row_id, t.vendor_key, t.unit_price, coalesce(t.quantity, 1), n.mean_price
            FROM {AUDIT_VIEW} t JOIN norms n USING (item_category)
            WHERE t.unit_price > ? * n.mean_price
            ORDER BY t.row_id
            """,
            [self.INFLATION_MULTIPLE],
        ).fetchall()
        return [
            self._case(
                AnomalyType.INFLATION,
                f"unit price above {self.INFLATION_MULTIPLE:g}x the category mean",
                row_ids=[row_id],
                vendor_key=key,
                amount_at_risk=(price - mean) * quantity,
            )
            for row_id, key, price, quantity, mean in rows
        ]

    def _round_number_vendors(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        is_round = f"(amount % {self.ROUND_UNIT} = 0)"
        rows = con.execute(
            f"""
            SELECT vendor_key,
                   list(row_id ORDER BY row_id),
                   sum(CASE WHEN {is_round} THEN amount ELSE 0 END)
            FROM {AUDIT_VIEW}
            GROUP BY vendor_key
            HAVING count(*) >= ?
               AND avg(CASE WHEN {is_round} THEN 1.0 ELSE 0.0 END) >= ?
            ORDER BY vendor_key
            """,
            [self.ROUND_MIN_TRANSACTIONS, self.ROUND_SHARE],
        ).fetchall()
        return [
            self._case(
                AnomalyType.VENDOR_FLAG,
                f"at least {self.ROUND_SHARE:.0%} of invoices are exact multiples of "
                f"{settings.money(self.ROUND_UNIT)}",
                row_ids=ids,
                vendor_key=key,
                amount_at_risk=round_total,
            )
            for key, ids, round_total in rows
        ]
