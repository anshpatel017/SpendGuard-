# Data Schema

Two stores. DuckDB holds analytical data written by batch runs and read by everything. PostgreSQL holds operational state written by the API and the batch runs.

---

## 1. DuckDB — analytical store

### 1.1 `transactions`

The canonical schema. This is the contract between ingestion and every detector, every tool, and the Verifier.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `row_id` | BIGINT | no | Stable unique identifier. **This is what the agent cites.** Must not change between runs. |
| `vendor_name` | VARCHAR | no | Raw vendor name exactly as it appeared in the source |
| `vendor_key` | VARCHAR | no | Normalized vendor name — see section 3 |
| `invoice_no` | VARCHAR | yes | Invoice or purchase-order number, whichever the source provides |
| `amount` | DOUBLE | no | Transaction total |
| `txn_date` | DATE | no | Transaction date |
| `officer_id` | VARCHAR | yes | Buyer, requesting officer, or department — whatever the source's finest available grain is |
| `item_desc` | VARCHAR | yes | Free-text item description |
| `item_category` | VARCHAR | yes | Category code or label |
| `quantity` | DOUBLE | yes | Line quantity |
| `unit_price` | DOUBLE | yes | Price per unit |
| `source_dataset` | VARCHAR | no | Which dataset this row came from |
| `source_row_ref` | VARCHAR | yes | Identifier in the source file, for auditing ingestion |
| `is_injected` | BOOLEAN | no | True for rows created by the injection harness. Default false. |
| `injection_group_id` | VARCHAR | yes | Links injected rows belonging to the same synthetic anomaly |
| `injection_type` | VARCHAR | yes | `duplicate`, `split`, `inflation`, or `vendor_flag` |

Indexes on `vendor_key`, `txn_date`, and `(vendor_key, txn_date)`.

**Nullability matters.** `officer_id`, `invoice_no`, `item_category`, `quantity` and `unit_price` are all nullable because real datasets omit them. Detectors that depend on a nullable field must skip rows lacking it and report how many were skipped, rather than failing.

**Injection columns live in the same table** so that detectors see exactly the data an auditor would see. Detectors must never read `is_injected`, `injection_group_id` or `injection_type` — only the evaluation harness does. This is enforced by a test.

### 1.1a `audit_transactions` (view)

What detectors read. Every `transactions` column **except** `is_injected`, `injection_group_id`, `injection_type`, `source_row_ref` and `source_dataset`. Injected rows have no `source_row_ref`, so exposing it would leak the answer key through its absence. Rebuilt whenever `transactions` is written.

### 1.2 `ground_truth`

Written by the injection harness.

| Column | Type | Meaning |
|---|---|---|
| `injection_group_id` | VARCHAR | Primary key |
| `injection_type` | VARCHAR | Anomaly class injected |
| `row_ids` | BIGINT[] | Rows forming this synthetic anomaly |
| `source_row_ids` | BIGINT[] | Original rows the injection was derived from |
| `seed` | INTEGER | Seed used |
| `params` | JSON | Parameters used, e.g. inflation multiplier, date shift |
| `amount_at_risk` | DOUBLE | Value implicated by this anomaly |
| `vendor_key` | VARCHAR | The anomaly's supplier — vendor-flag cases are matched on this, not on rows (D-03) |

### 1.2a `injection_runs`

One row per injected database: seed, full configuration, and a summary of what was placed. The injected database is always a **separate file** (`spendguard_injected_seed<N>.duckdb`); the clean database is never modified.

### 1.3 `detector_output`

Raw scores before case grouping. Kept so PR curves can be recomputed without re-running detection.

| Column | Type | Meaning |
|---|---|---|
| `run_id` | VARCHAR | Which detection run |
| `detector` | VARCHAR | `d1`, `d2`, `d3`, `d4`, `baseline` |
| `row_id` | BIGINT | Scored row |
| `score` | DOUBLE | Raw detector score before normalization |
| `detector_score` | DOUBLE | Normalized to 0-1 |
| `group_key` | VARCHAR | Which anomaly group this row was assigned to |

### 1.4 `eval_results`

| Column | Type | Meaning |
|---|---|---|
| `run_id` | VARCHAR | Evaluation run |
| `detector` | VARCHAR | Detector or baseline |
| `anomaly_type` | VARCHAR | An anomaly type, or `all` for the pooled row |
| `granularity` | VARCHAR | `case` or `row` |
| `precision`, `recall`, `f1` | DOUBLE | Metrics |
| `pr_auc` | DOUBLE | Average precision; per-case rows only, null for per-row |
| `tp`, `fp`, `fn` | INTEGER | Counts |
| `seed` | INTEGER | Injection seed of the evaluated database |
| `created_at` | TIMESTAMP | |

The injection configuration is stored once in `injection_runs`, not repeated per metric row. Each evaluation also writes a JSON and Markdown report to `data/processed/eval/`.

---

## 2. PostgreSQL — operational store

### 2.1 `cases`

| Column | Type | Meaning |
|---|---|---|
| `case_id` | UUID PK | Case identifier |
| `run_id` | VARCHAR | Detection run that produced it |
| `anomaly_type` | ENUM | `duplicate`, `split`, `inflation`, `vendor_flag` |
| `detector` | VARCHAR | Which detector emitted it |
| `row_ids` | BIGINT[] | Rows forming the anomaly group |
| `detector_score` | FLOAT | 0-1, detector confidence |
| `amount_at_risk` | NUMERIC | Value implicated |
| `severity_prelim` | FLOAT | 0-100, set at case creation |
| `severity_final` | FLOAT | 0-100, set after investigation; null until then |
| `severity_band` | ENUM | `high`, `medium`, `low` |
| `status` | ENUM | `new`, `under_review`, `confirmed`, `dismissed` |
| `investigated` | BOOLEAN | Whether the agent has run on this case |
| `dismissed_by_agent` | BOOLEAN | True when the agent recommended dismissal |
| `reviewer_note` | TEXT | Free-text auditor note |
| `metadata` | JSONB | Detector-specific detail — window size, category, z-score, and so on |
| `created_at`, `updated_at` | TIMESTAMP | |

### 2.2 `audit_notes`

| Column | Type | Meaning |
|---|---|---|
| `note_id` | UUID PK | |
| `case_id` | UUID FK | |
| `finding` | TEXT | The written finding |
| `recommended_action` | TEXT | What the agent recommends |
| `verdict` | ENUM | `likely_true_positive`, `likely_false_positive`, `inconclusive` |
| `verification_status` | ENUM | `verified`, `unverified`, `failed_after_retries` |
| `citations_checked` | INTEGER | |
| `citations_passed` | INTEGER | |
| `deterministic_passed` | INTEGER | Passed the row-exists and values-match check |
| `semantic_passed` | INTEGER | Passed the support check |
| `retry_count` | INTEGER | Regeneration attempts used |
| `model_name` | VARCHAR | Model that produced it |
| `is_ablation` | BOOLEAN | Produced under an ablation configuration |
| `ablation_name` | VARCHAR | Which ablation, if any |
| `created_at` | TIMESTAMP | |

### 2.3 `citations`

One row per citation, so citation validity is computed by query rather than by parsing text.

| Column | Type | Meaning |
|---|---|---|
| `citation_id` | UUID PK | |
| `note_id` | UUID FK | |
| `claim_text` | TEXT | The sentence or clause making the claim |
| `row_id` | BIGINT | Cited row |
| `row_exists` | BOOLEAN | Deterministic check |
| `values_match` | BOOLEAN | Deterministic check |
| `supports_claim` | BOOLEAN | Semantic check |
| `failure_reason` | TEXT | Populated on failure |

### 2.4 `agent_traces`

| Column | Type | Meaning |
|---|---|---|
| `trace_id` | UUID PK | |
| `case_id` | UUID FK | |
| `step_index` | INTEGER | Order within the loop |
| `role` | VARCHAR | `investigator` or `verifier` |
| `tool_name` | VARCHAR | Null for a reasoning step |
| `tool_args` | JSONB | |
| `tool_result` | JSONB | Truncated if large, with a truncation flag |
| `latency_ms` | INTEGER | |
| `prompt_tokens`, `completion_tokens` | INTEGER | |
| `error` | TEXT | Populated when the step failed |
| `created_at` | TIMESTAMP | |

### 2.5 `runs`

| Column | Type | Meaning |
|---|---|---|
| `run_id` | VARCHAR PK | |
| `kind` | ENUM | `ingest`, `detect`, `investigate`, `evaluate` |
| `status` | ENUM | `running`, `completed`, `failed` |
| `config` | JSONB | Full configuration snapshot |
| `seed` | INTEGER | |
| `started_at`, `finished_at` | TIMESTAMP | |
| `summary` | JSONB | Counts and headline figures |

---

## 3. Vendor normalization

Applied at ingestion to produce `vendor_key`.

```
lowercase
remove punctuation
strip legal suffixes:
    pvt, private, ltd, limited, llp, inc, corp, co, company,
    and, &, enterprise(s), trader(s)
collapse whitespace
token-sort so word order does not matter
```

```
"Sharma Enterprises"          ->  "sharma"
"SHARMA ENTERPRISES PVT LTD"  ->  "sharma"
"Sharma  Enterprise"          ->  "sharma"
"Enterprises Sharma"          ->  "sharma"
```

**Known trade-off.** This is deliberately aggressive, which means genuinely different vendors sharing a stem can collapse to the same key. `vendor_key` is therefore used for **blocking** — cheaply generating candidate matches — and never as sole proof of identity. D1 applies a similarity check on `vendor_name` before reporting a duplicate.

---

## 4. Dataset mapping

Column mapping is configuration, one file per dataset, never hardcoded.

```yaml
# mappings/california_po.yaml
source: "Large Purchases by the State of California"
columns:
  vendor_name:   "Supplier Name"
  invoice_no:    "Purchase Order Number"
  amount:        "Total Price"
  txn_date:      "Purchase Date"
  officer_id:    "Department Name"
  item_desc:     "Item Name"
  item_category: "Normalized UNSPSC"
  quantity:      "Quantity"
  unit_price:    "Unit Price"
```

**Note on `officer_id`.** Where a dataset has no individual buyer, department is the finest available grain. This is a real weakening of D2, because "same department" is much coarser than "same officer" and will surface more benign groups. It must be stated in the limitations section, and the D2 case metadata must record which grain was used.

---

## 5. Rules

1. `row_id` is immutable. Re-ingestion of the same source must reproduce the same assignment.
2. Detectors read only the operational columns. Reading `is_injected` or its siblings is a test failure.
3. The API opens DuckDB **read-only**. Only batch scripts write to it.
4. Raw data is never committed to version control.
5. The frozen demo snapshot is version-pinned and stored separately from working data.
