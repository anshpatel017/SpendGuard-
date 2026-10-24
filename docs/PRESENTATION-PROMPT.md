# A prompt for generating the slide deck

Paste everything below the line into Claude (or any assistant) to generate the deck.
Every figure in it was read from `docs/results/` on 2026-10-24 and verified against
`spendguard check-evaluation`. If the numbers move, regenerate the reports and update
this file rather than editing a deck by hand — the point of tracing figures to commands
is that the trace survives.

The slide-by-slide layout and the speaker's own notes live in [SLIDES.md](SLIDES.md);
the figures with the caveat that must be spoken beside each one live in
[PRESENTATION.md](PRESENTATION.md). This file is only the generator prompt.

---

I need a presentation for my final-year engineering capstone project. I'm presenting
tomorrow to a faculty panel. Please build a slide deck.

## THE PROJECT: SpendGuard

**One line:** Existing audit tools flag suspicious procurement transactions and stop
there. SpendGuard investigates them and hands the auditor a finished, evidence-cited
case file that a second AI has verified.

Team of 3, zero budget, everything runs on a laptop GPU. Built in Python (DuckDB,
SQLite, Polars, FastAPI) with a React dashboard.

**The contribution is the layer AFTER detection.** Detection is a solved problem;
commercial tools do it. What nobody automates is the investigation — the hours a human
spends checking whether a flag is real. That is what this automates, with every claim
traceable to a database row.

## HOW IT WORKS — four stages

**Stage 1 — DETECT (100% of transactions, no sampling)**
Four detectors, each finding a different class of fraud or error:
- **D1 Duplicate records** — the same bill entered twice. Exact match first, then fuzzy
  (same vendor, amount close but not identical, within a 14-day window), then
  probabilistic record linkage. Catches typos.
- **D2 Split purchases** — someone breaks a ₹4,00,000 purchase into two ₹2,00,000 orders
  to stay under the ₹2,50,000 approval threshold. Groups by vendor + officer in rolling
  windows, flags where each order is below the limit but the total crosses it.
- **D3 Price inflation** — paying far above the normal price for an item. Uses median and
  MAD (robust statistics), plus Isolation Forest as an independent second opinion.
- **D4 Vendor red flags** — four tests combined: too many round-number amounts, odd
  leading-digit distribution, billing clustered at period end, and new vendors instantly
  taking large orders.

Key design point: **D4 compares each vendor against other vendors selling the same kind
of thing, not against a fixed rule.** Round prices are normal for bulk fuel, suspicious
for consulting. Judging everyone by one rule (Benford's law) wrongly accused 61 of 210
real suppliers — so we replaced it with peer comparison.

**Stage 2 — INVESTIGATE (top cases by severity)**
An AI agent takes the highest-severity cases and investigates like a junior auditor,
choosing from six tools: query the database, pull a vendor's full history, find similar
invoices, search the company policy document, run digit statistics, and a calculator.
It decides which tools to use and when it has enough. Then it writes an audit note with
one of three verdicts: likely a real issue / likely a false alarm / inconclusive.

Two rules: **every factual claim must cite a row ID**, and **the agent never closes a
case** — it only recommends. A human decides.

**Stage 3 — VERIFY (a second agent checks the first)**
Because AI models invent things. Two checks:
1. **Deterministic** — does that row exist? Do the values match? Does the cited policy
   clause exist? Pure database lookups, no AI involved, cannot lie.
2. **Semantic** — a fresh AI judge reads whether the cited row actually supports the claim.

Failures are sent back for rewriting. If they still fail, the note is released marked
**unverified** — never silently passed off as checked.

**Stage 4 — THE HUMAN**
A web dashboard: KPI cards, a sortable/filterable case queue, and per case the audit note
with clickable citations, the evidence table, the verification badge, a step-by-step
timeline of what the agent did, and buttons to Confirm or Dismiss with a reviewer note.
Cases export as a Markdown or HTML case file.

## THE NUMBERS — use these exactly, they are all measured

**Detection** (50,963 synthetic transactions, 508 planted anomalies, 3 seeds, ± is
variation across seeds):

| Detector | Precision | Recall | F1 |
|---|---|---|---|
| Rule-based baseline (all) | 0.153 ± 0.005 | 0.310 ± 0.011 | 0.205 ± 0.007 |
| **SpendGuard (all)** | 0.686 ± 0.006 | 0.692 ± 0.006 | **0.689 ± 0.006** |
| D1 duplicates | 1.000 ± 0.000 | 0.903 ± 0.016 | 0.949 ± 0.009 |
| D2 splits | 0.828 ± 0.008 | 0.643 ± 0.017 | 0.724 ± 0.013 |
| D3 inflation | 0.369 ± 0.008 | 0.484 ± 0.009 | 0.419 ± 0.009 |
| D4 vendor flags | 1.000 ± 0.000 | 0.750 ± 0.125 | 0.853 ± 0.082 |

**False positives on clean data (no anomalies planted):** D1 = 0, D2 = 0, D4 = 0,
D3 = 154 of 49,900 rows (0.31%).

**The agent** (20-case sample, complete):
- 20 audit notes, 204 citations
- **100.0% of cited values matched exactly — checked by rule, no AI involved**
- 89.4% judged semantically supported by an AI (reported beside, never averaged in)
- 11 notes released as Verified, 2 unverified, 7 failed checks
- 33,965 tokens, 9.9 tool calls, 30 seconds per investigation

**The ablation — the most important table** (full agent vs a template arm that writes a
note from detector output and never dismisses anything):

| Arm | Citations valid | Real anomalies kept | **False alarms filtered** | Decisive accuracy |
|---|---|---|---|---|
| **Full agent** | 100% | 87% | **75%** | **89%** |
| Template (no AI) | 100% | 100% | **0%** | 79% |

The template keeps every real anomaly because it never dismisses anything — and filters
none of the false alarms for exactly the same reason. **That 75% vs 0% column is the
contribution, measured rather than claimed.**

**Runs fully offline:** a 3-billion-parameter model (Qwen2.5-3B) on a 4GB laptop GPU
wrote 5 audit notes, 3 verified, using 2,158 MiB, with every network connection blocked.
No paid API needed. The system ships defaulting to the local model.

**Also tested on real data:** 346,018 California government purchase order line items,
336,995 loaded.

**Engineering:** 885 backend tests + 40 frontend tests, CI green, 66 of 72 requirements
implemented with no mandatory one outstanding. Dashboard cold start 2.65s, full
four-detector scan 15.3s.

## BE HONEST — this matters more than looking impressive

Include a limitations slide. Say these plainly:

1. **D3 is the weak detector** (F1 0.419 vs the baseline's 0.432 — it loses on F1, wins
   on ranking with PR-AUC 0.280 vs 0.196). Honest expensive purchases look exactly like
   inflated ones on price alone. **Turn this into the argument: it is precisely why the
   investigation layer exists.**
2. **Detection covers 100% of rows; investigation covers prioritized cases, not all of
   them.** Each investigation takes 1–3 minutes on a free AI tier.
3. **The synthetic anomalies are planted and known.** The real California flags are
   suspicions, never described as proven fraud.
4. **The procurement policy is ours**, derived from India's GFR 2017 and CVC guidance.
5. **On real data D3's category system breaks down** (items sit 5.63× from their category
   median vs 1.11× on synthetic data) and **48.7% of D1's real-data flags are two lines of
   the same purchase order** — both documented as open issues.
6. **Adjusted precision on real data is not yet measured** — it needs human reviewers, and
   we refuse to fabricate it.

## WORDING RULES — do not break these

- Say "duplicate **transaction records**", never "duplicate payments" (the data is
  purchase orders, not payments).
- Say "detects across 100% of transactions, then autonomously **investigates prioritized
  cases**" — never "investigates every flagged case".
- **Never claim better raw detection accuracy than commercial tools.** The claim is the
  investigation layer, not the detection.
- Always state sample size with a rate: "100% over 20 notes", never bare "100%".
- Never merge the rule-checked and AI-judged citation numbers into one figure.

## WHAT I WANT

A **13–15 slide deck**, suitable for a 10–12 minute talk plus questions. Structure:

1. Title
2. The problem (auditors drown in flags; 100% of spend is never checked)
3. The gap in existing tools (they stop at a risk score)
4. What SpendGuard does — the one-line claim
5. Architecture — the four stages as a diagram
6. The four detectors, one line each
7. Detection results vs baseline (the table)
8. How the agent investigates — the six tools
9. Verification — two numbers, never blended
10. **The ablation table** — the slide that proves the contribution
11. A real case walkthrough (see below)
12. Runs offline on a laptop GPU
13. Limitations, stated plainly
14. What's next / closing

**For slide 11, use this real case from the system:**
Case 9b5896b3, "Duplicate record — Sunrise Technologies", ₹1,98,398.72 at risk. Two rows,
4 days apart, same invoice number INV-00714, same amount, same officer — and **the
supplier name is misspelt on the second row ("Sunrise Technolgoies")**, which exact
matching would have missed. The agent's note: "Rows 2128 and 50657 are the same obligation
recorded twice." Verified, 2 of 2 citations. Recommended action: hold payment on the later
row.

**Style:** clean and professional, not corporate-flashy. Dark text on light background.
Numbers should be large and readable from the back of a room. Minimal text per slide —
I am speaking over them, they are not a document. Include brief speaker notes for each
slide telling me what to say, especially for the limitations slide.
