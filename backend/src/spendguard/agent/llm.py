"""The LLM client - one interface, any OpenAI-compatible endpoint.

Groq during development because it is free and fast; Ollama on the machine
itself for the "fully local" claim. Both speak the OpenAI chat-completions API,
so switching is a change to ``LLM_PROVIDER`` and its two companions in ``.env``,
never a change to code.

Everything above this module - tools, Investigator, Verifier - sees only
``LLMClient.chat()`` and an :class:`LLMResponse`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from spendguard.config import LLMProvider, settings


class LLMNotConfiguredError(RuntimeError):
    """No usable API key for the selected provider."""


class LLMCallError(RuntimeError):
    """The endpoint could not be reached, or refused the request."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    finish_reason: str = ""
    raw_message: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _parse_arguments(raw: str) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string and are not always valid JSON."""
    import json

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


class LLMClient:
    """Thin wrapper over the OpenAI SDK, pointed wherever configuration says."""

    RETRY_STATUSES = (408, 429, 500, 502, 503, 504)

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = provider or settings.llm_provider
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.max_retries = max_retries

        if self.provider is not LLMProvider.OLLAMA and self.api_key in ("", "not-set"):
            raise LLMNotConfiguredError(
                f"No API key for provider '{self.provider.value}'. Copy .env.example to .env "
                "and set LLM_API_KEY, or switch LLM_PROVIDER to ollama for a local model."
            )

        from openai import OpenAI

        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "ollama",
            timeout=settings.llm_timeout_seconds,
            max_retries=0,  # retried here, so backoff and logging stay in one place
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """One turn. Returns the assistant message, with any tool calls parsed out."""
        from openai import APIStatusError, OpenAIError

        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = tool_choice

        started = time.perf_counter()
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                completion = self._client.chat.completions.create(**request)
                break
            except APIStatusError as exc:
                last = exc
                if exc.status_code not in self.RETRY_STATUSES:
                    raise LLMCallError(f"{self.model} refused the request: {exc}") from exc
                time.sleep(2**attempt)
            except OpenAIError as exc:
                last = exc
                time.sleep(2**attempt)
        else:
            raise LLMCallError(
                f"{self.provider.value} unreachable after {self.max_retries} attempts: {last}"
            ) from last

        choice = completion.choices[0]
        message = choice.message
        calls = tuple(
            ToolCall(
                id=c.id,
                name=c.function.name,
                arguments=_parse_arguments(c.function.arguments),
                raw_arguments=c.function.arguments,
            )
            for c in (message.tool_calls or [])
            if c.type == "function"
        )
        usage = completion.usage
        return LLMResponse(
            content=message.content or "",
            tool_calls=calls,
            model=completion.model or self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_seconds=round(time.perf_counter() - started, 3),
            finish_reason=choice.finish_reason or "",
            raw_message=message.model_dump(),
        )

    def health(self) -> dict[str, Any]:
        """Cheapest possible round trip, for `spendguard check-llm` and the API."""
        try:
            reply = self.chat(
                [{"role": "user", "content": "Reply with exactly: ok"}], max_tokens=5, temperature=0
            )
        except (LLMCallError, LLMNotConfiguredError) as exc:
            return {
                "ok": False,
                "provider": self.provider.value,
                "model": self.model,
                "error": str(exc),
            }
        return {
            "ok": True,
            "provider": self.provider.value,
            "model": reply.model,
            "latency_seconds": reply.latency_seconds,
            "reply": reply.content.strip(),
        }
