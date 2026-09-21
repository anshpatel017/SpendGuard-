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


def owns(detector: str, anomaly_type: str) -> bool:
    """Does the detector emit this anomaly type at all?

    Evaluation scores every detector against every type, so D1 has an F1 of
    0.000 on split purchases - true, meaningless, and exactly the number a
    reader misreads (it happened, on the dashboard). Result tables show only the
    types a detector declares, and the pooled "all" row only for a detector
    covering several - the baseline. An unknown name is kept, not hidden.
    """
    detector_class = REGISTRY.get(detector)
    if detector_class is None:
        return True
    types = {t.value for t in detector_class.anomaly_types}
    return anomaly_type in types or (anomaly_type == "all" and len(types) > 1)


__all__ = [
    "PRODUCTION_DETECTORS",
    "REGISTRY",
    "BaselineDetector",
    "Detector",
    "DuplicateDetector",
    "InflationDetector",
    "SplitDetector",
    "VendorFlagDetector",
    "owns",
]
