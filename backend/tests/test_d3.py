"""D3 price inflation (policy SG-PP-6.3, decision D-23)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.detectors import InflationDetector
from spendguard.detectors.d3_inflation import second_opinion_gap
from spendguard.eval.injection import InjectionResult
from spendguard.eval.matching import load_ground_truth, match
from spendguard.pipeline.ingest import IngestResult

from .conftest import build_db

DAY0 = date(2025, 4, 1)


def _category(name: str, price: float, n: int, start: int = 0) -> list[dict[str, object]]:
    """A category of n honest purchases at a steady unit price."""
    return [
        {
            "item_category": name,
            "item_desc": name,
            "unit_price": price + (i % 5),  # a little natural spread
            "quantity": 10.0,
            "amount": (price + (i % 5)) * 10,
            "txn_date": DAY0 + timedelta(days=start + i),
            "vendor_name": f"Vendor {i % 7}",
        }
        for i in range(n)
    ]


def test_price_far_above_the_category_norm_is_flagged(tmp_path: Path) -> None:
    rows = _category("Paper", 300.0, 40)
    rows.append({**rows[0], "unit_price": 1_200.0, "amount": 12_000.0})  # 4x
    con = build_db(tmp_path / "t.duckdb", rows)
    cases = InflationDetector().detect(con)
    assert [c.row_ids for c in cases] == [(41,)]
    case = cases[0]
    assert case.anomaly_type == AnomalyType.INFLATION
    assert case.metadata["policy_clause"] == "SG-PP-6.3"
    assert case.metadata["times_expected"] > 3
    assert case.amount_at_risk == pytest.approx(
        (1200 - case.metadata["expected_price"]) * 10, rel=0.01
    )


def test_a_normal_price_is_not_flagged(tmp_path: Path) -> None:
    con = build_db(tmp_path / "t.duckdb", _category("Paper", 300.0, 40))
    assert InflationDetector().detect(con) == []


def test_small_categories_are_skipped(tmp_path: Path) -> None:
    """Too little history to know what normal is - an unstable median invents outliers."""
    rows = _category("Rare", 300.0, settings.inflation_min_category_size - 2)
    rows.append({**rows[0], "unit_price": 5_000.0, "amount": 50_000.0})
    assert len(rows) < settings.inflation_min_category_size
    con = build_db(tmp_path / "t.duckdb", rows)
    assert InflationDetector().detect(con) == []


def test_identical_prices_do_not_divide_by_zero(tmp_path: Path) -> None:
    """A category where every price is the same has MAD 0."""
    rows = [{**r, "unit_price": 300.0, "amount": 3_000.0} for r in _category("Flat", 300.0, 40)]
    con = build_db(tmp_path / "t.duckdb", rows)
    assert InflationDetector().detect(con) == []  # no variation, no outlier

    rows.append({**rows[0], "unit_price": 900.0, "amount": 9_000.0})
    con = build_db(tmp_path / "flat2.duckdb", rows)
    cases = InflationDetector().detect(con)
    assert [c.row_ids for c in cases] == [(41,)]


def test_log_space_treats_cheap_and_expensive_categories_alike(tmp_path: Path) -> None:
    """A 4x markup is the same event on a ₹300 ream and a ₹60,000 laptop."""
    rows = _category("Paper", 300.0, 40) + _category("Laptop", 60_000.0, 40, start=100)
    rows.append({**rows[0], "unit_price": 1_200.0, "amount": 12_000.0})
    rows.append({**rows[40], "unit_price": 240_000.0, "amount": 2_400_000.0})
    con = build_db(tmp_path / "t.duckdb", rows)
    flagged = {c.row_ids[0] for c in InflationDetector().detect(con)}
    assert flagged == {81, 82}


def test_rows_without_a_price_or_category_are_excluded(tmp_path: Path) -> None:
    rows = _category("Paper", 300.0, 40)
    rows += [
        {**rows[0], "unit_price": None, "amount": 99_999.0},
        {**rows[0], "item_category": None, "unit_price": 9_000.0},
        {**rows[0], "quantity": None, "unit_price": 9_000.0},
    ]
    con = build_db(tmp_path / "t.duckdb", rows)
    assert InflationDetector().detect(con) == []


def test_controls_recover_the_real_price_drift(injected: InjectionResult) -> None:
    """The generator drifts prices ~6%/yr; the control should find roughly that."""
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        detector = InflationDetector()
        detector.detect(con)
    assert 0.01 < detector.controls.annual_drift < 0.15
    # Bulk discount is real but weak in this data, and its sign is not stable on a
    # small sample. What matters is that it stays a small correction, not a lever.
    assert abs(detector.controls.bulk_discount) < 0.05


def test_scores_are_bounded_and_ordered(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        cases = InflationDetector().detect(con)
    assert cases
    for c in cases:
        assert 0.5 <= c.detector_score <= 1.0  # at or above the threshold
        assert c.metadata["robust_z"] >= settings.inflation_zscore_threshold


def test_ranks_where_the_baseline_only_says_yes_or_no(injected: InjectionResult) -> None:
    """D3 ties the rule baseline on F1; its advantage is a *ranked* score, which is
    what top-N triage needs. The measured PR-AUC gap (0.369 vs 0.197) is on the
    full 50k dataset - see docs/EVALUATION.md; this fixture is too small to show it."""
    from spendguard.detectors import BaselineDetector

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        d3 = InflationDetector().detect(con)
        base = [c for c in BaselineDetector().detect(con) if c.anomaly_type.value == "inflation"]
    assert len({c.detector_score for c in d3}) > 1
    assert {c.detector_score for c in base} == {1.0}


def test_isolation_forest_is_recorded_but_never_raises_a_case(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        detector = InflationDetector()
        cases = detector.detect(con)
        gap = second_opinion_gap(detector, con)
    assert all("isolation_forest_agrees" in c.metadata for c in cases)
    # It disagrees with the z-score on many rows; none of those became a case.
    assert gap["forest_only"] > 0
    assert len(cases) == gap["z_only"] + gap["both"]


def test_detection_is_deterministic(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        runs = [[c.model_dump() for c in InflationDetector().detect(con)] for _ in range(2)]
    assert runs[0] == runs[1]


def test_clean_data_raises_few_cases(ingested: IngestResult) -> None:
    """Honest premium and urgent purchases exist; D3 should not drown in them."""
    with duckdb.connect(str(ingested.db_path), read_only=True) as con:
        rows = con.execute("SELECT count(*) FROM transactions").fetchone()
        cases = InflationDetector().detect(con)
    assert rows is not None
    assert len(cases) < 0.01 * rows[0]


def test_quality_on_injected_data(injected: InjectionResult) -> None:
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        groups = load_ground_truth(con)
        cases = InflationDetector().detect(con)
    m = match(cases, groups, AnomalyType.INFLATION)
    assert m.tp / max(m.tp + m.fp, 1) >= 0.2
    assert m.tp / (m.tp + m.fn) >= 0.3
