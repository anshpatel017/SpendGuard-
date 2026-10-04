import type { AnomalyType } from "../api/types";
import { ANOMALY_LABEL } from "./format";

/**
 * How the live demo explains its own result (D-34).
 *
 * This used to be one fixed sentence saying a miss was "small price markups,
 * hard to separate from honest premium purchases" — whatever had actually been
 * missed. On a run that caught the inflation and missed a duplicate it
 * contradicted the table printed directly above it, and it claimed a miss even
 * when nothing had been missed at all.
 *
 * The demo's whole credibility rests on showing misses as misses (DEMO.md), so
 * the sentence now names what was missed and makes no claim about why beyond
 * pointing at the measured recall.
 */
export function missExplanation(missed: AnomalyType[]): string {
  if (missed.length === 0) {
    return (
      "Everything planted was caught this time. That is not guaranteed — the detectors' " +
      "measured recall is below 1.0, and on another seed something here would be missed " +
      "and shown as missed."
    );
  }
  const names = missed.map((t) => ANOMALY_LABEL[t].toLowerCase()).join(", ");
  const subject = missed.length === 1 ? "this is a case" : "these are cases";
  return (
    `A miss is shown as a miss, and it is what the measured recall predicts: the Evaluation ` +
    `page has each detector's recall, and ${subject} it describes. Missed here: ${names}.`
  );
}
