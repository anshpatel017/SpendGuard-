"""Live checks against the configured LLM endpoint.

Opt-in: skipped unless selected with ``-m llm`` (see conftest.py), and skipped
without a key, so CI and routine runs never spend the rate-limited quota:

    pytest backend -m llm

The investigation test runs one case of every anomaly type end to end; on the
Groq free tier expect several minutes, most of it waiting on rate limits.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from spendguard.agent.tools import ToolBox
from spendguard.cases import AnomalyType
from spendguard.config import LLMProvider, settings
from spendguard.db.duck import AUDIT_VIEW
from spendguard.eval.injection import InjectionResult

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        settings.llm_provider is not LLMProvider.OLLAMA and settings.llm_api_key in ("", "not-set"),
        reason="no LLM_API_KEY configured",
    ),
]


@pytest.fixture(scope="module")
def client():  # type: ignore[no-untyped-def]
    pytest.importorskip("openai")
    from spendguard.agent.llm import LLMClient

    return LLMClient()


def test_the_endpoint_answers(client) -> None:  # type: ignore[no-untyped-def]
    health = client.health()
    assert health["ok"], health
    assert health["latency_seconds"] < 30


def test_the_model_calls_a_tool_rather_than_guessing(client, injected: InjectionResult) -> None:  # type: ignore[no-untyped-def]
    """The Investigator's whole design rests on this: given tools, the model uses them."""
    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        box = ToolBox(con)
        vendor = con.execute(
            f"SELECT vendor_key FROM {AUDIT_VIEW} GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
        ).fetchone()
        assert vendor is not None

        reply = client.chat(
            [
                {
                    "role": "system",
                    "content": "You are an auditor. Use the tools; never guess a figure.",
                },
                {
                    "role": "user",
                    "content": f"How many transactions does supplier '{vendor[0]}' have?",
                },
            ],
            tools=box.schemas(),
        )
        assert reply.wants_tool, f"model answered without a tool: {reply.content[:200]}"

        call = reply.tool_calls[0]
        assert call.name in {t.name for t in box.tools()}
        result = box.run(call.name, call.arguments)
        assert "error" not in result, result
        json.dumps(result, default=str)  # results must be serializable back to the model


@pytest.mark.parametrize("kind", [t.value for t in AnomalyType])
def test_the_investigator_writes_a_cited_note_for_every_anomaly_type(
    client,
    injected: InjectionResult,
    kind: str,  # type: ignore[no-untyped-def]
) -> None:
    """Phase 6 exit criterion: a schema-valid, cited note with a full trace, per type."""
    from spendguard.agent.investigator import Investigator
    from spendguard.detectors import PRODUCTION_DETECTORS, REGISTRY

    with duckdb.connect(str(injected.out_db), read_only=True) as con:
        cases = [c for n in PRODUCTION_DETECTORS for c in REGISTRY[n]().detect(con)]
        of_kind = sorted(
            (c for c in cases if c.anomaly_type.value == kind), key=lambda c: -c.severity_prelim
        )
        if not of_kind:
            pytest.skip(f"no {kind} case in the test dataset")
        result = Investigator(client, con).investigate(of_kind[0])

    assert result.status == "completed", result.error
    assert result.note is not None and result.note.claims
    assert all(claim.row_ids for claim in result.note.claims)
    assert result.tool_calls >= 1  # it investigated rather than answering from the brief
    assert [s.step_index for s in result.trace] == list(range(len(result.trace)))
    assert result.severity_final is not None
