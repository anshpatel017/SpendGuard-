# Evaluation

This is where the project earns its marks. Everything here must be reproducible from a seed.

---

## 1. The core problem

Fraud datasets have no labels. Nobody publishes "these 100 transactions are fraud." Without labels there is no precision, no recall, and no defensible claim of improvement.

**Solution: an anomaly-injection harness.** Take real public procurement data and script the injection of realistic frauds. The injected anomalies are the ground truth. Because injection is scripted and seeded, the whole evaluation reproduces exactly.

---

## 2. Injection harness

### 2.1 What gets injected

| Class | Method |
|---|---|
| **Duplicate** | Copy a real row. Perturb the vendor string — typos, "Pvt Ltd" to "Private Limited", spacing and case changes. Shift the date by a few days. Keep the amount identical or within a very small tolerance. |
| **Split** | Replace one above-threshold transaction with 3-6 sub-threshold transactions to the same vendor and officer, inside a short window, summing to the original amount. |
| **Inflation** | Multiply unit price by a factor in the range 1.5-3.0 for sampled line items within a category. |
| **Vendor flag** | Synthesize a vendor whose invoices are round-number heavy, temporally clustered at period end, and whose first-digit distribution departs from the Benford expectation. |

### 2.2 Parameters

| Parameter | Value |
|---|---|
| Injection rate | `rate` = anomaly **groups** per transaction, default 1%. Splits touch several rows each, so the share of rows touched is higher — **2.24%** on the 50k development dataset — and is reported with every run. |
| Mix | 40% duplicate, 25% split, 35% inflation; vendor flags separately, 1% of suppliers, at least 2 |
| Inside the policy definitions | Duplicate shifts ≤ 10 days and split windows ≤ 10 days, both inside the 14-day policy windows even after a weekend roll. An anomaly no correct detector could find would measure nothing. |
| Disjoint | A row belongs to at most one anomaly group, so matching is unambiguous |
| Per-category injection cap (inflation) | 5% of a category's rows, and only categories with enough rows to establish a norm |
| Vendor-flag pricing | Round numbers, but priced within the category's normal range — so a fake vendor tests the vendor-flag detector alone and never also trips the price detector |
| Seeds | Fixed and recorded. Results reported across multiple seeds. |
| Reproducibility | Fully scripted. Same seed and same input produce byte-identical output. |

### 2.3 Ground truth records

Each injection writes a `ground_truth` row: the group id, the anomaly class, the row ids forming the anomaly, the source rows it was derived from, the seed, the parameters used, and the amount at risk.

### 2.4 Isolation rule

Injection markers (`is_injected`, `injection_group_id`, `injection_type`) live in the `transactions` table so detectors see exactly what an auditor would see. **Detectors must never read them.** Only the evaluation harness does.

Enforced two ways. Detectors query the `audit_transactions` view, which omits the markers and `source_row_ref` (injected rows have none, so its absence would itself leak the answer). And a test parses every detector module and fails on any string literal naming a hidden column, the ground-truth table, or the raw `transactions` table. That test was verified by planting a leak and confirming it fails.

---

## 3. Matching a detected case to ground truth

A case is a group of rows, and an injected anomaly is a group of rows. Scoring requires a rule for when they correspond.

### 3.1 Row-group anomalies (D1, D2, D3)

A detected case counts as a **true positive** when both hold:

1. At least one injected row from the ground-truth group is present in the case, **and**
2. No more than 50% of the case's rows are spurious — that is, not part of the ground-truth group.

Otherwise the case is a false positive. A ground-truth group matched by no case is a false negative.

**Exactly 50% spurious still matches** — the boundary is inclusive, defined once in `eval/matching.py`, and unit-tested on both sides.

**Matching is one-to-one and score-ordered.** Cases are visited from highest `detector_score` down, ties broken by `case_id`; each claims the best still-unclaimed group — most overlap, then least spurious. A second case landing on an already-claimed group is a **false positive**: an auditor handed five alerts for one split scheme has four redundant alerts, and the metric should say so. This is the object-detection convention, and it keeps the ranked list consistent with average precision.

Types must agree: a duplicate case never matches a split group.

### 3.2 Vendor-level anomalies (D4)

Row-overlap matching does not work for D4, because a vendor red-flag case contains all of that vendor's transactions while injection may have altered only a subset. Under the row rule, a correct detection would score as a false positive.

**Rule for D4:** match at the vendor level. A D4 case is a true positive when its `vendor_key` is the vendor the anomaly was injected into. Row-level metrics for D4 are reported separately and interpreted with this in mind.

### 3.3 Two granularities, both reported

| Granularity | Question it answers |
|---|---|
| **Per case** (primary) | "How many of the frauds did we find, and how many alerts were wasted?" — the auditor's question |
| **Per row** (secondary) | "How much of the implicated data did we surface?" — the completeness question |

Both are reported, because examiners may ask for either and they genuinely differ.

---

## 4. Detection metrics

Per detector, against the rule-based baseline, at both granularities:

| Metric | Purpose |
|---|---|
| Precision | Of what we flagged, how much was real |
| Recall | Of what was there, how much we found |
| F1 | Balance |
| PR-AUC | Threshold-independent quality — more honest than ROC-AUC on heavily imbalanced data. Computed as average precision over **distinct score thresholds** (the scikit-learn definition), so tied scores enter together: a binary detector gets exactly precision × recall regardless of tie order. Missed groups count in the recall denominator. |
| Alert volume at fixed precision | Practical usability — how many alerts an auditor must work through to sustain a given precision |

### 4.0 The rule-based baseline

Four fixed rules — each a real, commonly used control, none of which normalizes names, learns a distribution, or looks at more than one transaction at a time. Every rule is binary, so every baseline case scores 1.0.

| Anomaly | Rule |
|---|---|
| duplicate | Same supplier name (case- and space-insensitive), same invoice number, same amount |
| split | Amount within 10% below the approval threshold |
| inflation | Unit price above twice the category mean |
| vendor_flag | At least half of a supplier's invoices (minimum 10) are exact multiples of ₹1,000 |

**First results** — 50,735 transactions, 504 injected groups, seed 42, per case:

| Anomaly | Precision | Recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| duplicate | 1.000 | 0.220 | 0.361 | 44 | 0 | 156 |
| split | 0.013 | 0.072 | 0.022 | 9 | 682 | 116 |
| inflation | 0.357 | 0.554 | 0.434 | 97 | 175 | 78 |
| vendor_flag | 0.364 | 1.000 | 0.533 | 4 | 7 | 0 |
| **all** | **0.151** | **0.306** | **0.202** | 154 | 864 | 350 |

Each failure is the gap a detector must close: exact matching misses disguised duplicates; the near-threshold rule drowns in legitimate large purchases; a mean-based price rule fires on honest premium and urgent purchases; and round-number vendors include legitimate fixed-fee contracts such as security services.

### 4.0a Phase 3 results — D1 and D2

Three injection seeds, 50k-row development dataset, per case, **mean ± standard deviation**. Seed 42 was used during design; **7 and 2026 are held out** — no threshold or model choice looked at them.

| Anomaly | Detector | Precision | Recall | F1 | PR-AUC |
|---|---|---:|---:|---:|---:|
| duplicate | baseline | 1.000 ± 0.000 | 0.215 ± 0.015 | 0.354 ± 0.020 | 0.215 ± 0.015 |
| duplicate | **D1** | **1.000 ± 0.000** | **0.903 ± 0.013** | **0.949 ± 0.007** | **0.903 ± 0.013** |
| split | baseline | 0.017 ± 0.003 | 0.096 ± 0.017 | 0.029 ± 0.005 | 0.002 ± 0.001 |
| split | **D2** | **0.828 ± 0.006** | **0.643 ± 0.014** | **0.724 ± 0.011** | **0.583 ± 0.011** |

**Clean-data check.** On the same dataset with *no* planted anomalies, D1 and D2 together raise **0** cases. This check is part of every evaluation from now on: it caught a failure the injected-data metrics could not show (decision D-20, correction 3).

**What D1 misses.** Almost exclusively duplicates paid under an unrelated reference (D-22). Duplicates disguised with a supplier-name typo are all found — the reason blocking is on amount rather than vendor key (D-19).

### 4.0b Results — all four detectors

Three injection seeds, 50k-row development dataset, per case, **mean ± sample standard deviation**. Seed 42 was used during design; **7 and 2026 are held out**.

> **Source:** [`docs/results/detection.md`](results/detection.md), generated by `spendguard report detection` at commit `10639cc`. It also holds the per-row table, the per-seed breakdown, the settings used and a determinism check. Re-run that command to reproduce every number here; do not edit these figures by hand.
>
> The spreads are the *sample* standard deviation (n − 1). An earlier hand-assembled version of this table used the population deviation, so its spreads were slightly narrower (for example ± 0.007 instead of ± 0.009 on D1's F1). The means were identical.

| Anomaly | Detector | Precision | Recall | F1 | PR-AUC |
|---|---|---:|---:|---:|---:|
| duplicate | baseline | 1.000 ± 0.000 | 0.215 ± 0.018 | 0.354 ± 0.024 | 0.215 ± 0.018 |
| duplicate | **D1** | **1.000 ± 0.000** | **0.903 ± 0.016** | **0.949 ± 0.009** | **0.903 ± 0.016** |
| split | baseline | 0.017 ± 0.004 | 0.096 ± 0.021 | 0.029 ± 0.006 | 0.002 ± 0.001 |
| split | **D2** | **0.828 ± 0.008** | **0.643 ± 0.017** | **0.724 ± 0.013** | **0.583 ± 0.013** |
| inflation | baseline | 0.353 ± 0.006 | 0.556 ± 0.003 | **0.432 ± 0.005** | 0.196 ± 0.004 |
| inflation | **D3** | 0.369 ± 0.008 | 0.484 ± 0.009 | 0.419 ± 0.009 | **0.280 ± 0.010** |
| vendor_flag | baseline | 0.414 ± 0.049 | 0.625 ± 0.125 | 0.497 ± 0.075 | 0.263 ± 0.082 |
| vendor_flag | **D4** | **1.000 ± 0.000** | **0.750 ± 0.125** | **0.853 ± 0.082** | **0.750 ± 0.125** |

**D3 does not beat the baseline on F1, and the report must say so.** It finishes marginally below (0.419 vs 0.432) while ranking substantially better (PR-AUC +43%). Legitimate premium and urgent purchases occupy the same price band as the injected markups, so no price statistic separates them — the reason the investigation layer exists (decision D-23).

**Clean-data check.** On the same dataset with no planted anomalies: D1, D2 and D4 raise **0** cases. D3 raises 154 of 49,900 rows (0.3%), the honest premium and urgent purchases.

### 4.1 The unlabeled-flag problem

Real procurement data already contains genuine duplicates, splits and inflated prices that nobody injected. When a detector correctly finds one, it scores as a false positive, because it is not in the ground-truth set. **Every detector's precision is therefore systematically understated.**

This is not a bug to hide; it is a property to state and quantify:

- Report **raw precision** — the strict number against injected ground truth
- Manually review the top-k unlabeled flags per detector, classify each as plausible-real or spurious, and report **adjusted precision** alongside
- State the review protocol and the value of k

Doing this converts a weakness into evidence of methodological care.

---

## 5. Agent metrics

### 5.1 Citation validity — reported as two numbers

Reporting one number invites the question "so the model grades itself?" The check is therefore split.

**Hard citation validity (deterministic).** For each citation: does the cited `row_id` exist, and do the values stated about it match the row's actual field values? Purely mechanical, no model involved. **This is the headline number, with a target of at least 95%.**

**Semantic support rate (model-judged).** Does the cited row actually support the claim made about it? An LLM judgment, reported alongside the hard number and explicitly labelled as model-judged.

Both are stored per citation, so both are computed by query rather than by re-parsing text.

### 5.2 Triage accuracy

Agreement between the agent's verdict (`likely_true_positive` / `likely_false_positive` / `inconclusive`) and injection ground truth, measured **only over cases the detectors flagged and the agent investigated**.

**Stated caveat:** only the top-N cases by severity are investigated, and severity is amount-weighted. Triage accuracy is therefore measured on the high-value slice, not on flagged cases uniformly. This is defensible — it mirrors how audit teams triage — but the report must say it rather than let a panel discover it.

### 5.3 Note factual accuracy

Blinded human rubric on a sample of notes:

- Sample size around 50 notes
- Three graders
- Notes shuffled and anonymized — grader cannot tell agent from template, or verifier-on from verifier-off
- Rubric fixed in advance and included in the report
- Inter-grader agreement reported

**As built (Phase 9).** Three commands, and the rubric lives in code so it cannot be revised after the grades are in.

```bash
spendguard grade export --seed 42            # rubric.md, notes.md, one sheet per grader, key.json
spendguard grade import grades-a.csv         # by blind id, into the evaluation store
spendguard grade report --seed 42            # -> docs/results/grading.md
```

| Concern | How it is handled |
|---|---|
| **The rubric** | Five dimensions scored **0, 1 or 2**: factual accuracy, evidence sufficiency, innocent explanation considered, verdict justified by the note alone, actionability. Each score has a written anchor. Three points rather than five, because three graders agree far better on three and an agreement number nobody believes makes the scores worthless. The third dimension is the one a template must score 0 on by construction. |
| **The sample** | Seeded; spread evenly over the arms first and anomaly types second, so the comparison is not between sample sizes and no arm is flattered by drawing the easy types. |
| **Blinding** | Notes are pooled, given opaque ids and shuffled per grader. The arm, model, verification badge, run id, note id and case id are never exported. A test reads every file a grader receives and fails if any of them appears; sabotaging the export makes it fail. |
| **Evidence** | The rows a note cites are printed beside it. Without them a grader can only judge fluency, which is what a language model is best at faking. |
| **Agreement** | Krippendorff's alpha, **ordinal** — it knows 0 against 2 is a worse disagreement than 0 against 1, which Fleiss' kappa does not. Implemented here and pinned to the published worked example (α nominal 0.691, ordinal 0.807). Exact agreement is reported beside it because it needs no definition. |
| **Corrections** | Re-importing a grader's sheet replaces their grades. A score off the scale or an unknown blind id is refused, not rounded. |

**One limitation that cannot be engineered away, and is printed in the report:** a template note is formulaic *by definition* — every one restates what the detector matched and every one agrees with it — so a grader working through a batch can come to recognise that arm. Removing the tell would mean making the template not a template. Its scores are an upper bound on how well blinding held, not a fully blind comparison.

### 5.4 Efficiency

Per case: average tool calls, prompt and completion tokens, wall-clock latency. Also the number of notes regenerated and the number that failed after the retry limit.

### 5.5 Money at risk

Total value implicated by flagged cases on real data, and separately the value in cases confirmed by a reviewer. This is the headline demonstration figure. It must be labelled as *value implicated by flagged transactions*, not as *fraud detected* — the flags are suspicions, not findings.

---

## 6. Ablations

Mandatory. Ablations are what distinguish a project that built something from a project that showed something.

| Ablation | Configuration | Expected result | What it proves |
|---|---|---|---|
| **Verifier off** | Investigator releases notes with no citation checking | Citation-error rate rises sharply | The Verifier is load-bearing, not decoration |
| **Template notes** | Replace the agent with template-filled notes from detector output | Information quality drops on the blinded rubric while citation validity stays high | The agent adds information a template cannot, which is the whole thesis |
| **Model size** | Compare a smaller and a larger model on the same cases | Larger model improves structure adherence and reasoning quality | Characterizes the quality-per-compute trade-off |

Each ablation runs on the same cases, the same seed, and the same dataset as the main run. Only the named variable changes.

**As built (Phase 9).** Each arm draws the same seeded sample as the main run and is stored beside it, never inside it: an arm's notes carry `ablation_name`, never stand as a case's own note, never mark a case investigated, and are scored only against the arm's own notes. Each arm writes its own report, `investigate-eval-<stamp>-seed<seed>-<arm>.{md,json}`, and appears as its own row on the dashboard's evaluation page, described from the run's own config snapshot.

| Arm | Command | Notes |
|---|---|---|
| Verifier off | `spendguard investigate --eval-seed 42 --no-verify` | Labelled `no-verifier` automatically in evaluation mode. The *deterministic* check still runs — otherwise the arm could not be measured — but nothing is enforced and nothing is regenerated, and the notes are released `unverified`. |
| Template notes | `spendguard investigate --eval-seed 42 --ablation template` | Needs no model to write: the note is filled from the detector's output and the rows it flagged. The Verifier still checks and judges it, so the comparison is like for like. Every verdict is `likely_true_positive` by construction — the template cannot weigh an innocent explanation, which is precisely what the triage column measures. |
| Model size | `LLM_PROVIDER=… spendguard investigate --eval-seed 42` | No arm name: a note records the model that wrote it and evaluation is scored per model (D-33), so a smaller model is another run, not another arm. |

---

## 7. Reproducibility

| Requirement | Implementation |
|---|---|
| Every stochastic component seeded | One global seed in configuration, threaded through injection, sampling, Isolation Forest, and any model sampling |
| Every run logged | Parameters, seed, configuration snapshot, and results written to a local experiment tracker and to `eval_results` |
| Same seed reproduces results | Verified by test — a repeated run produces identical detector output |
| Multiple seeds reported | Headline numbers reported as mean with spread across seeds, not a single lucky run |
| Configuration snapshotted | The full config is stored with the run, so a result can always be traced to the settings that produced it |

---

## 8. Headline result format

> On **N** real transactions with **M** injected anomalies, SpendGuard achieved **F1 = X** against a rule-based baseline at **Y**, with **Z%** hard citation validity, and flagged **V** of value implicated in suspicious real spend.

Every number in that sentence must trace to a logged run.

---

## 9. Honesty caveats to include in the report

These belong in the limitations section. Stating them is stronger than being asked about them.

1. **Not duplicate-payment confirmation.** D1 detects duplicate transaction records. Confirming an actual double disbursement requires invoice-to-payment reconciliation, which the available public datasets do not contain.
2. **Investigation is not exhaustive.** Detection covers 100% of rows; investigation covers the top-N cases by severity. The claim is "detects across 100%, investigates prioritized cases."
3. **Precision is understated.** Real anomalies already present in the data score as false positives against injected ground truth. Adjusted precision from manual review of the top-k flags is reported alongside the raw figure.
4. **Triage accuracy is measured on a severity-biased sample.**
5. **The procurement policy is authored by the team**, with clauses derived from published public rules, because the datasets do not ship with the issuing organization's internal policy.
6. **Semantic citation checking is model-judged**, and is reported separately from the deterministic check for that reason.
7. **`officer_id` may be a coarse grain.** Where a dataset provides only a department rather than an individual buyer, D2 groups more loosely and will surface more benign groups. The grain used is recorded in each case's metadata.
8. **No claim of superior raw detection accuracy** against commercial systems trained on vastly larger proprietary corpora. The contribution is the investigation and verification layer.
