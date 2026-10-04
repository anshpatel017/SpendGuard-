"""Adjusted precision on unlabelled real data (EVALUATION 5.1, FR-7.12).

On the synthetic dataset every anomaly was planted, so precision is a fact. On
real procurement data nothing is labelled: a flagged case is neither known to be
fraud nor known to be innocent. Reporting "precision" there would be inventing a
number.

What can honestly be done is sample the flags, have people judge them against
the evidence, and report **adjusted precision** - the share judged plausible -
with an interval wide enough to admit how small the sample was. Three rules make
that defensible rather than decorative:

* **The sample is drawn before anything is judged**, seeded, and recorded. A
  sample chosen after seeing the verdicts is not a sample.
* **"Unclear" is a first-class answer.** A reviewer forced to choose between
  plausible and implausible will guess, and a guess enters the numerator. Unclear
  verdicts are excluded from the ratio and reported beside it, because a detector
  whose flags cannot be judged has a problem the ratio would hide.
* **The interval is always shown.** 8 of 10 plausible is not 80% precision; it is
  somewhere between about 49% and 94%. Wilson's interval is used rather than the
  textbook normal one, which gives impossible bounds on small or lopsided samples.

Two sampling strategies, because they answer different questions. ``top`` takes
the highest-severity flags - what an auditor actually works through, and the
number FR-7.12 asks for. ``random`` takes a seeded random sample - the unbiased
estimate of precision over everything flagged. Severity is amount-weighted, so
the two differ, and the report always says which was used.

    spendguard review export --store … --per-detector 15
    spendguard review import reviews-a.csv --store …
    spendguard review report --store … -> docs/results/real-data.md
"""

from __future__ import annotations

import csv
import json
import math
import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from spendguard.config import settings
from spendguard.db.store import CaseRecord, FlagReviewRecord

PLAUSIBLE = "plausible"
IMPLAUSIBLE = "implausible"
UNCLEAR = "unclear"
VERDICTS: tuple[str, ...] = (PLAUSIBLE, IMPLAUSIBLE, UNCLEAR)

COLUMNS: tuple[str, ...] = ("case_id", "detector", "anomaly_type", "verdict", "comment")
KEY_FILE = "sample.json"
# A real item description can be six lines of contract prose. A newline inside a
# Markdown cell silently destroys the table, and a pipe ends the cell early.
CELL_LIMIT = 90
CASES_FILE = "cases.md"
GUIDE_FILE = "how-to-review.md"

STRATEGIES: tuple[str, ...] = ("top", "random")

# Fetches the evidence rows a batch needs, keyed by row id - only the sampled cases'
# rows, because a D4 case can cover hundreds and the whole dataset is 337,000.
EvidenceLoader = Callable[[list[int]], dict[int, dict[str, Any]]]


class ReviewError(RuntimeError):
    """A sheet or a sample that cannot be trusted."""


# ------------------------------------------------------------------ the interval


def wilson(successes: int, trials: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion.

    Not the normal approximation: with 10 of 10 plausible that gives 100% +/- 0,
    which is false, and with small samples it produces bounds below 0 or above 1.
    Wilson stays inside [0, 1] and never collapses to a point.
    """
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


# ------------------------------------------------------------------ sampling


@dataclass(frozen=True)
class SampledCase:
    case_id: str
    detector: str
    anomaly_type: str
    severity_prelim: float
    amount_at_risk: float
    row_ids: list[int]
    vendor_key: str | None
    details: dict[str, Any]


def sample_flags(
    engine: Engine, *, per_detector: int, seed: int, strategy: str = "top"
) -> list[SampledCase]:
    """A fixed, recorded sample of flagged cases - drawn before anything is judged."""
    if strategy not in STRATEGIES:
        raise ReviewError(f"unknown strategy {strategy!r}; known: {', '.join(STRATEGIES)}")
    with Session(engine) as session:
        cases = list(session.scalars(select(CaseRecord)))
    if not cases:
        raise ReviewError("no cases in this store. Run `spendguard detect` against it first.")

    rng = random.Random(seed)
    chosen: list[CaseRecord] = []
    for detector in sorted({c.detector for c in cases}):
        of_detector = sorted(
            (c for c in cases if c.detector == detector),
            key=lambda c: (-c.severity_prelim, c.case_id),  # ties broken stably
        )
        if strategy == "top":
            chosen += of_detector[:per_detector]
        else:
            chosen += rng.sample(of_detector, min(per_detector, len(of_detector)))
    chosen.sort(key=lambda c: (c.detector, c.case_id))
    return [
        SampledCase(
            case_id=c.case_id,
            detector=c.detector,
            anomaly_type=c.anomaly_type,
            severity_prelim=c.severity_prelim,
            amount_at_risk=c.amount_at_risk,
            row_ids=list(c.row_ids),
            vendor_key=c.vendor_key,
            details=dict(c.details or {}),
        )
        for c in chosen
    ]


# ------------------------------------------------------------------ export

GUIDE = f"""# Reviewing flagged transactions

These are real purchase records. **Nothing here is known to be fraud**, and
nothing here is known to be innocent - that is the whole reason for this
exercise. You are not deciding whether something *is* fraud. You are deciding
whether the flag is one an auditor would reasonably act on.

For each case, read the evidence rows in `{CASES_FILE}` and put one word in the
`verdict` column of your sheet:

| Verdict | Means |
|---|---|
| `{PLAUSIBLE}` | The pattern the detector describes is really there in these rows, and it is worth an auditor's time. |
| `{IMPLAUSIBLE}` | The pattern is not there, or it is there but has an obvious innocent explanation visible in the rows. |
| `{UNCLEAR}` | You genuinely cannot tell from what is shown. |

**Look at the `document` column first on duplicate flags.** Two rows carrying the
same document number are two lines of *one* purchase order, not two orders - a
repeat there is usually how the order was written up, not a duplicate record.
Two rows with *different* document numbers are the ones worth attention.

**Use `{UNCLEAR}` freely.** It is a real answer, reported separately, and it
costs the project nothing. Guessing does: a guess lands in the precision figure
and makes it wrong in a way nobody can detect afterwards.

The `comment` column is optional and is the most useful thing you can leave,
especially on `{IMPLAUSIBLE}` - say what the innocent explanation was.
"""


def _cell(value: Any, limit: int = CELL_LIMIT) -> str:
    """One Markdown table cell: no newlines, no pipes, and short enough to read."""
    text = " ".join(str("" if value is None else value).split())
    text = text.replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_cases(
    sample: Sequence[SampledCase], load_evidence: EvidenceLoader, currency: str
) -> str:
    """The cases as a reviewer sees them: what was flagged, why, and the rows behind it."""
    evidence = load_evidence(
        sorted({r for c in sample for r in c.row_ids[: settings.review_max_rows]})
    )
    lines = [
        "# Flagged transactions to review",
        "",
        f"{len(sample)} cases. Read each one's rows, then fill the `verdict` column in your "
        f"sheet. `{GUIDE_FILE}` says what the words mean.",
        "",
    ]
    for case in sample:
        lines += [
            "---",
            "",
            f"## {case.case_id[:8]}  -  {case.anomaly_type}",
            "",
            f"Flagged by **{case.detector.upper()}**, severity {case.severity_prelim:.1f}, "
            f"{settings.money(case.amount_at_risk)} at risk.",
            "",
        ]
        if case.details:
            shown = {k: v for k, v in case.details.items() if not isinstance(v, list | dict)}
            if shown:
                lines += [
                    "What the detector matched: "
                    + ", ".join(f"`{k}` = {v}" for k, v in sorted(shown.items())),
                    "",
                ]
        lines += [
            f"| row | document | supplier | date | amount ({currency}) | department | item "
            "| qty | unit price |",
            "|---:|---|---|---|---:|---|---|---:|---:|",
        ]
        for row_id in case.row_ids[: settings.review_max_rows]:
            row = evidence.get(row_id)
            if row is None:
                lines.append(f"| {row_id} | | _row not found_ | | | | | | |")
                continue
            lines.append(
                f"| {row_id} | {_cell(row.get('source_row_ref'), 24)} "
                f"| {_cell(row.get('vendor_name'), 34)} | {_cell(row.get('txn_date'))} "
                f"| {_cell(row.get('amount'))} | {_cell(row.get('officer_id'), 34)} "
                f"| {_cell(row.get('item_desc'))} | {_cell(row.get('quantity'))} "
                f"| {_cell(row.get('unit_price'))} |"
            )
        if len(case.row_ids) > settings.review_max_rows:
            # One empty cell per remaining column. This line was written before the
            # `document` column existed and was never widened, so it rendered as a
            # broken row - on a D4 case, the row saying "763 more rows".
            hidden = len(case.row_ids) - settings.review_max_rows
            lines.append(
                f"| … | _{hidden} more row{'' if hidden == 1 else 's'} in this case_"
                + " |" * 7
                + " |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ReviewBatch:
    batch_id: str
    out_dir: Path
    sample: list[SampledCase]
    sheets: list[Path]
    strategy: str


def export(
    engine: Engine,
    out_dir: Path,
    *,
    per_detector: int,
    seed: int,
    reviewers: Sequence[str],
    load_evidence: EvidenceLoader,
    strategy: str = "top",
    dataset: str = "real",
) -> ReviewBatch:
    sample = sample_flags(engine, per_detector=per_detector, seed=seed, strategy=strategy)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = f"review-{dataset}-{strategy}{per_detector}-seed{seed}"
    (out_dir / GUIDE_FILE).write_text(GUIDE, encoding="utf-8")
    (out_dir / CASES_FILE).write_text(
        render_cases(sample, load_evidence, settings.currency), encoding="utf-8"
    )
    sheets = []
    for name in reviewers:
        path = out_dir / f"reviews-{name}.csv"
        # Same order for everyone: cases are grouped by detector, and a reviewer
        # judging one detector's flags in a run judges them more consistently.
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            for case in sample:
                writer.writerow([case.case_id, case.detector, case.anomaly_type, "", ""])
        sheets.append(path)
    (out_dir / KEY_FILE).write_text(
        json.dumps(
            {
                "batch_id": batch_id,
                "dataset": dataset,
                "strategy": strategy,
                "per_detector": per_detector,
                "seed": seed,
                "reviewers": list(reviewers),
                "cases": [asdict(c) for c in sample],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return ReviewBatch(batch_id, out_dir, sample, sheets, strategy)


# ------------------------------------------------------------------ import


def load_sample(out_dir: Path) -> dict[str, Any]:
    path = out_dir / KEY_FILE
    if not path.exists():
        raise ReviewError(f"no {KEY_FILE} in {out_dir}. Export the batch before importing reviews.")
    sample: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return sample


def import_reviews(engine: Engine, sheet: Path, sample: dict[str, Any], reviewer: str) -> int:
    """Store one reviewer's filled sheet. Re-importing replaces their verdicts."""
    in_batch = {c["case_id"] for c in sample["cases"]}
    reviews: list[FlagReviewRecord] = []
    problems: list[str] = []
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "verdict" not in rows[0]:
        raise ReviewError(f"{sheet.name} has no `verdict` column.")
    for line, row in enumerate(rows, start=2):
        case_id = (row.get("case_id") or "").strip()
        verdict = (row.get("verdict") or "").strip().lower()
        if not case_id or not verdict:
            continue  # not reviewed yet
        if case_id not in in_batch:
            problems.append(f"line {line}: {case_id[:8]} is not in this batch")
            continue
        if verdict not in VERDICTS:
            problems.append(f"line {line}: {verdict!r} is not one of {', '.join(VERDICTS)}")
            continue
        reviews.append(
            FlagReviewRecord(
                review_id=str(uuid.uuid4()),
                case_id=case_id,
                reviewer=reviewer,
                batch=sample["batch_id"],
                verdict=verdict,
                comment=(row.get("comment") or "").strip() or None,
            )
        )
    if problems:
        raise ReviewError(f"{sheet.name}: " + "; ".join(problems[:10]))
    if not reviews:
        raise ReviewError(f"{sheet.name} has no filled rows yet.")

    with Session(engine) as session, session.begin():
        existing = session.scalars(
            select(FlagReviewRecord).where(
                FlagReviewRecord.batch == sample["batch_id"],
                FlagReviewRecord.reviewer == reviewer,
            )
        ).all()
        for record in existing:
            session.delete(record)
        session.flush()
        session.add_all(reviews)
    return len(reviews)


# ------------------------------------------------------------------ the numbers


@dataclass
class DetectorPrecision:
    detector: str
    anomaly_type: str
    flagged_total: int  # everything this detector raised, not just the sample
    reviewed: int
    plausible: int
    implausible: int
    unclear: int

    @property
    def judged(self) -> int:
        return self.plausible + self.implausible

    @property
    def adjusted_precision(self) -> float | None:
        return self.plausible / self.judged if self.judged else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.plausible, self.judged)


@dataclass
class ReviewReport:
    batch: str | None
    strategy: str | None
    reviewers: list[str]
    detectors: list[DetectorPrecision]
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, str]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _majority(verdicts: list[str]) -> tuple[str, bool]:
    """One verdict per case, plus whether the reviewers disagreed.

    A tie is `unclear`: if the people who looked at it could not agree, the
    honest record is that it could not be judged, not a coin toss.
    """
    counts = {v: verdicts.count(v) for v in set(verdicts)}
    best = max(counts.values())
    winners = sorted(v for v, n in counts.items() if n == best)
    disagreed = len(set(verdicts)) > 1
    return (winners[0] if len(winners) == 1 else UNCLEAR), disagreed


def collect(engine: Engine, *, batch: str | None = None) -> ReviewReport:
    from spendguard.eval.report import provenance

    with Session(engine) as session:
        query = select(FlagReviewRecord)
        if batch is not None:
            query = query.where(FlagReviewRecord.batch == batch)
        reviews = list(session.scalars(query))
        cases = {c.case_id: c for c in session.scalars(select(CaseRecord))}

    per_case: dict[str, list[FlagReviewRecord]] = {}
    for review in reviews:
        per_case.setdefault(review.case_id, []).append(review)

    totals: dict[str, int] = {}
    for case in cases.values():
        totals[case.detector] = totals.get(case.detector, 0) + 1

    tallies: dict[str, DetectorPrecision] = {}
    disagreements = []
    for case_id, found in sorted(per_case.items()):
        if case_id not in cases:  # the store was re-detected and this case is gone
            continue
        case = cases[case_id]
        verdict, disagreed = _majority([r.verdict for r in found])
        row = tallies.setdefault(
            case.detector,
            DetectorPrecision(
                case.detector, case.anomaly_type, totals.get(case.detector, 0), 0, 0, 0, 0
            ),  # fmt: skip
        )
        row.reviewed += 1
        setattr(row, verdict, getattr(row, verdict) + 1)
        if disagreed:
            disagreements.append(
                {
                    "case_id": case_id,
                    "detector": case.detector,
                    "verdicts": {
                        r.reviewer: r.verdict for r in sorted(found, key=lambda r: r.reviewer)
                    },  # fmt: skip
                }
            )

    comments = [
        {
            "case_id": r.case_id[:8],
            "detector": cases[r.case_id].detector if r.case_id in cases else "?",
            "reviewer": r.reviewer,
            "verdict": r.verdict,
            "comment": r.comment or "",
        }
        for r in sorted(reviews, key=lambda r: (r.case_id, r.reviewer))
        if r.comment
    ]
    return ReviewReport(
        batch=batch,
        strategy=None,
        reviewers=sorted({r.reviewer for r in reviews}),
        detectors=[tallies[d] for d in sorted(tallies)],
        disagreements=disagreements,
        comments=comments,
        manifest=provenance(()),
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def render_markdown(report: ReviewReport, dataset: dict[str, Any] | None = None) -> str:
    m = report.manifest
    dirty = " **(uncommitted changes)**" if m.get("dirty") else ""
    lines = [
        "# Real data - detection and reviewed precision",
        "",
        f"Generated {m.get('generated_at')} from commit `{m.get('commit')}`{dirty}. "
        "Regenerate with `spendguard review report`.",
        "",
    ]
    if dataset:
        lines += [
            "## The dataset",
            "",
            "| | |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in dataset.items()],
            "",
        ]
    if not report.detectors:
        return "\n".join([*lines, "No flags reviewed yet.", ""])

    strategy = report.strategy or "unknown"
    lines += [
        "## Adjusted precision",
        "",
        "**Nothing in this dataset is labelled.** These are not precision figures in "
        "the sense the synthetic evaluation reports them: they are the share of a "
        "*sample* of flags that people judged an auditor should act on, which is the "
        "most that can honestly be said about unlabelled data (FR-7.12).",
        "",
        f"Sample: up to {settings.review_per_detector} flags per detector, drawn "
        f"**{strategy}** and fixed before any verdict was given. Reviewers: "
        f"{', '.join(report.reviewers) or 'none'}. Where they disagreed, the majority "
        "verdict counts and a tie counts as unclear.",
        "",
        "| Detector | Anomaly | Flagged in total | Reviewed | Plausible | Implausible "
        "| Unclear | Adjusted precision | 95% interval |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for d in report.detectors:
        interval = d.interval
        span = "-" if interval is None else f"{interval[0]:.0%} - {interval[1]:.0%}"
        lines.append(
            f"| {d.detector} | {d.anomaly_type} | {d.flagged_total:,} | {d.reviewed} "
            f"| {d.plausible} | {d.implausible} | {d.unclear} "
            f"| **{_pct(d.adjusted_precision)}** | {span} |"
        )
    lines += [
        "",
        "The interval is Wilson's, over the flags that were *judged* - unclear verdicts "
        "are excluded from the ratio and shown separately, because a detector whose "
        "flags cannot be judged has a problem that a ratio would hide. With samples this "
        "small the interval is wide, and that width is the finding: it says what the "
        "sample can and cannot support.",
        "",
    ]
    if strategy == "top":
        lines += [
            "**Stated caveat.** These are the *highest-severity* flags, and severity is "
            "amount-weighted. This is what an auditor works through first, so it is the "
            "useful number - but it is not precision over everything flagged, which would "
            "be lower. `--strategy random` measures that instead.",
            "",
        ]
    if report.disagreements:
        lines += [
            f"## Where reviewers disagreed ({len(report.disagreements)})",
            "",
            "| Case | Detector | Verdicts |",
            "|---|---|---|",
            *[
                f"| {d['case_id'][:8]} | {d['detector']} | "
                + ", ".join(f"{k}: {v}" for k, v in d["verdicts"].items())
                + " |"
                for d in report.disagreements
            ],
            "",
        ]
    if report.comments:
        lines += [
            "## What reviewers said",
            "",
            "| Case | Detector | Reviewer | Verdict | Comment |",
            "|---|---|---|---|---|",
            *[
                f"| {c['case_id']} | {c['detector']} | {c['reviewer']} | {c['verdict']} "
                f"| {c['comment']} |"
                for c in report.comments
            ],
            "",
        ]
    return "\n".join(lines) + "\n"


def write_review_report(
    report: ReviewReport, out_dir: Path, dataset: dict[str, Any] | None = None
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "real-data.md"
    js = out_dir / "real-data.json"
    md.write_text(render_markdown(report, dataset), encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "manifest": report.manifest,
                "batch": report.batch,
                "strategy": report.strategy,
                "dataset": dataset or {},
                "reviewers": report.reviewers,
                "detectors": [
                    {
                        **asdict(d),
                        "adjusted_precision": d.adjusted_precision,
                        "interval": d.interval,
                    }
                    for d in report.detectors
                ],
                "disagreements": report.disagreements,
                "comments": report.comments,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return md, js
