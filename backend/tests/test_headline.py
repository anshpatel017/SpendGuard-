"""The headline sentence: generated, sourced, and honest about what is missing.

This sentence gets copied into the report, the slides and the viva. It is the
most quoted figure in the project and so the most likely to be repeated from a
run that has since been redone. The tests are about the two ways it could
mislead: quoting a rate from a sample too small to support one, and implying the
detection figures came from real transactions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spendguard.config import settings
from spendguard.eval.headline import UNMEASURED, build, render_markdown, write_headline


def _write(results: Path, name: str, payload: dict[str, Any]) -> None:
    results.mkdir(parents=True, exist_ok=True)
    (results / name).write_text(json.dumps(payload), encoding="utf-8")


def _detection(results: Path) -> None:
    _write(
        results,
        "detection.json",
        {
            "seeds": [42, 7, 2026],
            "runs": [
                {"seed": 42, "transactions": 50907, "ground_truth_groups": {"duplicate": 508}}
            ],
            "aggregate": [
                {
                    "anomaly_type": "all",
                    "detector": "spendguard",
                    "granularity": "case",
                    "f1": {"mean": 0.689, "sd": 0.006},
                },
                {
                    "anomaly_type": "all",
                    "detector": "baseline",
                    "granularity": "case",
                    "f1": {"mean": 0.205, "sd": 0.007},
                },
            ],
        },
    )


def _agent(results: Path, notes: int, validity: float = 1.0) -> None:
    _write(
        results,
        "agent.json",
        {
            "results": [
                {
                    "seed": 42,
                    "arm": "agent",
                    "notes": notes,
                    "citations_checked": notes * 5,
                    "deterministic_valid": validity,
                }
            ]
        },
    )


def test_the_detection_figures_are_never_called_real_transactions(tmp_path: Path) -> None:
    """Injection runs on synthetic data; the real dataset is never injected into.

    One sentence covering both would read as though the F1 had been achieved on
    real procurement, which is the single most misleading thing this project
    could say.
    """
    _detection(tmp_path / "results")
    headline = build(tmp_path / "results")
    assert "synthetic" in headline.detection
    assert "real transactions" not in headline.detection
    assert "0.689 ± 0.006" in headline.detection and "0.205 ± 0.007" in headline.detection


def test_a_rate_is_not_quoted_from_a_sample_too_small_to_support_one(tmp_path: Path) -> None:
    """100% from three notes is the kind of number a panel is right to attack."""
    results = tmp_path / "results"
    _detection(results)
    _agent(results, notes=3)
    headline = build(results)

    assert "provisional" in headline.agent
    assert "only 3 note(s)" in headline.agent
    assert str(settings.headline_min_notes) in headline.agent


def test_a_large_enough_sample_is_quoted_plainly(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _detection(results)
    _agent(results, notes=settings.headline_min_notes, validity=0.97)
    headline = build(results)

    assert "provisional" not in headline.agent
    assert "97.0%" in headline.agent
    assert "no model involved" in headline.agent  # the rule-checked number, labelled as such


def test_citation_validity_is_weighted_by_citations_not_by_run(tmp_path: Path) -> None:
    """A run of two notes must not count as much as a run of forty."""
    results = tmp_path / "results"
    _detection(results)
    _write(
        results,
        "agent.json",
        {
            "results": [
                {"seed": 42, "arm": "agent", "notes": 2, "citations_checked": 10,
                 "deterministic_valid": 0.5},
                {"seed": 7, "arm": "agent", "notes": 30, "citations_checked": 90,
                 "deterministic_valid": 1.0},
            ]
        },
    )  # fmt: skip
    headline = build(results)
    # (0.5*10 + 1.0*90) / 100 = 0.95, not the unweighted mean of 0.75.
    assert "95.0%" in headline.agent


def test_an_ablation_arm_never_enters_the_headline(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _detection(results)
    _write(
        results,
        "agent.json",
        {
            "results": [
                {"seed": 42, "arm": "template", "notes": 40, "citations_checked": 200,
                 "deterministic_valid": 1.0}
            ]
        },
    )  # fmt: skip
    headline = build(results)
    assert UNMEASURED in headline.agent  # the template arm is not the agent


def test_a_figure_that_does_not_exist_yet_says_so(tmp_path: Path) -> None:
    """It must never leave a gap for someone to fill in from memory."""
    _detection(tmp_path / "results")
    headline = build(tmp_path / "results")

    assert not headline.complete
    assert UNMEASURED in headline.agent and UNMEASURED in headline.real_data
    assert "spendguard review report" in headline.real_data  # and says how to get it


def test_with_nothing_generated_at_all_it_still_refuses_to_invent(tmp_path: Path) -> None:
    headline = build(tmp_path / "nothing")
    assert not headline.complete
    assert all(not f.measured for f in headline.figures)
    assert UNMEASURED in headline.sentence()


def test_every_figure_carries_the_file_it_came_from(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _detection(results)
    _agent(results, notes=25)
    headline = build(results)

    assert headline.figures
    assert all(f.source for f in headline.figures)
    text = render_markdown(headline)
    assert "Where each figure comes from" in text
    assert "detection.json" in text and "agent.json" in text
    assert "Do not edit this sentence by hand" in text


def test_the_written_file_records_whether_it_is_complete(tmp_path: Path) -> None:
    _detection(tmp_path / "results")
    headline = build(tmp_path / "results")
    md, js = write_headline(headline, tmp_path / "out")

    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["sentence"] == headline.sentence()
    assert "Incomplete" in md.read_text(encoding="utf-8")


def test_the_committed_headline_matches_the_committed_results() -> None:
    """The real one: docs/results/headline.json against what build() produces now."""
    committed = settings.results_dir / "headline.json"
    if not committed.exists():
        pytest.skip("no headline generated yet")
    payload = json.loads(committed.read_text(encoding="utf-8"))
    assert payload["sentence"] == build().sentence(), (
        "docs/results/headline.md is stale - run `spendguard report headline`"
    )
