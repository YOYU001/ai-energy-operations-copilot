"""Step 12 Sub-step 3A Slice 4: tests for app.main.generate() and
_finalize_with_fallback(), driven directly (not through TestClient, which
buffers streaming responses and cannot simulate a mid-stream disconnect or
a stalled/timing-out provider). See docs/step12_slice4_plan.md.

No real DB, no real OpenAI calls: get_connection is monkeypatched to a
fake context manager and finalize_assistant_message is monkeypatched to a
recorder/side-effect stub for every test in this file.
"""

import asyncio

import pytest

import app.main as main_module
from app.services.chat_provider import ChatDeltaEvent, ChatFinishEvent, ChatProviderAPIError


def run_async(coro):
    return asyncio.run(coro)


class _FakeConnCtx:
    """Stand-in for `with get_connection() as conn:` -- no real engine
    involved. Each call to get_connection() in the fake below returns a
    fresh instance, matching real behavior (a new connection per `with`
    block)."""

    def __init__(self):
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.committed = True


class _FinalizeRecorder:
    """Records every call's arguments; side_effects (if given) is a list
    popped one per call -- an Exception instance is raised, anything else
    is returned as the rowcount."""

    def __init__(self, side_effects=None):
        self.calls = []
        self.side_effects = list(side_effects) if side_effects is not None else None

    def __call__(self, conn, message_id, content, status, error_message, finish_reason, usage):
        self.calls.append(
            {
                "message_id": message_id,
                "content": content,
                "status": status,
                "error_message": error_message,
                "finish_reason": finish_reason,
                "usage": usage,
            }
        )
        if self.side_effects is not None:
            effect = self.side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return 1


class FakeRequest:
    """Fake starlette Request -- only is_disconnected() is used by
    generate(). disconnect_after=N means the Nth call and every call after
    it returns True; None means never disconnected."""

    def __init__(self, disconnect_after=None):
        self.disconnect_after = disconnect_after
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        if self.disconnect_after is None:
            return False
        return self.calls > self.disconnect_after


class FakeCompletingProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def stream_chat(self, messages, tools=None, tool_choice=None):
        async def _gen():
            yield ChatDeltaEvent(delta="Hello")
            yield ChatDeltaEvent(delta=" world")
            yield ChatFinishEvent(finish_reason="stop", usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})

        return _gen()


class FakeAPIErrorProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def stream_chat(self, messages, tools=None, tool_choice=None):
        async def _gen():
            yield ChatDeltaEvent(delta="partial")
            raise ChatProviderAPIError("simulated provider failure")
            yield  # pragma: no cover -- unreachable, keeps this a generator

        return _gen()


class FakeStallingProvider:
    """Never yields within the (monkeypatched, shortened) idle timeout."""

    provider_name = "fake"
    model_name = "fake-model"

    def stream_chat(self, messages, tools=None, tool_choice=None):
        async def _gen():
            await asyncio.sleep(10)
            yield ChatDeltaEvent(delta="never reached")  # pragma: no cover

        return _gen()


class FakeSlowButNotStallingProvider:
    """Yields events fast enough to never trip the idle timeout, but the
    cumulative wall-clock time trips the (monkeypatched, shortened)
    overall generation timeout."""

    provider_name = "fake"
    model_name = "fake-model"

    def stream_chat(self, messages, tools=None, tool_choice=None):
        async def _gen():
            for i in range(5):
                await asyncio.sleep(0.03)
                yield ChatDeltaEvent(delta=f"chunk-{i}")

        return _gen()


def _use_fake_connection(monkeypatch):
    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx())


def _collect_frames(gen):
    frames = []

    async def _run():
        async for frame in gen:
            frames.append(frame)

    run_async(_run())
    return frames


# ---------------------------------------------------------------------------
# 1. Normal streaming completion
# ---------------------------------------------------------------------------


def test_generate_normal_completion_streams_tokens_and_finalizes_completed(monkeypatch):
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    frames = _collect_frames(
        main_module.generate(42, FakeCompletingProvider(), [{"role": "user", "content": "hi"}], FakeRequest(), is_diagnostic=False, build_embedding_provider=None)
    )

    joined = "".join(frames)
    assert "event: message_started" in joined
    assert "event: thinking" in joined
    # Phase 2 is buffered (TODO.md bug 3, 2026-08-26): individual deltas are
    # no longer streamed live -- the full, verified answer is sent as one
    # token frame, so "Hello" + " world" arrive combined, not separately.
    assert 'data: {"delta": "Hello world"}' in joined
    assert "event: message_completed" in joined
    assert "event: message_failed" not in joined

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["message_id"] == 42
    assert call["content"] == "Hello world"
    assert call["status"] == "completed"
    assert call["error_message"] is None
    assert call["finish_reason"] == "stop"
    assert call["usage"] == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


# ---------------------------------------------------------------------------
# 2. Provider error
# ---------------------------------------------------------------------------


def test_generate_provider_api_error_finalizes_failed_provider_error(monkeypatch):
    """This error happens during Phase 1 (tool orchestration round 1,
    which every message enters first). Phase 1 content is buffered, never
    streamed -- so the "partial" delta that arrived just before the error
    must NOT reach the client and must NOT be persisted (Internal
    Knowledge Only fix: nothing not-yet-vetted is ever shown or saved)."""
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    frames = _collect_frames(
        main_module.generate(42, FakeAPIErrorProvider(), [{"role": "user", "content": "hi"}], FakeRequest(), is_diagnostic=False, build_embedding_provider=None)
    )

    joined = "".join(frames)
    assert 'data: {"delta": "partial"}' not in joined
    assert "event: tool_call" not in joined
    assert "event: message_failed" in joined
    assert '"error": "assistant response failed, please try again"' in joined
    assert "event: message_completed" not in joined

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["content"] == ""
    assert call["status"] == "failed"
    assert call["error_message"] == "provider_error"


# ---------------------------------------------------------------------------
# 3. Idle timeout
# ---------------------------------------------------------------------------


def test_generate_idle_timeout_finalizes_failed_provider_timeout(monkeypatch):
    _use_fake_connection(monkeypatch)
    monkeypatch.setattr(main_module, "IDLE_TOKEN_TIMEOUT_SECONDS", 0.05)
    recorder = _FinalizeRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    frames = _collect_frames(
        main_module.generate(42, FakeStallingProvider(), [{"role": "user", "content": "hi"}], FakeRequest(), is_diagnostic=False, build_embedding_provider=None)
    )

    joined = "".join(frames)
    assert "event: message_failed" in joined

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["status"] == "failed"
    assert recorder.calls[0]["error_message"] == "provider_timeout"


# ---------------------------------------------------------------------------
# 4. Overall generation timeout
# ---------------------------------------------------------------------------


def test_generate_overall_timeout_finalizes_failed_provider_timeout(monkeypatch):
    """This timeout happens during Phase 1 (tool orchestration round 1).
    Phase 1 content is buffered, never streamed -- so none of the chunks
    that arrived before the timeout tripped may reach the client or get
    persisted (same Internal Knowledge Only fix as the provider-error
    case above)."""
    _use_fake_connection(monkeypatch)
    monkeypatch.setattr(main_module, "OVERALL_GENERATION_TIMEOUT_SECONDS", 0.05)
    recorder = _FinalizeRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    frames = _collect_frames(
        main_module.generate(42, FakeSlowButNotStallingProvider(), [{"role": "user", "content": "hi"}], FakeRequest(), is_diagnostic=False, build_embedding_provider=None)
    )

    joined = "".join(frames)
    assert "event: message_failed" in joined
    assert "chunk-0" not in joined

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["status"] == "failed"
    assert recorder.calls[0]["error_message"] == "provider_timeout"
    assert recorder.calls[0]["content"] == ""


# ---------------------------------------------------------------------------
# 5. Client disconnect
# ---------------------------------------------------------------------------


def test_generate_disconnect_finalizes_aborted_with_no_leaked_content_and_suppresses_terminal_frame(monkeypatch):
    """Disconnect happens during Phase 1 (tool orchestration round 1). The
    "Hello" delta that arrived just before the disconnect check tripped
    was only ever buffered, never streamed -- so it must not appear in the
    SSE output and must not be persisted (same Internal Knowledge Only fix
    as the provider-error/timeout cases above)."""
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    # 1st is_disconnected() call (loop start, before 1st event) -> False, lets "Hello" be buffered.
    # 2nd call (loop start, before 2nd event) -> True, breaks the loop.
    frames = _collect_frames(
        main_module.generate(42, FakeCompletingProvider(), [{"role": "user", "content": "hi"}], FakeRequest(disconnect_after=1), is_diagnostic=False, build_embedding_provider=None)
    )

    joined = "".join(frames)
    assert 'data: {"delta": "Hello"}' not in joined
    assert 'data: {"delta": " world"}' not in joined
    # terminal SSE frame is best-effort and suppressed once disconnected is observed
    assert "event: message_completed" not in joined
    assert "event: message_failed" not in joined

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["content"] == ""
    assert call["status"] == "aborted"
    assert call["error_message"] is None


# ---------------------------------------------------------------------------
# 6 & 7. _finalize_with_fallback
# ---------------------------------------------------------------------------


def test_finalize_with_fallback_first_attempt_fails_second_succeeds(monkeypatch):
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder(side_effects=[RuntimeError("transient db blip"), 1])
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    finalized = main_module._finalize_with_fallback(42, "content", "completed", None, "stop", None)

    assert finalized is True
    assert len(recorder.calls) == 2


def test_finalize_with_fallback_both_attempts_fail(monkeypatch, caplog):
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder(side_effects=[RuntimeError("blip 1"), RuntimeError("blip 2")])
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    with caplog.at_level("ERROR"):
        finalized = main_module._finalize_with_fallback(42, "content", "completed", None, "stop", None)

    assert finalized is False
    assert len(recorder.calls) == 2


def test_generate_does_not_raise_when_both_finalize_attempts_fail(monkeypatch, caplog):
    _use_fake_connection(monkeypatch)
    recorder = _FinalizeRecorder(side_effects=[RuntimeError("blip 1"), RuntimeError("blip 2")])
    monkeypatch.setattr(main_module, "finalize_assistant_message", recorder)

    with caplog.at_level("ERROR"):
        # must not raise out of the generator despite both finalize attempts failing
        frames = _collect_frames(
            main_module.generate(42, FakeCompletingProvider(), [{"role": "user", "content": "hi"}], FakeRequest(), is_diagnostic=False, build_embedding_provider=None)
        )

    assert len(recorder.calls) == 2
    assert any("left in a non-terminal DB state" in r.message for r in caplog.records)
    # best-effort terminal frame is still attempted even though persistence failed
    assert any("event: message_completed" in f for f in frames)
