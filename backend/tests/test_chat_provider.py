"""Step 12 Sub-step 3A: unit tests for app/services/chat_provider.py.

Uses a fake AsyncOpenAI-shaped client (no real network/API calls) driven
via asyncio.run -- no new test dependency (pytest-asyncio/anyio plugin)
is needed since each test wraps its own async body and runs it with the
stdlib's asyncio.run().
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.services.chat_provider import (
    ChatDeltaEvent,
    ChatFinishEvent,
    ChatProviderAPIError,
    OpenAIChatProvider,
)


def run_async(coro):
    return asyncio.run(coro)


@dataclass
class FakeDelta:
    content: Optional[str] = None
    tool_calls: Optional[list] = None


@dataclass
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def model_dump(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class FakeChoice:
    delta: Optional[FakeDelta] = None
    finish_reason: Optional[str] = None


@dataclass
class FakeChunk:
    choices: list = field(default_factory=list)
    usage: Optional[FakeUsage] = None


class FakeAsyncStream:
    """Minimal async-iterator stand-in for the object AsyncOpenAI's
    chat.completions.create(..., stream=True) resolves to."""

    def __init__(self, chunks: list[FakeChunk], raise_after: Optional[int] = None):
        self._chunks = chunks
        self._raise_after = raise_after
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._raise_after is not None and self._index == self._raise_after:
            raise RuntimeError("simulated mid-stream provider failure")
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class FakeCompletions:
    def __init__(self, stream: FakeAsyncStream = None, raise_on_create: Exception = None):
        self._stream = stream
        self._raise_on_create = raise_on_create
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_on_create is not None:
            raise self._raise_on_create
        return self._stream


class FakeChat:
    def __init__(self, completions: FakeCompletions):
        self.completions = completions


class FakeAsyncOpenAIClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = FakeChat(completions)


def _make_provider(stream: FakeAsyncStream = None, raise_on_create: Exception = None) -> OpenAIChatProvider:
    client = FakeAsyncOpenAIClient(FakeCompletions(stream=stream, raise_on_create=raise_on_create))
    return OpenAIChatProvider(model="gpt-4o-mini", client=client)


def test_tool_choice_is_forwarded_to_the_underlying_api_call_when_given():
    chunks = [FakeChunk(choices=[FakeChoice(delta=FakeDelta(content=None), finish_reason="stop")])]
    provider = _make_provider(stream=FakeAsyncStream(chunks))

    async def collect():
        async for _ in provider.stream_chat(messages=[{"role": "user", "content": "hi"}], tool_choice="required"):
            pass

    run_async(collect())

    assert provider._client.chat.completions.calls[0]["tool_choice"] == "required"


def test_tool_choice_omitted_from_the_underlying_api_call_when_not_given():
    chunks = [FakeChunk(choices=[FakeChoice(delta=FakeDelta(content=None), finish_reason="stop")])]
    provider = _make_provider(stream=FakeAsyncStream(chunks))

    async def collect():
        async for _ in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            pass

    run_async(collect())

    assert "tool_choice" not in provider._client.chat.completions.calls[0]


def test_normal_streaming_yields_deltas_then_finish_with_usage():
    chunks = [
        FakeChunk(choices=[FakeChoice(delta=FakeDelta(content="Hello"))]),
        FakeChunk(choices=[FakeChoice(delta=FakeDelta(content=" world"))]),
        FakeChunk(
            choices=[FakeChoice(delta=FakeDelta(content=None), finish_reason="stop")],
            usage=FakeUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        ),
    ]
    provider = _make_provider(stream=FakeAsyncStream(chunks))

    async def collect():
        events = []
        async for event in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            events.append(event)
        return events

    events = run_async(collect())

    assert events == [
        ChatDeltaEvent(delta="Hello"),
        ChatDeltaEvent(delta=" world"),
        ChatFinishEvent(finish_reason="stop", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
    ]


def test_stream_open_failure_raises_chat_provider_api_error():
    provider = _make_provider(raise_on_create=ConnectionError("network down"))

    async def consume():
        async for _ in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(ChatProviderAPIError) as exc_info:
        run_async(consume())
    assert isinstance(exc_info.value.__cause__, ConnectionError)


def test_mid_stream_exception_raises_chat_provider_api_error_after_partial_events():
    chunks = [
        FakeChunk(choices=[FakeChoice(delta=FakeDelta(content="partial"))]),
    ]
    provider = _make_provider(stream=FakeAsyncStream(chunks, raise_after=1))

    events = []

    async def consume():
        async for event in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            events.append(event)

    with pytest.raises(ChatProviderAPIError) as exc_info:
        run_async(consume())

    assert events == [ChatDeltaEvent(delta="partial")]
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_empty_choices_chunk_is_skipped_without_error():
    chunks = [
        FakeChunk(choices=[]),  # e.g. an OpenAI usage-only trailer chunk with no choices
        FakeChunk(choices=[FakeChoice(delta=FakeDelta(content="ok"), finish_reason="stop")]),
    ]
    provider = _make_provider(stream=FakeAsyncStream(chunks))

    async def collect():
        events = []
        async for event in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            events.append(event)
        return events

    events = run_async(collect())

    assert events == [ChatDeltaEvent(delta="ok"), ChatFinishEvent(finish_reason="stop", usage=None)]
