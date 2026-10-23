"""Taking in a procurement file nobody has seen before (FR-1.3).

`spendguard ingest` assumes someone already wrote a mapping YAML describing the
source's columns. That is right for the two datasets this project ships, and
wrong for the first thing a new organisation does, which is hand the system a
CSV export and ask whether it can be used at all.

So this module answers that question **before** anything is written: read the
headers, guess which canonical field each one is, count how many rows would
survive cleaning, and say plainly what is missing. A preview is read-only by
construction - it opens the file and nothing else - which is why it is safe to
expose over HTTP where `ingest` is not.

Two rules worth stating, because both are about not destroying evidence:

1. **Ingesting never overwrites the dataset being served.** `ingest` replaces
   the `transactions` table in whatever DuckDB file it is given, so a new upload
   goes to a *new* file. Two datasets then sit side by side and can be compared;
   one cannot silently become the other.
2. **There is no edit path, here or anywhere.** A correction is a new ingestion
   of a corrected source, which leaves the original intact and comparable. An
   audit trail whose rows can be edited in place is not evidence, and the first
   question any auditor asks of this system is whether that is possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from spendguard.config import settings
from spendguard.pipeline.mapping import (
    MAPPABLE_FIELDS,
    REQUIRED_FIELDS,
    DatasetMapping,
)

# Header spellings seen in real procurement exports, most specific first. Matched
# against the header with case, spaces, underscores and punctuation removed, so
# "Supplier Name", "supplier_name" and "SUPPLIERNAME" are one key.
HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "vendor_name": ("suppliername", "vendorname", "payeename", "supplier", "vendor", "payee"),
    "amount": ("totalprice", "totalamount", "grossamount", "linetotal", "amount", "value"),
    "txn_date": ("transactiondate", "invoicedate", "orderdate", "postingdate", "date"),
    "invoice_no": ("invoicenumber", "invoiceno", "billno", "documentno", "ponumber", "invoice"),
    "officer_id": ("officerid", "department", "requisitioner", "buyer", "costcentre", "office"),
    "item_desc": ("itemdescription", "description", "lineitem", "particulars", "item"),
    "item_category": ("itemcategory", "category", "commodity", "class", "segment"),
    "quantity": ("quantity", "qty", "units"),
    "unit_price": ("unitprice", "rateperunit", "priceperunit", "rate", "price"),
}

SAMPLE_ROWS = 5

# Tried against the date column in order. `%d-%m-%Y` and `%m-%d-%Y` both parse
# "01-04-2024" into different months, which is why `detect_date_formats` reports
# every format that fits rather than returning the first.
CANDIDATE_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
)


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Guess which source column is which canonical field.

    A guess, offered for correction - never applied silently. Getting `amount`
    wrong would put a quantity into every severity score, so the preview shows
    what was guessed and the caller confirms it.

    Longest hint first, so "unitprice" is not claimed by the "price" hint that
    `unit_price` also matches; and a column already taken is not reused.
    """
    by_key = {_key(h): h for h in headers}
    taken: set[str] = set()
    guess: dict[str, str | None] = dict.fromkeys(MAPPABLE_FIELDS)

    for canonical in MAPPABLE_FIELDS:
        for hint in HEADER_HINTS.get(canonical, ()):
            exact = by_key.get(hint)
            if exact is not None and exact not in taken:
                guess[canonical] = exact
                taken.add(exact)
                break

    # Second pass, only for fields still unclaimed: a header that *contains* a
    # hint, and only when exactly one does - two candidates is not a guess.
    for canonical in MAPPABLE_FIELDS:
        if guess[canonical] is not None:
            continue
        for hint in HEADER_HINTS.get(canonical, ()):
            hits = [h for k, h in by_key.items() if hint in k and h not in taken]
            if len(hits) == 1:
                guess[canonical] = hits[0]
                taken.add(hits[0])
                break
    return guess


def detect_date_formats(values: list[str], *, threshold: float = 0.95) -> list[str]:
    """Every candidate format that parses essentially all of a column.

    Returns a list, not a best guess, because `01-04-2024` is 1 April under
    `%d-%m-%Y` and 4 January under `%m-%d-%Y` and nothing in the column itself
    settles which. A caller that silently took the first would mis-date a
    quarter of a year's transactions, and every duplicate and split window
    computed from them.
    """
    sample = [v.strip() for v in values if v and v.strip()]
    if not sample:
        return []
    needed = max(1, int(len(sample) * threshold))
    fits = []
    for fmt in CANDIDATE_DATE_FORMATS:
        parsed = 0
        for value in sample:
            try:
                datetime.strptime(value, fmt)  # noqa: DTZ007 - a date, not an instant
            except (ValueError, TypeError):
                continue
            parsed += 1
        if parsed >= needed:
            fits.append(fmt)
    return fits


def _is_ambiguous(fits: list[str]) -> bool:
    """Whether the fitting formats disagree about which number is the month."""
    day_first = {"%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"}
    month_first = {"%m-%d-%Y", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S"}
    return bool(set(fits) & day_first) and bool(set(fits) & month_first)


def candidates_for(canonical: str, headers: list[str]) -> list[str]:
    """Headers that could plausibly be this field, for when the guess declines.

    `suggest_mapping` deliberately returns nothing when two headers match equally
    well. That is the right call - picking the wrong date column silently would
    mis-date every case - but "no column looks like txn_date" is unhelpful when
    the file plainly has two. This names them.
    """
    keyed = {h: _key(h) for h in headers}
    hints = HEADER_HINTS.get(canonical, ())
    return [h for h, k in keyed.items() if any(hint in k for hint in hints)]


@dataclass(frozen=True)
class IntakePreview:
    """What a file would become, decided without writing anything."""

    filename: str
    rows: int
    headers: list[str]
    suggested: dict[str, str | None]
    unmapped_headers: list[str]
    missing_required: list[str]
    problems: list[str]
    # Every date format that fits the date column. More than one means the column
    # is ambiguous and the caller must choose; none means ingestion would drop
    # every row, which is the failure this preview exists to catch early.
    date_formats: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether `ingest` could run at all. Problems may remain either way."""
        return not self.missing_required and self.rows > 0 and len(self.date_formats) == 1


def _unparseable(frame: pl.DataFrame, column: str | None, expr: pl.Expr) -> int:
    if not column or column not in frame.columns:
        return 0
    non_null = frame.filter(pl.col(column).is_not_null() & (pl.col(column).cast(pl.Utf8) != ""))
    if non_null.is_empty():
        return 0
    return int(non_null.select(expr.is_null().sum()).item())


def preview(source: Path, *, sample_rows: int = SAMPLE_ROWS) -> IntakePreview:
    """Read a candidate file and report whether it can be audited.

    Reads the whole file to count rows honestly - a preview that guessed from the
    first hundred rows would miss exactly the date format that appears late and
    costs a tenth of the data.
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    try:
        frame = pl.read_csv(
            source, infer_schema_length=0, truncate_ragged_lines=True, ignore_errors=True
        )
    except Exception as exc:  # noqa: BLE001 - any malformed file lands here, and must be reported
        return IntakePreview(
            filename=source.name,
            rows=0,
            headers=[],
            suggested={},
            unmapped_headers=[],
            missing_required=list(REQUIRED_FIELDS),
            problems=[f"The file could not be read as CSV: {exc}"],
            date_formats=[],
        )

    headers = list(frame.columns)
    suggested = suggest_mapping(headers)
    used = {h for h in suggested.values() if h}
    missing = [f for f in REQUIRED_FIELDS if not suggested.get(f)]

    problems: list[str] = []
    if frame.height == 0:
        problems.append("The file has a header row but no data.")
    for canonical in missing:
        near = candidates_for(canonical, headers)
        if near:
            # Usually this means two columns matched and neither clearly wins -
            # the California export has both "Creation Date" and "Purchase Date",
            # and which one is the transaction date is a judgement its own mapping
            # records in a comment. Naming the two is useful; guessing is not.
            problems.append(
                f"`{canonical}` is required and more than one column could be it: "
                f"{', '.join(near)}. Choose one."
            )
        else:
            problems.append(
                f"No column looks like `{canonical}`, which is required. "
                f"The file has: {', '.join(headers[:12]) or '(none)'}"
                f"{' …' if len(headers) > 12 else ''}."
            )

    amount_column = suggested.get("amount")
    amount_bad = (
        _unparseable(
            frame,
            amount_column,
            pl.col(amount_column)
            .cast(pl.Utf8)
            .str.replace_all(r"[^0-9.\-]", "")
            .cast(pl.Float64, strict=False),
        )
        if amount_column
        else 0
    )
    if amount_bad:
        problems.append(
            f"{amount_bad:,} of {frame.height:,} rows have an amount that is not a number; "
            "ingestion would drop them."
        )
    if frame.height and amount_bad == frame.height:
        problems.append("Every amount failed to parse - the amount column is probably wrong.")

    # Dates last, because the answer decides whether the file is usable at all.
    # Checking amounts but not dates was the first version of this function, and
    # it reported "no problems" on a file whose every row was then dropped for an
    # unparseable date - a preview that does that is worse than none.
    date_column = suggested.get("txn_date")
    fits: list[str] = []
    if date_column and date_column in frame.columns:
        fits = detect_date_formats(frame[date_column].cast(pl.Utf8).to_list())
        if not fits:
            shown = [str(v) for v in frame[date_column].head(3).to_list()]
            problems.append(
                f"No known date format fits `{date_column}` (for example {', '.join(shown)}). "
                "Every row would be dropped. Check the column, or export dates as YYYY-MM-DD."
            )
        elif _is_ambiguous(fits):
            problems.append(
                f"`{date_column}` is ambiguous: values like "
                f"{frame[date_column].head(1).to_list()[0]} parse as both day-month and "
                "month-day, which are different dates. Choose the format deliberately."
            )

    return IntakePreview(
        filename=source.name,
        rows=frame.height,
        headers=headers,
        suggested=suggested,
        unmapped_headers=sorted(h for h in headers if h not in used),
        missing_required=missing,
        problems=problems,
        date_formats=fits,
        sample=frame.head(sample_rows).to_dicts(),
    )


def mapping_from(
    dataset: str,
    columns: dict[str, str | None],
    *,
    date_formats: list[str] | None = None,
    description: str = "",
) -> DatasetMapping:
    """A mapping for an uploaded file, without a YAML on disk to load it from."""
    return DatasetMapping(
        dataset=dataset,
        description=description or f"Uploaded {dataset}",
        date_formats=date_formats or ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y"],
        columns={f: columns.get(f) for f in MAPPABLE_FIELDS},
    )


def dataset_db_path(dataset: str) -> Path:
    """Where an uploaded dataset's own DuckDB file lives.

    Its own file, never the one being served: `ingest` replaces the whole
    `transactions` table, so sharing a file would mean a new upload silently
    deleting the data a reviewer is working through.
    """
    return settings.processed_data_dir / f"{dataset}.duckdb"


def is_protected(db_path: Path) -> bool:
    """Whether writing here would overwrite data the system is already using."""
    reserved = {
        settings.duckdb_path.resolve(),
        (settings.processed_data_dir / "california.duckdb").resolve(),
    }
    return db_path.resolve() in reserved
