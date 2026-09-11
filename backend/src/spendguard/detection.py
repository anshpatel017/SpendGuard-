"""Run the production detectors over the operational dataset and store the cases.

This is ``spendguard detect``: detection over 100% of rows (decision D-05),
with every case persisted to the case store for review. It is the operational
path - evaluation against planted anomalies is ``spendguard evaluate``, which
never touches the case store.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from spendguard.cases import Case
from spendguard.config import settings
from spendguard.db.duck import connect, table_exists
from spendguard.db.store import SaveResult, get_engine, record_run, save_cases
from spendguard.detectors import PRODUCTION_DETECTORS, REGISTRY


class EvaluationDatabaseError(RuntimeError):
    """Refusing to load planted anomalies into the operational case store."""


@dataclass
class DetectionRun:
    run_id: str
    dataset: str
    transactions: int
    cases: list[Case]
    seconds: dict[str, float]
    saved: SaveResult | None = None
    by_detector: dict[str, int] = field(default_factory=dict)


def run_detection(
    db_path: Path | None = None,
    detectors: Sequence[str] | None = None,
    store_url: str | None = None,
    *,
    reset: bool = False,
) -> DetectionRun:
    names = list(detectors or PRODUCTION_DETECTORS)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"Unknown detector(s) {unknown}. Available: {sorted(REGISTRY)}")

    started = datetime.now(UTC).replace(tzinfo=None)
    db_path = db_path or settings.duckdb_path
    with connect(db_path, read_only=True) as con:
        if table_exists(con, "injection_runs"):
            raise EvaluationDatabaseError(
                f"{db_path.name} contains planted anomalies. Use `spendguard evaluate` for it; "
                "the case store is for real findings only."
            )
        row = con.execute("SELECT any_value(source_dataset), count(*) FROM transactions").fetchone()
        dataset, transactions = (str(row[0]), int(row[1])) if row else ("unknown", 0)

        cases: list[Case] = []
        seconds: dict[str, float] = {}
        for name in names:
            t = time.perf_counter()
            cases.extend(REGISTRY[name]().detect(con))
            seconds[name] = round(time.perf_counter() - t, 3)

    run_id = f"detect-{started:%Y%m%dT%H%M%S}"
    engine = get_engine(store_url)
    saved = save_cases(engine, run_id, dataset, cases, reset=reset)
    by_detector = dict(Counter(c.detector for c in cases))
    record_run(
        engine,
        run_id,
        "detect",
        dataset,
        config={
            "detectors": names,
            "db_path": str(db_path),
            "approval_threshold": settings.approval_threshold,
            "duplicate_match_threshold": settings.duplicate_match_threshold,
            "split_score_threshold": settings.split_score_threshold,
        },
        summary={"cases": len(cases), "by_detector": by_detector, "seconds": seconds},
        started_at=started,
    )
    return DetectionRun(run_id, dataset, transactions, cases, seconds, saved, by_detector)
