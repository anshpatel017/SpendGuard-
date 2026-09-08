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

## Open issues

| ID | Issue | Status |
|---|---|---|
| ~~O-01~~ | ~~Reporting currency~~ | **Resolved — see D-15. INR.** |
| ~~O-02~~ | ~~Approval threshold figure~~ | **Resolved — see D-16. ₹2,50,000.** |
| **O-03** | **`reference_amount` in `amount_weight`.** Defining it as the maximum amount in the run makes severity non-comparable across runs — a single unusually large transaction rescales every other case, and the same case receives a different severity on a different subset. A fixed constant or a high percentile of the amount distribution would keep severity stable across the demo run, the evaluation run, and the ablations. | Recommend a fixed reference; awaiting decision |
| **O-04** | **`severity_final` semantics.** When the agent drops a false positive "to Low", does `severity_final` become an actual number below 33, or does only the band move while the number stays? Both fields exist in the contract; one line settles it. | Undecided |
| **O-05** | **Item category source.** Where the dataset lacks a usable category, D3 needs pseudo-categories from description clustering. Whether this is in the core build or deferred is not yet fixed. | Undecided |
