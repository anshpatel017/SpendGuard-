"""Detectors. Each implements ``detect(con) -> list[Case]`` over the audit view."""

from spendguard.detectors.base import Detector
from spendguard.detectors.baseline import BaselineDetector
from spendguard.detectors.d1_duplicates import DuplicateDetector
from spendguard.detectors.d2_splits import SplitDetector
from spendguard.detectors.d3_inflation import InflationDetector
from spendguard.detectors.d4_vendor import VendorFlagDetector

# Name -> detector class.
REGISTRY: dict[str, type[Detector]] = {
    BaselineDetector.name: BaselineDetector,
    DuplicateDetector.name: DuplicateDetector,
    SplitDetector.name: SplitDetector,
    InflationDetector.name: InflationDetector,
    VendorFlagDetector.name: VendorFlagDetector,
}

# What `spendguard detect` runs by default. The baseline is a benchmark, not a product.
PRODUCTION_DETECTORS: tuple[str, ...] = (
    DuplicateDetector.name,
    SplitDetector.name,
    InflationDetector.name,
    VendorFlagDetector.name,
)

__all__ = [
    "PRODUCTION_DETECTORS",
    "REGISTRY",
    "BaselineDetector",
    "Detector",
    "DuplicateDetector",
    "InflationDetector",
    "SplitDetector",
    "VendorFlagDetector",
]
