"""The names of the ablation arms, and what each one changed.

EVALUATION section 6 asks for three ablations. Two of them need a name, because
their notes have to be stored and scored apart from the main run's:

* ``template`` - the agent is replaced by notes filled from detector output;
* ``no-verifier`` - the Investigator's first draft is released unchecked.

The third, model size, needs none: a note already records the model that wrote
it and evaluation is scored per model (D-33), so a smaller model is simply
another run, not another arm.

This module is deliberately tiny and imports nothing of SpendGuard's, so the
API can name an arm without pulling the agent layer into a web request (D-10).
"""

from __future__ import annotations

from typing import Any

TEMPLATE = "template"
NO_VERIFIER = "no-verifier"
ARMS: tuple[str, ...] = (TEMPLATE, NO_VERIFIER)


def describe(config: dict[str, Any] | None) -> str:
    """What an arm changed, read from the run's own config snapshot - never assumed.

    The snapshot is what actually ran. Labelling the arm from a table here would
    keep saying "Verifier off" long after someone ran it with the Verifier on.
    """
    config = config or {}
    model = str(config.get("model", "unknown"))
    # A model is worth naming only if it did something. The template arm's model
    # is the Verifier's judge, and with the Verifier off no model ran at all -
    # naming the client that happened to be configured would overstate the run.
    checked = bool(config.get("verifier_enabled", True)) and model != "unknown"
    if config.get("ablation") == TEMPLATE:
        written = "notes filled from detector output, no model writes them"
        return f"{written}; judged by {model}" if checked else f"{written}; no model ran at all"
    if not config.get("verifier_enabled", True):
        return f"Verifier off, the first draft is released unchecked; Investigator {model}"
    return f"model {model}"
