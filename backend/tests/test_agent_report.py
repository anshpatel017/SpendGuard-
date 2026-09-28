"""Aggregating agent results across seeds, models and arms.

The table this produces is the one the report quotes, and it is assembled from
stores that fill up a few notes a day. So the tests are about what must never
happen to it: two models merged into one row, an arm's notes counted as the
agent's, a stale run's triage attached to a newer arm, or a rate printed as if
the sample were complete.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from spendguard.db.store import get_engine, record_run, save_cases, save_investigation
from spendguard.eval.agent_report import (
    MAIN_ARM,
    agent_report,
    collect_seed,
    render_markdown,
    write_agent_report,
)

from .conftest import build_db
from .test_api import NOTE, _case, _result


def _now(minute: int = 0) -> datetime:
    return datetime(2026, 9, 28, 10, minute)


@pytest.fixture
def seed_store(tmp_path: Path) -> Any:
    """One seed's store: two models on the main arm, plus the template arm."""
    con = build_db(tmp_path / "t.duckdb", [{"amount": 87450.0 + i} for i in range(6)])
    engine = get_engine(f"sqlite:///{(tmp_path / 'investigation_seed42.sqlite').as_posix()}")
    cases = [_case([1, 2], "duplicate", 87_450.0), _case([3, 4], "split", 3_60_000.0)]
    save_cases(engine, "detect-1", "injected_seed42", cases)

    def run(model: str, arm: str | None, minute: int, triage: float, sampled: int = 4) -> None:
        for case in cases:
            result = _result(case, NOTE, con, "verified")
            result.model = model
            save_investigation(engine, f"run-{model}-{arm}", result, ablation_name=arm)
        record_run(
            engine, f"run-{model}-{arm}", "investigate", "injected_seed42",
            {"seed": 42, "per_type": 2, "model": model, "ablation": arm},
            {"sampled": sampled, "quota_stopped": False,
             "triage": {"all": {"cases": 4, "decisive_accuracy": triage, "real_kept": 1.0,
                                "spurious_filtered": 0.5}},
             "verification": {"first_draft_deterministic_valid": 0.9}},
            started_at=_now(minute),
        )  # fmt: skip

    run("qwen/qwen3.8-27b", None, 0, 0.75)
    run("gemini-3.8-flash", None, 10, 0.80)
    run("template", "template", 20, 0.50)
    con.close()
    return engine


def _by(results: list[Any], model: str, arm: str) -> Any:
    return next(r for r in results if r.model == model and r.arm == arm)


def test_two_models_are_never_merged_into_one_row(seed_store: Any) -> None:
    """D-33: Groq and Gemini share the store but never one number."""
    results = collect_seed(seed_store, 42)
    agents = [r for r in results if r.arm == MAIN_ARM]
    assert sorted(r.model for r in agents) == ["gemini-3.8-flash", "qwen/qwen3.8-27b"]
    assert _by(results, "gemini-3.8-flash", MAIN_ARM).triage_accuracy == 0.80
    assert _by(results, "qwen/qwen3.8-27b", MAIN_ARM).triage_accuracy == 0.75


def test_an_arms_notes_are_never_counted_as_the_agents(seed_store: Any) -> None:
    """D-35: an arm sits beside the main run, never inside it."""
    results = collect_seed(seed_store, 42)
    arms = {r.arm for r in results}
    assert arms == {MAIN_ARM, "template"}
    assert all(r.notes == 2 for r in results)  # each arm sees its own two notes, not six


def test_each_arm_gets_the_triage_of_its_own_newest_run(seed_store: Any) -> None:
    results = collect_seed(seed_store, 42)
    assert _by(results, "template", "template").triage_accuracy == 0.50
    assert _by(results, "template", "template").sampled == 4


def test_a_case_investigated_twice_counts_once(seed_store: Any, tmp_path: Path) -> None:
    """The newest note is the one that stands; a revision is not a second note."""
    before = _by(collect_seed(seed_store, 42), "gemini-3.8-flash", MAIN_ARM).notes
    con = build_db(tmp_path / "again.duckdb", [{"amount": 87450.0 + i} for i in range(6)])
    case = _case([1, 2], "duplicate", 87_450.0)
    result = _result(case, NOTE, con, "verified")
    result.model = "gemini-3.8-flash"
    save_investigation(seed_store, "run-again", result)
    con.close()
    assert _by(collect_seed(seed_store, 42), "gemini-3.8-flash", MAIN_ARM).notes == before


def test_the_deterministic_and_judged_numbers_stay_apart(seed_store: Any) -> None:
    """D-13: the headline is checked by rule; the model-judged number sits beside it."""
    row = _by(collect_seed(seed_store, 42), "gemini-3.8-flash", MAIN_ARM)
    # The fixture's note cites one row that does not exist, so the rule-checked
    # number is 4 of 6 while the judge - which was told every claim holds - says
    # all of them. They must stay two numbers; averaging them would hide the gap.
    assert row.deterministic_valid == pytest.approx(4 / 6, abs=0.001)
    assert row.semantic_valid == 1.0
    assert row.first_draft_valid == 0.9  # from the run that produced them
    text = render_markdown(agent_report_of([row]))
    assert "model-judged" in text and "never blended" in text


def agent_report_of(results: list[Any]) -> Any:
    from spendguard.eval.agent_report import AgentReport

    return AgentReport(seeds=[42], results=results, manifest={"commit": "abc"})


def test_a_short_sample_is_labelled_rather_than_quietly_reported(seed_store: Any) -> None:
    """Two notes against a sample of four is an indication, not a rate."""
    report = agent_report_of(collect_seed(seed_store, 42))
    text = render_markdown(report)
    assert "still short of their sample" in text
    assert "not a rate" in text


def test_a_spread_is_only_reported_when_more_than_one_seed_has_notes(
    seed_store: Any, tmp_path: Path
) -> None:
    one = agent_report_of(collect_seed(seed_store, 42))
    assert "## Across seeds" not in render_markdown(one)

    both = collect_seed(seed_store, 42) + collect_seed(seed_store, 7)
    report = agent_report_of(both)
    report.seeds = [42, 7]
    assert "## Across seeds" in render_markdown(report)


def test_reading_every_seed_skips_the_ones_never_run(tmp_path: Path, seed_store: Any) -> None:
    report = agent_report([42, 7, 2026], eval_dir=tmp_path)
    assert {r.seed for r in report.results} == {42}  # only seed 42 has a store
    assert report.seeds == [42, 7, 2026]


def test_nothing_investigated_yet_says_so_rather_than_printing_zeros(tmp_path: Path) -> None:
    report = agent_report([42], eval_dir=tmp_path / "empty")
    assert report.results == []
    assert "No investigations stored yet" in render_markdown(report)


def test_the_written_report_carries_its_provenance(seed_store: Any, tmp_path: Path) -> None:
    report = agent_report([42], eval_dir=tmp_path)
    md, js = write_agent_report(report, tmp_path / "results")
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["seeds"] == [42] and payload["results"]
    assert "manifest" in payload and "Regenerate with" in md.read_text(encoding="utf-8")
