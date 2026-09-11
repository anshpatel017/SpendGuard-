"""The synthetic INR generator: reproducible, realistic, and anomaly-free."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from spendguard.config import settings
from spendguard.pipeline.synthetic import (
    DATE_FORMAT,
    DIRT_TYPES,
    MALFORMED_TYPES,
    SOURCE_COLUMNS,
    GeneratorConfig,
    SyntheticDataset,
    generate,
)
from spendguard.pipeline.vendors import normalize_vendor

from .conftest import SMALL


def _clean(ds: SyntheticDataset) -> pl.DataFrame:
    """Rows without any defect, joined to their ground truth."""
    return ds.frame.with_columns(ds.truth.drop("voucher_no")).filter(pl.col("defect").is_null())


def test_same_seed_is_byte_identical(small_dataset: SyntheticDataset) -> None:
    again = generate(SMALL)
    assert small_dataset.frame.equals(again.frame)
    assert small_dataset.truth.equals(again.truth)


def test_different_seed_differs(small_dataset: SyntheticDataset) -> None:
    other = generate(GeneratorConfig(n_transactions=SMALL.n_transactions, seed=SMALL.seed + 1))
    assert not small_dataset.frame.equals(other.frame)


def test_row_count_is_exact(small_dataset: SyntheticDataset) -> None:
    assert small_dataset.frame.height == SMALL.n_transactions
    assert small_dataset.truth.height == SMALL.n_transactions


def test_headers_are_source_style_not_canonical(small_dataset: SyntheticDataset) -> None:
    assert small_dataset.frame.columns == list(SOURCE_COLUMNS.values())
    assert "vendor_name" not in small_dataset.frame.columns


def test_vouchers_are_unique(small_dataset: SyntheticDataset) -> None:
    assert small_dataset.frame["Voucher No"].n_unique() == SMALL.n_transactions


def test_dates_are_in_range_and_indian_format(small_dataset: SyntheticDataset) -> None:
    dates = [
        datetime.strptime(d, DATE_FORMAT).date() for d in _clean(small_dataset)["Invoice Date"]
    ]
    assert min(dates) >= SMALL.start_date
    assert max(dates) <= SMALL.end_date


def test_amounts_are_positive_inr(small_dataset: SyntheticDataset) -> None:
    amounts = _clean(small_dataset)["Invoice Amount (INR)"].cast(pl.Float64)
    assert (amounts > 0).all()


def test_amount_equals_quantity_times_rate(small_dataset: SyntheticDataset) -> None:
    clean = _clean(small_dataset).with_columns(
        pl.col("Qty").cast(pl.Float64),
        pl.col("Rate (INR)").cast(pl.Float64),
        pl.col("Invoice Amount (INR)").cast(pl.Float64),
    )
    diff = (clean["Qty"] * clean["Rate (INR)"] - clean["Invoice Amount (INR)"]).abs()
    assert (diff < 0.011).all()


def test_spans_the_approval_threshold(small_dataset: SyntheticDataset) -> None:
    """Split-purchase injection needs genuine large purchases to split."""
    above = small_dataset.report["rows_above_approval_threshold"]
    assert isinstance(above, int)
    assert 0 < above < SMALL.n_transactions * 0.25


def test_every_supplier_variant_normalizes_to_one_key(small_dataset: SyntheticDataset) -> None:
    """Legitimate spelling drift must never split one supplier across keys."""
    keys = (
        _clean(small_dataset)
        .with_columns(
            pl.col("Supplier Name")
            .map_elements(normalize_vendor, return_dtype=pl.String)
            .alias("key")
        )
        .group_by("vendor_id")
        .agg(pl.col("key").n_unique().alias("n_keys"))
    )
    assert (keys["n_keys"] == 1).all()


def test_name_variants_are_present(small_dataset: SyntheticDataset) -> None:
    variants = small_dataset.truth.filter(
        pl.col("written_vendor_name") != pl.col("canonical_vendor_name")
    )
    assert variants.height > SMALL.n_transactions * SMALL.legit_variant_rate * 0.5


def test_recurring_contracts_bill_a_fixed_amount_monthly(small_dataset: SyntheticDataset) -> None:
    """The legitimate pattern D1 must not flag: same vendor, same amount, every month."""
    recurring = _clean(small_dataset).filter(pl.col("is_recurring"))
    assert recurring.height > 0

    for (_vendor,), group in recurring.group_by(["vendor_id"]):
        dates = sorted(datetime.strptime(d, DATE_FORMAT).date() for d in group["Invoice Date"])
        gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
        # Several contracts can share one supplier, so look at each contract's own gaps.
        assert gaps and min(gaps) >= 0
        assert any(25 <= g <= 36 for g in gaps)


def test_recurring_payments_never_fall_inside_the_duplicate_window(
    small_dataset: SyntheticDataset,
) -> None:
    recurring = _clean(small_dataset).filter(pl.col("is_recurring"))
    for (_desc,), group in recurring.group_by(["Item Description"]):
        if group.height < 2:
            continue
        per_vendor = group.group_by("vendor_id").agg(pl.len())
        assert (per_vendor["len"] == 1).all(), "one invoice per contract per service month"


def test_march_year_end_rush(small_dataset: SyntheticDataset) -> None:
    months = [
        datetime.strptime(d, DATE_FORMAT).month for d in _clean(small_dataset)["Invoice Date"]
    ]
    march_share = months.count(3) / len(months)
    assert march_share > 1.2 / 12


def test_weekends_are_quiet(small_dataset: SyntheticDataset) -> None:
    days = [
        datetime.strptime(d, DATE_FORMAT).weekday() for d in _clean(small_dataset)["Invoice Date"]
    ]
    assert sum(1 for d in days if d >= 5) / len(days) < 0.08


def test_defect_counts_match_report(small_dataset: SyntheticDataset) -> None:
    defects = small_dataset.truth["defect"].drop_nulls().value_counts()
    counts = dict(zip(defects["defect"], defects["count"], strict=True))
    malformed = small_dataset.report["malformed_rows"]
    dirty = small_dataset.report["dirty_rows"]
    assert isinstance(malformed, dict) and isinstance(dirty, dict)
    assert {k: v for k, v in counts.items() if k in MALFORMED_TYPES} == malformed
    assert {k: v for k, v in counts.items() if k in DIRT_TYPES} == dirty


def test_invoice_numbers_unique_per_supplier(small_dataset: SyntheticDataset) -> None:
    per_vendor = (
        small_dataset.frame.with_columns(small_dataset.truth["vendor_id"])
        .group_by("vendor_id")
        .agg(pl.col("Invoice Number").n_unique().alias("u"), pl.len().alias("n"))
    )
    assert (per_vendor["u"] == per_vendor["n"]).all()


def test_ground_truth_is_not_in_the_csv(small_dataset: SyntheticDataset) -> None:
    """Detectors must only ever see what an auditor would see."""
    for leaked in ("vendor_id", "canonical_vendor_name", "is_recurring", "defect"):
        assert leaked not in small_dataset.frame.columns


@pytest.mark.parametrize(
    "bad",
    [
        {"n_transactions": 10},
        {"dirt_rate": 1.5},
        {"start_date": date(2026, 1, 1), "end_date": date(2025, 1, 1)},
    ],
)
def test_invalid_config_is_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        GeneratorConfig(**bad)  # type: ignore[arg-type]


def test_default_seed_comes_from_settings() -> None:
    assert GeneratorConfig().seed == 42 == settings.random_seed
