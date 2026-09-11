"""Vendor normalization (FR-1.5) and the blocking/identity split (decision D-12)."""

from __future__ import annotations

import pytest

from spendguard.pipeline.vendors import identity_name, name_similarity, normalize_vendor


@pytest.mark.parametrize(
    "variant",
    [
        "Sharma Enterprises",
        "SHARMA ENTERPRISES PVT LTD",
        "Sharma  Enterprise",
        "Enterprises Sharma",
        "M/s. Sharma Enterprises Private Limited",
        "M/S Sharma Enterprises",
        "Messrs Sharma Enterprises",
        "sharma enterprises pvt. ltd.",
        "  Sharma Enterprises  ",
        "The Sharma Enterprises",
    ],
)
def test_documented_variants_collapse_to_one_key(variant: str) -> None:
    """The CLAUDE.md examples, plus the Indian 'M/s' honorific."""
    assert normalize_vendor(variant) == "sharma"


def test_key_is_order_independent() -> None:
    assert normalize_vendor("Saxena Petroleum") == normalize_vendor("Petroleum Saxena")


def test_trade_words_that_are_not_generic_survive() -> None:
    """Only 'enterprises' and 'traders' are generic; 'Petroleum' says what the business is."""
    assert normalize_vendor("Saxena Petroleum Pvt Ltd") == "petroleum saxena"
    assert normalize_vendor("Saxena Traders") != normalize_vendor("Saxena Petroleum")


def test_legal_suffix_only_names_do_not_collapse_to_empty() -> None:
    """Otherwise every such vendor would share the key '' and look like one supplier."""
    assert normalize_vendor("The Company Ltd") != ""
    assert normalize_vendor("Traders & Co") != ""


@pytest.mark.parametrize("empty", [None, "", "   ", "\t\n"])
def test_empty_input_gives_empty_key(empty: str | None) -> None:
    assert normalize_vendor(empty) == ""


@pytest.mark.parametrize(
    "name",
    ["12345", "3M India Ltd", "शर्मा ट्रेडर्स", "Café Supplies", "Ω Omega Labs", "ABC-123/XYZ"],
)
def test_unusual_names_do_not_raise_and_stay_non_empty(name: str) -> None:
    assert normalize_vendor(name)


def test_devanagari_vowel_signs_are_kept() -> None:
    """Combining marks are part of the word; stripping them would mangle the name."""
    assert normalize_vendor("शर्मा") == "शर्मा"


def test_cooperative_is_not_split_by_co_stripping() -> None:
    key = normalize_vendor("Amul Co-operative Society")
    assert "cooperative" in key
    assert normalize_vendor("Amul Cooperative Society") == key


@pytest.mark.parametrize(
    ("typoed", "clean"),
    [
        ("Global Chemicals Private Limitd", "Global Chemicals Private Limited"),
        ("Global Chemicals Privte Limited", "Global Chemicals Private Limited"),
        ("Sharma Tradres", "Sharma Traders"),
        ("Sharma Enterprsies", "Sharma Enterprises"),
    ],
)
def test_one_keystroke_typo_in_a_suffix_keeps_the_key(typoed: str, clean: str) -> None:
    """Otherwise a duplicate disguised with a suffix typo lands in a different block."""
    assert normalize_vendor(typoed) == normalize_vendor(clean)


def test_short_stopwords_match_exactly_only() -> None:
    """One edit from 'pvt' is 'pvc' - a real trade word that must survive."""
    assert "pvc" in normalize_vendor("Sharma PVC Pipes")


def test_honorific_only_stripped_as_prefix() -> None:
    assert normalize_vendor("MS Dhoni Sports") == "dhoni ms sports"


# ------------------------------------------------------------- identity (D-12)


def test_identity_keeps_trade_words() -> None:
    assert identity_name("Sharma Traders Pvt. Ltd.") == "sharma traders"


def test_blocking_key_collides_where_identity_does_not() -> None:
    """The documented trade-off: one key, two different businesses."""
    a, b = "Patel Traders", "Patel & Co"
    assert normalize_vendor(a) == normalize_vendor(b) == "patel"
    assert identity_name(a) != identity_name(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Sharma Traders Pvt Ltd", "SHARMA TRADERS PRIVATE LIMITED"),
        ("Sharma Traders", "M/s Sharma Traders"),
        ("Global Chemicals Pvt Ltd", "Global  Chemicals"),
        ("Saxena Petroleum", "Petroleum Saxena"),
        ("Balaji Electricals", "Balaji Electricls"),  # typo
        ("Sharma Traders", "Sharma raders"),  # typo on a first letter changes sort order
    ],
)
def test_genuine_variants_score_high(a: str, b: str) -> None:
    assert name_similarity(a, b) >= 90


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Sharma Traders", "Sharma Electricals"),
        ("Saxena Petroleum", "Saxena Constructions"),
        ("Patel Traders", "Patel & Sons"),
    ],
)
def test_different_businesses_sharing_a_stem_score_low(a: str, b: str) -> None:
    assert name_similarity(a, b) < 75


def test_similarity_of_empty_is_zero() -> None:
    assert name_similarity("", "Sharma Traders") == 0.0
    assert name_similarity(None, None) == 0.0
