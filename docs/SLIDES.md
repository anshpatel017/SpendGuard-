# SLIDES.md — the deck, slide by slide

Every figure here is lifted from [PRESENTATION.md](PRESENTATION.md), which traces each one
to the command that produced it. **Regenerate the reports before you build the deck** —
`spendguard report detection|agent|headline` — and re-check any number you paste.

Thirteen slides for twelve to fifteen minutes. The demo is slide 10 and it is the point;
everything before it is setup, so keep the setup moving.

---

## 1 — Title

> **SpendGuard**
> Procurement anomaly detection that investigates what it finds
>
> *Final-year capstone · three people · open-source · runs on a laptop*

**Say:** nothing yet. Let the next slide do the work.

---

## 2 — The problem *(no screen — talk to the room)*

A mid-sized organisation issues tens of thousands of purchase orders a year. An internal
auditor samples perhaps 2% of them. The other 98% is never looked at by anyone.

Tools exist that score every transaction for risk. They hand the auditor a ranked list, and
the auditor still has to open each case, pull the supplier's history, check the policy, and
decide. **The bottleneck was never detection. It is the work after detection.**

---

## 3 — What we built

> Existing tools flag suspicious transactions.
> **SpendGuard investigates them and hands the auditor a finished, verified case file.**

Three claims, in order of how hard they are to make good on:

1. Audits **100%** of transactions, not a sample
2. **Autonomously investigates** prioritized cases — gathers evidence, weighs the innocent
   explanation, writes a cited note
3. A **second agent verifies every citation** before the note is released

---

## 4 — Architecture *(one diagram)*

```
ingest → detect (D1–D4, 100% of rows) → prioritize by severity
                                              ↓
                              investigate (6 tools, policy RAG)
                                              ↓
                                   verify (rules, then a judge)
                                              ↓
                                     auditor reviews and decides
```

**Say:** the agent never closes a case. It writes a note and a verdict; a person moves it.
That is a design decision, not a limitation — D-04.

---

## 5 — Detection: four detectors over every row

| Anomaly | Detector | F1 | vs baseline |
|---|---|---:|---:|
| Duplicate records | D1 — Fellegi–Sunter linkage | **0.949** | 0.354 |
| Split purchases | D2 — minimal runs under threshold | **0.724** | 0.029 |
| Price inflation | D3 — robust z vs category median | 0.419 | 0.432 |
| Vendor red flags | D4 — peer tests, Fisher, FDR | **0.853** | 0.497 |
| **All** | **SpendGuard** | **0.689 ± 0.006** | **0.205 ± 0.007** |

Three seeds, mean ± sd. **Point at D3 yourself** — see slide 11.

---

## 6 — On clean data, it stays quiet

| Detector | Cases on 49,900 clean rows |
|---|---:|
| D1 | **0** |
| D2 | **0** |
| D4 | **0** |
| D3 | 154 (0.31%) |

**Say:** we evaluate on clean data as well as injected data. Metrics on injected data alone
once hid a bug that flagged 1,732 false duplicates — the clean run is what caught it.

---

## 7 — The contribution: an investigated case

*Screenshot of one case page, or go live.*

- The agent queried the database, read the supplier's history, retrieved the policy clause
- Every claim carries the **row ids** it rests on
- The badge says **Verified** only when rules *and* a second model both passed

**Say:** read one finding aloud. The duplicate case is the clearest.

---

## 8 — Verification: two numbers, never blended

| | |
|---|---:|
| Citations checked | 226 |
| **Rule-checked valid** | **100.0%** |
| Model-judged supported | 89.0% |
| Notes verified | 11 of 21 |

**Say:** the rule-checked number involves no model at all — the row either exists and the
stated value either matches, or it does not. We report the model-judged number beside it and
never average the two, because one is checkable and one is an opinion.

---

## 9 — Does the agent actually add anything? *(the slide that matters)*

| Arm | Real kept | **Spurious filtered** | Decisive accuracy |
|---|---:|---:|---:|
| **Full agent** | 93% | **75%** | **90%** |
| Template (no agent) | 100% | **0%** | 78.6% |

**Say:** we built a deliberately stupid arm that writes a note from the detector output and
never dismisses anything. It keeps every real anomaly — and filters none of the false alarms,
because it has no way to weigh an innocent explanation. **That column is the contribution,
measured rather than asserted.** If asked why the agent keeps 92% and not 100%: it wrongly
dismissed one genuine anomaly of fifteen, which is the cost of being able to dismiss
anything at all, and it is in the report rather than rounded away.

---

## 10 — Live demonstration *(2 minutes)*

Follow [DEMO.md](DEMO.md). In short:

1. Serve the **frozen** state — `spendguard serve --frozen`
2. Open the case you chose; **click a citation**, the evidence row highlights
3. Show the **dismissal** — a case the agent overruled to `likely_false_positive`
4. Live injection: plant 3 anomalies, watch detection run

⚠️ **Warm it first.** The first injection of the day takes 13 s; every one after takes 4.
Run one before the room fills.

⚠️ **Let it miss.** If an anomaly is missed, say *"that is the detector's measured recall,
and it is why the investigation layer exists."* Do not re-roll for a better seed.

---

## 11 — What we got wrong, and what real data broke

**D3 is worse than the baseline on F1** — 0.419 against 0.432. It ranks better (PR-AUC 0.280
vs 0.196), and the report says both. Honest premium purchases sit in the same price band as
inflated ones, which is precisely why a detector score is not an answer.

**On real California purchase orders, D3's assumption fails outright.** A synthetic item sits
within 11% of its category median; a real one sits **5.63× away**. The published UNSPSC
taxonomy is not a price norm at any level.

**And 48.7%** of D1's real-data flags pair two line items of the *same* purchase order —
a failure mode the synthetic generator cannot produce, because it emits one row per
transaction.

**Say:** a project that only reports what worked has not measured anything.

---

## 12 — Limitations *(say these before you are asked)*

1. We find duplicate **transaction records**, not confirmed duplicate **payments** —
   confirming a double disbursement needs invoice-to-payment reconciliation
2. Detection covers 100% of rows; **investigation covers prioritized cases**, not all of them
3. Triage accuracy is measured on a **severity-biased sample**
4. The procurement **policy is ours** — derived from GFR 2017 and CVC guidance, because no
   dataset ships with the policy it was bought under
5. Semantic citation checking is **model-judged**, and reported separately for that reason
6. Precision is **understated** against injected ground truth — real anomalies already in the
   data count as false positives
7. **No claim** of better raw detection accuracy than commercial systems

---

## 13 — Where it runs, and what is next

**It runs locally, and that is measured too.** Qwen2.5-3B under Ollama, **2,158 MiB of a
4 GB card**, with every non-loopback connection blocked: **5 audit notes, 3 of them verified,
100% of cited values matching by rule.** A three-billion-parameter model on a laptop GPU
produces checkable audit notes. No cloud dependency, no per-seat cost.

*(Reported as its own row, never pooled with the hosted model's numbers — D-33.)*

**Next:** pseudo-categories for D3 and a document id for the duplicate detector — both open
issues with the measurement that motivates them already recorded (O-05, O-07).

---

## Backup slides — have these, do not present them

| If asked | Slide |
|---|---|
| "How does D1 decide?" | Fellegi–Sunter: blocks on amount+date, scores pairs by MAP-EM |
| "Why not Benford for D4?" | It accused 61 of 210 real suppliers. Peer tests + Fisher + FDR instead |
| "Cost per investigation?" | 34,275 tokens, 10.0 tool calls, 32.5 s |
| "How big is the real dataset?" | 346,018 line items read, 336,995 loaded |
| "Is the agent sample complete?" | **Yes — 21 notes on seed 42.** Held-out seeds 7 and 2026 have detection metrics but no agent run — stated in the report |
| "Can you prove a note is not invented?" | Corrupt one by hand — the Verifier rejects it on value, row id and clause |

---

## Before you build the deck

- [ ] `spendguard report detection|agent|headline` — regenerate, then paste
- [ ] `spendguard check-evaluation` — every quoted figure matches its results file
- [ ] Run the wording pass in [PRESENTATION.md](PRESENTATION.md) §4 over the finished slides
- [ ] Every number on a slide appears in `docs/results/` — if it does not, it is not a result
