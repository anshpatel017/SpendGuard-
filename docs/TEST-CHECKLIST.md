# Test Checklist

Every item is a concrete, checkable statement. Requirement IDs in brackets refer to [REQUIREMENTS.md](REQUIREMENTS.md).

Legend: **[unit]** automated test · **[int]** integration test · **[man]** manual verification

---

## 1. Data pipeline

- [ ] **[unit]** `normalize_vendor` collapses known variants to one key — "Sharma Enterprises", "SHARMA ENTERPRISES PVT LTD", "Sharma  Enterprise" all produce the same key. [FR-1.5]
- [ ] **[unit]** `normalize_vendor` handles empty string, `None`, digits-only, and unicode names without raising. [FR-1.5]
- [ ] **[unit]** Vendor normalization is order-independent — token reordering produces the same key. [FR-1.5]
- [ ] **[unit]** Two genuinely different vendors sharing a stem are recorded as a known collision case, and the raw-name similarity check separates them. [FR-2.4]
- [ ] **[unit]** Column mapping is read from configuration; renaming a source column changes only the config, not the code. [FR-1.3]
- [ ] **[unit]** Malformed dates and non-numeric amounts are coerced or dropped, and the count is reported, not silently swallowed. [FR-1.4]
- [ ] **[int]** Ingesting the same CSV twice produces identical `row_id` assignments. [FR-1.2]
- [ ] **[int]** `row_id` is unique across the whole table. [FR-1.2]
- [ ] **[int]** A dataset missing `officer_id` ingests successfully and D2 degrades rather than crashing. [FR-1.6]
- [ ] **[int]** A dataset card is written with source, row count, date range, and per-column null rates. [FR-1.7]
- [ ] **[unit]** A non-INR dataset converts using the rate pinned in its configuration, and the rate and date appear in the dataset card. [FR-1.8]
- [ ] **[unit]** Ingestion makes no network call to fetch an exchange rate — verified, not assumed. [FR-1.8]
- [ ] **[int]** Re-ingesting a converted dataset produces identical amounts, proving the rate is pinned and not live. [FR-1.8] [NFR-4]
- [ ] **[man]** Spot-check twenty random rows against the source CSV for field-level correctness.

---

## 2. Detectors

### General

- [ ] **[unit]** Every detector implements the shared interface and returns the Case schema. [FR-2.2]
- [ ] **[unit]** Every `detector_score` falls in `[0, 1]`. [FR-2.9]
- [ ] **[unit]** Every case carries a non-empty `row_ids` list and every id exists in `transactions`. [FR-2.11]
- [ ] **[unit]** Every case carries `amount_at_risk` and a `severity_prelim` in `[0, 100]`. [FR-2.11]
- [ ] **[unit]** Running a detector twice on identical input with the same seed produces identical cases. [NFR-4]
- [ ] **[int]** An empty input table produces zero cases and no exception. [FR-2.2]
- [ ] **[int]** Detectors process the full table, not a sample — case row references span the full row_id range where anomalies exist. [FR-2.1]

### D1 duplicates

- [ ] **[unit]** Two identical rows are detected as one case with two row_ids. [FR-2.3]
- [ ] **[unit]** Same vendor variant spelling, same amount, dates two days apart, is detected. [FR-2.3]
- [ ] **[unit]** Same vendor, same amount, dates far outside the window, is not detected. [FR-2.3]
- [ ] **[unit]** Amounts just inside and just outside the tolerance behave correctly on both sides of the boundary. [FR-2.3]
- [ ] **[unit]** A legitimate recurring monthly payment from the same vendor is not reported as a duplicate. [FR-2.4]
- [ ] **[unit]** Three duplicates of one transaction form a single case with three row_ids, not three pairwise cases. [FR-2.2]

### D2 split purchases

- [ ] **[unit]** Five transactions each below threshold, same vendor and officer, inside the window, totalling above threshold, are detected. [FR-2.5]
- [ ] **[unit]** A group whose total is below threshold is not detected. [FR-2.5]
- [ ] **[unit]** A group containing one transaction already above threshold is not detected — that is not a split. [FR-2.5]
- [ ] **[unit]** Transactions spread outside the window are not grouped. [FR-2.5]
- [ ] **[unit]** Changing the configured threshold changes the results, proving it is not hardcoded. [FR-2.6]
- [ ] **[unit]** An automated check asserts `APPROVAL_THRESHOLD` equals the figure in the policy threshold summary, and fails on a deliberate mismatch. [FR-2.14]
- [ ] **[unit]** The same check covers the D1 amount tolerance, the D1 and D2 date windows, and the D4 new-vendor period. [FR-2.14]
- [ ] **[unit]** Amounts at exactly ₹2,50,000 are handled per the policy wording — "at or above" the threshold is not a split. [FR-2.5]

### D3 price inflation

- [ ] **[unit]** A unit price far above the category median is flagged. [FR-2.7]
- [ ] **[unit]** A category with very few rows does not produce spurious flags from an unstable median. [FR-2.7]
- [ ] **[unit]** MAD of zero (all identical prices) does not raise a division error. [FR-2.7]
- [ ] **[unit]** Isolation Forest runs with a fixed seed and produces reproducible scores. [NFR-4]
- [ ] **[unit]** Rows with null unit price or null category are excluded rather than crashing. [FR-1.6]

### D4 vendor red flags

- [ ] **[unit]** A synthesized vendor with round-number-heavy invoices scores highly on round-number ratio. [FR-2.8]
- [ ] **[unit]** A vendor with a natural first-digit distribution does not fail the Benford test. [FR-2.8]
- [ ] **[unit]** Vendors below a minimum transaction count are excluded from Benford testing. [FR-2.8]
- [ ] **[unit]** Period-end clustering is detected on a vendor with artificially month-end-concentrated dates. [FR-2.8]

### Baseline

- [ ] **[unit]** The baseline implements the same interface as the detectors. [FR-2.10]
- [ ] **[int]** The baseline runs over the same dataset and produces a comparable metrics table. [FR-2.10]

---

## 3. Injection harness

- [ ] **[unit]** Injecting with a fixed seed twice produces byte-identical output. [FR-7.1]
- [ ] **[unit]** Ground truth records anomaly groups with row ids and anomaly type. [FR-7.2]
- [ ] **[unit]** Injected duplicates carry realistic vendor-string perturbation and date shift, and preserve the amount. [FR-7.1]
- [ ] **[unit]** Injected splits replace one large transaction with several sub-threshold ones summing to the original. [FR-7.1]
- [ ] **[unit]** Injected inflation multiplies unit price within the specified range. [FR-7.1]
- [ ] **[unit]** The injection rate matches the configured rate within tolerance. [FR-7.1]
- [ ] **[int]** Injected rows are traceable back to their source rows for auditing the harness itself. [FR-7.2]
- [ ] **[man]** Per-category injection rate for D3 is capped, so injection does not materially shift the category median it is measured against.

---

## 4. Agent tools

- [ ] **[unit]** Every tool exposes a valid JSON schema. [FR-3.4]
- [ ] **[unit]** `query_transactions` rejects any statement that is not a read. [FR-3.3]
- [ ] **[unit]** `query_transactions` on a malformed query returns a structured error rather than raising. [FR-3.3]
- [ ] **[unit]** `query_transactions` caps returned rows so a broad query cannot flood the context window. [FR-3.3]
- [ ] **[unit]** `vendor_profile` on an unknown vendor returns an explicit empty result. [FR-3.3]
- [ ] **[unit]** `find_similar_invoices` on an invalid row_id returns an explicit error. [FR-3.3]
- [ ] **[unit]** `calculator` rejects anything that is not arithmetic. [FR-3.3]
- [ ] **[unit]** `benford_stats` on a vendor below the minimum transaction count returns a clear insufficient-data result. [FR-3.3]
- [ ] **[int]** `policy_lookup` returns the correct clause for a paraphrased query that shares no keywords with the clause text. [FR-3.10]
- [ ] **[int]** `policy_lookup` returns a clause identifier the agent can cite, not just raw text. [FR-3.10]

---

## 5. Investigator agent

- [ ] **[int]** Output parses and validates against the audit note JSON schema. [FR-3.1]
- [ ] **[int]** The loop terminates at the step bound and does not run unbounded. [FR-3.2]
- [ ] **[int]** Every claim in the note carries at least one citation. [FR-3.5]
- [ ] **[int]** Every cited row_id exists in `transactions`. [FR-3.5]
- [ ] **[int]** Exactly one verdict is emitted, from the allowed set. [FR-3.6]
- [ ] **[int]** A clean, obviously legitimate case yields `likely_false_positive` with a stated reason. [FR-3.6]
- [ ] **[int]** An obvious injected duplicate yields `likely_true_positive`. [FR-3.6]
- [ ] **[int]** The agent performs no writes to case state. [FR-3.7]
- [ ] **[int]** A trace is recorded with tool name, arguments, result, latency and token counts for every step. [FR-3.8]
- [ ] **[int]** Investigation runs on exactly the configured top-N cases, ordered by `severity_prelim`. [FR-3.9]
- [ ] **[int]** Switching the configured provider changes the endpoint used and nothing else. [FR-3.11]
- [ ] **[man]** Read ten generated notes end to end and confirm they are coherent, specific, and free of invented entities.

---

## 6. Verifier agent

- [ ] **[unit]** All cited row_ids are extracted from a note, including repeated and multi-id citations. [FR-4.1]
- [ ] **[unit]** A citation to a nonexistent row_id is caught. [FR-4.2]
- [ ] **[unit]** A note stating a wrong amount for a real row is caught by the deterministic check. [FR-4.3]
- [ ] **[unit]** A note citing a real row that does not support the claim is caught by the semantic check. [FR-4.4]
- [ ] **[int]** A failed note triggers regeneration, and the failure reason is passed back as context. [FR-4.5]
- [ ] **[int]** Regeneration stops at the retry limit. [FR-4.5]
- [ ] **[int]** A note that still fails is stored with an explicit unverified status. [FR-4.7]
- [ ] **[int]** `verification_status` and the passed-of-checked counts are persisted with the note. [FR-4.6]
- [ ] **[int]** Deterministic and semantic validity are recorded as two separate numbers. [FR-7.5]
- [ ] **[man]** Deliberately corrupt a note by hand and confirm the Verifier rejects it.

---

## 7. Database

- [ ] **[unit]** Case status transitions persist and survive a restart. [FR-5.3]
- [ ] **[unit]** Reviewer notes persist against the correct case. [FR-5.2]
- [ ] **[int]** Alembic migrations apply cleanly to an empty database. [NFR-10]
- [ ] **[int]** The API opens DuckDB read-only, so a batch run and the API can operate concurrently. [Architecture 2.4]
- [ ] **[int]** A batch run while the dashboard is open does not produce a lock error. [Architecture 2.4]

---

## 8. API

- [ ] **[int]** Every endpoint validates its response against its Pydantic model. [FR-5.9]
- [ ] **[int]** The OpenAPI schema is published and matches the implemented routes. [FR-5.9]
- [ ] **[int]** Case listing filters correctly by status, anomaly type, severity band, and verdict. [FR-5.5]
- [ ] **[int]** Case detail returns the note, its citations, the referenced evidence rows, and the trace. [FR-5.6]
- [ ] **[int]** A case that has not been investigated returns detector output with an explicit not-investigated marker, not a null-filled note. [FR-5.6]
- [ ] **[int]** Status update rejects an invalid transition target. [FR-5.1]
- [ ] **[int]** Metrics endpoint returns flagged, investigated and queued counts that sum consistently. [FR-5.7]
- [ ] **[int]** Requesting an unknown case id returns 404 with a structured error, not a stack trace. [NFR-10]
- [ ] **[int]** Evaluation endpoint returns detector-versus-baseline and ablation tables. [FR-5.8]

---

## 9. Frontend

- [ ] **[man]** Case queue sorts and filters correctly, and pagination works past the first page. [FR-6.2]
- [ ] **[man]** KPI cards show money at risk and the flagged / investigated / queued line. [FR-6.1]
- [ ] **[man]** Citations in the note are inspectable and resolve to the correct evidence rows. [FR-6.3]
- [ ] **[man]** Evidence table visually distinguishes the rows belonging to the case. [FR-6.4]
- [ ] **[man]** Verification badge shows passed of checked, and an unverified note is visibly marked as such. [FR-6.5] [FR-6.9]
- [ ] **[man]** Agent trace renders as an ordered timeline with arguments and results readable. [FR-6.6]
- [ ] **[man]** Status change and reviewer note save, and survive a page reload. [FR-6.7]
- [ ] **[man]** Metrics view renders the detector table and the ablation table. [FR-6.8]
- [ ] **[man]** Loading and error states render for every data-fetching view — no blank screens. [NFR-5]
- [ ] **[man]** A deliberate API shape change is caught by Zod validation with a visible error. [Architecture 2.6]
- [ ] **[man]** Layout holds at a projector resolution and does not scroll horizontally.
- [ ] **[man]** Every monetary value shows `₹` with Indian digit grouping, and converted figures are visibly marked as converted. [FR-6.10]

---

## 10. Evaluation

- [ ] **[int]** Per-case precision, recall, F1 and PR-AUC are produced per detector against the baseline. [FR-7.3]
- [ ] **[int]** Per-row metrics are produced as a secondary table. [FR-7.4]
- [ ] **[int]** The case-overlap matching rule is implemented exactly as specified and unit-tested at its boundaries. [FR-7.3]
- [ ] **[int]** D4 vendor-level cases are matched by the rule appropriate to vendor-level cases, not by row overlap. [Open issue]
- [ ] **[int]** Citation validity is reported split into deterministic and semantic. [FR-7.5]
- [ ] **[int]** Triage accuracy is computed only over investigated cases, and the report states that this sample is severity-biased. [FR-7.6]
- [ ] **[int]** Efficiency metrics — tool calls, tokens, latency — are recorded per case. [FR-7.7]
- [ ] **[int]** The Verifier-off ablation runs and produces a comparison table. [FR-7.8]
- [ ] **[int]** The template-notes ablation runs and produces a comparison table. [FR-7.9]
- [ ] **[int]** Every run is logged to the experiment tracker with its parameters, seeds and results. [FR-7.10]
- [ ] **[int]** Re-running an evaluation with the same seed reproduces the same numbers. [NFR-4]
- [ ] **[man]** Results are reported across multiple seeds with variation stated. [FR-7.11]
- [ ] **[man]** Top-k unlabeled flags are manually reviewed so precision can be reported raw and adjusted. [FR-7.12]

---

## 11. System and privacy

- [ ] **[int]** A full run against the local endpoint makes no external network calls — verified by monitoring, not assumed. [NFR-1] [NFR-3]
- [ ] **[int]** No API key for a paid provider is required for the delivered configuration. [NFR-1]
- [ ] **[man]** The model runs within available VRAM and the memory ceiling is recorded. [NFR-2]
- [ ] **[man]** Full detection over the development dataset completes within the target time, and the figure is recorded. [NFR-6]
- [ ] **[man]** No credentials, API keys or raw data are committed to version control. [DR-4]
- [ ] **[man]** A clean-machine setup from the documented commands succeeds. [NFR-10]

---

## 12. Pre-demonstration

- [ ] The demo dataset is frozen and version-pinned. [NFR-9] [DR-5]
- [ ] The demo runs from the frozen snapshot, not a live path that can change.
- [ ] Every screen in the demo sequence has been walked through at least three times end to end.
- [ ] A pre-computed run exists so nothing has to be generated live.
- [ ] The live injection demonstration completes within the time allowed, rehearsed with a stopwatch.
- [ ] The live injection demonstration catches exactly the injected anomalies, verified on a rehearsal run.
- [ ] A recorded video fallback exists and has been played back in full.
- [ ] The machine is tested on the actual projector and resolution.
- [ ] The system starts from cold — model loaded, database up, API up, frontend up — within the setup time available.
- [ ] Every number quoted in the presentation traces to a logged run.
- [ ] Wording checks: "duplicate transaction records", never "duplicate payments" for purchase-order data. "Detects across 100% of transactions, then autonomously investigates prioritized cases", never "investigates every flagged case".
- [ ] The limitations section states the invoice-to-payment reconciliation gap, the authored-policy caveat, and the severity-biased triage sample.
