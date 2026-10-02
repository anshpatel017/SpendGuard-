# Agent results - investigation and verification

Generated 2026-10-02 17:13 UTC from commit `74e4aac`. Regenerate with `spendguard report agent`.

Read from the evaluation stores, not from any single run: notes accumulate a few a day against a free-tier daily quota (D-30), and the newest note per (case, model, arm) is the one that stands. **Numbers are per model** - two models are never merged into one row (D-33) - and ablation arms sit beside the main run, never inside it (D-35).

## Citation validity

**The deterministic column is the headline** - rows exist and every stated value matches, checked by rule with no model involved. The semantic column is judged by a model and is labelled so; the two are never blended (D-13). *First draft* is what the Investigator produced unaided, so the gap to *released* is what the Verifier's regeneration bought.

| Seed | Model | Arm | Notes | Citations | First draft | Released (deterministic) | Supported (model-judged) | Regenerated |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 8 | 73 | 100.0% | **100.0%** | 89.7% | 6 |
| 42 | template | template | 5 | 35 | 100.0% | **100.0%** | - | 0 |

## Triage - what the agent filters

Over the seeded sample of real and spurious cases for each seed. *Real kept* is the share of genuine anomalies the agent did not dismiss; *spurious filtered* is the share of false alarms it did. A template arm scores 0 on the second by construction - it cannot weigh an innocent explanation - which is the comparison the arm exists to make.

| Seed | Model | Arm | Sample | Investigated | Real kept | Spurious filtered | Decisive accuracy |
|---:|---|---|---:|---:|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 15 | 7 | 100% | 50% | **100%** |
| 42 | template | template | 5 | 5 | 100% | 0% | **80%** |

## Cost per investigation

| Seed | Model | Arm | Tool calls | Tokens | Seconds of model time |
|---:|---|---|---:|---:|---:|
| 42 | qwen/qwen3.8-27b | agent | 7.9 | 32,886 | 34.0 |
| 42 | template | template | 0.0 | 0 | 0.0 |

**Some runs stopped on the provider's daily quota** and have fewer notes than their sample: seed 42 / qwen/qwen3.8-27b / agent. Running the same command later continues where it stopped (D-30).


**1 arm(s) are still short of their sample.** Every rate above is over the notes that exist, so it will move as the rest arrive. Treat a row with fewer than ~20 notes as an indication, not a rate.

