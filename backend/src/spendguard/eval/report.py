"""Result tables that can be regenerated from one command (Phase 9, EVALUATION section 7).

    spendguard report detection

runs every detector over every evaluation seed, aggregates the results as mean
and spread, repeats the clean-data check, re-runs the development seed to show
the output does not change, and writes the tables to ``docs/results/`` beside
the commit and the settings that produced them.

Before this, the three-seed table in EVALUATION.md was assembled by hand from
three separate runs. A number that has to be copied by hand is a number that
can be copied wrong, and one nobody can check without redoing the work.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.db.duck import connect, table_exists
from spendguard.detectors import PRODUCTION_DETECTORS, REGISTRY, owns
from spendguard.eval.injection import InjectionConfig, default_injected_path, inject
from spendguard.eval.metrics import ALL, DetectionMetrics
from spendguard.eval.runner import EvaluationRun, run_evaluation

REPORTED_DETECTORS: tuple[str, ...] = ("baseline", *PRODUCTION_DETECTORS)
TYPE_ORDER: tuple[str, ...] = (*(t.value for t in AnomalyType), ALL)
PACKAGES = ("duckdb", "polars", "numpy", "scipy", "scikit-learn", "rapidfuzz")
# Settings that decide what the detectors flag - recorded with every report.
DETECTOR_SETTINGS = (
    "approval_threshold", "duplicate_amount_tolerance", "duplicate_date_window_days",
    "duplicate_name_confirm", "duplicate_match_threshold", "split_window_days",
    "split_score_threshold", "inflation_zscore_threshold", "inflation_min_category_size",
    "vendor_min_distinct_amounts", "vendor_min_transactions", "vendor_fdr_alpha",
    "severity_reference_amount",
)  # fmt: skip


# ------------------------------------------------------------------ provenance


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=settings.project_root, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def provenance(extra_settings: Sequence[str] = DETECTOR_SETTINGS) -> dict[str, Any]:
    """Where a result came from: code, environment and settings.

    ``dirty`` is true when the working tree has uncommitted changes: the commit
    alone then does not reproduce the result, and the report says so.
    """
    versions: dict[str, str | None] = {}
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "packages": versions,
        "settings": {name: getattr(settings, name) for name in extra_settings},
    }


# ------------------------------------------------------------------ aggregation


@dataclass(frozen=True)
class Spread:
    mean: float
    sd: float  # sample standard deviation across seeds (n - 1); 0 with one seed

    @classmethod
    def of(cls, values: Sequence[float]) -> Spread:
        return cls(statistics.fmean(values), statistics.stdev(values) if len(values) > 1 else 0.0)

    def text(self) -> str:
        return f"{self.mean:.3f} ± {self.sd:.3f}"


@dataclass(frozen=True)
class AggregateRow:
    anomaly_type: str
    detector: str
    granularity: str
    precision: Spread
    recall: Spread
    f1: Spread
    pr_auc: Spread | None


def aggregate(runs: Sequence[EvaluationRun]) -> list[AggregateRow]:
    """Mean and spread across seeds, for the types each detector owns."""
    rows = []
    for granularity in ("case", "row"):
        for anomaly_type in TYPE_ORDER:
            for detector in REPORTED_DETECTORS:
                if not owns(detector, anomaly_type):
                    continue
                found = [
                    m
                    for run in runs
                    for m in run.metrics
                    if (m.detector, m.anomaly_type, m.granularity)
                    == (detector, anomaly_type, granularity)
                ]
                if len(found) != len(runs):
                    continue
                pr_aucs = [m.pr_auc for m in found]
                rows.append(
                    AggregateRow(
                        anomaly_type=anomaly_type,
                        detector=detector,
                        granularity=granularity,
                        precision=Spread.of([m.precision for m in found]),
                        recall=Spread.of([m.recall for m in found]),
                        f1=Spread.of([m.f1 for m in found]),
                        pr_auc=(
                            Spread.of([v for v in pr_aucs if v is not None])
                            if all(v is not None for v in pr_aucs)
                            else None
                        ),
                    )
                )
    return rows


# ------------------------------------------------------------------ checks


@dataclass
class CleanCheck:
    """What the detectors flag on data with nothing planted in it (CLAUDE.md convention 5)."""

    transactions: int
    cases: dict[str, int]
    rows_flagged: dict[str, int]


def clean_data_check(db_path: Path | None = None) -> CleanCheck:
    db_path = db_path or settings.duckdb_path
    cases: dict[str, int] = {}
    rows: dict[str, int] = {}
    with connect(db_path, read_only=True) as con:
        if table_exists(con, "injection_runs"):
            raise ValueError(
                f"{db_path.name} has planted anomalies; the clean check needs clean data"
            )
        found = con.execute("SELECT count(*) FROM transactions").fetchone()
        total = int(found[0]) if found else 0
        for name in PRODUCTION_DETECTORS:
            flagged = REGISTRY[name]().detect(con)
            cases[name] = len(flagged)
            rows[name] = len({r for c in flagged for r in c.row_ids})
    return CleanCheck(transactions=total, cases=cases, rows_flagged=rows)


def _fingerprint(cases: Sequence[Case]) -> list[tuple[str, float]]:
    return [(c.case_id, round(c.detector_score, 12)) for c in cases]


def reproduces(run: EvaluationRun) -> tuple[bool, int]:
    """Detect again on the same database: the same cases, scores and order? (convention 4)."""
    with connect(run.db_path, read_only=True) as con:
        again = {name: REGISTRY[name]().detect(con) for name in PRODUCTION_DETECTORS}
    same = all(_fingerprint(again[n]) == _fingerprint(run.cases[n]) for n in again)
    return same, sum(len(cases) for cases in again.values())


# ------------------------------------------------------------------ the report


@dataclass
class DetectionReport:
    seeds: list[int]
    runs: list[EvaluationRun]
    rows: list[AggregateRow]
    clean: CleanCheck
    reproduced: bool
    reproduced_cases: int
    manifest: dict[str, Any]
    seconds: float
    paths: tuple[Path, ...] = field(default_factory=tuple)


def detection_report(
    seeds: Sequence[int] | None = None,
    *,
    out_dir: Path | None = None,
    eval_dir: Path | None = None,
    clean_db: Path | None = None,
    injected: dict[int, Path] | None = None,
) -> DetectionReport:
    """Every seed, every detector, the clean check and a determinism check, written out."""
    started = time.perf_counter()
    seeds = list(seeds or settings.evaluation_seeds)
    runs = []
    for seed in seeds:
        db = (injected or {}).get(seed) or default_injected_path(seed)
        if not db.exists():
            inject(clean_db, db, InjectionConfig(seed=seed))
        runs.append(run_evaluation(db, list(REPORTED_DETECTORS), report_dir=eval_dir))
    reproduced, reproduced_cases = reproduces(runs[0])
    report = DetectionReport(
        seeds=seeds,
        runs=runs,
        rows=aggregate(runs),
        clean=clean_data_check(clean_db),
        reproduced=reproduced,
        reproduced_cases=reproduced_cases,
        manifest=provenance(),
        seconds=round(time.perf_counter() - started, 1),
    )
    report.paths = write_detection_report(report, out_dir or settings.results_dir)
    return report


def _f1(run: EvaluationRun, detector: str, anomaly_type: str) -> str:
    for m in run.metrics:
        if (m.detector, m.anomaly_type, m.granularity) == (detector, anomaly_type, "case"):
            return f"{m.f1:.3f}"
    return "-"


def render_markdown(report: DetectionReport) -> str:
    m = report.manifest
    dev, *held_out = report.seeds
    state = "" if m["dirty"] is False else " (uncommitted changes present)" if m["dirty"] else ""
    lines = [
        "# Detection results",
        "",
        "> Generated by `spendguard report detection` - do not edit by hand. "
        f"Commit `{m['commit']}`{state}, {m['generated_at']}, {report.seconds:.0f} s.",
        "",
        f"Seeds: **{dev}** (development: every threshold was tuned on it)"
        + (f", **{', '.join(map(str, held_out))}** (held out)." if held_out else "."),
        "Values are the mean ± sample standard deviation across seeds.",
        "",
    ]

    def table(granularity: str, title: str) -> None:
        with_auc = granularity == "case"
        lines.extend([f"## {title}", ""])
        head = "| Anomaly | Detector | Precision | Recall | F1 |" + (
            " PR-AUC |" if with_auc else ""
        )
        lines.append(head)
        lines.append("|---|---|---:|---:|---:|" + ("---:|" if with_auc else ""))
        for r in report.rows:
            if r.granularity != granularity:
                continue
            detector = r.detector if r.detector == "baseline" else f"**{r.detector.upper()}**"
            cells = [r.anomaly_type, detector, r.precision.text(), r.recall.text(), r.f1.text()]
            if with_auc:
                cells.append(r.pr_auc.text() if r.pr_auc else "-")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    table("case", "Per case (headline)")
    table("row", "Per row (secondary)")

    lines += [
        "## Per seed - F1 per case",
        "",
        "| Seed | Transactions | Planted groups | Baseline (all) | D1 | D2 | D3 | D4 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for seed, run in zip(report.seeds, report.runs, strict=True):
        cells = [
            str(seed),
            f"{run.transactions:,}",
            str(sum(run.ground_truth_groups.values())),
            _f1(run, "baseline", ALL),
            _f1(run, "d1", "duplicate"),
            _f1(run, "d2", "split"),
            _f1(run, "d3", "inflation"),
            _f1(run, "d4", "vendor_flag"),
        ]
        lines.append("| " + " | ".join(cells) + " |")

    c = report.clean
    lines += [
        "",
        f"## Clean data - nothing planted ({c.transactions:,} transactions)",
        "",
        "| Detector | Cases | Rows flagged | Share of rows |",
        "|---|---:|---:|---:|",
    ]
    for name in PRODUCTION_DETECTORS:
        share = c.rows_flagged[name] / c.transactions if c.transactions else 0.0
        lines.append(
            f"| {name.upper()} | {c.cases[name]:,} | {c.rows_flagged[name]:,} | {share:.2%} |"
        )
    lines += [
        "",
        "## Reproducibility",
        "",
        f"Seed {dev} detected a second time: **"
        + ("identical" if report.reproduced else "DIFFERENT")
        + f"** - {report.reproduced_cases:,} cases, the same ids, scores and order.",
        "",
        "## Settings that decide what is flagged",
        "",
        "| Setting | Value |",
        "|---|---|",
        *(f"| `{k}` | {v} |" for k, v in m["settings"].items()),
        "",
        f"Python {m['python']}; "
        + ", ".join(f"{k} {v}" for k, v in m["packages"].items() if v)
        + ".",
        "",
    ]
    return "\n".join(lines)


def write_detection_report(report: DetectionReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "detection.md"
    js = out_dir / "detection.json"
    md.write_text(render_markdown(report), encoding="utf-8")
    payload = {
        "manifest": report.manifest,
        "seeds": report.seeds,
        "runs": [
            {
                "seed": seed,
                "run_id": run.run_id,
                "transactions": run.transactions,
                "ground_truth_groups": run.ground_truth_groups,
                "metrics": [asdict(m) for m in run.metrics],
            }
            for seed, run in zip(report.seeds, report.runs, strict=True)
        ],
        "aggregate": [asdict(r) for r in report.rows],
        "clean": asdict(report.clean),
        "reproduced": report.reproduced,
        "reproduced_cases": report.reproduced_cases,
    }
    js.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return md, js


__all__ = [
    "AggregateRow",
    "CleanCheck",
    "DetectionMetrics",
    "DetectionReport",
    "Spread",
    "aggregate",
    "clean_data_check",
    "detection_report",
    "provenance",
    "reproduces",
]
