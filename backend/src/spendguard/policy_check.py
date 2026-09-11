"""Parse the threshold summary table out of ``policy/policy.md``.

The procurement policy and ``config.py`` state the same figures in two places.
They will drift unless something checks them. If they drift, an audit note will
cite a policy clause saying one number while the detector that raised the case
used another - which quietly destroys the citation guarantee the whole project
rests on.

This module extracts the figures from the policy prose. ``tests/test_policy_config_agreement.py``
asserts they equal the configured values (docs/REQUIREMENTS.md FR-2.14).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spendguard.config import settings

_SUMMARY_HEADING = "## Threshold summary"

# "3 and 7 days" -> [3, 7]
_MULTI_INT = re.compile(r"^(\d+)\s+and\s+(\d+)\s+\w+$")
# "14 days", "12 months"
_SINGLE_INT = re.compile(r"^(\d+)\s+\w+$")
# "0.5%"
_PERCENT = re.compile(r"^([\d.]+)\s*%$")
# "Rs 2,50,000" with any leading currency symbol
_MONEY = re.compile(r"^[^\d]*([\d,]+(?:\.\d+)?)$")


class PolicyParseError(RuntimeError):
    """The policy document could not be parsed as expected."""


@dataclass(frozen=True)
class PolicyThreshold:
    """One row of the policy's threshold summary table."""

    parameter: str
    raw_value: str
    value: float | int | list[int]
    clause: str
    used_by: str

    @property
    def key(self) -> str:
        """Normalized lookup key: 'Duplicate amount tolerance' -> 'duplicate_amount_tolerance'."""
        cleaned = re.sub(r"[^a-z0-9]+", "_", self.parameter.lower())
        return cleaned.strip("_")


def _strip_markdown(cell: str) -> str:
    """Remove bold markers, inline code ticks and surrounding whitespace."""
    return cell.replace("**", "").replace("`", "").strip()


def _parse_value(raw: str) -> float | int | list[int]:
    """Turn a policy table value into the type ``config.py`` stores it as."""
    text = _strip_markdown(raw)

    if match := _MULTI_INT.match(text):
        return [int(match.group(1)), int(match.group(2))]

    if match := _PERCENT.match(text):
        return float(match.group(1)) / 100.0

    if match := _SINGLE_INT.match(text):
        return int(match.group(1))

    if match := _MONEY.match(text):
        return float(match.group(1).replace(",", ""))

    raise PolicyParseError(f"Cannot parse threshold value from policy: {raw!r}")


def parse_policy_thresholds(policy_path: Path | None = None) -> dict[str, PolicyThreshold]:
    """Read the threshold summary table and return it keyed by normalized parameter name.

    Raises:
        FileNotFoundError: the policy document is missing.
        PolicyParseError: the heading or table is absent, or a value is unparseable.
    """
    path = policy_path or settings.policy_path
    if not path.exists():
        raise FileNotFoundError(f"Policy document not found at {path}")

    lines = path.read_text(encoding="utf-8").splitlines()

    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _SUMMARY_HEADING)
    except StopIteration as exc:
        raise PolicyParseError(f"No {_SUMMARY_HEADING!r} heading in {path}") from exc

    thresholds: dict[str, PolicyThreshold] = {}

    for line in lines[start + 1 :]:
        stripped = line.strip()

        if stripped.startswith("## "):  # next section - table is over
            break
        if not stripped.startswith("|"):
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 4:
            continue

        parameter, raw_value, clause, used_by = (_strip_markdown(c) for c in cells)

        # Skip the header row and the |---|---| separator row.
        if parameter.lower() == "parameter" or set(parameter) <= {"-", ":"}:
            continue

        threshold = PolicyThreshold(
            parameter=parameter,
            raw_value=raw_value,
            value=_parse_value(raw_value),
            clause=clause,
            used_by=used_by,
        )
        thresholds[threshold.key] = threshold

    if not thresholds:
        raise PolicyParseError(f"Threshold summary table in {path} contained no rows")

    return thresholds


# Maps a policy table row onto the attribute of ``Settings`` that mirrors it.
# Every entry here is a place the policy and the code must agree.
POLICY_TO_SETTINGS: dict[str, str] = {
    "direct_purchase_ceiling": "direct_purchase_ceiling",
    "principal_control_threshold": "approval_threshold",
    "limited_tender_ceiling": "limited_tender_ceiling",
    "split_detection_window": "split_window_days",
    "heightened_scrutiny_windows": "split_scrutiny_windows_days",
    "duplicate_amount_tolerance": "duplicate_amount_tolerance",
    "duplicate_date_window": "duplicate_date_window_days",
    "pre_payment_lookback": "prepayment_lookback_days",
    "new_vendor_period": "new_vendor_days",
    "price_history_comparison_period": "price_history_months",
}


def find_disagreements(policy_path: Path | None = None) -> list[str]:
    """Return a human-readable message for every policy/config mismatch.

    An empty list means the policy document and the configuration agree.
    """
    thresholds = parse_policy_thresholds(policy_path)
    problems: list[str] = []

    for policy_key, settings_attr in POLICY_TO_SETTINGS.items():
        threshold = thresholds.get(policy_key)
        if threshold is None:
            problems.append(
                f"Policy is missing a threshold summary row for {policy_key!r} "
                f"(expected to match settings.{settings_attr})"
            )
            continue

        configured = getattr(settings, settings_attr)

        if isinstance(threshold.value, list):
            matches = sorted(threshold.value) == sorted(configured)
        else:
            matches = abs(float(threshold.value) - float(configured)) < 1e-9

        if not matches:
            problems.append(
                f"{threshold.parameter} ({threshold.clause}): "
                f"policy says {threshold.raw_value!r} -> {threshold.value}, "
                f"but settings.{settings_attr} is {configured}"
            )

    return problems
