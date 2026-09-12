"""Live checks against the configured LLM endpoint.

Skipped unless a key is configured, so CI and anyone without one still get a
green suite. Run them deliberately:

    pytest backend -m llm
"""

from __future__ import annotations

import json

import duckdb
import pytest

from spendguard.agent.tools import ToolBox
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
