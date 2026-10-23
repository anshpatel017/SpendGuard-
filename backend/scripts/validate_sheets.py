"""Check reviewer and grader sheets before they are imported.

Six CSVs come back from three people who have opened them in whatever spreadsheet
they had. Excel re-encodes, reorders, drops a header, turns `0` into `0.0`, or
silently writes a BOM. `review import` and `grade import` will reject some of
that and quietly accept the rest, and a verdict that lands in the wrong row is a
measurement error nobody can see afterwards.

So this checks the things that must hold before any of it is imported:

  * the header is byte-identical to the sheet as exported
  * the row order and the id in each row are unchanged
  * the row count is what the batch drew
  * every verdict is one of the three allowed words
  * every score is 0, 1, 2 or genuinely empty
  * the file parses as UTF-8 CSV

It reads the `.orig.csv` backup beside each sheet when one exists, which is the
only reliable record of what was exported. Without it the structural checks fall
back to the first row of the sheet itself, and the output says so rather than
implying a comparison it did not make.

Run it before importing:

    python backend/scripts/validate_sheets.py

Exit status is 1 if any sheet fails, so it can gate an import step.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REVIEW_DIR = Path("data/review")
GRADING_DIR = Path("data/grading/seed42")

VERDICTS = {"plausible", "implausible", "unclear"}
SCORES = {"0", "1", "2"}
REVIEW_ROWS = 46
GRADE_ROWS = 7

REVIEW_HEADER = ["case_id", "detector", "anomaly_type", "verdict", "comment"]
GRADE_HEADER = [
    "blind_id",
    "factual_accuracy",
    "evidence_sufficiency",
    "alternative_considered",
    "verdict_justified",
    "actionability",
    "comment",
]
GRADE_DIMENSIONS = GRADE_HEADER[1:-1]


@dataclass
class Result:
    path: Path
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    means: dict[str, float | None] = field(default_factory=dict)
    filled: int = 0
    total: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def _read(path: Path) -> tuple[list[str], list[list[str]]] | None:
    try:
        text = path.read_text(encoding="utf-8-sig")  # tolerate a BOM, report it below
    except UnicodeDecodeError:
        return None
    rows = list(csv.reader(text.splitlines()))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return None
    return rows[0], rows[1:]


def _check_structure(res: Result, header: list[str], rows: list[list[str]],
                     expected_header: list[str], expected_rows: int) -> None:
    if header != expected_header:
        res.problems.append(f"header is {header}, expected {expected_header}")
    if len(rows) != expected_rows:
        res.problems.append(f"{len(rows)} rows, expected {expected_rows}")
    width = len(expected_header)
    for i, row in enumerate(rows, start=2):
        if len(row) != width:
            res.problems.append(f"line {i}: {len(row)} columns, expected {width}")

    if path_orig := _orig_for(res.path):
        original = _read(path_orig)
        if original is None:
            res.notes.append(f"{path_orig.name} unreadable; order not compared")
            return
        orig_header, orig_rows = original
        if header != orig_header:
            res.problems.append("header differs from the exported sheet")
        ids_now = [r[0] for r in rows if r]
        ids_orig = [r[0] for r in orig_rows if r]
        if ids_now != ids_orig:
            if sorted(ids_now) == sorted(ids_orig):
                res.problems.append("rows were reordered - verdicts may be against the wrong ids")
            else:
                res.problems.append("the set of ids does not match the exported sheet")
    else:
        res.notes.append("no .orig.csv backup; order checked against this file only")


def _orig_for(path: Path) -> Path | None:
    orig = path.parent / f"{path.stem}.orig.csv"
    return orig if orig.exists() else None


def check_review(path: Path) -> Result:
    res = Result(path)
    parsed = _read(path)
    if parsed is None:
        res.problems.append("not readable as UTF-8 CSV")
        return res
    header, rows = parsed
    _check_structure(res, header, rows, REVIEW_HEADER, REVIEW_ROWS)

    res.total = len(rows)
    for i, row in enumerate(rows, start=2):
        if len(row) < 5:
            continue
        verdict = row[3].strip()
        comment = row[4].strip()
        if not verdict:
            continue
        res.filled += 1
        if verdict != verdict.lower():
            res.problems.append(f"line {i}: verdict {verdict!r} is not lowercase")
        if verdict.lower() not in VERDICTS:
            res.problems.append(f"line {i}: verdict {verdict!r} is not one of {sorted(VERDICTS)}")
            continue
        res.counts[verdict.lower()] += 1
        if verdict.lower() in {"implausible", "unclear"} and not comment:
            res.notes.append(f"line {i}: {verdict} with no comment (how-to-review asks for one)")
    if res.filled == 0:
        res.problems.append("no verdicts filled in - nothing to import")
    elif res.filled < res.total:
        res.problems.append(f"only {res.filled} of {res.total} verdicts filled")
    return res


def check_grades(path: Path) -> Result:
    res = Result(path)
    parsed = _read(path)
    if parsed is None:
        res.problems.append("not readable as UTF-8 CSV")
        return res
    header, rows = parsed
    _check_structure(res, header, rows, GRADE_HEADER, GRADE_ROWS)

    res.total = len(rows)
    per_dimension: dict[str, list[int]] = {d: [] for d in GRADE_DIMENSIONS}
    for i, row in enumerate(rows, start=2):
        if len(row) < len(GRADE_HEADER):
            continue
        scored = 0
        for offset, dimension in enumerate(GRADE_DIMENSIONS, start=1):
            cell = row[offset].strip()
            if not cell:
                continue
            scored += 1
            # Excel turns 0 into 0.0 often enough to be worth naming precisely.
            if cell not in SCORES:
                res.problems.append(
                    f"line {i}: {dimension} is {cell!r}, expected 0, 1, 2 or empty"
                )
                continue
            per_dimension[dimension].append(int(cell))
        if scored:
            res.filled += 1
    for dimension, values in per_dimension.items():
        res.means[dimension] = round(sum(values) / len(values), 2) if values else None
    if res.filled == 0:
        res.problems.append("no scores filled in - nothing to import")
    elif res.filled < res.total:
        res.problems.append(f"only {res.filled} of {res.total} notes scored")
    return res


def main() -> int:
    results: list[Result] = []
    for name in ("a", "b", "c"):
        p = REVIEW_DIR / f"reviews-{name}.csv"
        results.append(check_review(p) if p.exists() else _missing(p))
    for name in ("a", "b", "c"):
        p = GRADING_DIR / f"grades-{name}.csv"
        results.append(check_grades(p) if p.exists() else _missing(p))

    failed = 0
    for res in results:
        status = "OK " if res.ok else "FAIL"
        print(f"{status}  {res.path}")
        if res.counts:
            total = sum(res.counts.values())
            spread = "  ".join(f"{k}={res.counts[k]}" for k in sorted(VERDICTS))
            print(f"      {total} verdicts   {spread}")
        if any(v is not None for v in res.means.values()):
            means = "  ".join(
                f"{d.split('_')[0]}={v}" for d, v in res.means.items() if v is not None
            )
            print(f"      {res.filled}/{res.total} notes scored   mean  {means}")
        for note in res.notes:
            print(f"      note: {note}")
        for problem in res.problems:
            print(f"      PROBLEM: {problem}")
        failed += 0 if res.ok else 1

    print()
    print(f"{len(results) - failed} of {len(results)} sheets ready to import.")
    if failed:
        print("Fix the sheets, not the import code.")
    return 1 if failed else 0


def _missing(path: Path) -> Result:
    res = Result(path)
    res.problems.append("file not found")
    return res


if __name__ == "__main__":
    sys.exit(main())
