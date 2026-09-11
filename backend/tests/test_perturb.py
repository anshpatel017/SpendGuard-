"""Perturbations shared by the generator and the injection harness (DR-3)."""

from __future__ import annotations

import numpy as np
import pytest

from spendguard.pipeline.perturb import (
    LEGITIMATE_VARIANTS,
    add_firm_honorific,
    legitimate_variant,
    swap_legal_suffix,
    typo,
)
from spendguard.pipeline.vendors import name_similarity, normalize_vendor

NAMES = [
    "Sharma Traders Pvt Ltd",
    "Global Chemicals Private Limited",
    "Apex Hydraulics",
    "Goyal Constructions LLP",
    "Balaji Electricals & Co",
]


def rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def test_swap_changes_the_suffix_form() -> None:
    out = swap_legal_suffix("Sharma Traders Pvt Ltd", rng())
    assert out != "Sharma Traders Pvt Ltd"
    assert out.startswith("Sharma Traders ")


def test_swap_is_a_no_op_without_a_private_limited_suffix() -> None:
    assert swap_legal_suffix("Apex Hydraulics", rng()) == "Apex Hydraulics"


def test_honorific_prefix() -> None:
    assert add_firm_honorific("Apex Hydraulics", rng()).startswith("M/")


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", range(20))
def test_legitimate_variants_never_change_the_vendor_key(name: str, seed: int) -> None:
    """The generator relies on this: a legitimate variant is the same supplier."""
    assert normalize_vendor(legitimate_variant(name, rng(seed))) == normalize_vendor(name)


@pytest.mark.parametrize("name", NAMES)
def test_legitimate_variant_always_changes_the_string(name: str) -> None:
    assert all(legitimate_variant(name, rng(s)) != name for s in range(20))


def test_typo_is_not_a_legitimate_variant() -> None:
    assert typo not in LEGITIMATE_VARIANTS


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("seed", range(10))
def test_typo_is_small(name: str, seed: int) -> None:
    out = typo(name, rng(seed))
    assert out[0] == name[0], "typo must never touch the first character"
    assert abs(len(out) - len(name)) <= 1
    assert name_similarity(name, out) >= 85


def test_perturbations_are_reproducible() -> None:
    assert legitimate_variant(NAMES[0], rng(42)) == legitimate_variant(NAMES[0], rng(42))
    assert typo(NAMES[0], rng(42)) == typo(NAMES[0], rng(42))
