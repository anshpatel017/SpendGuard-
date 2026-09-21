"""The frozen demo: a hashed snapshot, served from a fresh copy every time."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spendguard.api import create_app
from spendguard.db.store import CaseStatus, get_engine, save_cases, set_status
from spendguard.eval.injection import InjectionResult
from spendguard.freeze import FrozenStateError, freeze, prepare, verify

from .test_investigation import _case


@pytest.fixture
def evaluation(tmp_path: Path, injected: InjectionResult) -> dict[str, Path]:
    """A seed-11 evaluation run's outputs, as `spendguard investigate --eval-seed` leaves them."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    db = tmp_path / "injected.duckdb"
    shutil.copy(injected.out_db, db)
    save_cases(get_engine(f"sqlite:///{(eval_dir / 'investigation_seed11.sqlite').as_posix()}"),
               "detect", "injected_seed11", [_case([1, 2])])  # fmt: skip
    (eval_dir / "eval-20260101T000000-seed11.json").write_text("{}", encoding="utf-8")
    (eval_dir / "eval-20260102T000000-seed11.json").write_text('{"newest": 1}', encoding="utf-8")
    (eval_dir / "investigate-eval-20260101T000000-seed11.json").write_text("{}", encoding="utf-8")
    return {"db": db, "eval_dir": eval_dir, "frozen": tmp_path / "frozen" / "demo"}


def _freeze(e: dict[str, Path]) -> dict[str, object]:
    return freeze(
        11, injected_db=e["db"], eval_dir=e["eval_dir"], out_dir=e["frozen"], commit="abc"
    )


def test_freezing_copies_the_run_and_hashes_every_file(evaluation: dict[str, Path]) -> None:
    manifest = _freeze(evaluation)
    assert set(manifest["files"]) == {  # type: ignore[arg-type]
        "spendguard.duckdb",
        "eval/investigation_seed11.sqlite",
        "eval/eval-20260102T000000-seed11.json",  # the newest report only
        "eval/investigate-eval-20260101T000000-seed11.json",
    }
    on_disk = json.loads((evaluation["frozen"] / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["commit"] == "abc" and on_disk["seed"] == 11
    assert verify(evaluation["frozen"])["files"] == manifest["files"]


def test_a_changed_snapshot_is_refused(evaluation: dict[str, Path]) -> None:
    _freeze(evaluation)
    (evaluation["frozen"] / "eval" / "eval-20260102T000000-seed11.json").write_text(
        '{"newest": 2}', encoding="utf-8"
    )
    with pytest.raises(FrozenStateError, match="has changed"):
        verify(evaluation["frozen"])


def test_there_is_nothing_to_serve_before_a_freeze(tmp_path: Path) -> None:
    with pytest.raises(FrozenStateError, match="spendguard freeze"):
        prepare(tmp_path / "nothing")


def test_every_demo_starts_from_the_frozen_state(evaluation: dict[str, Path]) -> None:
    """A reviewer's clicks during one demo must not leak into the next - or into the snapshot."""
    _freeze(evaluation)
    first = prepare(evaluation["frozen"])
    case_id = _case([1, 2]).case_id
    engine = get_engine(first.database_url)
    set_status(engine, case_id, CaseStatus.CONFIRMED, "during the demo")
    engine.dispose()  # the demo's server stops before the next launch

    second = prepare(evaluation["frozen"])  # the next launch
    client = TestClient(create_app(duckdb_path=second.duckdb_path,
                                   database_url=second.database_url, eval_dir=second.eval_dir))  # fmt: skip
    assert client.get(f"/api/v1/cases/{case_id}").json()["case"]["status"] == "new"
    verify(evaluation["frozen"])  # the snapshot itself never changed


def test_a_working_copy_still_in_use_is_reported_not_crashed(evaluation: dict[str, Path]) -> None:
    _freeze(evaluation)
    live = prepare(evaluation["frozen"])
    engine = get_engine(live.database_url)
    try:
        with engine.connect():  # an open file, as a still-running server holds it
            try:
                prepare(evaluation["frozen"])
            except FrozenStateError as exc:
                assert "still running" in str(exc)  # Windows: the file is locked
    finally:
        engine.dispose()
