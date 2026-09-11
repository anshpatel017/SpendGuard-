"""The Case object: deterministic identity and the stage-1 severity model (D-02, D-08)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spendguard.cases import AnomalyType, Case, severity_prelim
from spendguard.config import settings


def _case(**overrides: object) -> Case:
    fields: dict[str, object] = {
        "detector": "d1",
        "anomaly_type": AnomalyType.DUPLICATE,
        "row_ids": [7, 3],
        "detector_score": 0.8,
        "amount_at_risk": 50_000.0,
    }
    fields.update(overrides)
    return Case.build(**fields)  # type: ignore[arg-type]


def test_case_id_is_deterministic() -> None:
    assert _case().case_id == _case().case_id


def test_case_id_ignores_row_order() -> None:
    assert _case(row_ids=[3, 7]).case_id == _case(row_ids=[7, 3, 3]).case_id


def test_case_id_depends_on_detector_type_and_rows() -> None:
    base = _case().case_id
    assert _case(detector="baseline").case_id != base
    assert _case(anomaly_type=AnomalyType.SPLIT).case_id != base
    assert _case(row_ids=[3, 8]).case_id != base


def test_row_ids_are_sorted_and_unique() -> None:
    assert _case(row_ids=[9, 2, 9, 5]).row_ids == (2, 5, 9)


def test_empty_row_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _case(row_ids=[])


@pytest.mark.parametrize("score", [-0.1, 1.01])
def test_score_outside_unit_interval_is_rejected(score: float) -> None:
    with pytest.raises(ValidationError):
        _case(detector_score=score)


def test_severity_is_zero_when_detector_has_no_confidence() -> None:
    assert severity_prelim(0.0, 10_000_000) == 0.0


def test_severity_saturates_at_the_reference_amount() -> None:
    reference = settings.severity_reference_amount
    assert severity_prelim(1.0, reference) == 100.0
    assert severity_prelim(1.0, reference * 50) == 100.0


def test_severity_grows_with_amount_and_confidence() -> None:
    assert severity_prelim(0.9, 10_000) < severity_prelim(0.9, 1_000_000)
    assert severity_prelim(0.3, 1_000_000) < severity_prelim(0.9, 1_000_000)


def test_severity_is_stable_across_runs() -> None:
    """O-03: a fixed reference, so the same case scores the same in every run."""
    assert _case().severity_prelim == _case().severity_prelim


def test_band_follows_severity() -> None:
    assert _case(detector_score=1.0, amount_at_risk=5_000_000).severity_band == "high"
    assert _case(detector_score=0.1, amount_at_risk=500).severity_band == "low"
