"""The live injection demonstration (FR-5.10): bounded, seeded, and harmless to the data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spendguard import demo
from spendguard.api import create_app
from spendguard.cases import AnomalyType
from spendguard.config import settings
from spendguard.demo import DemoBusyError, live_injection_demo, plan
from spendguard.eval.injection import InjectionResult
from spendguard.pipeline.ingest import IngestResult

WHOLE_FIXTURE = 48  # months: the 3,000-row test dataset fits inside this window


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_three_anomalies_are_one_of_each_kind() -> None:
    assert plan(3, seed=1) == {
        AnomalyType.DUPLICATE: 1,
        AnomalyType.SPLIT: 1,
        AnomalyType.INFLATION: 1,
    }


def test_the_plan_for_a_seed_never_changes() -> None:
    """Built on random.Random, not hash(): string hashing differs between processes."""
    assert plan(6, seed=99) == plan(6, seed=99)
    assert sum(plan(6, seed=99).values()) == 6
    assert AnomalyType.VENDOR_FLAG not in plan(6, seed=99)  # needs a supplier's long history


def test_a_demo_reports_every_planted_anomaly(ingested: IngestResult) -> None:
    run = live_injection_demo(3, 5, source_db=ingested.db_path, months=WHOLE_FIXTURE)
    planted = len(run.results) + sum(run.shortfall.values())
    assert planted == 3 and run.requested == 3
    assert run.dataset_rows == ingested.rows_loaded
    for r in run.results:
        assert r.injected_row_ids
        assert r.detected == (r.case_id is not None) == (r.detected_by is not None)
    assert run.caught == sum(r.detected for r in run.results)


def test_the_same_seed_gives_the_same_demo(ingested: IngestResult) -> None:
    first = live_injection_demo(3, 11, source_db=ingested.db_path, months=WHOLE_FIXTURE)
    again = live_injection_demo(3, 11, source_db=ingested.db_path, months=WHOLE_FIXTURE)
    assert [(r.anomaly_type, r.injected_row_ids, r.detected) for r in first.results] == [
        (r.anomaly_type, r.injected_row_ids, r.detected) for r in again.results
    ]


def test_the_demo_never_touches_the_data_it_copies(ingested: IngestResult) -> None:
    before = _sha(ingested.db_path)
    live_injection_demo(3, 2, source_db=ingested.db_path, months=WHOLE_FIXTURE)
    assert _sha(ingested.db_path) == before


def test_the_number_of_anomalies_is_capped(ingested: IngestResult) -> None:
    run = live_injection_demo(1_000, 3, source_db=ingested.db_path, months=WHOLE_FIXTURE)
    assert run.requested == settings.demo_max_anomalies


def test_data_that_already_has_planted_anomalies_is_refused(injected: InjectionResult) -> None:
    with pytest.raises(ValueError, match="clean data"):
        live_injection_demo(3, 1, source_db=injected.out_db)


def test_a_second_demo_while_one_runs_is_told_so(ingested: IngestResult) -> None:
    assert demo._running.acquire(blocking=False)
    try:
        with pytest.raises(DemoBusyError):
            live_injection_demo(3, 1, source_db=ingested.db_path)
    finally:
        demo._running.release()


# ------------------------------------------------------------------ the endpoint


@pytest.fixture
def client(tmp_path: Path, ingested: IngestResult, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings, "demo_months", WHOLE_FIXTURE)
    app = create_app(
        duckdb_path=ingested.db_path,
        database_url=f"sqlite:///{(tmp_path / 'cases.sqlite').as_posix()}",
        demo_source=ingested.db_path,
        frontend_dist=tmp_path / "no-build",
    )
    return TestClient(app)


def test_the_endpoint_runs_the_demo(client: Any) -> None:
    body = client.post("/api/v1/demo/inject", json={"anomaly_count": 3, "seed": 5}).json()
    assert body["seed"] == 5 and body["requested"] == 3
    assert body["caught"] == sum(r["detected"] for r in body["results"])
    assert all(isinstance(r["amount_at_risk"], str) for r in body["results"])  # money: a string


def test_the_endpoint_refuses_a_nonsense_count(client: Any) -> None:
    response = client.post("/api/v1/demo/inject", json={"anomaly_count": 0})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


def test_the_endpoint_answers_busy_with_a_structured_409(client: Any) -> None:
    assert demo._running.acquire(blocking=False)
    try:
        response = client.post("/api/v1/demo/inject", json={})
    finally:
        demo._running.release()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "demo_busy"
