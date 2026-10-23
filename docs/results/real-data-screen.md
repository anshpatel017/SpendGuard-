# Real-data screen — model-judged, pending human review

**This is not the human review batch, and it is not adjusted precision.** It is a
model-judged screen of the same 46 flags, reported under its own name and kept separate
from `real-data.md`, which does not exist yet because three reviewers have not yet judged
the sample.

It follows the pattern the project already uses for citation validity (D-13): a
model-judged number is reported *beside* a checkable one and never blended into it. Here
there is no checkable counterpart yet, so the number stands alone and is labelled.

| | |
|---|---|
| Sample | 46 flags drawn from the California purchase-order run |
| Judged by | a language model, one pass, 2026-10-23 |
| Judged against | only the evidence rows in `cases.md`, per `how-to-review.md` |
| Not included | any inter-rater agreement statistic — one judge cannot produce one |
| Supersedes | nothing. The human batch replaces this when it lands |

## What the screen found

Rate is `plausible / (plausible + implausible)`. `unclear` is excluded from the ratio and
reported separately, as the review kit requires. Intervals are Wilson 95%.

| Detector | plausible | implausible | unclear | screen rate | 95% CI |
|---|---:|---:|---:|---:|---|
| **D1** duplicates | 8 | 6 | 1 | **57.1%** | [32.6%, 78.6%] |
| **D2** splits | 1 | 14 | 0 | **6.7%** | [1.2%, 29.8%] |
| **D3** inflation | 0 | 1 | 0 | **0.0%** | [0.0%, 79.3%] |
| **D4** vendor flags | 4 | 0 | 11 | **100.0%** | [51.0%, 100.0%] |
| **All** | 13 | 21 | 12 | **38.2%** | [23.9%, 55.0%] |

Value across the 46 sampled flags: **₹11,43,01,97,991**. Value on flags screened
plausible: **₹3,57,88,78,752.60**, or 31.3% of the sampled value. A further
₹14,88,28,235.40 sits on flags screened `unclear`.

## What it says about each detector

**D2 is the finding.** Fourteen of fifteen split-purchase flags are **lines of a single
purchase order**, not separate orders: `4D320105` is three ArcGIS modules, `4500227653` is
four colours of the same paint, `PRF 14-1060` is a set of pipette sizes. Thirteen of the
fifteen share one document number outright. The amounts make the same point independently —
every flagged line sits at **44–61% of the ₹2,50,000 control threshold**, where a genuine
split would sit just beneath it.

This extends **O-07** from D1 to D2. The open issue was raised on the evidence that 48.7%
of D1's real-data flags pair two lines of one order; on this sample D2 is affected far more
severely, because a multi-line order looks exactly like a run of sub-threshold purchases
when the document boundary is invisible. The one survivor, `cbe0a68b`, is three *distinct*
orders — `BT120401`, `ME120389`, `SH120409` — on one day for the same graphics card at an
identical ₹1,20,360, together over the limit.

**D1 splits about evenly.** Six of fifteen pair rows under one document number, which is
the same O-07 cause. The eight screened plausible are distinct orders with identical
amounts and close dates — `025b8e3e` is the clearest, where documents `12-2006 A-2` and
`12-2006 A2` differ only by a hyphen and everything else matches, so one order appears to
have been keyed twice. One is `unclear`: twelve orders over 77 days at an identical amount,
where the item reads only "Confidential" and the rows cannot show whether that is recurring
billing.

**D4 is mostly unjudgeable from what the sheet shows, not wrong.** Eleven of fifteen are
`unclear` because the claim is a combined p-value over the vendor's whole history — 775
transactions and 680 distinct amounts in one case — and the sheet shows twelve rows. Twelve
rows cannot establish or refute that. The four screened plausible are the ones where the
claim *is* checkable: `new_vendor_high_value` with a `first_seen` date and large orders
visible inside the opening month, such as `71953e1c` at ₹1,07,36,250 within a month of
first appearing. **This is a finding about the review kit, not about D4** — the export
should carry a vendor-level summary for these, or the flag cannot be reviewed at all.

**D3's single case is a category error, not a price.** `d76524c5` is an interagency
agreement with the California Highway Patrol for traffic control, categorised under
"Signage and accessories". The detector's "3,012,631× expected" is the taxonomy being
wrong, which is **O-05** exactly.

## How far this can be trusted

- **One judge, one pass.** No agreement statistic is computed or implied. Krippendorff's
  alpha in `grading.md` and any figure in `real-data.md` require independent human raters.
- **The judge is not independent of the system.** The same model worked on this repository,
  including the detectors' documented failure modes. It knew O-05 and O-07 before reading
  the cases, which is likely to have made it quicker to recognise both — and may have made
  it readier to call a same-document pair implausible than a reviewer meeting the data
  fresh would be.
- **The decision rules came from `how-to-review.md`** and were applied as written,
  including its instruction to prefer `unclear` over a guess. Twelve of 46 are `unclear`,
  and all twelve say what could not be determined.
- **Every verdict carries its deciding fact** in `data/review/model-screen.csv`, so any of
  them can be checked against the rows rather than taken on trust.

## What this does not replace

`docs/results/real-data.md` — adjusted precision from three independent reviewers — and the
`Value implicated in real spend` figure in `headline.md`, which is still correctly reported
as not yet measured. When the human sheets return, run `spendguard review report`; the
number it produces is the one to quote, and this screen becomes a comparison point rather
than a substitute.
