"""The blinded grading kit (EVALUATION section 5.3).

Citation validity is checked by rule and by a model. Neither can answer the
question the project actually rests on: *is this note worth an auditor's time?*
A note can cite every row correctly and still say nothing a detector did not
already say. That is what people have to judge, and judging it fairly needs
three things a spreadsheet does not give you by itself.

**Blinding.** A grader who knows which note the agent wrote will score it
higher. So notes are pooled across arms and models, given opaque ids, shuffled,
and written out with nothing that identifies where they came from - no arm, no
model, no verification badge, no run id. The key that maps ids back is written
to a separate file the graders are not given.

**A rubric fixed in advance.** Written here, exported with every batch, and
printed in the report, so nobody can decide after the fact what "good" meant.
Five dimensions, 0-1-2 each. Three points, not five: three people agree far
better on three, and an agreement number nobody believes makes the scores
worthless.

**Agreement.** Reported beside every score - see ``eval/agreement.py``.

The evidence rows a note cites are exported with it. Without them a grader
cannot judge factual accuracy, only fluency, and fluency is exactly what a
language model is best at faking.

    spendguard grade export --seed 42          # sheets + notes + key
    spendguard grade import <filled csv>       # into the store, by blind id
    spendguard grade report --seed 42          # -> docs/results/grading.md
"""

from __future__ import annotations

import csv
import json
import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from spendguard.config import settings
from spendguard.db.store import AuditNoteRecord, CaseRecord, NoteGradeRecord

BLIND_PREFIX = "N"
KEY_FILE = "key.json"
RUBRIC_FILE = "rubric.md"
NOTES_FILE = "notes.md"
MAX_SCORE = 2

# Fetches the evidence rows a batch needs, keyed by row id. A callable rather than a
# table, because which rows are needed is only known once the sample is drawn.
EvidenceLoader = Callable[[list[int]], dict[int, dict[str, Any]]]


@dataclass(frozen=True)
class Dimension:
    """One rubric axis, with what each of its three scores means."""

    key: str
    title: str
    question: str
    anchors: tuple[str, str, str]  # what 0, 1 and 2 mean


# Fixed in advance (EVALUATION 5.3). Changing this changes what every past grade
# meant, so a batch records the rubric it was graded against.
RUBRIC: tuple[Dimension, ...] = (
    Dimension(
        "factual_accuracy",
        "Factual accuracy",
        "Does every figure, date and name in the note match the rows shown beside it?",
        (
            "a statement contradicts the evidence rows",
            "everything checkable is right, but something material is vague or unsupported",
            "every checkable statement matches the evidence exactly",
        ),
    ),
    Dimension(
        "evidence_sufficiency",
        "Evidence sufficiency",
        "Do the rows cited actually establish the finding, or is more needed?",
        (
            "the cited rows do not establish the finding",
            "they point at it but leave an obvious gap",
            "they establish it; an auditor would not need to go looking",
        ),
    ),
    Dimension(
        "alternative_considered",
        "Innocent explanation considered",
        "Does the note weigh the benign reading - a fixed contract, a premium "
        "specification, two genuinely separate requirements - and say why it does or "
        "does not hold here?",
        (
            "not considered at all; the detector's reading is simply repeated",
            "mentioned, but not tested against the evidence",
            "named and tested against the evidence, either way",
        ),
    ),
    Dimension(
        "verdict_justified",
        "Verdict justified by the note alone",
        "Reading only this note, is its verdict the one the evidence supports? "
        "Judge the reasoning shown, not whether the case is truly fraud.",
        (
            "the evidence in the note points the other way",
            "defensible, but the note does not carry it",
            "the note's own evidence supports its verdict",
        ),
    ),
    Dimension(
        "actionability",
        "Actionability",
        "Could an auditor act on the recommended action tomorrow without going "
        "back to the data to work out what to do?",
        (
            "generic: it would apply to any case of this type",
            "specific, but leaves the first step to the reader",
            "names the step, the document or the person to take it up with",
        ),
    ),
)

DIMENSIONS: tuple[str, ...] = tuple(d.key for d in RUBRIC)
COLUMNS: tuple[str, ...] = ("blind_id", *DIMENSIONS, "comment")


class GradingError(RuntimeError):
    """A sheet that cannot be trusted: unknown ids, scores off the scale, missing columns."""


# ------------------------------------------------------------------ sampling


@dataclass(frozen=True)
class BlindedNote:
    blind_id: str
    note_id: str
    case_id: str
    anomaly_type: str
    arm: str  # "agent" or the ablation's name - never exported to a grader
    model: str


def _arm(note: AuditNoteRecord) -> str:
    return note.ablation_name or "agent"


def sample_notes(
    engine: Engine, *, size: int, seed: int, arms: Sequence[str] | None = None
) -> list[BlindedNote]:
    """Up to ``size`` notes, spread evenly over the arms, then over anomaly types.

    Even over arms because the comparison is between arms: 40 agent notes and 3
    template ones would measure the agent precisely and the template not at all.
    Within an arm, spread over anomaly types, because a duplicate is far easier
    to write well than a vendor red flag and a sample of one type would flatter
    whichever arm happened to draw the easy ones.
    """
    rng = random.Random(seed)
    with Session(engine) as session:
        notes = list(session.scalars(select(AuditNoteRecord)))
        kinds: dict[str, str] = {
            case_id: kind
            for case_id, kind in session.execute(
                select(CaseRecord.case_id, CaseRecord.anomaly_type)
            ).all()
        }

    # Newest note per (case, arm, model): a case investigated twice is one note here.
    newest: dict[tuple[str, str, str], AuditNoteRecord] = {}
    for note in sorted(notes, key=lambda n: n.created_at):
        newest[(note.case_id, _arm(note), note.model_name)] = note
    pool = list(newest.values())
    if arms is not None:
        pool = [n for n in pool if _arm(n) in arms]

    by_arm: dict[str, list[AuditNoteRecord]] = {}
    for note in pool:
        by_arm.setdefault(_arm(note), []).append(note)

    chosen: list[AuditNoteRecord] = []
    per_arm = max(1, size // len(by_arm)) if by_arm else 0
    for arm in sorted(by_arm):
        chosen += _spread(by_arm[arm], per_arm, kinds, rng)
    # A short arm leaves room; fill it from whatever is left, still seeded.
    if len(chosen) < size:
        rest = sorted(set(pool) - set(chosen), key=lambda n: n.note_id)
        chosen += rng.sample(rest, min(size - len(chosen), len(rest)))

    rng.shuffle(chosen)
    return [
        BlindedNote(
            blind_id=f"{BLIND_PREFIX}-{i:03d}",
            note_id=n.note_id,
            case_id=n.case_id,
            anomaly_type=kinds.get(n.case_id, "unknown"),
            arm=_arm(n),
            model=n.model_name,
        )
        for i, n in enumerate(chosen, start=1)
    ]


def _spread(
    notes: list[AuditNoteRecord], want: int, kinds: dict[str, str], rng: random.Random
) -> list[AuditNoteRecord]:
    """Take ``want`` notes, one anomaly type at a time, so no type dominates."""
    buckets: dict[str, list[AuditNoteRecord]] = {}
    for note in sorted(notes, key=lambda n: n.note_id):
        buckets.setdefault(kinds.get(note.case_id, "unknown"), []).append(note)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    taken: list[AuditNoteRecord] = []
    while len(taken) < want and any(buckets.values()):
        for kind in sorted(buckets):
            if buckets[kind] and len(taken) < want:
                taken.append(buckets[kind].pop())
    return taken


# ------------------------------------------------------------------ export


def render_rubric() -> str:
    lines = [
        "# Grading rubric - fixed in advance",
        "",
        "Score every note on all five dimensions. **0, 1 or 2**, no half marks.",
        "Judge the note as written, against the evidence rows printed beside it.",
        "You are not told which system wrote it, and you should not try to work it out.",
        "",
        "If a dimension genuinely does not apply, leave the cell empty rather than "
        "guessing - a blank is handled, a guess is not.",
        "",
    ]
    for d in RUBRIC:
        lines += [f"## {d.title} (`{d.key}`)", "", d.question, ""]
        lines += [f"- **{score}** - {text}" for score, text in enumerate(d.anchors)]
        lines.append("")
    lines += [
        "## Comment",
        "",
        "One line, optional, and the most useful thing you can leave: what made you "
        "give the lowest score you gave.",
        "",
    ]
    return "\n".join(lines)


def render_notes(
    blinded: Sequence[BlindedNote], engine: Engine, load_evidence: EvidenceLoader
) -> str:
    """The notes as a grader sees them: the note, its claims, and the rows it cites.

    Deliberately absent: the arm, the model, the verification badge, the run id,
    the detector score and the case id. Anything that survives here is something
    a grader could unblind the sample with.
    """
    with Session(engine) as session:
        records = {
            n.note_id: n
            for n in session.scalars(
                select(AuditNoteRecord).where(
                    AuditNoteRecord.note_id.in_([b.note_id for b in blinded])
                )
            )
        }
    wanted = sorted(
        {
            row
            for b in blinded
            for claim in records[b.note_id].claims
            for row in claim.get("row_ids", [])
        }
    )
    evidence = load_evidence(wanted)
    lines = [
        "# Notes to grade",
        "",
        f"{len(blinded)} notes, in no particular order. Grade each one in your sheet "
        f"against `{RUBRIC_FILE}`.",
        "",
    ]
    for b in blinded:
        note = records[b.note_id]
        lines += [
            "---",
            "",
            f"## {b.blind_id}",
            "",
            f"**Anomaly type:** {b.anomaly_type}",
            "",
            f"**Verdict:** {note.verdict}",
            "",
            f"**Finding.** {note.finding}",
            "",
            "**Claims**",
            "",
        ]
        for claim in note.claims:
            rows = ", ".join(str(r) for r in claim.get("row_ids", []))
            lines.append(f"- {claim.get('text', '')}  _(rows {rows})_")
            for fact in claim.get("facts", []):
                lines.append(
                    f"    - states row {fact['row_id']} `{fact['field']}` = `{fact['value']}`"
                )
        lines += [
            "",
            f"**Policy clauses cited:** {', '.join(note.policy_clauses) or 'none'}",
            "",
            f"**Recommended action.** {note.recommended_action}",
            "",
            "**Evidence rows**",
            "",
            "| row_id | vendor | date | amount | invoice | item | qty | unit price |",
            "|---:|---|---|---:|---|---|---:|---:|",
        ]
        cited = sorted({r for c in note.claims for r in c.get("row_ids", [])})
        for row_id in cited[: settings.verifier_max_rows]:
            row = evidence.get(row_id)
            if row is None:
                lines.append(f"| {row_id} | _row not found_ | | | | | | |")
                continue
            lines.append(
                f"| {row_id} | {row.get('vendor_name', '')} | {row.get('txn_date', '')} "
                f"| {row.get('amount', '')} | {row.get('invoice_no') or ''} "
                f"| {row.get('item_desc') or ''} | {row.get('quantity') or ''} "
                f"| {row.get('unit_price') or ''} |"
            )
        if len(cited) > settings.verifier_max_rows:
            lines.append(f"| … | _{len(cited) - settings.verifier_max_rows} more cited rows_ "
                         "| | | | | | |")  # fmt: skip
        lines.append("")
    return "\n".join(lines) + "\n"


def write_sheet(path: Path, blinded: Sequence[BlindedNote], rng: random.Random) -> Path:
    """One grader's empty sheet. Row order is shuffled per grader, ids are not.

    Per-grader order so three people do not tire at the same notes; shared ids
    so the three sheets can still be joined into one agreement calculation.
    """
    order = list(blinded)
    rng.shuffle(order)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for b in order:
            writer.writerow([b.blind_id, *([""] * len(DIMENSIONS)), ""])
    return path


@dataclass(frozen=True)
class Batch:
    batch_id: str
    out_dir: Path
    blinded: list[BlindedNote]
    sheets: list[Path]


def export(
    engine: Engine,
    out_dir: Path,
    *,
    seed: int,
    size: int,
    graders: Sequence[str],
    load_evidence: EvidenceLoader,
    arms: Sequence[str] | None = None,
) -> Batch:
    """Write the rubric, the blinded notes, one empty sheet per grader, and the key."""
    blinded = sample_notes(engine, size=size, seed=seed, arms=arms)
    if not blinded:
        raise GradingError(
            "no notes to grade. Run `spendguard investigate --eval-seed "
            f"{seed}` (and its ablation arms) first."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = f"grade-seed{seed}-n{len(blinded)}"
    (out_dir / RUBRIC_FILE).write_text(render_rubric(), encoding="utf-8")
    (out_dir / NOTES_FILE).write_text(
        render_notes(blinded, engine, load_evidence), encoding="utf-8"
    )
    sheets = [
        write_sheet(out_dir / f"grades-{name}.csv", blinded, random.Random(f"{seed}-{name}"))
        for name in graders
    ]
    # The key is what unblinds the batch. It stays with whoever ran the export.
    (out_dir / KEY_FILE).write_text(
        json.dumps(
            {
                "batch_id": batch_id,
                "seed": seed,
                "graders": list(graders),
                "rubric": [d.key for d in RUBRIC],
                "notes": [
                    {
                        "blind_id": b.blind_id,
                        "note_id": b.note_id,
                        "case_id": b.case_id,
                        "anomaly_type": b.anomaly_type,
                        "arm": b.arm,
                        "model": b.model,
                    }
                    for b in blinded
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return Batch(batch_id, out_dir, blinded, sheets)


# ------------------------------------------------------------------ import


def load_key(out_dir: Path) -> dict[str, Any]:
    path = out_dir / KEY_FILE
    if not path.exists():
        raise GradingError(f"no {KEY_FILE} in {out_dir}. Export the batch before importing grades.")
    key: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return key


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise GradingError(f"{path.name} has no rows.")
    missing = [c for c in COLUMNS if c not in (rows[0].keys() | {"comment"})]
    if missing:
        raise GradingError(f"{path.name} is missing column(s): {', '.join(missing)}")
    return rows


def import_grades(engine: Engine, sheet: Path, key: dict[str, Any], grader: str) -> int:
    """Store one grader's filled sheet. Re-importing replaces that grader's grades.

    A row is rejected, not rounded, when a score is off the scale or the blind id
    is not in the batch: a typo in a grade is a wrong number in the report, and
    the report is the thing the project is judged on.
    """
    by_blind = {n["blind_id"]: n for n in key["notes"]}
    graded: list[NoteGradeRecord] = []
    problems: list[str] = []
    for line, row in enumerate(read_sheet(sheet), start=2):
        blind_id = (row.get("blind_id") or "").strip()
        if not blind_id:
            continue
        note = by_blind.get(blind_id)
        if note is None:
            problems.append(f"line {line}: {blind_id!r} is not in this batch")
            continue
        scores: dict[str, int] = {}
        for dimension in DIMENSIONS:
            raw = (row.get(dimension) or "").strip()
            if not raw:
                continue  # a blank is a dimension the grader could not judge
            try:
                score = int(raw)
            except ValueError:
                problems.append(f"line {line}: {dimension} = {raw!r} is not a whole number")
                continue
            if not 0 <= score <= MAX_SCORE:
                problems.append(f"line {line}: {dimension} = {score} is outside 0-{MAX_SCORE}")
                continue
            scores[dimension] = score
        if not scores:
            continue  # an entirely blank row: not graded yet, not an error
        graded.append(
            NoteGradeRecord(
                grade_id=str(uuid.uuid4()),
                note_id=note["note_id"],
                grader=grader,
                batch=key["batch_id"],
                blind_id=blind_id,
                scores=scores,
                comment=(row.get("comment") or "").strip() or None,
            )
        )
    if problems:
        raise GradingError(f"{sheet.name}: " + "; ".join(problems[:10]))
    if not graded:
        raise GradingError(f"{sheet.name} has no filled rows yet.")

    with Session(engine) as session, session.begin():
        existing = session.scalars(
            select(NoteGradeRecord).where(
                NoteGradeRecord.batch == key["batch_id"], NoteGradeRecord.grader == grader
            )
        ).all()
        for record in existing:  # a corrected sheet replaces, never duplicates
            session.delete(record)
        session.flush()
        session.add_all(graded)
    return len(graded)
