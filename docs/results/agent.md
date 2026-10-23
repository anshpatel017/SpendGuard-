# Agent results - investigation and verification

Generated 2026-10-23 19:08 UTC from commit `4df74a6`. Regenerate with `spendguard report agent`.

Read from the evaluation stores, not from any single run: notes accumulate a few a day against a free-tier daily quota (D-30), and the newest note per (case, model, arm) is the one that stands. **Numbers are per model** - two models are never merged into one row (D-33) - and ablation arms sit beside the main run, never inside it (D-35).

## Citation validity

**The deterministic column is the headline** - rows exist and every stated value matches, checked by rule with no model involved. The semantic column is judged by a model and is labelled so; the two are never blended (D-13). *First draft* is what the Investigator produced unaided, so the gap to *released* is what the Verifier's regeneration bought.

| Seed | Model | Arm | Notes | Citations | First draft | Released (deterministic) | Supported (model-judged) | Regenerated |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 19 | 183 | 100.0% | **100.0%** | 88.0% | 12 |
| 42 | qwen2.5:3b-instruct-q4_K_M | agent | 5 | 12 | - | **100.0%** | 83.3% | 3 |
| 42 | template | template | 17 | 97 | 100.0% | **100.0%** | 73.0% | 0 |

## Triage - what the agent filters

Over the seeded sample of real and spurious cases for each seed. *Real kept* is the share of genuine anomalies the agent did not dismiss; *spurious filtered* is the share of false alarms it did. A template arm scores 0 on the second by construction - it cannot weigh an innocent explanation - which is the comparison the arm exists to make.

**The investigated subset is severity-biased** (FR-7.6). The sample is drawn per anomaly type, but cases are worked highest-severity first and a spent daily quota stops the run where it stands, so an arm whose *Investigated* count is below its *Sample* has been scored on its higher-severity cases. Those are not a random half: a high-severity case tends to carry more rows and a larger amount, so these rates should not be read as rates over the whole sample until the counts match.

| Seed | Model | Arm | Sample | Investigated | Real kept | Spurious filtered | Decisive accuracy |
|---:|---|---|---:|---:|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 20 | 17 | 92% | 75% | **88%** |
| 42 | qwen2.5:3b-instruct-q4_K_M | agent | 5 | 5 | 75% | 0% | **60%** |
| 42 | template | template | 15 | 14 | 100% | 0% | **79%** |

## Cost per investigation

| Seed | Model | Arm | Tool calls | Tokens | Seconds of model time |
|---:|---|---|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 10.0 | 34,078 | 29.9 |
| 42 | qwen2.5:3b-instruct-q4_K_M | agent | 17.0 | 27,064 | 47.9 |
| 42 | template | template | 0.0 | 391 | 0.3 |

**Some runs stopped on the provider's daily quota** and have fewer notes than their sample: seed 42 / qwen/qwen3.8-27b / agent, seed 42 / template / template. Running the same command later continues where it stopped (D-30).


**1 arm(s) are still short of their sample.** Every rate above is over the notes that exist, so it will move as the rest arrive. Treat a row with fewer than ~20 notes as an indication, not a rate.

