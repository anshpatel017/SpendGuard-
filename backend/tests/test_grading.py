"""The blinded grading kit: what a grader is shown, what they are not, and what is stored.

The point of the kit is that a grader cannot tell which system wrote a note, so
the sharpest test here is the one that reads every exported file and fails if
anything in it identifies an arm.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from spendguard.db.store import (
    AuditNoteRecord,
    NoteGradeRecord,
    get_engine,
    save_cases,
    save_investigation,
)
from spendguard.eval.grading import (
    COLUMNS,
    DIMENSIONS,
    KEY_FILE,
    NOTES_FILE,
    RUBRIC,
    RUBRIC_FILE,
    GradingError,
    export,
    import_grades,
    load_key,
    sample_notes,
)
from spendguard.eval.grading_report import collect, render_markdown, write_grading_report

from .conftest import build_db
from .test_api import NOTE, _case, _result

ARMS = ("agent", "template", "no-verifier")


@pytest.fixture
def store(tmp_path: Path) -> Any:
    """A store with the same cases investigated by each arm - what a real batch draws from."""
    con = build_db(tmp_path / "t.duckdb", [{"amount": 87450.0 + i} for i in range(6)])
    engine = get_engine(f"sqlite:///{(tmp_path / 'investigation_seed42.sqlite').as_posix()}")
    cases = [
        _case([1, 2], "duplicate", 87_450.0),
        _case([3, 4], "split", 3_60_000.0),
        _case([5], "inflation", 9_000.0),
    ]
    save_cases(engine, "detect-1", "injected_seed42", cases)
    for arm in ARMS:
        for case in cases:
            result = _result(case, NOTE, con, "verified")
            result.model = "scripted" if arm == "agent" else arm
            save_investigation(
                engine, f"run-{arm}", result, ablation_name=None if arm == "agent" else arm
            )
    con.close()
    return engine


def _evidence(tmp_path: Path) -> Any:
    rows = {
        i: {"row_id": i, "vendor_name": "Sharma Traders", "txn_date": "2025-04-01",
            "amount": 87450.0, "invoice_no": f"INV-{i}", "item_desc": "Chair",
            "quantity": 10.0, "unit_price": 8745.0}
        for i in range(1, 40)
    }  # fmt: skip
    return lambda ids: {i: rows[i] for i in ids if i in rows}


def _export(
    store: Any, tmp_path: Path, size: int = 9, graders: tuple[str, ...] = ("a", "b")
) -> Any:
    return export(
        store, tmp_path / "batch", seed=42, size=size,
        graders=graders, load_evidence=_evidence(tmp_path),
    )  # fmt: skip


# ------------------------------------------------------------------ sampling


def test_the_sample_is_spread_over_the_arms_not_taken_from_whichever_has_most(store: Any) -> None:
    """Comparing 30 agent notes against 3 template ones would compare sample sizes."""
    blinded = sample_notes(store, size=6, seed=42)
    counts = {arm: sum(1 for b in blinded if b.arm == arm) for arm in ARMS}
    assert counts == {"agent": 2, "template": 2, "no-verifier": 2}


def test_the_same_seed_draws_the_same_sample_in_the_same_order(store: Any) -> None:
    first = sample_notes(store, size=6, seed=42)
    assert [(b.blind_id, b.note_id) for b in first] == [
        (b.blind_id, b.note_id) for b in sample_notes(store, size=6, seed=42)
    ]
    assert [b.note_id for b in first] != [b.note_id for b in sample_notes(store, size=6, seed=7)]


def test_a_batch_cannot_be_exported_before_anything_has_been_investigated(tmp_path: Path) -> None:
    empty = get_engine(f"sqlite:///{(tmp_path / 'empty.sqlite').as_posix()}")
    with pytest.raises(GradingError, match="no notes to grade"):
        export(empty, tmp_path / "b", seed=42, size=5, graders=["a"], load_evidence=lambda i: {})


# ------------------------------------------------------------------ blinding


def test_nothing_a_grader_receives_says_which_system_wrote_a_note(
    store: Any, tmp_path: Path
) -> None:
    """The kit's whole purpose. If this passes for the wrong reason, the scores are worthless."""
    batch = _export(store, tmp_path)
    given_to_graders = [batch.out_dir / NOTES_FILE, batch.out_dir / RUBRIC_FILE, *batch.sheets]

    tells = ["template", "no-verifier", "ablation", "scripted", "verified", "unverified"]
    for path in given_to_graders:
        text = path.read_text(encoding="utf-8").lower()
        found = [t for t in tells if t in text]
        assert not found, f"{path.name} leaks {found}"
    # The note ids and case ids are tells too: they join straight back to the store.
    notes = (batch.out_dir / NOTES_FILE).read_text(encoding="utf-8")
    for b in batch.blinded:
        assert b.note_id not in notes and b.case_id not in notes
        assert b.blind_id in notes


def test_the_key_stays_out_of_the_graders_files_but_maps_every_note_back(
    store: Any, tmp_path: Path
) -> None:
    batch = _export(store, tmp_path)
    key = json.loads((batch.out_dir / KEY_FILE).read_text(encoding="utf-8"))
    assert {n["blind_id"] for n in key["notes"]} == {b.blind_id for b in batch.blinded}
    assert {n["arm"] for n in key["notes"]} == set(ARMS)
    assert (batch.out_dir / KEY_FILE) not in batch.sheets


def test_every_grader_gets_the_same_notes_in_their_own_order(store: Any, tmp_path: Path) -> None:
    """Shared ids so the sheets can be joined; different order so fatigue does not line up."""
    batch = _export(store, tmp_path, graders=("a", "b"))
    orders = []
    for sheet in batch.sheets:
        with sheet.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0]) == list(COLUMNS)
        assert all(r[d] == "" for r in rows for d in DIMENSIONS)  # empty, to be filled
        orders.append([r["blind_id"] for r in rows])
    assert set(orders[0]) == set(orders[1]) and orders[0] != orders[1]


def test_a_grader_is_shown_the_rows_a_note_cites(store: Any, tmp_path: Path) -> None:
    """Without the evidence they can only grade fluency, which is what a model fakes best."""
    batch = _export(store, tmp_path)
    notes = (batch.out_dir / NOTES_FILE).read_text(encoding="utf-8")
    assert "| row_id | vendor |" in notes
    assert "Sharma Traders" in notes
    assert all(d.title in (batch.out_dir / RUBRIC_FILE).read_text(encoding="utf-8") for d in RUBRIC)


# ------------------------------------------------------------------ import


def _fill(sheet: Path, scores: dict[str, list[int]], comment: str = "") -> Path:
    with sheet.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        values = scores.get(row["blind_id"])
        if values is None:
            continue
        for dimension, value in zip(DIMENSIONS, values, strict=True):
            row[dimension] = str(value)
        row["comment"] = comment
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return sheet


def test_a_filled_sheet_is_stored_against_the_notes_it_graded(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    ids = [b.blind_id for b in batch.blinded]
    stored = import_grades(
        store,
        _fill(batch.sheets[0], {i: [2, 2, 1, 2, 1] for i in ids}, "solid"),
        load_key(batch.out_dir),
        "a",
    )
    assert stored == len(ids)

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(store) as session:
        grades = list(session.scalars(select(NoteGradeRecord)))
        notes = {n.note_id for n in session.scalars(select(AuditNoteRecord))}
    assert {g.note_id for g in grades} <= notes
    assert all(g.scores["alternative_considered"] == 1 and g.comment == "solid" for g in grades)


def test_a_corrected_sheet_replaces_that_graders_grades_rather_than_doubling_them(
    store: Any, tmp_path: Path
) -> None:
    batch = _export(store, tmp_path)
    key = load_key(batch.out_dir)
    ids = [b.blind_id for b in batch.blinded]
    import_grades(store, _fill(batch.sheets[0], {i: [0, 0, 0, 0, 0] for i in ids}), key, "a")
    import_grades(store, _fill(batch.sheets[0], {i: [2, 2, 2, 2, 2] for i in ids}), key, "a")

    report = collect(store)
    assert sum(a.grades for a in report.arms) == len(ids)  # not twice
    assert all(a.total == 10.0 for a in report.arms)


def test_a_score_off_the_scale_is_refused_rather_than_rounded(store: Any, tmp_path: Path) -> None:
    """A typo in a grade becomes a wrong number in the report, and the report is the deliverable."""
    batch = _export(store, tmp_path)
    ids = [b.blind_id for b in batch.blinded]
    with pytest.raises(GradingError, match="outside 0-2"):
        import_grades(
            store, _fill(batch.sheets[0], {ids[0]: [2, 2, 5, 2, 1]}), load_key(batch.out_dir), "a"
        )


def test_a_blind_id_from_another_batch_is_refused(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    sheet = _fill(batch.sheets[0], {b.blind_id: [1, 1, 1, 1, 1] for b in batch.blinded})
    text = sheet.read_text(encoding="utf-8").replace("N-001", "N-999")
    sheet.write_text(text, encoding="utf-8")
    with pytest.raises(GradingError, match="not in this batch"):
        import_grades(store, sheet, load_key(batch.out_dir), "a")


def test_an_unfilled_sheet_says_so_instead_of_reporting_nothing(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    with pytest.raises(GradingError, match="no filled rows"):
        import_grades(store, batch.sheets[0], load_key(batch.out_dir), "a")


def test_a_dimension_left_blank_is_kept_as_not_judged(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    first = batch.blinded[0].blind_id
    sheet = _fill(batch.sheets[0], {b.blind_id: [1, 1, 1, 1, 1] for b in batch.blinded})
    rows = sheet.read_text(encoding="utf-8").splitlines()
    rows = [r.replace(f"{first},1,1,1,1,1", f"{first},1,,1,1,1") for r in rows]
    sheet.write_text("\n".join(rows) + "\n", encoding="utf-8")
    import_grades(store, sheet, load_key(batch.out_dir), "a")

    report = collect(store)
    assert report.agreement[1].units == 0  # evidence_sufficiency: one grader, one blank


# ------------------------------------------------------------------ the report


def test_the_report_puts_agreement_beside_every_score(store: Any, tmp_path: Path) -> None:
    """A mean of graders who do not agree is a number with no content."""
    batch = _export(store, tmp_path, graders=("a", "b"))
    key = load_key(batch.out_dir)
    by_arm = {b.blind_id: b.arm for b in batch.blinded}
    # The template arm scores 0 on the innocent explanation, by construction.
    good = [2, 2, 2, 2, 2]
    poor = [2, 2, 0, 1, 1]
    scores = {i: (poor if by_arm[i] == "template" else good) for i in by_arm}
    for sheet, grader in zip(batch.sheets, ("a", "b"), strict=True):
        import_grades(store, _fill(sheet, scores), key, grader)

    report = collect(store)
    arms = {a.arm: a for a in report.arms}
    assert arms["template"].per_dimension["alternative_considered"] == 0.0
    assert arms["agent"].per_dimension["alternative_considered"] == 2.0
    assert arms["agent"].total > arms["template"].total
    assert report.overall_alpha == 1.0  # the two graders agreed exactly
    assert report.graders == ["a", "b"]

    md, js = write_grading_report(report, tmp_path / "results")
    text = md.read_text(encoding="utf-8")
    assert "Inter-grader agreement" in text and "alpha = 1.000" in text
    assert "Blinding is imperfect" in text  # the limitation is stated, not found later
    assert json.loads(js.read_text(encoding="utf-8"))["overall_alpha"] == 1.0


def test_a_report_with_no_grades_says_so_rather_than_printing_zeros(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{(tmp_path / 'empty.sqlite').as_posix()}")
    report = collect(engine)
    assert report.arms == [] and report.overall_alpha is None
    assert "No grades imported yet" in render_markdown(report)
