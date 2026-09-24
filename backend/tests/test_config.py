"""Phase 0 smoke tests: the package imports, settings load, paths resolve."""

from __future__ import annotations

from pathlib import Path

import pytest

from spendguard.config import LLMProvider, Settings, SeverityBand, get_settings, settings


def test_package_imports() -> None:
    assert settings is not None


def test_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_project_root_resolves_to_repo() -> None:
    root: Path = settings.project_root
    assert (root / "docs").is_dir()
    assert (root / "policy" / "policy.md").is_file()
    assert (root / "backend" / "pyproject.toml").is_file()


def test_currency_is_rupees() -> None:
    """Decision D-15."""
    assert settings.currency == "INR"
    assert settings.currency_symbol == "₹"


def test_thresholds_are_ordered() -> None:
    """The GFR ladder must be monotonically increasing (policy SG-PP-2.1)."""
    assert (
        settings.direct_purchase_ceiling
        < settings.approval_threshold
        < settings.limited_tender_ceiling
    )


def test_split_windows_are_sorted_and_deduplicated() -> None:
    assert settings.split_windows_all == [3, 7, 14]


def test_llm_provider_defaults_to_groq() -> None:
    """Development default (D-26). The test pins the code, not whatever .env says.

    Read through ``settings``, this failed the day the dev machine switched to
    Gemini for the evaluation runs - which is exactly what LLM_PROVIDER is for.
    """
    assert Settings.model_fields["llm_provider"].default is LLMProvider.GROQ


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (100.0, SeverityBand.HIGH),
        (66.0, SeverityBand.HIGH),
        (65.9, SeverityBand.MEDIUM),
        (33.0, SeverityBand.MEDIUM),
        (32.9, SeverityBand.LOW),
        (0.0, SeverityBand.LOW),
    ],
)
def test_severity_band_boundaries(severity: float, expected: SeverityBand) -> None:
    """Decision D-08: High >= 66, Medium 33-65, Low < 33."""
    assert settings.band_for(severity) is expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0.00"),
        (5, "₹5.00"),
        (999, "₹999.00"),
        (1_000, "₹1,000.00"),
        (99_999, "₹99,999.00"),
        (100_000, "₹1,00,000.00"),
        (250_000, "₹2,50,000.00"),
        (2_500_000, "₹25,00,000.00"),
        (10_000_000, "₹1,00,00,000.00"),
        (1_234_567.5, "₹12,34,567.50"),
        (-250_000, "-₹2,50,000.00"),
    ],
)
def test_indian_digit_grouping(amount: float, expected: str) -> None:
    """FR-6.10: money is displayed with Indian grouping, not thousands separators."""
    assert settings.money(amount) == expected


def test_env_overrides_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing may be hardcoded: every value must be overridable from the environment."""
    monkeypatch.setenv("APPROVAL_THRESHOLD", "500000")
    monkeypatch.setenv("INVESTIGATE_TOP_N", "7")
    fresh = Settings()
    assert fresh.approval_threshold == 500_000.0
    assert fresh.investigate_top_n == 7
