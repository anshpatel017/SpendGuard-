"""Seeded, INR-native synthetic procurement data.

This produces the *clean* baseline: legitimate procurement with the texture of
real Indian public-sector spend. It deliberately contains the things that make
fraud detection hard, because a detector that only works on tidy data proves
nothing:

* **legitimate name variants** - the same supplier typed as "Sharma Traders Pvt
  Ltd", "SHARMA TRADERS", "M/s Sharma Traders Private Limited"
* **legitimate recurring contracts** - security and housekeeping billed the same
  amount every month, which a naive duplicate detector will wrongly flag
* **sticky officer-supplier relationships** - the same officer buying from the
  same supplier repeatedly, which a naive split detector will wrongly flag
* **seasonality** - the March year-end rush and month-end clustering that
  government spending genuinely shows, which a naive vendor-flag detector will
  wrongly flag
* **price drift, bulk discounts, spec tiers and urgent purchases** - so unit
  prices within one category legitimately span 0.7x to beyond 2x, and an honest
  premium purchase can look like inflation, as it does in real data
* **dirty formatting** and a few **malformed rows** - so ingestion is exercised

It contains **no anomalies**. Frauds are added later by the injection harness,
which is how ground truth is known exactly (docs/EVALUATION.md).

Everything is drawn from one ``numpy`` Generator, so a seed reproduces the output
byte for byte.
"""

from __future__ import annotations

import calendar as _calendar
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from spendguard.config import settings
from spendguard.pipeline.catalogue import (
    CATEGORIES,
    CATEGORIES_BY_NAME,
    DEPARTMENTS,
    FIRM_WORDS,
    GENERAL_CATEGORIES,
    LEGAL_SUFFIXES,
    SURNAMES,
    Category,
    Department,
    Item,
)
from spendguard.pipeline.perturb import legitimate_variant
from spendguard.pipeline.vendors import identity_name

DATASET_NAME = "synthetic_inr"

# Canonical field -> the header the generator writes. Deliberately *not* the
# canonical names, so ingestion's column mapping is genuinely exercised.
SOURCE_COLUMNS: dict[str, str] = {
    "source_row_ref": "Voucher No",
    "txn_date": "Invoice Date",
    "vendor_name": "Supplier Name",
    "invoice_no": "Invoice Number",
    "department": "Department",  # present in the file, not mapped - ingestion must ignore it
    "officer_id": "Requesting Officer",
    "item_category": "Commodity Category",
    "item_desc": "Item Description",
    "quantity": "Qty",
    "unit_price": "Rate (INR)",
    "amount": "Invoice Amount (INR)",
}

DATE_FORMAT = "%d-%m-%Y"  # Indian convention

# Cosmetic mess that ingestion must *clean* - the row survives.
DIRT_TYPES: tuple[str, ...] = (
    "amount_rupee_format",
    "vendor_padding",
    "blank_quantity",
    "bad_quantity",
    "blank_category",
    "blank_officer",
)

# Defects that make a row unusable - ingestion must *drop* and count it.
MALFORMED_TYPES: tuple[str, ...] = (
    "amount_not_available",
    "impossible_date",
    "blank_supplier",
    "zero_amount",
)


@dataclass(frozen=True)
class GeneratorConfig:
    n_transactions: int = 50_000
    seed: int = 42
    start_date: date = date(2024, 4, 1)  # FY 2024-25
    end_date: date = date(2026, 3, 31)  # through FY 2025-26
    n_vendors: int | None = None  # None -> scaled from n_transactions
    legit_variant_rate: float = 0.12
    dirt_rate: float = 0.01
    malformed_rate: float = 0.002
    preferred_vendor_rate: float = 0.60
    annual_price_drift: float = 0.06
    urgent_rate: float = 0.02  # emergency purchases at a legitimate premium

    def __post_init__(self) -> None:
        if self.n_transactions < 500:
            raise ValueError("n_transactions must be at least 500 for realistic structure")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        for name in (
            "legit_variant_rate",
            "dirt_rate",
            "malformed_rate",
            "preferred_vendor_rate",
            "urgent_rate",
        ):
            value = getattr(self, name)
            if not 0 <= value < 1:
                raise ValueError(f"{name} must be in [0, 1), got {value}")

    @property
    def vendor_count(self) -> int:
        if self.n_vendors is not None:
            return self.n_vendors
        return int(min(1_500, max(80, self.n_transactions / 125)))

    @property
    def contract_count(self) -> int:
        return max(3, round(self.n_transactions / 1_700))


@dataclass
class SyntheticDataset:
    """A generated dataset: what goes to disk, what only the harness may know, and counts."""

    frame: pl.DataFrame  # exactly what is written to CSV - all strings
    truth: pl.DataFrame  # per-voucher ground truth (true supplier, defects) - never ingested
    report: dict[str, object]
    config: GeneratorConfig


# --------------------------------------------------------------------- internals


@dataclass
class _Officer:
    officer_id: str
    department: Department


@dataclass
class _Vendor:
    idx: int
    name: str
    categories: list[Category]
    weight: float
    price_level: float
    onboard_idx: int  # first calendar day this supplier can be paid
    invoice_style: int
    invoice_prefix: str
    seq: int
    fy_seq: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def vendor_id(self) -> str:
        return f"V{self.idx:05d}"


@dataclass
class _Row:
    vendor: _Vendor
    officer: _Officer
    category: Category
    item_name: str  # the commodity - what the category label is built from
    item_desc: str  # what the invoice says, which may add a grade or urgency
    quantity: int
    unit_price: float
    amount: float
    txn_date: date
    is_recurring: bool
    invoice_no: str = ""


class _Calendar:
    """Working-day calendar with realistic spending seasonality.

    Weekends are near-silent, March carries the financial-year-end rush, and the
    last days of each month are a little busier. Sampling a date after a given
    day (a supplier's onboarding) uses the cumulative weights directly.
    """

    def __init__(self, start: date, end: date) -> None:
        self.days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        weights = np.array([self._weight(d) for d in self.days], dtype=float)
        self.cumulative = np.cumsum(weights)

    @staticmethod
    def _weight(d: date) -> float:
        w = {5: 0.25, 6: 0.05}.get(d.weekday(), 1.0)  # Saturday, Sunday
        if d.month == 3:
            w *= 1.8
        if d.day > _calendar.monthrange(d.year, d.month)[1] - 3:
            w *= 1.3
        return w

    def sample(self, rng: np.random.Generator, not_before: int = 0) -> int:
        low = self.cumulative[not_before - 1] if not_before > 0 else 0.0
        u = rng.uniform(low, self.cumulative[-1])
        return min(int(np.searchsorted(self.cumulative, u, side="right")), len(self.days) - 1)

    def index_of(self, d: date) -> int:
        return (d - self.days[0]).days


def _weighted_pick(rng: np.random.Generator, cumulative: np.ndarray) -> int:
    return int(np.searchsorted(cumulative, rng.uniform(0, cumulative[-1]), side="right"))


def _fy_label(d: date) -> str:
    """Indian financial year label: 12 Jan 2025 -> '24-25'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _round_price(value: float, step: float) -> float:
    if step >= 1:
        return max(step, round(value / step) * step)
    return max(0.01, round(value, 2))


def _indian_grouping(amount: float) -> str:
    return settings.money(amount).lstrip(settings.currency_symbol)


def _build_officers(rng: np.random.Generator) -> tuple[list[_Officer], np.ndarray]:
    officers: list[_Officer] = []
    weights: list[float] = []
    for dept in DEPARTMENTS:
        numbers = sorted(rng.choice(np.arange(1, 60), size=dept.n_officers, replace=False))
        for n in numbers:
            officers.append(_Officer(f"{dept.code}-{int(n):03d}", dept))
            weights.append(dept.activity / dept.n_officers)
    return officers, np.cumsum(weights)


def _supplier_name(rng: np.random.Generator, category: Category, taken: set[str]) -> str:
    suffixes = [s for s, _ in LEGAL_SUFFIXES]
    probs = np.array([p for _, p in LEGAL_SUFFIXES])
    probs = probs / probs.sum()

    for attempt in range(200):
        pool = SURNAMES if rng.random() < 0.5 else FIRM_WORDS
        stem = pool[int(rng.integers(len(pool)))]
        if attempt > 50:  # namespace getting crowded: two stems
            stem = f"{stem} {SURNAMES[int(rng.integers(len(SURNAMES)))]}"
        trade = category.trade_words[int(rng.integers(len(category.trade_words)))]
        suffix = suffixes[int(rng.choice(len(suffixes), p=probs))]
        name = f"{stem} {trade} {suffix}".strip()

        identity = identity_name(name)
        if identity not in taken:
            taken.add(identity)
            return name
    raise RuntimeError("Could not generate a unique supplier name")


def _build_vendors(rng: np.random.Generator, cfg: GeneratorConfig, cal: _Calendar) -> list[_Vendor]:
    n = cfg.vendor_count
    if n < 3 * len(CATEGORIES):
        raise ValueError(f"Need at least {3 * len(CATEGORIES)} vendors, got {n}")

    # Every category gets at least three suppliers; the rest follow market weight.
    market = np.array([c.market_weight for c in CATEGORIES])
    primary = [i for i in range(len(CATEGORIES)) for _ in range(3)]
    primary += list(rng.choice(len(CATEGORIES), size=n - len(primary), p=market / market.sum()))
    rng.shuffle(primary)

    # Zipf-like size distribution: a few suppliers win most of the business.
    ranks = rng.permutation(n) + 1
    taken: set[str] = set()
    vendors: list[_Vendor] = []

    for idx, cat_idx in enumerate(primary):
        category = CATEGORIES[int(cat_idx)]
        categories = [category]
        siblings = [c for c in CATEGORIES if c.group == category.group and c is not category]
        if siblings and rng.random() < 0.3:
            categories.append(siblings[int(rng.integers(len(siblings)))])

        name = _supplier_name(rng, category, taken)
        initials = "".join(w[0] for w in name.split() if w[0].isalpha())[:3].upper() or "SUP"

        vendors.append(
            _Vendor(
                idx=idx + 1,
                name=name,
                categories=categories,
                weight=1.0 / float(ranks[idx]) ** 0.8,
                price_level=float(rng.lognormal(0.0, 0.05)),
                # 70% are established suppliers; the rest onboard during the period.
                onboard_idx=0
                if rng.random() < 0.7
                else int(rng.integers(0, max(1, len(cal.days) - 90))),
                invoice_style=int(rng.integers(5)),
                invoice_prefix=initials,
                seq=int(rng.integers(1, 800)),
            )
        )
    return vendors


def _vendors_by_category(vendors: list[_Vendor]) -> dict[str, tuple[list[_Vendor], np.ndarray]]:
    grouped: dict[str, list[_Vendor]] = defaultdict(list)
    for v in vendors:
        for c in v.categories:
            grouped[c.name].append(v)
    return {name: (vs, np.cumsum([v.weight for v in vs])) for name, vs in grouped.items()}


def _recurring_rows(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    vendors: list[_Vendor],
    officers: list[_Officer],
    cal: _Calendar,
) -> tuple[list[_Row], int]:
    """Fixed monthly service contracts - the legitimate pattern D1 must not flag."""
    by_category = _vendors_by_category(vendors)
    contract_items = [
        (c, item) for c in CATEGORIES for item in c.recurring_items if c.name in by_category
    ]
    if not contract_items:
        return [], 0

    months: list[tuple[int, int]] = []
    y, m = cfg.start_date.year, cfg.start_date.month
    while date(y, m, 1) <= cfg.end_date:
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    admin = [o for o in officers if o.department.code == "ADM"]
    rows: list[_Row] = []
    contracts = 0

    for _ in range(cfg.contract_count):
        category, item = contract_items[int(rng.integers(len(contract_items)))]
        candidates, cumulative = by_category[category.name]
        vendor = candidates[_weighted_pick(rng, cumulative)]
        pool = admin if (admin and rng.random() < 0.7) else officers
        officer = pool[int(rng.integers(len(pool)))]

        monthly = _round_price(item.base_price * float(rng.lognormal(0.0, 0.15)), category.round_to)
        onboard = cal.days[vendor.onboard_idx]
        first = next(
            (i for i, (yy, mm) in enumerate(months) if date(yy, mm, 1) > onboard), len(months)
        )
        if first >= len(months) - 3:
            continue
        start = int(rng.integers(first, min(first + 12, len(months) - 3)))
        duration = int(rng.integers(12, 25))
        pay_day = int(rng.integers(1, 11))
        contracts += 1

        for yy, mm in months[start : start + duration]:
            last_day = _calendar.monthrange(yy, mm)[1]
            day = min(last_day, max(1, pay_day + int(rng.integers(-2, 3))))
            when = date(yy, mm, day)
            while when.weekday() >= 5:  # paid on a working day
                when += timedelta(days=1)
            if when > cfg.end_date:
                break
            service_month = (date(yy, mm, 1) - timedelta(days=1)).strftime("%b-%Y")
            rows.append(
                _Row(
                    vendor=vendor,
                    officer=officer,
                    category=category,
                    item_name=item.name,
                    item_desc=f"{item.name} for {service_month}",
                    quantity=1,
                    unit_price=monthly,
                    amount=monthly,
                    txn_date=when,
                    is_recurring=True,
                )
            )
    return rows, contracts


def _pick_category(rng: np.random.Generator, dept: Department) -> Category:
    if rng.random() < 0.10:
        return CATEGORIES_BY_NAME[GENERAL_CATEGORIES[int(rng.integers(len(GENERAL_CATEGORIES)))]]
    weights = np.array([1.0 / (1 + 0.35 * i) for i in range(len(dept.categories))])
    return CATEGORIES_BY_NAME[dept.categories[_weighted_pick(rng, np.cumsum(weights))]]


def _regular_rows(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    n_rows: int,
    vendors: list[_Vendor],
    officers: list[_Officer],
    officer_cumulative: np.ndarray,
    cal: _Calendar,
) -> list[_Row]:
    """Ad hoc purchases of goods and one-off services."""
    by_category = _vendors_by_category(vendors)
    preferred: dict[tuple[str, str], _Vendor] = {}
    rows: list[_Row] = []

    for _ in range(n_rows):
        officer = officers[_weighted_pick(rng, officer_cumulative)]
        category = _pick_category(rng, officer.department)
        candidates, cumulative = by_category[category.name]

        key = (officer.officer_id, category.name)
        if key not in preferred:
            preferred[key] = candidates[_weighted_pick(rng, cumulative)]
        if rng.random() < cfg.preferred_vendor_rate:
            vendor = preferred[key]
        else:
            vendor = candidates[_weighted_pick(rng, cumulative)]

        items = category.regular_items
        item: Item = items[int(rng.integers(len(items)))]
        day = cal.days[cal.sample(rng, not_before=vendor.onboard_idx)]

        # Skewed toward small orders: most purchases are modest.
        span = item.qty_max - item.qty_min + 1
        quantity = min(item.qty_max, item.qty_min + int(span * rng.random() ** 2))

        # Legitimate reasons one category's unit prices spread far apart. Without
        # them no honest purchase ever looks expensive, and any price detector -
        # even a naive one - scores a meaningless perfect precision.
        tier, tier_factor = _spec_tier(rng)
        urgent = rng.random() < cfg.urgent_rate
        if urgent:
            tier_factor *= float(rng.uniform(1.3, 2.0))

        years = (day - cfg.start_date).days / 365.25
        price = (
            item.base_price
            * tier_factor
            * vendor.price_level
            * float(rng.lognormal(0.0, category.price_sigma))
            * (1 + cfg.annual_price_drift * years)
            * max(0.85, 1 - 0.04 * math.log10(quantity))  # bulk discount
        )
        unit_price = _round_price(price, category.round_to)

        # Half the time the invoice says why it cost what it did; half it does not.
        desc = item.name
        if tier and rng.random() < 0.5:
            desc = f"{desc} - {tier} Grade"
        if urgent and rng.random() < 0.5:
            desc = f"{desc} (Urgent Supply)"

        rows.append(
            _Row(
                vendor=vendor,
                officer=officer,
                category=category,
                item_name=item.name,
                item_desc=desc,
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                txn_date=day,
                is_recurring=False,
            )
        )
    return rows


def _spec_tier(rng: np.random.Generator) -> tuple[str, float]:
    """Economy, standard or premium specification of the same commodity."""
    draw = rng.random()
    if draw < 0.10:
        return "Economy", float(rng.uniform(0.70, 0.85))
    if draw < 0.30:
        return "Premium", float(rng.uniform(1.35, 1.70))
    return "", 1.0


def _assign_invoice_numbers(rows: list[_Row]) -> None:
    """Per-supplier sequential invoice numbers, each supplier in its own house style."""
    for row in rows:  # rows are already in date order
        v, d = row.vendor, row.txn_date
        v.seq += 1
        fy = _fy_label(d)
        v.fy_seq[fy] += 1
        row.invoice_no = (
            f"INV-{v.seq:05d}",
            f"{v.invoice_prefix}/{fy}/{v.fy_seq[fy]:03d}",
            f"{v.seq}",
            f"{v.invoice_prefix}-{d.year % 100:02d}{v.seq:04d}",
            f"BILL/{v.seq:04d}",
        )[v.invoice_style]


def _render(
    rng: np.random.Generator, cfg: GeneratorConfig, rows: list[_Row]
) -> tuple[pl.DataFrame, pl.DataFrame, Counter[str], Counter[str], int]:
    """Turn rows into the strings a real export would contain, dirt and defects included."""
    n = len(rows)
    order = rng.permutation(n)
    n_malformed = round(n * cfg.malformed_rate)
    n_dirty = round(n * cfg.dirt_rate)
    defect: dict[int, str] = {}
    for i in order[:n_malformed]:
        defect[int(i)] = MALFORMED_TYPES[int(rng.integers(len(MALFORMED_TYPES)))]
    for i in order[n_malformed : n_malformed + n_dirty]:
        defect[int(i)] = DIRT_TYPES[int(rng.integers(len(DIRT_TYPES)))]

    columns: dict[str, list[str]] = {header: [] for header in SOURCE_COLUMNS.values()}
    truth: dict[str, list[object]] = {
        "voucher_no": [],
        "vendor_id": [],
        "canonical_vendor_name": [],
        "written_vendor_name": [],
        "is_recurring": [],
        "defect": [],
    }
    malformed: Counter[str] = Counter()
    dirty: Counter[str] = Counter()
    variants = 0

    for i, row in enumerate(rows):
        kind = defect.get(i)

        vendor_name = row.vendor.name
        if rng.random() < cfg.legit_variant_rate:
            vendor_name = legitimate_variant(vendor_name, rng)
            variants += 1

        out = {
            "source_row_ref": f"PV-{i + 1:07d}",
            "txn_date": row.txn_date.strftime(DATE_FORMAT),
            "vendor_name": vendor_name,
            "invoice_no": row.invoice_no,
            "department": row.officer.department.name,
            "officer_id": row.officer.officer_id,
            "item_category": f"{row.category.name} / {row.item_name}",
            "item_desc": row.item_desc,
            "quantity": str(row.quantity),
            "unit_price": f"{row.unit_price:.2f}",
            "amount": f"{row.amount:.2f}",
        }

        if kind in MALFORMED_TYPES:
            malformed[kind] += 1
            if kind == "amount_not_available":
                out["amount"] = "N/A"
            elif kind == "impossible_date":
                out["txn_date"] = f"31-02-{row.txn_date.year}"
            elif kind == "blank_supplier":
                out["vendor_name"] = ""
            elif kind == "zero_amount":
                out["amount"] = "0.00"
        elif kind in DIRT_TYPES:
            dirty[kind] += 1
            if kind == "amount_rupee_format":
                prefix = ("Rs. ", "₹", "INR ")[int(rng.integers(3))]
                out["amount"] = f"{prefix}{_indian_grouping(row.amount)}"
            elif kind == "vendor_padding":
                out["vendor_name"] = f"  {vendor_name}   "
            elif kind == "blank_quantity":
                out["quantity"] = ""
            elif kind == "bad_quantity":
                out["quantity"] = "NA"
            elif kind == "blank_category":
                out["item_category"] = ""
            elif kind == "blank_officer":
                out["officer_id"] = ""

        for canonical, header in SOURCE_COLUMNS.items():
            columns[header].append(out[canonical])

        truth["voucher_no"].append(out["source_row_ref"])
        truth["vendor_id"].append(row.vendor.vendor_id)
        truth["canonical_vendor_name"].append(row.vendor.name)
        truth["written_vendor_name"].append(out["vendor_name"])
        truth["is_recurring"].append(row.is_recurring)
        truth["defect"].append(kind)

    frame = pl.DataFrame(columns, schema={h: pl.String for h in columns})
    truth_frame = pl.DataFrame(
        truth,
        schema={
            "voucher_no": pl.String,
            "vendor_id": pl.String,
            "canonical_vendor_name": pl.String,
            "written_vendor_name": pl.String,
            "is_recurring": pl.Boolean,
            "defect": pl.String,
        },
    )
    return frame, truth_frame, malformed, dirty, variants


# --------------------------------------------------------------------- public API


def generate(config: GeneratorConfig | None = None) -> SyntheticDataset:
    """Generate a clean, realistic, seeded INR procurement dataset."""
    cfg = config or GeneratorConfig(seed=settings.random_seed)
    rng = np.random.default_rng(cfg.seed)

    cal = _Calendar(cfg.start_date, cfg.end_date)
    officers, officer_cumulative = _build_officers(rng)
    vendors = _build_vendors(rng, cfg, cal)

    recurring, contracts = _recurring_rows(rng, cfg, vendors, officers, cal)
    recurring = recurring[: cfg.n_transactions]
    regular = _regular_rows(
        rng, cfg, cfg.n_transactions - len(recurring), vendors, officers, officer_cumulative, cal
    )

    rows = recurring + regular
    rows.sort(key=lambda r: (r.txn_date, r.vendor.idx, r.officer.officer_id))
    _assign_invoice_numbers(rows)

    frame, truth, malformed, dirty, variants = _render(rng, cfg, rows)

    amounts = np.array([r.amount for r in rows])
    report: dict[str, object] = {
        "dataset": DATASET_NAME,
        "seed": cfg.seed,
        "rows": len(rows),
        "vendors": len(vendors),
        "officers": len(officers),
        "departments": len(DEPARTMENTS),
        "recurring_contracts": contracts,
        "recurring_rows": len(recurring),
        "legitimate_name_variants": variants,
        "dirty_rows": dict(sorted(dirty.items())),
        "malformed_rows": dict(sorted(malformed.items())),
        "rows_above_approval_threshold": int((amounts >= settings.approval_threshold).sum()),
        "total_amount": float(amounts.sum()),
        "date_range": [cfg.start_date.isoformat(), cfg.end_date.isoformat()],
    }
    return SyntheticDataset(frame=frame, truth=truth, report=report, config=cfg)


def default_output_path(config: GeneratorConfig) -> Path:
    return settings.raw_data_dir / f"{DATASET_NAME}_seed{config.seed}_{config.n_transactions}.csv"


def write(dataset: SyntheticDataset, path: Path) -> tuple[Path, Path]:
    """Write the CSV, plus a sidecar parquet of ground truth that ingestion never reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.frame.write_csv(path)
    truth_path = path.with_name(f"{path.stem}.truth.parquet")
    dataset.truth.write_parquet(truth_path)
    return path, truth_path
