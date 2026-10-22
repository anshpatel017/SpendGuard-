# Test Checklist

Every item is a concrete, checkable statement. Requirement IDs in brackets refer to [REQUIREMENTS.md](REQUIREMENTS.md).

Legend: **[unit]** automated test · **[int]** integration test · **[man]** manual verification

---

## 1. Data pipeline

- [x] **[unit]** `normalize_vendor` collapses known variants to one key — "Sharma Enterprises", "SHARMA ENTERPRISES PVT LTD", "Sharma  Enterprise" all produce the same key. [FR-1.5]
- [x] **[unit]** `normalize_vendor` handles empty string, `None`, digits-only, and unicode names without raising. [FR-1.5]
- [x] **[unit]** Vendor normalization is order-independent — token reordering produces the same key. [FR-1.5]
- [x] **[unit]** Two genuinely different vendors sharing a stem are recorded as a known collision case, and the raw-name similarity check separates them. [FR-2.4]
- [x] **[unit]** Column mapping is read from configuration; renaming a source column changes only the config, not the code. [FR-1.3]
- [x] **[unit]** Malformed dates and non-numeric amounts are coerced or dropped, and the count is reported, not silently swallowed. [FR-1.4]
- [x] **[int]** Ingesting the same CSV twice produces identical `row_id` assignments. [FR-1.2]
- [x] **[int]** `row_id` is unique across the whole table. [FR-1.2]
- [x] **[int]** A dataset missing `officer_id` ingests successfully and D2 degrades rather than crashing. [FR-1.6] 
- [x] **[int]** A dataset card is written with source, row count, date range, and per-column null rates. [FR-1.7]
- [x] **[unit]** A non-INR dataset converts using the rate pinned in its configuration, and the rate and date appear in the dataset card. [FR-1.8]
- [x] **[unit]** Ingestion makes no network call to fetch an exchange rate — verified, not assumed. [FR-1.8] *(2026-10-22: the California CSV ingested twice with `socket.socket.connect`, `socket.create_connection` and `socket.getaddrinfo` all raising. Both runs completed. The rate is `fx_rate_to_inr: 60.0` dated 2014-01-01, read from `backend/mappings/california_po.yaml`; no HTTP client is imported anywhere under `pipeline/` or `db/`.)*
- [x] **[int]** Re-ingesting a converted dataset produces identical amounts, proving the rate is pinned and not live. [FR-1.8] [NFR-4] *(2026-10-22, two independent ingests into fresh databases: 336,995 rows each, sum 9,084,722,252,210.89, min 0.6, max 440,222,283,840.0 — identical. A live rate would have moved between runs.)*
- [x] **[man]** Spot-check twenty random rows against the source CSV for field-level correctness. *(2026-10-22, twenty rows drawn with a fixed seed from the California database and traced back to the source: 160 field comparisons across vendor, date, department, description, category, quantity, unit price and amount, the money fields checked through the pinned 60.0 rate rather than taken on faith. Eighteen rows matched line for line. The other two looked wrong and were not — `source_row_ref` is the purchase order number, not a line number, so a PO with many line items let the comparison land on the wrong line. Checked at PO level instead: `4500186243` has 9 CSV lines and 9 ingested rows, `14-G0035` has 49 and 49, and both unit-price sets — 41 distinct values for the second — are identical between source and database.)*

---

## 2. Detectors

### General

- [x] **[unit]** Every detector implements the shared interface and returns the Case schema. [FR-2.2]
- [x] **[unit]** Every `detector_score` falls in `[0, 1]`. [FR-2.9]
- [x] **[unit]** Every case carries a non-empty `row_ids` list and every id exists in `transactions`. [FR-2.11]
- [x] **[unit]** Every case carries `amount_at_risk` and a `severity_prelim` in `[0, 100]`. [FR-2.11]
- [x] **[unit]** Running a detector twice on identical input with the same seed produces identical cases. [NFR-4]
- [x] **[int]** An empty input table produces zero cases and no exception. [FR-2.2]
- [x] **[int]** Detectors process the full table, not a sample — case row references span the full row_id range where anomalies exist. [FR-2.1]

### D1 duplicates

- [x] **[unit]** Two identical rows are detected as one case with two row_ids. [FR-2.3]
- [x] **[unit]** Same vendor variant spelling, same amount, dates two days apart, is detected. [FR-2.3]
- [x] **[unit]** Same vendor, same amount, dates far outside the window, is not detected. [FR-2.3]
- [x] **[unit]** Amounts just inside and just outside the tolerance behave correctly on both sides of the boundary. [FR-2.3]
- [x] **[unit]** A legitimate recurring monthly payment from the same vendor is not reported as a duplicate. [FR-2.4]
- [x] **[unit]** Three duplicates of one transaction form a single case with three row_ids, not three pairwise cases. [FR-2.2]

### D2 split purchases

- [x] **[unit]** Five transactions each below threshold, same vendor and officer, inside the window, totalling above threshold, are detected. [FR-2.5]
- [x] **[unit]** A group whose total is below threshold is not detected. [FR-2.5]
- [x] **[unit]** A group containing one transaction already above threshold is not detected — that is not a split. [FR-2.5]
- [x] **[unit]** Transactions spread outside the window are not grouped. [FR-2.5]
- [x] **[unit]** Changing the configured threshold changes the results, proving it is not hardcoded. [FR-2.6]
- [x] **[unit]** An automated check asserts `APPROVAL_THRESHOLD` equals the figure in the policy threshold summary, and fails on a deliberate mismatch. [FR-2.14]
- [x] **[unit]** The same check covers the D1 amount tolerance, the D1 and D2 date windows, and the D4 new-vendor period. [FR-2.14]
- [x] **[unit]** Amounts at exactly ₹2,50,000 are handled per the policy wording — "at or above" the threshold is not a split. [FR-2.5]

### D3 price inflation

- [x] **[unit]** A unit price far above the category median is flagged. [FR-2.7]
- [x] **[unit]** A category with very few rows does not produce spurious flags from an unstable median. [FR-2.7]
- [x] **[unit]** MAD of zero (all identical prices) does not raise a division error. [FR-2.7]
- [x] **[unit]** Isolation Forest runs with a fixed seed and produces reproducible scores. [NFR-4]
- [x] **[unit]** Rows with null unit price or null category are excluded rather than crashing. [FR-1.6]

### D4 vendor red flags

- [x] **[unit]** A synthesized vendor with round-number-heavy invoices scores highly on round-number ratio. [FR-2.8]
- [x] **[unit]** A vendor with a natural first-digit distribution does not fail the Benford test. [FR-2.8]
- [x] **[unit]** Vendors below a minimum transaction count are excluded from Benford testing. [FR-2.8]
- [x] **[unit]** Period-end clustering is detected on a vendor with artificially month-end-concentrated dates. [FR-2.8]

### Baseline

- [x] **[unit]** The baseline implements the same interface as the detectors. [FR-2.10]
- [x] **[int]** The baseline runs over the same dataset and produces a comparable metrics table. [FR-2.10]

---

## 3. Injection harness

- [x] **[unit]** Injecting with a fixed seed twice produces byte-identical output. [FR-7.1]
- [x] **[unit]** Ground truth records anomaly groups with row ids and anomaly type. [FR-7.2]
- [x] **[unit]** Injected duplicates carry realistic vendor-string perturbation and date shift, and preserve the amount. [FR-7.1]
- [x] **[unit]** Injected splits replace one large transaction with several sub-threshold ones summing to the original. [FR-7.1]
- [x] **[unit]** Injected inflation multiplies unit price within the specified range. [FR-7.1]
- [x] **[unit]** The injection rate matches the configured rate within tolerance. [FR-7.1]
- [x] **[int]** Injected rows are traceable back to their source rows for auditing the harness itself. [FR-7.2]
- [x] **[man]** Per-category injection rate for D3 is capped, so injection does not materially shift the category median it is measured against.

---

## 4. Agent tools

- [x] **[unit]** Every tool exposes a valid JSON schema. [FR-3.4]
- [x] **[unit]** `query_transactions` rejects any statement that is not a read. [FR-3.3]
- [x] **[unit]** `query_transactions` on a malformed query returns a structured error rather than raising. [FR-3.3]
- [x] **[unit]** `query_transactions` caps returned rows so a broad query cannot flood the context window. [FR-3.3]
- [x] **[unit]** `vendor_profile` on an unknown vendor returns an explicit empty result. [FR-3.3]
- [x] **[unit]** `find_similar_invoices` on an invalid row_id returns an explicit error. [FR-3.3]
- [x] **[unit]** `calculator` rejects anything that is not arithmetic. [FR-3.3]
- [x] **[unit]** `benford_stats` on a vendor below the minimum transaction count returns a clear insufficient-data result. [FR-3.3]
- [x] **[int]** `policy_lookup` returns the correct clause for a paraphrased query that shares no keywords with the clause text. [FR-3.10]
- [x] **[int]** `policy_lookup` returns a clause identifier the agent can cite, not just raw text. [FR-3.10]

---

## 5. Investigator agent

- [x] **[int]** Output parses and validates against the audit note JSON schema. [FR-3.1]
- [x] **[int]** The loop terminates at the step bound and does not run unbounded. [FR-3.2]
- [x] **[int]** Every claim in the note carries at least one citation. [FR-3.5]
- [x] **[int]** Every cited row_id exists in `transactions`. [FR-3.5] *(Enforced by the Verifier's deterministic check, Phase 7.)*
- [x] **[int]** Exactly one verdict is emitted, from the allowed set. [FR-3.6]
- [x] **[int]** A clean, obviously legitimate case yields `likely_false_positive` with a stated reason. [FR-3.6] *(3 of 17 seed-42 notes are dismissals, each reasoning from the data rather than the label: `fe2c704f` — petrol at 3.3× the median, but comparable premium-grade purchases cost as much or more; `dd3f8ece` — 2.93× the median, but the same supplier's own premium purchases run 1.39–1.9× and five same-commodity rows sit within 1.01–1.16×; `72c2ddfc` — 2.66×, premium grade corroborated by comparables.)*
- [x] **[int]** An obvious injected duplicate yields `likely_true_positive`. [FR-3.6] *(all five duplicate cases investigated on seed 42 returned `likely_true_positive`, two of them `verified`. `b113c2e3` is the clearest: same supplier under a variant spelling, identical amount, officer, item and quantity, the invoice retyped from BILL/0539 to 539, ten days apart — and it rules out the innocent explanation, noting the supplier's only recurring billing is a different item.)*
- [x] **[int]** The agent performs no writes to case state. [FR-3.7]
- [x] **[int]** A trace is recorded with tool name, arguments, result, latency and token counts for every step. [FR-3.8]
- [x] **[int]** Investigation runs on exactly the configured top-N cases, ordered by `severity_prelim`. [FR-3.9]
- [x] **[int]** Switching the configured provider changes the endpoint used and nothing else. [FR-3.11]
- [x] **[man]** Read ten generated notes end to end and confirm they are coherent, specific, and free of invented entities. *(2026-10-22, the ten most recent seed-42 agent notes. Coherent: each runs from grounded observations to a verdict. Specific: real row ids, amounts, unit rates, dates and clause numbers throughout, with comparisons to the vendor's own history rather than generic prose. **Entities checked against the database rather than taken on impression** — all six suppliers and five officers named in prose exist, and `Deccan Goyal Solutions` has exactly the 46 transactions its note claims. Several notes consider and reject an innocent explanation before concluding, which is what D-29's prompt asks for.)*

---

## 6. Verifier agent

- [x] **[unit]** All cited row_ids are extracted from a note, including repeated and multi-id citations. [FR-4.1]
- [x] **[unit]** A citation to a nonexistent row_id is caught. [FR-4.2]
- [x] **[unit]** A note stating a wrong amount for a real row is caught by the deterministic check. [FR-4.3]
- [x] **[unit]** A note citing a real row that does not support the claim is caught by the semantic check. [FR-4.4]
- [x] **[int]** A failed note triggers regeneration, and the failure reason is passed back as context. [FR-4.5]
- [x] **[int]** Regeneration stops at the retry limit. [FR-4.5]
- [x] **[int]** A note that still fails is stored with an explicit unverified status. [FR-4.7]
- [x] **[int]** `verification_status` and the passed-of-checked counts are persisted with the note. [FR-4.6]
- [x] **[int]** Deterministic and semantic validity are recorded as two separate numbers. [FR-7.5]
- [x] **[man]** Deliberately corrupt a note by hand and confirm the Verifier rejects it. *(2026-10-22, on stored note `7279ba74`, which passes clean at 5/5. Three corruptions, each rejected: a stated `unit_price` changed from 7885.35 to 999999999.99 → 4/5; a cited row id replaced with 99,999,999 → 4/5; an invented clause `SG-PP-9.9` → flagged. No model involved — these are the deterministic checks.)*

---

## 7. Database

- [x] **[unit]** Case status transitions persist and survive a restart. [FR-5.3]
- [x] **[unit]** Reviewer notes persist against the correct case. [FR-5.2]
- [x] **[int]** Alembic migrations apply cleanly to an empty database. [NFR-10] *(2026-10-22: `backend/alembic/`, one revision covering all eight tables, generated from the models rather than written by hand. Four tests, and the one that matters is not “migrations run” but **a migrated store and a `create_all` store have the same schema** — two descriptions of one store is exactly where drift lives. Also pinned: the revision rolls back to an empty database, and autogenerate finds nothing left to do. Proved non-vacuous — adding a column to one model fails two of them and names it.)*
- [x] **[int]** The API opens DuckDB read-only, so a batch run and the API can operate concurrently. [Architecture 2.4] *(2026-10-22: `detect` scanned 49,900 transactions against the live DuckDB while the dashboard was served, writing 154 cases to a scratch store. 400 of 400 API requests returned 200.)*
- [x] **[int]** A batch run while the dashboard is open does not produce a lock error. [Architecture 2.4] *(2026-10-22: zero matches for lock, conflict or IO Error in either the batch log or the server log during the run above.)*

---

## 8. API

- [x] **[int]** Every endpoint validates its response against its Pydantic model. [FR-5.9]
- [x] **[int]** The OpenAPI schema is published and matches the implemented routes. [FR-5.9]
- [x] **[int]** Case listing filters correctly by status, anomaly type, severity band, and verdict. [FR-5.5]
- [x] **[int]** Case detail returns the note, its citations, the referenced evidence rows, and the trace. [FR-5.6]
- [x] **[int]** A case that has not been investigated returns detector output with an explicit not-investigated marker, not a null-filled note. [FR-5.6]
- [x] **[int]** Status update rejects an invalid transition target. [FR-5.1]
- [x] **[int]** Metrics endpoint returns flagged, investigated and queued counts that sum consistently. [FR-5.7]
- [x] **[int]** Requesting an unknown case id returns 404 with a structured error, not a stack trace. [NFR-10]
- [x] **[int]** Evaluation endpoint returns detector-versus-baseline and ablation tables. [FR-5.8] *(an arm's row is described from its own run config; its notes never enter the agent's numbers)*

---

## 9. Frontend

- [x] **[man]** Case queue sorts and filters correctly, and pagination works past the first page. [FR-6.2]
- [x] **[man]** KPI cards show money at risk and the flagged / investigated / queued line. [FR-6.1]
- [x] **[man]** Citations in the note are inspectable and resolve to the correct evidence rows. [FR-6.3]
- [x] **[man]** Evidence table visually distinguishes the rows belonging to the case. [FR-6.4]
- [x] **[man]** Verification badge shows passed of checked, and an unverified note is visibly marked as such. [FR-6.5] [FR-6.9]
- [x] **[man]** Agent trace renders as an ordered timeline with arguments and results readable. [FR-6.6]
- [x] **[man]** Status change and reviewer note save, and survive a page reload. [FR-6.7]
- [x] **[man]** Metrics view renders the detector table and the ablation table. [FR-6.8]
- [x] **[man]** Loading and error states render for every data-fetching view — no blank screens. [NFR-5]
- [x] **[man]** A deliberate API shape change is caught by Zod validation with a visible error. [Architecture 2.6] *(2026-10-22, shown live: `amount_at_risk` was rewritten at the wire from a decimal string to the number 12345.67 — the exact breach convention 11 forbids — and the queue rendered a red banner reading “The API's reply to /cases?page=1&page_size=50&detector=duplicate broke the contract (items.0.amount_at_risk: Expected string, received number).” It names the endpoint, the field path and both types, and no rows render from an unvalidated payload.)*
- [x] **[man]** Layout holds at a projector resolution and does not scroll horizontally. *(2026-10-22 at 1920×1080: no horizontal scroll on any of the eight pages, `scrollWidth` equal to `clientWidth` throughout. **The actual projector is still untested** — that is the separate item in section 12.)*
- [x] **[man]** Every monetary value shows `₹` with Indian digit grouping, and converted figures are visibly marked as converted. [FR-6.10] *(2026-10-22: every one of the 52 money strings rendered on the queue matches Indian grouping, and no dollar sign appears anywhere. The conversion marker is now covered end to end — the California card records `currency: USD, fx_rate_to_inr: 60.0, converted: true`, the API maps it to `converted_from`, and five new tests pin `<DatasetBanner>` on both branches. Proved non-vacuous: disabling the converted branch fails two of them.)*

---

## 10. Evaluation

- [x] **[int]** Per-case precision, recall, F1 and PR-AUC are produced per detector against the baseline. [FR-7.3] *(`docs/results/detection.md`, “Per case (headline)”: all four columns, every detector beside its baseline, mean ± sd across three seeds.)*
- [x] **[int]** Per-row metrics are produced as a secondary table. [FR-7.4] *(`detection.md`, “Per row (secondary)” — labelled secondary, as D-02 requires.)*
- [x] **[int]** The case-overlap matching rule is implemented exactly as specified and unit-tested at its boundaries. [FR-7.3]
- [x] **[int]** D4 vendor-level cases are matched by the rule appropriate to vendor-level cases, not by row overlap. [Open issue]
- [x] **[int]** Citation validity is reported split into deterministic and semantic. [FR-7.5]
- [x] **[int]** Triage accuracy is computed only over investigated cases, and the report states that this sample is severity-biased. [FR-7.6] *(2026-10-22: the table carries both Sample and Investigated, and the section now says in bold that an arm whose Investigated is below its Sample has been scored on its higher-severity cases — which are not a random half. It did not say so before.)*
- [x] **[int]** Efficiency metrics — tool calls, tokens, latency — are recorded per case. [FR-7.7]
- [x] **[int]** The Verifier-off ablation runs and produces a comparison table. [FR-7.8] *(`--no-verify` in evaluation mode is the `no-verifier` arm: stored, scored and reported apart, so unverified notes never replace verified ones)*
- [x] **[int]** The template-notes ablation runs and produces a comparison table. [FR-7.9] *(`--ablation template`; needs no model to write the note, and its citations still pass the deterministic check - the arm's point is the triage column, not the citation column)*
- [x] **[int]** Every run is logged to the experiment tracker with its parameters, seeds and results. [FR-7.10] *(2026-10-22: results and seeds were already in `eval_results`; **parameters were not logged anywhere**, so a run was reproducible only because the config happened not to have moved. An `eval_runs` row now records the run id, seed, transaction count, detectors and the 13 thresholds in force, from the same `DETECTOR_SETTINGS` list the report prints — one list, not two. Pinned by two tests, one of which moves a threshold and checks the snapshot follows; proved non-vacuous by making the snapshot return zeros. **The tracker is DuckDB plus the generated reports, not MLflow** — FR-7.10 asks for a local experiment tracker and this is one; MLflow stays a Phase 10 convenience.)*
- [x] **[int]** Re-running an evaluation with the same seed reproduces the same numbers. [NFR-4] *(2026-10-22, after the DuckDB/Polars/Pydantic pins: `report detection` re-detects seed 42 and prints “identical”. Every metric payload — aggregate, clean, reproduced, reproduced_cases, seeds — byte-identical across runs; only run ids and timestamps differ.)*
- [x] **[unit]** Every sourced figure in EVALUATION.md matches the file that generated it. [Phase 9 exit] *(`spendguard check-evaluation`; catches a one-figure drift, ignores rounding in the last place, and fails loudly if it finds no sourced table at all)*
- [x] **[man]** Results are reported across multiple seeds with variation stated. [FR-7.11] *(`detection.md`: seeds 42, 7 and 2026 named with 42 marked as the one every threshold was tuned on; values are mean ± sample sd, plus a per-seed F1 table. The agent numbers are seed 42 only, which the agent report says on its face.)*
- [x] **[int]** Top-k unlabeled flags can be reviewed so precision is reported raw and adjusted. [FR-7.12] *(`spendguard review export/import/report`; the sample is seeded and recorded before any verdict, unclear verdicts stay out of the ratio, and every ratio carries a Wilson interval pinned in tests)*
- [ ] **[man]** A real review batch is filled by three reviewers and reported. [FR-7.12]
- [x] **[int]** A second dataset ingests, detects and stores without touching the operational store. [FR-1.3] *(California: 336,995 rows in 6.7 s via `california_po.yaml` and `detect --store`)*
- [x] **[int]** Notes are graded blind against a rubric fixed in advance, with inter-grader agreement reported. [EVALUATION 5.3] *(`spendguard grade export/import/report`; a test reads every file a grader receives and fails if the arm, model, badge or ids leak - verified by sabotaging the export)*
- [x] **[unit]** The agreement statistic is correct, not merely plausible. [EVALUATION 5.3] *(Krippendorff's alpha pinned to the published worked example at α nominal 0.691 and ordinal 0.807, plus the properties relied on: noise ≈ 0, worse-than-chance < 0, ordinal punishes a two-point gap harder than a one-point gap)*
- [ ] **[man]** A real grading batch is filled by three graders and reported. [EVALUATION 5.3] *(needs the note pool from step 6)*

---

## 11. System and privacy

- [x] **[int]** A full run against the local endpoint makes no external network calls — verified by monitoring, not assumed. [NFR-1] [NFR-3] *(2026-10-22, every outbound connection inspected with loopback allowed and everything else raising. A full `evaluate_investigation` on seed 42 wrote **5 notes, 2 of them verified**, against Ollama on localhost — and attempted **20 connections to huggingface.co**, all blocked, the run completing anyway. That is sentence-transformers checking the Hub for an embedding model it already has cached: not a dependency, but not nothing either, since the claim has to mean it does not try. With `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` the same run contacts **nothing but loopback**. Both flags are documented in `.env.example`.)*
- [x] **[int]** No API key for a paid provider is required for the delivered configuration. [NFR-1] *(2026-10-22: `LLM_PROVIDER=ollama` needs no key at all — the client sends the literal string `ollama` where a key would go, and `check-llm` passes chat, tool calling and a second turn against it. Groq remains configured for the hosted evaluation and is itself a free tier, but nothing in the delivered path requires either.)*
- [x] **[man]** The model runs within available VRAM and the memory ceiling is recorded. [NFR-2] *(2026-10-22 on the development machine's RTX 2050: **2,158 MiB of 4,096 MiB** while Qwen2.5-3B-Instruct q4_K_M was loaded and generating — 1.9 GB of headroom. Sampled every 2 s across a generation; the figure is the peak.)*
- [x] **[man]** Full detection over the development dataset completes within the target time, and the figure is recorded. [NFR-6] *(2026-10-22: **15.3 s** wall for D1–D4 over 49,900 clean transactions. D1 reports no anomalies on clean data, which is the answer convention 5 exists to check.)*
- [x] **[man]** No credentials, API keys or raw data are committed to version control. [DR-4] *(2026-10-22, scanned all 135 commits: no `gsk_`/`sk-`/`AIza` token shapes and no PRIVATE KEY blocks anywhere in history; `.env` has never been tracked; zero files tracked under `data/`, and every subdirectory of it is git-ignored.)*
- [ ] **[man]** A clean-machine setup from the documented commands succeeds. [NFR-10]

---

## 12. Pre-demonstration

- [x] The demo dataset is frozen and version-pinned. [NFR-9] [DR-5] *(re-frozen 2026-10-22 07:32 UTC at commit `7fbcb47`, now holding **17 investigated cases and 9 verified notes** — the previous snapshot predated most of them at 12 and 6. Four files under a SHA-256 manifest; `verify()` matches all four. **Re-freeze again after the final matrix run**, which will add the last few notes.)*
- [x] The demo runs from the frozen snapshot, not a live path that can change. *(2026-10-22, demonstrated rather than asserted: with `serve --frozen` running, a case was PATCHed to `confirmed` with a reviewer note. The working copy showed the change, so the demo stays interactive — and the snapshot stayed byte-identical, same SHA-256 before and after. On relaunch the case came back `new` with no note and no reviews. A stray click during a rehearsal cannot change what the room sees.)*
- [ ] Every screen in the demo sequence has been walked through at least three times end to end.
- [x] A pre-computed run exists so nothing has to be generated live. *(the frozen snapshot carries the completed seed-42 evaluation and its 17 audit notes, including the verified dismissal `fe2c704f` the walkthrough is built around. Nothing in the demo sequence calls a language model; the only live computation is the injection demo, which is detection only.)*
- [ ] The live injection demonstration completes within the time allowed, rehearsed with a stopwatch.
- [x] The live injection demonstration reports every planted anomaly as caught or missed, and each miss is named and attributed to the measured recall rather than to a guessed cause, verified on a rehearsal run. *(2026-10-22: six planted, three caught. Each miss renders as **Missed** with an em dash for detector and score — no invented value — and the sentence reads “Missed here: price inflation, split purchase ×2”, naming what actually got away and pointing at the Evaluation page rather than guessing why. Scan time 4.7 s warm.)*
- [ ] A recorded video fallback exists and has been played back in full.
- [ ] The machine is tested on the actual projector and resolution.
- [x] The system starts from cold — model loaded, database up, API up, frontend up — within the setup time available. *(2026-10-22, `serve --frozen`, two consecutive runs: health answering 2.27 s, dashboard HTML +0.23 s, first queue page +0.17 s — **2.65 s total**. No language model loads on this path; health never probes the LLM, D-32.)*
- [ ] Every number quoted in the presentation traces to a logged run.
- [x] Wording checks: "duplicate transaction records", never "duplicate payments" for purchase-order data. "Detects across 100% of transactions, then autonomously investigates prioritized cases", never "investigates every flagged case". *(2026-10-22, grepped across docs, code and the frontend: no claim of investigating every flagged case, no claim of beating commercial tools, and every “duplicate payment” hit is either the authored policy corpus — which legitimately covers payments — a test fixture exercising the rule, or a sentence drawing the PO/payment distinction explicitly. **This covers the repository, not the slides**, which still need the same pass.)*
- [ ] The limitations section states the invoice-to-payment reconciliation gap, the authored-policy caveat, and the severity-biased triage sample.
