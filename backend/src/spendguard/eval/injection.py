"""Anomaly-injection harness - ground truth for data that has none (docs/EVALUATION.md).

Public procurement data ships without fraud labels, so there is nothing to
measure precision or recall against. This harness plants realistic, parameterized
anomalies into clean data with a fixed seed and records exactly where it put
them. The result is a separate database: the clean one is never modified.

    duplicate    copy a real row; perturb the supplier name and invoice number,
                 shift the date a few days, keep the amount
    split        replace one above-threshold purchase with 3-6 sub-threshold
                 purchases from the same supplier and officer, inside a short window
    inflation    multiply a line item's unit price by 1.5-3x
    vendor_flag  synthesize a new supplier whose invoices are round-number heavy,
                 clustered at month- and year-end, and billed to one or two officers

Design choices a reviewer should know about:

* ``rate`` is the number of anomaly **groups** per transaction. A split touches
  several rows, so the share of rows touched is higher; it is reported.
* Every injected anomaly stays inside the policy's own definition of that
  anomaly - duplicates within the 14-day window, splits within 14 days. An
  anomaly no correct detector could find would measure nothing.
* A row belongs to at most one anomaly group, so matching stays unambiguous.
* Inflation is capped per category, so the planted outliers cannot drag the
  category median they are measured against (docs/EVALUATION.md 2.2).
* Split originals are deleted - the requirement is *replaced* by its parts.
* Injected rows have no ``source_row_ref``; detectors read a view that
  excludes it, so that gap cannot leak the answer key.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.db.duck import (
    DATASET_CARDS_DDL,
    GROUND_TRUTH_DDL,
    INJECTION_RUNS_DDL,
    connect,
    read_transactions,
    table_exists,
    write_transactions,
)
from spendguard.pipeline.catalogue import FIRM_WORDS, SURNAMES
from spendguard.pipeline.perturb import legitimate_variant, typo
from spendguard.pipeline.vendors import normalize_vendor

_GROUP_PREFIX = {
    AnomalyType.DUPLICATE: "DUP",
    AnomalyType.SPLIT: "SPL",
    AnomalyType.INFLATION: "INF",
    AnomalyType.VENDOR_FLAG: "VEN",
}


@dataclass(frozen=True)
class InjectionConfig:
    seed: int = 42
    rate: float = 0.01  # anomaly groups per transaction, vendor flags excluded
    duplicate_share: float = 0.40
    split_share: float = 0.25
    inflation_share: float = 0.35
    vendor_flags: int | None = None  # None -> 1% of suppliers, at least 2

    # duplicate
    duplicate_max_shift_days: int = 10
    triplicate_share: float = 0.10
    # (mode, probability) - how a duplicate's supplier name is disguised
    duplicate_name_modes: tuple[tuple[str, float], ...] = (
        ("exact", 0.35),
        ("variant", 0.35),
        ("typo", 0.30),
    )
    # (mode, probability) - how a duplicate's invoice reference is recorded.
    # "rekeyed" is the hard case: paid twice under unrelated references, as when
    # one payment is made from a statement and another from the invoice.
    duplicate_invoice_modes: tuple[tuple[str, float], ...] = (
        ("same", 0.35),
        ("reformatted", 0.55),
        ("rekeyed", 0.10),
    )

    # split
    split_min_parts: int = 3
    split_max_parts: int = 6
    split_window_days: int = 10

    # inflation
    inflation_min_factor: float = 1.5
    inflation_max_factor: float = 3.0
    inflation_category_cap: float = 0.05

    # vendor flag
    vendor_flag_min_rows: int = 35
    vendor_flag_max_rows: int = 60
    # How obvious each synthetic vendor is, drawn per vendor. A single high value
    # makes every planted vendor blatant and any detector score 1.000; real shell
    # vendors vary, and the spread is what makes recall meaningful (decision D-25).
    vendor_flag_round_share: tuple[float, float] = (0.35, 0.75)
    vendor_flag_period_end_share: tuple[float, float] = (0.30, 0.60)

    def __post_init__(self) -> None:
        if not 0 < self.rate <= 0.05:
            raise ValueError(f"rate must be in (0, 0.05], got {self.rate}")
        shares = self.duplicate_share + self.split_share + self.inflation_share
        if abs(shares - 1.0) > 1e-9:
            raise ValueError(f"type shares must sum to 1, got {shares}")
        if self.duplicate_max_shift_days + 2 > settings.duplicate_date_window_days:
            raise ValueError(
                "duplicate shift (plus weekend roll) must stay inside the policy window"
            )
        if self.split_window_days + 4 > settings.split_window_days:
            raise ValueError("split window (plus weekend roll) must stay inside the policy window")
        if not 1 < self.inflation_min_factor <= self.inflation_max_factor:
            raise ValueError("inflation factors must satisfy 1 < min <= max")
        if not 2 <= self.split_min_parts <= self.split_max_parts:
            raise ValueError("split parts must satisfy 2 <= min <= max")
        if self.vendor_flag_min_rows < settings.benford_min_transactions:
            raise ValueError("synthetic vendors need enough invoices for a first-digit test")
        for name in ("vendor_flag_round_share", "vendor_flag_period_end_share"):
            low, high = getattr(self, name)
            if not 0 < low <= high < 1:
                raise ValueError(f"{name} must be a range inside (0, 1), got {(low, high)}")


@dataclass
class TruthRecord:
    injection_group_id: str
    injection_type: AnomalyType
    row_ids: list[int]
    source_row_ids: list[int]
    vendor_key: str | None
    amount_at_risk: float
    params: dict[str, Any]


@dataclass
class InjectionResult:
    out_db: Path
    seed: int
    rows_before: int
    rows_after: int
    groups: dict[str, int]
    rows_injected: dict[str, int]  # new or modified rows, by type
    rows_deleted: int
    shortfall: dict[str, int]  # groups requested but not placeable
    amount_at_risk: dict[str, float]
    records: list[TruthRecord] = field(default_factory=list)

    @property
    def row_share(self) -> float:
        """Share of the final table that is injected."""
        return sum(self.rows_injected.values()) / max(self.rows_after, 1)


# ------------------------------------------------------------------ helpers


def _weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _clamp(d: date, low: date, high: date) -> date:
    return max(low, min(high, d))


def _bump_invoice(invoice: str | None, step: int) -> str | None:
    """Next invoice in the same series: 'INV-00123' + 2 -> 'INV-00125'."""
    if invoice is None:
        return None
    match = re.search(r"(\d+)(?!.*\d)", invoice)
    if match is None:
        return f"{invoice}-{step}"
    digits = match.group(1)
    bumped = str(int(digits) + step).zfill(len(digits))
    return f"{invoice[: match.start()]}{bumped}{invoice[match.end() :]}"


def _reformat_invoice(invoice: str | None, when: date, rng: np.random.Generator) -> str | None:
    """Same invoice, typed differently: 'INV-04471' -> '4471/2026' (CLAUDE.md example)."""
    if invoice is None:
        return None
    digits = re.findall(r"\d+", invoice)
    core = (digits[-1].lstrip("0") or "0") if digits else invoice
    options = [
        core,
        f"{core}/{when.year}",
        invoice.replace("-", "/") if "-" in invoice else invoice.replace("/", "-"),
        f"{core}/{when.year % 100:02d}",
    ]
    options = [o for o in options if o != invoice]
    return options[int(rng.integers(len(options)))] if options else f"{invoice}-1"


# ------------------------------------------------------------------ injector


class _Injector:
    def __init__(self, frame: pl.DataFrame, cfg: InjectionConfig, rng: np.random.Generator) -> None:
        self.frame = frame
        self.cfg = cfg
        self.rng = rng
        self.next_id = int(frame["row_id"].max()) + 1  # type: ignore[arg-type]
        self.first_day: date = frame["txn_date"].min()  # type: ignore[assignment]
        self.last_day: date = frame["txn_date"].max()  # type: ignore[assignment]
        self.dataset: str = frame["source_dataset"][0]

        self.used: set[int] = set()
        self.deleted: set[int] = set()
        self.updates: list[dict[str, Any]] = []
        self.new_rows: list[dict[str, Any]] = []
        self.records: list[TruthRecord] = []
        self.shortfall: Counter[str] = Counter()
        self._serial: Counter[AnomalyType] = Counter()
        self._invoices: dict[str, set[str]] | None = None

    def _fresh_invoice(self, vendor_key: str, base: str | None, step: int) -> str | None:
        """A reference in the supplier's own series that it has never issued.

        Bumping blindly would reuse a number already on another transaction -
        something no real supplier does, and a spurious signal for detectors.
        """
        if base is None:
            return None
        if self._invoices is None:
            self._invoices = {}
            for key, invoice in (
                self.frame.select("vendor_key", "invoice_no").drop_nulls().iter_rows()
            ):
                self._invoices.setdefault(key, set()).add(invoice)
        issued = self._invoices.setdefault(vendor_key, set())
        candidate = _bump_invoice(base, step)
        while candidate in issued:
            candidate = _bump_invoice(candidate, 1)
        assert candidate is not None
        issued.add(candidate)
        return candidate

    # ------------------------------------------------------------ plumbing

    def _group_id(self, kind: AnomalyType) -> str:
        self._serial[kind] += 1
        return f"{_GROUP_PREFIX[kind]}-{self.cfg.seed}-{self._serial[kind]:04d}"

    def _shuffled(self, candidates: pl.DataFrame) -> list[int]:
        ids = candidates.get_column("row_id").sort().to_list()
        return [ids[i] for i in self.rng.permutation(len(ids))]

    def _rows(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        subset = self.frame.filter(pl.col("row_id").is_in(ids))
        return {r["row_id"]: r for r in subset.iter_rows(named=True)}

    def _new_row(
        self, template: dict[str, Any], group_id: str, kind: AnomalyType, **changes: Any
    ) -> int:
        row = {**template, **changes}
        row["row_id"] = self.next_id
        row["vendor_key"] = normalize_vendor(row["vendor_name"])
        row["source_dataset"] = self.dataset
        row["source_row_ref"] = None
        row["is_injected"] = True
        row["injection_group_id"] = group_id
        row["injection_type"] = kind.value
        self.new_rows.append(row)
        self.next_id += 1
        return int(row["row_id"])

    # ------------------------------------------------------------ splits

    def _partition(self, row: dict[str, Any]) -> list[tuple[int, float]] | None:
        """Split a line's quantity into k parts, each strictly below the threshold."""
        threshold = settings.approval_threshold
        amount, price = float(row["amount"]), float(row["unit_price"])
        quantity = int(row["quantity"])
        k_min = max(self.cfg.split_min_parts, math.ceil(amount / (0.95 * threshold)))
        if k_min > self.cfg.split_max_parts or quantity < k_min:
            return None
        k = int(self.rng.integers(k_min, min(self.cfg.split_max_parts, quantity) + 1))

        for _ in range(30):
            weights = self.rng.dirichlet(np.full(k, 4.0))
            parts = np.maximum(1, np.floor(weights * quantity)).astype(int)
            while parts.sum() < quantity:
                parts[int(self.rng.integers(k))] += 1
            while parts.sum() > quantity:
                i = int(np.argmax(parts))
                parts[i] -= 1
            amounts = [round(int(q) * price, 2) for q in parts]
            amounts[-1] = round(amount - sum(amounts[:-1]), 2)  # keep the total exact
            if all(0 < a < 0.98 * threshold for a in amounts):
                return [(int(q), a) for q, a in zip(parts, amounts, strict=True)]
        return None

    def inject_splits(self, n: int) -> None:
        threshold = settings.approval_threshold
        candidates = self.frame.filter(
            (pl.col("amount") >= threshold)
            & (pl.col("amount") <= self.cfg.split_max_parts * 0.9 * threshold)
            & pl.col("officer_id").is_not_null()
            & pl.col("unit_price").is_not_null()
            & (pl.col("quantity") >= self.cfg.split_min_parts)
            & (pl.col("quantity") == pl.col("quantity").floor())
        )
        order = self._shuffled(candidates)
        rows = self._rows(order)
        made = 0
        for row_id in order:
            if made == n:
                break
            if row_id in self.used:
                continue
            row = rows[row_id]
            parts = self._partition(row)
            if parts is None:
                continue

            group_id = self._group_id(AnomalyType.SPLIT)
            start = _clamp(
                row["txn_date"] - timedelta(days=int(self.rng.integers(0, 3))),
                self.first_day,
                self.last_day,
            )
            offsets = sorted(
                int(x) for x in self.rng.integers(0, self.cfg.split_window_days + 1, len(parts))
            )
            new_ids: list[int] = []
            for i, ((quantity, amount), offset) in enumerate(zip(parts, offsets, strict=True)):
                name = row["vendor_name"]
                if self.rng.random() < 0.3:
                    name = legitimate_variant(name, self.rng)
                when = _clamp(
                    _weekday(start + timedelta(days=offset)), self.first_day, self.last_day
                )
                new_ids.append(
                    self._new_row(
                        row,
                        group_id,
                        AnomalyType.SPLIT,
                        vendor_name=name,
                        # The deleted original's number is free for the first part.
                        invoice_no=row["invoice_no"]
                        if i == 0
                        else self._fresh_invoice(row["vendor_key"], row["invoice_no"], i),
                        amount=amount,
                        quantity=float(quantity),
                        txn_date=when,
                    )
                )

            self.used.add(row_id)
            self.deleted.add(row_id)
            dates = [r["txn_date"] for r in self.new_rows[-len(parts) :]]
            self.records.append(
                TruthRecord(
                    injection_group_id=group_id,
                    injection_type=AnomalyType.SPLIT,
                    row_ids=new_ids,
                    source_row_ids=[row_id],
                    vendor_key=row["vendor_key"],
                    amount_at_risk=float(row["amount"]),
                    params={
                        "parts": len(parts),
                        "span_days": (max(dates) - min(dates)).days,
                        "original_amount": float(row["amount"]),
                        "largest_part": max(a for _, a in parts),
                    },
                )
            )
            made += 1
        self.shortfall[AnomalyType.SPLIT.value] += n - made

    # ------------------------------------------------------------ inflation

    def inject_inflation(self, n: int) -> None:
        sizes = self.frame.group_by("item_category").len().drop_nulls("item_category")
        cap = {
            r["item_category"]: max(1, int(self.cfg.inflation_category_cap * r["len"]))
            for r in sizes.iter_rows(named=True)
            if r["len"] >= settings.inflation_min_category_size
        }
        candidates = self.frame.filter(
            pl.col("item_category").is_in(list(cap))
            & pl.col("unit_price").is_not_null()
            & pl.col("quantity").is_not_null()
            & (pl.col("quantity") > 0)
        )
        order = self._shuffled(candidates)
        rows = self._rows(order)
        taken: Counter[str] = Counter()
        made = 0
        for row_id in order:
            if made == n:
                break
            row = rows[row_id]
            category = row["item_category"]
            if row_id in self.used or taken[category] >= cap[category]:
                continue

            factor = float(
                self.rng.uniform(self.cfg.inflation_min_factor, self.cfg.inflation_max_factor)
            )
            price = round(float(row["unit_price"]) * factor, 2)
            amount = round(float(row["quantity"]) * price, 2)
            group_id = self._group_id(AnomalyType.INFLATION)
            self.updates.append(
                {
                    "row_id": row_id,
                    "unit_price": price,
                    "amount": amount,
                    "is_injected": True,
                    "injection_group_id": group_id,
                    "injection_type": AnomalyType.INFLATION.value,
                }
            )
            self.records.append(
                TruthRecord(
                    injection_group_id=group_id,
                    injection_type=AnomalyType.INFLATION,
                    row_ids=[row_id],
                    source_row_ids=[row_id],
                    vendor_key=row["vendor_key"],
                    amount_at_risk=round(amount - float(row["amount"]), 2),
                    params={
                        "factor": round(factor, 4),
                        "original_unit_price": float(row["unit_price"]),
                        "category": category,
                    },
                )
            )
            self.used.add(row_id)
            taken[category] += 1
            made += 1
        self.shortfall[AnomalyType.INFLATION.value] += n - made

    # ------------------------------------------------------------ duplicates

    def inject_duplicates(self, n: int) -> None:
        modes = [m for m, _ in self.cfg.duplicate_name_modes]
        probs = np.array([p for _, p in self.cfg.duplicate_name_modes])
        probs = probs / probs.sum()
        invoice_modes = [m for m, _ in self.cfg.duplicate_invoice_modes]
        invoice_probs = np.array([p for _, p in self.cfg.duplicate_invoice_modes])
        invoice_probs = invoice_probs / invoice_probs.sum()

        order = self._shuffled(self.frame)
        made = 0
        chosen: list[int] = []
        for row_id in order:
            if len(chosen) == n:
                break
            if row_id not in self.used:
                chosen.append(row_id)
                self.used.add(row_id)
        rows = self._rows(chosen)

        for row_id in chosen:
            row = rows[row_id]
            copies = 2 if self.rng.random() < self.cfg.triplicate_share else 1
            group_id = self._group_id(AnomalyType.DUPLICATE)
            ids, applied = [row_id], []

            for _ in range(copies):
                mode = modes[int(self.rng.choice(len(modes), p=probs))]
                name = row["vendor_name"]
                if mode == "variant":
                    name = legitimate_variant(name, self.rng)
                elif mode == "typo":
                    name = typo(name, self.rng)

                shift = int(self.rng.integers(1, self.cfg.duplicate_max_shift_days + 1))
                when = _weekday(row["txn_date"] + timedelta(days=shift))
                if when > self.last_day:
                    when = row["txn_date"] - timedelta(days=shift)
                    while when.weekday() >= 5:
                        when -= timedelta(days=1)

                invoice_mode = invoice_modes[
                    int(self.rng.choice(len(invoice_modes), p=invoice_probs))
                ]
                if invoice_mode == "reformatted":
                    invoice = _reformat_invoice(row["invoice_no"], when, self.rng)
                elif invoice_mode == "rekeyed":
                    # Paid again under a reference unrelated to the first:
                    # from a statement, or a resubmitted invoice.
                    invoice = self._fresh_invoice(
                        row["vendor_key"], row["invoice_no"], int(self.rng.integers(50, 500))
                    )
                else:
                    invoice = row["invoice_no"]
                ids.append(
                    self._new_row(
                        row,
                        group_id,
                        AnomalyType.DUPLICATE,
                        vendor_name=name,
                        invoice_no=invoice,
                        txn_date=_clamp(when, self.first_day, self.last_day),
                    )
                )
                applied.append(
                    {
                        "name_mode": mode,
                        "invoice_mode": invoice_mode,
                        "shift_days": abs((when - row["txn_date"]).days),
                    }
                )

            self.records.append(
                TruthRecord(
                    injection_group_id=group_id,
                    injection_type=AnomalyType.DUPLICATE,
                    row_ids=ids,
                    source_row_ids=[row_id],
                    vendor_key=row["vendor_key"],
                    amount_at_risk=round(float(row["amount"]) * copies, 2),
                    params={"copies": copies, "perturbations": applied},
                )
            )
            made += 1
        self.shortfall[AnomalyType.DUPLICATE.value] += n - made

    # ------------------------------------------------------------ vendor flags

    def _new_vendor_name(self, taken: set[str]) -> str:
        trades = ("Consultants", "Associates", "Management Services", "Solutions", "Ventures")
        for _ in range(500):
            name = (
                f"{FIRM_WORDS[int(self.rng.integers(len(FIRM_WORDS)))]} "
                f"{SURNAMES[int(self.rng.integers(len(SURNAMES)))]} "
                f"{trades[int(self.rng.integers(len(trades)))]} Pvt Ltd"
            )
            key = normalize_vendor(name)
            if key not in taken:
                taken.add(key)
                return name
        raise RuntimeError("Could not synthesize a unique supplier name")

    def _service_categories(self) -> list[dict[str, Any]]:
        """Categories billed per unit of 1 at substantial prices - where a fake
        consultancy's invoices blend in without tripping the price detector."""
        stats = (
            self.frame.filter(pl.col("item_category").is_not_null())
            .group_by("item_category")
            .agg(
                pl.col("quantity").median().alias("median_qty"),
                pl.col("unit_price").median().alias("median_price"),
                pl.col("item_desc").first().alias("item_desc"),
                pl.len().alias("n"),
            )
            .filter(
                (pl.col("median_qty") == 1)
                & (pl.col("median_price") >= 10_000)
                & (pl.col("n") >= 5)
            )
            .sort("item_category")
        )
        return stats.to_dicts()

    def inject_vendor_flags(self, n: int) -> None:
        taken = set(self.frame.get_column("vendor_key").unique().to_list())
        officers = self.frame.get_column("officer_id").drop_nulls().unique().sort().to_list()
        services = self._service_categories()

        span = (self.last_day - self.first_day).days
        for _ in range(n):
            name = self._new_vendor_name(taken)
            group_id = self._group_id(AnomalyType.VENDOR_FLAG)
            onboard = self.first_day + timedelta(
                days=int(self.rng.integers(int(span * 0.55), max(int(span * 0.55) + 1, span - 60)))
            )
            days = [
                onboard + timedelta(days=i)
                for i in range((self.last_day - onboard).days + 1)
                if (onboard + timedelta(days=i)).weekday() < 5
            ]
            # Month-end and March-heavy: the pattern of spending to exhaust budget.
            end_heavy = [
                d for d in days if d.month == 3 or (d + timedelta(days=4)).month != d.month
            ]
            count = int(
                self.rng.integers(self.cfg.vendor_flag_min_rows, self.cfg.vendor_flag_max_rows + 1)
            )
            billed_to = (
                [
                    officers[int(i)]
                    for i in self.rng.choice(
                        len(officers), size=min(2, len(officers)), replace=False
                    )
                ]
                if officers
                else [None]
            )

            # How obvious this particular vendor is (D-25).
            round_share = float(self.rng.uniform(*self.cfg.vendor_flag_round_share))
            period_end_share = float(self.rng.uniform(*self.cfg.vendor_flag_period_end_share))

            ids: list[int] = []
            round_count = period_end_count = 0
            prefix = "".join(w[0] for w in name.split()[:3]).upper()
            for seq in range(count):
                at_period_end = bool(end_heavy) and self.rng.random() < period_end_share
                pool = end_heavy if at_period_end else days
                period_end_count += at_period_end
                when = pool[int(self.rng.integers(len(pool)))]
                service = services[int(self.rng.integers(len(services)))] if services else None

                # Priced within the category's normal range, so this tests the
                # vendor-flag detector alone and does not also trip the price one.
                typical = float(service["median_price"]) if service else 100_000.0
                raw = typical * float(self.rng.uniform(0.5, 1.4))
                if self.rng.random() < round_share:
                    amount = float(max(5_000, round(raw / 5_000) * 5_000))
                    round_count += 1
                else:
                    amount = round(raw, 2)

                template = {
                    "officer_id": billed_to[int(self.rng.integers(len(billed_to)))],
                    "item_desc": service["item_desc"] if service else "Professional Services",
                    "item_category": service["item_category"] if service else None,
                    "quantity": 1.0 if service else None,
                    "unit_price": amount if service else None,
                }
                ids.append(
                    self._new_row(
                        template,
                        group_id,
                        AnomalyType.VENDOR_FLAG,
                        vendor_name=name,
                        invoice_no=f"{prefix}/{seq + 1:03d}",
                        amount=amount,
                        txn_date=when,
                    )
                )

            amounts = [r["amount"] for r in self.new_rows[-count:]]
            self.records.append(
                TruthRecord(
                    injection_group_id=group_id,
                    injection_type=AnomalyType.VENDOR_FLAG,
                    row_ids=ids,
                    source_row_ids=[],
                    vendor_key=normalize_vendor(name),
                    amount_at_risk=round(float(sum(amounts)), 2),
                    params={
                        "vendor_name": name,
                        "onboarded": onboard.isoformat(),
                        "transactions": count,
                        "round_share": round(round_count / count, 3),
                        "period_end_share": round(period_end_count / count, 3),
                        "target_round_share": round(round_share, 3),
                        "target_period_end_share": round(period_end_share, 3),
                        "officers": billed_to,
                    },
                )
            )

    # ------------------------------------------------------------ assembly

    def assemble(self) -> pl.DataFrame:
        base = self.frame.filter(~pl.col("row_id").is_in(list(self.deleted)))
        if self.updates:
            changes = pl.DataFrame(self.updates).cast(
                {c: self.frame.schema[c] for c in self.updates[0] if c in self.frame.schema}
            )
            base = base.update(changes, on="row_id")
        if self.new_rows:
            added = pl.DataFrame(self.new_rows, schema=self.frame.schema)
            base = pl.concat([base, added])
        return base.sort("row_id")


# ------------------------------------------------------------------ public API


def default_injected_path(seed: int) -> Path:
    return settings.processed_data_dir / f"spendguard_injected_seed{seed}.duckdb"


def planned_counts(n_rows: int, n_vendors: int, cfg: InjectionConfig) -> dict[AnomalyType, int]:
    groups = max(1, round(n_rows * cfg.rate))
    return {
        AnomalyType.DUPLICATE: round(groups * cfg.duplicate_share),
        AnomalyType.SPLIT: round(groups * cfg.split_share),
        AnomalyType.INFLATION: round(groups * cfg.inflation_share),
        # Enough synthetic vendors that recall has finer resolution than 25% steps.
        AnomalyType.VENDOR_FLAG: cfg.vendor_flags
        if cfg.vendor_flags is not None
        else max(4, round(n_vendors * 0.02)),
    }


def inject(
    source_db: Path | None = None,
    out_db: Path | None = None,
    config: InjectionConfig | None = None,
) -> InjectionResult:
    """Copy the clean database and plant seeded anomalies in the copy."""
    cfg = config or InjectionConfig(seed=settings.random_seed)
    source_db = Path(source_db or settings.duckdb_path)
    out_db = Path(out_db or default_injected_path(cfg.seed))
    if source_db.resolve() == out_db.resolve():
        raise ValueError("Refusing to inject into the clean source database; choose another output")

    with connect(source_db, read_only=True) as con:
        frame = read_transactions(con)
        cards = (
            con.execute("SELECT * FROM dataset_cards").fetchall()
            if table_exists(con, "dataset_cards")
            else []
        )
    if frame.is_empty():
        raise ValueError(f"{source_db} has no transactions")
    if frame["is_injected"].any():
        raise ValueError(
            f"{source_db} already contains injected rows; inject from a clean database"
        )

    rng = np.random.default_rng(cfg.seed)
    plan = planned_counts(frame.height, frame["vendor_key"].n_unique(), cfg)
    injector = _Injector(frame, cfg, rng)
    # Splits first: they need scarce above-threshold rows. Duplicates last: any row will do.
    injector.inject_splits(plan[AnomalyType.SPLIT])
    injector.inject_inflation(plan[AnomalyType.INFLATION])
    injector.inject_duplicates(plan[AnomalyType.DUPLICATE])
    injector.inject_vendor_flags(plan[AnomalyType.VENDOR_FLAG])
    final = injector.assemble()

    records = injector.records
    groups = Counter(r.injection_type.value for r in records)
    at_risk: dict[str, float] = {}
    for r in records:
        at_risk[r.injection_type.value] = (
            at_risk.get(r.injection_type.value, 0.0) + r.amount_at_risk
        )
    touched = Counter(final.filter(pl.col("is_injected"))["injection_type"].to_list())

    result = InjectionResult(
        out_db=out_db,
        seed=cfg.seed,
        rows_before=frame.height,
        rows_after=final.height,
        groups={t.value: groups.get(t.value, 0) for t in AnomalyType},
        rows_injected={t.value: touched.get(t.value, 0) for t in AnomalyType},
        rows_deleted=len(injector.deleted),
        shortfall={k: v for k, v in injector.shortfall.items() if v},
        amount_at_risk={t.value: round(at_risk.get(t.value, 0.0), 2) for t in AnomalyType},
        records=records,
    )
    _write(out_db, final, records, cards, cfg, result)
    return result


def _write(
    out_db: Path,
    final: pl.DataFrame,
    records: list[TruthRecord],
    cards: list[tuple[Any, ...]],
    cfg: InjectionConfig,
    result: InjectionResult,
) -> None:
    for stale in (out_db, out_db.with_name(out_db.name + ".wal")):
        if stale.exists():
            stale.unlink()
    out_db.parent.mkdir(parents=True, exist_ok=True)

    with connect(out_db) as con:
        write_transactions(con, final)
        con.execute(GROUND_TRUTH_DDL)
        con.executemany(
            "INSERT INTO ground_truth VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    r.injection_group_id,
                    r.injection_type.value,
                    r.row_ids,
                    r.source_row_ids,
                    r.vendor_key,
                    r.amount_at_risk,
                    cfg.seed,
                    json.dumps(r.params, default=str),
                ]
                for r in records
            ],
        )
        con.execute(DATASET_CARDS_DDL)
        if cards:
            con.executemany("INSERT OR REPLACE INTO dataset_cards VALUES (?, ?, ?)", cards)
        con.execute(INJECTION_RUNS_DDL)
        summary = {k: v for k, v in asdict(result).items() if k not in {"records", "out_db"}}
        con.execute(
            "INSERT INTO injection_runs VALUES (?, ?, ?, ?)",
            [
                cfg.seed,
                datetime.now(UTC).replace(tzinfo=None),
                json.dumps(asdict(cfg), default=str),
                json.dumps(summary, default=str),
            ],
        )


__all__ = ["InjectionConfig", "InjectionResult", "TruthRecord", "default_injected_path", "inject"]
