"""The interface every detector implements (CLAUDE.md section 15).

    detect(con) -> list[Case]

A detector receives a DuckDB connection and must read only the
``audit_transactions`` view - what a real auditor would see. It must never
read the injection answer key or ingestion provenance; a test scans every
detector module for those names.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

import duckdb

from spendguard.cases import AnomalyType, Case
from spendguard.db.duck import AUDIT_VIEW

__all__ = ["AUDIT_VIEW", "Detector"]


@runtime_checkable
class Detector(Protocol):
    name: ClassVar[str]
    anomaly_types: ClassVar[tuple[AnomalyType, ...]]

    def detect(self, con: duckdb.DuckDBPyConnection) -> list[Case]:
        """Score every row and return one Case per anomaly group found."""
        ...
