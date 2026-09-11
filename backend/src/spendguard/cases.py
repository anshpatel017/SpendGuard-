"""The Case - one anomaly group, the unit every detector emits (decision D-02).

    duplicate pair            -> 1 case, 2 row_ids
    split of five POs         -> 1 case, 5 row_ids
    inflated line item        -> 1 case, 1 row_id
    vendor red flag           -> 1 case, that vendor's row_ids

This is the detection-side half of the Case contract in docs/API-CONTRACT.md.
Operational fields - status, reviewer note, investigation state - belong to
the case store and are added when a case is persisted, not by detectors.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spendguard.config import settings

# Fixed namespace: the same detector flagging the same rows always yields the
# same case_id, on any machine, in any run. Reproducibility is graded.
_CASE_NAMESPACE = uuid.UUID("7a1c4e52-3b9d-4f0a-9c61-5e2d8b0f1a34")


class AnomalyType(StrEnum):
    DUPLICATE = "duplicate"
    SPLIT = "split"
    INFLATION = "inflation"
    VENDOR_FLAG = "vendor_flag"


def severity_prelim(detector_score: float, amount_at_risk: float) -> float:
    """Stage-1 severity, 0-100 (decision D-08).

        100 * detector_score * log1p(amount) / log1p(reference_amount)

    The reference amount is a fixed constant rather than the run maximum, so one
    unusually large transaction cannot rescale every other case, and a case gets
    the same severity in the demo run, the evaluation run and every ablation
    (open issue O-03). Amounts above the reference saturate at weight 1.
    """
    weight = math.log1p(max(amount_at_risk, 0.0)) / math.log1p(settings.severity_reference_amount)
    return round(100.0 * detector_score * min(weight, 1.0), 2)


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    anomaly_type: AnomalyType
    detector: str
    row_ids: tuple[int, ...] = Field(min_length=1)
    detector_score: float = Field(ge=0.0, le=1.0)
    amount_at_risk: float = Field(ge=0.0)
    severity_prelim: float = Field(ge=0.0, le=100.0)
    vendor_key: str | None = None  # required for vendor-level matching (decision D-03)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("row_ids")
    @classmethod
    def _sorted_unique(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(set(v)))

    @classmethod
    def build(
        cls,
        *,
        detector: str,
        anomaly_type: AnomalyType,
        row_ids: Iterable[int],
        detector_score: float,
        amount_at_risk: float,
        vendor_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Case:
        """Construct a case, deriving its deterministic id and preliminary severity."""
        rows = tuple(sorted({int(r) for r in row_ids}))
        identity = f"{detector}|{anomaly_type.value}|{','.join(map(str, rows))}"
        amount = max(float(amount_at_risk), 0.0)
        return cls(
            case_id=str(uuid.uuid5(_CASE_NAMESPACE, identity)),
            anomaly_type=anomaly_type,
            detector=detector,
            row_ids=rows,
            detector_score=float(detector_score),
            amount_at_risk=round(amount, 2),
            severity_prelim=severity_prelim(detector_score, amount),
            vendor_key=vendor_key,
            metadata=metadata or {},
        )

    @property
    def severity_band(self) -> str:
        return settings.band_for(self.severity_prelim).value
