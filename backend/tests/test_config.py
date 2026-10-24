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


def test_the_agent_evaluation_plan_names_only_real_seeds_and_arms() -> None:
    """The plan is walked unattended over days; a typo in it wastes a day of quota."""
    from spendguard.ablations import ARMS

    plan = settings.agent_eval_plan
    assert plan, "the reported agent results come from this plan"
    assert all(step.seed in settings.evaluation_seeds for step in plan)
    assert all(step.arm is None or step.arm in ARMS for step in plan)
    assert all(step.per_type >= 1 for step in plan)
    # The development seed is reported thoroughly and with every arm; the
    # held-out seeds narrowly, on the main arm only (CLAUDE.md convention 6).
    dev = [s for s in plan if s.seed == settings.random_seed]
    assert {s.arm for s in dev} == {None, *ARMS}
    assert all(s.arm is None for s in plan if s.seed != settings.random_seed)
    assert all(
        s.per_type <= min(d.per_type for d in dev) for s in plan if s.seed != settings.random_seed
    )


def test_split_windows_are_sorted_and_deduplicated() -> None:
    assert settings.split_windows_all == [3, 7, 14]


def test_the_delivered_default_needs_no_external_api() -> None:
    """FR-3.11 and NFR-1: what ships runs locally, with no key and no network.

    This pins the *code* default, not whatever `.env` says on the machine running
    the tests - the distinction the whole provider switch exists for. The reported
    evaluation runs on Groq via `LLM_PROVIDER=groq`, and that is a per-machine
    choice; a fresh clone must not reach for someone else's free tier, three of
    which have already been retired or broken under this project (D-37).

    The earlier version of this test asserted the default was Groq, which was
    true of the development machine and wrong for the delivered system.
    """
    default = Settings.model_fields["llm_provider"].default
    assert default is LLMProvider.OLLAMA
    assert Settings.model_fields[f"{default.value}_base_url"].default.startswith(
        "http://localhost"
    ), "the default endpoint is on this machine"


def test_the_shipped_env_template_does_not_reach_for_an_external_api() -> None:
    """`.env.example` is what a fresh clone copies, so it is the real default.

    Pinning only `Settings` would leave the guarantee half-made: someone follows
    the README, copies the template, and the delivered system is back on a free
    tier it has no key for. A key left blank beside `LLM_PROVIDER=groq` fails at
    the first investigation rather than at setup, which is the worse of the two.
    """
    from spendguard.config import PROJECT_ROOT

    template = PROJECT_ROOT / ".env.example"
    assert template.is_file(), "the setup the README documents has to exist"
    assigned = dict(
        line.split("=", 1)
        for line in template.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    assert assigned["LLM_PROVIDER"].strip() == LLMProvider.OLLAMA.value
    assert assigned["LLM_PROVIDER"].strip() == Settings.model_fields["llm_provider"].default.value

    # And no secret rode along into the template.
    for key, value in assigned.items():
        if key.endswith("_API_KEY"):
            assert value.strip() == "", f"{key} must ship empty, not pre-filled"


def test_no_provider_default_carries_a_usable_key() -> None:
    """A real key must come from the environment, never from the source tree.

    If a default ever reads like a key, it is either a committed secret or it
    makes an unconfigured clone look configured. Both are worse than failing.
    """
    for provider in LLMProvider:
        field = f"{provider.value}_api_key"
        if field in Settings.model_fields:
            assert Settings.model_fields[field].default == "not-set"


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
