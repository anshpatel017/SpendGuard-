# PROGRESS.md — SpendGuard

Running phase-by-phase log. Updated at the end of every phase, before starting the next.
Detailed rationale lives in [docs/DECISIONS.md](docs/DECISIONS.md); results in [docs/EVALUATION.md](docs/EVALUATION.md).

---

## Project Roadmap

Ten phases, numbered 0–9. A phase is **done** when its exit criterion is demonstrably true, the suite is green, and it is committed.

| # | Phase | Goal |
|---|---|---|
| 0 | **Foundation** | Repo scaffold, typed config, CI, and the policy/config agreement check |
| 1 | **Data** | Seeded synthetic INR generator, ingestion pipeline, vendor normalization, dataset card |
| 2 | **Ground truth and baseline** | Anomaly-injection harness, rule-based baseline, evaluation and matching |
| 3 | **D1 + D2** | Duplicate-record and split-purchase detectors, plus the operational case store |
| 4 | **D3 + D4** | Price-inflation and vendor-red-flag detectors; severity-ranked queue complete |
| 5 | **Agent tools and policy RAG** | Six agent tools, semantic retrieval over `policy.md`, provider-switchable LLM client |
| 6 | **Investigator** | Bounded tool-calling loop producing schema-valid, cited audit notes with full traces |
| 7 | **Verifier** | Citation extraction, deterministic + semantic checks, regeneration loop |
| 8 | **API and dashboard** | FastAPI over the stores, then the React case queue, evidence view and trace timeline |
| 9 | **Evaluation, real data and freeze** | Multi-seed runs, ablations, blinded grading, California dataset, frozen demo + video |

> **Note:** `docs/PHASE-PLAN.md` was written with 12 phases. It is consolidated here into 10 by merging *API + Frontend* into Phase 8 and *Evaluation + hardening/real data* into Phase 9. Numbering for phases 0–4 is unchanged, so commits and earlier notes still line up.

---

## Completed Phases

### Phase 0 — Foundation ✅ (`f2fda41`, `137ddd1`)

**Built:** monorepo scaffold; `pyproject.toml` with phase-scoped dependency extras (`detect`, `agent`, `api`, `track`, `linkage`, `dev`); `config.py` as the single typed source of truth; `policy_check.py`, which parses the threshold table out of `policy/policy.md` and compares it to config; Indian digit grouping for money; GitHub Actions CI (lint → format → types → tests).

**Files:** `backend/pyproject.toml`, `src/spendguard/config.py`, `src/spendguard/policy_check.py`, `tests/test_config.py`, `tests/test_policy_config_agreement.py`, `.github/workflows/ci.yml`, `.gitignore`, `.env.example`, `docs/PHASE-PLAN.md`.

**Decisions and gotchas:**
- The policy/config agreement check was built **first**, on purpose: ₹2,50,000 appears in two places and will drift. A test also tampers with a copy of the policy to prove the check can fail — a check that cannot fail is worse than none.
- Open issue **O-03** settled in config: severity uses a **fixed** reference amount (₹1 crore), not the run maximum, so one large transaction cannot rescale every other case.
- Python floor raised to 3.12 (installed numpy's stubs need it).

---

### Phase 1 — Data ✅ (`6f3d89b`)

**Built:** a seeded, INR-native synthetic generator (12 departments, 22 commodity categories, Zipf-distributed suppliers, recurring monthly contracts, March year-end rush, spec tiers, dirty formatting, malformed rows) and the ingestion pipeline (per-dataset YAML column mapping, cleaning, pinned-rate currency conversion, vendor normalization, DuckDB write, dataset card).

**Files:** `pipeline/synthetic.py`, `pipeline/catalogue.py`, `pipeline/perturb.py`, `pipeline/vendors.py`, `pipeline/ingest.py`, `pipeline/mapping.py`, `pipeline/dataset_card.py`, `db/duck.py`, `cli.py`, `mappings/synthetic_inr.yaml`, four test modules.

**Decisions and gotchas:**
- `row_id` is the **source line number**, assigned before any row is dropped, so tightening a cleaning rule never renumbers rows and an audit note's citations never silently point elsewhere.
- Vendor normalization measured against generator truth: **0** suppliers split across keys, **10 of 382** keys over-merged (2.2% of rows) — the D-12 trade-off, left in deliberately because real vendor masters contain the same pairs.
- Two defects the tests caught: a typo in a legal suffix changed the blocking key (fixed with fuzzy stopword matching), and token-sort similarity collapsed to 44/100 on a first-letter typo (fixed by taking the better of two scorers).
- Windows consoles are cp1252 and crash on `₹`; the CLI forces UTF-8 on its own output.

---

### Phase 2 — Ground truth and baseline ✅ (`ec81083`)

**Built:** the anomaly-injection harness (duplicates, splits, inflation, synthesized fraud vendors) writing to a **separate** database with a `ground_truth` table; the four-rule baseline detector; and the evaluation stack — one-to-one score-ordered case matching, vendor-level matching for D4, per-case and per-row metrics, PR-AUC, DuckDB `eval_results` plus JSON/Markdown reports.

**Files:** `eval/injection.py`, `eval/matching.py`, `eval/metrics.py`, `eval/runner.py`, `detectors/base.py`, `detectors/baseline.py`, `cases.py`, four test modules.

**Decisions and gotchas:**
- Detectors read the **`audit_transactions` view**, which hides the answer key and `source_row_ref` (injected rows have none, so its absence would leak). A test parses every detector module for leaks — verified by planting one and watching it fail.
- The first baseline run scored **perfect precision on inflation**, which was a defect in the *generator*: prices were too tightly spread for any honest purchase to look expensive. Added spec tiers and urgent-purchase premiums; precision fell to a realistic 0.357 (**D-18**).
- Baseline, 504 planted groups: pooled per-case P 0.151 / R 0.306 / F1 0.202.

---

### Phase 3 — D1 + D2 and the case store ✅ (`ad94181`)

**Built:** **D1** (exact stage, plus amount+date blocking → name-similarity identity confirmation → Fellegi–Sunter model fitted by MAP-EM, transitive grouping); **D2** (minimal runs per supplier and officer, four equally weighted policy indicators, dev-seed threshold); the SQLite case store with the review workflow; and `spendguard detect`.

**Files:** `detectors/d1_duplicates.py`, `detectors/d2_splits.py`, `db/store.py`, `detection.py`, `tests/test_d1.py`, `tests/test_d2.py`, `tests/test_store.py`.

**Results** (3 seeds, mean; seed 42 dev, seeds 7 and 2026 held out):

| Anomaly | Baseline F1 | Detector F1 | Precision | Recall |
|---|---:|---:|---:|---:|
| duplicate | 0.354 | **D1 0.949** | 1.000 | 0.903 |
| split | 0.029 | **D2 0.724** | 0.828 | 0.643 |

**Decisions and gotchas:**
- **D-19 (user-approved):** D1 blocks on amount + date, not vendor key — a typo in the distinctive part of a name changes the key, so exact-key blocking is structurally blind to 30% of injected duplicates. A log-bucket equi-join is **set-identical** to the brute-force join and 300× faster.
- **Three modelling corrections, all found by testing:** `u` learned from look-alikes too far apart in time to be duplicates (and the reference set must mirror candidate selection *exactly*); officer/item/amount compared **jointly** because they co-vary and were being counted three times; and **MAP-EM priors**, because plain EM invented a duplicate class on clean data and raised **1,732 false duplicates** — now 0.
- **The clean-data check is now permanent.** Injected-data metrics alone could not have shown that bug.
- **D-22:** the harness got harder — 10% of duplicates re-keyed under unrelated references (D1's honest blind spot), and split parts now take never-issued invoice numbers.
- Fixed a determinism bug: DuckDB's parallel `GROUP BY` is unordered, so case order varied between runs.
- The case store **upserts**: re-running detection refreshes detector facts but never discards an auditor's status or note. `detect` refuses a database containing planted anomalies.

---

### Phase 4 — D3 + D4 ✅ (`ff311b3`)

**Built:** **D3** (robust z-score on log unit price against a per-category median, adjusted for bulk discount and annual drift, with an Isolation Forest as a recorded second opinion) and **D4** (vendor red flags as statistical tests against peer behaviour, combined by Fisher's method, FDR-controlled across all suppliers). Both registered and running in `spendguard detect`.

**Files:** `detectors/d3_inflation.py`, `detectors/d4_vendor.py`, `tests/test_d3.py`, `tests/test_d4.py`, config additions, `detectors/__init__.py`.

**Results** (3 seeds, mean ± sd; seed 42 dev, 7 and 2026 held out):

| Anomaly | Baseline F1 | Detector F1 | Precision | Recall | PR-AUC (vs baseline) |
|---|---:|---:|---:|---:|---|
| inflation | **0.432** | D3 0.419 | 0.369 | 0.484 | **0.280** vs 0.196 |
| vendor_flag | 0.497 | **D4 0.853** | **1.000** | 0.750 | **0.750** vs 0.263 |

**Decisions and gotchas:**

- **D3 does not beat the baseline on F1 — and the report says so (D-23).** Five statistics were compared on the dev seed; all landed within 0.02 F1 of each other and of the rule baseline. The cause is structural: 7,508 honest rows sit above 1.4× their category median, because legitimate premium and urgent purchases occupy the same band as the injected markups. D3's real gain is **ranking** (PR-AUC +43%), which is what matters when only top-N cases are investigated. This is the strongest argument in the project for the investigation layer.
- **D3 ignores the item description on purpose.** Half the legitimate premium rows say "Premium Grade"; trusting that means trusting text written by whoever set the price. It is evidence for the agent, not an input to a detector.
- **The Isolation Forest is kept only as a recorded second opinion.** On its own it scores F1 0.07. Reported as a measured negative result.
- **D4: Benford's law is not a valid null here (D-24).** Procurement invoices are quantity × a near-fixed price and depart from Benford routinely — testing against the law directly accused **61 of 210** real suppliers. The null is now the empirical digit distribution of the same categories; Benford conformity is still reported as context.
- **Three more D4 guards, each added after it accused someone real:** tests run on distinct amounts (a monthly contract is one price decision, not twelve); expectations are conditional on the supplier's own categories (a consultancy billing round figures is normal for a consultancy); and an effect must be *material*, not merely significant (with 400 invoices a three-point deviation is significant and meaningless).
- **D4 first scored F1 = 1.000 on every seed — so the harness was made harder (D-25).** Planted vendors now draw their own round-number share (35–75%) and period-end share (30–60%). F1 fell to 0.853 and the misses are exactly the subtlest vendors. Same correction as D-22, same reason: an evaluation that cannot fail measures nothing.
- **Clean-data check:** D1, D2 and D4 raise 0 cases; D3 raises 154 of 49,900 (0.3%) — the honest premium and urgent purchases.
- Four test-only bugs found and fixed: assertions that asserted full-scale results against a 3,000-row fixture, and one that tested the random number generator rather than behaviour.

**457 tests passing.**

---

### Phase 5 — Agent tools and policy RAG ✅ (`1603324`)

**Built:** the provider-switchable LLM client, the six agent tools, and semantic retrieval over the procurement policy. Plus `spendguard check-llm`, which verifies the endpoint answers *and* that tool calling works.

**Files:** `agent/llm.py`, `agent/tools.py`, `agent/policy.py`, `tests/test_llm.py`, `tests/test_agent_tools.py`, `tests/test_policy_rag.py`, `tests/test_agent_live.py`, `cli.py`.

**Decisions and gotchas:**

- **The planned model no longer exists (D-26).** Groq retired `llama-3.3-70b-versatile`. Chose **`qwen/qwen3.8-27b`** from the current list: the local target is Qwen2.5-3B, so prompts are more likely to survive the port to Ollama. Tool calling verified live before anything was built on it.
- **Retrieval is dense embeddings, and the alternatives were measured, not assumed (D-27).** Hybrid (dense + BM25 via Reciprocal Rank Fusion) is the standard remedy for keyword-ish queries, so it was built and compared: dense 5/10 top-1, BM25 2/10, hybrid 4/10. Hybrid never won — 41 short clauses of formal prose give BM25 almost no lexical overlap to exploit. Other modes stay available for the ablation.
- **A cache bug that hid its own fix.** The embedding cache was keyed on the policy file, so changing how clauses are flattened left stale vectors in place: the measurement after the change came back byte-identical to the one before. The key now hashes the exact text that gets embedded.
- **Three layers keep the tools safe (D-28):** a read-only connection, a view without the answer key, and a validator that refuses anything but a single SELECT over that view. Tools never raise into the loop — a failure returns `{"error": ...}` the model can read and recover from.
- **`vendor_profile` reports fixed monthly contracts.** This is the evidence the Investigator needs to dismiss a "duplicate" as routine billing, which is the false-positive filtering the project claims (D-04).
- Live test: given the six tools, the model chose `vendor_profile` and the toolbox executed it. Skipped automatically when no key is set, so CI stays green.

**528 tests passing.**

---

### Phase 6 — Investigator ✅ (`feb62e3`)

**Built:** the Investigator — a hand-written, bounded tool-calling loop that briefs the model on a case, runs the tools it asks for, and validates the JSON audit note it returns; the note schema (structured, citable claims); per-type prompts; persistence of notes, per-row citations and full traces; and `spendguard investigate`, with an operational mode (top-N open cases from the store) and an evaluation mode (a seeded sample of real and spurious cases on an injected database, scored for triage).

**Files:** `agent/note.py`, `agent/prompts.py`, `agent/investigator.py`, `investigation.py`, `eval/triage.py`, `db/store.py` (`audit_notes`, `citations`, `agent_traces`), `agent/llm.py` (rate-limit and quota handling), `cli.py`, `agent/tools.py` (smaller default result size), `config.py` (`AGENT_CONTEXT_TOKENS`, `AGENT_TOOL_RESULT_CHARS`), `.env.example`, `tests/test_investigator_note.py`, `tests/test_investigator.py`, `tests/test_investigation.py`, `tests/test_llm.py`, `tests/test_agent_live.py`, `tests/conftest.py` (live tests opt-in), `docs/DATA-SCHEMA.md`, `docs/DECISIONS.md` (D-29, D-30), `docs/TEST-CHECKLIST.md`.

**Exit criterion met:** on the dev seed, the top case of **each of the four types** produced a schema-valid note with every claim cited, no citation of a row the agent had not seen, and a full trace (4–10 tool calls, 15–25k prompt tokens a case). All four were genuine planted anomalies (checked against ground truth); inflation, split and vendor_flag came back `likely_true_positive`, and the duplicate's claims argued for a duplicate, though its verdict line was not captured in the smoke output. The stored evaluation note (a duplicate) is specific and correct: same invoice number one day apart, and it checked the supplier for a fixed monthly contract before concluding.

**Decisions and gotchas:**

- **Notes are structured claims, not prose with citation markers (D-29).** Each claim carries its `row_ids` and optional `facts` (`{row_id, field, value}`), so the Verifier checks data, not text. A fact may only name a field the audit view exposes.
- **The prompt shows one worked example — the case's own type — and tells the agent to look for the innocent explanation first.** An investigator that only confirms flags adds nothing; dismissal is the contribution (D-04).
- **A malformed note is sent back with the validation error** (up to twice), and when steps run out a final turn with tools switched off asks for the note. Qwen 3's `<think>` blocks are stripped before parsing.
- **Free tier limits shaped the loop (D-30).** The first live run failed every case: the client retried a 429 after 1, 2 and 4 s while Groq asked for ~28 s. It now waits as long as the server asks. Then a vendor investigation grew to 7,753 tokens in one request and was refused outright (HTTP 413), so every request now fits a **token budget**: the bulkiest earlier tool results are trimmed to the row ids they held (oldest-first was tried; the model re-requested what it lost). Tool results are cut by whole rows, never mid-JSON.
- **The binding limit is 200,000 tokens per day — about ten investigations.** Runs now stop cleanly when the daily quota is spent and resume on the next run; evaluation samples accumulate across days, and a quota stop is never scored as an agent failure.
- **O-04 implemented as recommended** (the number moves with the band) — awaiting your confirmation.
- **Live LLM tests are now opt-in** (`pytest -m llm`). With a key in `.env` the default suite was calling Groq, which spends the daily quota on every test run.
- **Seen once, for the Verifier:** a note's recommended action said "duplicate payment", echoing the policy's own "duplicate-payment register" despite the prompt's rule.

**Triage evaluation — started, not finished.** `spendguard investigate --eval-seed 42 --per-type 1` drew 6 cases; 1 completed (a real duplicate, correctly kept) before the daily quota ran out. The triage numbers — real anomalies kept, spurious ones filtered — need the full sample and belong to Phase 9.

**595 tests passing** (+6 live tests, opt-in).

---

### Phase 7 — Verifier ✅ (`3154e63`)

**Built:** the Verifier. Every note is checked before release: a **deterministic** check (cited rows exist, stated values match, cited policy clauses exist, no "duplicate payment" wording) and a **semantic** check (a fresh-context LLM judge rules whether the evidence supports each claim). Failures go back into the Investigator's own conversation for revision, up to `VERIFIER_MAX_RETRIES`, and the best draft is released as `verified`, `failed_after_retries` or `unverified`. Badge, counts and every citation's check results are stored. `spendguard investigate --no-verify` runs the Verifier-off ablation (FR-7.8).

**Files:** `agent/checks.py` (new, deterministic), `agent/verifier.py` (new, judge and loop), `agent/investigator.py` (keeps its conversation; `revise()`, `finalize()`), `agent/note.py` (`citations()`), `db/store.py` (verification fields and trace role persisted), `investigation.py` (Verifier in both modes; citation validity in the summary and report), `cli.py` (`--verify/--no-verify`, badge per case), `config.py` (`VERIFIER_ENABLED`, `VERIFIER_SEMANTIC_CHECK`, `VERIFIER_TEMPERATURE`, `VERIFIER_MAX_ROWS`, `VERIFIER_CONTEXT_CHARS`), `.env.example`, `tests/test_verifier.py` (new, 38 tests), `tests/test_investigation.py`, `tests/test_investigator.py`, `tests/test_agent_live.py`, `docs/DECISIONS.md` (D-31), `docs/DATA-SCHEMA.md`, `docs/TEST-CHECKLIST.md`.

**Exit criterion met:** a note planted with a wrong amount, a nonexistent row and an unsupported claim is caught on each count, and a clean note is released `verified`. The tests are not vacuous: breaking the value comparison on purpose makes four of them fail. Live, the real judge accepted a true claim about a row and rejected an invented one about the same row. On the real note the agent wrote in Phase 6, the deterministic check passes all 8 citations and all 14 stated values, and catches that note's "duplicate payment" wording.

**Decisions and gotchas:**

- **Two numbers, never blended (D-13, D-31).** Deterministic validity involves no model and is the headline. The semantic number comes from the same model family that wrote the note, so it is labelled model-judged.
- **A stated number matches at the precision it was stated.** `259463` matches `259463.41`; `260000` does not; nor does a transposed digit. Invoice numbers are compared almost literally, because `INV-4471` against `INV-04471` is the retyping that makes a duplicate.
- **The judge gets a fresh context:** claims, cited rows and the Investigator's tool results, never its reasoning. It rules on claims, not rows one at a time, because "the four orders total ₹3,26,873" is supported by its rows together.
- **Revision continues the Investigator's conversation** instead of investigating again. A fix costs a turn or two rather than 15–25k tokens, which matters at ~10 investigations a day. This needed a small refactor: the loop now lives in one `_gather()` used by both `investigate()` and `revise()`.
- **The best draft is released, not the last**, and a revision that never arrives keeps the original note.
- **`verified` requires both checks to have run.** A judge that could not answer means `unverified`; any known failure means `failed_after_retries`.
- **The Verifier-off ablation still measures.** Nothing is enforced or regenerated, but the deterministic check runs and is stored, so both arms are measured by the same code.
- A test fixture was wrong, not the code: a scripted note claimed ₹5,000 for a ₹1,000 row, and the new Verifier caught it.

**Not yet done live:** a full investigate → verify → revise run on real cases. The attempt stopped on the Groq daily quota after one case, cleanly, with four sample cases left. `spendguard investigate --eval-seed 42 --per-type 1` continues it when the quota refills.

**633 tests passing** (+7 live tests, opt-in).

---

### Phase 8 — API and dashboard ✅ (`a5789ec`, `0035fe8`)

**Built:** the FastAPI backend (`spendguard serve`) and the React dashboard it serves.
- **API** (`/api/v1`): the case queue with filters, sorting and paging; case detail with the audit note, per-citation check results, evidence and context rows, and the trace; paged evidence; single-transaction lookup; the review action; metrics; evaluation results; run history; health. Errors are structured, never a stack trace. OpenAPI is published at `/docs` and exported by `spendguard openapi`.
- **Dashboard** (React 18, TypeScript, Vite, TanStack Query):
  - KPI cards and the honest coverage line;
  - a filterable, sortable, paged queue whose filters live in the URL;
  - the case page: the note with clickable citations that highlight their evidence row, the verification badge, the evidence table with case rows shaded, the trace timeline and the review panel;
  - an evaluation page.
- **Evaluation view:** `spendguard serve --eval-seed 42` shows an evaluation run's stores under a planted-anomalies banner.

**Files:**
- Backend: `api/app.py`, `api/schemas.py`, `api/deps.py`, `api/cases.py`, `api/overview.py`, `cli.py` (`serve`, `openapi`), `config.py` (`API_*`, `FRONTEND_DIST`), `db/store.py` (clearing a note), `investigation.py` (every flagged case saved), `tests/test_api.py`.
- Frontend: `frontend/` — `src/api` (generated `schema.d.ts`, `validate.ts`, `client.ts`, `hooks.ts`, contract fixtures), `src/lib` (format, verification), `src/components`, `src/pages`, three test files, and `openapi.json`.
- CI and docs: `.github/workflows/ci.yml` (frontend job, API extra), `.env.example`, `docs/API-CONTRACT.md` (as-built differences), `docs/DECISIONS.md` (D-32), `docs/TEST-CHECKLIST.md`.

**Exit criterion met, in the running app:** on the seed-42 evaluation stores (511 flagged cases), the dashboard shows the KPIs and the coverage line.
- **Queue:** filtering to investigated cases, opening one by URL, and paging (page 2 of 11, sorted by amount) all work.
- **Case page:** it shows the note with its claims, citations and policy clauses, 2 evidence rows plus 15 context rows, and the 8-step trace.
- **Citations:** clicking one highlights and scrolls to its row.
- **Review:** confirming the case with a note persisted it, and the confirmed money at risk rose to ₹2,59,463.41. The case was reset afterwards.
- **Speed:** warm API calls take 11–40 ms and a cold metrics call 346 ms, inside the ~2 s target.

**Decisions and gotchas:**

- **The contract is enforced at three points (D-32).** A backend test fails if the committed `openapi.json` differs from the API. CI fails if the generated TypeScript types differ from `openapi.json`. Every response is parsed at runtime by Zod schemas typed against those generated types. The first compile caught a real mismatch.
- **The answer key cannot leak through the API, and a test proves it.** Evidence goes through the audit view, an explicit field list and a closed response schema. Breaking one layer leaked nothing; only breaking all three made the leak test fail.
- **Money is a string end to end**, formatted with Indian grouping without ever becoming a float.
- **Two bugs found only by using it in a browser.**
  - The evaluation table showed D1 for every anomaly type (F1 0.000 on splits) because the report scores every detector against every type. The API now serves only the types a detector declares.
  - A reviewer could not clear a note, and an empty one was stored as `""`, breaking the null rule. A blank note now clears to null.

  Both have regression tests now.
- **Health reports the LLM as configured, not reachable.** A probe per health check would spend the daily quota.
- **Dependencies were audited.** React Router 6 and Vitest 3 carried moderate advisories, so both moved up a major version (7 and 5). `npm audit` reports 0 vulnerabilities.
- **Deferred to Phase 9:** the live-injection demo endpoint (a SHOULD), which needs the frozen demo dataset.
- **Browser caveat:** the built-in browser pane stopped painting partway through (the app window was behind another one). The later checks were done by reading the page and its DOM rather than by screenshot.

**Not yet shown in the browser:** a note with a `verified` badge. None exists yet because of the Groq quota. The badge logic is unit-tested for every status.

**662 backend tests** (+7 live, opt-in) **and 29 frontend tests passing.**

---

### Between phases — first live verified run, and Gemini as a provider (`567ccd0`, `1bf735a`)

Not a phase: fixes found by the first real run of the Verifier, and the provider switch decided before Phase 9.

**The first live verified run (2026-09-22, Groq)** investigated one case before the daily quota ran out.
- **Result:** the agent called a split case genuine, and it was: a planted *duplicate* that D2 had also flagged as a split. The agent even suggested checking for a duplicate record.
- **Citations:** all 12 existed and matched (100% deterministic); 83% were supported (model-judged).
- **Released as `failed_after_retries`.** Two bugs explain that, both fixed with regression tests built from the real data:
  - **The judge was shown evidence cut mid-text.** Each tool result was cut at 700 characters; the vendor profile's `looks_like_fixed_contract: false` sat at character 952. So the judge rejected a true claim, which forced a revision and used up the quota. Results are now shrunk by whole list items with every summary field kept (`fit_json`, shared with the Investigator).
  - **Triage scored real fraud as a false alarm.** The case counted as "spurious" because it touched no planted *split*. A case now counts as spurious only if it touches no planted anomaly of any type.

**Gemini as a provider (D-33).** You decided on Gemini's free tier for the Phase 9 evaluation runs, with Ollama later when there is disk space.
- **One line switches:** `LLM_PROVIDER=groq | gemini | ollama`. Each provider keeps its own key, endpoint and model (`GROQ_*`, `GEMINI_*`, `OLLAMA_*`), and an explicit `LLM_*` value still overrides. Your `.env` Groq entries were renamed to `GROQ_*` without touching the key, and an empty `GEMINI_API_KEY` was added.
- **Gemini's rate-limit wording** ("retry in 17.5s", `retryDelay`) is read. A per-day quota ends the run for resumption, even when it hints at a short wait.
- **Evaluation is per model:** progress and triage count only notes by the running model, so Groq and Gemini results never blend.
- **Caveats recorded:** Gemini free-tier prompts may be used by Google (fine for synthetic and public data, never for confidential records). Free-tier limits are per account and will be measured on first use.
- **Fixed along the way:** literal backspace bytes that had replaced a regex's `\b` word boundaries.

**Files:** `agent/investigator.py` (`fit_json`), `agent/verifier.py`, `agent/llm.py`, `config.py` (per-provider settings, `endpoint_for`), `db/store.py` (`latest_note` by model), `investigation.py`, `api/overview.py`, `.env.example`, tests in `test_verifier.py`, `test_investigation.py`, `test_llm.py`, and `docs/DECISIONS.md` (D-31 addendum, D-33).

**671 backend tests** (+7 live, opt-in) **and 29 frontend tests passing.**

---

## Current Phase

### Phase 9 — Evaluation, real data and freeze 🚧 in progress (started 2026-09-22)

Exit criterion: every number in `docs/EVALUATION.md` comes from a reproducible command, and the demo runs from a frozen state. Seven steps; those needing no LLM come first.

1. ✅ **Reproducible detector results** (`10639cc`, `9f592e4`). `spendguard report detection` re-runs every seed, the clean-data check and a determinism check, and writes `docs/results/detection.md` with the commit, settings and package versions that produced it. The means match the old hand-built table exactly. The spreads are now the sample standard deviation, a little wider than before. EVALUATION.md 4.0b cites the generated file.
2. ✅ **Live demo and frozen demo state** (`8d80df2`, D-34).
   - **Live demo:** `POST /demo/inject`, `spendguard demo` and the dashboard's "Live demo" page. It plants anomalies in a temporary copy of the last three months of clean data and catches them in 3–8 s. Misses are shown as misses (2 of 3 caught on rehearsal, as recall predicts). Verified in the running dashboard.
   - **Frozen state:** `spendguard freeze` and `spendguard serve --frozen`, a hashed snapshot served from a fresh copy. Re-freeze once verified notes exist.
3. ✅ **Ablation code** (`74c4537`, D-35). Three arms, each isolating one variable.
   - **Template notes** (`--ablation template`): a note filled from the detector's output and the rows it flagged, with no model writing it. It cites real rows and copies their values, so its citations pass the deterministic check - and every verdict is `likely_true_positive`, because a template cannot weigh an innocent explanation. That is what the arm isolates: the triage the agent adds, not the citations.
   - **Verifier off** (`--no-verify` in evaluation mode) is now labelled `no-verifier` automatically. It had to be: unlabelled, its unverified notes would have stood as the cases' own notes and quietly replaced the verified numbers the arm is measured against.
   - **Model size** needs no arm - a note records the model that wrote it and evaluation is already per model (D-33).
   - **Kept apart:** an arm's notes never stand as a case's note, never mark it investigated, never enter the agent's metrics, and resume on the arm's own notes. Each arm writes its own report and its own dashboard row, described from the run's own config snapshot rather than a label in the API.
   - **The Verifier still judges the template arm:** the arm removes the note's author, not its checking, or the citation columns would not be comparable.
   - **Verified on the real injected seed-42 database, with no API calls:** 5 of 5 notes written, all 35 citations existing and matching (100% deterministic), and the predicted triage profile - 100% of real cases kept, 0% of spurious ones filtered. Those notes are stored `unverified` because the smoke run used `--no-verify`; step 6 re-runs the arm judged, with `--again`.
   - **Fixed while building it:** a walrus in a comprehension shadowed the evaluation report and blanked the whole endpoint (caught by an existing test), and `test_llm_provider_defaults_to_groq` was reading the developer's `.env`, so it failed the moment this machine switched to Gemini - it now pins the code's default. Reading the generated notes also caught three wordings a panel would have: "at risk" means a different quantity per detector and now says which, identical duplicate amounts read as a list, and a one-day split run printed a date range twice.
4. ✅ **Grading kit.** `spendguard grade export | import | report`, and the rubric lives in code so it cannot be revised once the grades are in.
   - **The rubric** (your choice): five dimensions scored 0, 1 or 2 - factual accuracy, evidence sufficiency, innocent explanation considered, verdict justified by the note alone, actionability - each with a written anchor for every score. Three points rather than five, because three graders agree far better on three and an agreement number nobody believes makes the scores worthless. The third dimension is the one a template must score 0 on by construction, which is what makes the ablation visible.
   - **Blinding is enforced by a test, not by care.** Every file a grader receives is read and the test fails if the arm, model, verification badge, run id, note id or case id appears in it. Proved non-vacuous: adding the arm to one line of the export makes it fail with `notes.md leaks ['template', 'no-verifier']`.
   - **Graders see the rows a note cites.** Without them they can only grade fluency, which is what a language model is best at faking.
   - **Agreement is Krippendorff's alpha, ordinal** - it knows 0 against 2 is a worse disagreement than 0 against 1, which Fleiss' kappa does not. Implemented here and pinned to the published worked example (α nominal 0.691, ordinal 0.807), plus the properties relied on: random grading ≈ 0, worse-than-chance < 0, and a two-point gap punished harder than a one-point gap.
   - **The sample is seeded and spread over the arms first, anomaly types second**, so the comparison is not between sample sizes and no arm is flattered by drawing the easy types.
   - **Verified end to end** on the real seed-42 store: 7 notes exported across two arms, two sheets filled and imported, the report written. The scores were invented to exercise the pipeline, so they were **deleted afterwards** and `docs/results/grading.md` was removed - a results file holding made-up numbers is the exact failure this project is meant to avoid. The real batch belongs to step 6, when the note pool is big enough.
   - **One limitation that cannot be engineered away, and is printed in the report:** a template note is formulaic by definition, so a grader working through a batch can come to recognise that arm. Its scores are an upper bound on how well blinding held.
   - `data/grading/` is git-ignored: `key.json` is what unblinds a batch.
5. ✅ **California real data.** 346,018 purchase order line items ingested (336,995 loaded, 6.7 s), all four detectors run, and a review kit for the precision that unlabelled data allows.
   - **Three mapping judgements, each written into `california_po.yaml`** because a reader has to be able to check them: `invoice_no` is deliberately **unmapped** (the obvious candidate is a *document* id, and mapping it would have handed D1's exact-match stage 11,842 fabricated pairs before any scoring ran); `officer_id` holds the **department**, since the file names no person; `item_category` is UNSPSC **Family**, not Class (too thin) or Segment (too coarse).
   - **Finding 1 - D3's core assumption fails on a real taxonomy.** A typical synthetic item sits within 11% of its category median; a typical California item sits **5.63× away**. The same z-threshold that means "twice the going rate" on one dataset means "1,031,569× the median" on the other, so D3 flags **1 row in 333,291**. Re-grouping at every level available shows the taxonomy is the problem, not the threshold: even the finest 8-digit UNSPSC code needs a 9,550× markup, and only comparing the *same item description* gets it to 41-100× - covering 23-35% of rows, not all. Nothing was re-tuned (convention 6). **This is the evidence O-05 was waiting for**, and it is now recorded there.
   - **Finding 2 - a duplicate detector on line-item data needs the document boundary.** 5,973 of D1's 12,257 flags (**48.7%**) pair two line items of the *same* purchase order. The synthetic generator emits one row per transaction, so this failure mode cannot appear there. Raised as **O-07** rather than fixed quietly: giving detectors a document id is a schema decision, not a tuning one.
   - **Finding 3 - the pinned rate is doing visible work.** At ₹60/USD, **49.8%** of line items land at or above the ₹2,50,000 approval threshold, against a median line of $3,600. The rate is pinned, dated and stated in the mapping for exactly this reason.
   - **The review kit** (`spendguard review export | import | report`): the sample is drawn and recorded *before* any verdict exists; `unclear` is a first-class answer kept out of the ratio; every ratio carries a **Wilson** interval, pinned in tests against the values the normal approximation gets wrong; reviewers see the **document number** that detectors never see. Verdicts land in `flag_reviews`, apart from the operational review workflow (D-04), so a measurement cannot be disturbed by someone working the queue.
   - **Also fixed:** `spendguard detect --store` now exists - without it a second dataset's cases landed on top of the operational ones. And a real item description of six lines of contract prose was silently destroying the review table; cells are now flattened, pipe-escaped and truncated, with a test that counts cells per row.
   - `data/review/` is git-ignored.
6. 🚧 **Agent evaluation — in progress.** The infrastructure is done and committed; the numbers accumulate against a daily quota and are not complete.
   - **Gemini is out, and not on quota (D-37).** Every model its free tier serves fails: the 2.5 family returns 404 "no longer available to new users" (while still being *listed* for the key), and every 3.x model returns 400 "Function call is missing a `thought_signature`". Gemini 3.x issues a thought signature with each function call and wants it back when the conversation is replayed; the OpenAI-compatible schema has nowhere to put it. So the **first** tool call succeeds and the **second turn** fails — which is every turn after the first in a tool-calling loop. A seed-42 run produced **0 notes from 3 attempts**. D-33's provider switch is unchanged and still right; only its recommendation moved. The evaluation runs on **Groq**.
   - **`check-llm` had called Gemini healthy**, because it asked for one tool call and stopped. It now completes a **second turn** — handing the tool call and a result back and requiring the model to continue, which is the shape the Investigator actually uses. Two extra calls; it would have caught this in ten seconds instead of hours into a run. A model that replies in prose instead of calling the tool now fails the check rather than warning.
   - **`spendguard report agent`** assembles the results table. Detection regenerates from one command because it is deterministic; agent results do not — they accumulate a few notes a day across three seeds, three arms and however many models, and no single run holds them all. So the table is read from the evaluation stores: citation validity and cost from the notes themselves (newest per case, model and arm), triage from the run that drew that arm's sample and already scored it. Ten tests pin what it must never do: merge two models into one row (D-33), count an arm's notes as the agent's (D-35), blend the rule-checked number into the model-judged one (D-13), attach a stale run's triage to another arm, report a spread from one seed, or print a rate from a still-filling sample without saying so.
   - **Your call encoded as a plan.** Seed 42 thoroughly and with every arm (3 per type); held-out seeds 7 and 2026 narrowly on the main arm (1 per type). Five runs, in `AGENT_EVAL_PLAN`. `spendguard investigate --matrix` walks them in order and stops the moment quota runs out; running it tomorrow continues from there. A test checks the plan names only real seeds and known arms, and that the held-out seeds stay narrower and main-arm only — a typo there costs a day of quota, not a test run.
   - **Two defects the run exposed, both fixed.**
     - **Widening a sample re-drew it.** Going from 1 case per type to 2 kept **1 of 5**; the other four already-investigated cases were orphaned. For a project accumulating ~10 investigations a day that meant never widening without discarding work — exactly what "thorough on seed 42" needs. Each pool is now shuffled once from a seed independent of how many are drawn, so the sample for 3 contains the sample for 1. Verified on real seed-42 data for 1→4, pinned by a test. One-time cost: the new draw excludes the 2 agent notes already stored.
     - **`LLM_MAX_TOKENS` exceeded Groq's *output* ceiling**, and was silently eating the run. Every failing case ended on a 429 that was not congestion: "Request too large … output tokens per minute (OTPM): Limit 1000, Requested 1025 … reduce max_tokens". We asked for 2048, so notes were refused *before being written*, and the generic 429 path retried three times — three more calls on a request that could never succeed. Cap is now 900 and that class of 429 raises at once, naming the setting. The output-side twin of the 413 input limit (D-30), recorded beside it: **a free tier has several independent ceilings, and the one you have not hit yet is the one that stops the run.**
   - **A third defect, from the first matrix run: nothing bounded tool use.** The first case called `calculator` **58 times** across 19 turns, wrote no note, and died on the context budget - two minutes and a slice of the day's quota for nothing. `AGENT_MAX_STEPS` bounds model *turns*, and one turn can request several tools, so it never applied. `AGENT_MAX_TOOL_CALLS` (24) and `AGENT_MAX_CALLS_PER_TOOL` (8) now bound it, refused as an ordinary tool error naming the count so the agent can still write its note from what it has (convention 7). Proved non-vacuous: with the check disabled the same scripted loop makes 18 calls instead of 8.
   - **A fourth, self-inflicted: capping output below the ceiling truncated the notes.** Setting `LLM_MAX_TOKENS` to 900 to stay under Groq's 1,000-token output ceiling looked right, but real notes had been reaching **1,016-1,026** tokens — so 900 did not make them fit, it cut them off. A note truncated mid-JSON parses as *every field missing*, which reads like a model ignoring its schema, and the retry said "fix the note", asking for the same too-long note again. Result: 2026-09-29's quota produced **0 notes** from 3 cases. The cap now sits just under the ceiling (990), truncation is detected from `finish_reason`, recorded on the parse error, and answered with feedback the model can act on. **The symptom pointed at the wrong cause** — two days of failures looked like a model that could not follow a schema.
   - **The real cause of the lost days, found by measuring instead of guessing (2026-09-29).** Four days of runs had produced three notes. Counting tokens *per case* rather than per run showed why: one inflation case had taken **214,892 tokens across 132 tool calls and 44 model turns** — more than a whole day's quota — and never written a note. A successful note costs 2,000–23,000. Three defects, none of which the tool-call budget touched:
     - **No ceiling on a whole case.** There was a per-*request* context budget but nothing bounding an investigation. `AGENT_MAX_CASE_TOKENS` (30,000) now stops one and gives it a final turn to write the note from what it has.
     - **The tool budget was handed back on every revision** — the counter lived inside `_gather`, and `revise()` starts another one, so a case that had made 24 calls could make 24 more, twice over. It now lives on the result.
     - **A failing case kept its place at the front of the queue.** The sample is severity-ordered and worked through over days, so the worst case was retried *first every single day*, spent the quota, and starved everything behind it. Pending cases are now ordered by attempts first.
     - The third is what cost the four days, and it is the one nobody was looking for: the calculator loop and the truncation bug were both real, both fixed, and both irrelevant while one case owned the queue. Each fix is pinned by a test that was **verified to fail when the fix is removed**.
   - **Runs so far, honestly:** 2026-09-28 produced 0 notes (the calculator loop, then quota); 2026-09-29 produced 0 notes (truncation, then quota). The tool budget did work — the looping case fell from 58 tool calls to 23 — but the truncation bug meant it still wrote nothing. Seed 42 stands at **3 agent notes of 15**.
   - **Also:** a 503 "high demand" used to back off 1s then 2s and give up, losing a case that would have succeeded a minute later; an overloaded provider now gets its own schedule (5s, 15s, 45s, 60s).
   - **Where the numbers stand** (`docs/results/agent.md`, regenerate with `spendguard report agent`): seed 42 has **3 agent notes** against a sample of 15, plus 15 template-arm notes from an earlier, narrower draw. Far too few to read as rates, which the report says on its face — **nothing here is a reported result yet.** The held-out seeds have no store at all. The remaining runs are calendar time rather than work: `spendguard investigate --matrix`, once a day, until the plan is complete. A run is in progress as of 2026-09-29.
   - **Third time now:** D-26 lost a retired Llama model, D-33 chose Gemini, D-37 lost Gemini to an API change. Free-tier model availability is not a stable foundation — an argument *for* the Ollama local-runtime proof, not for postponing it.
7. 🚧 **EVALUATION.md, the freeze and the walkthrough — started.**
   - ✅ **Every number traced to a command, and checked rather than promised.** Section 4.0b already carried a "Source:" line and "do not edit these figures by hand" — but that was an honour system: the numbers live in the prose *and* in `detection.json`, and two copies of a number drift. `spendguard check-evaluation` parses the figures back out of the document and fails on any that disagrees with the generated file beyond rounding. Same move as the policy/config agreement check, for the same reason. Proved non-vacuous: a one-figure edit (D1's F1 0.949 → 0.984) is caught and named. It also fails loudly when it finds *no* sourced table at all, because a check that silently passes having checked nothing is worse than none.
   - **Deliberately not checked:** section 4.0a, the Phase 3 snapshot. It carries no "Source:" marker, and a historical record should not be rewritten every time a detector changes. It is now labelled as superseded.
   - ✅ **The headline sentence, generated rather than typed** (`spendguard report headline` → `docs/results/headline.md`). It is the most-copied figure in the project and so the most likely to be quoted from a run that has since been redone, so every number in it names the results file it came from.
     - **The sentence as originally specified would have been misleading, and is not the one used.** EVALUATION 8 read "On N **real** transactions with M injected anomalies…" — but injection runs on the *synthetic* dataset, and the real California data is never injected into. One sentence covering both reads as though the F1 had been achieved on real procurement. The two datasets are now named separately, and a test asserts the detection clause never says "real transactions".
     - **A rate is withheld, not rounded, when the sample is too small.** Below `HEADLINE_MIN_NOTES` (20) citation validity is reported as provisional with its sample size attached — right now that reads "100.0% over only 3 note(s)", which is the honest form. An unmeasured figure says so rather than leaving a gap to fill from memory.
     - **Citation validity is weighted by citations, not by run**, so a two-note run cannot count as much as a forty-note one; ablation arms never enter it.
   - ✅ **A system-level comparison to quote.** The per-detector table deliberately has no pooled row for D1–D4 (`owns`: D1's F1 of 0.000 on splits is true and meaningless), but "SpendGuard against the baseline" is a real question and the baseline already had an `all` row. The suite now has one: **F1 0.689 ± 0.006 against the baseline's 0.205 ± 0.007**, pooled from *counts* rather than by averaging four F1 scores — averaging ratios would weight D4's eight vendor cases the same as D1's two hundred duplicates. No pooled PR-AUC: one ranking across four independent scorers is not a meaningful quantity.
     - **`check-evaluation` was silently skipping that row.** Its PR-AUC cell is `-`, and the parser required *every* cell to parse before checking any — so the most-quoted number in the document was the one number not being checked. A row now counts if any cell is a figure, and the `-` cells are skipped individually. Caught by testing the check against its own new row.
   - 🚧 **The final freeze — mechanism proved, the shipping snapshot still waits on notes.** `spendguard freeze --seed 42` and `spendguard serve --frozen` had unit tests but had never been run end to end, and DEMO.md tells the presenter to depend on them. Run for real: 4 files hashed into an 8.5 MB snapshot, the dashboard served from a fresh copy of it (511 cases, 3 investigated, **0 verified**), a case confirmed with a reviewer note through the API, the server relaunched — and the case came back `new` with a null note, with `verify()` confirming all four hashes unchanged. That is the property the demo rests on, now demonstrated rather than asserted.
     - **The shipping freeze is deliberately not taken yet.** The current snapshot holds three notes, none `verified` and one `failed_after_retries`. Freezing that would undercut the demo it exists to support — the case page with a verification badge is DEMO.md's centrepiece. Re-freeze once step 6's notes land.
     - A `dashboard-frozen` launch config now sits beside `dashboard-eval-42`, on port 8001, so the frozen state can be rehearsed without disturbing the live one.
   - ✅ **The demo walkthrough** ([docs/DEMO.md](docs/DEMO.md)). What to run, in what order, what to say, and what to do when something fails in front of people. Three things it insists on, because each is a place a demo goes wrong: serve the **frozen** state rather than a live store (notes come from a model and a rerun does not reproduce them word for word); **show a dismissal**, because a case the agent called a false positive is the strongest single artefact the project has; and **let the live injection miss**, saying "that is the detector's measured recall" rather than re-rolling for a better seed. It ends with the questions a panel will ask and an honest answer to each, including "your D3 is worse than the baseline" — which it is, on F1, and the report says so.

### Between steps — CI had been red since Phase 5 (`1603324`)

Found by checking after a push rather than assuming. **Ten consecutive runs failed**, from the Phase 5 commit that introduced the `agent` extra right through to Phase 9, while CLAUDE.md said "CI, every push" as though it were green. The frontend job passed throughout; the backend job failed at *Tests*.

- **Cause:** CI installs `dev,detect,api` and the `agent` extra pulls PyTorch, so it was excluded — but `openai` lives in that same extra. 24 of `test_llm.py`'s tests construct an `LLMClient` and so could not run at all. Two more failed for related reasons: `test_api.py`'s health test monkeypatches `openai.OpenAI`, and one policy-RAG test built a real index without the `importorskip` guard its neighbours have. **26 failures.**
- **Fix:** the extra is split. `llm` (openai, tiktoken) is a few megabytes and CI now installs it, so the rate-limit, quota and retry logic — including everything changed this week — is actually exercised there. `agent` keeps the heavy retrieval half and the handful of tests needing it skip. The missed guard was added.
- **Verified** by simulating CI's environment locally (blocking the heavy packages at import): **791 passed, 14 skipped, 0 failed**, against 26 failures before.
- **So it cannot rot silently again:** a CI badge now sits at the top of the README, and CLAUDE.md states what CI installs and says plainly that it was red for four phases because nobody looked.

## Next Steps

**Nothing is blocking.** `LLM_PROVIDER=groq` is set and passes `spendguard check-llm`, including the new second-turn check. Steps 1-5 are complete; step 6 needs only calendar time.

1. **Run `spendguard investigate --matrix` once a day** until the plan is complete — about ten investigations a day (D-30), so roughly a week. It stops itself when the quota is spent and continues from there next time. `spendguard report agent` rewrites `docs/results/agent.md` from whatever has landed.
2. **Then step 7:** final numbers traced to commands, the headline sentence, the final freeze, the demo walkthrough.
3. **Three decisions, none blocking.** **O-04** (implemented as recommended, awaiting confirmation); **O-05** (D3 pseudo-categories — now has measured evidence, EVALUATION 4.0c Finding 1); **O-07** (a document id for detectors — EVALUATION 4.0c Finding 2).
4. **Later, when there is disk space:** install Ollama and `ollama pull qwen2.5:3b-instruct-q4_K_M`, then `LLM_PROVIDER=ollama`. D-37 makes this more valuable than it looked: three free-tier models have now been lost to retirement or an API change, so the local proof is the only runtime nobody else can withdraw.
5. **Housekeeping:** `main` matches GitHub as of `3a17a05`; later commits still to push.
