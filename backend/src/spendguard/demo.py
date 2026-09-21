"""The live injection demonstration - plant anomalies, watch them get caught (FR-5.10).

    copy the last few months of the clean dataset into a throwaway database
    plant a few anomalies of known kinds in the copy (the injection harness)
    run the production detectors over the copy
    report, for each planted anomaly, whether a detector caught it

It exists for an audience: the evaluation tables say the detectors work, this
shows them working on anomalies nobody has seen before, in a few seconds.

Three rules keep it honest and safe:

* **It never touches the data being demonstrated.** Everything happens in a
  temporary copy that is deleted afterwards.
* **It is bounded.** A few months of data and a capped number of anomalies,
  so it answers in seconds rather than the half-minute a full scan takes.
* **Caught means caught as what it is.** A planted duplicate counts as caught
  only by a duplicate case - the same matching rule as the evaluation (D-03).
  Vendor red flags are left out: they need months of a supplier's history
  that a short window does not have.
"""

from __future__ import annotations

import random
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.db.duck import TRANSACTION_FIELDS, connect, read_transactions, write_transactions
from spendguard.detectors import PRODUCTION_DETECTORS, REGISTRY
from spendguard.eval.injection import InjectionConfig, inject
from spendguard.eval.matching import load_ground_truth, match

DEMO_TYPES: tuple[AnomalyType, ...] = (
    AnomalyType.DUPLICATE,
    AnomalyType.SPLIT,
    AnomalyType.INFLATION,
)

# One demo at a time: each one builds and scans a database, and a second click
# while the first is running should be told so, not queued behind it.
_running = threading.Lock()


class DemoBusyError(RuntimeError):
    """A demonstration is already running."""


@dataclass
class PlantedResult:
    injection_group_id: str
    anomaly_type: str
    injected_row_ids: list[int]
    amount_at_risk: float
    detected: bool
    detected_by: str | None = None
    case_id: str | None = None
    detector_score: float | None = None


@dataclass
class DemoRun:
    seed: int
    dataset_rows: int
    window_start: date
    window_end: date
    requested: int
    results: list[PlantedResult]
    other_cases: int  # cases raised that match no planted anomaly: honest flags on real rows
    elapsed_seconds: float
    shortfall: dict[str, int] = field(default_factory=dict)

    @property
    def caught(self) -> int:
        return sum(1 for r in self.results if r.detected)


def plan(count: int, seed: int) -> dict[AnomalyType, int]:
    """Spread ``count`` anomalies over the demo types: one of each first, then seeded extras.

    Seeded with ``random.Random``, never ``hash()``: string hashing is randomized
    per process, so the same seed would plant different anomalies on another run.
    """
    rng = random.Random(seed)
    counts = {t: 0 for t in DEMO_TYPES}
    for i in range(count):
        kind = DEMO_TYPES[i] if i < len(DEMO_TYPES) else rng.choice(DEMO_TYPES)
        counts[kind] += 1
    return counts


def _window(frame: pl.DataFrame, months: int) -> pl.DataFrame:
    end = frame["txn_date"].max()
    start = pl.Series([end]).dt.offset_by(f"-{months}mo")[0]
    return frame.filter(pl.col("txn_date") > start)


def live_injection_demo(
    anomaly_count: int = 3,
    seed: int | None = None,
    *,
    source_db: Path | None = None,
    months: int | None = None,
) -> DemoRun:
    """Plant ``anomaly_count`` anomalies in a bounded copy and detect them."""
    if not _running.acquire(blocking=False):
        raise DemoBusyError("A demonstration is already running; try again in a few seconds.")
    try:
        return _run(anomaly_count, seed, source_db, months)
    finally:
        _running.release()


def _run(
    anomaly_count: int, seed: int | None, source_db: Path | None, months: int | None
) -> DemoRun:
    started = time.perf_counter()
    count = max(1, min(anomaly_count, settings.demo_max_anomalies))
    seed = secrets.randbelow(2**31) if seed is None else seed
    source = Path(source_db or settings.demo_source_db or settings.duckdb_path)

    with connect(source, read_only=True) as con:
        frame = read_transactions(con)
    if frame["is_injected"].any():
        raise ValueError(f"{source.name} already has planted anomalies; the demo needs clean data")
    window = _window(frame, months or settings.demo_months)

    work = Path(tempfile.mkdtemp(prefix="spendguard-demo-"))
    try:
        clean = work / "window.duckdb"
        with connect(clean) as con:
            write_transactions(con, window.select(TRANSACTION_FIELDS))
        planted = work / "planted.duckdb"
        injection = inject(
            clean, planted, InjectionConfig(seed=seed, vendor_flags=0), counts=plan(count, seed)
        )
        with connect(planted, read_only=True) as con:
            cases: list[Case] = [c for n in PRODUCTION_DETECTORS for c in REGISTRY[n]().detect(con)]
            groups = load_ground_truth(con)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    by_id = {c.case_id: c for c in cases}
    caught: dict[str, Case] = {}
    unmatched = 0
    for kind in AnomalyType:
        result = match(cases, groups, kind)
        caught.update({group_id: by_id[case_id] for case_id, group_id in result.matched.items()})
        unmatched += len(result.false_positives)

    results = []
    for group in sorted(groups, key=lambda g: (g.anomaly_type.value, g.group_id)):
        case = caught.get(group.group_id)
        results.append(
            PlantedResult(
                injection_group_id=group.group_id,
                anomaly_type=group.anomaly_type.value,
                injected_row_ids=sorted(group.row_ids),
                amount_at_risk=round(group.amount_at_risk, 2),
                detected=case is not None,
                detected_by=case.detector if case else None,
                case_id=case.case_id if case else None,
                detector_score=round(case.detector_score, 4) if case else None,
            )
        )
    return DemoRun(
        seed=seed,
        dataset_rows=window.height,
        window_start=cast(date, window["txn_date"].min()),
        window_end=cast(date, window["txn_date"].max()),
        requested=count,
        results=results,
        other_cases=unmatched,
        elapsed_seconds=round(time.perf_counter() - started, 2),
        shortfall=dict(injection.shortfall),
    )
