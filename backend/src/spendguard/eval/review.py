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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from spendguard.config import settings
from spendguard.db.store import CaseRecord, FlagReviewRecord
from spendguard.detectors.d4_vendor import _is_period_end

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

**Vendor flags are about a supplier, not about the rows.** The claim is that some
habit of theirs - round amounts, billing at period end, an odd spread of leading
digits - runs well above the rate of other suppliers selling the *same kinds of
things*. The tables under the flag give you that comparison, and the rows beneath
are a sample chosen to show the habit, with a `why shown` column saying which test
each one illustrates. Do not try to re-derive the statistic from twelve rows; you
cannot, and you are not being asked to. Judge whether an auditor should look -
then ask the opposite question, because trades differ: bulk fuel and software
licences are genuinely negotiated at round figures, annual renewals genuinely fall
at the end of a quarter, and a supplier with one product has few distinct amounts
by nature. If the rows show you a reason like that, `{IMPLAUSIBLE}` with a comment
is the useful answer.

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


def _leading_digit(amount: Any) -> int | None:
    """Leading significant digit of an amount, 1-9, matching `d4_vendor.first_digits`.

    Restated here on a scalar rather than imported, because the detector's version
    is vectorised over a numpy array of a whole supplier's amounts. `math.log10`
    gives the same answer as its `np.log10` for every positive float.
    """
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return int(value / 10 ** math.floor(math.log10(value)))


def _most_over_represented_digit(test: Any) -> tuple[int, float] | None:
    """The leading digit this supplier uses most beyond its peers, and by how much.

    A leading-digit flag is a claim about a distribution, so "the twelve largest"
    illustrates nothing - in the California sample `5497f8b8` was flagged because
    51.5% of its amounts start with 3 against 16.9% for its peers, and not one of
    the twelve rows shown started with a 3. The reviewer needs to see that digit.
    """
    if not isinstance(test, dict):
        return None
    observed, peers = test.get("observed_share"), test.get("peer_share")
    if not isinstance(observed, list) or not isinstance(peers, list):
        return None
    excesses = [
        (float(o) - float(p), i + 1)
        for i, (o, p) in enumerate(zip(observed[:9], peers[:9], strict=False))
    ]
    if not excesses:
        return None
    excess, digit = max(excesses)
    return (digit, excess) if excess > 0 else None


def _as_date(value: Any) -> date | None:
    """A row's date, whether the loader handed back a `date` or an ISO string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _rate(value: Any) -> str:
    """A measured rate as a percentage; anything unparseable passes through as text."""
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return _cell(value)


# What each vendor test counted, because they do not all count the same thing and a
# bare "n = 680" invites a reviewer to read it as 680 transactions. D4 runs the round
# and leading-digit tests over a supplier's *distinct amounts* - billing the same
# round figure fifty times is one habit, not fifty - and the period-end test over
# every transaction. An unlisted test falls back to the neutral "observations".
DENOMINATOR = {"round_numbers": "distinct amounts", "period_end": "transactions"}


def render_indicators(details: dict[str, Any]) -> list[str]:
    """The evidence behind a statistical flag, in a form a reviewer can judge.

    A D4 flag asserts a combined p-value over a supplier's whole history - hundreds
    of transactions in some cases - while the sheet shows at most
    ``settings.review_max_rows`` of them. A reviewer looking only at those rows
    cannot establish or refute the claim, and the honest answer to every such case
    is `unclear`, which is no measurement at all. Eleven of fifteen vendor flags
    came back that way on the first screen of the California sample.

    The detector already records what each test measured, what it compared against
    and by how much the supplier differs. That detail lives under a dict key, and
    ``render_cases`` previously kept only scalar fields, so all of it was dropped
    on the way to the sheet. This puts it back.

    Anything unrecognised is printed as plain key/value rather than skipped: a new
    indicator shape silently vanishing is the whole defect being fixed here.
    """
    indicators = details.get("indicators")
    if not isinstance(indicators, dict) or not indicators:
        return []

    lines = [
        "Why this supplier was flagged. Each test compares it with other suppliers in "
        "its own categories, not with a fixed rule:",
        "",
    ]

    proportions = {
        name: d
        for name, d in indicators.items()
        if isinstance(d, dict) and "observed_rate" in d and "expected_rate" in d
    }
    if proportions:
        lines += [
            "| test | what it measures | this supplier | its categories | ratio | out of | p |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for name, d in sorted(proportions.items()):
            measures = d.get("definition") or (
                f"amounts that are a round multiple of {d['unit']:,.0f}"
                if d.get("unit") is not None
                else ""
            )
            ratio = d.get("risk_ratio")
            lines.append(
                f"| {name.replace('_', ' ')} | {_cell(measures, 46)} "
                f"| {_rate(d.get('observed_rate'))} | {_rate(d.get('expected_rate'))} "
                f"| {ratio}x | {_cell(d.get('observations'))} {DENOMINATOR.get(name, 'observations')} "
                f"| {_cell(d.get('p_value'))} |"
            )
        lines.append("")

    digits = indicators.get("first_digit")
    if isinstance(digits, dict) and isinstance(digits.get("observed_share"), list):
        observed = digits["observed_share"]
        peers = digits.get("peer_share") or []
        count = digits.get("distinct_amounts")
        over = f"{count} distinct amounts" if count else "its distinct amounts"
        lines += [
            f"Leading digit across {over}, against the same categories "
            f"(chi-square {digits.get('chi_square')}, p = {digits.get('p_value')}). "
            f"A supplier that prices freely looks like its peers here:",
            "",
            "| leading digit | " + " | ".join(str(i) for i in range(1, 10)) + " |",
            "|---|" + "---:|" * 9,
            "| this supplier | " + " | ".join(_rate(v) for v in observed[:9]) + " |",
        ]
        if peers:
            lines.append("| its categories | " + " | ".join(_rate(v) for v in peers[:9]) + " |")
        lines.append("")

    handled = set(proportions) | {"first_digit"}
    for name, d in sorted(indicators.items()):
        if name in handled:
            continue
        if isinstance(d, dict):
            body = ", ".join(f"`{k}` = {v}" for k, v in sorted(d.items()))
        else:
            body = str(d)
        lines += [f"{name.replace('_', ' ')}: {_cell(body, 200)}", ""]

    return lines


def select_evidence_rows(
    case: SampledCase, rows: dict[int, dict[str, Any]]
) -> list[tuple[int, str]]:
    """Which of a case's rows to put in front of a reviewer, and why each is there.

    For D1-D3 the case *is* its rows - a duplicate pair, a split run - so the first
    ``settings.review_max_rows`` of them are the evidence and nothing needs choosing.

    A vendor flag is not like that. Its rows are the supplier's entire history, up to
    1,029 of them in the California run, and the first twelve by row id are an
    arbitrary slice that may contain no instance of the behaviour that was flagged.
    Two of the fifteen vendor flags screened on 2026-10-23 were marked `unclear` for
    exactly this: flagged for taking large orders as a new supplier, with no row near
    `first_seen` among the twelve shown.

    So for a flag carrying indicators the rows are *chosen* - a few for each test that
    fired, plus the largest overall - and each is labelled with the reason it appears.
    Round-robin rather than in priority order, so a supplier flagged on three tests
    does not spend all twelve rows on the first one.

    ``_is_period_end`` is imported from the detector rather than restated here: a
    label that disagreed with the test that produced the flag would be worse than no
    label at all.
    """
    budget = settings.review_max_rows
    indicators = case.details.get("indicators") if case.details else None
    if not isinstance(indicators, dict) or not indicators:
        return [(rid, "") for rid in case.row_ids[:budget]]

    present = [(rid, rows[rid]) for rid in case.row_ids if rid in rows]
    by_amount = sorted(present, key=lambda pair: (-(pair[1].get("amount") or 0.0), pair[0]))

    buckets: list[tuple[str, list[int]]] = []

    if case.details.get("new_vendor_high_value"):
        first_seen = _as_date(case.details.get("first_seen"))
        if first_seen is not None:
            window = timedelta(days=settings.new_vendor_days)
            buckets.append(
                (
                    f"largest in the first {settings.new_vendor_days} days",
                    [
                        rid
                        for rid, row in by_amount
                        if (d := _as_date(row.get("txn_date"))) is not None
                        and first_seen <= d <= first_seen + window
                    ],
                )
            )

    if "period_end" in indicators:
        buckets.append(
            (
                "period end",
                [
                    rid
                    for rid, row in by_amount
                    if (d := _as_date(row.get("txn_date"))) is not None and _is_period_end(d)
                ],
            )
        )

    if "round_numbers" in indicators:
        raw = indicators["round_numbers"]
        unit = float(
            (raw.get("unit") if isinstance(raw, dict) else None) or settings.round_number_unit
        )
        buckets.append(
            (
                f"round multiple of {unit:,.0f}",
                [
                    rid
                    for rid, row in by_amount
                    if (a := row.get("amount")) is not None and float(a) % unit == 0
                ],
            )
        )

    if (over := _most_over_represented_digit(indicators.get("first_digit"))) is not None:
        digit, excess = over
        buckets.append(
            (
                f"amount starts with {digit} ({excess:+.0%} vs its categories)",
                [
                    rid
                    for rid, row in by_amount
                    if (a := row.get("amount")) is not None and _leading_digit(a) == digit
                ],
            )
        )

    buckets.append(("largest", [rid for rid, _ in by_amount]))

    picked: list[tuple[int, str]] = []
    seen: set[int] = set()
    cursors = [0] * len(buckets)
    while len(picked) < budget:
        progressed = False
        for i, (label, candidates) in enumerate(buckets):
            if len(picked) >= budget:
                break
            while cursors[i] < len(candidates) and candidates[cursors[i]] in seen:
                cursors[i] += 1
            if cursors[i] >= len(candidates):
                continue
            rid = candidates[cursors[i]]
            cursors[i] += 1
            seen.add(rid)
            picked.append((rid, label))
            progressed = True
        if not progressed:
            break
    return picked


def render_cases(
    sample: Sequence[SampledCase], load_evidence: EvidenceLoader, currency: str
) -> str:
    """The cases as a reviewer sees them: what was flagged, why, and the rows behind it."""
    # A vendor flag's rows have to be chosen (see `select_evidence_rows`), which
    # means loading all of them, not the first `review_max_rows`.
    wanted: set[int] = set()
    for case in sample:
        chooses = isinstance((case.details or {}).get("indicators"), dict)
        wanted.update(case.row_ids if chooses else case.row_ids[: settings.review_max_rows])
    evidence = load_evidence(sorted(wanted))
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
            # A plain list used to be dropped along with everything else non-scalar,
            # which hid how many departments a flagged supplier billed - part of what
            # the flag is about. Only lists of plain values: D1 also records `pairs`,
            # a list of dicts of its own matching state, and a reviewer reading a
            # truncated Python repr of it learns nothing.
            listed = {
                k: v
                for k, v in case.details.items()
                if isinstance(v, list)
                and k != "row_ids"
                and all(not isinstance(item, list | dict) for item in v)
            }
            for key, values in sorted(listed.items()):
                if not values:
                    continue
                joined = ", ".join(_cell(v, 40) for v in values[:6])
                more = f" (+{len(values) - 6} more)" if len(values) > 6 else ""
                lines += [f"`{key}` ({len(values)}): {joined}{more}", ""]
            lines += render_indicators(case.details)
        picked = select_evidence_rows(case, evidence)
        labelled = any(why for _, why in picked)
        if labelled:
            lines += [
                f"{len(picked)} of this supplier's {len(case.row_ids)} transactions, chosen to "
                "show the behaviour each test flagged rather than the first few by row id:",
                "",
            ]
        head = [
            "row", "document", "supplier", "date", f"amount ({currency})",
            "department", "item", "qty", "unit price",
        ]  # fmt: skip
        align = ["---:", "---", "---", "---", "---:", "---", "---", "---:", "---:"]
        if labelled:
            head.append("why shown")
            align.append("---")
        lines += ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
        for row_id, why in picked:
            row = evidence.get(row_id)
            if row is None:
                cells = [str(row_id), "", "_row not found_", "", "", "", "", "", ""]
            else:
                cells = [
                    str(row_id),
                    _cell(row.get("source_row_ref"), 24),
                    _cell(row.get("vendor_name"), 34),
                    _cell(row.get("txn_date")),
                    _cell(row.get("amount")),
                    _cell(row.get("officer_id"), 34),
                    _cell(row.get("item_desc")),
                    _cell(row.get("quantity")),
                    _cell(row.get("unit_price")),
                ]
            if labelled:
                cells.append(_cell(why, 56))
            lines.append("| " + " | ".join(cells) + " |")
        hidden = len(case.row_ids) - len(picked)
        if hidden > 0:
            # One empty cell per remaining column. This line was written before the
            # `document` column existed and was never widened, so it rendered as a
            # broken row - on a D4 case, the row saying "763 more rows".
            note = f"_{hidden} more row{'' if hidden == 1 else 's'} in this case_"
            lines.append("| … | " + note + " |" * (len(head) - 1))
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
