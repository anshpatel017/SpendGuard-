"""Local experiment tracking for evaluation runs (FR-7.10).

Every evaluation run already records its parameters, seeds and results durably:
`eval_runs` carries the seed, the row count, which detectors ran and the whole
threshold set in force, and `eval_results` carries the numbers, both in the same
DuckDB file the run read from. That is the record, and it stays the record.

What it is not is a *tracker*. Comparing last Tuesday's seed-7 run against
today's means writing SQL, and nobody writing SQL at 2 a.m. notices that the two
rows they are comparing were produced under different thresholds. FR-7.10 asks
for a tracker, so this logs the same facts a second time into MLflow's local
file store, where runs sit side by side and a changed parameter is visible.

Three rules this module keeps, in order of importance:

1. **It never fails a run.** MLflow lives in the optional `track` extra, which CI
   does not install, and a tracker that takes the evaluation down with it when a
   write fails is worse than no tracker. Every entry point swallows and reports.
2. **It is never the source of truth.** Everything logged here is read off the
   `EvaluationRun` that DuckDB already holds. If the two disagree, the DuckDB row
   is right and this is broken. Nothing in the project reads back from MLflow.
3. **It is local, and stays local.** The backend is a SQLite file inside the
   project and artifacts go to a directory beside it; no server, nothing pointing
   off this machine unless someone sets `MLFLOW_TRACKING_URI` deliberately. NFR-1
   and NFR-3 are not negotiable for a convenience feature.

Not the `./mlruns` file store, which is what every MLflow tutorial reaches for:
MLflow 3.x put that backend in maintenance mode and now *raises* on connecting to
it unless `MLFLOW_ALLOW_FILE_STORE=true`. Since rule 1 swallows failures, taking
the tutorial's default would have produced a tracker that reported success and
logged nothing - which is how this was caught, on a real run that wrote its
reports and left no `mlruns/` behind.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from spendguard.config import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from spendguard.eval.runner import EvaluationRun

log = logging.getLogger(__name__)

# MLflow rejects a param value over 6,000 characters. The threshold set is well
# under that, but `config` is a free dict and a future entry could be anything.
MAX_PARAM_CHARS = 500


class TrackingUnavailableError(RuntimeError):
    """MLflow is not installed, or could not be reached. Never raised at callers."""


def _mlflow() -> Any:
    """Import MLflow, or say why not. Imported here, never at module scope.

    `spendguard.eval.runner` imports this module unconditionally, and the `track`
    extra is optional, so a top-level import would make the whole evaluation
    pipeline uninstallable without it.
    """
    try:
        import mlflow
    except ImportError as exc:  # pragma: no cover - exercised by the skip path
        raise TrackingUnavailableError(
            "mlflow is not installed. `pip install -e './backend[track]'` to enable it."
        ) from exc
    return mlflow


def enabled() -> bool:
    """Whether tracking should be attempted at all."""
    return bool(settings.mlflow_enabled)


def available() -> bool:
    """Whether tracking is both wanted and possible, without logging anything."""
    if not enabled():
        return False
    try:
        _mlflow()
    except TrackingUnavailableError:
        return False
    return True


def _flatten(prefix: str, value: Any) -> dict[str, float]:
    """A nested result into MLflow's flat `name -> number` metric space."""
    if isinstance(value, dict):
        out: dict[str, float] = {}
        for key, item in value.items():
            out.update(_flatten(f"{prefix}.{key}", item))
        return out
    if isinstance(value, bool) or value is None:
        return {}
    if isinstance(value, int | float):
        return {prefix: float(value)}
    return {}


def _params(run: EvaluationRun) -> dict[str, str]:
    """The parameters half of FR-7.10: what produced these numbers.

    The seed and the detector list are the obvious ones. The threshold set matters
    more, because it is what makes two runs comparable or not, and reading it back
    from `config.py` at comparison time would read today's values rather than the
    ones in force when the run happened.
    """
    params: dict[str, str] = {
        "seed": str(run.seed),
        "transactions": str(run.transactions),
        "detectors": ",".join(sorted(run.cases) or ["(none)"]),
        "database": run.db_path.name,
        "currency": settings.currency,
    }
    for key, value in sorted(run.config.items()):
        text = str(value)
        params[f"config.{key}"] = (
            text if len(text) <= MAX_PARAM_CHARS else text[: MAX_PARAM_CHARS - 1] + "…"
        )
    for anomaly, count in sorted(run.ground_truth_groups.items()):
        params[f"injected.{anomaly}"] = str(count)
    return params


def _metrics(run: EvaluationRun) -> dict[str, float]:
    """The results half. One metric per detector, anomaly type and granularity."""
    metrics: dict[str, float] = {}
    for m in run.metrics:
        stem = f"{m.granularity}.{m.detector}.{m.anomaly_type}"
        metrics[f"{stem}.precision"] = m.precision
        metrics[f"{stem}.recall"] = m.recall
        metrics[f"{stem}.f1"] = m.f1
        metrics[f"{stem}.tp"] = float(m.tp)
        metrics[f"{stem}.fp"] = float(m.fp)
        metrics[f"{stem}.fn"] = float(m.fn)
        if m.pr_auc is not None:
            metrics[f"{stem}.pr_auc"] = m.pr_auc
    for detector, seconds in run.seconds.items():
        metrics[f"seconds.{detector}"] = float(seconds)
    for detector, cases in run.cases.items():
        metrics[f"cases.{detector}"] = float(len(cases))
    return metrics


def tracking_uri() -> str:
    """Where runs are stored: a SQLite file in the project unless told otherwise.

    The directory is created here because SQLite will not create a missing parent
    and MLflow's error for it names neither the path nor the cause.
    """
    if settings.mlflow_tracking_uri:
        return settings.mlflow_tracking_uri
    settings.mlflow_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(settings.mlflow_dir / 'mlflow.db').as_posix()}"


def _experiment_id(mlflow: Any) -> str:
    """The experiment, created on first use with a local artifact directory.

    `set_experiment` cannot set an artifact location, and with a database backend
    MLflow otherwise resolves artifacts relative to the process's working
    directory - so the same run logged from two places lands in two trees.
    """
    client = mlflow.MlflowClient()
    existing = client.get_experiment_by_name(settings.mlflow_experiment)
    if existing is not None:
        return str(existing.experiment_id)
    artifacts = settings.mlflow_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return str(
        client.create_experiment(settings.mlflow_experiment, artifact_location=artifacts.as_uri())
    )


def log_run(run: EvaluationRun) -> str | None:
    """Log one evaluation run. Returns MLflow's run id, or None if nothing was logged.

    Called for its side effect and never for a value anything depends on, which is
    why every failure path returns None rather than raising. A broken tracker must
    cost the evaluation nothing; the numbers are already in DuckDB either way.
    """
    if not enabled():
        return None
    try:
        mlflow = _mlflow()
    except TrackingUnavailableError as exc:
        log.info("Experiment tracking skipped: %s", exc)
        return None

    try:
        mlflow.set_tracking_uri(tracking_uri())
        with mlflow.start_run(run_name=run.run_id, experiment_id=_experiment_id(mlflow)) as active:
            mlflow.set_tags(
                {
                    "run_id": run.run_id,
                    "seed": str(run.seed),
                    "project": "spendguard",
                    # Which half of the system produced this. The agent arms are
                    # tracked separately and must not be averaged in with these.
                    "stage": "detection",
                }
            )
            mlflow.log_params(_params(run))
            mlflow.log_metrics(_metrics(run))
            for path in run.report_paths:
                if path.exists():
                    mlflow.log_artifact(str(path), artifact_path="reports")
            return str(active.info.run_id)
    except Exception as exc:  # noqa: BLE001 - a tracker must never fail a run
        log.warning("Experiment tracking failed for %s: %s", run.run_id, exc)
        return None
