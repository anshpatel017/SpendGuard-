"""Template notes: the ablation that asks what the agent is actually worth (EVALUATION 6).

A template note is filled straight from the detector's own output and the rows
it flagged. No model, no tools, no judgement - the strongest thing that can be
built without an agent, and therefore the fair thing to compare one against.

What it can do, by construction:

* cite real rows and state their values correctly, because it copies them;
* quote the policy clause the detector's rule comes from;
* describe the pattern the detector matched.

What it cannot do, also by construction:

* **decide**. It has no way to find the innocent explanation - a fixed monthly
  contract, a premium specification, two genuinely separate requirements - so
  every case comes back ``likely_true_positive``. That is the claim under test
  (D-04): if dismissing false positives has value, the template arm should show
  high citation validity and poor triage.
* explain *why* this case is or is not what the detector thinks. It restates.

Notes are stored as an ablation, so they never stand as a case's own note.
"""

from __future__ import annotations

from typing import Any

from spendguard.ablations import TEMPLATE
from spendguard.agent.note import CHECKABLE_FIELDS, Claim, Fact, InvestigatorNote, Verdict
from spendguard.cases import AnomalyType, Case
from spendguard.config import settings

ABLATION_NAME = TEMPLATE  # re-exported so a reader of this module sees the arm it feeds

# The clause each detector's rule comes from. Every id exists in policy/policy.md;
# a test checks that, because a note citing a clause that does not exist is exactly
# what the Verifier is built to catch.
CLAUSES: dict[AnomalyType, list[str]] = {
    AnomalyType.DUPLICATE: ["SG-PP-4.4", "SG-PP-4.1"],
    AnomalyType.SPLIT: ["SG-PP-3.1", "SG-PP-3.2"],
    AnomalyType.INFLATION: ["SG-PP-6.3", "SG-PP-6.2"],
    AnomalyType.VENDOR_FLAG: ["SG-PP-5.5", "SG-PP-5.3"],
}

ACTIONS: dict[AnomalyType, str] = {
    AnomalyType.DUPLICATE: (
        "Check the flagged records against the supplier's invoices before any further payment, "
        "and recover under SG-PP-4.5 if the obligation was met twice."
    ),
    AnomalyType.SPLIT: (
        "Ask the approving officer to explain the orders in writing and confirm whether they form "
        "one requirement under SG-PP-3.4."
    ),
    AnomalyType.INFLATION: (
        "Obtain the recorded justification for the rate under SG-PP-6.2 and compare it with the "
        "supplier's other purchases of the same item."
    ),
    AnomalyType.VENDOR_FLAG: (
        "Review the supplier's registration and bank details under SG-PP-5.1 and SG-PP-5.2, and "
        "the orders of the officers who approved its invoices."
    ),
}


def _facts(row: dict[str, Any], fields: tuple[str, ...]) -> list[Fact]:
    return [
        Fact(row_id=int(row["row_id"]), field=f, value=row[f])
        for f in fields
        if f in CHECKABLE_FIELDS and row.get(f) is not None
    ]


def _money(value: Any) -> str:
    return settings.money(float(value or 0.0))


def _finding(case: Case, rows: list[dict[str, Any]]) -> str:
    """One paragraph restating what the detector matched. No interpretation."""
    kind = case.anomaly_type
    count = len(case.row_ids)
    supplier = rows[0]["vendor_name"]
    dates = sorted(str(r["txn_date"]) for r in rows)
    when = f"on {dates[0]}" if dates[0] == dates[-1] else f"from {dates[0]} to {dates[-1]}"
    # "Amount at risk" is not one quantity: D1 counts the repeat records, D2 the
    # run's total, D3 only the excess over the benchmark, D4 the supplier's billing.
    # Saying which one this is stops the figure reading as a contradiction of the
    # line total the claims state.
    at_risk = {
        AnomalyType.DUPLICATE: "in the repeated records",
        AnomalyType.SPLIT: "across the run",
        AnomalyType.INFLATION: "as the excess over the category benchmark",
        AnomalyType.VENDOR_FLAG: "in the supplier's billing for the period",
    }[kind]
    common = (
        f"Detector {case.detector.upper()} flagged {count} transaction record"
        f"{'' if count == 1 else 's'} from {supplier}, {_money(case.amount_at_risk)} at risk "
        f"{at_risk}, at a detector score of {case.detector_score:.2f}."
    )
    if kind is AnomalyType.DUPLICATE:
        return (
            f"{common} The records match on the fields the duplicate rule compares - amount within "
            f"{settings.duplicate_amount_tolerance:.1%} and within "
            f"{settings.duplicate_date_window_days} days, {when} - which "
            "SG-PP-4.4 lists as indicators of a duplicate transaction record."
        )
    if kind is AnomalyType.SPLIT:
        total = sum(float(r["amount"]) for r in rows)
        return (
            f"{common} The records total {_money(total)}, above the "
            f"{settings.money(settings.approval_threshold)} approval threshold, while each part "
            f"falls below it, {when} and so inside the {settings.split_window_days}-day window. "
            "SG-PP-3.2 lists that pattern as an indicator of splitting."
        )
    if kind is AnomalyType.INFLATION:
        row = rows[0]
        rate = (
            f"unit price of {_money(row['unit_price'])}"
            if row.get("unit_price") is not None
            else f"line total of {_money(row['amount'])}"
        )
        return (
            f"{common} The {rate} for {row.get('item_desc') or 'the item'} is above the recent "
            "median for its category, which SG-PP-6.3 treats as an indicator of price "
            "irregularity."
        )
    return (
        f"{common} The supplier's billing differs from its peers on the tests SG-PP-5.5 lists as "
        "indicators of vendor irregularity."
    )


def _claims(case: Case, rows: list[dict[str, Any]]) -> list[Claim]:
    kind = case.anomaly_type
    cited = [int(r["row_id"]) for r in rows]
    if kind is AnomalyType.DUPLICATE:
        distinct = {float(r["amount"]) for r in rows}
        amounts = (
            f"each for {_money(rows[0]['amount'])}"
            if len(distinct) == 1
            else "for " + ", ".join(_money(r["amount"]) for r in rows)
        )
        return [
            Claim(
                # "Each for X" only when they really are equal: D1 matches within a
                # tolerance, so the amounts need not be. A claim the data does not
                # support is the one thing a template has no excuse for.
                text=f"The flagged records are {amounts}.",
                row_ids=cited,
                facts=[f for r in rows for f in _facts(r, ("amount",))],
            ),
            Claim(
                text="They were recorded on these dates, under these invoice references.",
                row_ids=cited,
                facts=[f for r in rows for f in _facts(r, ("txn_date", "invoice_no"))],
            ),
        ]
    if kind is AnomalyType.SPLIT:
        total = sum(float(r["amount"]) for r in rows)
        return [
            Claim(
                text=(
                    f"The {len(rows)} records total {_money(total)}, above the "
                    f"{settings.money(settings.approval_threshold)} threshold, each part below it."
                ),
                row_ids=cited,
                facts=[f for r in rows for f in _facts(r, ("amount",))],
            ),
            Claim(
                text="They fall within the scrutiny window, on these dates.",
                row_ids=cited,
                facts=[f for r in rows for f in _facts(r, ("txn_date",))],
            ),
        ]
    if kind is AnomalyType.INFLATION:
        row = rows[0]
        rate = (
            f"priced at {_money(row['unit_price'])} per unit for {row['quantity']:g} units, "
            if row.get("unit_price") is not None and row.get("quantity") is not None
            else ""
        )
        return [
            Claim(
                text=f"The record is {rate}{_money(row['amount'])} in total.",
                row_ids=cited,
                facts=_facts(row, ("unit_price", "quantity", "amount")),
            )
        ]
    shown = rows[: settings.verifier_max_rows]
    return [
        Claim(
            text=(
                f"The supplier billed {len(case.row_ids)} transactions in the period; these are "
                f"{len(shown)} of them."
            ),
            row_ids=[int(r["row_id"]) for r in shown],
            facts=[f for r in shown for f in _facts(r, ("amount", "txn_date"))],
        )
    ]


def template_note(case: Case, rows: list[dict[str, Any]]) -> InvestigatorNote:
    """A note built from the detector's output alone - the ablation's writer."""
    if not rows:
        raise ValueError(f"case {case.case_id} has no evidence rows to write about")
    return InvestigatorNote(
        # A template cannot weigh an innocent explanation, so it always agrees
        # with the detector. That is the point of the comparison, not a defect.
        verdict=Verdict.LIKELY_TRUE_POSITIVE,
        finding=_finding(case, rows),
        claims=_claims(case, rows),
        policy_clauses=CLAUSES[case.anomaly_type],
        recommended_action=ACTIONS[case.anomaly_type],
    )
