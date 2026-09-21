"""What the Investigator is told: rules, per-type guidance, one example, the case.

Kept apart from the loop so the prompt can be read, argued about and changed
without touching control flow - and so an ablation can swap it wholesale.

Three choices worth defending:

* **Only the relevant example is shown.** Four worked examples cost tokens on
  every turn of every investigation, and a small local model imitates whatever
  it sees; one example of the right type is both cheaper and less confusing.
* **The model is told to look for the innocent explanation first.** The
  detectors are tuned for recall and D3 shares its price band with honest
  premium purchases (D-23). An investigator that only confirms flags adds
  nothing; one that can dismiss them is the contribution (D-04).
* **Arithmetic goes through the calculator.** A figure the model computed in
  its head is a figure the Verifier cannot trust.
"""

from __future__ import annotations

import json
from typing import Any

from spendguard.agent.note import CHECKABLE_FIELDS, NOTE_TEMPLATE
from spendguard.cases import AnomalyType, Case
from spendguard.config import settings

SYSTEM_PROMPT = """\
You are a procurement auditor investigating ONE case that an automated detector \
flagged. Gather evidence with the tools, decide whether the flag is a real \
problem, and write an audit note.

Rules - every one is checked:
1. Every factual claim cites the row_ids it rests on. No claim without a citation.
2. Only cite rows you have actually seen, in the case evidence or a tool result. \
Never invent or guess a row_id.
3. Compute every figure with the calculator tool. Never do arithmetic yourself.
4. Cite policy by clause id (for example SG-PP-4.4). Find clauses with policy_lookup.
5. The detector can be wrong. Look for the innocent explanation first - a fixed \
monthly contract, a premium specification, an urgent purchase, separate \
requirements - and weigh it against the evidence.
6. Verdicts:
   - likely_true_positive: the evidence supports the anomaly.
   - likely_false_positive: a legitimate explanation fits the evidence better.
   - inconclusive: the evidence cannot settle it; say what a human should check.
7. You recommend; a human decides. Never say a case is closed or dismissed.
8. Say "duplicate transaction record", never "duplicate payment": these records \
may be purchase orders.
9. Use at most {max_steps} tool calls. When you have enough evidence, stop \
calling tools and reply with the JSON note and nothing else.

A fact may name only these fields: {fields}.

Reply format - exactly one JSON object:
{template}
"""

# What to check for each anomaly type, and the clauses that usually apply.
GUIDANCE: dict[AnomalyType, str] = {
    AnomalyType.DUPLICATE: """\
Duplicate transaction records. Compare the flagged rows field by field: supplier \
name spelling, invoice number (the same number retyped, such as INV-04471 and \
4471/2025, is strong evidence), amount, date gap, officer, item and quantity. \
Then check vendor_profile: a supplier billing one fixed amount every month is a \
recurring contract, not a duplicate. Relevant clauses: SG-PP-4.1 to SG-PP-4.6.""",
    AnomalyType.SPLIT: """\
Split purchase. Add the parts with the calculator and compare the total with the \
approval threshold of {threshold} (SG-PP-2.2). Check whether the parts are the \
same item at the same unit rate, how many days they span, and whether each part \
sits below the threshold. Innocent explanations: genuinely separate needs, or \
instalments of one approved contract (SG-PP-3.5). Relevant clauses: SG-PP-3.1 to \
SG-PP-3.6.""",
    AnomalyType.INFLATION: """\
Price inflation. Compare the unit price with comparable purchases from \
find_similar_invoices and compute how many times the typical price it is. Read \
the item description carefully: the detector ignores it on purpose, but you \
should weigh it - "Premium Grade" or "Urgent Supply" can explain a high price. \
Treat a description as a claim to test, not proof: check whether comparable \
premium or urgent purchases cost as much. Relevant clauses: SG-PP-6.1 to SG-PP-6.5.""",
    AnomalyType.VENDOR_FLAG: """\
Vendor red flag. Use vendor_profile (first seen, officers billed, categories, \
round-number share, fixed-contract pattern) and benford_stats (compare with peers, \
not only with Benford's law - procurement invoices depart from Benford \
routinely). A new supplier billing round amounts to one or two officers at month \
end is the concerning pattern; a long-standing fixed-fee contract is not. \
Relevant clauses: SG-PP-5.1 to SG-PP-5.6 and SG-PP-7.1.""",
}

# One worked example per type. Row ids are illustrative and say so.
EXAMPLES: dict[AnomalyType, dict[str, Any]] = {
    AnomalyType.DUPLICATE: {
        "verdict": "likely_true_positive",
        "finding": (
            "Rows 2847 and 3102 are the same obligation recorded twice: the same supplier, "
            "amount and item, 16 days apart, with the invoice number retyped from INV-04471 "
            "to 4471/2025. The supplier has no fixed monthly billing that would explain a "
            "repeat."
        ),
        "claims": [
            {
                "text": "Both records are from Sharma Traders for Rs 87,450.",
                "row_ids": [2847, 3102],
                "facts": [
                    {"row_id": 2847, "field": "amount", "value": 87450.0},
                    {"row_id": 3102, "field": "amount", "value": 87450.0},
                ],
            },
            {
                "text": "The invoice numbers share the core number 4471.",
                "row_ids": [2847, 3102],
                "facts": [
                    {"row_id": 2847, "field": "invoice_no", "value": "INV-04471"},
                    {"row_id": 3102, "field": "invoice_no", "value": "4471/2025"},
                ],
            },
        ],
        "policy_clauses": ["SG-PP-4.4", "SG-PP-4.5"],
        "recommended_action": (
            "Hold any payment against row 3102 and confirm with the supplier; if already paid, "
            "recover by set-off under SG-PP-4.5."
        ),
    },
    AnomalyType.SPLIT: {
        "verdict": "likely_true_positive",
        "finding": (
            "Three purchase orders from one supplier to one officer within four days total "
            "Rs 3,60,000 against a Rs 2,50,000 threshold. Each is below the limit, all are the "
            "same item at the same unit rate, which reads as one requirement divided to avoid "
            "the tender process."
        ),
        "claims": [
            {
                "text": "The three orders total Rs 3,60,000.",
                "row_ids": [501, 504, 509],
                "facts": [
                    {"row_id": 501, "field": "amount", "value": 120000.0},
                    {"row_id": 504, "field": "amount", "value": 120000.0},
                    {"row_id": 509, "field": "amount", "value": 120000.0},
                ],
            }
        ],
        "policy_clauses": ["SG-PP-3.1", "SG-PP-3.2"],
        "recommended_action": (
            "Ask the officer to explain the three orders in writing; if one requirement, refer "
            "for regularization under SG-PP-3.6."
        ),
    },
    AnomalyType.INFLATION: {
        "verdict": "likely_false_positive",
        "finding": (
            "Row 7710 is priced at 1.9 times the typical rate for its category, but its "
            "description marks it as a premium grade, and comparable premium purchases in the "
            "same category cost about the same. The price is explained, not inflated."
        ),
        "claims": [
            {
                "text": "The unit price is Rs 16,150 against a typical Rs 8,500.",
                "row_ids": [7710],
                "facts": [{"row_id": 7710, "field": "unit_price", "value": 16150.0}],
            },
            {
                "text": "The item is described as a premium grade.",
                "row_ids": [7710],
                "facts": [
                    {
                        "row_id": 7710,
                        "field": "item_desc",
                        "value": "Ergonomic Office Chair - Premium Grade",
                    }
                ],
            },
        ],
        "policy_clauses": ["SG-PP-6.2"],
        "recommended_action": (
            "No price action needed; confirm the premium specification was required, as "
            "SG-PP-6.2 asks for a recorded reason."
        ),
    },
    AnomalyType.VENDOR_FLAG: {
        "verdict": "likely_true_positive",
        "finding": (
            "The supplier first appears late in the period, bills only two officers, and most "
            "of its invoices are exact multiples of Rs 5,000 clustered at month end - far from "
            "how its peers bill. It is not a fixed monthly contract."
        ),
        "claims": [
            {
                "text": "Most invoices are round multiples of Rs 5,000.",
                "row_ids": [9001, 9004, 9007],
                "facts": [
                    {"row_id": 9001, "field": "amount", "value": 45000.0},
                    {"row_id": 9004, "field": "amount", "value": 60000.0},
                ],
            }
        ],
        "policy_clauses": ["SG-PP-5.5", "SG-PP-5.3"],
        "recommended_action": (
            "Verify the supplier's registration and bank details under SG-PP-5.1 and SG-PP-5.2, "
            "and review the approving officers' orders."
        ),
    },
}

# Case evidence shown up front. Vendor cases can carry hundreds of rows; the model
# sees a sample and the aggregate, and can query for more.
MAX_EVIDENCE_ROWS = 8
MAX_METADATA_CHARS = 700


# Compact JSON everywhere the model reads it: every turn resends the whole
# conversation, and the free tier allows 8,000 input tokens a minute.
def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def system_prompt(kind: AnomalyType) -> str:
    base = SYSTEM_PROMPT.format(
        max_steps=settings.agent_max_steps,
        fields=", ".join(CHECKABLE_FIELDS),
        template=_json(NOTE_TEMPLATE),
    )
    guidance = GUIDANCE[kind].format(threshold=settings.money(settings.approval_threshold))
    example = _json(EXAMPLES[kind])
    return (
        f"{base}\n"
        f"How to investigate this type of case:\n{guidance}\n\n"
        f"An example note for this type (its row ids are illustrative - cite only real rows "
        f"from your own case):\n{example}"
    )


def _compact(value: Any, limit: int) -> str:
    text = _json(value)
    return text if len(text) <= limit else text[: limit - 20] + " ...(truncated)"


def case_brief(case: Case, rows: list[dict[str, Any]]) -> str:
    """The first user message: what was flagged, why, and the rows involved."""
    shown = rows[:MAX_EVIDENCE_ROWS]
    lines = [
        f"Case {case.case_id}",
        f"Anomaly type: {case.anomaly_type.value}",
        f"Raised by detector: {case.detector} (score {case.detector_score:.2f})",
        f"Amount at risk: {settings.money(case.amount_at_risk)}",
        f"Supplier key: {case.vendor_key}",
        f"Rows in this case: {len(case.row_ids)}",
        f"Why the detector flagged it: {_compact(case.metadata, MAX_METADATA_CHARS)}",
        "",
        f"Evidence rows ({len(shown)} of {len(rows)} shown):",
    ]
    lines += [_json(r) for r in shown]
    if len(rows) > len(shown):
        amounts = [float(r["amount"]) for r in rows]
        dates = sorted(str(r["txn_date"]) for r in rows)
        lines.append(
            f"... and {len(rows) - len(shown)} more rows. Across all {len(rows)}: total "
            f"{settings.money(sum(amounts))}, dates {dates[0]} to {dates[-1]}. "
            "Use query_transactions to see any of them."
        )
    lines += ["", "Investigate, then reply with the JSON note."]
    return "\n".join(lines)
