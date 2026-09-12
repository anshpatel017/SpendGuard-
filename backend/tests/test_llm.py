"""The LLM client: provider switching, retries, and tool-call parsing.

No network. The OpenAI SDK is replaced with a stub, so these run in CI and
prove the wrapper's own behaviour rather than the endpoint's.
"""

from __future__ import annotations

from typing import Any

import pytest

from spendguard.agent.llm import (
    LLMCallError,
    LLMClient,
    LLMNotConfiguredError,
    _parse_arguments,
)
from spendguard.config import LLMProvider


def _response(status: int) -> Any:
    """Minimal stand-in for an httpx response: the SDK reads .request off it."""
    return type("R", (), {"status_code": status, "headers": {}, "request": None})()


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name, self.arguments = name, arguments


class _ToolCall:
    def __init__(self, name: str, arguments: str, call_id: str = "call_1") -> None:
        self.id, self.type, self.function = call_id, "function", _Function(name, arguments)


class _Message:
    def __init__(self, content: str = "", tool_calls: list[_ToolCall] | None = None) -> None:
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self) -> dict[str, Any]:
        return {"content": self.content}


class _Completion:
    def __init__(self, message: _Message, model: str = "test-model") -> None:
        self.choices = [type("C", (), {"message": message, "finish_reason": "stop"})()]
        self.model = model
        self.usage = type("U", (), {"prompt_tokens": 11, "completion_tokens": 7})()


class StubOpenAI:
    """Records requests and replays scripted responses or errors."""

    def __init__(self, responses: list[Any], **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        outer = self

        class _Completions:
            def create(self, **request: Any) -> Any:
                outer.requests.append(request)
                item = outer._responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Builds a client whose SDK is a stub; the test supplies the responses."""

    def build(responses: list[Any], **overrides: Any) -> tuple[LLMClient, StubOpenAI]:
        stub_holder: dict[str, StubOpenAI] = {}

        def factory(**kwargs: Any) -> StubOpenAI:
            stub_holder["stub"] = StubOpenAI(responses, **kwargs)
            return stub_holder["stub"]

        monkeypatch.setattr("openai.OpenAI", factory)
        settings_overrides = {"api_key": "gsk_test", **overrides}
        return LLMClient(**settings_overrides), stub_holder["stub"]

    return build


def test_a_plain_reply_is_parsed(client: Any) -> None:
    llm, _ = client([_Completion(_Message("Two rows match."))])
    reply = llm.chat([{"role": "user", "content": "hello"}])
    assert reply.content == "Two rows match."
    assert reply.wants_tool is False
    assert (reply.prompt_tokens, reply.completion_tokens, reply.total_tokens) == (11, 7, 18)
    assert reply.latency_seconds >= 0


def test_tool_calls_are_parsed_into_arguments(client: Any) -> None:
    call = _ToolCall("vendor_profile", '{"vendor_key": "sharma"}')
    llm, _ = client([_Completion(_Message(tool_calls=[call]))])
    reply = llm.chat([{"role": "user", "content": "look it up"}], tools=[{"type": "function"}])
    assert reply.wants_tool
    assert reply.tool_calls[0].name == "vendor_profile"
    assert reply.tool_calls[0].arguments == {"vendor_key": "sharma"}


def test_malformed_tool_arguments_do_not_crash_the_loop() -> None:
    assert _parse_arguments("{not json") == {}
    assert _parse_arguments("") == {}
    assert _parse_arguments('"bare string"') == {"value": "bare string"}


def test_tools_are_only_sent_when_provided(client: Any) -> None:
    llm, stub = client([_Completion(_Message("ok")), _Completion(_Message("ok"))])
    llm.chat([{"role": "user", "content": "x"}])
    assert "tools" not in stub.requests[0]
    llm.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}])
    assert stub.requests[1]["tools"]


def test_a_rate_limit_is_retried(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    monkeypatch.setattr("time.sleep", lambda _: None)
    error = openai.APIStatusError("rate limited", response=_response(429), body=None)
    llm, stub = client([error, _Completion(_Message("recovered"))])
    assert llm.chat([{"role": "user", "content": "x"}]).content == "recovered"
    assert len(stub.requests) == 2


def test_a_refused_request_is_not_retried(client: Any) -> None:
    import openai

    error = openai.APIStatusError("no such model", response=_response(404), body=None)
    llm, stub = client([error])
    with pytest.raises(LLMCallError, match="refused"):
        llm.chat([{"role": "user", "content": "x"}])
    assert len(stub.requests) == 1


def test_giving_up_after_repeated_failures(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    monkeypatch.setattr("time.sleep", lambda _: None)
    errors = [openai.APIConnectionError(request=None) for _ in range(3)]  # type: ignore[arg-type]
    llm, _ = client(errors, max_retries=3)
    with pytest.raises(LLMCallError, match="unreachable"):
        llm.chat([{"role": "user", "content": "x"}])


def test_a_missing_key_fails_with_an_instruction_not_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: None)
    with pytest.raises(LLMNotConfiguredError, match="LLM_API_KEY"):
        LLMClient(provider=LLMProvider.GROQ, api_key="not-set")


def test_ollama_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The local provider is the whole point of the fully-local claim."""
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("openai.OpenAI", factory)
    llm = LLMClient(
        provider=LLMProvider.OLLAMA,
        base_url="http://localhost:11434/v1",
        model="qwen2.5:3b-instruct-q4_K_M",
        api_key="",
    )
    assert llm.provider is LLMProvider.OLLAMA
    assert captured["base_url"] == "http://localhost:11434/v1"


def test_switching_provider_changes_only_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq and Ollama differ by three settings, never by code."""
    seen: list[str] = []
    monkeypatch.setattr("openai.OpenAI", lambda **kw: seen.append(kw["base_url"]) or object())
    LLMClient(provider=LLMProvider.GROQ, base_url="https://api.groq.com/openai/v1", api_key="gsk_x")
    LLMClient(provider=LLMProvider.OLLAMA, base_url="http://localhost:11434/v1", api_key="")
    assert seen == ["https://api.groq.com/openai/v1", "http://localhost:11434/v1"]


def test_health_reports_failure_without_raising(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openai

    monkeypatch.setattr("time.sleep", lambda _: None)
    llm, _ = client([openai.APIConnectionError(request=None) for _ in range(3)])  # type: ignore[arg-type]
    health = llm.health()
    assert health["ok"] is False and "error" in health


def test_health_reports_success(client: Any) -> None:
    llm, _ = client([_Completion(_Message("ok"))])
    health = llm.health()
    assert health["ok"] is True and health["reply"] == "ok"
