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
from datetime import date, datetime, timezone

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
        self.messages_per_call: list = []
        self.tool_choice_per_call: list = []

    def stream_chat(self, messages, tools=None, tool_choice=None):
        events = self._rounds[self.calls]
        self.calls += 1
        self.tools_per_call.append(tools)
        self.messages_per_call.append(messages)
        self.tool_choice_per_call.append(tool_choice)

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


# ---------------------------------------------------------------------------
# 1b. tool_choice="required" on round 1 of a diagnostic message (TODO.md
#     "mode 2" finding, 2026-08-26): forces the model to attempt at least
#     one tool call instead of silently skipping straight to a zero-
#     evidence answer.
# ---------------------------------------------------------------------------


def test_round_one_forces_tool_choice_required_for_diagnostic_messages(monkeypatch):
    _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        return {"dataset_id": 12, "summary": {"battery_temperature": {"max": 42}}}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),  # round 1
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert provider.tool_choice_per_call[0] == "required"  # round 1
    assert provider.tool_choice_per_call[1] is None  # Phase 2 synthesis: tools disabled entirely


def test_round_one_does_not_force_tool_choice_for_non_diagnostic_messages(monkeypatch):
    _setup(monkeypatch)

    provider = _ScriptedProvider(rounds=[_stop_round("Hello! How can I help?")])

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "hi"}], FakeRequest(),
            is_diagnostic=False, build_embedding_provider=None,
        )
    )

    assert provider.tool_choice_per_call[0] is None


def test_round_two_does_not_force_tool_choice_even_for_diagnostic_messages(monkeypatch):
    finalize_recorder, tool_activity_recorder = _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        return {"dataset_id": 12, "summary": {"battery_temperature": {"max": 42}}}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),  # round 1
            _tool_call_events("call_2", "get_dataset_summary", {"dataset_id": 13}),  # round 2
            _stop_round("DISCARDED ORCHESTRATION TEXT -- must never appear"),  # round 3: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert provider.tool_choice_per_call[0] == "required"  # round 1
    assert provider.tool_choice_per_call[1] is None  # round 2: back to auto
    assert provider.tool_choice_per_call[2] is None  # round 3: back to auto
    assert provider.tool_choice_per_call[3] is None  # Phase 2 synthesis

    assert provider.calls == 4
    assert provider.tools_per_call[0] is main_module.TOOL_SCHEMAS
    assert provider.tools_per_call[1] is main_module.TOOL_SCHEMAS
    assert provider.tools_per_call[2] is main_module.TOOL_SCHEMAS
    assert provider.tools_per_call[3] is None  # the final synthesis call disables tools

    assert len(finalize_recorder.calls) == 1
    call = finalize_recorder.calls[0]
    assert call["status"] == "completed"
    assert call["content"] == _SEVEN_PART_ANSWER
    assert "DISCARDED ORCHESTRATION TEXT" not in call["content"]

    # SSE token stream concatenation == exact DB content
    assert _joined_token_deltas(frames) == _SEVEN_PART_ANSWER
    assert "DISCARDED ORCHESTRATION TEXT" not in "".join(frames)

    assert len(tool_activity_recorder.calls) == 1
    tool_calls = tool_activity_recorder.calls[0]["tool_calls"]
    assert tool_calls[0]["tool_name"] == "get_dataset_summary"
    assert tool_calls[1]["tool_name"] == "get_dataset_summary"
    assert tool_calls[0]["error"] is False
    assert tool_calls[1]["error"] is False


def test_text_alongside_a_tool_call_in_the_same_round_is_never_sent_or_persisted(monkeypatch):
    """requirement 2, explicit: a round that emits BOTH content deltas and
    a tool call (models sometimes emit a short preamble before calling a
    tool) must never let that preamble reach the client or the DB."""
    finalize_recorder, _ = _setup(monkeypatch)
    # dataset_id: 12 matches _SEVEN_PART_ANSWER's "dataset 12" reference --
    # the groundedness check (TODO.md bug 3, 2026-08-26) requires numeric
    # claims in the final answer to actually appear in the tool evidence.
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"dataset_id": 12, "ok": True})

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
    """Strengthened (TODO.md bug 3, 2026-08-26): a message where the ONLY
    tool call fails (unknown tool) now correctly triggers the same
    insufficient-data fallback as zero tool calls -- a failed call is not
    usable evidence. This reverses the assertion this test had before that
    fix (a failed-but-logged tool_call_log entry used to be enough to
    satisfy the capability guard, which was itself the bug: it let a
    message with only failed tool calls reach unverified synthesis)."""
    finalize_recorder, tool_activity_recorder = _setup(monkeypatch)

    from app.services.tool_registry import UnknownToolError

    def fake_execute_tool(conn, embedding_provider, name, args):
        raise UnknownToolError(name)

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "delete_everything", {}),
            _stop_round("discarded"),  # round 2: orchestration ends, discarded
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
    assert finalize_recorder.calls[0]["content"] == main_module.INSUFFICIENT_DATA_ANSWER


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


# ---------------------------------------------------------------------------
# 5. Tool results containing datetime/date values must be JSON-encoded
#    (via jsonable_encoder) before being embedded in the tool message sent
#    back to the provider -- a raw json.dumps on these shapes previously
#    raised TypeError and aborted orchestration.
# ---------------------------------------------------------------------------


def test_get_dataset_summary_result_with_datetime_is_encoded_and_orchestration_continues(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        assert name == "get_dataset_summary"
        return {
            "dataset_id": 12,
            "summary": {
                "row_count": 100,
                "site_count": 2,
                "start_time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                "end_time": datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
                "columns": {"battery_temperature": {"min": 10.0, "mean": 20.0, "max": 42.0}},
            },
        }

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT -- must never appear"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: message_completed" in joined
    assert "event: error" not in joined

    # orchestration reached Phase 2 synthesis instead of aborting on TypeError
    assert provider.calls == 3
    assert len(finalize_recorder.calls) == 1
    assert finalize_recorder.calls[0]["content"] == _SEVEN_PART_ANSWER

    # the tool message handed to the provider for round 2 must be JSON-decodable
    second_call_messages = provider.messages_per_call[1]
    tool_message = next(m for m in second_call_messages if m.get("role") == "tool")
    decoded = json.loads(tool_message["content"])
    assert decoded["summary"]["start_time"] == "2026-01-01T00:00:00+00:00"
    assert decoded["summary"]["end_time"] == "2026-01-02T00:00:00+00:00"


def test_get_dataset_timeseries_result_with_timestamp_is_encoded_and_orchestration_continues(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        assert name == "get_dataset_timeseries"
        return {
            "dataset_id": 12,
            "total": 1,
            "rows": [
                {
                    "id": 1,
                    "dataset_id": 12,
                    "timestamp": datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc),
                    "reading_date": date(2026, 1, 1),
                    "electricity_price": 3.5,
                    "grid_import_kw": 12.0,
                }
            ],
        }

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_timeseries", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT -- must never appear"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "show me dataset 12 timeseries"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: message_completed" in joined
    assert "event: error" not in joined

    assert provider.calls == 3
    assert len(finalize_recorder.calls) == 1
    assert finalize_recorder.calls[0]["content"] == _SEVEN_PART_ANSWER

    second_call_messages = provider.messages_per_call[1]
    tool_message = next(m for m in second_call_messages if m.get("role") == "tool")
    decoded = json.loads(tool_message["content"])
    assert decoded["rows"][0]["timestamp"] == "2026-01-01T08:30:00+00:00"
    assert decoded["rows"][0]["reading_date"] == "2026-01-01"


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


# ---------------------------------------------------------------------------
# 6. tools= parameter (TODO.md, 2026-08-26): a structural fix for the "表4"
#    (PDF table number) vs dataset_id confusion. generate() no longer
#    hardcodes TOOL_SCHEMAS for Phase 1 -- callers (post_message/
#    post_regenerate, via _tools_for_turn) pass a filtered list when the
#    message looks like a PDF table/figure reference, so the model is never
#    offered the dataset tools it kept misusing. Two prompt-based fixes
#    (tool description rewording, an explicit system instruction) were
#    tried first and confirmed too weak to reliably stop the model.
# ---------------------------------------------------------------------------


def test_generate_defaults_to_full_tool_schemas_when_tools_not_passed(monkeypatch):
    """Regression guard: existing callers that don't pass tools= (like every
    other test in this file) must keep getting the full TOOL_SCHEMAS, not a
    filtered subset -- the filter is additive/conditional, not global."""
    finalize_recorder, _ = _setup(monkeypatch)
    provider = _ScriptedProvider(rounds=[_stop_round(_SEVEN_PART_ANSWER)])

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert provider.tools_per_call[0] is main_module.TOOL_SCHEMAS


def test_generate_uses_the_explicitly_passed_filtered_tool_list(monkeypatch):
    """Proves the filtered list -- not TOOL_SCHEMAS -- is literally what
    reaches stream_chat when a caller passes tools=NON_DATASET_TOOL_SCHEMAS,
    and that the dataset tools are genuinely absent from it."""
    finalize_recorder, _ = _setup(monkeypatch)

    def fake_execute_tool(conn, embedding_provider, name, args):
        assert name == "search_documents"
        return {"results": []}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "search_documents", {"query_text": "表4"}),
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "表4 的數值是多少?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=lambda: object(),
            tools=main_module.NON_DATASET_TOOL_SCHEMAS,
        )
    )

    assert provider.tools_per_call[0] is main_module.NON_DATASET_TOOL_SCHEMAS
    offered_names = {s["function"]["name"] for s in provider.tools_per_call[0]}
    assert offered_names == {"search_documents", "search_similar_cases"}
    assert "get_dataset_summary" not in offered_names
    assert "get_dataset_timeseries" not in offered_names
    assert "get_dataset_analysis" not in offered_names


# ---------------------------------------------------------------------------
# 7. Post-generation groundedness gate (TODO.md bug 3, 2026-08-26): a real
#    LLM-as-a-Judge run found the model can call the right tool, get the
#    correct PDF chunk back, and still fabricate numbers/dates not present
#    in it. Phase 2 is now buffered (never streamed live) so a fabricated
#    draft can be replaced before the client ever sees any of it, preceded
#    by an "thinking" frame so the client can show a working indicator
#    during that buffering.
# ---------------------------------------------------------------------------


def test_thinking_frame_precedes_phase_2_for_every_outcome(monkeypatch):
    finalize_recorder, _ = _setup(monkeypatch)
    provider = _ScriptedProvider(
        rounds=[
            _stop_round("DISCARDED first pass"),  # Phase 1 orchestration round, discarded
            _stop_round("SOC stands for State of Charge."),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "what does SOC mean"}], FakeRequest(),
            is_diagnostic=False, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "event: thinking" in joined
    assert joined.index("event: thinking") < joined.index("event: token")


def test_grounded_draft_answer_is_shown_as_is(monkeypatch):
    """Every numeric claim in the draft appears in the evidence -- the
    groundedness gate must not touch an answer that's actually grounded."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"dataset_id": 12, "ok": True})

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT"),  # round 2: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert finalize_recorder.calls[0]["content"] == _SEVEN_PART_ANSWER
    assert finalize_recorder.calls[0]["finish_reason"] == "stop"
    assert _joined_token_deltas(frames) == _SEVEN_PART_ANSWER
    # a grounded first draft must not burn a spurious retry call
    assert provider.calls == 3


def test_ungrounded_draft_answer_still_ungrounded_after_retry_is_replaced_before_ever_being_shown(monkeypatch):
    """Both the first draft and the retry draft fabricate content -- the
    whole thing must be discarded (not surgically edited, per the design
    decision to fail closed), replaced with INSUFFICIENT_DATA_ANSWER, and
    neither draft's text (nor the corrective retry instruction) may ever
    reach an SSE frame (this is the entire point of buffering Phase 2)."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"dataset_id": 12, "ok": True})

    fabricated_1 = (
        "## Confirmed facts / Finding\nSOC 從 91.9% 變化到 89.9%\n\n"
        "## Evidence\ndataset 12\n\n"
        "## Possible causes\nhypothesis\n\n"
        "## General engineering background\nn/a\n\n"
        "## Suggested actions / Next checks\ncheck cooling\n\n"
        "## Confidence\nmedium\n\n"
        "## Citations\n[internal] dataset 12"
    )
    fabricated_2 = (
        "## Confirmed facts / Finding\nSOC 從 77.7% 變化到 66.6%\n\n"
        "## Evidence\ndataset 12\n\n"
        "## Possible causes\nhypothesis\n\n"
        "## General engineering background\nn/a\n\n"
        "## Suggested actions / Next checks\ncheck cooling\n\n"
        "## Confidence\nmedium\n\n"
        "## Citations\n[internal] dataset 12"
    )
    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT"),  # round 2: orchestration ends, discarded
            _stop_round(fabricated_1),  # Phase 2 attempt 1: fabricates 91.9%/89.9%
            _stop_round(fabricated_2),  # Phase 2 attempt 2 (retry): still fabricates
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    for leaked in ("91.9%", "89.9%", "77.7%", "66.6%", "do not appear verbatim"):
        assert leaked not in joined
    assert finalize_recorder.calls[0]["content"] == main_module.INSUFFICIENT_DATA_ANSWER
    assert finalize_recorder.calls[0]["finish_reason"] == "ungrounded_retry_exhausted"
    assert _joined_token_deltas(frames) == main_module.INSUFFICIENT_DATA_ANSWER
    assert provider.calls == 4  # 2 orchestration rounds + 2 synthesis attempts

    # the retry's corrective message must actually be sent to the provider
    retry_call_messages = provider.messages_per_call[3]
    assert any(
        m.get("role") == "user" and "91.9%" in m.get("content", "") for m in retry_call_messages
    ), "corrective retry message must name the unsupported claims from attempt 1"


def test_ungrounded_draft_retried_then_grounded_draft_is_shown(monkeypatch):
    """Draft 1 fabricates a percentage; draft 2 (after the corrective
    retry message) is fully grounded -- the retry must recover the answer
    instead of falling back to INSUFFICIENT_DATA_ANSWER."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"dataset_id": 12, "ok": True})

    fabricated_answer = (
        "## Confirmed facts / Finding\nSOC 從 91.9% 變化到 89.9%\n\n"
        "## Evidence\ndataset 12\n\n"
        "## Possible causes\nhypothesis\n\n"
        "## General engineering background\nn/a\n\n"
        "## Suggested actions / Next checks\ncheck cooling\n\n"
        "## Confidence\nmedium\n\n"
        "## Citations\n[internal] dataset 12"
    )
    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT"),  # round 2: orchestration ends, discarded
            _stop_round(fabricated_answer),  # Phase 2 attempt 1: ungrounded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 attempt 2 (retry): grounded
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    joined = "".join(frames)
    assert "91.9%" not in joined and "89.9%" not in joined  # fabricated draft never shown
    assert finalize_recorder.calls[0]["content"] == _SEVEN_PART_ANSWER
    assert finalize_recorder.calls[0]["finish_reason"] == "stop"
    assert _joined_token_deltas(frames) == _SEVEN_PART_ANSWER
    assert provider.calls == 4  # 2 orchestration rounds + 2 synthesis attempts


def test_grounding_retry_skipped_when_insufficient_time_budget_remains(monkeypatch):
    """If barely any of the overall timeout budget is left after attempt 1,
    the retry must be skipped entirely (not attempted and then timed out
    mid-stream) -- forcing GROUNDING_RETRY_MIN_REMAINING_SECONDS above the
    whole overall budget makes every attempt 2 look "too late", regardless
    of real elapsed time, which is deterministic and fast for a test."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"dataset_id": 12, "ok": True})
    monkeypatch.setattr(main_module, "GROUNDING_RETRY_MIN_REMAINING_SECONDS", main_module.OVERALL_GENERATION_TIMEOUT_SECONDS + 1)

    fabricated_answer = (
        "## Confirmed facts / Finding\nSOC 從 91.9% 變化到 89.9%\n\n"
        "## Evidence\ndataset 12\n\n"
        "## Possible causes\nhypothesis\n\n"
        "## General engineering background\nn/a\n\n"
        "## Suggested actions / Next checks\ncheck cooling\n\n"
        "## Confidence\nmedium\n\n"
        "## Citations\n[internal] dataset 12"
    )
    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "get_dataset_summary", {"dataset_id": 12}),
            _stop_round("DISCARDED ORCHESTRATION TEXT"),  # round 2: orchestration ends, discarded
            _stop_round(fabricated_answer),  # Phase 2 attempt 1: ungrounded, no retry follows
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "why is battery 12 hot?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert finalize_recorder.calls[0]["content"] == main_module.INSUFFICIENT_DATA_ANSWER
    assert finalize_recorder.calls[0]["finish_reason"] == "ungrounded_retry_exhausted"
    assert provider.calls == 3  # no retry call attempted


def test_groundedness_gate_skipped_when_no_evidence_to_check_against(monkeypatch):
    """A conversational message (no tool calls, no evidence) has nothing to
    verify against -- the gate must not block it."""
    finalize_recorder, _ = _setup(monkeypatch)
    provider = _ScriptedProvider(
        rounds=[
            _stop_round("DISCARDED first pass"),  # orchestration round, discarded
            _stop_round("SOC stands for 91.9% charge, roughly."),  # Phase 2 synthesis
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "what does SOC mean"}], FakeRequest(),
            is_diagnostic=False, build_embedding_provider=None,
        )
    )

    assert finalize_recorder.calls[0]["content"] == "SOC stands for 91.9% charge, roughly."


def test_capability_guard_treats_empty_search_result_as_no_evidence(monkeypatch):
    """A tool call that "succeeds" but finds nothing (e.g. search_documents
    with zero matches) must not satisfy the capability guard -- an empty
    results list is not meaningfully different from a failed call."""
    finalize_recorder, _ = _setup(monkeypatch)
    monkeypatch.setattr(main_module, "execute_tool", lambda conn, ep, name, args: {"results": []})

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "search_documents", {"query_text": "表4"}),
            _stop_round("discarded"),  # round 2: orchestration ends, discarded
        ]
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "表4 的內容是什麼?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=lambda: object(),
        )
    )

    assert finalize_recorder.calls[0]["content"] == main_module.INSUFFICIENT_DATA_ANSWER
    assert "discarded" not in "".join(frames)


def test_filtered_tools_with_zero_tool_calls_still_hits_capability_guard(monkeypatch):
    """Even in the worst case -- the model ignores both remaining tools and
    tries to answer straight from general knowledge -- the pre-existing
    capability guard (unrelated to this fix) still catches it, so the
    failure mode stays "資料不足", never a confidently wrong answer."""
    finalize_recorder, _ = _setup(monkeypatch)

    provider = _ScriptedProvider(
        rounds=[_stop_round("表4 大概是某某規格（憑印象回答，未呼叫任何工具）")],
    )

    frames = _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "表4 的內容是什麼?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
            tools=main_module.NON_DATASET_TOOL_SCHEMAS,
        )
    )

    assert finalize_recorder.calls[0]["content"] == main_module.INSUFFICIENT_DATA_ANSWER
    assert "表4 大概是" not in "".join(frames)


# ---------------------------------------------------------------------------
# 8. Guessed document_id is stripped before search_documents executes
#    (TODO.md "mode 2" finding, 2026-08-28): real end-to-end testing caught
#    the model guessing document_id=1 for a question whose answer was in a
#    different document, silently zeroing the search results instead of
#    erroring or searching broadly.
# ---------------------------------------------------------------------------


def test_guessed_document_id_is_stripped_before_search_documents_executes(monkeypatch):
    _setup(monkeypatch)
    received_args = []

    def fake_execute_tool(conn, embedding_provider, name, args):
        received_args.append(args)
        return {"results": [{"document_id": 3, "content": "表4 ... 2024年5月26日 ... 四筆"}]}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events(
                "call_1", "search_documents", {"query_text": "表4 超約時段", "document_id": 1}  # never seen -> guessed
            ),
            _stop_round(_SEVEN_PART_ANSWER),
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "表4 中 2024年5月26日 有幾筆超約時段?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert received_args[0]["document_id"] is None  # guessed id 1 stripped, search proceeds unrestricted


def test_document_id_seen_in_an_earlier_round_this_turn_is_kept(monkeypatch):
    _setup(monkeypatch)
    received_args = []

    def fake_execute_tool(conn, embedding_provider, name, args):
        received_args.append(args)
        return {"results": [{"document_id": 3, "content": "..."}]}

    monkeypatch.setattr(main_module, "execute_tool", fake_execute_tool)

    provider = _ScriptedProvider(
        rounds=[
            _tool_call_events("call_1", "search_documents", {"query_text": "表4"}),  # round 1: learns document_id 3
            _tool_call_events(
                "call_2", "search_documents", {"query_text": "表4 續", "document_id": 3}
            ),  # round 2: reuses a genuinely-seen id
            _stop_round("DISCARDED ORCHESTRATION TEXT -- must never appear"),  # round 3: orchestration ends, discarded
            _stop_round(_SEVEN_PART_ANSWER),  # Phase 2 synthesis
        ]
    )

    _collect_frames(
        main_module.generate(
            42, provider, [{"role": "user", "content": "表4 的內容?"}], FakeRequest(),
            is_diagnostic=True, build_embedding_provider=None,
        )
    )

    assert received_args[0].get("document_id") is None
    assert received_args[1]["document_id"] == 3  # legitimately seen in round 1 -- kept, not stripped
