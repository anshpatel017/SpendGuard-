"""Run detectors against an injected database and record how they did.

Results go to three places: the ``eval_results`` table in the evaluated database,
a JSON file for machines, and a Markdown table for people. Every number in the
final report must trace back to one of these runs.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from spendguard.cases import Case
from spendguard.config import settings
from spendguard.db.duck import EVAL_RESULTS_DDL, connect, table_exists
from spendguard.detectors import REGISTRY
from spendguard.eval.matching import TruthGroup, load_ground_truth
from spendguard.eval.metrics import ALL, DetectionMetrics, evaluate_cases


@dataclass
class EvaluationRun:
    run_id: str
    db_path: Path
    seed: int | None
    transactions: int
    ground_truth_groups: dict[str, int]
    metrics: list[DetectionMetrics]
    cases: dict[str, list[Case]] = field(default_factory=dict, repr=False)
    seconds: dict[str, float] = field(default_factory=dict)
    report_paths: tuple[Path, ...] = ()


def _injection_seed(con: object) -> int | None:
    if not table_exists(con, "injection_runs"):  # type: ignore[arg-type]
        return None
    row = con.execute("SELECT seed FROM injection_runs LIMIT 1").fetchone()  # type: ignore[attr-defined]
    return int(row[0]) if row else None


def run_evaluation(
    db_path: Path, detectors: list[str], report_dir: Path | None = None
) -> EvaluationRun:
    unknown = [d for d in detectors if d not in REGISTRY]
    if unknown:
        raise KeyError(f"Unknown detector(s) {unknown}. Available: {sorted(REGISTRY)}")

    created = datetime.now(UTC)
    with connect(db_path) as con:
        groups: list[TruthGroup] = load_ground_truth(con)
        seed = _injection_seed(con)
        row = con.execute("SELECT count(*) FROM transactions").fetchone()
        transactions = int(row[0]) if row else 0

        metrics: list[DetectionMetrics] = []
        all_cases: dict[str, list[Case]] = {}
        seconds: dict[str, float] = {}
        for name in detectors:
            started = time.perf_counter()
            found = REGISTRY[name]().detect(con)
            seconds[name] = round(time.perf_counter() - started, 3)
            all_cases[name] = found
            metrics.extend(evaluate_cases(name, found, groups))

        run_id = f"eval-{created:%Y%m%dT%H%M%S}-seed{seed}"
        con.execute(EVAL_RESULTS_DDL)
        con.executemany(
            "INSERT INTO eval_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [run_id, m.detector, m.anomaly_type, m.granularity, m.precision, m.recall,
                 m.f1, m.pr_auc, m.tp, m.fp, m.fn, seed, created.replace(tzinfo=None)]
                for m in metrics
            ],
        )  # fmt: skip

    truth_counts: dict[str, int] = {}
    for g in groups:
        truth_counts[g.anomaly_type.value] = truth_counts.get(g.anomaly_type.value, 0) + 1

    run = EvaluationRun(
        run_id=run_id,
        db_path=db_path,
        seed=seed,
        transactions=transactions,
        ground_truth_groups=truth_counts,
        metrics=metrics,
        cases=all_cases,
        seconds=seconds,
    )
    run.report_paths = write_report(run, report_dir or settings.processed_data_dir / "eval")
    return run


def render_markdown(run: EvaluationRun) -> str:
    groups = ", ".join(f"{n} {k}" for k, n in sorted(run.ground_truth_groups.items()))
    lines = [
        f"# Evaluation - `{run.run_id}`",
        "",
        f"- **Database:** `{run.db_path.name}` · **injection seed:** {run.seed}",
        f"- **Transactions:** {run.transactions:,}",
        f"- **Injected anomaly groups:** {sum(run.ground_truth_groups.values())} ({groups})",
        "",
        "Per-case is primary: one case per anomaly group, matched one-to-one "
        "(docs/EVALUATION.md). Per-row is the completeness view.",
        "",
    ]
    for granularity in ("case", "row"):
        lines += [
            f"## Per {granularity}",
            "",
            "| Detector | Anomaly | Precision | Recall | F1 | PR-AUC | TP | FP | FN |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in run.metrics:
            if m.granularity != granularity:
                continue
            kind = f"**{m.anomaly_type}**" if m.anomaly_type == ALL else m.anomaly_type
            auc = f"{m.pr_auc:.3f}" if m.pr_auc is not None else "—"
            lines.append(
                f"| {m.detector} | {kind} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} "
                f"| {auc} | {m.tp:,} | {m.fp:,} | {m.fn:,} |"
            )
        lines.append("")
    lines += [
        "## Run time",
        "",
        *[f"- `{name}`: {secs:.2f}s" for name, secs in run.seconds.items()],
        "",
    ]
    return "\n".join(lines)


def write_report(run: EvaluationRun, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{run.run_id}.md"
    json_path = out_dir / f"{run.run_id}.json"
    md_path.write_text(render_markdown(run), encoding="utf-8")
    payload = {
        "run_id": run.run_id,
        "db_path": str(run.db_path),
        "seed": run.seed,
        "transactions": run.transactions,
        "ground_truth_groups": run.ground_truth_groups,
        "seconds": run.seconds,
        "metrics": [asdict(m) for m in run.metrics],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return md_path, json_path
