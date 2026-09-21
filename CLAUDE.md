# CLAUDE.md — SpendGuard

> Persistent context, loaded every session. Keep it short. Detail lives in `docs/`.
> **Status:** Phases 0–6 complete · 595 tests passing · currently on Phase 7 (Verifier).
> Running log: [PROGRESS.md](PROGRESS.md).

---

## 1. Project overview

SpendGuard audits **100% of an organization's procurement transactions**, detects four classes of fraud or error, then **autonomously investigates prioritized cases** and produces an evidence-cited audit note that a second agent verifies before release. Existing tools stop at a risk score; the contribution here is the layer *after* detection — automated investigation with machine-verified citations, open-source and fully local. Final-year capstone, 3 people, zero budget, everything runs on a laptop GPU or a free Colab T4.

**One line:** existing tools flag suspicious transactions; SpendGuard investigates them and hands the auditor a finished, verified case file.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ (dev machine runs 3.13) |
| Analytical store | **DuckDB** — transactions, detector output, evaluation results |
| Operational store | **SQLite** via SQLAlchemy 2.0 — cases, review status, notes, runs. Postgres is a one-line `DATABASE_URL` swap |
| Data | Polars (primary), pandas, PyArrow |
| Detection / ML | numpy, scikit-learn, PyOD, scipy, rapidfuzz |
| Agent | openai SDK (any OpenAI-compatible endpoint), sentence-transformers `bge-small-en-v1.5`, FAISS |
| Config | Pydantic v2 + pydantic-settings |
| CLI | Typer + Rich |
| Planned | FastAPI + React 18/TypeScript/Vite/TanStack Query (Phase 8), MLflow (Phase 9) |
| Tooling | pytest, ruff, mypy, GitHub Actions |

**LLM plan (forced by hardware):** the dev machine has a 4 GB RTX 2050, so a 7B model does not fit. Groq free tier for development, model **`qwen/qwen3.8-27b`** (Groq retired Llama 3.3; Qwen chosen so prompts transfer — D-26); **Qwen2.5-3B-Instruct Q4_K_M** via Ollama for the "fully local" proof; 7B on a free Colab T4 for the model-size comparison. `spendguard check-llm` verifies both chat and tool calling.

---

## 3. Folder structure

```
SpendGuard/
├── CLAUDE.md, PROGRESS.md, README.md
├── backend/
│   ├── pyproject.toml          deps in phase-scoped extras, ruff/mypy/pytest config
│   ├── mappings/*.yaml         per-dataset column mappings (never hardcode columns)
│   ├── src/spendguard/
│   │   ├── config.py           SINGLE source of truth for every tunable value
│   │   ├── policy_check.py     parses policy.md thresholds; fails build on drift
│   │   ├── cases.py            Case model, AnomalyType, severity (D-02, D-08)
│   │   ├── cli.py              generate · ingest · detect · inject · evaluate ·
│   │   │                    investigate · check-llm · check-policy
│   │   ├── detection.py        `spendguard detect` orchestration → case store
│   │   ├── investigation.py    `spendguard investigate`: top-N from the store, or eval mode
│   │   ├── db/duck.py          DuckDB schema, audit_transactions view, writers
│   │   ├── db/store.py         case store, review workflow, notes · citations · traces
│   │   ├── pipeline/           synthetic generator, ingestion, vendor normalization
│   │   ├── detectors/          base · baseline · d1_duplicates · d2_splits
│   │   │                    d3_inflation · d4_vendor
│   │   ├── eval/               injection harness · matching · metrics · runner · triage
│   │   ├── agent/              llm (provider switch) · tools (the six) · policy (RAG)
│   │   │                    note (schema) · prompts · investigator (the loop)
│   │   │                    verifier is Phase 7, next
│   │   └── api/                (empty — Phase 8)
│   └── tests/                  mirrors src; 595 tests (+6 live, opt-in)
├── docs/                       DESIGN · REQUIREMENTS · ARCHITECTURE · DATA-SCHEMA
│                               API-CONTRACT · EVALUATION · TEST-CHECKLIST
│                               DECISIONS (binding) · PHASE-PLAN
├── policy/policy.md            authored procurement policy; the RAG corpus
└── data/                       raw · processed · frozen (all gitignored)
```

---

## 4. Conventions and rules

**Non-negotiable**

1. **Nothing is hardcoded.** Every threshold, path, model name and knob lives in `config.py` and is overridable from `.env`.
2. **Policy and config must agree.** Threshold figures appear in `policy/policy.md` *and* `config.py`; a test parses the policy and fails on drift. If the agent cites a clause stating a different number from the detector that raised the case, the citation guarantee is dead.
3. **Detectors read `audit_transactions`, never `transactions`.** The view hides the injection answer key and `source_row_ref`. A test parses every detector module and fails on any reference to a hidden column.
4. **Everything is seeded and deterministic.** Same seed and input → identical output, same order. Sort SQL that feeds output: DuckDB's parallel `GROUP BY` is unordered.
5. **Evaluate on clean data too.** Metrics on injected data alone hid a bug that flagged 1,732 false duplicates.
6. **Tune on the dev seed (42) only**; report on held-out seeds (7, 2026).
7. **Agent tools never raise.** A failure is `{"error": ...}` the model can read and recover from.
   Tools read `audit_transactions` only, through a read-only connection.
8. **The agent never changes review status.** It writes a note, a verdict and `severity_final`;
   only a person moves a case (D-04). Every request fits `AGENT_CONTEXT_TOKENS` (D-30).
9. **Live LLM tests are opt-in** (`-m llm`). The default suite and CI never call a rate-limited API.

**Style**

- Type hints on public functions; `from __future__ import annotations`; ruff line length 100.
- Every detector implements `detect(con) -> list[Case]` and is registered in `detectors/__init__.py`.
- Docstrings explain **why**, especially where a naive approach was tried and failed.
- Prefer readable over clever — this code gets explained in a viva.
- Tests name the behaviour, not the function (`test_routine_buying_does_not_chain_into_one_sprawling_run`).
- Money is INR, displayed with Indian digit grouping via `settings.money()`.

**Wording discipline (honesty; a panel will check)**

- "duplicate **transaction records** (POs or payments, depending on the source system)" — never "duplicate payments" on PO data.
- "Detects across 100% of transactions, then autonomously **investigates prioritized cases**" — never "investigates every flagged case".
- Never claim better raw detection accuracy than commercial tools.

---

## 5. Key commands

```bash
spendguard generate                  # seeded synthetic INR dataset -> data/raw/
spendguard ingest <csv>              # clean, normalize, load DuckDB + dataset card
spendguard detect                    # D1-D4 over 100% of rows -> case store
spendguard inject --seed 42          # plant known anomalies in a copy -> ground truth
spendguard evaluate --seed 42 --detector baseline --detector d1 --detector d2 --detector d3 --detector d4
spendguard investigate --top 10      # Investigator on the 10 highest-severity open cases
spendguard investigate --eval-seed 42 --per-type 2   # triage accuracy on planted anomalies
spendguard check-llm                 # endpoint answers, and tool calling works
spendguard check-policy              # policy.md and config.py agree?
```

The venv is at `.venv`; with it active the bare `spendguard` command works, otherwise use `./.venv/Scripts/spendguard.exe`.

```bash
./.venv/Scripts/python.exe -m pytest backend                          # tests (offline)
./.venv/Scripts/python.exe -m pytest backend -m llm                   # live LLM tests, minutes
./.venv/Scripts/python.exe -m ruff check backend/src backend/tests    # lint
./.venv/Scripts/python.exe -m ruff format backend/src backend/tests   # format
./.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/src
./.venv/Scripts/python.exe -m pip install -e "./backend[dev,detect,agent]"  # install
```

CI runs lint → format check → mypy → pytest on every push.

---

## 6. Environment and setup

Copy `.env.example` to `.env` (gitignored). Names only, no secrets in the repo:

- **Reproducibility:** `RANDOM_SEED`
- **Currency:** `CURRENCY` (INR)
- **Policy thresholds:** `APPROVAL_THRESHOLD`, `DIRECT_PURCHASE_CEILING`, `LIMITED_TENDER_CEILING`, `DUPLICATE_AMOUNT_TOLERANCE`, `DUPLICATE_DATE_WINDOW_DAYS`, `SPLIT_WINDOW_DAYS`, `PREPAYMENT_LOOKBACK_DAYS`, `NEW_VENDOR_DAYS`, `PRICE_HISTORY_MONTHS`
- **LLM (Phase 5+):** `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TEMPERATURE`, `AGENT_MAX_STEPS`, `AGENT_CONTEXT_TOKENS`, `VERIFIER_MAX_RETRIES`, `INVESTIGATE_TOP_N`
- **Stores:** `DATABASE_URL` (defaults to SQLite under `data/processed/`)

The Groq key is set and verified (`spendguard check-llm`). Outstanding manual steps: **Ollama + Qwen2.5-3B** before the local-runtime proof, and the **Kaggle California PO dataset** into `data/raw/` before Phase 9.

The `agent` extra pulls PyTorch (via sentence-transformers) and is a large download. CI installs only `dev,detect`, so tests needing the embedding model or a key skip there rather than fail.

---

## 7. Important decisions

Full log with rationale in [docs/DECISIONS.md](docs/DECISIONS.md) (D-01 … D-30). The ones that shape day-to-day work:

- **D-02** A *case* is one anomaly group, not a row. Metrics are per case, with per-row secondary.
- **D-04** The agent may overrule a detector (`likely_true_positive` / `likely_false_positive` / `inconclusive`) but never closes anything. Humans decide.
- **D-05** Detection covers 100% of rows; **investigation is top-N by severity** (LLM-bound: 1–3 min
  per case on the Groq free tier, measured in Phase 6).
- **D-09** DuckDB (columnar, analytical) + SQLite/Postgres (transactional). No Node backend, no Django: DuckDB is embedded, so a second runtime buys nothing and Django's ORM cannot address it.
- **D-12** `vendor_key` is for **blocking**, never identity. Measured: 0 suppliers split, 10 of 382 keys over-merged.
- **D-15/16** Currency INR; principal control threshold **₹2,50,000** (GFR 2017 ladder, policy SG-PP-2.2).
- **D-19** D1 blocks on **amount + date**, not vendor key — a typo in a name must not hide a duplicate. Log-bucket join, set-identical to brute force, 300× faster.
- **D-20** D1 scores pairs with a **Fellegi–Sunter model fitted by MAP-EM**: data-driven, explainable per field, and priors stop EM inventing a duplicate class when there are none.
- **D-21** D2 takes minimal runs, four equally weighted policy indicators, threshold picked on the dev seed only.
- **D-23** D3 ties the baseline on F1 and wins on ranking; legitimate premium and urgent purchases
  share the injected price band, which is why the investigation layer exists. It never reads the
  item description — a fraudster writes that too.
- **D-24** D4 tests each supplier against its *peers*, not against Benford (which accused 61 of 210
  real suppliers), combines tests with Fisher, and controls FDR across suppliers.
- **D-27** Policy retrieval is dense embeddings; BM25 and hybrid were built, measured and lost.
  Chunk on clause boundaries — half a clause reads as authoritative and is incomplete.
- **D-28** Agent tools: read-only connection, a view without the answer key, a validated
  single-SELECT, and errors returned as data.
- **D-29** Notes are structured claims (`row_ids` + checkable `facts`), so the Verifier checks
  data, not prose. The prompt shows one example of the case's type and asks for the innocent
  explanation first.
- **D-30** Groq free tier: ~8k input tokens/min and **200k tokens/day (~10 investigations)**.
  The client waits as long as a 429 asks; the loop trims the bulkiest old tool results to fit
  the token budget; a spent daily quota stops the run, and the next run resumes.
- **O-04** implemented as recommended (the number moves with the band), awaiting confirmation.
  **O-05** open.
