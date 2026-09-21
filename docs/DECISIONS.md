# Decision Log

Binding decisions and their rationale. Where an earlier document conflicts with an entry here, this file wins.

---

## D-01 — Detection object is the transaction record

**Decision.** We audit transaction records. We do not perform invoice-to-payment three-way matching. D1 detects duplicate *transaction records*; on a purchase-order dataset that means duplicate POs, on a payment dataset it means duplicate payments. The logic is identical, only the object changes.

**Rationale.** The available public datasets contain one document type, not the invoice-plus-payment pair that true duplicate-payment confirmation requires. Claiming otherwise would be false.

**Consequences.** Standard wording everywhere: "duplicate transaction records (POs or payments, depending on the source system)". The limitations section states the reconciliation gap. In demonstration narrative it is acceptable to say "this is the pattern that causes a duplicate payment" — but never to label a duplicate PO a duplicate payment in the report.

---

## D-02 — A case is an anomaly group

**Decision.** One case equals one anomaly group, not one row. Duplicate pair: 1 case, 2 rows. Split of five: 1 case, 5 rows. Inflation on a line item: 1 case, 1 row. Vendor flag: 1 case, N rows.

**Rationale.** This matches the unit an auditor actually works, and it is the unit the agent investigates.

**Consequences.** Primary metrics are per case. Per-row metrics are reported as a secondary table. Case-to-ground-truth matching needs an explicit overlap rule — see D-03.

---

## D-03 — Case matching rule for evaluation

**Decision.** For row-group anomalies (D1, D2, D3), a case is a true positive when at least one injected row is present **and** no more than 50% of the case's rows are spurious.

For vendor-level anomalies (D4), matching is at the vendor level: the case is a true positive when its `vendor_key` is the vendor the anomaly was injected into.

**Rationale.** Row-overlap matching breaks for D4. A vendor red-flag case contains all of that vendor's transactions, while injection may have altered only a subset — so a correct detection would score as a false positive under the row rule.

**Consequences.** Two matching implementations, both unit-tested at their boundaries. The 50% boundary behaviour is defined once in code.

---

## D-04 — The agent is a filter as well as a reporter

**Decision.** The Investigator emits one of three verdicts: `likely_true_positive`, `likely_false_positive`, `inconclusive`. It never deletes or auto-closes anything. A case dismissed on the agent's recommendation remains in the queue under a dedicated filter.

**Rationale.** Reducing the false-positive burden is a substantial part of the contribution — that burden is what makes rule engines unusable in practice. But an agent that silently closes cases is not auditable, which defeats the purpose.

**Consequences.** Triage accuracy becomes a reportable metric. The queue needs a "Dismissed by agent" filter. Severity adjustment after investigation is the agent's only influence on ranking.

---

## D-05 — Detection is 100%; investigation is top-N

**Decision.** Detectors run over every row, always. Investigation runs on the top-N cases by `severity_prelim`, N configurable. Remaining cases sit in the queue marked *not yet investigated*.

**Rationale.** Investigation is LLM-bound at roughly 30-60 seconds per case. Investigating thousands of cases is not feasible, and prioritizing by severity is exactly how a real audit team triages.

**Consequences.** Fixed claim wording: "Detects across 100% of transactions, then autonomously investigates prioritized cases." Never "investigates every flagged case." The dashboard must show flagged / investigated / queued explicitly. Triage accuracy is measured on a severity-biased sample, and the report says so.

---

## D-06 — The procurement policy is authored by the team

**Decision.** A representative procurement policy is written in `policy/`, with clauses derived from India's General Financial Rules 2017 and CVC procurement guidelines, optionally referencing the US FAR micro-purchase threshold for US datasets. Minimum clauses: approval thresholds by value; prohibition of splitting to avoid thresholds; duplicate payment prevention and recovery; vendor onboarding; price reasonableness.

**Rationale.** Public datasets do not ship with the issuing organization's internal policy document, and `policy_lookup` needs something real to retrieve over.

**Consequences.** The D2 threshold is a configuration value **and** appears as the same figure in the policy text, so the agent's citation and the detector's behaviour never disagree. The report carries the authored-policy caveat.

---

## D-07 — Minimal case state management is in scope

**Decision.** Per case: `New -> Under Review -> Confirmed -> Dismissed`, plus a free-text reviewer note, persisted in the operational database. Out of scope: login, auth, multi-user, retraining from feedback, email or ticket integration.

**Rationale.** A read-only dashboard is a report viewer; a queue you can act in is a tool. The cost is small and it makes the demonstrated workflow complete end to end.

---

## D-08 — Two severity numbers, named differently

**Decision.**

`detector_score` — float 0-1, produced by the detector, confidence only. Each detector normalizes its own statistic.

`severity` — float 0-100 plus a band, in two stages:
- Stage 1 at case creation: `severity_prelim = 100 * detector_score * amount_weight`, where `amount_weight = log1p(amount_at_risk) / log1p(reference_amount)`. This orders the investigation queue.
- Stage 2 after investigation: the agent may adjust the band — `likely_false_positive` drops to Low, `inconclusive` caps at Medium, `likely_true_positive` keeps the preliminary band.

Bands: High >= 66, Medium 33-65, Low < 33.

**Rationale.** The original contracts carried an unnamed `score` from detection and an unnamed `severity` from the agent, which read as two different things with no way to tell them apart.

**Consequences.** Both interface contracts use these names. See open issue O-03 on the choice of `reference_amount`.

---

## D-09 — Stack: React + FastAPI + PostgreSQL + DuckDB

**Decision.** Frontend in React with TypeScript. Backend entirely in FastAPI. Two data stores: DuckDB for analytics, PostgreSQL for operational state. No Django. No Node backend.

**Rationale.**

*Why not Node/Express:* two runtimes and two dependency systems. DuckDB is embedded, so a Node process cannot share a connection and every query would become an extra HTTP hop into Python. No benefit, and a hard question to answer in a viva.

*Why not Django:* two Python web frameworks doing one job. The Django ORM cannot address DuckDB, so it would force a second relational store purely for its own sake and split the data across engines. Its main value — admin, auth, migrations — is either out of scope here or already covered by Alembic.

*Why two stores:* DuckDB is columnar and single-writer. It is right for the aggregate scans detectors run and wrong for the small concurrent writes case-state management produces. The split follows the access pattern.

**Consequences.** The API opens DuckDB read-only, which removes write-lock contention between the dashboard and batch runs. Interface contracts become Pydantic models and are published as OpenAPI. SQLite substitutes for PostgreSQL through SQLAlchemy where a server is unavailable.

---

## D-10 — Heavy work runs in batch, not in requests

**Decision.** Detection and investigation run as CLI batch scripts that write results to storage. The API reads finished results and writes case state. The only exception is the bounded live-injection demonstration endpoint.

**Rationale.** Investigation takes 30-60 seconds per case. Nothing that slow belongs inside an HTTP request.

**Consequences.** The API stays thin — around ten endpoints. No job queue, no worker infrastructure, no websockets needed. Build order puts the pipeline, detectors and agents before the API, because the API is a wrapper over functions that must already exist.

---

## D-11 — The agent loop is hand-written

**Decision.** A plain Python while-loop, not an agent framework.

**Rationale.** Frameworks place hundreds of lines of abstraction between the team and the agent's actual behaviour. Every step here has to be explainable and debuggable under questioning. Migrating to a framework later is straightforward; starting with one costs understanding.

---

## D-12 — Vendor key is for blocking, not for identity

**Decision.** `vendor_key` is used to generate candidate matches cheaply. D1 applies a similarity check on the raw `vendor_name` before reporting two records as duplicates.

**Rationale.** Normalization is deliberately aggressive — suffixes stripped, tokens sorted — so genuinely different vendors sharing a stem can collapse to the same key. Treating the key as proof of identity would inflate D1's false positives.

**Measured (Phase 1, 50,000-row synthetic dataset, seed 42).** Against generator ground truth:

| | Result |
|---|---|
| Raw spellings → vendor keys | 2,063 → 382 |
| Suppliers split across more than one key (under-merging) | **0** |
| Keys merging two genuinely different suppliers (over-merging) | **10 of 382**, covering 2.2% of rows |

Every over-merge is the same shape: `Kaveri Traders` and `Kaveri Enterprises LLP` are distinct firms that both reduce to `kaveri`, because the spec strips "traders" and "enterprises" from the key. This is left in the synthetic data deliberately — real vendor masters contain exactly these pairs, and data without them would flatter D1.

**Refinements made during Phase 1**, beyond the CLAUDE.md suffix list:

- The Indian firm honorific `M/s` / `Messrs` is stripped as a prefix.
- `Co-operative` is kept as one token so the `co` stopword does not break it.
- Stopwords of five or more letters match within one keystroke (OSA distance, so an adjacent swap counts as one edit). Without this, `Private Limitd` produced a different blocking key from `Private Limited`, and a duplicate disguised with a suffix typo would never be compared. Short stopwords stay exact-only: one edit from `pvt` is `pvc`, a real trade word.
- `name_similarity` takes the better of plain ratio and token-sort ratio. Token-sort alone collapses when a typo hits a word's first letter — `raders` sorts before `sharma` while `traders` sorts after — scoring a one-letter typo at 44/100.

---

## D-13 — Citation validity is reported as two numbers

**Decision.** Hard citation validity (row exists, stated values match the row) is deterministic and is the headline number, target at least 95%. Semantic support rate (does the row support the claim) is model-judged and reported separately, labelled as such.

**Rationale.** A single blended number invites "so the model grades itself?" Splitting it makes the strong claim unassailable and the weaker claim honest.

---

## D-14 — Precision is reported raw and adjusted

**Decision.** Raw precision is measured strictly against injected ground truth. In addition, the top-k unlabeled flags per detector are manually reviewed and classified, and an adjusted precision is reported alongside, with the protocol and the value of k stated.

**Rationale.** Real data already contains genuine anomalies nobody injected. When a detector correctly finds one it scores as a false positive, so raw precision is systematically understated. Reporting only the raw number undersells the system; reporting only the adjusted number is unrigorous. Report both.

---

## D-15 — Reporting currency is Indian Rupees

**Decision.** The system reports in **INR (`₹`)**. `CURRENCY=INR` in configuration. The headline money-at-risk figure is quoted in rupees.

**Rationale.** The policy framework is anchored to Indian public-procurement rules (GFR 2017, CVC guidance), the panel context is Indian, and a single reporting currency keeps the headline figure unambiguous.

**Consequences.**

- The authored policy uses rupee thresholds throughout — see D-16.
- Where a source dataset is denominated in another currency, ingestion records the source currency in the dataset card and converts to INR at a **fixed, recorded rate pinned per dataset**, never a live rate. A live rate would make results irreproducible between runs.
- The dataset card and the report state the conversion rate and its date. Converted figures are labelled as converted.
- Any dataset shown in the final demonstration should preferably be rupee-denominated or clearly labelled as converted, so no figure on screen is ambiguous.

---

## D-16 — Approval threshold is ₹2,50,000

**Decision.** The principal control threshold — the figure D2 anchors to — is **₹2,50,000**. `APPROVAL_THRESHOLD=250000`.

**Rationale.** Under the GFR 2017 ladder, ₹2,50,000 is the point at which a purchase leaves the Local Purchase Committee route and enters formal competitive tendering. It is the most consequential band boundary in the ladder and therefore the one with the strongest incentive to split beneath. It is a real, defensible figure rather than an invented round number.

**Consequences.**

- The full ladder is stated in `policy/policy.md` clause SG-PP-2.1: ₹25,000 direct purchase · ₹2,50,000 committee ceiling · ₹25,00,000 limited tender ceiling.
- The policy's threshold summary table and the configuration values **must match exactly**. A mismatch means the agent cites a clause that contradicts the detector that flagged the case. This is checked by a test.
- D2's split window is 14 days (SG-PP-3.2), with 3 and 7 days as heightened-scrutiny windows (SG-PP-3.3).
- D1's amount tolerance of 0.5% and date window of 14 days are likewise stated in the policy at SG-PP-4.4, so D1 findings can cite policy as well.
- For a US-denominated dataset, a separate threshold profile applies the FAR micro-purchase threshold. Profiles are per-dataset configuration; the rupee profile is the default.

---

## D-17 — Injection harness design

**Decision.** The harness writes a **separate** database and never modifies the clean one. Within it:

- `rate` counts anomaly **groups**, not rows; the resulting row share (2.24% on the development dataset) is reported with every run.
- Every injected anomaly stays **inside the policy's own definition** of it — duplicate shifts and split windows ≤ 10 days against 14-day policy windows, with headroom for a weekend roll.
- A row belongs to **at most one** anomaly group.
- Split originals are **deleted**: the requirement is replaced by its parts, as in a real split.
- Inflation is capped at 5% of a category, and only placed in categories large enough to establish a norm.
- Synthetic fraud vendors are priced round but **within their category's normal range**, so each planted anomaly tests exactly one detector.
- Duplicates are disguised three ways — exact, legitimate spelling variant, typo — recorded per group, so D1's recall can later be broken down by disguise.

**Rationale.** Each choice removes a way the evaluation could be unfair in either direction: anomalies no detector could find, anomalies that trip the wrong detector, overlapping ground truth, or planted outliers dragging the norm they are measured against.

**Detector isolation.** Detectors read the `audit_transactions` view, which omits the answer-key columns and `source_row_ref` — injected rows have no source reference, so exposing that column would leak the answer through its absence. A test parses every detector module and fails on any string naming a hidden column or the raw table; it was verified by planting a leak and confirming the failure.

---

## D-18 — Rule baseline, and a correction to the synthetic data it exposed

**Decision.** The baseline is four fixed, binary rules (docs/EVALUATION.md 4.0): exact duplicate match, amount within 10% below the threshold, unit price above 2× the category mean, and supplier invoices mostly in round thousands.

**Finding.** Its first run scored **perfect precision on inflation**. That was a defect in the generator, not a strength of the rule: every commodity had a tight lognormal price spread, so no legitimate purchase ever reached 2× the category mean. Real categories are not like that — one "office chair" category holds economy and premium models, and emergency purchases carry a premium.

**Correction.** The generator now draws a specification tier per purchase (10% economy at 0.70–0.85×, 20% premium at 1.35–1.70×) and makes 2% of purchases urgent at a further 1.3–2.0×. Half of those rows say so in the description (`- Premium Grade`, `(Urgent Supply)`); half do not. Baseline inflation precision fell from 1.000 to **0.357**, with 175 false alarms on honest purchases.

**Why this matters beyond the number.** Leaving data this easy would have let D3 post near-perfect scores that a panel would rightly dismiss. The description markers also give the Investigator agent real evidence to cite when it dismisses a false alarm.

---

## D-19 — D1 blocks on amount and date, not vendor key (supersedes CLAUDE.md section 8)

**Decision.** D1 stage 2 generates candidate pairs from **amount within ±0.5% and dates within 14 days**, then requires `name_similarity` ≥ 80 to confirm supplier identity. CLAUDE.md specified blocking on exact `vendor_key` first. Approved by the user on 2026-09-11.

**Rationale.** A typo in the distinctive part of a name (`Shrama Traders`) changes `vendor_key`, so under exact-key blocking a disguised duplicate is never compared at all. That is a structural blind spot, not a tuning problem: 30% of injected duplicates are disguised with a typo. A duplicate keeps its amount by construction, so blocking on amount cannot miss it the same way.

**Tolerance, defined exactly.** Two amounts qualify when `|a − b| < 0.5% × max(a, b)` — the policy's "differing by less than 0.5%" (SG-PP-4.4), measured against the larger amount so the test is symmetric and never depends on which row comes first. An earlier inclusive, one-sided form let ₹10,000 vs ₹10,050 qualify or not depending on row order and floating-point rounding; boundary tests now pin every case.

**Implementation.** An equi-join on a logarithmic amount bucket of width −ln(1 − 0.005), joined against the bucket and its two neighbours, then the exact filter. Any qualifying pair has a log-ratio below one bucket width, so it lands in the same or an adjacent bucket. Verified **set-identical** to the brute-force join — 107,649 candidate pairs on the 50k dataset — in 0.04 s instead of 12.2 s. The brute-force join would take minutes on the 350k-row real dataset.

---

## D-20 — D1 match probability from a Fellegi–Sunter model fitted by EM

**Decision.** Candidate pairs that pass the identity check are scored by a Fellegi–Sunter probabilistic record-linkage model — the model Splink implements — fitted to the data by expectation–maximization. Each pair is compared field by field (name similarity, invoice number, amount, date gap, officer, item); EM learns how often each comparison level occurs among true duplicates (`m`) and among non-duplicates (`u`). The posterior match probability is the `detector_score`, as D-08 already specified.

**Rationale.**

- **Data-driven, not hand-weighted.** The weights are estimated from the data, which keeps the project's "no manual expert rules" constraint. Nobody chose that an invoice match is worth more than an officer match — EM did.
- **Explainable.** Every pair's score decomposes into per-field match weights, log₂(m/u). The Investigator can cite *why* two records were judged duplicates.
- **Splink stays optional.** Implementing the model directly avoids depending on a library that may not install on Python 3.13, and leaves nothing hidden from a viva question. Splink remains a drop-in comparison if wanted.

**Three corrections made while building it**, each found by testing and each recorded because a panel will ask how the model was validated:

1. **u from look-alikes too far apart to be duplicates.** Left free, EM found the largest cluster of look-alike pairs — a supplier repeatedly selling one officer the same item — and called *that* the duplicate class. The u-probabilities are therefore estimated from a reference set selected *exactly* as candidates are, but 30–180 days apart, so by the policy's definition none is a duplicate. The reference must mirror candidate selection precisely: an earlier version also required the same vendor key, excluded the similar-but-different names common among candidates, and EM built a spurious class out of those.
2. **Officer, item and amount compared jointly.** Among innocent look-alikes these agree *together*. Fellegi–Sunter assumes independence within each class, so as separate fields they counted one fact three times and outweighed the invoice evidence. As one joint "context" field, EM learned a different invoice number is strong evidence *against* (−14.95 bits) and a shared core number strong evidence *for* (+9.31).
3. **MAP-EM with priors.** Plain EM always finds two classes, even when one does not exist: on the clean dataset it put **94.5%** of pairs in the duplicate class and flagged **1,732** false duplicates. Real data has few duplicates, which is exactly that regime. The starting m-values are now a Dirichlet prior worth 50 pairs, and the duplicate rate a Beta(2, 38) prior centred on 5%. On clean data D1 now raises **0** cases and estimates a 0.1% duplicate rate; on injected data, results are unchanged.

**Result**, three seeds, mean ± sd: precision 1.000 ± 0.000, recall 0.903 ± 0.013, F1 0.949 ± 0.007 (baseline F1 0.354). The misses are almost entirely *re-keyed* duplicates — paid twice under unrelated references — which look identical to repeat business on every field a transaction carries. That is the honest limit of record linkage here, and a case the Investigator can resolve by reading both documents.

**Invoice evidence.** Two invoice numbers "match at the core" when they share a numeric group other than the transaction's year or financial-year parts: `INV-04471` and `4471/2026` match; `ST/24-25/045` and `ST/24-25/046` do not.

---

## D-21 — D2: minimal runs, four equally weighted indicators, threshold from a development seed

**Decision.** For each supplier and officer, D2 walks sub-threshold purchases in date order and takes the **shortest** runs that reach the ₹2,50,000 threshold within 14 days, trimmed from the front. Each run is scored on four indicators, **equally weighted** — the least-tuned choice: tightness of the window (SG-PP-3.3), share of the run that is the same item (SG-PP-3.4), share billed at **one identical unit rate**, and a 3–6 part shape. A run is raised only if it scores at least **0.85**.

**Why minimal runs.** An officer buying from one supplier every few days otherwise chains months of routine purchases into one sprawling "split" that buries the real one.

**Why the single-rate indicator.** A requirement divided into invoices is billed at one quoted rate; routine repeat purchasing is re-priced each time. On the development seed, 60% of real splits bill every part at an identical rate against 1% of routine runs. A second candidate — parts unusually large for their item — was examined and **rejected**: it separated the classes only because of how the harness chooses what to split, which would not transfer to real data.

**Why a threshold at all.** Every sub-threshold run crossing the limit is a candidate, and routine purchasing produces thousands: 3,735 alerts on the development seed at precision 0.03. No auditor reads that list.

**Protocol.** The threshold was chosen to maximize F1 on **seed 42 only**, fixed, and then reported on seeds **7 and 2026**, which played no part in any design decision. Development F1 0.726; held-out 0.709 and 0.735.

**Result**, three seeds: precision 0.828 ± 0.006, recall 0.643 ± 0.014, F1 0.724 ± 0.011, PR-AUC 0.583 (baseline F1 0.029, PR-AUC 0.002). On the clean dataset, 0 of 3,540 candidate runs clear the threshold.

---

## D-22 — Harness realism: re-keyed duplicates and fresh split invoice numbers

**Decision.** 10% of injected duplicates are recorded under an **unrelated** invoice reference (paid from a statement and from the invoice, or resubmitted). Split parts after the first take invoice numbers the supplier has **never issued**.

**Rationale.** Without re-keyed duplicates, every planted duplicate kept a matching reference, EM learned that a different reference never occurs in a duplicate, and D1 scored recall 0.995 on data easier than reality. It would silently miss those duplicates in production and the evaluation would never show it. The split fix removes an unrealistic artefact: bumped numbers were colliding with invoices already issued to other transactions — something no supplier does, and a spurious signal for any detector.

---

## D-23 — D3: robust z on controlled log price, and an honest negative result

**Decision.** D3 flags a line item when its unit price exceeds, by a robust z-score, the price expected for its category, order size and date. Log space, because prices vary multiplicatively. Median and MAD, because a mean and standard deviation are dragged up by the very inflation being hunted. Two controls fitted from the data — bulk discount and annual drift — and deliberately **no supplier control**, which would raise the bar for exactly the supplier under suspicion. Threshold picked to maximize F1 on dev seed 42 only.

**The item description is not a feature.** Half the legitimate premium purchases say "Premium Grade" or "Urgent Supply" in their description. Using that would mean trusting text written by the same party that set the price — a fraudster need only type the word. It is evidence for the Investigator, not an input to the detector.

**Negative result, reported rather than buried.** Five statistics were compared on the development seed — ratio to median, ratio to mean, robust z, IQR z, and controlled z. All landed within 0.02 F1 of each other and of the rule baseline. Across three seeds D3 finishes marginally **below** the baseline on F1 (**0.419 ± 0.007 vs 0.432 ± 0.004**) while clearly ahead on ranking (**PR-AUC 0.280 ± 0.008 vs 0.196 ± 0.003**, +43%).

The cause is structural, not a tuning failure: legitimate premium and urgent purchases occupy the same price band as the injected markups. 7,508 honest rows sit above 1.4× their category median; only 285 sit above 2.0×. A price statistic alone cannot separate them, and **this is the strongest argument in the project for the investigation layer** — the agent can read the description and the policy, which D3 refuses to trust.

**The Isolation Forest earns its place only as a recorded second opinion.** On its own it scores F1 0.07 — at the configured contamination it flags a percent or two of *every* row. It never raises a case; its agreement is recorded on each one, and the overlap is reported for the ablation table.

**On clean data** D3 raises 154 cases in 49,900 rows (0.3%) — the honest premium and urgent purchases, the same overlap in a different light.

---

## D-24 — D4: statistical tests against peers, combined by Fisher, FDR-controlled

**Decision.** Each vendor red flag is a **statistical test against the population's own behaviour**, not a fixed cut-off. Independent p-values are combined per supplier with **Fisher's method**, and significance across all suppliers is controlled with **Benjamini–Hochberg FDR** at 5% — with ~380 suppliers, testing each at 5% would produce about 19 false accusations by chance.

**Four guards, each added because its absence accused a real supplier:**

1. **Tests run on distinct amounts, not transactions.** A fixed monthly contract is one price decision repeated twelve times, not twelve independent observations. Without this, every legitimate security and housekeeping contract looked overwhelmingly "round".
2. **Expectations are conditional on what the supplier sells.** A consultancy quoting round figures is normal *for a consultancy*. Indirect standardization against the supplier's own category mix; a single global rate flagged every training and advisory firm.
3. **Significance is not enough — the effect must be material.** A supplier must also exceed twice its expected rate. With 400+ invoices a three-point deviation is highly significant and means nothing.
4. **Benford's law is not the null.** Procurement invoices are quantity times a near-fixed price and depart from Benford routinely: testing against the law directly accused **61 of 210** real suppliers. The null used is the **empirical digit distribution of the same categories**; conformity to Benford is still computed and reported as context for the auditor, with Nigrini's MAD criterion as the materiality gate.

**Result**, three seeds: precision **1.000 ± 0.000**, recall 0.750 ± 0.102, F1 **0.853 ± 0.067** against the baseline's 0.497 ± 0.061. Zero false positives on every seed and on clean data.

---

## D-25 — Harness realism: planted vendors vary in how obvious they are

**Decision.** Each synthetic fraud vendor draws its own round-number share (35–75%) and period-end share (30–60%), and the harness plants at least 4 (2% of suppliers) rather than 2.

**Rationale.** With a single fixed 80% round share, every planted vendor was blatant and D4 scored a perfect **F1 = 1.000 on all three seeds** — a number that says more about the test than the detector, and one a panel would rightly distrust. With difficulty varying, F1 falls to 0.853 and the misses are exactly the subtlest vendors (34% round, 32% period-end). More vendors also give recall finer resolution than 25% steps.

This is the same correction applied to duplicates in D-22, for the same reason: an evaluation that cannot fail measures nothing.

---

## D-26 — Development model: `qwen/qwen3.8-27b` on Groq

**Decision.** Groq for development, model **`qwen/qwen3.8-27b`**. Tool calling verified live before building on it.

**Why not the planned model.** Groq has retired `llama-3.3-70b-versatile`; the account's model list is now gpt-oss, Qwen 3.x and a few speech models. The plan in CLAUDE.md named a model that no longer exists, which is a reminder that a hosted model list is not a stable dependency — `spendguard check-llm` exists so this fails loudly and early rather than mid-investigation.

**Why Qwen over gpt-oss-120b.** Both answered and both called tools correctly (~0.4-0.6 s). The local target is **Qwen2.5-3B**, so prompts developed against a Qwen model are more likely to survive the port to Ollama. Prompt transfer matters more here than raw capability, because the fully-local run is the claim being defended.

---

## D-27 — Policy retrieval is dense embeddings, measured against the alternatives

**Decision.** Clause-boundary chunking of `policy/policy.md` (41 clauses), `bge-small-en-v1.5` embeddings, FAISS inner-product search over normalized vectors. Hybrid and lexical modes stay behind `search(mode=...)` for the ablation.

**Measured on 10 colloquial paraphrases**, none of which reuses its clause's wording:

| Retrieval | top-1 | top-3 |
|---|---:|---:|
| **dense only** | **5/10** | **7/10** |
| BM25 only | 2/10 | 3/10 |
| hybrid RRF (top 5) | 4/10 | 7/10 |
| hybrid RRF (full) | 3/10 | 7/10 |

Hybrid retrieval is the standard remedy when queries turn on exact terms, so it was built and tested rather than assumed. It never won: with 41 short clauses of formal prose against plain-language questions there is little lexical overlap for BM25 to exploit, so it mostly adds noise. The benchmark is small and hand-labelled — it is a regression guard, not a claim of general accuracy.

**Two implementation notes worth keeping.**

- **The cache key must cover the embedded text, not the policy file.** Keying on the file alone meant a change to how clauses are flattened left stale vectors in place and silently won; the first measurement after the change was identical to the one before it, which is how the bug surfaced. The key is now a hash of the exact strings that get embedded, plus the model name.
- **Markdown is flattened to prose before embedding.** Clause SG-PP-2.1 is mostly a table of value bands; as pipes and dashes it embedded poorly.

---

## D-28 — Tool safety: a read-only view, a validated statement, and errors as data

**Decision.** Every tool reads `audit_transactions` through a read-only connection. `query_transactions` additionally validates that the statement is a single `SELECT`/`WITH`, contains no write or attach keywords, and references no table but the audit view or its own CTEs. Results are capped at 50 rows and 8,000 characters.

**Rationale.** Three independent layers, because any one can be circumvented: the connection cannot write, the view does not contain the answer key or `source_row_ref`, and the validator refuses anything that is not a plain read — with a *legible reason*, so the model corrects itself instead of retrying blindly.

**Tools never raise into the agent loop.** A failure returns `{"error": ...}`. An exception would end an investigation that the model could have recovered from by fixing its own query; an error message is something it can read and act on.

---

## D-29 — The Investigator: structured claims, one example, the innocent explanation first

**Decision.** A hand-written loop (D-11) in `agent/investigator.py`: brief the model on the case, let it call the six tools for at most `AGENT_MAX_STEPS` turns, then parse and validate its JSON note. The note is structured: `verdict`, `finding`, a list of `claims` (each a sentence, the `row_ids` it rests on, and optional `facts` of the form `{row_id, field, value}`), `policy_clauses`, and `recommended_action`.

**Why structured claims rather than prose with inline citations.** A fact like `{"row_id": 2847, "field": "amount", "value": 87450}` can be checked deterministically against the audit view; the sentence needs a semantic check. That is the split D-13 reports, and it means the Verifier never has to parse citation markers out of free text. A fact may name only a field the audit view exposes, so the answer key cannot be asserted even by accident.

**Prompt choices, each for a reason:**

- **Only the example for the case's type is shown.** Four worked examples cost tokens on every turn, and a small model imitates whatever it sees.
- **Look for the innocent explanation first.** The detectors are tuned for recall, and D3 shares its price band with honest premium purchases (D-23). An investigator that only confirms flags adds nothing; the contribution is the one that can dismiss them (D-04).
- **Every figure through the calculator.** A number computed in the model's head is one the Verifier cannot trust.

**Recovering instead of failing.** A malformed note is sent back with the validation error, phrased for the model, up to twice. Out of steps, one last turn with `tool_choice="none"` asks for the note from the evidence already gathered. Qwen 3's `<think>` blocks and fenced code are stripped before parsing.

**Measured on the dev seed, top case of each type:** all four produced schema-valid notes with every claim cited and no citation of a row the agent had not seen. 4–10 tool calls and 15–25k prompt tokens per case. One wording slip seen: a duplicate note's recommended action said "duplicate payment", echoing the policy's "duplicate-payment register" despite the prompt's rule — a deterministic check for the Verifier.

---

## D-30 — Working inside a free tier: honour the wait, and budget the context

**Finding.** Groq's free tier allows roughly **8,000 input tokens per minute**, **1,000 requests per day** and — the binding one — **200,000 tokens per day** for every model on the account that can do this work (`qwen/qwen3.8-27b`, `gpt-oss-120b`, `gpt-oss-20b`; confirmed against Groq's published limits). An investigation resends the whole conversation every turn — 2–6k tokens a turn, 15–25k per case — so it hits the per-minute limit within two or three turns, and the daily cap after **about ten investigations**. The daily bucket refills at roughly 8,300 tokens an hour. Switching models does not help; they carry the same limits.

**Two fixes, both in code rather than configuration.**

1. **Wait as long as the server asks.** A 429 carries a `retry-after` header or a message like "try again in 27.9s". The first client retried after 1, 2 and 4 seconds and gave up, so every investigation failed. The client now sleeps for the requested time, counts those waits separately from real failures (up to six, each capped at 65 s, so an exhausted *daily* quota ends the run rather than hanging it), and reports total wait time.
2. **Keep every request under a token budget** (`AGENT_CONTEXT_TOKENS`, default 5,500). A long vendor investigation reached 7,753 tokens in one request and was refused outright (HTTP 413). Before each turn the conversation is estimated — characters per token calibrated from the token counts the API returns — and the **bulkiest earlier tool results** are replaced with a marker listing the row ids they contained. The system prompt, the case brief and the latest turn are never trimmed. If trimming is not enough, gathering stops and the note is written from what the model has. Trimming oldest-first was tried first; the model then re-requested the small vendor profile it had lost, so size decides now, not age.

Tool results are also cut **by whole rows** with a note saying how many were shown; cutting mid-JSON left the model unsure what it had missed, and it re-ran the same query.

3. **Stop on a spent daily quota; resume next run.** A 429 asking for a wait longer than 65 s is a daily quota, not a per-minute one, and raises `LLMQuotaExhaustedError`. The run stops at once instead of failing every remaining case, and says how many were not attempted. Operational runs resume naturally (unfinished cases stay uninvestigated). Evaluation runs draw the same seeded sample each time and skip cases that already have a note, so a sample accumulates across days; a case the quota cut short is never scored as an agent failure.

**Cost.** About 1–3 minutes per investigation on the free tier, much of it waiting, and **about ten investigations a day**. That is enough to develop and demonstrate on; it is **not** enough for the Phase 9 evaluation (hundreds of investigations across seeds and ablations), which needs a local model or a more generous free provider. The budget also matters locally: Ollama silently truncates past `num_ctx`, which is worse than a refusal.

---

## D-31 — The Verifier: mechanical checks first, a fresh-context judge second, revise in place

**Decision.** Every note is checked before release, in two parts reported as two numbers (D-13):

1. **Deterministic** (`agent/checks.py`, no model): every cited row exists in `audit_transactions`; every value a claim states about a row matches it; every cited policy clause exists in `policy.md`; the note never says "duplicate payment". The headline number.
2. **Semantic** (`agent/verifier.py`, one LLM call per draft): does the evidence support each claim? Labelled model-judged.

On any failure the objections go back to the Investigator, which revises, up to `VERIFIER_MAX_RETRIES`. The best draft is released with `verified`, `failed_after_retries` or `unverified`.

**Choices, each with its reason:**

- **A stated number matches if it is the row's value rounded to the precision the note used.** `259463` matches `259463.41`; `260000` does not. A tolerance band would pass a transposed digit on a large amount; exact equality would fail an honest whole-rupee figure. The prompt asks for exact values, so a figure rounded to the thousand is treated as a different figure. Text matches ignoring case and spacing, but invoice numbers are not normalized further: `INV-4471` against `INV-04471` is precisely the retyping that makes a duplicate, so it must not be smoothed away.
- **The judge gets a fresh context.** It never sees the Investigator's reasoning, only the claims, the rows they cite and the tool results the Investigator obtained (calculator first, then vendor profile, Benford statistics, comparable invoices; capped). Showing it the conversation would let it be persuaded instead of checking.
- **The judge rules on claims, not on rows one at a time.** "The four orders total ₹3,26,873" is supported by its rows together, not by any single row. Its verdict is applied to every citation of that claim.
- **Revision continues the Investigator's own conversation** rather than investigating again. The evidence is already there, so a fix costs one or two turns instead of 15–25k tokens, which matters when the day allows about ten investigations (D-30). The model may still call tools if an objection means it needs more evidence.
- **The best draft is released, not the last.** A revision that made things worse does not replace a better one.
- **`verified` requires both checks to have run.** If the judge could not answer (unparseable twice, or quota spent), a note with no mechanical failure is released `unverified`, never `verified`. Any known failure means `failed_after_retries`.
- **With the Verifier off** (`--no-verify`, the FR-7.8 ablation), nothing is enforced and nothing is regenerated, but the deterministic check still runs and is stored. The ablation's citation validity is measured by the same code as the main run.

**Caveat, stated rather than hidden.** The judge is the same model that wrote the note. That is why the semantic number is reported separately and labelled model-judged, and why the deterministic number, which involves no model, is the headline.

**First live run (2026-09-22), and two bugs it exposed.** On a split case, all 12 citations existed and matched (100% deterministic), but the judge rejected the claim "the supplier has no fixed monthly contract". The agent had the evidence: `vendor_profile` returned `looks_like_fixed_contract: false`. But the judge was shown each tool result cut at 700 characters, and that field sat at character 952. Tool results are now shrunk by whole list items with every scalar field kept (`fit_json`, shared with the Investigator). The same case also exposed a scoring bug: it was a *planted duplicate* that D2 had flagged as a split, so it touched no planted split and counted as "spurious". The agent called it genuine, which is right, and suggested checking for a duplicate record. A case now counts as spurious only if it touches no planted anomaly of any type.

**Measured so far.** Offline, a note planted with a wrong amount, a nonexistent row and an unsupported claim is caught on each count; sabotaging the value comparison makes four tests fail. Live, the real judge accepted a true claim about a row and rejected an invented one ("blacklisted in 2019") about the same row.

---

## D-32 — The API and dashboard: thin, contract-checked, one process in production

**Decision.** A FastAPI app (`spendguard serve`) over the two stores, and a React 18 + TypeScript + Vite + TanStack Query dashboard served by the same process once built. The API reads batch results and writes one thing, a reviewer's decision. It never runs a detector or the LLM inside a request (D-10).

**Choices, each with its reason:**

- **Store paths are fixed when the app is built**, not read from global settings per request. `spendguard serve --eval-seed 42` serves an evaluation run's stores (the injected database and its evaluation case store) under a banner saying they hold planted anomalies. Operational and evaluation data can never mix in one process.
- **The evaluation store holds every flagged case, not only the investigated sample.** It then shows what an auditor would see: 511 flagged, a handful investigated, the rest queued. The dashboard's coverage line ("flagged · investigated · queued") is honest about it.
- **Evidence is served from the audit view, through an explicit field list and a closed response schema.** Three layers, so breaking one does not leak the answer key. That was measured: pointing the evidence query at the raw table still leaked nothing; the leak test failed only when all three were broken.
- **The contract is checked twice, at compile time and at runtime.** TypeScript types are generated from the OpenAPI schema, never hand-written. Every response is parsed by a Zod schema declared `satisfies z.ZodType<GeneratedType>`. The first compile caught a real mismatch (Zod treats an `unknown` field as optional; the contract says it is required).
- **Money is a string end to end.** Pydantic serializes `Decimal` as a string, the validator rejects a float, and the dashboard formats the string with Indian grouping without converting it to a number. The rupees shown are exactly the rupees stored.
- **"Verified" depends on the status alone** (FR-6.9). A note whose citations all passed the mechanical check, but whose semantic check never ran, displays as unverified.
- **Filters live in the URL**, so a filtered queue can be linked, bookmarked and reached with the back button.
- **Health does not probe the LLM.** A dashboard polls health; a probe per poll would spend the free tier's daily request quota.

**Found by running it in a browser, not by the tests.** The evaluation table showed D1 for every anomaly type, at F1 0.000 for split purchases, because the report scores every detector against every type. The API now serves only the types a detector declares. A reviewer also could not clear a note: a blank note was sent as "no change", and an explicit empty one was stored as `""`, breaking the null rule. A blank note now clears to null.

---

## D-33 — Gemini for the evaluation runs; Ollama later; one line switches between them

**Decision (user, 2026-09-22).** Run the Phase 9 agent evaluation on **Gemini's free tier**. Groq allows about ten investigations a day, and the evaluation needs hundreds. Ollama is deferred: the dev machine has no disk space for it yet. It stays the path for the "fully local" claim.

**One line switches provider.** `LLM_PROVIDER=groq | gemini | ollama`. Each provider keeps its own key, endpoint and model (`GROQ_*`, `GEMINI_*`, `OLLAMA_*`); an explicit `LLM_*` value still overrides the active one. Before this, switching meant editing three lines and overwriting the other provider's key.

**Evaluation is per model.** A seed's evaluation store can hold notes by several models. A run's progress and its triage numbers count only notes by the model doing the run, so Groq and Gemini results never blend into one figure.

**Rate limits in Gemini's wording.** A 429 says "Please retry in 17.5s" or carries `retryDelay`, and both are read. A **per-day** quota (Gemini's `GenerateRequestsPerDay…`, Groq's `TPD`) ends the run for resumption rather than failing each remaining case, even when it hints at a short wait.

**Caveats, stated.**
- **Data use:** Gemini's free tier may use prompts to improve Google's products. Acceptable for the synthetic data and the public California dataset; never for an organization's confidential records. That is what the Ollama run is for.
- **Limits:** the free-tier limits are shown per account in AI Studio, not in public documentation. They are measured on first use, not assumed.
- **Model:** the default is `gemini-2.5-flash` (stable, described as best price-performance). Newer 3.x Flash models exist; `GEMINI_MODEL` changes it. Prompts were developed on Qwen (D-26), so the first Gemini runs are also a test of how well they transfer.

---

## Open issues

| ID | Issue | Status |
|---|---|---|
| ~~O-01~~ | ~~Reporting currency~~ | **Resolved — see D-15. INR.** |
| ~~O-02~~ | ~~Approval threshold figure~~ | **Resolved — see D-16. ₹2,50,000.** |
| **O-03** | **`reference_amount` in `amount_weight`.** Defining it as the maximum amount in the run makes severity non-comparable across runs — a single unusually large transaction rescales every other case, and the same case receives a different severity on a different subset. A fixed constant or a high percentile of the amount distribution would keep severity stable across the demo run, the evaluation run, and the ablations. | Recommend a fixed reference; awaiting decision |
| **O-04** | **`severity_final` semantics.** When the agent drops a false positive "to Low", does `severity_final` become an actual number below 33, or does only the band move while the number stays? Both fields exist in the contract; one line settles it. | **Implemented as recommended, awaiting confirmation:** the number moves with the band — `likely_false_positive` caps it just below 33, `inconclusive` just below 66, `likely_true_positive` keeps it. Sorting by severity and filtering by band then agree. One function (`final_severity`) to change if decided otherwise. |
| ~~O-06~~ | ~~D1 must not block on exact `vendor_key` alone~~ | **Resolved — see D-19. Approved by the user, 2026-09-11.** |
| **O-05** | **Item category source.** Where the dataset lacks a usable category, D3 needs pseudo-categories from description clustering. Whether this is in the core build or deferred is not yet fixed. | Undecided |
