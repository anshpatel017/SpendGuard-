"""Local experiment tracking for evaluation runs (FR-7.10).

The point of these tests is not that MLflow works - it does - but that this
project's three rules about it hold: a tracker never fails a run, never becomes a
second source of truth, and never leaves the machine. Each rule is a way the
feature could quietly do harm, which is more dangerous than it failing loudly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from spendguard.config import Settings, settings
from spendguard.eval import tracking
from spendguard.eval.injection import InjectionResult
from spendguard.eval.runner import run_evaluation

mlflow = pytest.importorskip("mlflow", reason="the optional `track` extra is not installed")


@pytest.fixture
def tracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tracking on, pointed at a throwaway store so no test touches the real one."""
    store = tmp_path / "mlruns"
    monkeypatch.setattr(settings, "mlflow_enabled", True, raising=False)
    monkeypatch.setattr(settings, "mlflow_dir", store, raising=False)
    monkeypatch.setattr(settings, "mlflow_tracking_uri", "", raising=False)
    monkeypatch.setattr(settings, "mlflow_experiment", "test-detection", raising=False)
    return store


# ------------------------------------------------- rule 1: never fail a run


def test_tracking_is_off_until_someone_asks_for_it() -> None:
    """CI does not install the `track` extra, so the default cannot need it."""
    assert Settings.model_fields["mlflow_enabled"].default is False


def test_a_run_with_tracking_off_logs_nothing_and_says_so(
    tmp_path: Path, injected: InjectionResult
) -> None:
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    assert run.tracking_run_id is None
    assert run.metrics, "the evaluation still produced its numbers"


def test_a_missing_mlflow_is_reported_not_raised(
    tmp_path: Path, injected: InjectionResult, tracked: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a machine without the extra, the evaluation has to come out whole."""

    def _no_mlflow() -> Any:
        raise tracking.TrackingUnavailableError("mlflow is not installed")

    monkeypatch.setattr(tracking, "_mlflow", _no_mlflow)
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)

    assert run.tracking_run_id is None
    assert run.metrics
    assert not tracked.exists(), "nothing was written"


def test_a_tracker_that_breaks_mid_write_does_not_take_the_run_with_it(
    tmp_path: Path, injected: InjectionResult, tracked: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The numbers are already in DuckDB; losing them to a logging bug is absurd.

    Deliberately a bare `Exception` in the module under test, because the failure
    being guarded against is the one nobody predicted - a disk full, a locked
    SQLite file, an MLflow release changing a signature.
    """

    class Broken:
        def set_tracking_uri(self, uri: str) -> None:
            raise RuntimeError("database is locked")

    monkeypatch.setattr(tracking, "_mlflow", lambda: Broken())
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)

    assert run.tracking_run_id is None
    assert run.metrics
    assert run.report_paths and all(p.exists() for p in run.report_paths)


# ------------------------------------------- rule 2: never a second source of truth


def test_what_mlflow_holds_matches_what_duckdb_holds(
    tmp_path: Path, injected: InjectionResult, tracked: Path
) -> None:
    """The one that matters. Two records of a run that disagree are worse than one.

    DuckDB is authoritative; this only ever mirrors it. If a metric here drifted
    from `eval_results`, somebody would compare runs in the tracker and reach a
    conclusion the evidence does not support.
    """
    run = run_evaluation(injected.out_db, ["baseline", "d1"], report_dir=tmp_path)
    assert run.tracking_run_id, "the run was tracked"

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        stored = con.execute(
            """
            SELECT granularity, detector, anomaly_type, precision, recall, f1, tp, fp, fn
            FROM eval_results WHERE run_id = ?
            """,
            [run.run_id],
        ).fetchall()
    assert stored, "DuckDB recorded the run"

    mlflow.set_tracking_uri(tracking.tracking_uri())
    logged = mlflow.MlflowClient().get_run(run.tracking_run_id).data

    for granularity, detector, anomaly, precision, recall, f1, tp, fp, fn in stored:
        stem = f"{granularity}.{detector}.{anomaly}"
        assert logged.metrics[f"{stem}.precision"] == pytest.approx(precision)
        assert logged.metrics[f"{stem}.recall"] == pytest.approx(recall)
        assert logged.metrics[f"{stem}.f1"] == pytest.approx(f1)
        assert logged.metrics[f"{stem}.tp"] == tp
        assert logged.metrics[f"{stem}.fp"] == fp
        assert logged.metrics[f"{stem}.fn"] == fn


def test_the_thresholds_in_force_are_logged_with_the_numbers(
    tmp_path: Path, injected: InjectionResult, tracked: Path
) -> None:
    """FR-7.10 asks for parameters, and these are the parameters that matter.

    Two runs whose F1 differs because a threshold moved are not a result, and
    reading the thresholds from `config.py` at comparison time reads today's
    values rather than the ones that produced the numbers.
    """
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    mlflow.set_tracking_uri(tracking.tracking_uri())
    params = mlflow.MlflowClient().get_run(run.tracking_run_id or "").data.params

    assert params["seed"] == str(run.seed)
    assert params["transactions"] == str(run.transactions)
    assert params["detectors"] == "baseline"
    for key, value in run.config.items():
        assert params[f"config.{key}"] == str(value)
    assert params["config.approval_threshold"] == str(settings.approval_threshold)


def test_the_reports_ride_along_so_a_tracked_run_is_self_contained(
    tmp_path: Path, injected: InjectionResult, tracked: Path
) -> None:
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    mlflow.set_tracking_uri(tracking.tracking_uri())
    stored = mlflow.MlflowClient().list_artifacts(run.tracking_run_id or "", "reports")

    names = {Path(a.path).name for a in stored}
    assert names == {p.name for p in run.report_paths}
    assert any(n.endswith(".json") for n in names)


def test_nothing_in_the_project_reads_its_numbers_back_out_of_mlflow() -> None:
    """Rule 2, enforced rather than asserted in a docstring.

    A report that sourced a figure from the tracker would make an optional extra
    load-bearing, and `check-evaluation` traces every published figure to a
    results file. Only the tracking module may touch mlflow.
    """
    import ast

    root = Path(settings.project_root) / "backend" / "src" / "spendguard"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "tracking.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imported = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.split(".")[0] == "mlflow" for name in imported):
                offenders.append(path.relative_to(root).as_posix())
    assert offenders == [], f"mlflow imported outside the tracker: {offenders}"

    # `config.py` declaring `mlflow_*` settings is the one allowed mention: those
    # are knobs, not a data path, and rule 1 needs them readable without the extra.
    config = (root / "config.py").read_text(encoding="utf-8")
    assert "mlflow_enabled" in config


# ------------------------------------------------- rule 3: local, and stays local


def test_the_default_store_is_a_local_file_and_not_the_deprecated_one(tracked: Path) -> None:
    """Two failures in one, and the second cost a real run.

    MLflow 3.x put the `./mlruns` file store in maintenance mode and *raises* on
    connecting to it. Since rule 1 swallows failures, the tutorial default
    produced a tracker that reported success and logged nothing - caught only
    because a run left no store behind. SQLite is the supported local backend.
    """
    uri = tracking.tracking_uri()
    assert uri.startswith("sqlite:///")
    assert uri.endswith("mlflow.db")
    assert "://" not in uri.removeprefix("sqlite:///"), "no host, so nothing on a network"
    assert tracked.is_dir(), "the parent is created, since sqlite will not"


def test_an_explicit_uri_is_honoured_so_a_real_server_is_possible_but_deliberate(
    tracked: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deployments differ; silently overriding someone's choice would be wrong."""
    monkeypatch.setattr(settings, "mlflow_tracking_uri", "sqlite:///C:/elsewhere/other.db")
    assert tracking.tracking_uri() == "sqlite:///C:/elsewhere/other.db"


def test_artifacts_land_beside_the_store_not_wherever_the_shell_happened_to_be(
    tmp_path: Path, injected: InjectionResult, tracked: Path
) -> None:
    """With a database backend MLflow resolves artifacts against the working
    directory, so the same run logged from two places would split in two."""
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    mlflow.set_tracking_uri(tracking.tracking_uri())
    info = mlflow.MlflowClient().get_run(run.tracking_run_id or "").info

    assert (tracked / "artifacts").is_dir()
    assert "artifacts" in info.artifact_uri.replace("\\", "/")


def test_a_tracked_run_is_tagged_as_detection_so_arms_are_never_averaged(
    tmp_path: Path, injected: InjectionResult, tracked: Path
) -> None:
    """The agent arms are a different population (D-33, D-35); pooling them was
    already caught once in `headline.md`, where 17 Groq notes and 5 Ollama ones
    crossed a threshold together that neither reached alone."""
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    mlflow.set_tracking_uri(tracking.tracking_uri())
    tags = mlflow.MlflowClient().get_run(run.tracking_run_id or "").data.tags

    assert tags["stage"] == "detection"
    assert tags["seed"] == str(run.seed)


def test_an_unreadable_config_value_cannot_blow_the_param_limit(
    tmp_path: Path, injected: InjectionResult, tracked: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MLflow rejects a param over 6,000 characters, and `config` is a free dict.

    Today every value is a number. A future entry that is a long list would make
    the whole log call fail - and rule 1 means that failure would be silent.
    """
    from spendguard.eval import runner

    monkeypatch.setattr(runner, "detector_config", lambda: {"huge": json.dumps(list(range(5_000)))})
    run = run_evaluation(injected.out_db, ["baseline"], report_dir=tmp_path)
    assert run.tracking_run_id, "a long value is truncated, not fatal"

    mlflow.set_tracking_uri(tracking.tracking_uri())
    params = mlflow.MlflowClient().get_run(run.tracking_run_id).data.params
    assert len(params["config.huge"]) <= tracking.MAX_PARAM_CHARS
    assert params["config.huge"].endswith("\u2026")
