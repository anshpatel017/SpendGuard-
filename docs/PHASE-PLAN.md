# Build Plan

> **Status lives in [PROGRESS.md](../PROGRESS.md)**, which is the running log and the
> authoritative phase list (10 phases, 0-9: this document's Phase 8+9 are merged into
> Phase 8, and Phase 10+11 into Phase 9). This file keeps the detail behind each phase.

Phases, not weeks. Each phase ends with something that runs and something that is committed.

A phase is **done** when its exit criterion is demonstrably true — not when the code exists.

---

## Environment this project is built on

Recorded because two findings changed the plan.

| | Value | Consequence |
|---|---|---|
| Python | 3.13.5 | Splink may lack wheels. It is optional (D-12), so this is not a blocker. |
| Node / npm | 22.15 / 11.1 | React is fine. |
| **GPU** | **RTX 2050, 4 GB VRAM** | **A 7B model does not fit.** See below. |
| **RAM** | **7.7 GB** | No Docker Desktop. Avoid whole-dataset pandas loads; use DuckDB and Polars streaming. |
| Docker | not installed | Operational store is **SQLite**, not PostgreSQL (D-09 fallback). |
| Disk | 80 GB free | Ample. |

### LLM strategy forced by 4 GB VRAM

The design documents assume a 16 GB T4 running Qwen2.5-**7B** (~5–7 GB). That will not run here.

| Purpose | Model | Where |
|---|---|---|
| Development and iteration | Llama 3.3 70B | Groq free tier — fast, free, no GPU |
| "Fully local" proof | **Qwen2.5-3B-Instruct Q4_K_M** (~2.2 GB) | Ollama on the RTX 2050 |
| 7B comparison numbers | Qwen2.5-7B-Instruct Q4_K_M | Free Colab T4 |

This turns the stretch-goal model-size study into something obtained for free: **3B local vs 7B on T4**. The constraint becomes a contribution.

---

## Phases

### Phase 0 — Foundation

Repo scaffold, virtual environment, dependency groups, configuration module, `.gitignore`, pytest, CI.

Also implements **FR-2.14** immediately: a parser that reads the threshold summary out of `policy/policy.md` and a test asserting it equals `config.py`. Building this first means the policy and the code can never silently drift.

**Exit criterion:** `pytest` passes, including the policy/config agreement check, and CI runs on push.

---

### Phase 1 — Data

- INR-native synthetic transaction generator (Faker), seeded
- Ingestion pipeline: load → map columns → clean → coerce types → normalize vendors → DuckDB
- Vendor normalization with the blocking/identity separation (D-12)
- Stable `row_id` assignment
- Dataset card generation

**Exit criterion:** `transactions` populated with stable `row_id`s, dataset card written, re-ingestion reproduces identical ids.

---

### Phase 2 — Ground truth and baseline

- Injection harness for all four anomaly classes, fixed seeds (FR-7.1, FR-7.2)
- Rule-based baseline detector (FR-2.10)
- Evaluation skeleton: case matching rules for row-groups and for vendor-level cases (D-03)

**Exit criterion:** a first metrics table — baseline scored against injected ground truth, reproducible from a seed.

---

### Phase 3 — D1 and D2

- D1 duplicates: exact → fuzzy with raw-name confirmation
- D2 split purchases: rolling-window SQL over the three windows
- Case creation into SQLite with `detector_score`, `amount_at_risk`, `severity_prelim`

**Exit criterion:** both detectors beat the baseline on precision, recall and F1, per case and per row.

---

### Phase 4 — D3 and D4

- D3 price inflation: per-category median/MAD, plus Isolation Forest second opinion
- D4 vendor red flags: Benford chi-square, round-number ratio, period-end clustering, new-vendor-high-value
- Severity scoring and the ranked case queue

**Exit criterion:** all four detectors emit cases in the common schema with severity bands assigned.

---

### Phase 5 — Agent tools and policy retrieval

- The six tools, each with a JSON schema and its own tests
- `query_transactions` constrained to reads, row-capped
- Policy RAG: clause-boundary chunking, embeddings, FAISS index
- LLM client abstraction over the provider switch

**Exit criterion:** every tool callable and unit-tested standalone; `policy_lookup` retrieves the right clause for a paraphrased query.

**Manual step required — see below.**

---

### Phase 6 — Investigator

- The bounded tool-calling loop
- Audit note JSON schema, few-shot examples per anomaly type
- Trace logging of every step

**Exit criterion:** a case goes in, a schema-valid cited audit note comes out, with a full trace stored.

---

### Phase 7 — Verifier

- Citation extraction
- Deterministic checks: row exists, stated values match
- Semantic check: does the row support the claim
- Regeneration loop with failures fed back

**Exit criterion:** citation validity measured on a real run and reported as two separate numbers (D-13).

---

### Phase 8 — API

FastAPI, Pydantic models, the ten endpoints in [API-CONTRACT.md](API-CONTRACT.md), DuckDB opened read-only.

**Exit criterion:** `/docs` live, every endpoint serving, OpenAPI schema matching the contract.

---

### Phase 9 — Frontend

React + TypeScript, types generated from OpenAPI, TanStack Query and Table, case queue, case detail with evidence and citations, trace timeline, metrics view, status workflow.

**Exit criterion:** the full workflow is clickable end to end — browse, open, read, inspect evidence, view trace, change status, add note.

---

### Phase 10 — Evaluation

Full runs across multiple seeds, both ablations (Verifier off, template notes), blinded note grading, MLflow logging, adjusted-precision review of top-k unlabeled flags.

**Exit criterion:** results and ablation tables complete, every number traceable to a logged run.

---

### Phase 11 — Real data and freeze

California PO dataset ingested with pinned-rate INR conversion, money-at-risk headline run, frozen demo snapshot, live-injection demo rehearsed, fallback video recorded.

**Exit criterion:** [TEST-CHECKLIST.md](TEST-CHECKLIST.md) section 12 fully ticked.

---

## Manual steps

Things that cannot be automated. Each is listed against the phase that needs it.

### Anytime — dataset download (not blocking)

1. Create a free account at [kaggle.com](https://www.kaggle.com)
2. Search **"Large Purchases by the State of California"**
3. Download the CSV
4. Place it in `data/raw/`

Needed for Phase 11. Development runs on synthetic INR data until then.

### Before Phase 5 — Groq API key

1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Sign in with Google or GitHub — free, no card
3. Create an API key and copy it
4. `cp .env.example .env`
5. Paste the key into `LLM_API_KEY=` in `.env`

`.env` is gitignored. Never commit the key.

### Before the local-runtime proof — Ollama

1. Download from [ollama.com/download](https://ollama.com/download) and install
2. Pull the model that fits 4 GB VRAM:
   ```bash
   ollama pull qwen2.5:3b-instruct-q4_K_M
   ```
3. Switch the commented Ollama block in `.env` on, and comment the Groq block out

### Before Phase 10 — Colab for 7B numbers

Only needed for the model-size comparison. A free Colab T4 notebook running Ollama with the 7B model, pointed at by `LLM_BASE_URL`.

---

## Standing rules

1. **No new features once Phase 9 is complete.** Remaining effort goes to evaluation and hardening.
2. **The demo runs on a frozen snapshot**, never a live code path.
3. **Every stochastic step takes a seed.** Reproducibility is graded.
4. **Policy and configuration must agree** — enforced by test, not by discipline.
5. **Wording discipline:** "duplicate transaction records", never "duplicate payments" on PO data. "Detects across 100% of transactions, then autonomously investigates prioritized cases", never "investigates every flagged case".
