"""The headline sentence, generated rather than typed (EVALUATION section 8).

One sentence gets quoted in the report, the slides and the viva. It is the most
copied number in the project and therefore the most likely to be wrong: typed
once from a run that has since been re-done, then carried everywhere.

So it is generated from the same files the tables come from, and every figure in
it names the file it came from. ``spendguard report headline`` rewrites it;
``check-evaluation`` keeps the document honest about the rest.

**Two corrections to the sentence as originally specified**, both about not
claiming more than was measured:

*The detection figures are not from real transactions.* The template in
EVALUATION 8 read "On N **real** transactions with M injected anomalies" - but
injection runs on the seeded synthetic dataset, and the real California data is
unlabelled and never injected into. One sentence covering both would imply the
F1 was achieved on real procurement. The two datasets are named separately.

*A figure from too few notes is withheld, not rounded.* Citation validity from
three notes is not a rate, and "100%" from three notes is the kind of number a
panel is right to attack. Below ``headline_min_notes`` it is reported as
provisional with its sample size attached, never as a bare percentage.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spendguard.config import settings
from spendguard.eval.report import SUITE, provenance

UNMEASURED = "not yet measured"


@dataclass(frozen=True)
class Figure:
    """One number in the sentence, with where it came from."""

    name: str
    value: str
    source: str  # the generated file, or why it is absent

    @property
    def measured(self) -> bool:
        return self.value != UNMEASURED


@dataclass
class Headline:
    detection: str
    agent: str
    real_data: str
    figures: list[Figure] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return all(f.measured for f in self.figures)

    def sentence(self) -> str:
        parts = [self.detection, self.agent, self.real_data]
        return " ".join(p for p in parts if p)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _spread(row: dict[str, Any], metric: str) -> str:
    value = row.get(metric) or {}
    return f"{value.get('mean', 0):.3f} ± {value.get('sd', 0):.3f}"


def build(results_dir: Path | None = None) -> Headline:
    """The sentence, from the generated results only. Nothing here is typed by hand."""
    results_dir = results_dir or settings.results_dir
    figures: list[Figure] = []

    detection = _read(results_dir / "detection.json")
    if detection is None:
        sentence = f"Detection: {UNMEASURED} - run `spendguard report detection`."
        figures.append(Figure("detection", UNMEASURED, "detection.json is absent"))
    else:
        case_rows = {
            (r["anomaly_type"], r["detector"]): r
            for r in detection["aggregate"]
            if r["granularity"] == "case"
        }
        suite = case_rows.get(("all", SUITE))
        baseline = case_rows.get(("all", "baseline"))
        runs = detection.get("runs", [])
        transactions = max((r.get("transactions", 0) for r in runs), default=0)
        planted = max((sum(r.get("ground_truth_groups", {}).values()) for r in runs), default=0)
        seeds = detection.get("seeds", [])
        if suite is None or baseline is None:
            sentence = f"Detection: {UNMEASURED} - the pooled rows are missing from detection.json."
            figures.append(Figure("detection", UNMEASURED, "no pooled `all` row"))
        else:
            f1, base = _spread(suite, "f1"), _spread(baseline, "f1")
            figures += [
                Figure("transactions", f"{transactions:,}", "detection.json"),
                Figure("planted anomalies", str(planted), "detection.json"),
                Figure("SpendGuard F1 (per case)", f1, "detection.json"),
                Figure("baseline F1 (per case)", base, "detection.json"),
            ]
            sentence = (
                f"On {transactions:,} seeded synthetic transactions carrying {planted} planted "
                f"anomalies, across {len(seeds)} seeds, SpendGuard's four detectors reach a "
                f"pooled per-case **F1 of {f1}** against a rule-based baseline at **{base}**."
            )

    agent = _read(results_dir / "agent.json")
    main = [
        r
        for r in (agent or {}).get("results", [])
        if r.get("arm") == "agent" and r.get("deterministic_valid") is not None
    ]
    if not main:
        agent_sentence = (
            f"Citation validity: {UNMEASURED} - run `spendguard investigate --matrix`, "
            "then `spendguard report agent`."
        )
        figures.append(Figure("citation validity", UNMEASURED, "no agent notes yet"))
    else:
        notes = sum(int(r.get("notes", 0)) for r in main)
        checked = sum(int(r.get("citations_checked", 0)) for r in main)
        weighted = sum(
            float(r["deterministic_valid"]) * int(r.get("citations_checked", 0)) for r in main
        )
        validity = weighted / checked if checked else 0.0
        enough = notes >= settings.headline_min_notes
        figures.append(
            Figure(
                "citation validity (rule-checked)",
                f"{validity:.1%} over {notes} note(s)",
                "agent.json" + ("" if enough else " - provisional, sample still filling"),
            )
        )
        if enough:
            agent_sentence = (
                f"Every claim in a released note is checked against the data: **{validity:.1%}** "
                f"of cited values matched exactly, by rule and with no model involved, over "
                f"{notes} notes."
            )
        else:
            agent_sentence = (
                f"Citation validity is **provisional**: {validity:.1%} over only {notes} note(s), "
                f"below the {settings.headline_min_notes} this project will quote a rate from. "
                "The sample fills at roughly ten investigations a day."
            )

    real = _read(results_dir / "real-data.json")
    if real is None:
        real_sentence = (
            f"Value implicated in real spend: {UNMEASURED} - run `spendguard review report`."
        )
        figures.append(Figure("value implicated", UNMEASURED, "real-data.json is absent"))
    else:
        dataset = real.get("dataset", {})
        value = dataset.get("Total value", UNMEASURED)
        rows = dataset.get("Transactions", UNMEASURED)
        figures.append(Figure("real transactions audited", str(rows), "real-data.json"))
        real_sentence = (
            f"Separately, on {rows} unlabelled real purchase records worth {value}, the same "
            "detectors ran over every row; nothing there is labelled, so what those flags are "
            "worth is estimated from a reviewed sample and reported with an interval, never as "
            "a bare precision."
        )

    return Headline(
        detection=sentence,
        agent=agent_sentence,
        real_data=real_sentence,
        figures=figures,
        manifest=provenance(()),
    )


def render_markdown(headline: Headline) -> str:
    m = headline.manifest
    dirty = " **(uncommitted changes)**" if m.get("dirty") else ""
    lines = [
        "# Headline result",
        "",
        f"Generated {m.get('generated_at')} from commit `{m.get('commit')}`{dirty}. "
        "Regenerate with `spendguard report headline`. **Do not edit this sentence by hand** - "
        "it exists so the most-quoted numbers in the project cannot drift from the runs that "
        "produced them.",
        "",
        "---",
        "",
        f"> {headline.sentence()}",
        "",
        "---",
        "",
        "## Where each figure comes from",
        "",
        "| Figure | Value | Source |",
        "|---|---|---|",
    ]
    lines += [f"| {f.name} | {f.value} | {f.source} |" for f in headline.figures]
    lines += [
        "",
        "The detection figures are from the **seeded synthetic** dataset, which is the only one "
        "with an answer key; the real-data figures are from **California purchase orders**, which "
        "have none. The sentence keeps them apart on purpose: one sentence covering both would "
        "read as though the F1 had been achieved on real procurement, and it was not.",
        "",
    ]
    if not headline.complete:
        missing = [f.name for f in headline.figures if not f.measured]
        lines += [
            f"**Incomplete: {', '.join(missing)}.** The sentence says so rather than leaving a "
            "gap for someone to fill in from memory.",
            "",
        ]
    return "\n".join(lines)


def write_headline(headline: Headline, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "headline.md"
    js = out_dir / "headline.json"
    md.write_text(render_markdown(headline), encoding="utf-8")
    js.write_text(
        json.dumps(
            {
                "manifest": headline.manifest,
                "sentence": headline.sentence(),
                "complete": headline.complete,
                "figures": [asdict(f) for f in headline.figures],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return md, js
