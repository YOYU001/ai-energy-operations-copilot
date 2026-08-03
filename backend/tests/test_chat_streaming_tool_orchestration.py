"""Step 12 Sub-step 3B: tests for app.main.generate()'s two-phase design
(Phase 1: tool orchestration rounds, tools enabled, content always
buffered and discarded; Phase 2: final synthesis, tools disabled, the only
place provider content is ever streamed live). This split exists
specifically to close an Internal Knowledge Only gap a first draft had:
orchestration-round text must never reach the client before it's known
whether that round will end up discarded by a tool call, the capability
guard, or the round/call cap -- otherwise the client could see model text
the DB never persists, including text with no internal evidence behind it.

No real DB, no real OpenAI calls: get_connection is monkeypatched (both
the module-level one used by _finalize_with_fallback and the per-tool-call
one used inside generate()'s tool execution), and
finalize_assistant_message/record_tool_activity are monkeypatched to
recorder stubs.
"""

import asyncio
import json

import pytest

import app.main as main_module
from app.services.chat_provider import ChatDeltaEvent, ChatFinishEvent, ChatToolCallEvent


def run_async(coro):
    return asyncio.run(coro)


class _FakeConnCtx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        pass


class _FinalizeRecorder:
    def __init__(self):
        self.calls = []

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
        return 1


class _ToolActivityRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, conn, message_id, tool_calls, citations):
        self.calls.append({"message_id": message_id, "tool_calls": tool_calls, "citations": citations})
        return 1


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


class _ScriptedProvider:
    """Replays one list of ChatStreamEvent lists, one inner list per call
    to stream_chat (i.e. one orchestration round, or the final synthesis
    call). Records the `tools` kwarg of every call so tests can assert
    Phase 2 actually disables tools."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, rounds: list[list]):
        self._rounds = list(rounds)
        self.calls = 0
        self.tools_per_call: list = []

    def stream_chat(self, messages, tools=None):
        events = self._rounds[self.calls]
        self.calls += 1
        self.tools_per_call.append(tools)

        async def _gen():
            for event in events:
                yield event

        return _gen()


def _tool_call_events(tool_call_id: str, name: str, arguments: dict) -> list:
    args_json = json.dumps(arguments)
    return [
        ChatToolCallEvent(index=0, tool_call_id=tool_call_id, name=name, arguments_delta=""),
        ChatToolCallEvent(index=0, tool_call_id=None, name=None, arguments_delta=args_json),
        ChatFinishEvent(finish_reason="tool_calls", usage=None),
    ]


def _stop_round(content: str) -> list:
    """A round that ends WITHOUT a tool call (finish_reason='stop')."""
    return [ChatDeltaEvent(delta=content), ChatFinishEvent(finish_reason="stop", usage=None)]


_SEVEN_PART_ANSWER = (
    "## Confirmed facts / Finding\nhot battery\n\n"
    "## Evidence\ndataset 12\n\n"
    "## Possible causes\nhypothesis\n\n"
    "## General engineering background\nn/a\n\n"
    "## Suggested actions / Next checks\ncheck cooling\n\n"
    "## Confidence\nmedium\n\n"
    "## Citations\n[internal] dataset 12"
)


def _setup(monkeypatch):
    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx())
    finalize_recorder = _FinalizeRecorder()
    tool_activity_recorder = _ToolActivityRecorder()
    monkeypatch.setattr(main_module, "finalize_assistant_message", finalize_recorder)
    monkeypatch.setattr(main_module, "record_tool_activity", tool_activity_recorder)
    return finalize_recorder, tool_activity_recorder


def _collect_frames(gen):
    frames = []

    async def _run():
        async for frame in gen:
            frames.append(frame)

    run_async(_run())
    return frames


def _joined_token_deltas(frames: list[str]) -> str:
    """Reconstructs the exact text the client would render by concatenating
    every `token` SSE frame's `delta` field, in order -- used to assert SSE
    output matches the persisted DB content byte-for-byte."""
    deltas = []
    for frame in frames:
        if frame.startswith("event: token\n"):
            data_line = frame.split("\n", 2)[1]
            payload = json.loads(data_line[len("data: "):])
            deltas.append(payload["delta"])
    return "".join(deltas)


# ---------------------------------------------------------------------------
# 1. One tool-call round, then an orchestration round that stops (discarded),
#    then Phase 2 synthesis (the only round whose text is ever shown/persisted)
# ---------------------------------------------------------------------------


def test_one_tool_call_round_then_synthesis_answer(monkeypatch):
    finalize_recorder, tool_activity_recorder = _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        assert name == "get_dataset_summary"
        assert args == {"dataset_id": 12}
        return {"dataset_id": 12, "summary": {"battery_temperature": {"max": 42}}}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),  # round 1: tool call
            _stop_round("DISCARDED ORCHESTRATION TEXT -- must never appear"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis: the real, shown/persisted answer
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: tool_call" in joined
    assert '"tool_name": "get_dataset_summary"' in joined
    assert "event: tool_result" in joined
    assert "event: message_completed" in joined

    # requirement 2: discarded orchestration-round text never reaches SSE
    assert "DISCARDED ORCHESTRATION TEXT" not in joined

    assert provider.calls == 3
    assert provider.tools_per_call[0] is main_module.TOOL_SCHEMAS
    assert provider.tools_per_call[1] is main_module.TOOL_SCHEMAS
    # requirement 5: the final synthesis call disables tools
    assert provider.tools_per_call[2] is None

    assert len(finalize_recorder.calls) == 1
    call = finalize_recorder.calls[0]
    assert call["status"] == "completed"
    assert call["content"] == _SEVEN_PART_ANSWER
    assert "DISCARDED ORCHESTRATION TEXT" not in call["content"]

    # requirement 4: SSE token stream concatenation == exact DB content
    assert _joined_token_deltas(frames) == _SEVEN_PART_ANSWER

    assert len(tool_activity_recorder.calls) == 1
    tool_calls = tool_activity_recorder.calls[0]["tool_calls"]
    assert tool_calls[0]["tool_name"] == "get_dataset_summary"
    assert tool_calls[0]["error"] is False


def test_text_alongside_a_tool_call_in_the_same_round_is_never_sent_or_persisted(monkeypatch):
    """requirement 2, explicit: a round that emits BOTH content deltas and
    a tool call (models sometimes emit a short preamble before calling a
    tool) must never let that preamble reach the client or the DB."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"ok": True})

    round_1 = [
        ChatDeltaEvent(delta="Let me check the dataset for you -- "),
        ChatToolCallEvent(index=0, tool_call_id="call_1", name="get_dataset_summary", arguments_delta=""),
        ChatToolCallEvent(index=0, tool_call_id=None, name=None, arguments_delta=json.dumps({"dataset_id": 1})),
        ChatFinishEvent(finish_reason="tool_calls", usage=None),
    ]
    provider = _ScriptedProvider(
        rounds=[
            round_1,
            _stop_round("ok"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "Let me check the dataset for you" not in joined
    assert finalize_recorder.calls[0]["content"] == _SEVEN_PART_ANSWER
    assert "Let me check the dataset for you" not in finalize_recorder.calls[0]["content"]


# ---------------------------------------------------------------------------
# 2. Max-rounds / max-calls cap -- buffered text before the cap must never
#    be sent (requirement 3)
# ---------------------------------------------------------------------------


def test_max_rounds_cap_discards_buffered_text_and_produces_deterministic_capped_answer(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"ok": True})

    # 3 rounds (MAX_TOOL_ROUNDS); round 3 also carries stray content before
    # its tool call -- that text must never surface. Capped without ever
    # calling stream_chat a 4th time (no Phase 2 synthesis for this outcome).
    round_3 = [
        ChatDeltaEvent(delta="STRAY TEXT IN CAPPED ROUND -- must never appear"),
        ChatToolCallEvent(index=0, tool_call_id="call_3", name="get_dataset_summary", arguments_delta=""),
        ChatToolCallEvent(index=0, tool_call_id=None, name=None, arguments_delta=json.dumps({"dataset_id": 3})),
        ChatFinishEvent(finish_reason="tool_calls", usage=None),
    ]
    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 1}),
            _tool_call_events("call_2", "get_dataset_summary", {"dataset_id": 2}),
            round_3,
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "STRAY TEXT IN CAPPED ROUND" not in joined
    assert "event: message_completed" in joined
    assert provider.calls == 3  # never made a 4th (synthesis) call

    assert len(finalize_recorder.calls) == 1
    call = finalize_recorder.calls[0]
    assert call["finish_reason"] == "tool_cap_exceeded"
    assert "## Confirmed facts / Finding" in call["content"]
    assert "STRAY TEXT IN CAPPED ROUND" not in call["content"]
    assert _joined_token_deltas(frames) == call["content"]


def test_max_tool_calls_cap_stops_after_five_calls_in_one_round(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"ok": True})

    # A single round where the model requests 5 tool calls at once (index 0..4)
    # must trip the total-call cap and never start a second round.
    events = []
    for i in range(5):
        args_json = json.dumps({"dataset_id": i})
        events.append(ChatToolCallEvent(index=i, tool_call_id=f"call_{i}", name="get_dataset_summary", arguments_delta=""))
        events.append(ChatToolCallEvent(index=i, tool_call_id=None, name=None, arguments_delta=args_json))
    events.append(ChatFinishEvent(finish_reason="tool_calls", usage=None))

    provider = _ScriptedProvider(rounds=[events])

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert provider.calls == 1
    assert len(finalize_recorder.calls) == 1
    assert finalize_recorder.calls[0]["finish_reason"] == "tool_cap_exceeded"
    assert _joined_token_deltas(frames) == finalize_recorder.calls[0]["content"]


# ---------------------------------------------------------------------------
# 3. Unknown tool name
# ---------------------------------------------------------------------------


def test_unknown_tool_name_reported_back_not_silently_dropped(monkeypatch):
    finalize_recorder, tool_activity_recorder = _setup(monkeypatch)

    from app.services.tool_registry import UnknownToolError

    def fake_execute_tool(conn, embedding_provider, name, args):
        raise UnknownToolError(name)

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "delete_everything", {}),
            _stop_round("discarded"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER.replace("medium", "low")),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: tool_result" in joined
    assert "unknown tool" in joined

    assert tool_activity_recorder.calls[0]["tool_calls"][0]["error"] is True
    # an unknown-tool response does not count as satisfying the capability
    # guard as a *successful* tool call, but it did produce a (failed)
    # tool_call_log entry, so the insufficient-data override does not fire
    assert finalize_recorder.calls[0]["content"] != main_module.INSUFFICIENT_DATA_ANSWER


# ---------------------------------------------------------------------------
# 4. Capability guard: diagnostic message, zero tool calls
# ---------------------------------------------------------------------------


def test_capability_guard_rejects_diagnostic_answer_with_no_tool_calls_and_never_sends_raw_model_text(monkeypatch):
    finalize_recorder, tool_activity_recorder = _setup(monkeypatch)

    provider = _ScriptedProvider(
        rounds=[
            _stop_round("I think it's probably a wiring issue based on general knowledge."),
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "為什麼電池異常？"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: message_completed" in joined

    # requirement 1: the model's raw (ungrounded) text is never sent to the client
    assert "wiring issue" not in joined
    assert provider.calls == 1  # no Phase 2 synthesis call for this outcome

    assert len(finalize_recorder.calls) == 1
    call = finalize_recorder.calls[0]
    assert call["content"] == main_module.INSUFFICIENT_DATA_ANSWER
    assert "wiring issue" not in call["content"]
    assert call["finish_reason"] == "insufficient_data"
    assert call["status"] == "completed"
    # requirement 6: only the fixed safe answer is ever sent for this fallback
    assert _joined_token_deltas(frames) == main_module.INSUFFICIENT_DATA_ANSWER
    # no tool ever executed -> record_tool_activity is not called at all
    assert len(tool_activity_recorder.calls) == 0


def test_capability_guard_does_not_apply_to_conversational_messages(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)

    provider = _ScriptedProvider(
        rounds=[
            _stop_round("DISCARDED first pass -- must never appear"),  # orchestration round, discarded
            _stop_round("SOC stands for State of Charge."),  # Phase 2 synthesis
        ]
    )

    def _boom_embedding_provider():
        raise AssertionError("embedding provider must not be built for a message with no tool calls")

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "what does SOC mean"}], FakeRequest(),
            is_diagnostic=False, build_embedding_provider=_boom_embedding_provider,
        )
    )

    joined = "".join(frames)
    assert "DISCARDED first pass" not in joined
    assert "event: message_completed" in joined
    assert provider.calls == 2
    assert provider.tools_per_call[1] is None  # Phase 2 synthesis disables tools

    assert finalize_recorder.calls[0]["content"] == "SOC stands for State of Charge."
    assert finalize_recorder.calls[0]["content"] != main_module.INSUFFICIENT_DATA_ANSWER
    assert _joined_token_deltas(frames) == "SOC stands for State of Charge."
