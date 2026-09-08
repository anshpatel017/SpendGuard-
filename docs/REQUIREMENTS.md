# Requirements

Requirements are numbered so tests and the test checklist can reference them directly.

Priority: **MUST** = core, blocks delivery · **SHOULD** = strongly wanted · **MAY** = stretch.

---

## 1. Functional requirements

### 1.1 Data ingestion and preparation

| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | The system SHALL ingest procurement transaction data from CSV into a DuckDB `transactions` table. | MUST |
| FR-1.2 | Every ingested row SHALL be assigned a stable, unique `row_id` that persists across runs and is the identifier the agent cites. | MUST |
| FR-1.3 | The system SHALL map source-specific column names onto the canonical schema through a per-dataset mapping configuration, not hardcoded column names. | MUST |
| FR-1.4 | The system SHALL clean and coerce types — dates parsed, amounts numeric, nulls explicit — and record how many rows were dropped or coerced. | MUST |
| FR-1.5 | The system SHALL derive a normalized `vendor_key` from the raw vendor name by lowercasing, removing punctuation, stripping legal suffixes, and token-sorting. | MUST |
| FR-1.6 | Fields absent from a given dataset (for example `officer_id`, `invoice_no`) SHALL be nullable, and detectors that depend on them SHALL degrade gracefully rather than fail. | MUST |
| FR-1.7 | Ingestion SHALL emit a dataset card recording source, row count, date range, null rates per column, and applied mapping. | SHOULD |

### 1.2 Detection

| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | Detectors SHALL run over 100% of rows in the `transactions` table. No sampling at the detection layer. | MUST |
| FR-2.2 | Every detector SHALL expose the same interface and SHALL emit cases in the common Case schema. | MUST |
| FR-2.3 | **D1** SHALL detect duplicate transaction records via exact matching on `(vendor_key, amount, invoice_no)` followed by fuzzy matching blocked on `vendor_key`, amount within a tolerance, and a date window. | MUST |
| FR-2.4 | D1 SHALL apply a secondary similarity check on the raw vendor name before two records are reported as duplicates. | MUST |
| FR-2.5 | **D2** SHALL detect split purchases by grouping on `(vendor_key, officer_id)` within rolling windows and flagging groups where every individual transaction is below the approval threshold but the group total meets or exceeds it. | MUST |
| FR-2.6 | The D2 approval threshold SHALL be a configuration value, and the same figure SHALL appear in the procurement policy document. | MUST |
| FR-2.7 | **D3** SHALL detect price inflation per item category using a robust statistic (median and MAD) on unit price, and SHALL additionally run Isolation Forest on engineered features as an independent second opinion. | MUST |
| FR-2.8 | **D4** SHALL score vendors on first-digit distribution deviation (chi-square against Benford expectation), round-number amount ratio, and period-end temporal clustering. | MUST |
| FR-2.9 | Each detector SHALL emit a `detector_score` in the range 0-1, normalized from its own internal statistic. | MUST |
| FR-2.10 | A rule-based baseline detector SHALL exist and SHALL be runnable over the same data for comparison. | MUST |
| FR-2.11 | Each case SHALL carry `amount_at_risk` and a `severity_prelim` computed as specified in the design document. | MUST |
| FR-2.12 | D1 SHOULD support probabilistic record linkage (Splink) as an optional third stage. This is an upgrade, not a dependency. | SHOULD |
| FR-2.13 | Where item categories are absent, D3 MAY cluster item descriptions with embeddings to form pseudo-categories. | MAY |

### 1.3 Investigation agent

| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | The Investigator Agent SHALL accept a case and produce a structured audit note conforming to a strict JSON schema. | MUST |
| FR-3.2 | The agent SHALL operate as a bounded tool-calling loop with a configurable maximum step count. | MUST |
| FR-3.3 | The agent SHALL have access to at minimum these tools: `query_transactions`, `vendor_profile`, `find_similar_invoices`, `policy_lookup`, `benford_stats`, `calculator`. | MUST |
| FR-3.4 | Every tool SHALL expose a JSON schema describing its parameters to the model. | MUST |
| FR-3.5 | Every factual claim in an audit note SHALL cite one or more `row_id` values. | MUST |
| FR-3.6 | The agent SHALL emit exactly one verdict per case: `likely_true_positive`, `likely_false_positive`, or `inconclusive`. | MUST |
| FR-3.7 | The agent SHALL NOT delete, close, or otherwise mutate case state. It recommends only. | MUST |
| FR-3.8 | Every agent step — tool name, arguments, result, latency, token counts — SHALL be logged as a trace attached to the case. | MUST |
| FR-3.9 | Investigation SHALL run on the top-N cases by `severity_prelim`, with N configurable. | MUST |
| FR-3.10 | `policy_lookup` SHALL perform semantic retrieval over the procurement policy document and return the retrieved clause text with its identifier. | MUST |
| FR-3.11 | The agent SHALL be able to run against any OpenAI-compatible endpoint, switched by configuration, with a local endpoint as the default for the delivered system. | MUST |

### 1.4 Verification agent

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | The Verifier SHALL extract every cited `row_id` from a draft audit note. | MUST |
| FR-4.2 | The Verifier SHALL re-fetch each cited row from the database and confirm the row exists. | MUST |
| FR-4.3 | The Verifier SHALL check that the values stated about a cited row match the row's actual field values (deterministic check). | MUST |
| FR-4.4 | The Verifier SHALL check that the cited row supports the claim made about it (semantic check). | MUST |
| FR-4.5 | On failure, the Verifier SHALL reject the note and trigger regeneration, up to a configurable retry limit. | MUST |
| FR-4.6 | Each released note SHALL carry a `verification_status` and the count of citations checked and passed. | MUST |
| FR-4.7 | Notes that still fail after the retry limit SHALL be released with an explicit "unverified" status, never silently. | MUST |

### 1.5 Case management and API

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | Every case SHALL have a status in `New`, `Under Review`, `Confirmed`, `Dismissed`. | MUST |
| FR-5.2 | A reviewer SHALL be able to change a case status and attach a free-text note. | MUST |
| FR-5.3 | Case status and reviewer notes SHALL be persisted in the operational database. | MUST |
| FR-5.4 | Cases dismissed on the agent's recommendation SHALL remain visible under a dedicated filter. | MUST |
| FR-5.5 | The API SHALL expose case listing with filtering by status, anomaly type, severity band, and verdict. | MUST |
| FR-5.6 | The API SHALL expose case detail including the audit note, its citations, the referenced evidence rows, and the agent trace. | MUST |
| FR-5.7 | The API SHALL expose aggregate metrics: total transactions, cases flagged, cases investigated, cases queued, money at risk, breakdown by anomaly type. | MUST |
| FR-5.8 | The API SHALL expose evaluation results: per-detector metrics against baseline, and ablation results. | MUST |
| FR-5.9 | All request and response bodies SHALL be defined as Pydantic models, and the API SHALL publish an OpenAPI schema. | MUST |
| FR-5.10 | The API SHALL expose an endpoint that runs a small live injection demonstration on a bounded dataset. | SHOULD |

### 1.6 Dashboard

| ID | Requirement | Priority |
|---|---|---|
| FR-6.1 | The dashboard SHALL show KPI cards including money at risk and the honest coverage line (flagged / investigated / queued). | MUST |
| FR-6.2 | The dashboard SHALL present a sortable, filterable case queue. | MUST |
| FR-6.3 | Case detail SHALL render the audit note with citations displayed as inspectable references to evidence rows. | MUST |
| FR-6.4 | Case detail SHALL render the evidence rows in a table, with the rows in the case visually distinguished. | MUST |
| FR-6.5 | Case detail SHALL display the verification badge showing citations passed out of citations checked. | MUST |
| FR-6.6 | Case detail SHALL render the agent trace as a step-by-step timeline. | MUST |
| FR-6.7 | The dashboard SHALL allow status changes and reviewer notes from the case detail view. | MUST |
| FR-6.8 | A metrics view SHALL display the detector comparison table and the ablation table. | MUST |
| FR-6.9 | The dashboard SHALL never present an unverified note as verified. | MUST |

### 1.7 Evaluation

| ID | Requirement | Priority |
|---|---|---|
| FR-7.1 | An injection harness SHALL inject duplicate, split, inflation, and vendor-flag anomalies into real data with fixed random seeds. | MUST |
| FR-7.2 | The harness SHALL record ground truth as anomaly groups with the injected row ids and anomaly type. | MUST |
| FR-7.3 | The evaluation harness SHALL report precision, recall, F1 and PR-AUC per detector, per case, against the rule-based baseline. | MUST |
| FR-7.4 | The evaluation harness SHALL additionally report per-row precision and recall as a secondary table. | MUST |
| FR-7.5 | The harness SHALL report citation validity, split into a deterministic check and a semantic check. | MUST |
| FR-7.6 | The harness SHALL report triage accuracy — agent verdict against injection ground truth, over investigated cases only. | MUST |
| FR-7.7 | The harness SHALL report efficiency metrics per case: tool calls, tokens, wall-clock latency. | MUST |
| FR-7.8 | The system SHALL support an ablation with the Verifier disabled. | MUST |
| FR-7.9 | The system SHALL support an ablation replacing the agent with template-generated notes. | MUST |
| FR-7.10 | Every evaluation run SHALL be logged with its parameters, seeds, and results to a local experiment tracker. | MUST |
| FR-7.11 | Results SHOULD be reported across multiple seeds with variation stated. | SHOULD |
| FR-7.12 | The harness SHOULD support manual review of top-k unlabeled flags so that precision can be reported both raw and adjusted. | SHOULD |

---

## 2. Non-functional requirements

| ID | Requirement | Priority |
|---|---|---|
| NFR-1 | The runtime system SHALL NOT depend on any paid or external API. All inference SHALL be servable locally. | MUST |
| NFR-2 | The LLM SHALL fit in 16 GB of VRAM in quantized form. | MUST |
| NFR-3 | No transaction data SHALL leave the deployment during a runtime run. | MUST |
| NFR-4 | Every stochastic component SHALL accept and honour a random seed; a repeated run with the same seed and inputs SHALL produce the same detector output. | MUST |
| NFR-5 | Dashboard interactions SHALL respond within roughly two seconds on the demo dataset. | SHOULD |
| NFR-6 | Detection over the development dataset SHALL complete within a few minutes on commodity hardware. | SHOULD |
| NFR-7 | All configuration — thresholds, model name, provider, paths, N — SHALL live in one typed configuration module loaded from environment. | MUST |
| NFR-8 | Public functions SHALL carry type hints; the codebase SHALL pass lint and type checks in CI. | SHOULD |
| NFR-9 | The demo SHALL run against a frozen dataset snapshot, not a live code path that can change. | MUST |
| NFR-10 | The system SHALL be startable from a documented sequence of commands on a clean machine. | MUST |

---

## 3. Data requirements

| ID | Requirement |
|---|---|
| DR-1 | The canonical `transactions` schema is defined in [DATA-SCHEMA.md](DATA-SCHEMA.md) and is the contract between ingestion and every detector. |
| DR-2 | The primary development dataset is a real public procurement dataset with item-level unit prices. |
| DR-3 | A semi-synthetic generator SHALL exist as a guaranteed fallback and SHALL share machinery with the injection harness. |
| DR-4 | Raw data SHALL NOT be committed to version control. |
| DR-5 | A frozen demo snapshot SHALL be produced and version-pinned before the final demonstration. |

---

## 4. Acceptance criteria

The system is complete when all of the following hold:

1. Ingestion produces a populated `transactions` table with stable `row_id`s and a dataset card.
2. All four detectors run over the full dataset and emit cases in the common schema.
3. The rule-based baseline runs over the same data and produces a comparable metrics table.
4. The injection harness produces reproducible ground truth from a fixed seed.
5. Per-detector precision, recall, F1 and PR-AUC are reported against the baseline, per case and per row.
6. The Investigator produces schema-valid, cited audit notes for the top-N cases with full traces logged.
7. The Verifier checks every citation and rejects and regenerates failures; deterministic citation validity meets the stated target.
8. Both ablations run and produce comparison tables.
9. The API serves the case queue, case detail, metrics and evaluation endpoints with a published OpenAPI schema.
10. The dashboard supports the full workflow: browse queue, open case, read cited note, inspect evidence, view trace, change status, add note, view metrics.
11. The whole pipeline runs against a local model endpoint with no external calls.
12. A frozen demo dataset and a recorded fallback demonstration exist.

---

## 5. Open items

| Item | Status |
|---|---|
| ~~Reporting currency~~ | **Resolved — INR (`₹`). See D-15.** |
| ~~Approval threshold figure~~ | **Resolved — ₹2,50,000. See D-16 and `policy/policy.md` SG-PP-2.2.** |
| Reference amount used in `amount_weight` (fixed constant vs percentile vs run maximum) | Open — see [DECISIONS.md](DECISIONS.md) O-03 |
| `severity_final` semantics when the agent drops a case to Low | Open — see [DECISIONS.md](DECISIONS.md) O-04 |
| Whether D3 pseudo-categories from description clustering are core or deferred | Open — see [DECISIONS.md](DECISIONS.md) O-05 |

### Requirements added by the currency and threshold decisions

| ID | Requirement | Priority |
|---|---|---|
| FR-1.8 | Where a source dataset is denominated in a currency other than INR, ingestion SHALL convert amounts using a fixed rate pinned in the dataset configuration, SHALL record that rate and its date in the dataset card, and SHALL NOT call a live rate service. | MUST |
| FR-2.14 | An automated check SHALL assert that the approval threshold in configuration equals the figure stated in the policy document's threshold summary, and SHALL fail the build if they diverge. | MUST |
| FR-6.10 | All monetary values displayed SHALL carry the `₹` symbol, SHALL use Indian digit grouping, and SHALL be visibly marked where they were converted from another currency. | MUST |
