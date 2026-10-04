"""Reviewing flags on unlabelled real data, and the adjusted precision that comes out.

The numbers here are the only ones the project can report about real data, so
the tests are mostly about refusing to produce a number that would be wrong:
a guessed verdict, a sample drawn after the fact, a ratio with no interval.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from spendguard.cases import AnomalyType, Case
from spendguard.config import settings
from spendguard.db.store import FlagReviewRecord, get_engine, save_cases
from spendguard.eval.review import (
    CASES_FILE,
    COLUMNS,
    GUIDE_FILE,
    IMPLAUSIBLE,
    KEY_FILE,
    PLAUSIBLE,
    UNCLEAR,
    ReviewError,
    collect,
    export,
    import_reviews,
    load_sample,
    render_markdown,
    sample_flags,
    wilson,
    write_review_report,
)


def _case(detector: str, kind: str, rows: list[int], amount: float) -> Case:
    return Case.build(
        detector=detector, anomaly_type=AnomalyType(kind), row_ids=rows,
        detector_score=0.9, amount_at_risk=amount, vendor_key="acme",
        metadata={"policy_clause": "SG-PP-4.4"},
    )  # fmt: skip


@pytest.fixture
def store(tmp_path: Path) -> Any:
    engine = get_engine(f"sqlite:///{(tmp_path / 'real_cases.sqlite').as_posix()}")
    cases = [_case("d1", "duplicate", [i, i + 100], 1_000.0 * (i + 1)) for i in range(1, 9)]
    cases += [_case("d2", "split", [i, i + 1], 500_000.0) for i in range(20, 24)]
    save_cases(engine, "detect-real", "california_po", cases)
    return engine


def _evidence(ids: list[int]) -> dict[int, dict[str, Any]]:
    return {
        i: {
            "row_id": i,
            "vendor_name": "Acme | Supplies",  # a pipe: would end a Markdown cell early
            "txn_date": "2014-09-24",
            "amount": 1000.0,
            "officer_id": "Transportation, Department of",
            # A real California item description runs to six lines of contract prose.
            "item_desc": "Contractor agrees to provide services\npursuant to Title 42\nof the Code",
            "quantity": 1.0,
            "unit_price": 1000.0,
            "source_row_ref": f"PO-{i // 100}",
        }
        for i in ids
    }


def _export(store: Any, tmp_path: Path, **kw: Any) -> Any:
    options: dict[str, Any] = {
        "per_detector": 3, "seed": 42, "reviewers": ["a", "b"],
        "load_evidence": _evidence, "dataset": "california_po",
    }  # fmt: skip
    return export(store, tmp_path / "batch", **{**options, **kw})


# ------------------------------------------------------------------ the interval


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        (8, 10, 0.4902, 0.9433),
        (10, 10, 0.7225, 1.0),
        (0, 10, 0.0, 0.2775),
        (30, 40, 0.5981, 0.8581),
    ],
)
def test_the_interval_is_wilsons_not_the_textbook_normal_one(
    k: int, n: int, lo: float, hi: float
) -> None:
    """The normal approximation gives 100% +/- 0 for 10 of 10, and bounds outside [0, 1]."""
    got = wilson(k, n)
    assert got is not None
    assert got == pytest.approx((lo, hi), abs=0.0001)
    assert 0.0 <= got[0] <= got[1] <= 1.0


def test_an_interval_over_nothing_is_none_not_zero() -> None:
    assert wilson(0, 0) is None


# ------------------------------------------------------------------ sampling


def test_the_top_strategy_takes_the_flags_an_auditor_would_work_first(store: Any) -> None:
    """The sheet is grouped by detector for steady judging, but the *choice* is by severity."""
    d1 = [c for c in sample_flags(store, per_detector=3, seed=42, strategy="top")
          if c.detector == "d1"]  # fmt: skip
    everything = [c for c in sample_flags(store, per_detector=99, seed=42, strategy="top")
                  if c.detector == "d1"]  # fmt: skip
    assert len(d1) == 3 and len(everything) == 8
    top_three = sorted((c.severity_prelim for c in everything), reverse=True)[:3]
    assert sorted((c.severity_prelim for c in d1), reverse=True) == top_three


def test_the_random_strategy_is_seeded_and_differs_from_the_top_one(store: Any) -> None:
    first = sample_flags(store, per_detector=3, seed=42, strategy="random")
    again = sample_flags(store, per_detector=3, seed=42, strategy="random")
    other = sample_flags(store, per_detector=3, seed=7, strategy="random")
    assert [c.case_id for c in first] == [c.case_id for c in again]
    assert [c.case_id for c in first] != [c.case_id for c in other]


def test_an_unknown_strategy_is_refused_before_anything_is_drawn(store: Any) -> None:
    with pytest.raises(ReviewError, match="unknown strategy"):
        sample_flags(store, per_detector=3, seed=42, strategy="whatever")


def test_there_is_nothing_to_review_before_detection_has_run(tmp_path: Path) -> None:
    empty = get_engine(f"sqlite:///{(tmp_path / 'empty.sqlite').as_posix()}")
    with pytest.raises(ReviewError, match="no cases in this store"):
        sample_flags(empty, per_detector=3, seed=42)


# ------------------------------------------------------------------ export


def test_a_multiline_item_description_cannot_break_the_table(store: Any, tmp_path: Path) -> None:
    """Found on the real data: six lines of contract prose in one cell destroyed the table."""
    batch = _export(store, tmp_path)
    text = (batch.out_dir / CASES_FILE).read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if line.startswith("| ")]
    assert body
    # Every row of every table has the same number of cells as its header.
    for line in body:
        assert line.count("|") == 10, line
    assert "Contractor agrees to provide services pursuant to Title 42" in text  # joined, not cut


def test_a_reviewer_is_shown_the_document_number(store: Any, tmp_path: Path) -> None:
    """On line-item data, two rows of one purchase order are not a duplicate record."""
    batch = _export(store, tmp_path)
    text = (batch.out_dir / CASES_FILE).read_text(encoding="utf-8")
    assert "| document |" in text and "PO-0" in text
    guide = (batch.out_dir / GUIDE_FILE).read_text(encoding="utf-8")
    assert "document" in guide and UNCLEAR in guide


def test_the_sample_is_recorded_before_any_verdict_exists(store: Any, tmp_path: Path) -> None:
    """A sample chosen after seeing the verdicts is not a sample."""
    batch = _export(store, tmp_path)
    key = json.loads((batch.out_dir / KEY_FILE).read_text(encoding="utf-8"))
    assert key["strategy"] == "top" and key["seed"] == 42
    assert {c["case_id"] for c in key["cases"]} == {c.case_id for c in batch.sample}
    for sheet in batch.sheets:
        with sheet.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0]) == list(COLUMNS)
        assert all(r["verdict"] == "" for r in rows)


# ------------------------------------------------------------------ import


def _fill(sheet: Path, verdicts: dict[str, str], comment: str = "") -> Path:
    with sheet.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["case_id"] in verdicts:
            row["verdict"] = verdicts[row["case_id"]]
            row["comment"] = comment
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return sheet


def test_a_verdict_outside_the_vocabulary_is_refused(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    first = batch.sample[0].case_id
    with pytest.raises(ReviewError, match="is not one of"):
        import_reviews(
            store, _fill(batch.sheets[0], {first: "probably"}), load_sample(batch.out_dir), "a"
        )


def test_a_case_from_another_batch_is_refused(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    sheet = _fill(batch.sheets[0], {c.case_id: PLAUSIBLE for c in batch.sample})
    text = sheet.read_text(encoding="utf-8").replace(batch.sample[0].case_id, "not-a-case-id")
    sheet.write_text(text, encoding="utf-8")
    with pytest.raises(ReviewError, match="not in this batch"):
        import_reviews(store, sheet, load_sample(batch.out_dir), "a")


def test_a_corrected_sheet_replaces_that_reviewers_verdicts(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    key = load_sample(batch.out_dir)
    ids = [c.case_id for c in batch.sample]
    import_reviews(store, _fill(batch.sheets[0], dict.fromkeys(ids, IMPLAUSIBLE)), key, "a")
    import_reviews(store, _fill(batch.sheets[0], dict.fromkeys(ids, PLAUSIBLE)), key, "a")

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(store) as session:
        stored = list(session.scalars(select(FlagReviewRecord)))
    assert len(stored) == len(ids)
    assert {r.verdict for r in stored} == {PLAUSIBLE}


def test_an_unfilled_sheet_says_so(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path)
    with pytest.raises(ReviewError, match="no filled rows"):
        import_reviews(store, batch.sheets[0], load_sample(batch.out_dir), "a")


# ------------------------------------------------------------------ the numbers


def test_unclear_verdicts_stay_out_of_the_ratio_and_are_reported_beside_it(
    store: Any, tmp_path: Path
) -> None:
    """A reviewer forced to choose would guess, and a guess lands in the precision figure."""
    batch = _export(store, tmp_path, per_detector=4)
    key = load_sample(batch.out_dir)
    d1 = [c.case_id for c in batch.sample if c.detector == "d1"]
    verdicts = {d1[0]: PLAUSIBLE, d1[1]: PLAUSIBLE, d1[2]: IMPLAUSIBLE, d1[3]: UNCLEAR}
    for sheet, who in zip(batch.sheets, ("a", "b"), strict=True):
        import_reviews(store, _fill(sheet, verdicts, "same order, one PO"), key, who)

    report = collect(store)
    row = next(d for d in report.detectors if d.detector == "d1")
    assert (row.plausible, row.implausible, row.unclear) == (2, 1, 1)
    assert row.reviewed == 4
    assert row.adjusted_precision == pytest.approx(2 / 3)  # the unclear one is excluded
    assert row.flagged_total == 8  # of everything D1 raised, not just the sample
    assert row.interval is not None and row.interval[0] < row.adjusted_precision < row.interval[1]


def test_reviewers_who_disagree_are_recorded_and_a_tie_counts_as_unclear(
    store: Any, tmp_path: Path
) -> None:
    batch = _export(store, tmp_path, per_detector=1)
    key = load_sample(batch.out_dir)
    case = batch.sample[0].case_id
    import_reviews(store, _fill(batch.sheets[0], {case: PLAUSIBLE}), key, "a")
    import_reviews(store, _fill(batch.sheets[1], {case: IMPLAUSIBLE}), key, "b")

    report = collect(store)
    (row,) = [d for d in report.detectors if d.reviewed]
    assert (row.plausible, row.implausible, row.unclear) == (0, 0, 1)
    assert row.adjusted_precision is None  # nothing was judged, so there is no ratio
    assert len(report.disagreements) == 1
    assert report.disagreements[0]["verdicts"] == {"a": PLAUSIBLE, "b": IMPLAUSIBLE}


def test_the_report_never_prints_a_ratio_without_its_interval(store: Any, tmp_path: Path) -> None:
    batch = _export(store, tmp_path, per_detector=3)
    key = load_sample(batch.out_dir)
    import_reviews(
        store, _fill(batch.sheets[0], {c.case_id: PLAUSIBLE for c in batch.sample}), key, "a"
    )
    report = collect(store)
    report.strategy = "top"
    md, js = write_review_report(report, tmp_path / "results", {"Dataset": "california_po"})
    text = md.read_text(encoding="utf-8")

    assert "Adjusted precision" in text and "95% interval" in text
    assert "Nothing in this dataset is labelled" in text
    assert "highest-severity" in text  # the top-strategy caveat is stated
    assert json.loads(js.read_text(encoding="utf-8"))["strategy"] == "top"


def test_a_report_with_nothing_reviewed_says_so_rather_than_printing_zeros(tmp_path: Path) -> None:
    engine = get_engine(f"sqlite:///{(tmp_path / 'empty.sqlite').as_posix()}")
    report = collect(engine)
    assert report.detectors == []
    assert "No flags reviewed yet" in render_markdown(report)


def test_the_overflow_row_has_as_many_cells_as_the_header(store: Any, tmp_path: Path) -> None:
    """A D4 case covers hundreds of rows, so most of them are summarised in one line.

    That line was written before the `document` column existed and was never
    widened, so it rendered as a broken row - and on a vendor case it is the line
    saying "763 more rows", which is exactly the one a reviewer needs to read.
    """
    many = _case("d4", "vendor_flag", list(range(1, 40)), 5_000_000.0)
    save_cases(store, "detect-wide", "california_po", [many])
    batch = _export(store, tmp_path, per_detector=99)

    rendered = (batch.out_dir / CASES_FILE).read_text(encoding="utf-8").splitlines()
    body = [line for line in rendered if line.startswith("| ")]
    assert body
    assert {line.count("|") for line in body} == {10}, "every row matches the header"

    overflow = [line for line in body if "more row" in line]
    assert overflow, "the hidden rows are summarised"
    assert "more rows in this case" in overflow[0]


def test_one_hidden_row_is_not_described_as_rows(store: Any, tmp_path: Path) -> None:
    rows = list(range(1, settings.review_max_rows + 2))  # exactly one over the limit
    save_cases(store, "detect-one-over", "california_po", [_case("d4", "vendor_flag", rows, 1.0)])
    batch = _export(store, tmp_path, per_detector=99)

    text = (batch.out_dir / CASES_FILE).read_text(encoding="utf-8")
    assert "1 more row in this case" in text
    assert "1 more rows" not in text
