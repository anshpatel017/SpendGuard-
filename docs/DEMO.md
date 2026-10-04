# Demo walkthrough

The script for showing SpendGuard: what to run, in what order, what to say, and
what to do when something fails in front of people.

**The arc, in one line each.** Existing tools stop at a risk score. A score is
not a finding, and the gap between them is an auditor's afternoon. SpendGuard
detects across 100% of transactions, then *investigates* the prioritized cases
and hands over a case file whose every citation has been checked.

Read [DECISIONS.md](DECISIONS.md) before presenting. Most hard questions are
answered there, and answering one with "we measured that, here is the number" is
worth more than any slide.

---

## 0. Before anyone is in the room

```bash
spendguard check-policy                 # policy.md and config.py agree
spendguard check-evaluation             # every quoted figure matches its results file
spendguard check-llm                    # chat, tool calling, and a second turn
spendguard freeze --seed 42             # hash and snapshot the state you will serve
spendguard serve --frozen               # serve it, from a fresh working copy
```

> **Verified end to end on 2026-09-29**, not just unit-tested: snapshot taken, dashboard served from a fresh copy, a case confirmed through the API, server relaunched — the case came back `new` and all four file hashes still matched. Rehearse it anyway; the point of a walkthrough is that nothing is being tried for the first time in the room.

- **Serve `--frozen`, not a live store.** Audit notes come from a language model
  and are not reproduced word for word by a rerun. The frozen state is the notes
  that were actually checked, with a SHA-256 manifest. It is also re-copied on
  every launch, so a click during a rehearsal cannot change what the room sees
  (D-34).
- **Have the dashboard already built** (`npm run build` in `frontend/`), or
  `serve` has nothing to serve.
- **Open the tabs in advance**: the queue, one case page, the evaluation page,
  the live-demo page. Do not navigate from scratch while talking.
- **Know your one case.** Pick a case with a verified note beforehand and be able
  to say what the agent found and why it matters. A demo that hunts for a good
  example loses the room.

---

## 1. The problem (60 seconds, no screen)

Procurement fraud hides in volume. An organization runs hundreds of thousands of
purchase records a year; an audit team samples a few hundred. Existing analytics
tools flag anomalies — and then stop, handing over a ranked list of suspicions
with no explanation attached to any of them.

**Say the gap out loud, because it is the contribution:** a score tells you
*where* to look, not *what you found*. Somebody still has to open the records,
work out whether there is an innocent explanation, check it against policy, and
write it up. That is the work SpendGuard automates, and the part nobody else
automates.

---

## 2. Detection across 100% of rows

Show the **queue**.

- Every transaction is scanned — not a sample. The coverage line on the
  dashboard says how many cases were flagged, how many investigated, how many
  still queued, and those three are always consistent.
- Four classes: duplicate transaction records, split purchases, price inflation,
  vendor red flags.
- Sort by severity. Filter by type. Note the filters live in the URL, so a case
  can be sent to a colleague as a link.

**The honest line, and say it before you are asked:** detection covers 100% of
rows; *investigation* is top-N by severity, because each investigation costs a
minute or two of model time (D-05). Never say "investigates every flagged case".

---

## 3. The case file — this is the demo

Open the case you chose. Take it slowly; everything before this was setup.

1. **The finding.** One paragraph, written by the agent, about this specific
   supplier and these specific rows.
2. **Click a citation.** The evidence row highlights and scrolls into view. Every
   claim carries the row ids it rests on — the note is structured claims, not
   prose with numbers sprinkled in (D-29).
3. **The verification badge.** Explain what it means: a second agent, with a
   fresh context, checked that every cited row exists and that every stated value
   matches at the precision it was stated. That check involves no model at all.
   A separate model-judged check asks whether the evidence *supports* the claim.
   **The two numbers are reported side by side and never blended** (D-13, D-31).
4. **The trace.** Every tool call the agent made, what it asked, what came back.
   Nothing about the note is unexplainable.

**If you show one thing, show a dismissal.** A case the agent marked
`likely_false_positive` — a "duplicate" that turned out to be a fixed monthly
contract — is the strongest single artefact the project has, because it is the
part a score cannot do. Have one ready.

**And say what it does not do:** the agent never closes a case. It writes a note,
a verdict and a final severity; a person moves the case (D-04). Show the review
panel and move a case yourself.

---

## 4. The live injection demo (2 minutes)

Open the **Live demo** page and inject 3 anomalies.

- It plants them in a *temporary copy* of the last three months of the clean
  dataset, runs detection, and reports which were caught. The data being served
  is never touched, and a test hashes it before and after.
- Takes 3–8 seconds.

**Misses are shown as misses.** On rehearsal seeds it catches 2 of 3. The page
names whatever was actually missed on the run in front of you and points at the
measured recall on the Evaluation page, rather than guessing a cause; on a run
that misses nothing it says so without promising a clean sweep next time.
**Do not apologise for this, and do not re-roll for a better seed.** Say: "that
is the detector's measured recall, and it is why the investigation layer
exists" — D3's is about 0.48, the one most likely to be on screen. A demo
rigged to always succeed would contradict the evaluation it is meant to
illustrate.

---

## 5. The numbers (evaluation page)

| What to show | What to say |
|---|---|
| Detectors vs the rule baseline | D1 0.949, D2 0.724, D4 0.853 per-case F1, mean ± sd across three seeds |
| **D3 below the baseline on F1** | Say it plainly. It wins on ranking (PR-AUC) and loses on F1, because honest premium purchases sit in the same price band as the injected markups. This is the single best illustration of why a score is not a finding. |
| Citations valid | The rule-checked number is the headline; the model-judged one sits beside it |
| Ablations | The template arm cites just as accurately and triages far worse — which is the thesis in one row |

**Every figure regenerates from one command**, and `spendguard check-evaluation`
fails if the document and the results files ever disagree. Offer to run it.

**Seeds 7 and 2026 were never looked at during design.** Say so — an examiner
who has to ask is less impressed than one who is told.

---

## 6. Real data, and what it broke

Worth two minutes, because it is where the project stops being a toy.

346,018 California purchase-order line items. Three findings synthetic data
could not have produced (EVALUATION 4.0c):

- **D3's assumption fails on a real taxonomy.** A typical synthetic item sits
  within 11% of its category median; a typical California item sits 5.63× away.
  The same threshold that means "twice the going rate" on one dataset means a
  million times on the other.
- **48.7% of D1's real-data flags pair two lines of the same purchase order** —
  one order written across two lines, not two records. The synthetic generator
  emits one row per transaction, so the failure mode could not appear there.
- **Nothing is labelled**, so precision on real data is estimated from a reviewed
  sample and reported with a Wilson interval — never as a bare percentage.

A panel that hears a team explain how its own detector fails, with numbers, will
trust the numbers that worked.

---

## 7. Closing

Local and open-source. No cloud dependency in the design: the provider is one
line of configuration, and the same code runs against a local model.

Then the honest caveats, said rather than extracted — they are in
[EVALUATION.md](EVALUATION.md) §9, and saying them yourself is the point.

---

## When it goes wrong

| If | Do |
|---|---|
| The dashboard will not load | You rehearsed on `--frozen`; relaunch it. Never debug a dev server in front of people. |
| The live injection fails or is slow | Move on and show the frozen results instead. Say the injection is bounded to a copy and occasionally the copy is slow; it is not the point of the demo. |
| A detector shows a result you did not expect | Say what you see, not what you hoped. The queue is live over a real store — "that is the flag, and here is what an investigation would do with it" is a fine answer. |
| Asked for a number you do not have | "That is measured in the results file, I do not want to guess at it" beats an invented figure. Every one is in `docs/results/`. |
| The agent looks slow | It is: 1–3 minutes a case on a free tier. That is a quota constraint, not an architectural one, and the frozen state exists precisely so you never wait in front of an audience. |

---

## Questions to expect

**"Why not just use a commercial tool?"**
They stop at the score. The layer after detection — investigation with checked
citations — is the contribution. Also: open-source, local, no per-seat cost.

**"How do you know the agent is not making things up?"**
That is what the Verifier is for, and it is why citation validity is reported as
two numbers. The rule-checked one involves no model: the row either exists and
the value either matches, or it does not.

**"Your D3 is worse than the baseline."**
On F1, yes, and the report says so. It ranks better, and on real data its
category assumption fails outright — both measured, both written down. A project
that only reports what worked has not measured anything.

**"Is this real fraud?"**
No. The synthetic anomalies are planted and known; the California flags are
suspicions, not findings, and are labelled as *value implicated by flagged
transactions*, never as fraud detected.

**"What would you do with more time?"**
Pseudo-categories for D3 and a document id for the duplicate detector — both
open issues with the measurement that motivates them already recorded (O-05,
O-07). Naming your own next step, with evidence, is a strong finish.
