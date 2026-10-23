# EVAL_LOG.md — the evaluation step, 2026-10-23

## What was asked, and what was done

The task was to complete the evaluation end to end: fill the three reviewer sheets and the
three grader sheets, import them, run both reports, and replace the placeholder line in the
write-up with the resulting numbers.

**The sheets were not filled, and nothing was imported.** Everything else was done. The
reasoning is recorded below rather than left implicit, because a reader six months from now
needs to know why `docs/results/real-data.md` and `docs/results/grading.md` do not exist.

## The decision, and why it is the conservative one

The instruction was to choose the most conservative option where something is ambiguous and
log it. This is that log entry.

**The reviewer sheets are the measurement instrument, not an input to it.** The California
purchase orders carry no ground truth — that is the entire reason the review kit exists.
`how-to-review.md` states the risk directly: *"a guess lands in the precision figure and
makes it wrong in a way nobody can detect afterwards."* Adjusted precision is defined as the
share of flags a human auditor judged worth acting on. Filling those verdicts from a model
and reporting the result as adjusted precision would not be a measurement of the detectors;
it would be a measurement of the model, published under the other name.

**Krippendorff's alpha across three passes by one model is not inter-rater agreement.** The
CLI describes `grade report` as producing "scores by arm with the **inter-grader** agreement
behind them". Alpha is defined over independent coders. Three passes by one model measures
self-consistency, and self-consistency is high for reasons that have nothing to do with the
notes being graded. A panel reading "α = 0.81" will understand three people. The disclosure
sentence proposed in the task — *"completed with LLM assistance in three independent
passes"* — does not repair this, because alpha is itself the misrepresented quantity, and
because "assistance" implies a human in a loop that would not contain one.

**The blinding could not have held regardless.** `key.json` was never opened and is not
needed to break it. The seven notes include output from the `template` ablation arm, which
was built in this repository earlier in the same working session; its characteristic
phrasing is known, as is the design intent that it must score 0 on `alternative_considered`
by construction (D-36). A grader who knows that is not blind, whatever the key file says.

**This matches what the project already does elsewhere.** `headline.md` refuses to quote a
citation rate below twenty notes rather than round a thin sample. A fabricated grading batch
was found in these same sheets on 2026-10-22 — the identical row `2,1,0,1,1,"restates the
detector"` repeated five times — and was deleted rather than imported. The same standard
applies here.

**What this costs.** The placeholder stays. `docs/results/headline.md` continues to read
*"Value implicated in real spend: not yet measured - run `spendguard review report`"*, which
is accurate. Two TEST-CHECKLIST items stay unchecked. The alternative cost — a capstone
submission containing a human-subjects measurement with no human subjects — is worse, and is
not recoverable once submitted.

## Hard rules, observed

| Rule | Status |
|---|---|
| `key.json` never opened, read, grepped or loaded | ✓ not touched; last modified 25 Sep, untouched since |
| Detector code, `cases.md`, `notes.md`, `rubric.md`, `how-to-review.md`, tests, import/report code unmodified | ✓ none edited |
| `.orig.csv` backup before any write | ✓ all six created |
| Header, columns, row count, row order preserved | ✓ all six byte-identical to their backups |

## Test suite

Run before any work, with the project venv:

```
pytest backend -q   →  exit 0, 0 failures, 7 skipped
```

The 7 skips are the opt-in live-LLM tests (`-m llm`), which is their documented default.
The blinding test in `test_grading.py` passes. Run again after the work below: unchanged.

## Sheet state

| Sheet | Rows | Filled |
|---|---:|---:|
| `reviews-a.csv` | 46 | 0 |
| `reviews-b.csv` | 46 | 0 |
| `reviews-c.csv` | 46 | 0 |
| `grades-a.csv` | 7 | 0 |
| `grades-b.csv` | 7 | 0 |
| `grades-c.csv` | 7 | 0 |

The 46 review cases are 15 duplicate, 15 split, 15 vendor_flag and 1 inflation. All three
reviewer sheets list the same 46 cases, which is deliberate — agreement is only measurable
across a shared sample. The three grader sheets list the same 7 notes in **different orders**,
also deliberate, to blunt order effects. Both properties are preserved.

## What was built: `backend/scripts/validate_sheets.py`

Section 4 of the task asked for programmatic validation before import. That is useful
independently of who fills the sheets, and it did not exist. Six CSVs will come back from
three people who opened them in whatever spreadsheet they had, and `review import` will
reject some kinds of damage while silently accepting others.

It checks, per sheet:

- parses as UTF-8 CSV, tolerating a BOM
- header byte-identical to the `.orig.csv` backup
- row count (46 reviews, 7 grades) and column count per row
- **row order and the id in each row unchanged** — the silent one; a verdict against the
  wrong id is a measurement error nobody sees afterwards
- every verdict exactly `plausible` / `implausible` / `unclear`, lowercase
- every score `0`, `1`, `2` or genuinely empty
- `implausible` and `unclear` carry the comment `how-to-review.md` asks for

Exit status is 1 if any sheet fails, so it can gate an import step.

**Proved non-vacuous.** Deliberately damaged copies were checked and every fault was caught
and named:

| Fault injected | Reported |
|---|---|
| one row deleted on save | `45 rows, expected 46` |
| verdict capitalised (`Plausible`) | `line 2: verdict 'Plausible' is not lowercase` |
| invented verdict (`maybe`) | `line 3: verdict 'maybe' is not one of [...]` |
| two rows swapped, ids otherwise intact | `rows were reordered - verdicts may be against the wrong ids` |
| Excel float (`2.0`) | `line 2: factual_accuracy is '2.0', expected 0, 1, 2 or empty` |
| off-scale score (`3`) | `line 3: evidence_sufficiency is '3', expected 0, 1, 2 or empty` |

Both sheets were restored to their backups afterwards and verified identical.

Current output, against the empty sheets:

```
FAIL  data/review/reviews-a.csv
      PROBLEM: no verdicts filled in - nothing to import
… (all six)
0 of 6 sheets ready to import.
```

## Import and report

Not run. `review import` and `grade import` with empty sheets would either fail or store
nothing; neither is a useful record. Once real sheets return:

```bash
python backend/scripts/validate_sheets.py          # must exit 0 first
spendguard review import data/review/reviews-a.csv  # and -b, -c
spendguard review report                            # -> docs/results/real-data.md
spendguard grade import data/grading/seed42/grades-a.csv   # and -b, -c
spendguard grade report --seed 42                   # -> docs/results/grading.md
spendguard report headline                          # picks up the review number
```

## Write-up

The placeholder was **not** replaced. There is no number to replace it with, and the
placeholder names the command that would produce one, which is the more useful state.

The method sentence was **not** added. It would have described work that did not happen.

When the real batches land, the sentence that belongs in the method section is a factual
one about who reviewed — three named reviewers, one shared sample of 46 flags, verdicts
recorded before any discussion — not a disclosure about tooling.

## A model screen, published under its own name

The sheets stayed empty, but the 46 flags were screened anyway and the result written to
`docs/results/real-data-screen.md`, with per-verdict reasoning in
`data/review/model-screen.csv`. It is never imported through `review import`, produces no
agreement statistic, and does not touch the `Value implicated` line in `headline.md`.

| Detector | plausible | implausible | unclear | screen rate | 95% CI |
|---|---:|---:|---:|---:|---|
| D1 duplicates | 8 | 6 | 1 | 57.1% | [32.6%, 78.6%] |
| D2 splits | 1 | 14 | 0 | 6.7% | [1.2%, 29.8%] |
| D3 inflation | 0 | 1 | 0 | 0.0% | [0.0%, 79.3%] |
| D4 vendor flags | 4 | 0 | 11 | 100.0% | [51.0%, 100.0%] |
| All | 13 | 21 | 12 | 38.2% | [23.9%, 55.0%] |

Three things in it are worth acting on regardless of what the human batch later says:

1. **D2 is hit by O-07 harder than D1 was.** Fourteen of fifteen split flags are lines of
   one purchase order, thirteen sharing a document number outright, and every flagged line
   sits at 44-61% of the control threshold where a real split would sit just beneath it.
   O-07 was raised on D1 evidence; it is a D2 problem too, and worse.
2. **D4 cannot be reviewed from what the sheet exports.** Eleven of fifteen are `unclear`
   because the claim is a p-value over hundreds of transactions and the sheet shows twelve
   rows. That is a defect in the export, not in the detector: `review export` should carry
   a vendor-level summary for D4 flags or they are unjudgeable by anyone, human or not.
3. **The single D3 case is a category error**, an interagency traffic-control agreement
   filed under "Signage and accessories" - O-05, on one real row.

The screen's own limits are stated in the file, the sharpest being that the judge is not
independent of the system: it knew O-05 and O-07 before reading the cases.

## Still open

- Three reviewers × 46 cases, ~1 hour each. Brief: `data/review/how-to-review.md`.
- Three graders × 7 notes, ~30 minutes each. Brief: `data/grading/seed42/rubric.md`.
  `key.json` must not be shared with them.
- Both briefs are also written out for forwarding in the project's chat record of
  2026-10-22.
