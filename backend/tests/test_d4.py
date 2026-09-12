"""D4 vendor red flags (policy SG-PP-5.5, decision D-24)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pytest

from spendguard.cases import AnomalyType
from spendguard.detectors import VendorFlagDetector
from spendguard.detectors.d4_vendor import (
    BENFORD,
    benjamini_hochberg,
    digit_share,
    first_digits,
)
from spendguard.eval.injection import InjectionResult
from spendguard.eval.matching import load_ground_truth, match
from spendguard.pipeline.ingest import IngestResult

from .conftest import build_db

DAY0 = date(2025, 4, 1)


def _vendor(
    name: str,
    amounts: list[float],
    category: str = "Services",
    period_end: bool = False,
) -> list[dict[str, object]]:
    """One supplier's billing history. Dates avoid month end unless asked for."""
    rows = []
    for i, amount in enumerate(amounts):
        when = date(2025, 4 + (i % 6), 27 if period_end else 3 + (i % 20))
        rows.append(
            {
                "vendor_name": name,
                "amount": amount,
                "unit_price": amount,
                "quantity": 1.0,
                "item_category": category,
                "item_desc": category,
                "txn_date": when,
            }
        )
    return rows


def _natural(n: int, seed: int = 0, low: float = 4_000, high: float = 400_000) -> list[float]:
    """Amounts with no round-number habit, spanning two orders of magnitude."""
    rng = np.random.default_rng(seed)
    return [round(float(x), 2) for x in rng.uniform(low, high, n)]


# ---------------------------------------------------------------- helpers


def test_first_digits() -> None:
    assert list(first_digits(np.array([5_000.0, 12_345.0, 999.0, 7.5]))) == [5, 1, 9, 7]


def test_digit_share_sums_to_one() -> None:
    assert digit_share(np.array(_natural(200))).sum() == pytest.approx(1.0)


def test_benford_expectation_is_the_classic_curve() -> None:
    assert BENFORD[0] == pytest.approx(0.301, abs=0.001)
    assert BENFORD[8] == pytest.approx(0.0458, abs=0.001)


@pytest.mark.parametrize(
    ("p_values", "alpha", "expected"),
    [
        ([], 0.05, 0.0),
        ([0.9, 0.8, 0.7], 0.05, 0.0),  # nothing significant
        ([1e-9, 0.9, 0.8], 0.05, 1e-9),  # one clear hit
        ([0.01, 0.02, 0.03], 0.05, 0.03),  # a run of small values all pass
    ],
)
def test_benjamini_hochberg(p_values: list[float], alpha: float, expected: float) -> None:
    assert benjamini_hochberg(p_values, alpha) == pytest.approx(expected)


# ---------------------------------------------------------------- the detector


def test_round_number_vendor_is_flagged(tmp_path: Path) -> None:
    rows = _vendor("Shell Consultants", [float(5_000 * i) for i in range(4, 44)])
    for peer in range(6):  # peers billing naturally in the same category
        rows += _vendor(f"Honest Firm {peer}", _natural(40, seed=peer))
    con = build_db(tmp_path / "t.duckdb", rows)
    cases = VendorFlagDetector().detect(con)
    assert [c.metadata["vendor_name"] for c in cases] == ["Shell Consultants"]
    assert "round_numbers" in cases[0].metadata["indicators"]
    assert cases[0].anomaly_type == AnomalyType.VENDOR_FLAG


def test_natural_billing_is_not_flagged(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for peer in range(8):
        rows += _vendor(f"Honest Firm {peer}", _natural(40, seed=peer))
    con = build_db(tmp_path / "t.duckdb", rows)
    assert VendorFlagDetector().detect(con) == []


def test_a_whole_category_billing_round_is_normal_for_that_category(tmp_path: Path) -> None:
    """Consultancies quote round figures. Compared globally they all look guilty;
    compared to their own category they do not (decision D-24)."""
    rows: list[dict[str, object]] = []
    for firm in range(6):
        amounts = [float(5_000 * (4 + (i * 3 + firm) % 40)) for i in range(40)]
        rows += _vendor(f"Advisory {firm}", amounts, category="Consultancy")
    for firm in range(6):  # a different trade, billing naturally
        rows += _vendor(f"Supplier {firm}", _natural(40, seed=firm + 20), category="Stationery")
    con = build_db(tmp_path / "t.duckdb", rows)
    assert VendorFlagDetector().detect(con) == []


def test_period_end_clustering_is_detected(tmp_path: Path) -> None:
    rows = _vendor("Year End Traders", _natural(40, seed=1), period_end=True)
    for peer in range(6):
        rows += _vendor(f"Honest Firm {peer}", _natural(40, seed=peer + 5))
    con = build_db(tmp_path / "t.duckdb", rows)
    cases = VendorFlagDetector().detect(con)
    assert [c.metadata["vendor_name"] for c in cases] == ["Year End Traders"]
    assert "period_end" in cases[0].metadata["indicators"]


def test_small_suppliers_are_not_tested(tmp_path: Path) -> None:
    """Too few invoices to say anything - silence, not an accusation."""
    rows = _vendor("Tiny Traders", [float(5_000 * i) for i in range(4, 9)])
    for peer in range(6):
        rows += _vendor(f"Honest Firm {peer}", _natural(40, seed=peer))
    con = build_db(tmp_path / "t.duckdb", rows)
    flagged = {c.metadata["vendor_name"] for c in VendorFlagDetector().detect(con)}
    assert "Tiny Traders" not in flagged


def test_a_repeated_fixed_fee_contract_is_not_round_number_evidence(tmp_path: Path) -> None:
    """One price decision repeated monthly is one observation, not twenty-four."""
    rows = _vendor("Security Services Co", [145_000.0] * 24)
    for peer in range(6):
        rows += _vendor(f"Honest Firm {peer}", _natural(40, seed=peer))
    con = build_db(tmp_path / "t.duckdb", rows)
    flagged = {c.metadata["vendor_name"] for c in VendorFlagDetector().detect(con)}
    assert "Security Services Co" not in flagged


def test_a_trivial_deviation_by_a_large_supplier_is_not_material(tmp_path: Path) -> None:
    """Significance is not enough: with 400 invoices a tiny excess is significant."""
    amounts = _natural(400, seed=3)
    amounts[:30] = [float(1_000 * (5 + i)) for i in range(30)]  # 7.5% round
    rows = _vendor("Big Supplier", amounts)
    for peer in range(6):
        rows += _vendor(f"Honest Firm {peer}", _natural(60, seed=peer + 9))
    con = build_db(tmp_path / "t.duckdb", rows)
    flagged = {c.metadata["vendor_name"] for c in VendorFlagDetector().detect(con)}
    assert "Big Supplier" not in flagged


def test_cases_carry_their_statistics(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        cases = VendorFlagDetector().detect(con)
    assert cases
    for c in cases:
        meta = c.metadata
        assert meta["policy_clauses"] == ["SG-PP-5.5", "SG-PP-7.1"]
        assert meta["indicators"]
        assert float(meta["combined_p_value"]) <= float(meta["fdr_cutoff"])
        assert 0.0 <= c.detector_score <= 1.0
        assert len(c.row_ids) == meta["transactions"]


def test_quality_on_injected_data(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        groups = load_ground_truth(con)
        cases = VendorFlagDetector().detect(con)
    m = match(cases, groups, AnomalyType.VENDOR_FLAG)
    # Only four vendors are planted in this small fixture, and the subtler ones sit
    # below the power of a 3,000-row dataset. Precision is the claim worth holding
    # here; full-scale recall (0.63-0.88) is in docs/EVALUATION.md.
    assert m.tp / max(m.tp + m.fp, 1) >= 0.6
    assert m.tp >= 1


def test_clean_data_raises_nothing(ingested: IngestResult) -> None:
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        assert VendorFlagDetector().detect(con) == []


def test_detection_is_deterministic(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        runs = [[c.model_dump() for c in VendorFlagDetector().detect(con)] for _ in range(2)]
    assert runs[0] == runs[1]
