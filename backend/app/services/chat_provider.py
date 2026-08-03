"""Step 12 Sub-step 3A: ChatProvider abstraction.

Mirrors the EmbeddingProvider pattern (app/services/embedding_provider.py):
callers depend only on the ChatProvider Protocol, OpenAIChatProvider is the
only concrete implementation, and a factory seam (added later in main.py,
matching _build_embedding_provider) lets tests inject a fake provider
instead of calling OpenAI.

Async, not sync-in-a-thread (see docs/step12_substep3a_plan.md section 1):
a chat completion is consumed from an async FastAPI route under a
streaming response, where cancellation on client disconnect and precise
per-token timeouts matter -- both are native to an async generator and
would require extra cross-thread signaling to approximate with a sync
client run in a worker thread.

This module implements no DB access, no FastAPI route, and no SSE framing
-- it is deliberately usable and testable standalone. Step 12 Sub-step 3B
adds ChatToolCallEvent and the delta.tool_calls parsing branch below (a
real gap found in the original 3A implementation: tools was already
forwarded to the API call, but nothing read tool-call deltas back out of
the response, so any tool call the model made was silently dropped).
Assembling complete tool calls from fragments and deciding what to do with
them is still entirely the caller's (app/main.py's) responsibility -- this
module only yields raw per-fragment events, never SSE frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol, Union


@dataclass(frozen=True)
class ChatDeltaEvent:
    delta: str


@dataclass(frozen=True)
class ChatFinishEvent:
    finish_reason: str  # "stop" | "length" | "content_filter" | "tool_calls"
    usage: Optional[dict]  # {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int} or None


@dataclass(frozen=True)
class ChatToolCallEvent:
    """One fragment of one tool call. OpenAI streams tool-call arguments as
    partial JSON string fragments grouped by `index` (position among the
    tool calls in this round) -- `tool_call_id` and `name` are only
    non-None on the FIRST fragment for a given index; every later fragment
    for that same call carries id=None/name=None and only a further
    arguments_delta piece. Callers must accumulate by `index` (not by
    tool_call_id, which is only known once) until the round's
    ChatFinishEvent(finish_reason='tool_calls') signals the round is
    complete, then use whichever fragment's tool_call_id was non-None as
    the call's real id."""

    index: int
    tool_call_id: Optional[str]
    name: Optional[str]
    arguments_delta: str


ChatStreamEvent = Union[ChatDeltaEvent, ChatFinishEvent, ChatToolCallEvent]


class ChatProviderError(RuntimeError):
    """Base class for provider-side failures raised by this module. Callers
    map subclasses to the sanitized error_message codes in
    docs/step12_substep3_plan.md section 10 (never the raw exception
    detail)."""


class ChatProviderTimeout(ChatProviderError):
    """Raised by the caller's own timeout enforcement (this module does not
    enforce timeouts itself -- see docs/step12_substep3a_plan.md section 2,
    which wraps stream_chat's iteration in asyncio.wait_for at the call
    site). Kept here so callers have one shared exception type to raise."""


class ChatProviderAPIError(ChatProviderError):
    """Raised when the provider API itself fails (rate limit, auth,
    malformed response, connection error, mid-stream interruption). Wraps
    the underlying SDK exception as __cause__ for server-log-only detail --
    never surfaced directly to the DB or SSE layer."""


class ChatProvider(Protocol):
    provider_name: str
    model_name: str

    def stream_chat(
        self, messages: list[dict], tools: Optional[list[dict]] = None
    ) -> AsyncIterator[ChatStreamEvent]: ...


class OpenAIChatProvider:
    """Wraps the OpenAI chat completions API in streaming mode via
    AsyncOpenAI. Requires OPENAI_API_KEY in the environment (loaded via
    python-dotenv by the caller, exactly like backend/app/db.py does for
    DATABASE_URL) -- never pass a key literal."""

    provider_name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", client=None):
        self.model_name = model
        if client is not None:
            self._client = client  # test hook: inject a fake AsyncOpenAI-shaped client
        else:
            from openai import AsyncOpenAI  # imported lazily so tests can mock without requiring the package at import time

            self._client = AsyncOpenAI()

    async def stream_chat(
        self, messages: list[dict], tools: Optional[list[dict]] = None
    ) -> AsyncIterator[ChatStreamEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model_name, messages=messages, tools=tools, stream=True,
            )
        except Exception as exc:  # noqa: BLE001 -- intentionally broad, matches EmbeddingProvider's fail-closed convention
            raise ChatProviderAPIError("failed to open chat stream") from exc

        try:
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                if choice.delta is not None and choice.delta.content:
                    yield ChatDeltaEvent(delta=choice.delta.content)
                if choice.delta is not None and choice.delta.tool_calls:
                    for tc in choice.delta.tool_calls:
                        yield ChatToolCallEvent(
                            index=tc.index,
                            tool_call_id=tc.id,
                            name=tc.function.name if tc.function is not None else None,
                            arguments_delta=(tc.function.arguments or "") if tc.function is not None else "",
                        )
                if choice.finish_reason is not None:
                    usage = getattr(chunk, "usage", None)
                    yield ChatFinishEvent(
                        finish_reason=choice.finish_reason,
                        usage=usage.model_dump() if usage is not None else None,
                    )
        except Exception as exc:  # noqa: BLE001
            raise ChatProviderAPIError("chat stream interrupted") from exc
