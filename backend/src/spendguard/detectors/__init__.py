"""Detectors. Each implements ``detect(con) -> list[Case]`` over the audit view."""

from spendguard.detectors.base import Detector
from spendguard.detectors.baseline import BaselineDetector
from spendguard.detectors.d1_duplicates import DuplicateDetector
from spendguard.detectors.d2_splits import SplitDetector

# Name -> detector class. Phase 4 registers d3 and d4 here.
REGISTRY: dict[str, type[Detector]] = {
    BaselineDetector.name: BaselineDetector,
    DuplicateDetector.name: DuplicateDetector,
    SplitDetector.name: SplitDetector,
}

# What `spendguard detect` runs by default. The baseline is a benchmark, not a product.
PRODUCTION_DETECTORS: tuple[str, ...] = (DuplicateDetector.name, SplitDetector.name)

__all__ = [
    "PRODUCTION_DETECTORS",
    "REGISTRY",
    "BaselineDetector",
    "Detector",
    "DuplicateDetector",
    "SplitDetector",
]
