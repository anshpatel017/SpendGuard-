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

### Phase 4 — D3 + D4 ✅

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

## Current Phase

### Phase 5 — Agent tools and policy RAG 🚧 not started

- The six tools: `query_transactions` (read-only, row-capped), `vendor_profile`, `find_similar_invoices`, `policy_lookup`, `benford_stats`, `calculator`. Each with a JSON schema and its own tests.
- Policy RAG over `policy/policy.md`: chunk on clause boundaries so a retrieved clause is complete, embed with `bge-small-en-v1.5`, index with FAISS.
- LLM client behind the `LLM_PROVIDER` switch so the same code runs against Groq now and Ollama later.
- Exit criterion: every tool callable and unit-tested standalone, and `policy_lookup` returns the right clause for a paraphrased query that shares no keywords with the clause text.

**This is the first phase that needs an LLM.** See Next Steps.

## Next Steps

1. **Phase 4 now** — build D3, then D4, evaluate on seeds 42 / 7 / 2026 plus clean data, update this file, commit.
2. **Before Phase 5** — you create a free **Groq API key** at console.groq.com/keys and paste it into `.env` as `LLM_API_KEY`. Phases 0–4 need no LLM at all.
3. **Before the local-runtime proof** — install Ollama and `ollama pull qwen2.5:3b-instruct-q4_K_M`.
4. **Before Phase 9** — download the Kaggle "Large Purchases by the State of California" CSV into `data/raw/`.
5. **Still open for you to decide:** **O-04** (when the agent drops a case to Low, does `severity_final` become a number below 33 or does only the band move?) and **O-05** (are D3 pseudo-categories from description clustering core or deferred?).
6. **Housekeeping:** all work sits on `main` and is committed locally but **not pushed**. Say the word and I will push, or set up a branch-and-PR flow.
