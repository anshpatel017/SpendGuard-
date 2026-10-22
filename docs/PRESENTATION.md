# PRESENTATION.md — what to put on the slides, and where every number comes from

The walkthrough is [DEMO.md](DEMO.md). This is the other half: the figures you are
allowed to quote, the sentence each one belongs in, and the limitations slide written
out so it is said rather than extracted.

**Regenerate before you present.** Every figure below is produced by a command, and the
numbers move as the evaluation fills:

```bash
spendguard report detection      # docs/results/detection.{md,json}
spendguard report agent          # docs/results/agent.{md,json}
spendguard report headline       # docs/results/headline.{md,json}
spendguard check-evaluation      # fails if any figure in EVALUATION.md has drifted
```

---

## 1. The one sentence

Generated, never typed. It lives in `docs/results/headline.md` and refuses to quote a
citation rate until the sample reaches 20 notes:

> On 50,963 seeded synthetic transactions carrying 508 planted anomalies, across 3 seeds,
> SpendGuard's four detectors reach a pooled per-case **F1 of 0.689 ± 0.006** against a
> rule-based baseline at **0.205 ± 0.007**.

**Do not merge the synthetic and real figures into one sentence.** The F1 is from the
seeded synthetic dataset, which is the only one with an answer key. The California
purchase orders have none. One sentence covering both reads as though the F1 were
achieved on real procurement, and it was not.

---

## 2. Every number, and the file it comes from

### Detection — `docs/results/detection.md`, from `spendguard report detection`

| Figure | Value | Where |
|---|---|---|
| Transactions audited | 50,963 | Per case table header |
| Planted anomaly groups | 508 | Per seed table |
| Seeds | 42 (tuned on), 7, 2026 (held out) | Per seed table |
| **SpendGuard pooled F1** | **0.689 ± 0.006** | Per case, `all / SPENDGUARD` |
| **Baseline pooled F1** | **0.205 ± 0.007** | Per case, `all / baseline` |
| D1 duplicates F1 | 0.949 ± 0.009 | Per case |
| D2 splits F1 | 0.724 ± 0.013 | Per case |
| D3 inflation F1 | 0.419 ± 0.009 | Per case — **below its baseline, say so** |
| D4 vendor F1 | 0.853 ± 0.082 | Per case |
| False positives on clean data | D1 0, D2 0, D4 0; D3 154 of 49,900 (0.31%) | Clean data table |
| Reproducibility | seed 42 re-detected, identical | Reproducibility section |

The ± is the sample standard deviation across the three seeds, not a confidence interval.

### Agent — `docs/results/agent.md`, from `spendguard report agent`

| Figure | Value | Caveat you must say with it |
|---|---|---|
| Notes written (seed 42) | 17 of a 20-case sample | Sample still filling — 3 short of the 20 the headline needs |
| **Local model, same seed** | **5 notes, 3 verified, 100% rule-checked** | Qwen2.5-3B under Ollama. Its own row, never pooled with the hosted model (D-33) |
| **Citation validity, rule-checked** | **100.0%** over 164 citations | This is the headline number — no model involved |
| Citation validity, model-judged | 87.8% | Always reported *beside* the above, never blended into it (D-13) |
| First-draft validity | 100.0% | What the Investigator produced unaided |
| Notes verified | 9 of 17 (6 failed checks, 2 unverified) | `verified` requires **both** checks to pass |
| Cost per investigation | 33,700 tokens, 9.6 tool calls, 30 s | Free tier, ~10 investigations a day |

### The ablation — the strongest single table you have

| Arm | Released | Model-judged | Real kept | **Spurious filtered** | **Decisive accuracy** |
|---|---:|---:|---:|---:|---:|
| **agent** | 100% | 86.1% | 82% | **100%** | **100%** |
| template | 100% | 73.0% | 100% | **0%** | **79%** |

Both arms on the same 15-case sample. The template keeps every real anomaly because it
never dismisses anything, and filters none of the spurious ones for the same reason — it
cannot weigh an innocent explanation. **That is the whole argument for the investigation
layer, measured rather than asserted.**

### Real data — `docs/EVALUATION.md` §4.0c

| Figure | Value |
|---|---|
| California purchase order line items | 346,018 read, 336,995 loaded |
| D3's category spread, real vs synthetic | 5.63× vs 1.11× from the category median |
| D1 flags pairing two lines of one order | 48.7% of 12,257 |
| Conversion | USD → INR at a pinned 60.0, dated 2014-01-01 |

### Not yet measured — say this rather than leaving a gap

- **Value implicated in real spend.** Needs the three-reviewer batch; run
  `spendguard review report` once the sheets return.
- **Note quality scores and grader agreement.** Needs the three-grader batch.
- **Held-out seeds for the agent.** Seeds 7 and 2026 have detection metrics but no agent
  notes. Any claim about the agent generalising across seeds is unsupported today.

---

## 3. The limitations slide, written out

Say these. Being asked them is weaker than volunteering them.

> **What this does not do**
>
> 1. **It finds duplicate transaction records, not confirmed duplicate payments.**
>    Confirming a double disbursement needs invoice-to-payment reconciliation against a
>    payments ledger, which these datasets do not contain.
>
> 2. **Detection covers 100% of rows; investigation does not.** The agent works the
>    highest-severity cases, bounded by a free-tier quota. The claim is "detects across
>    100% of transactions, then autonomously investigates prioritized cases" — never
>    "investigates every flagged case".
>
> 3. **Triage accuracy is measured on a severity-biased sample**, for the same reason:
>    cases are worked highest-severity first, so an incomplete arm has been scored on its
>    harder, larger cases.
>
> 4. **The procurement policy is ours.** Clauses are derived from India's GFR 2017 and CVC
>    guidance, but no dataset ships with the policy it was bought under, so the RAG corpus
>    is authored rather than issued.
>
> 5. **Semantic citation checking is model-judged**, and is reported separately from the
>    deterministic check for exactly that reason.
>
> 6. **Precision is understated against injected ground truth.** Real anomalies already in
>    the data count as false positives. Adjusted precision needs human review.
>
> 7. **No claim of better raw detection accuracy than commercial systems** trained on
>    proprietary corpora. The contribution is the layer after detection.

---

## 4. Wording rules for the slides

The repository has been checked against these. **The slides have not** — this is the pass
to do before you print.

| Never write | Write instead |
|---|---|
| "duplicate payments" on purchase-order data | "duplicate **transaction records** (POs or payments, depending on the source system)" |
| "investigates every flagged case" | "detects across 100% of transactions, then autonomously **investigates prioritized cases**" |
| "more accurate than commercial tools" | "the contribution is the layer *after* detection" |
| "fraud detected" on California data | "**value implicated** by flagged transactions" |
| a citation rate with no sample size | "100% over 17 notes" — the sample size travels with the rate |

---

## 5. The four questions, and the answers that hold

**"Your D3 is worse than the baseline."**
On F1, yes — 0.419 against 0.432, and the report says so on its face. It ranks better
(PR-AUC 0.280 against 0.196), and on real data its category assumption fails outright. Both
measured, both written down. A project that only reports what worked has not measured
anything.

**"How do you know the agent is not making things up?"**
Two numbers, never blended. The rule-checked one involves no model at all: the row either
exists and the stated value either matches, or it does not. We corrupt a note by hand and
the Verifier rejects it — wrong value, nonexistent row, invented clause, all three.

**"Is this real fraud?"**
No. The synthetic anomalies are planted and known. The California flags are suspicions,
labelled as value implicated, never as fraud detected.

**"Is it actually local?"**
Yes, and it was run that way. Qwen2.5-3B-Instruct under Ollama, 2,158 MiB of a 4 GB
RTX 2050, writing **5 audit notes with 2 verified** while every non-loopback connection
was blocked. The provider is one line of configuration; the evaluation numbers come from
the hosted free tier because it is faster per case, not because anything needs it.

---

## 6. Before you present

```bash
spendguard check-policy          # policy.md and config.py agree
spendguard check-evaluation      # every quoted figure matches its results file
spendguard freeze --seed 42      # snapshot the state you will serve
spendguard serve --frozen        # serve it
spendguard demo --count 3        # once, to warm the file cache: first run 13 s, then 4 s
```

Then open the tabs you need in advance, and pick the one case you will talk through.
