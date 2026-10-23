# Demo intake files

Two small CSVs for demonstrating **Add Data** live. They are *input*, not results: they
load into a dataset of their own, feed no reported figure, and nothing in
`docs/results/` is computed from them.

**The anomalies in `demo-purchases.csv` are planted on purpose and listed below**, so
that a reader six months from now cannot mistake them for something the system found in
real spend. Regenerate either file from the seeded script that produced them if they are
ever lost; the content is deterministic.

## `demo-purchases.csv` — 44 rows, loads cleanly

Nine columns, all of which the intake maps automatically, and ISO dates so there is no
format question to answer mid-demo:

| Canonical field | Column in the file |
|---|---|
| `vendor_name` | Supplier Name |
| `invoice_no` | Invoice Number |
| `amount` | Invoice Amount (INR) |
| `txn_date` | Invoice Date |
| `officer_id` | Department |
| `item_desc` | Item Description |
| `item_category` | Commodity Category |
| `quantity` | Qty |
| `unit_price` | Rate (INR) |

Suppliers sell one kind of thing and departments buy what they would plausibly buy — a
first draft paired them at random and produced cement bought by IT, which is the first
thing a reader notices and the last thing a demo needs.

### What is planted in it, and which detector should find it

| | Where | Why it should be flagged |
|---|---|---|
| **Duplicate record** | `INV-4135` and `INV-4136`, 17 and 21 Feb | Same item, same quantity, same ₹1,36,430.00, four days apart — and the supplier is **"Nova Scientifc Instruments"** on the second, a misspelling that exact matching misses and the fuzzy stage catches |
| **Split purchase** | Kalpataru Infra Services, 2–8 Mar | Three orders to one supplier for one department inside a week, **₹95,000 each** — under the ₹2,50,000 approval threshold individually, **₹2,85,000 together** |
| **Price inflation** | Sharma Stationers, 18 Mar | A4 paper at **₹2,350 a ream** against a catalogue rate near ₹290 — roughly eight times |
| **Round-number supplier** | Girikand Facility Services | Four invoices, every one exactly **₹75,000.00** |

## `demo-purchases-unusable.csv` — 3 rows, deliberately broken

Its dates read `last Tuesday`, `end of Q1`, `whenever it cleared`, and it has no usable
date column at all. The preview refuses it rather than loading three rows and dropping
all of them, which is the whole reason the preview step exists.

It also earned its keep during development: it exposed a real bug. The column
`Invoice Amount (INR)` contains the word "invoice", so the invoice-number field claimed
it before the amount field was considered, leaving the most important column in the file
unmapped. Required fields now take their turn first, and
`test_an_amount_column_is_not_stolen_by_the_invoice_number_field` keeps it that way.

## Running detection over the uploaded file

Ingestion does not run detectors (D-10), so the upload reports the two commands that do.
After loading the file as, say, `demo_purchases`:

```bash
spendguard detect --db data/processed/demo_purchases.duckdb
spendguard serve --db data/processed/demo_purchases.duckdb
```

Doing this live means restarting the server mid-presentation. Deciding in advance whether
to show it is worth more than discovering the decision on stage.
