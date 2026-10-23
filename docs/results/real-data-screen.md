# Real-data screen — model-judged, pending human review

**This is not the human review batch, and it is not adjusted precision.** It is a
model-judged screen of the 46 sampled flags, reported under its own name and kept
separate from `real-data.md`, which does not exist yet because three reviewers have not
yet judged the sample.

It follows the pattern the project already uses for citation validity (D-13): a
model-judged number is reported *beside* a checkable one and never blended into it. Here
there is no checkable counterpart yet, so the number stands alone and is labelled.

| | |
|---|---|
| Sample | 46 flags drawn from the California purchase-order run (`sample.json`, seed 42) |
| Judged by | a language model, 2026-10-23 |
| Judged against | only the evidence in `cases.md`, per `how-to-review.md` |
| Not included | any inter-rater agreement statistic — one judge cannot produce one |
| Supersedes | nothing. The human batch replaces this when it lands |

## Two passes, because the sheet changed between them

The first pass found that **11 of 15 vendor flags could not be judged at all**: the claim
is a combined p-value over a supplier's whole history, up to 1,029 transactions, and the
sheet showed twelve rows chosen by row id. That was a defect in `review export`, not in
D4, and it has since been fixed — the sheet now carries each test's rate against the
supplier's own peer group, the leading-digit comparison, and rows *chosen* to show the
behaviour that was flagged, each labelled with which test put it there.

**The 15 vendor flags were therefore screened a second time, against the fixed sheet.**
The D1, D2 and D3 verdicts below are from the first pass and were not revisited; nothing
in the fix changed what those cases show, beyond adding the policy clauses and the
matching stage to the header. Rows in the table are flagged accordingly.

| Detector | pass | plausible | implausible | unclear | screen rate | 95% CI |
|---|---|---:|---:|---:|---:|---|
| **D1** duplicates | first | 8 | 6 | 1 | **57.1%** | [32.6%, 78.6%] |
| **D2** splits | first | 1 | 14 | 0 | **6.7%** | [1.2%, 29.8%] |
| **D3** inflation | first | 0 | 1 | 0 | **0.0%** | [0.0%, 79.3%] |
| **D4** vendor flags | **second** | 9 | 6 | 0 | **60.0%** | [35.7%, 80.2%] |
| **All** | mixed | 18 | 27 | 1 | **40.0%** | [27.0%, 54.5%] |

Rate is `plausible / (plausible + implausible)`. `unclear` is excluded from the ratio and
reported separately, as the review kit requires. Intervals are Wilson 95%.

### What the export fix was worth

| | before | after |
|---|---:|---:|
| Vendor flags that could be judged | 4 of 15 | **15 of 15** |
| Vendor flags answered `unclear` | 11 | **0** |
| Reported D4 screen rate | 100.0% on n=4 | 60.0% on n=15 |

The first number was not a better result, it was a smaller one. A 100% rate resting on
four judgeable cases out of fifteen says almost nothing; the honest reading is that
two thirds of the detector's output was unreviewable. 60% on all fifteen is a measurement.

### Value

Value is each case's `amount_at_risk`, the figure the sheet itself prints per case.

| | amount | share |
|---|---:|---:|
| Across the 46 sampled flags | ₹25,90,26,14,841.73 | |
| On flags screened plausible | ₹2,15,89,14,764.40 | 8.3% |
| On flags screened implausible | ₹23,72,69,00,077.33 | 91.6% |
| On the one flag screened unclear | ₹1,68,00,000.00 | 0.1% |

**These figures correct the first pass**, which reported ₹11,43,01,97,991 sampled and
₹3,57,88,78,752.60 plausible. Neither matches the sum of `amount_at_risk` over the
sample on any grouping, so the earlier pair was wrong and is withdrawn rather than
carried forward.

The plausible share is small because the implausible column holds the bulk-fuel cases,
where a single flag covers ₹1,000 crore of supply contracts.

## What it says about each detector

**D2 is the finding.** Fourteen of fifteen split-purchase flags are **lines of a single
purchase order**, not separate orders: `4D320105` is three ArcGIS modules, `4500227653`
is four colours of the same paint, `PRF 14-1060` is a set of pipette sizes. Thirteen of
the fifteen share one document number outright. The amounts make the same point
independently — every flagged line sits at **44–61% of the ₹2,50,000 control
threshold**, where a genuine split would sit just beneath it.

This extends **O-07** from D1 to D2. The open issue was raised on the evidence that 48.7%
of D1's real-data flags pair two lines of one order; on this sample D2 is affected far
more severely, because a multi-line order looks exactly like a run of sub-threshold
purchases when the document boundary is invisible. The one survivor, `cbe0a68b`, is three
*distinct* orders — `BT120401`, `ME120389`, `SH120409` — on one day for the same graphics
card at an identical ₹1,20,360, together over the limit.

**D1 splits about evenly.** Six of fifteen pair rows under one document number, which is
the same O-07 cause. The eight screened plausible are distinct orders with identical
amounts and close dates — `025b8e3e` is the clearest, where documents `12-2006 A-2` and
`12-2006 A2` differ only by a hyphen and everything else matches, so one order appears to
have been keyed twice. One is `unclear`: twelve orders over 77 days at an identical
amount, where the item reads only "Confidential" and the rows cannot show whether that is
recurring billing.

**D4 divides on what the supplier sells, which is only visible now.** The nine screened
plausible are suppliers whose amounts cluster just under a round figure — `5497f8b8` has
six amounts between ₹3,88,725 and ₹3,98,025 against a peer rate of 16.9% for leading 3s,
`4d47351e` has four reagent orders at ₹2,98,909–₹2,99,130 — plus new suppliers taking
large value immediately, such as `71953e1c` at ₹1,07,36,250 inside its opening month, and
`92340a53` at 10.65× its peers' round-number rate, the largest ratio in the sample.

The six screened implausible share one shape: **the trade explains the habit**. Three are
bulk fuel (`3f76b6ae`, `cea19878`, `f79126b4`), where supply contracts are written against
round budget ceilings — ₹7,50,00,000, ₹1,08,00,00,000 — so a high round-number rate is how
the market works. `66439431` is sack lunches for fire crews, priced per lunch across
thousands of units, so the totals land on round thousands by arithmetic. `560bb7ba` is
annual ArcGIS maintenance renewals across 15 departments, which produces both flagged
habits at once. `5b4c514b` is bulk produce for prisons billed on a monthly cycle, so its
"period end" rows are the 23rd to 29th of successive months.

None of this was visible before the fix, and all of it is the detector working as
designed: D4 compares a supplier with its peer group, and the residual is exactly the
judgement a human has to make.

**D3's single case is a category error, not a price.** `d76524c5` is an interagency
agreement with the California Highway Patrol for traffic control, categorised under
"Signage and accessories". The detector's "3,012,631× expected" is the taxonomy being
wrong, which is **O-05** exactly.

## A new observation: the period-end definition is jurisdiction-bound

D4's period-end test counts "last four days of a month, **or March**". The March clause is
India's financial year end (GFR 2017), which is right for the policy the project
implements and wrong for California purchase orders, where March is an ordinary month.
The *ratio* survives this — peers are measured under the same definition, so both sides
carry the clause — but two cases show a second-order problem:

- `620a5cb2` reports **100% period end over 45 transactions** that fall on just two dates.
- `623f5716` reports **100% over 30 transactions** on two dates, with 6 distinct amounts.

A supplier with two order dates cannot have a period-end *habit*; the rate is an artefact
of how few dates there are. The test's `vendor_min_transactions` floor counts
transactions, not distinct dates, so a multi-line order passes it. Worth raising as an
open issue beside O-05 and O-07, and worth a sentence in the viva either way: it is the
kind of thing the export fix made visible, which is the argument for the fix.

## How far this can be trusted

- **One judge.** No agreement statistic is computed or implied. Krippendorff's alpha in
  `grading.md` and any figure in `real-data.md` require independent human raters.
- **The judge is not independent of the system.** The same model worked on this
  repository, including the detectors' documented failure modes, and wrote the export fix
  being evaluated here. It knew O-05 and O-07 before reading the cases, which is likely to
  have made it quicker to recognise both — and it has an obvious interest in the second
  pass looking better than the first. Treat the before/after table as a claim to check,
  not a result.
- **The two passes are not interchangeable.** The D4 verdicts were made against a richer
  sheet than D1–D3 were. The `All` row mixes them and is labelled as mixed.
- **The decision rules came from `how-to-review.md`** and were applied as written,
  including its instruction to prefer `unclear` over a guess.
- **Every verdict carries its deciding fact** in `data/review/model-screen.csv`, so any of
  them can be checked against the rows rather than taken on trust.

## What this does not replace

`docs/results/real-data.md` — adjusted precision from three independent reviewers — and
the `Value implicated in real spend` figure in `headline.md`, which is still correctly
reported as not yet measured. When the human sheets return, run `spendguard review
report`; the number it produces is the one to quote, and this screen becomes a comparison
point rather than a substitute.
