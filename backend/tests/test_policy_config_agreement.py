"""FR-2.14 - the procurement policy and the configuration must state the same figures.

If these drift, the Investigator will cite a policy clause quoting one number
while the detector that raised the case used another. That is a contradiction a
panel would find immediately, and it undermines the citation guarantee that is
the project's headline contribution.
"""

from __future__ import annotations

import pytest

from spendguard.config import settings
from spendguard.policy_check import (
    POLICY_TO_SETTINGS,
    PolicyParseError,
    find_disagreements,
    parse_policy_thresholds,
)


def test_policy_document_exists() -> None:
    assert settings.policy_path.is_file(), f"No policy document at {settings.policy_path}"


def test_threshold_table_parses() -> None:
    thresholds = parse_policy_thresholds()
    assert thresholds, "Threshold summary table parsed to nothing"


def test_every_mapped_threshold_is_present_in_policy() -> None:
    thresholds = parse_policy_thresholds()
    missing = [key for key in POLICY_TO_SETTINGS if key not in thresholds]
    assert not missing, f"Policy threshold summary is missing rows: {missing}"


def test_policy_and_config_agree() -> None:
    """The check that actually matters."""
    problems = find_disagreements()
    assert not problems, "Policy and configuration disagree:\n  - " + "\n  - ".join(problems)


def test_principal_threshold_is_two_and_a_half_lakh() -> None:
    """Decision D-16, policy clause SG-PP-2.2."""
    thresholds = parse_policy_thresholds()
    principal = thresholds["principal_control_threshold"]
    assert principal.value == 250_000.0
    assert principal.clause == "SG-PP-2.2"
    assert settings.approval_threshold == 250_000.0


def test_every_detector_has_a_policy_anchor() -> None:
    """Each detector must be able to cite at least one policy clause."""
    thresholds = parse_policy_thresholds()
    anchored = " ".join(t.used_by for t in thresholds.values())
    for detector in ("D1", "D2", "D3", "D4"):
        assert detector in anchored, f"{detector} has no threshold anchored to a policy clause"


def test_detects_a_deliberate_mismatch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check must actually fail when the policy disagrees - not silently pass."""
    original = settings.policy_path.read_text(encoding="utf-8")
    tampered = original.replace(
        "| **Principal control threshold** | **₹2,50,000** |",
        "| **Principal control threshold** | **₹5,00,000** |",
    )
    assert tampered != original, "Tamper target not found; the policy table format changed"

    fake_policy = tmp_path / "policy.md"
    fake_policy.write_text(tampered, encoding="utf-8")

    problems = find_disagreements(fake_policy)
    assert any("Principal control threshold" in p for p in problems)


def test_unparseable_value_raises(tmp_path) -> None:
    fake_policy = tmp_path / "policy.md"
    fake_policy.write_text(
        "## Threshold summary\n\n"
        "| Parameter | Value | Clause | Used by |\n"
        "|---|---|---|---|\n"
        "| Some limit | whenever it feels right | SG-PP-9.9 | D1 |\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyParseError):
        parse_policy_thresholds(fake_policy)


def test_missing_summary_heading_raises(tmp_path) -> None:
    fake_policy = tmp_path / "policy.md"
    fake_policy.write_text("# A policy with no threshold summary\n", encoding="utf-8")
    with pytest.raises(PolicyParseError):
        parse_policy_thresholds(fake_policy)
