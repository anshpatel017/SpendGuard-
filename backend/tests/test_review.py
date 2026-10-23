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


# ------------------------------------------------------- what a vendor flag shows


def _vendor_case(rows: list[int], indicators: dict[str, Any], **extra: Any) -> Case:
    """A D4-shaped case: the metadata the vendor detector actually writes."""
    return Case.build(
        detector="d4", anomaly_type=AnomalyType.VENDOR_FLAG, row_ids=rows,
        detector_score=0.9, amount_at_risk=9_000_000.0, vendor_key="acme",
        metadata={
            "policy_clauses": ["SG-PP-5.5", "SG-PP-7.1"],
            "vendor_name": "Acme Fuel",
            "transactions": len(rows),
            "combined_p_value": "1.2e-09",
            "first_seen": "2013-01-07",
            "officers": [f"Department {n}" for n in range(9)],
            "indicators": indicators,
            **extra,
        },
    )  # fmt: skip


ALL_ROWS = list(range(1, 41))
ROUND_ROWS = {31, 33, 35}  # amounts divisible by the round-number unit
PERIOD_END_ROWS = {37, 38}  # dated in the last four days of a month
EARLY_ROWS = {39, 40}  # inside the new-vendor window, and large


def _vendor_evidence(ids: list[int]) -> dict[int, dict[str, Any]]:
    """Rows where every interesting one sits past the cut-off a naive slice takes.

    Row ids 1-30 are small and ordinary; the rows carrying the flagged behaviour
    are 31-40, so anything that shows `row_ids[:12]` shows a reviewer none of it.
    """
    rows = {}
    for i in ids:
        amount, txn_date = 100.0 + i, "2014-06-15"
        if i in ROUND_ROWS:
            amount = 1_000.0 * i
        if i in PERIOD_END_ROWS:
            amount, txn_date = 2_000_000.0 + i, "2014-06-29"
        if i in EARLY_ROWS:
            amount, txn_date = 5_000_000.0 + i, "2013-02-11"  # inside new_vendor_days
        rows[i] = {
            "row_id": i, "vendor_name": "Acme Fuel", "txn_date": txn_date,
            "amount": amount, "officer_id": "Transportation, Department of",
            "item_desc": "diesel", "quantity": 1.0, "unit_price": amount,
            "source_row_ref": f"PO-{i}",
        }  # fmt: skip
    return rows


ROUND_TEST = {
    "p_value": "1.29e-12", "unit": 1000.0, "observed_rate": 0.106,
    "expected_rate": 0.0419, "risk_ratio": 2.53, "observations": 680,
}  # fmt: skip
PERIOD_TEST = {
    "p_value": "1.05e-18", "definition": "last four days of a month, or March",
    "observed_rate": 0.645, "expected_rate": 0.2179, "risk_ratio": 2.96,
    "observations": 93,
}  # fmt: skip
DIGIT_TEST = {
    "p_value": "4.92e-24", "chi_square": 128.84, "distinct_amounts": 680,
    "observed_share": [0.21, 0.169, 0.288, 0.131, 0.063, 0.057, 0.04, 0.021, 0.021],
    "peer_share": [0.292, 0.197, 0.151, 0.095, 0.071, 0.061, 0.049, 0.042, 0.041],
}  # fmt: skip


def _block(text: str, case: Case) -> str:
    """One case's section of the sheet, so a sibling case cannot satisfy an assertion."""
    marker = f"## {case.case_id[:8]}"
    assert marker in text, f"{marker} is not in the sheet"
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def _row_table(block: str) -> list[str]:
    """The evidence table: header, rule and rows, stopping at the end of the table."""
    lines = block.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| row |"))
    table = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        table.append(line)
    return table


def _row_ids(block: str) -> set[int]:
    return {
        int(cell)
        for line in _row_table(block)[2:]
        if (cell := line.split("|")[1].strip()).isdigit()
    }


def _vendor_block(store: Any, tmp_path: Path, case: Case) -> str:
    save_cases(store, "detect-vendor", "california_po", [case])
    batch = _export(store, tmp_path, per_detector=99, load_evidence=_vendor_evidence)
    return _block((batch.out_dir / CASES_FILE).read_text(encoding="utf-8"), case)


def test_a_vendor_flag_carries_the_test_that_produced_it(store: Any, tmp_path: Path) -> None:
    """The claim is a rate measured against peers, and the sheet has to state it.

    Without it a reviewer sees a p-value and twelve rows out of hundreds, and the
    only honest verdict is `unclear` - which is not a measurement of anything.
    """
    block = _vendor_block(store, tmp_path, _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST}))
    assert "round numbers" in block
    assert "10.6%" in block, "the supplier's own rate"
    assert "4.2%" in block, "the rate expected for what it sells"
    assert "2.53x" in block
    assert "1.29e-12" in block


def test_the_leading_digit_comparison_is_not_dropped_on_the_way_to_the_sheet(
    store: Any, tmp_path: Path
) -> None:
    """It lives in a nested dict, and the export used to discard those wholesale."""
    block = _vendor_block(store, tmp_path, _vendor_case(ALL_ROWS, {"first_digit": DIGIT_TEST}))
    assert "28.8%" in block, "the supplier's share of leading 3s"
    assert "15.1%" in block, "its peers' share, which is the comparison"
    assert "128.84" in block


def test_an_indicator_nobody_has_written_a_renderer_for_is_printed_not_skipped(
    store: Any, tmp_path: Path
) -> None:
    """Silently dropping an unrecognised shape is the defect being fixed here.

    A fifth vendor test added later must not vanish from the sheet merely because
    this module has not been taught what it looks like.
    """
    unknown = {"weekend_orders": {"p_value": "0.004", "seen": 19}}
    block = _vendor_block(store, tmp_path, _vendor_case(ALL_ROWS, unknown))
    assert "weekend orders" in block
    assert "0.004" in block
    assert "19" in block


def test_the_rows_under_a_vendor_flag_show_the_behaviour_that_was_flagged(
    store: Any, tmp_path: Path
) -> None:
    """Twelve arbitrary rows of a supplier's history are evidence for nothing.

    Every row carrying the flagged habit here sits past the first twelve by row
    id, so a naive slice puts none of it in front of the reviewer.
    """
    case = _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST, "period_end": PERIOD_TEST})
    block = _vendor_block(store, tmp_path, case)
    shown = _row_ids(block)
    assert ROUND_ROWS & shown, "a round-amount row is in front of the reviewer"
    assert PERIOD_END_ROWS & shown, "a period-end row is too"
    assert "round multiple of 1,000" in block
    assert "period end" in block


def test_a_supplier_flagged_as_a_new_vendor_shows_its_opening_orders(
    store: Any, tmp_path: Path
) -> None:
    """The flag is about what it billed just after appearing, so show those rows.

    Two of the fifteen vendor flags screened on 2026-10-23 were `unclear` for the
    lack of them: flagged for taking large orders as a new supplier, with not one
    row near `first_seen` among the twelve shown.
    """
    case = _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST}, new_vendor_high_value=True)
    block = _vendor_block(store, tmp_path, case)
    assert f"largest in the first {settings.new_vendor_days} days" in block
    assert EARLY_ROWS & _row_ids(block), "an order from the opening window is visible"


def test_no_single_test_is_allowed_to_spend_the_whole_row_budget(
    store: Any, tmp_path: Path
) -> None:
    """A supplier flagged on three tests needs rows for all three, not twelve for one."""
    case = _vendor_case(
        ALL_ROWS,
        {"round_numbers": ROUND_TEST, "period_end": PERIOD_TEST},
        new_vendor_high_value=True,
    )
    block = _vendor_block(store, tmp_path, case)
    reasons = {line.split("|")[-2].strip() for line in _row_table(block)[2:]}
    assert "period end" in reasons
    assert "round multiple of 1,000" in reasons
    assert f"largest in the first {settings.new_vendor_days} days" in reasons


def test_every_chosen_row_says_which_test_put_it_there(store: Any, tmp_path: Path) -> None:
    """A chosen sample without its reasons is only a different arbitrary slice."""
    case = _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST, "period_end": PERIOD_TEST})
    table = _row_table(_vendor_block(store, tmp_path, case))
    assert "why shown" in table[0]
    assert {line.count("|") for line in table} == {11}, "every row matches the header"


def test_a_row_is_never_shown_twice_to_pad_the_sample(store: Any, tmp_path: Path) -> None:
    """Rows 31-35 qualify on two tests at once; the sample must not repeat them."""
    case = _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST, "period_end": PERIOD_TEST})
    rows = _row_table(_vendor_block(store, tmp_path, case))[2:]
    ids = [cell for line in rows if (cell := line.split("|")[1].strip()).isdigit()]
    assert len(ids) == len(set(ids))
    assert len(ids) == settings.review_max_rows


def test_the_count_behind_a_rate_says_what_it_counted(store: Any, tmp_path: Path) -> None:
    """`n = 680` beside a supplier with 93 transactions reads as a contradiction.

    The round-number test runs over distinct amounts - billing one round figure
    fifty times is one habit, not fifty - and the period-end test over every
    transaction. Saying which is the difference between a figure a reviewer can
    use and one that makes them distrust the sheet.
    """
    case = _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST, "period_end": PERIOD_TEST})
    block = _vendor_block(store, tmp_path, case)
    assert "680 distinct amounts" in block
    assert "93 transactions" in block


def test_the_departments_a_flagged_supplier_billed_reach_the_sheet(
    store: Any, tmp_path: Path
) -> None:
    """A supplier selling to nine departments is part of what the flag is about.

    `officers` is a list, and lists went out of the sheet along with the dicts.
    """
    block = _vendor_block(store, tmp_path, _vendor_case(ALL_ROWS, {"round_numbers": ROUND_TEST}))
    assert "`officers` (9)" in block
    assert "Department 0" in block
    assert "(+3 more)" in block, "a long list is truncated, not dumped"


def test_a_flag_with_no_indicators_still_shows_its_own_rows_in_order(
    store: Any, tmp_path: Path
) -> None:
    """D1 and D2 cases *are* their rows; nothing about them needs choosing.

    Choosing rows is for vendor flags alone, so a case without indicators must
    come out of the export in the order the case itself holds - unsorted by
    amount, unlabelled, exactly as before.
    """
    case = _case("d1", "duplicate", [7, 3, 9], 50_000.0)
    save_cases(store, "detect-plain", "california_po", [case])
    batch = _export(store, tmp_path, per_detector=99)
    block = _block((batch.out_dir / CASES_FILE).read_text(encoding="utf-8"), case)

    assert "why shown" not in block
    ids = [line.split("|")[1].strip() for line in _row_table(block)[2:]]
    assert ids == [str(r) for r in case.row_ids], "the case's own order, untouched"


def test_the_guide_tells_a_reviewer_what_a_vendor_flag_even_claims(
    store: Any, tmp_path: Path
) -> None:
    """The rules were written for duplicates. A statistical flag is judged differently.

    It also has to name the innocent explanations, because a reviewer who does not
    know that fuel is sold at round figures cannot weigh the round-number test.
    """
    batch = _export(store, tmp_path)
    guide = (batch.out_dir / GUIDE_FILE).read_text(encoding="utf-8")
    assert "Vendor flags are about a supplier, not about the rows" in guide
    assert "why shown" in guide
    assert "re-derive" in guide, "a reviewer is told not to recompute the statistic"


def test_a_detectors_internal_matching_state_is_not_shown_to_a_reviewer(
    store: Any, tmp_path: Path
) -> None:
    """Plain lists are evidence; lists of dicts are the detector talking to itself.

    D1 records `pairs`, its own per-pair scoring state. Printing a truncated Python
    repr of that above the rows tells a reviewer nothing and costs them attention.
    """
    case = Case.build(
        detector="d1", anomaly_type=AnomalyType.DUPLICATE, row_ids=[4, 5],
        detector_score=0.9, amount_at_risk=1_000.0, vendor_key="acme",
        metadata={
            "stages": ["probabilistic"],
            "pairs": [{"row_ids": [4, 5], "stage": "probabilistic"}],
        },
    )  # fmt: skip
    save_cases(store, "detect-pairs", "california_po", [case])
    batch = _export(store, tmp_path, per_detector=99)
    block = _block((batch.out_dir / CASES_FILE).read_text(encoding="utf-8"), case)

    assert "`stages` (1): probabilistic" in block, "how the match was made is useful"
    assert "pairs" not in block
    assert "row_ids" not in block


def test_a_leading_digit_flag_shows_rows_carrying_that_digit(store: Any, tmp_path: Path) -> None:
    """ "The twelve largest" illustrates a distribution claim not at all.

    `5497f8b8` in the California sample was flagged because 51.5% of its amounts
    start with 3 against 16.9% for its peers - and not one of the twelve rows the
    sheet showed started with a 3.
    """
    case = _vendor_case(ALL_ROWS, {"first_digit": DIGIT_TEST})
    block = _vendor_block(store, tmp_path, case)

    assert "amount starts with 3" in block
    amounts = [float(line.split("|")[5]) for line in _row_table(block)[2:-1]]
    assert any(str(int(a))[0] == "3" for a in amounts), "the over-used digit is visible"


def test_the_digit_singled_out_is_the_one_furthest_above_its_peers() -> None:
    """Not the most common digit - the most *unexpected* one.

    Leading 1s are the plurality for almost every supplier, so picking the biggest
    observed share would point at 1 nearly every time and say nothing.
    """
    from spendguard.eval.review import _most_over_represented_digit

    # 1 is still this supplier's commonest digit; 7 is the one out of line.
    skewed = {
        "observed_share": [0.40, 0.10, 0.08, 0.07, 0.06, 0.05, 0.18, 0.03, 0.03],
        "peer_share": [0.42, 0.18, 0.13, 0.10, 0.07, 0.04, 0.02, 0.02, 0.02],
    }
    chosen = _most_over_represented_digit(skewed)
    assert chosen is not None
    assert chosen[0] == 7
    assert chosen[1] == pytest.approx(0.16)


def test_a_supplier_that_bills_like_its_peers_has_no_digit_worth_pointing_at() -> None:
    """Every digit is at or below its peers, so the sheet must not invent a reason."""
    from spendguard.eval.review import _most_over_represented_digit

    flat = {"observed_share": [0.1] * 9, "peer_share": [0.2] * 9}
    assert _most_over_represented_digit(flat) is None
    assert _most_over_represented_digit({"p_value": "0.4"}) is None, "no shares recorded"
    assert _most_over_represented_digit(None) is None


def test_the_leading_digit_here_is_the_one_the_detector_computed() -> None:
    """A label disagreeing with the test that raised the flag is worse than none.

    The detector works on a numpy array of a whole supplier's amounts; the export
    needs one value at a time. They have to agree on every float, not most.
    """
    import numpy as np

    from spendguard.detectors.d4_vendor import first_digits
    from spendguard.eval.review import _leading_digit

    values = np.concatenate(
        [
            np.random.default_rng(0).uniform(0.01, 1e9, 5_000),
            np.array([1.0, 9.999, 10.0, 99.999, 100.0, 999_999.0, 1e9, 0.001]),
        ]
    )
    assert [_leading_digit(v) for v in values] == list(first_digits(values))
    assert _leading_digit(0) is None, "a zero amount has no leading digit"
    assert _leading_digit(-5) is None
    assert _leading_digit("not a number") is None
