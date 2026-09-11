# SpendGuard

**A multi-agent system for evidence-grounded detection and investigation of procurement spend anomalies.**

> Existing tools flag suspicious transactions. SpendGuard investigates them and hands the auditor a finished, verified case file.

---

## What it does

1. **Ingests** procurement transaction data (purchase orders / invoices / payments) into an analytical database.
2. **Detects** four classes of anomaly across **100% of rows** — duplicate records, split purchases, price inflation, vendor red flags.
3. **Investigates** prioritized cases with a local LLM agent that gathers evidence through tools, checks the organization's procurement policy, and writes a structured audit note where **every claim cites specific row IDs**.
4. **Verifies** every citation with a second agent that re-fetches each cited row and confirms it supports the claim — hallucination becomes a measured, minimized quantity.
5. **Presents** everything in a dashboard: money-at-risk, a case queue an auditor can act in, per-case evidence, and full agent reasoning traces.

Runs **fully local** on commodity GPU hardware. No paid APIs in the runtime system. Financial data never leaves the organization.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript, Vite, TanStack Query, TanStack Table, Tailwind + shadcn/ui, Recharts, Zod |
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic, uvicorn |
| Analytical store | DuckDB (transactions, detector output, evaluation results) |
| Operational store | PostgreSQL (cases, status, audit notes, traces) — SQLite fallback |
| Detection / ML | scikit-learn, PyOD, rapidfuzz, Splink, scipy, pandas / Polars |
| LLM | Qwen2.5-7B-Instruct (Q4_K_M) via Ollama; Groq/Gemini switchable for development |
| Policy RAG | sentence-transformers (bge-small-en-v1.5) + FAISS |
| Tracking | MLflow (local) |
| Tooling | Docker Compose, pytest, ruff, mypy, ESLint, Prettier, GitHub Actions |

---

## Repository layout

```
SpendGuard/
├── backend/
│   ├── src/
│   │   ├── pipeline/        ingestion, cleaning, vendor normalization
│   │   ├── detectors/       d1_duplicates, d2_splits, d3_inflation, d4_vendor
│   │   ├── agent/           tools, investigator, verifier
│   │   ├── eval/            injection harness, metrics, ablations
│   │   ├── api/             FastAPI routers, Pydantic schemas
│   │   └── db/              DuckDB + SQLAlchemy models, Alembic migrations
│   ├── scripts/             CLI batch runners
│   └── tests/
├── frontend/                React + TypeScript (Vite)
├── data/                    raw and processed datasets (gitignored)
├── docs/                    design, requirements, architecture, contracts
├── policy/                  procurement policy used for RAG
└── docker-compose.yml
```

---

## How work flows

The slow work happens **offline in batch scripts**, not inside HTTP requests:

```
scripts/ingest.py       CSV  →  clean  →  normalize  →  DuckDB
scripts/detect.py       DuckDB  →  detectors  →  cases (Postgres)
scripts/investigate.py  top-N cases  →  Investigator  →  Verifier  →  audit notes
scripts/evaluate.py     injection harness  →  metrics  →  MLflow
```

The API only **reads finished results** and **writes case-status updates**. That is why it stays thin and fast.

---

## Setup

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
```

```bash
./.venv/Scripts/python.exe -m pip install -e "./backend[dev,detect]"
```

```bash
cp .env.example .env
```

Verify the install:

```bash
./.venv/Scripts/python.exe -m pytest backend
```

Dependency groups are installed as each phase needs them, so the initial install
stays light: `detect` for the detectors, `agent` for the LLM layer and policy
retrieval, `api` for FastAPI, `track` for MLflow, `linkage` for optional Splink.

---

## Documentation

| Document | Contents |
|---|---|
| [Design](docs/DESIGN.md) | Problem, goals, core design decisions and their rationale |
| [Requirements](docs/REQUIREMENTS.md) | Numbered functional and non-functional requirements |
| [Architecture](docs/ARCHITECTURE.md) | Layers, components, data flow, deployment |
| [Data schema](docs/DATA-SCHEMA.md) | DuckDB and Postgres tables, dataset mapping, vendor normalization |
| [API contract](docs/API-CONTRACT.md) | Endpoints and the Case / AuditNote schemas |
| [Evaluation](docs/EVALUATION.md) | Injection harness, metrics definitions, ablations, honesty caveats |
| [Test checklist](docs/TEST-CHECKLIST.md) | What must be tested and verified before demo |
| [Decisions](docs/DECISIONS.md) | Binding decision log and open questions |
| [Procurement policy](policy/policy.md) | The policy corpus the agent retrieves over, with the threshold summary |

**Reporting currency: INR (`₹`).** Principal control threshold: **₹2,50,000** (policy clause SG-PP-2.2). Configuration and the policy document must state the same figures — a test enforces it.

---

## Honest scope

SpendGuard does **not** claim better raw detection accuracy than commercial systems trained on hundreds of millions of documents. The contribution is the layer *after* detection: automated investigation with machine-verified citations, delivered open-source and fully local.
