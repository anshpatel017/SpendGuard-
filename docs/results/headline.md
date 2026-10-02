# Headline result

Generated 2026-10-02 17:13 UTC from commit `74e4aac` **(uncommitted changes)**. Regenerate with `spendguard report headline`. **Do not edit this sentence by hand** - it exists so the most-quoted numbers in the project cannot drift from the runs that produced them.

---

> On 50,963 seeded synthetic transactions carrying 508 planted anomalies, across 3 seeds, SpendGuard's four detectors reach a pooled per-case **F1 of 0.689 ± 0.006** against a rule-based baseline at **0.205 ± 0.007**. Citation validity is **provisional**: 100.0% over only 8 note(s), below the 20 this project will quote a rate from. The sample fills at roughly ten investigations a day. Value implicated in real spend: not yet measured - run `spendguard review report`.

---

## Where each figure comes from

| Figure | Value | Source |
|---|---|---|
| transactions | 50,963 | detection.json |
| planted anomalies | 508 | detection.json |
| SpendGuard F1 (per case) | 0.689 ± 0.006 | detection.json |
| baseline F1 (per case) | 0.205 ± 0.007 | detection.json |
| citation validity (rule-checked) | 100.0% over 8 note(s) | agent.json - provisional, sample still filling |
| value implicated | not yet measured | real-data.json is absent |

The detection figures are from the **seeded synthetic** dataset, which is the only one with an answer key; the real-data figures are from **California purchase orders**, which have none. The sentence keeps them apart on purpose: one sentence covering both would read as though the F1 had been achieved on real procurement, and it was not.

**Incomplete: value implicated.** The sentence says so rather than leaving a gap for someone to fill in from memory.
