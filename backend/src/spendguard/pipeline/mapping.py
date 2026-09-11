"""Per-dataset column mapping (docs/REQUIREMENTS.md FR-1.3, FR-1.6, FR-1.8).

Every source system names its columns differently. The mapping file is the only
place that knowledge lives - never the ingestion code. Adding a dataset means
writing a YAML file, not editing Python.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spendguard.config import settings

# Canonical fields a source column may be mapped onto.
MAPPABLE_FIELDS: tuple[str, ...] = (
    "vendor_name",
    "invoice_no",
    "amount",
    "txn_date",
    "officer_id",
    "item_desc",
    "item_category",
    "quantity",
    "unit_price",
)

# Without these a row cannot be audited at all.
REQUIRED_FIELDS: tuple[str, ...] = ("vendor_name", "amount", "txn_date")


class DatasetMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str = ""

    # Decision D-15: non-INR sources convert at a rate pinned here, never live.
    source_currency: str = "INR"
    fx_rate_to_inr: float | None = None
    fx_rate_date: date | None = None

    date_formats: list[str] = Field(min_length=1)

    # canonical field -> source header; null means the source has no such column
    columns: dict[str, str | None]

    # Source column holding a stable row identifier, for auditing ingestion itself.
    source_row_ref: str | None = None

    @field_validator("source_currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("columns")
    @classmethod
    def _known_fields(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        unknown = set(v) - set(MAPPABLE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown canonical fields in mapping: {sorted(unknown)}")
        missing = [f for f in REQUIRED_FIELDS if not v.get(f)]
        if missing:
            raise ValueError(f"Mapping must provide a source column for {missing}")
        # Absent optional fields are explicit nulls, not silently missing keys.
        return {f: v.get(f) for f in MAPPABLE_FIELDS}

    @model_validator(mode="after")
    def _currency_rules(self) -> DatasetMapping:
        if self.source_currency == settings.currency:
            if self.fx_rate_to_inr not in (None, 1.0):
                raise ValueError(
                    f"{self.dataset}: source is already {settings.currency}; "
                    "fx_rate_to_inr must be omitted or 1.0"
                )
        else:
            if not self.fx_rate_to_inr or self.fx_rate_to_inr <= 0:
                raise ValueError(
                    f"{self.dataset}: source currency {self.source_currency} needs a pinned, "
                    "positive fx_rate_to_inr (decision D-15 - never a live rate)"
                )
            if self.fx_rate_date is None:
                raise ValueError(
                    f"{self.dataset}: fx_rate_date is required so the pinned rate is auditable"
                )
        return self

    @property
    def fx_rate(self) -> float:
        return self.fx_rate_to_inr or 1.0

    @property
    def is_converted(self) -> bool:
        return self.source_currency != settings.currency

    def source_headers(self) -> list[str]:
        """Every source header this mapping expects to find in the file."""
        headers = [h for h in self.columns.values() if h]
        if self.source_row_ref:
            headers.append(self.source_row_ref)
        return headers


def load_mapping(name_or_path: str | Path) -> DatasetMapping:
    """Load a mapping by dataset name (from ``backend/mappings``) or by file path."""
    path = Path(name_or_path)
    if not path.suffix:
        path = settings.mappings_dir / f"{name_or_path}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in settings.mappings_dir.glob("*.yaml"))
        raise FileNotFoundError(f"No mapping at {path}. Available: {available}")
    with path.open(encoding="utf-8") as fh:
        return DatasetMapping.model_validate(yaml.safe_load(fh))
