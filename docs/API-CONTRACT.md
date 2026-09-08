# API Contract

FastAPI, all bodies defined as Pydantic v2 models, OpenAPI published at `/docs`.

Base path: `/api/v1`

The API is **thin**. It reads results produced by batch runs and writes case state. It never runs a detector or an agent inside a request, with the single exception of the bounded live-injection demonstration endpoint.

---

## 1. Core schemas

### Case

Produced by the detection layer, consumed by the agent layer and the frontend.

```python
class Case(BaseModel):
    case_id: UUID
    run_id: str
    anomaly_type: Literal["duplicate", "split", "inflation", "vendor_flag"]
    detector: str
    row_ids: list[int]
    detector_score: float          # 0.0 - 1.0
    amount_at_risk: Decimal
    severity_prelim: float         # 0.0 - 100.0
    severity_final: float | None   # null until investigated
    severity_band: Literal["high", "medium", "low"]
    status: Literal["new", "under_review", "confirmed", "dismissed"]
    investigated: bool
    dismissed_by_agent: bool
    reviewer_note: str | None
    metadata: dict                 # detector-specific detail
    created_at: datetime
    updated_at: datetime
```

### AuditNote

Produced by the agent layer, consumed by the frontend.

```python
class Citation(BaseModel):
    citation_id: UUID
    claim_text: str
    row_id: int
    row_exists: bool
    values_match: bool
    supports_claim: bool
    failure_reason: str | None

class TraceStep(BaseModel):
    step_index: int
    role: Literal["investigator", "verifier"]
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None

class AuditNote(BaseModel):
    note_id: UUID
    case_id: UUID
    finding: str
    recommended_action: str
    verdict: Literal["likely_true_positive", "likely_false_positive", "inconclusive"]
    verification_status: Literal["verified", "unverified", "failed_after_retries"]
    citations: list[Citation]
    citations_checked: int
    citations_passed: int
    deterministic_passed: int
    semantic_passed: int
    retry_count: int
    model_name: str
    created_at: datetime
```

### TransactionRow

Evidence, read from DuckDB.

```python
class TransactionRow(BaseModel):
    row_id: int
    vendor_name: str
    vendor_key: str
    invoice_no: str | None
    amount: Decimal
    txn_date: date
    officer_id: str | None
    item_desc: str | None
    item_category: str | None
    quantity: float | None
    unit_price: Decimal | None
    in_case: bool          # true if this row is part of the case, false if context
```

---

## 2. Endpoints

### `GET /api/v1/cases`

List cases with filtering, sorting and pagination.

**Query parameters**

| Name | Type | Default | Meaning |
|---|---|---|---|
| `status` | enum, repeatable | all | Filter by case status |
| `anomaly_type` | enum, repeatable | all | Filter by anomaly class |
| `severity_band` | enum, repeatable | all | Filter by band |
| `verdict` | enum, repeatable | all | Filter by agent verdict |
| `investigated` | bool | all | Only investigated or only queued |
| `dismissed_by_agent` | bool | all | The "Dismissed by agent" filter |
| `min_amount` | decimal | none | Minimum amount at risk |
| `sort` | enum | `severity_prelim` | `severity_prelim`, `severity_final`, `amount_at_risk`, `created_at` |
| `order` | enum | `desc` | `asc` or `desc` |
| `page` | int | 1 | |
| `page_size` | int | 50 | Max 200 |

**Response**

```python
class CaseListResponse(BaseModel):
    items: list[CaseSummary]     # Case minus metadata, plus verdict and a short finding excerpt
    total: int
    page: int
    page_size: int
```

---

### `GET /api/v1/cases/{case_id}`

Full case detail.

```python
class CaseDetailResponse(BaseModel):
    case: Case
    audit_note: AuditNote | None       # null when not yet investigated
    evidence_rows: list[TransactionRow]
    context_rows: list[TransactionRow] # comparable rows for the same vendor or category
    trace: list[TraceStep]
```

`404` if the case id is unknown, with a structured error body.

When `case.investigated` is false, `audit_note` and `trace` are empty and the frontend must render a "not yet investigated" state — never a note-shaped object filled with nulls.

---

### `PATCH /api/v1/cases/{case_id}/status`

Change case status and optionally attach a reviewer note.

**Request**

```python
class StatusUpdateRequest(BaseModel):
    status: Literal["new", "under_review", "confirmed", "dismissed"]
    reviewer_note: str | None = None
```

**Response:** the updated `Case`.

Rejects unknown status values with `422`. The agent never calls this endpoint.

---

### `GET /api/v1/metrics`

Dashboard KPIs.

```python
class MetricsResponse(BaseModel):
    total_transactions: int
    total_amount: Decimal
    currency: str

    cases_flagged: int
    cases_investigated: int
    cases_queued: int              # flagged minus investigated

    money_at_risk: Decimal
    money_at_risk_confirmed: Decimal

    by_anomaly_type: dict[str, AnomalyBreakdown]   # count, amount at risk
    by_severity_band: dict[str, int]
    by_status: dict[str, int]

    last_run_id: str
    last_run_at: datetime
```

`cases_flagged`, `cases_investigated` and `cases_queued` must be internally consistent — this is what backs the honest coverage line in the dashboard.

---

### `GET /api/v1/cases/{case_id}/evidence`

Evidence rows alone, for lazy loading a large evidence table.

```python
class EvidenceResponse(BaseModel):
    case_id: UUID
    rows: list[TransactionRow]
    total: int
```

---

### `GET /api/v1/transactions/{row_id}`

Single transaction lookup — used when a citation is inspected.

**Response:** `TransactionRow`. `404` if unknown.

---

### `GET /api/v1/evaluation`

Evaluation and ablation results.

```python
class DetectorMetrics(BaseModel):
    detector: str
    granularity: Literal["case", "row"]
    precision: float
    recall: float
    f1: float
    pr_auc: float
    tp: int
    fp: int
    fn: int

class AgentMetrics(BaseModel):
    citation_validity_deterministic: float
    citation_validity_semantic: float
    triage_accuracy: float
    avg_tool_calls: float
    avg_tokens: float
    avg_latency_seconds: float
    notes_regenerated: int
    notes_failed_after_retries: int

class AblationRow(BaseModel):
    ablation_name: str
    configuration: str
    citation_validity_deterministic: float
    citation_validity_semantic: float
    triage_accuracy: float
    note_quality_score: float | None

class EvaluationResponse(BaseModel):
    run_id: str
    seed: int
    dataset: str
    injected_anomaly_count: int
    detector_metrics: list[DetectorMetrics]
    baseline_metrics: list[DetectorMetrics]
    agent_metrics: AgentMetrics
    ablations: list[AblationRow]
    generated_at: datetime
```

---

### `GET /api/v1/runs`

Run history, so the dashboard can state which run it is showing.

```python
class RunSummary(BaseModel):
    run_id: str
    kind: Literal["ingest", "detect", "investigate", "evaluate"]
    status: Literal["running", "completed", "failed"]
    seed: int | None
    started_at: datetime
    finished_at: datetime | None
    summary: dict
```

---

### `POST /api/v1/demo/inject`

The live injection demonstration. Injects a small, fixed number of anomalies into a bounded copy of the dataset, runs detection, and returns whether each injected anomaly was caught.

**Request**

```python
class DemoInjectRequest(BaseModel):
    anomaly_count: int = 3        # capped server-side
    seed: int | None = None       # random if omitted
```

**Response**

```python
class DemoInjectResult(BaseModel):
    injection_group_id: str
    anomaly_type: str
    injected_row_ids: list[int]
    detected: bool
    detected_by: str | None
    case_id: UUID | None
    detector_score: float | None

class DemoInjectResponse(BaseModel):
    seed: int
    dataset_rows: int
    results: list[DemoInjectResult]
    elapsed_seconds: float
```

Constraints: runs against a bounded copy, never the demo dataset itself; anomaly count and dataset size are capped server-side; must complete within a few seconds, since it runs live in front of an audience.

---

### `GET /api/v1/health`

```python
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    duckdb: bool
    postgres: bool
    llm_endpoint: bool
    llm_model: str | None
```

---

## 3. Conventions

| Concern | Rule |
|---|---|
| Errors | Structured body: `{"detail": {"code": str, "message": str}}`. Never a stack trace. |
| Money | Serialized as a string to avoid float rounding. `currency` is returned alongside. |
| Dates | ISO 8601. Dates as `YYYY-MM-DD`, timestamps in UTC. |
| Pagination | `page` and `page_size`, with `total` in the response. |
| Nulls | Explicit `null`, never an empty string or a zero standing in for missing. |
| Versioning | Path-prefixed `/api/v1`. |
| Writes | Only `PATCH /cases/{id}/status` and `POST /demo/inject`. Everything else is a read. |
| DuckDB | Opened read-only by the API, always. |

---

## 4. Frontend type generation

The React client does not hand-write these types. Generate them from the published OpenAPI schema, and validate responses at runtime with Zod. A contract change then surfaces as a compile error or a visible validation error, not a blank screen.
