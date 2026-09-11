"""Vendor name normalization - the foundation every detector depends on.

Two normalizations, for two different jobs (docs/DECISIONS.md D-12):

``normalize_vendor`` -> ``vendor_key``
    Aggressive. Strips legal forms *and* generic trade words, then token-sorts
    so word order does not matter. Used for **blocking**: cheaply grouping
    records that *might* be one supplier. It deliberately over-merges -
    "Patel Traders" and "Patel & Co" both become ``patel``.

``identity_name`` / ``name_similarity``
    Conservative. Strips only legal forms and keeps what the business *is*.
    Used to **confirm** that two records inside one block really are the same
    supplier before anything is reported as a duplicate.

Treating the blocking key as proof of identity would inflate D1's false positives.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz
from rapidfuzz.distance import OSA

# How a business is registered - says nothing about what it does.
LEGAL_FORMS: frozenset[str] = frozenset(
    {
        "pvt",
        "private",
        "ltd",
        "limited",
        "llp",
        "llc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "and",
    }
)

# Generic trade words. Stripped for the blocking key only (CLAUDE.md section 7).
GENERIC_TRADE_WORDS: frozenset[str] = frozenset({"enterprise", "enterprises", "trader", "traders"})

# Stopwords long enough to be matched fuzzily. Short ones ("pvt", "co") are
# exact-only: one edit from "pvt" is "pvc", which is a real trade word.
_FUZZY_MIN_LENGTH = 5


def _matches(token: str, vocabulary: frozenset[str]) -> bool:
    """Exact membership, or within one keystroke for longer words.

    OSA distance counts an adjacent swap as one edit, so "Limitd", "Privte" and
    "Tradres" are all recognised. Without this a single typo in a suffix
    changes the blocking key, and a disguised duplicate is never compared.
    """
    if token in vocabulary:
        return True
    if len(token) < _FUZZY_MIN_LENGTH:
        return False
    return any(
        OSA.distance(token, word, score_cutoff=1) <= 1
        for word in vocabulary
        if len(word) >= _FUZZY_MIN_LENGTH
    )


def _is_key_stopword(token: str) -> bool:
    return _matches(token, LEGAL_FORMS) or _matches(token, GENERIC_TRADE_WORDS)


def _is_legal_form(token: str) -> bool:
    return _matches(token, LEGAL_FORMS)


# "M/s", "M/S.", "Messrs" - the Indian honorific for a firm, never part of its name.
_FIRM_HONORIFIC = re.compile(r"^\s*(?:m\s*/\s*s|messrs)\b\.?")

# "Co-operative", "Co-op", "Cooperative" -> one token, so "co" is not stripped out of it.
_COOPERATIVE = re.compile(r"\bco\s*-?\s*op(?:erative)?\b")


def _strip_punctuation(text: str) -> str:
    """Replace every character that is not a letter, mark, digit or space with a space.

    Uses Unicode categories rather than ``[a-z0-9]`` so names in Devanagari or
    any other script survive: their vowel signs are combining *marks*, which a
    plain ``\\w`` regex would silently delete.
    """
    return "".join(
        ch if ch.isspace() or unicodedata.category(ch)[0] in "LMN" else " " for ch in text
    )


def _tokens(name: str) -> list[str]:
    """Shared front half of both normalizations."""
    text = unicodedata.normalize("NFKC", name).casefold()
    text = _FIRM_HONORIFIC.sub(" ", text)
    text = _COOPERATIVE.sub(" cooperative ", text)
    tokens = _strip_punctuation(text).split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return tokens


def normalize_vendor(name: str | None) -> str:
    """Blocking key: lowercase, no punctuation, no legal or generic trade words, token-sorted.

    >>> normalize_vendor("SHARMA ENTERPRISES PVT LTD")
    'sharma'
    >>> normalize_vendor("M/s. Sharma  Enterprise")
    'sharma'
    """
    if name is None:
        return ""
    tokens = _tokens(name)
    kept = [t for t in tokens if not _is_key_stopword(t)]
    # A name made only of stopwords ("The Company Ltd") would otherwise collapse
    # to "", and every such vendor would share one empty key.
    if not kept:
        kept = tokens
    return " ".join(sorted(kept))


def identity_name(name: str | None) -> str:
    """Conservative form for identity checks: legal forms removed, trade words kept.

    >>> identity_name("Sharma Traders Pvt. Ltd.")
    'sharma traders'
    """
    if name is None:
        return ""
    tokens = _tokens(name)
    kept = [t for t in tokens if not _is_legal_form(t)]
    if not kept:
        kept = tokens
    return " ".join(kept)


def name_similarity(a: str | None, b: str | None) -> float:
    """0-100 similarity of two raw vendor names, after legal forms are removed.

    High for genuine variants of one supplier (typos, "Pvt Ltd" vs "Private
    Limited", word order); low for different businesses that merely share a
    stem ("Sharma Traders" vs "Sharma Electricals"). The cut-off that turns this
    into a yes/no is a D1 decision, made against injected ground truth.

    Takes the better of two scorers, because each has a blind spot the other
    covers. Token-sort handles word order ("Saxena Petroleum" / "Petroleum
    Saxena") but collapses when a typo hits a word's first letter - "raders"
    sorts before "sharma" while "traders" sorts after, so the words are compared
    out of order. Plain ratio handles that typo but not reordering.
    """
    left, right = identity_name(a), identity_name(b)
    if not left or not right:
        return 0.0
    return float(max(fuzz.ratio(left, right), fuzz.token_sort_ratio(left, right)))
