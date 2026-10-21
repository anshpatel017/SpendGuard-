# Architecture

## 1. Shape of the system

SpendGuard is a **Python system with a React presentation layer**. The expensive work — detection over every row, and LLM investigation at roughly 30-60 seconds per case — runs in **offline batch scripts** that write their results to storage. The API and the frontend only read finished results and write small state updates.

That single decision is what keeps the serving layer thin: nothing slow ever happens inside an HTTP request.

```
+---------------------------------------------------------------+
|  FRONTEND                                                     |
|  React 18 + TypeScript (Vite)                                 |
|  TanStack Query - TanStack Table - Tailwind + shadcn/ui       |
|  Recharts - React Router - Zod                                |
+------------------------------+--------------------------------+
                               |  HTTP / JSON
                               v
+---------------------------------------------------------------+
|  API                                                          |
|  FastAPI + Pydantic v2 (OpenAPI published)                    |
|                                                               |
|   +-- SQLAlchemy 2.0 --------> PostgreSQL                     |
|   |                            cases, status, notes, traces   |
|   |                                                           |
|   +-- duckdb (read_only) ----> DuckDB                         |
|                                transactions, evidence rows,   |
|                                detector output, eval results  |
+---------------------------------------------------------------+
                               ^
                               |  written by batch runs
+------------------------------+--------------------------------+
|  OFFLINE PIPELINE (CLI)                                       |
|                                                               |
|  ingest  ->  detect  ->  investigate  ->  verify  ->  evaluate|
|                                                               |
|  pandas / Polars - scikit-learn - PyOD - rapidfuzz - Splink   |
|  scipy - sentence-transformers + FAISS - MLflow               |
|  Ollama serving Qwen2.5-7B-Instruct (Q4_K_M)                  |
+---------------------------------------------------------------+
```

---

## 2. Layers

### 2.1 Data layer

**Responsibility:** turn a messy source CSV into a clean, queryable, stably-identified table.

```
raw CSV
  -> column mapping (per-dataset config, never hardcoded)
  -> type coercion and cleaning
  -> vendor normalization  ->  vendor_key
  -> DuckDB `transactions`, every row given a row_id
  -> indexes on vendor_key and txn_date
  -> dataset card written
```

`row_id` is the spine of the entire system. It is what detectors group on, what agents cite, what the Verifier re-fetches, and what the dashboard renders as evidence. It must be stable across runs.

**Technology:** pandas for readability, Polars where a step becomes slow, DuckDB as the store. Both pandas and Polars share Arrow memory with DuckDB, so frames move between them without copying.

### 2.2 Detection layer

**Responsibility:** score 100% of rows and emit anomaly groups.

| Detector | Method | Emits |
|---|---|---|
| D1 duplicates | exact key match, then fuzzy blocking on `vendor_key` + amount tolerance + date window, with a raw-name similarity confirmation; optional probabilistic linkage as a third stage | 1 case per duplicate group |
| D2 split purchases | rolling-window SQL grouping on `(vendor_key, officer_id)`; flag groups where each transaction is below threshold but the total is not | 1 case per split group |
| D3 price inflation | per-category median and MAD robust z-score on unit price; Isolation Forest on engineered features as a second opinion | 1 case per line item |
| D4 vendor red flags | Benford first-digit chi-square, round-number ratio, period-end clustering, new-vendor-plus-high-value | 1 case per vendor |

Every detector implements the same interface and returns the same Case shape. That uniformity is what makes the evaluation harness and the agent layer generic rather than per-detector.

A **rule-based baseline** implements the same interface, deliberately naive, so that every claim of improvement has something concrete to be measured against.

**Technology:** scikit-learn, PyOD, rapidfuzz, Splink, scipy.stats, DuckDB SQL.

### 2.3 Agentic layer

**Responsibility:** turn a case into a finished, cited, verified case file.

#### Investigator

A bounded loop, written by hand:

```
build prompt from case + tool schemas
loop up to MAX_STEPS:
    response = llm.chat(messages, tools)
    if response is a tool call:
        result = execute_tool(name, args)
        log step (name, args, result, latency, tokens)
        append result to messages
    else:
        break
parse and validate final JSON against the audit note schema
```

**Tools:**

| Tool | Purpose |
|---|---|
| `query_transactions(sql)` | Fetch specific rows under a read-only, constrained query interface |
| `vendor_profile(vendor_key)` | Payment history, totals, first-seen date, transaction count |
| `find_similar_invoices(row_id)` | Comparable transactions for context |
| `policy_lookup(query)` | Semantic retrieval over the procurement policy, returns clause text and identifier |
| `benford_stats(vendor_key)` | First-digit distribution and test statistic for a vendor |
| `calculator(expr)` | Arithmetic, so numbers are computed rather than generated |

Output is strict JSON: a finding, a list of citations, a verdict, a severity adjustment, and the trace.

#### Verifier

```
extract every cited row_id from the note
for each citation:
    row = fetch(row_id)
    if row is missing                  -> FAIL (fabricated citation)
    if stated values != row values     -> FAIL (deterministic mismatch)
    if row does not support the claim  -> FAIL (semantic)
if any FAIL and retries remain:
    regenerate with the failures fed back as context
else:
    release with verification_status and counts
```

The deterministic checks (row exists, values match) are separated from the semantic check deliberately, because they carry different evidential weight and are reported as different numbers.

**Technology:** the `openai` Python client pointed at an OpenAI-compatible endpoint. Ollama serving Qwen2.5-7B-Instruct locally is the delivered configuration; the same code targets a hosted OpenAI-compatible endpoint during development by changing one environment variable.

### 2.4 Storage layer

Two stores, chosen by access pattern.

| | DuckDB | PostgreSQL |
|---|---|---|
| Workload | OLAP — large aggregate scans | OLTP — small frequent writes |
| Holds | `transactions`, detector output, evaluation results | `cases`, status, audit notes, citations, traces, run history |
| Written by | Batch pipeline only | API and batch pipeline |
| Read by API as | Read-only connection | SQLAlchemy session |
| Why | Columnar, built for the `GROUP BY` analytics detectors perform | Concurrent transactional writes, which a single-writer embedded engine handles badly |

Consequence: the API opens DuckDB **read-only**, so a batch run and the dashboard never contend for a write lock. SQLite substitutes for PostgreSQL through SQLAlchemy with no code changes if a server is unavailable.

### 2.5 API layer

FastAPI, thin by design. Every request and response body is a Pydantic model, which means the interface contracts are enforced by the type system and published as OpenAPI rather than living in a document that drifts.

Endpoint surface is specified in [API-CONTRACT.md](API-CONTRACT.md).

### 2.6 Presentation layer

React with TypeScript. TanStack Query owns all server state — caching, refetching, loading and error handling — so no component hand-rolls fetch logic. TanStack Table handles the case queue, which needs sorting, filtering and pagination over a large list. Zod validates API responses at runtime against the same shapes Pydantic emits, so a contract mismatch surfaces immediately rather than as a blank screen.

---

## 3. End-to-end data flow

```
1. ingest.py
     CSV -> clean -> normalize -> DuckDB.transactions

2. detect.py
     DuckDB.transactions -> D1..D4 + baseline
                         -> cases with detector_score, amount_at_risk, severity_prelim
                         -> Postgres.cases

3. investigate.py
     Postgres.cases  ORDER BY severity_prelim DESC  LIMIT N
       for each case:
         Investigator -> draft note (cites row_ids)
         Verifier     -> re-fetch cited rows, check, retry on failure
         -> Postgres.audit_notes + citations + agent_traces
         -> case marked investigated, severity_final set

4. evaluate.py
     injection ground truth vs detector output
       -> per-case and per-row precision / recall / F1 / PR-AUC
       -> citation validity, triage accuracy, efficiency
       -> ablation runs
       -> MLflow + DuckDB.eval_results

5. API + React
     read cases, notes, evidence rows, traces, metrics
     write case status and reviewer notes
```

---

## 4. Configuration

One typed configuration module, loaded from environment, holding at minimum:

```
DUCKDB_PATH                 path to the analytical store
DATABASE_URL                Postgres (or SQLite) connection string
LLM_PROVIDER                which OpenAI-compatible endpoint to use
LLM_BASE_URL                endpoint URL
LLM_MODEL                   model identifier
LLM_TEMPERATURE             low, for structured output
AGENT_MAX_STEPS             tool-loop bound
VERIFIER_MAX_RETRIES        regeneration limit
INVESTIGATE_TOP_N           how many cases get investigated
APPROVAL_THRESHOLD          250000        D2 threshold; must match SG-PP-2.2
DUPLICATE_AMOUNT_TOLERANCE  0.005         D1 amount tolerance; matches SG-PP-4.4
DUPLICATE_DATE_WINDOW_DAYS  14            D1 date window; matches SG-PP-4.4
SPLIT_WINDOWS_DAYS          [3, 7, 14]    D2 rolling windows; matches SG-PP-3.2/3.3
NEW_VENDOR_DAYS             90            D4 new-vendor period; matches SG-PP-5.3
RANDOM_SEED                 global seed
CURRENCY                    INR
POLICY_PATH                 path to policy/policy.md
```

Nothing that appears in this list may be hardcoded anywhere else.

### 4.1 Policy and configuration must agree

The threshold values above appear in two places: this configuration, and the threshold summary table in `policy/policy.md`. They must be identical.

If they diverge, the agent will cite a policy clause stating one figure while the detector that raised the case used another — an inconsistency a panel would find immediately, and one that undermines the citation guarantee the whole project rests on.

A test asserts equality between the configured values and the figures parsed from the policy's threshold summary, and fails the build on mismatch.

### 4.2 Currency

The system reports in **INR**. Where a source dataset is denominated in another currency, ingestion converts using a **fixed rate pinned in that dataset's configuration** — never a live rate, because a live rate makes two runs of the same evaluation produce different numbers. The rate and its date are recorded in the dataset card, and converted figures are labelled as converted wherever they are displayed.

---

## 5. Deployment

`docker-compose.yml` brings up three services:

| Service | Contents |
|---|---|
| `db` | PostgreSQL, with a named volume |
| `api` | FastAPI + uvicorn, mounting the DuckDB file read-only |
| `web` | React dev server, or a static build behind a small server |

Ollama runs on the host rather than in Compose, because it needs direct GPU access. The batch scripts run on the host or inside the `api` image; they need write access to the DuckDB file, so they are never run while the API holds it open for a schema-changing operation.

---

## 6. Failure behaviour

| Failure | Behaviour |
|---|---|
| Model returns unparseable JSON | Retry within the loop, up to the step bound; then mark the case investigation failed and leave it in the queue |
| Model cites a nonexistent row | Verifier fails the note, feeds the failure back, regenerates |
| Note still fails after the retry limit | Released with an explicit unverified status; never silently presented as verified |
| Tool raises | Error text returned to the model as the tool result so it can recover; the step is logged as failed |
| LLM endpoint unreachable | Batch run aborts with a clear message; already-written notes are unaffected |
| Detector finds no cases | Empty result is valid, not an error; the dashboard states zero explicitly |

---

## 7. Rejected alternatives

| Alternative | Why not |
|---|---|
| Node/Express for CRUD alongside Python for ML | Two runtimes and two dependency systems. DuckDB is embedded, so the Node process could not share a connection and every query would become an extra HTTP hop into Python. No benefit. |
| Django alongside FastAPI | Two Python web frameworks doing one job. The Django ORM cannot address DuckDB, so it would force a second relational store and split the data across engines. Its main value — admin, auth, migrations — is either out of scope or already covered by Alembic. |
| Single DuckDB for everything | DuckDB is single-writer. Case-status writes from the API would contend with batch runs for the file lock. |
| An agent framework | Hundreds of lines of abstraction between the team and the agent's behaviour, in a system where every step must be explainable and debuggable. |
| PostgreSQL for the analytical store too | Row-oriented, and needs tuning to approach DuckDB on the aggregate scans the detectors run. |
| Synchronous investigation inside an HTTP request | 30-60 seconds per case. Batch is the correct shape. |
