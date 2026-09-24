"""The grading result table: per-arm scores with the agreement behind them.

Kept apart from ``grading.py`` because exporting a batch and scoring one are
different jobs at different times - months apart, potentially - and the report
must be regenerable from the store alone, without the batch directory.

Two rules this file exists to enforce:

* **A score is never reported without its agreement.** A mean of graders who do
  not agree is a number with no content, so the arm table and the agreement
  table are written together and the reading ("reliable", "tentative only") is
  spelled out rather than left to the reader.
* **Arms are compared only on notes the same graders graded.** Comparing the
  agent's 30 notes against the template's 5 would compare sample sizes.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from spendguard.db.store import AuditNoteRecord, CaseRecord, NoteGradeRecord
from spendguard.eval.agreement import exact_agreement, interpret, krippendorff_alpha
from spendguard.eval.grading import DIMENSIONS, MAX_SCORE, RUBRIC, render_rubric
from spendguard.eval.report import provenance


@dataclass
class ArmScores:
    arm: str
    notes: int
    grades: int
    per_dimension: dict[str, float | None]
    total: float | None  # mean of each note's total across graders, out of 10

    @property
    def total_text(self) -> str:
        return "-" if self.total is None else f"{self.total:.2f} / {MAX_SCORE * len(DIMENSIONS)}"


@dataclass
class Agreement:
    dimension: str
    alpha: float | None
    exact: float | None
    units: int


@dataclass
class GradingReport:
    batch: str | None
    graders: list[str]
    arms: list[ArmScores]
    agreement: list[Agreement]
    overall_alpha: float | None
    comments: list[dict[str, str]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def collect(engine: Engine, *, batch: str | None = None) -> GradingReport:
    """Everything the report needs, from the store alone."""
    with Session(engine) as session:
        query = select(NoteGradeRecord)
        if batch is not None:
            query = query.where(NoteGradeRecord.batch == batch)
        grades = list(session.scalars(query))
        arms = {
            n.note_id: (n.ablation_name or "agent", n.case_id)
            for n in session.scalars(select(AuditNoteRecord))
        }
        kinds: dict[str, str] = {
            case_id: kind
            for case_id, kind in session.execute(
                select(CaseRecord.case_id, CaseRecord.anomaly_type)
            ).all()
        }

    graders = sorted({g.grader for g in grades})
    # Ratings matrix per dimension: one row per note, one column per grader.
    per_dimension: dict[str, dict[str, dict[str, int]]] = {d: defaultdict(dict) for d in DIMENSIONS}
    for grade in grades:
        for dimension, score in grade.scores.items():
            if dimension in per_dimension:
                per_dimension[dimension][grade.note_id][grade.grader] = score

    agreement = []
    for dimension in DIMENSIONS:
        notes = sorted(per_dimension[dimension])
        matrix = [[per_dimension[dimension][n].get(g) for g in graders] for n in notes]
        usable = sum(1 for row in matrix if sum(v is not None for v in row) >= 2)
        agreement.append(
            Agreement(dimension, krippendorff_alpha(matrix), exact_agreement(matrix), usable)
        )
    pooled = [
        [per_dimension[d][n].get(g) for g in graders]
        for d in DIMENSIONS
        for n in sorted(per_dimension[d])
    ]

    by_arm: dict[str, list[NoteGradeRecord]] = defaultdict(list)
    for grade in grades:
        by_arm[arms.get(grade.note_id, ("unknown", ""))[0]].append(grade)

    scored = []
    for arm in sorted(by_arm):
        of_arm = by_arm[arm]
        dims = {
            d: _mean([g.scores[d] for g in of_arm if d in g.scores]) for d in DIMENSIONS
        }  # fmt: skip
        totals = [sum(g.scores.values()) for g in of_arm if len(g.scores) == len(DIMENSIONS)]
        scored.append(
            ArmScores(
                arm=arm,
                notes=len({g.note_id for g in of_arm}),
                grades=len(of_arm),
                per_dimension=dims,
                total=_mean(totals),
            )
        )

    comments = [
        {
            "blind_id": g.blind_id,
            "arm": arms.get(g.note_id, ("unknown", ""))[0],
            "anomaly_type": kinds.get(arms.get(g.note_id, ("", ""))[1], "unknown"),
            "grader": g.grader,
            "comment": g.comment or "",
        }
        for g in sorted(grades, key=lambda g: (g.blind_id, g.grader))
        if g.comment
    ]
    return GradingReport(
        batch=batch,
        graders=graders,
        arms=scored,
        agreement=agreement,
        overall_alpha=krippendorff_alpha(pooled),
        comments=comments,
        manifest=provenance(()),
    )


def _cell(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_markdown(report: GradingReport) -> str:
    m = report.manifest
    dirty = " **(uncommitted changes)**" if m.get("dirty") else ""
    lines = [
        "# Note quality - blinded human grading",
        "",
        f"Generated {m.get('generated_at')} from commit `{m.get('commit')}`{dirty}.",
        "",
        "Regenerate with `spendguard grade report`. Graders saw the notes and the rows "
        "they cite, with no indication of which system wrote them, in a per-grader "
        "shuffled order. The rubric below was fixed before any note was graded.",
        "",
    ]
    if not report.arms:
        return "\n".join([*lines, "No grades imported yet.", ""])

    lines += [
        f"**Graders:** {', '.join(report.graders) or 'none'}.",
        "",
        "## Scores by arm",
        "",
        "| Arm | Notes | Grades | "
        + " | ".join(d.title for d in RUBRIC)
        + f" | Total /{MAX_SCORE * len(DIMENSIONS)} |",
        "|---|---:|---:|" + "---:|" * (len(DIMENSIONS) + 1),
    ]
    for arm in report.arms:
        cells = " | ".join(_cell(arm.per_dimension[d]) for d in DIMENSIONS)
        lines.append(
            f"| {arm.arm} | {arm.notes} | {arm.grades} | {cells} | **{arm.total_text}** |"
        )  # fmt: skip
    lines += [
        "",
        f"Each dimension is scored 0, 1 or 2; the total is out of {MAX_SCORE * len(DIMENSIONS)}. "
        "A mean is over every grade given, so a note graded by three people counts three times.",
        "",
        "## Inter-grader agreement",
        "",
        "Krippendorff's alpha, ordinal - it knows that 0 against 2 is a worse "
        "disagreement than 0 against 1. Exact agreement is the share of notes every "
        "grader scored identically, reported because it needs no definition.",
        "",
        "| Dimension | Alpha (ordinal) | Exact agreement | Notes with 2+ graders |",
        "|---|---:|---:|---:|",
    ]
    for a in report.agreement:
        title = next(d.title for d in RUBRIC if d.key == a.dimension)
        exact = "-" if a.exact is None else f"{a.exact:.0%}"
        lines.append(f"| {title} | {_cell(a.alpha, 3)} | {exact} | {a.units} |")
    lines += [
        "",
        f"**Pooled across dimensions: alpha = {_cell(report.overall_alpha, 3)} "
        f"({interpret(report.overall_alpha)}).**",
        "",
        "The customary reading is 0.800 and above reliable, 0.667 the floor for tentative "
        "conclusions, below that the rubric is the problem rather than the notes.",
        "",
        "## Limitations, stated rather than found",
        "",
        "- **The sample is small.** Investigations are LLM-bound (D-30), so the pool a "
        "batch is drawn from grows by roughly ten notes a day on a free tier.",
        "- **Blinding is imperfect, and one tell cannot be removed.** The arm, model, "
        "verification badge, run id, note id and case id are never exported, and each "
        "grader sees their own shuffled order. But a template note is formulaic by "
        "definition - every one opens by restating what the detector matched, and every "
        "one agrees with the detector - so a grader working through a batch can come to "
        "recognise the arm. Removing that tell would mean making the template not a "
        "template, which is the thing under test. The scores for that arm should "
        "therefore be read as an upper bound on how well blinding held, not as a "
        "fully blind comparison.",
        "- **Graders are the project's own authors.** Three independent graders were "
        "not available; the agreement number is what makes that checkable.",
        "",
    ]
    if report.comments:
        lines += ["## What graders said", "", "| Note | Arm | Type | Grader | Comment |",
                  "|---|---|---|---|---|"]  # fmt: skip
        lines += [
            f"| {c['blind_id']} | {c['arm']} | {c['anomaly_type']} | {c['grader']} "
            f"| {c['comment']} |"
            for c in report.comments
        ]
        lines.append("")
    lines += ["---", "", render_rubric().split("\n", 1)[1].lstrip("\n")]
    return "\n".join(lines) + "\n"


def write_grading_report(report: GradingReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "grading.md"
    js = out_dir / "grading.json"
    md.write_text(render_markdown(report), encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "manifest": report.manifest,
                "batch": report.batch,
                "graders": report.graders,
                "rubric": [asdict(d) for d in RUBRIC],
                "arms": [asdict(a) for a in report.arms],
                "agreement": [asdict(a) for a in report.agreement],
                "overall_alpha": report.overall_alpha,
                "comments": report.comments,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return md, js
