"""Policy retrieval (FR-3.10): clause parsing, caching, and search quality.

Parsing and prose flattening need nothing but text and run everywhere. The
search tests need the embedding model, so they skip where the agent extras are
not installed (CI installs only the detection extras).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spendguard.agent.policy import (
    CLAUSE_HEADING,
    Clause,
    fingerprint,
    parse_clauses,
    to_prose,
)
from spendguard.config import settings

# A paraphrase and the clause that answers it. Deliberately colloquial: none of
# these repeats the clause's own wording.
PROBES: list[tuple[str, str]] = [
    ("Can a department break one big order into several small ones?", "SG-PP-3.1"),
    ("We paid the same bill twice. How do we get the money back?", "SG-PP-4.5"),
    ("Is it fine to spend leftover budget before the year closes?", "SG-PP-7.2"),
    ("How much can I buy without asking anyone for quotes?", "SG-PP-2.1"),
    ("A firm we just signed up wants a very large order", "SG-PP-5.3"),
    ("The seller charges far more than everyone else for the same goods", "SG-PP-6.3"),
    ("Who signs off on a purchase of fifteen lakh rupees?", "SG-PP-2.1"),
    ("Someone approved their own brother-in-law's company", "SG-PP-5.4"),
    ("Two invoices from one supplier, same amount, a week apart", "SG-PP-4.4"),
    ("Must we buy through the government marketplace?", "SG-PP-1.4"),
]


# ---------------------------------------------------------------- parsing


def test_every_clause_in_the_policy_is_parsed() -> None:
    clauses = parse_clauses()
    expected = len(CLAUSE_HEADING.findall(settings.policy_path.read_text(encoding="utf-8")))
    assert len(clauses) == expected > 30


def test_clauses_carry_an_id_a_title_and_a_section() -> None:
    clause = next(c for c in parse_clauses() if c.clause_id == "SG-PP-3.2")
    assert clause.title == "Indicators of splitting"
    assert "Splitting" in clause.section or "split" in clause.section.lower()
    assert "fourteen days" in clause.text


def test_a_clause_is_never_split_in_half() -> None:
    """Half a clause reads as authoritative and is incomplete."""
    clause = next(c for c in parse_clauses() if c.clause_id == "SG-PP-2.1")
    # The whole value-band table survives, first row to last, plus its provenance note.
    assert "Up to" in clause.text and "Finance Committee" in clause.text
    assert "GFR 2017" in clause.text


def test_a_clause_never_swallows_the_next_section() -> None:
    for clause in parse_clauses():
        assert "\n## " not in clause.text, clause.clause_id


def test_ids_are_unique() -> None:
    ids = [c.clause_id for c in parse_clauses()]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- prose flattening


def test_tables_become_readable_prose() -> None:
    flattened = to_prose("| Band | Value |\n|---|---|\n| A | Up to Rs 25,000 |")
    assert "|" not in flattened and "---" not in flattened
    assert "Up to Rs 25,000" in flattened


def test_bullets_and_emphasis_are_stripped() -> None:
    flattened = to_prose("- placed with the **same supplier**\n- within **fourteen days**")
    assert "*" not in flattened and flattened.startswith("placed with the same supplier")


# ---------------------------------------------------------------- cache key


def test_the_cache_key_moves_when_the_embedded_text_moves() -> None:
    """Regression: keying on the policy file alone let stale vectors win after a
    change to how clauses are flattened."""
    one = Clause("SG-PP-1.1", "T", "S", "body")
    two = Clause("SG-PP-1.1", "T", "S", "body, amended")
    assert fingerprint([one], "m") != fingerprint([two], "m")
    assert fingerprint([one], "m") != fingerprint([one], "other-model")
    assert fingerprint([one], "m") == fingerprint([one], "m")


# ---------------------------------------------------------------- search


@pytest.fixture(scope="module")
def index() -> object:
    pytest.importorskip("sentence_transformers", reason="agent extras not installed")
    pytest.importorskip("faiss", reason="agent extras not installed")
    from spendguard.agent.policy import PolicyIndex

    return PolicyIndex()


@pytest.mark.slow
def test_a_paraphrase_finds_the_right_clause(index) -> None:  # type: ignore[no-untyped-def]
    """ "break one big order into several" shares no words with "No requirement
    shall be divided into smaller purchases"."""
    top = index.search("Can a department break one big order into several small ones?", k=3)
    assert top[0].clause.clause_id == "SG-PP-3.1"
    assert 0.0 < top[0].score <= 1.0


@pytest.mark.slow
def test_retrieval_quality_on_the_probe_set(index) -> None:  # type: ignore[no-untyped-def]
    """Dense retrieval measured at top-1 5/10 and top-3 7/10 when chosen over
    BM25 and hybrid; these bounds catch a regression, not a small drift."""
    top1 = top3 = 0
    for query, expected in PROBES:
        ids = [m.clause.clause_id for m in index.search(query, k=3)]
        top1 += ids[0] == expected
        top3 += expected in ids
    assert top1 >= 4, f"top-1 fell to {top1}/10"
    assert top3 >= 6, f"top-3 fell to {top3}/10"


@pytest.mark.slow
def test_search_returns_whole_clauses_with_citable_ids(index) -> None:  # type: ignore[no-untyped-def]
    for match in index.search("duplicate payment recovery", k=3):
        assert match.clause.clause_id.startswith("SG-PP-")
        assert match.clause.text
        assert set(match.as_dict()) == {"clause_id", "title", "section", "text", "similarity"}


@pytest.mark.slow
def test_empty_query_returns_nothing(index) -> None:  # type: ignore[no-untyped-def]
    assert index.search("   ") == []


@pytest.mark.slow
def test_unknown_mode_is_rejected(index) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="mode"):
        index.search("anything", mode="magic")


@pytest.mark.slow
def test_lookup_by_id(index) -> None:  # type: ignore[no-untyped-def]
    assert index.by_id("SG-PP-3.2") is not None
    assert index.by_id("SG-PP-99.9") is None


@pytest.mark.slow
def test_the_index_is_cached_on_disk(tmp_path: Path) -> None:
    from spendguard.agent.policy import PolicyIndex

    first = PolicyIndex(cache_dir=tmp_path)
    assert list(tmp_path.glob("clauses-*.npz"))
    second = PolicyIndex(cache_dir=tmp_path)
    assert second.fingerprint == first.fingerprint
