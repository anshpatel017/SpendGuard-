"""Detectors. Each implements ``detect(con) -> list[Case]`` over the audit view."""

from spendguard.detectors.base import Detector
from spendguard.detectors.baseline import BaselineDetector

# Name -> detector class. Phases 3-4 register d1-d4 here.
REGISTRY: dict[str, type[Detector]] = {
    BaselineDetector.name: BaselineDetector,
}

__all__ = ["REGISTRY", "BaselineDetector", "Detector"]
