"""String perturbations shared by the synthetic generator and the injection harness.

One module, two users (docs/REQUIREMENTS.md DR-3):

* the **generator** applies *legitimate* variants - the same supplier typed
  differently by different clerks - so vendor normalization has real work to do;
* the **injection harness** applies the same operations plus typos to disguise
  a duplicated record.

Sharing the machinery matters: an injected duplicate then looks exactly like
the harmless variation already present in the data, which is what makes the
detection problem honest.

Every function takes a numpy ``Generator`` so results are reproducible from a seed.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

# Interchangeable spellings of the Indian private-limited form.
PVT_LTD_FORMS: tuple[str, ...] = ("Pvt Ltd", "Pvt. Ltd.", "Private Limited", "Pvt Limited")

_PVT_LTD_SUFFIX = re.compile(
    r"\s+(pvt\.?\s*ltd\.?|private\s+limited|pvt\.?\s+limited)\s*$", re.IGNORECASE
)


def _canonical_form(form: str) -> str:
    return re.sub(r"[\s.]", "", form.lower())


def swap_legal_suffix(name: str, rng: np.random.Generator) -> str:
    """'Sharma Traders Pvt Ltd' -> 'Sharma Traders Private Limited'. No-op without such a suffix."""
    match = _PVT_LTD_SUFFIX.search(name)
    if match is None:
        return name
    current = _canonical_form(match.group(1))
    choices = [f for f in PVT_LTD_FORMS if _canonical_form(f) != current]
    return f"{name[: match.start()]} {choices[int(rng.integers(len(choices)))]}"


def change_case(name: str, rng: np.random.Generator) -> str:
    """UPPER, lower or Title case - whichever of those actually differ from the input."""
    options = [v for v in (name.upper(), name.lower(), name.title()) if v != name]
    if not options:  # no letters to recase, e.g. "12345"
        return f"{name} "
    return options[int(rng.integers(len(options)))]


def add_firm_honorific(name: str, rng: np.random.Generator) -> str:
    """Prefix the Indian firm honorific: 'M/s Sharma Traders'."""
    return f"{('M/s', 'M/S', 'M/s.')[int(rng.integers(3))]} {name}"


def extra_whitespace(name: str, rng: np.random.Generator) -> str:
    """Double one internal space, or pad the end."""
    spaces = [i for i, ch in enumerate(name) if ch == " "]
    if not spaces or rng.random() < 0.3:
        return f"{name}  "
    i = spaces[int(rng.integers(len(spaces)))]
    return f"{name[:i]} {name[i:]}"


def _long_word_positions(name: str, min_length: int = 4) -> list[int]:
    """Letter positions inside words of at least ``min_length`` letters."""
    positions: list[int] = []
    for match in re.finditer(r"[^\W\d_]+", name):
        if len(match.group()) >= min_length:
            positions.extend(range(match.start(), match.end()))
    return positions


def typo(name: str, rng: np.random.Generator) -> str:
    """One keystroke error - swap, drop, or double a letter.

    Never touches the first character, and only lands in words of four or more
    letters: a slip in "Pvt" or "Co" reads as a different abbreviation rather
    than a misspelling, and is not how disguised duplicates look in practice.

    Used by the injection harness to disguise duplicates, never by the generator:
    a typo is not a legitimate variant.
    """
    letters = [i for i in _long_word_positions(name) if i > 0]
    if not letters:
        return name
    i = letters[int(rng.integers(len(letters)))]
    op = int(rng.integers(3))
    if op == 0 and i + 1 < len(name) and name[i + 1].isalpha():
        return f"{name[:i]}{name[i + 1]}{name[i]}{name[i + 2 :]}"  # swap with next
    if op == 1:
        return f"{name[:i]}{name[i + 1 :]}"  # drop
    return f"{name[:i]}{name[i]}{name[i:]}"  # double


Perturbation = Callable[[str, np.random.Generator], str]

LEGITIMATE_VARIANTS: tuple[Perturbation, ...] = (
    swap_legal_suffix,
    change_case,
    add_firm_honorific,
    extra_whitespace,
)


def legitimate_variant(name: str, rng: np.random.Generator) -> str:
    """How the same supplier's name drifts across real invoices. Never a typo."""
    op = LEGITIMATE_VARIANTS[int(rng.integers(len(LEGITIMATE_VARIANTS)))]
    varied = op(name, rng)
    return varied if varied != name else change_case(name, rng)
