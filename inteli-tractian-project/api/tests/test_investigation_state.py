"""Testes determinísticos do InvestigationState, sem LLM ou rede."""

from __future__ import annotations

import json
import re
from enum import Enum

import pytest
from pydantic import ValidationError

from app.agents.understanding.schemas import UnderstandingInput
from app.investigation import (
    FinalResponse,
    HumanHandoff,
    InvestigationDecision,
    InvestigationDecisionType,
    InvestigationError,
    InvestigationErrorCode,
    InvestigationPhase,
    InvestigationState,
    LoopLimitExceeded,
    StateTransitionError,
    ToolRequest,
    UnderstandingSource,
    attach_final_response,
    attach_human_handoff,
    attach_understanding,
    begin_investigation,
    create_investigation_state,
    mark_failed,
    record_decision,
    synchronize_observability,
)
from app.investigation.state import forbidden_state_field_names
from app.observability import EvidenceLedger, ExecutionTrace
from scripts.generate_investigation_state_example import (
    EXAMPLE_PATH,
    build_example_state,
    example_request,
    example_understanding,
)


def initialized(**overrides):
    defaults = {
        "case_id": "case_1",
        "request_id": "request_1",
        "trace_id": "trace_1",
    }
    defaults.update(overrides)
    return create_investigation_state(example_request(), **defaults)


def investigating(**overrides) -> InvestigationState:
    runtime = initialized(**overrides)
    state = attach_understanding(
        runtime.state,
        example_understanding(),
        source=UnderstandingSource.TEST_FIXTURE,
    )
    return begin_investigation(state)


def decision(kind: InvestigationDecisionType, **overrides) -> InvestigationDecision:
    values = {
        "decision_id": f"decision_{kind.value}",
        "type": kind,
        "reason_codes": ("fixture_reason",),
    }
    if kind is InvestigationDecisionType.TOOL_CALL:
        values["tool_request"] = ToolRequest(
            tool_name="get_asset_context", arguments={"asset_id": "asset_B211"}
        )
    if kind is InvestigationDecisionType.ASK_USER:
        values["required_information"] = ("asset_id",)
    values.update(overrides)
    return InvestigationDecision.model_validate(values)


def test_factory_initializes_complete_safe_state() -> None:
    runtime = initialized(max_investigation_steps=7, max_tool_calls=4)
    state = runtime.state

    assert (state.case_id, state.request_id, state.trace_id) == ("case_1", "request_1", "trace_1")
    assert state.phase is InvestigationPhase.RECEIVED
    assert state.understanding is None
    assert state.understanding_source is None
    assert state.decision is None
    assert state.final_response is None
    assert state.human_handoff is None
    assert state.error is None
    assert (state.investigation_step_count, state.max_investigation_steps) == (0, 7)
    assert (state.tool_call_count, state.max_tool_calls) == (0, 4)
    assert state.trace.events == ()
    assert state.evidence_ledger.records == ()


def test_factory_creates_prefixed_ids_when_omitted() -> None:
    state = create_investigation_state(example_request()).state
    assert re.fullmatch(r"case_[0-9a-f]{32}", state.case_id)
    assert re.fullmatch(r"request_[0-9a-f]{32}", state.request_id)
    assert re.fullmatch(r"trace_[0-9a-f]{32}", state.trace_id)


def test_ids_remain_stable_across_transitions() -> None:
    initial = initialized().state
    attached = attach_understanding(
        initial, example_understanding(), source=UnderstandingSource.TEST_FIXTURE
    )
    started = begin_investigation(attached)
    assert (started.case_id, started.request_id, started.trace_id) == (
        initial.case_id,
        initial.request_id,
        initial.trace_id,
    )


def test_factory_reuses_matching_trace_and_ledger() -> None:
    trace = ExecutionTrace("trace_shared")
    ledger = EvidenceLedger("trace_shared")
    runtime = create_investigation_state(
        example_request(), trace=trace, evidence_ledger=ledger, case_id="case_1", request_id="request_1"
    )
    assert runtime.trace is trace
    assert runtime.evidence_ledger is ledger
    assert runtime.state.trace_id == "trace_shared"


def test_factory_rejects_mismatched_observability_resources() -> None:
    with pytest.raises(ValueError, match="coincidir"):
        create_investigation_state(
            example_request(), trace=ExecutionTrace("trace_a"), evidence_ledger=EvidenceLedger("trace_b")
        )


@pytest.mark.parametrize("field", ["max_investigation_steps", "max_tool_calls"])
def test_factory_rejects_non_positive_limits(field: str) -> None:
    with pytest.raises(ValidationError):
        initialized(**{field: 0})


def test_original_request_is_preserved_and_frozen() -> None:
    request = example_request()
    state = create_investigation_state(request, case_id="case_1", request_id="request_1", trace_id="trace_1").state
    assert state.request == request
    with pytest.raises(ValidationError):
        state.request.message = "reescrita"  # type: ignore[misc]


def test_attach_understanding_sets_typed_output_and_source() -> None:
    state = attach_understanding(
        initialized().state,
        example_understanding(),
        source=UnderstandingSource.TEST_FIXTURE,
    )
    assert state.phase is InvestigationPhase.UNDERSTANDING_COMPLETE
    assert state.understanding == example_understanding()
    assert state.understanding_source is UnderstandingSource.TEST_FIXTURE


def test_understanding_cannot_be_attached_twice() -> None:
    state = attach_understanding(
        initialized().state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE
    )
    with pytest.raises(StateTransitionError, match="uma vez"):
        attach_understanding(state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE)


def test_investigation_requires_completed_understanding() -> None:
    with pytest.raises(StateTransitionError, match="UNDERSTANDING_COMPLETE"):
        begin_investigation(initialized().state)


def test_begin_investigation_changes_only_operational_phase() -> None:
    before = attach_understanding(
        initialized().state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE
    )
    after = begin_investigation(before)
    assert after.phase is InvestigationPhase.INVESTIGATING
    assert after.request == before.request
    assert after.understanding == before.understanding


def test_tool_request_accepts_only_registered_read_tools() -> None:
    request = ToolRequest(tool_name="get_asset_rms", arguments={"asset_id": "asset_B211"})
    assert request.tool_name == "get_asset_rms"
    with pytest.raises(ValidationError, match="READ tool"):
        ToolRequest(tool_name="request_case_escalation", arguments={"case_id": "case_1"})
    with pytest.raises(ValidationError, match="READ tool"):
        ToolRequest(tool_name="invented_tool", arguments={})


def test_tool_request_rejects_extra_or_non_json_fields() -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate({"tool_name": "get_asset_context", "arguments": {}, "execute": True})
    with pytest.raises(ValidationError):
        ToolRequest(tool_name="get_asset_context", arguments={"value": object()})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"decision_id": "d1", "type": "tool_call", "reason_codes": ["need_data"]},
            "tool_request",
        ),
        (
            {
                "decision_id": "d1",
                "type": "continue",
                "reason_codes": ["continue"],
                "tool_request": {"tool_name": "get_asset_context", "arguments": {}},
            },
            "tool_request",
        ),
        (
            {"decision_id": "d1", "type": "ask_user", "reason_codes": ["missing"]},
            "required_information",
        ),
    ],
)
def test_decision_shape_is_validated_by_type(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        InvestigationDecision.model_validate(payload)


@pytest.mark.parametrize(
    ("kind", "expected_phase"),
    [
        (InvestigationDecisionType.CONTINUE, InvestigationPhase.INVESTIGATING),
        (InvestigationDecisionType.TOOL_CALL, InvestigationPhase.INVESTIGATING),
        (InvestigationDecisionType.ASK_USER, InvestigationPhase.AWAITING_USER),
        (InvestigationDecisionType.ANSWER, InvestigationPhase.READY_FOR_RESPONSE),
        (InvestigationDecisionType.ESCALATE, InvestigationPhase.HUMAN_REQUIRED),
    ],
)
def test_decision_and_phase_remain_separate(kind, expected_phase) -> None:
    state = record_decision(investigating(), decision(kind))
    assert state.decision.type is kind
    assert state.phase is expected_phase
    assert state.investigation_step_count == 1


def test_decision_requires_investigating_phase() -> None:
    with pytest.raises(StateTransitionError, match="INVESTIGATING"):
        record_decision(initialized().state, decision(InvestigationDecisionType.CONTINUE))


def test_investigation_step_limit_is_enforced_before_new_decision() -> None:
    state = investigating(max_investigation_steps=1)
    state = record_decision(state, decision(InvestigationDecisionType.CONTINUE))
    with pytest.raises(LoopLimitExceeded, match="passos"):
        record_decision(state, decision(InvestigationDecisionType.CONTINUE))


def test_tool_limit_is_enforced_before_tool_decision() -> None:
    state = investigating(max_tool_calls=1)
    state = state.model_copy(update={"tool_call_count": 1})
    with pytest.raises(LoopLimitExceeded, match="tools|tool|chamadas"):
        record_decision(state, decision(InvestigationDecisionType.TOOL_CALL))


def test_unknown_supporting_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="desconhecidos"):
        record_decision(
            investigating(),
            decision(InvestigationDecisionType.ANSWER, supporting_evidence_ids=("evidence_unknown",)),
        )


def test_deterministic_flow_updates_trace_ledger_and_counters() -> None:
    state = build_example_state()
    assert state.phase is InvestigationPhase.INVESTIGATING
    assert state.investigation_step_count == 1
    assert state.tool_call_count == 1
    assert state.decision is not None
    assert state.decision.tool_request is not None
    assert len(state.trace.events) == 2
    assert len(state.evidence_ledger.records) == 1
    evidence = state.evidence_ledger.records[0]
    completed = state.trace.events[1]
    assert evidence.source_call_id == completed.call_id == "call_fixture_001"
    assert evidence.source_trace_sequence == completed.sequence
    assert evidence.evidence_id == "evidence_fixture_001"


def test_observability_sync_rejects_other_trace() -> None:
    with pytest.raises(ValueError, match="outro trace_id"):
        synchronize_observability(
            initialized().state, ExecutionTrace("other"), EvidenceLedger("other")
        )


def test_state_json_round_trip_is_deterministic_and_checkpoint_safe() -> None:
    state = build_example_state()
    first = state.model_dump_json(indent=2)
    restored = InvestigationState.model_validate_json(first)
    assert restored == state
    assert restored.model_dump_json(indent=2) == first
    payload = json.loads(first)
    assert isinstance(payload["trace"]["events"], list)
    assert isinstance(payload["evidence_ledger"]["records"], list)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"phase": "completed"}, "final_response"),
        (
            {
                "phase": "failed",
                "error": None,
            },
            "error",
        ),
        (
            {
                "tool_call_count": 1,
            },
            "tool_call_count",
        ),
    ],
)
def test_checkpoint_validation_rejects_impossible_operational_state(updates, message) -> None:
    base = investigating() if updates.get("phase") == "completed" else initialized().state
    payload = base.model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        InvestigationState.model_validate(payload)


def test_final_response_placeholder_completes_ready_state() -> None:
    state = record_decision(investigating(), decision(InvestigationDecisionType.ANSWER))
    completed = attach_final_response(
        state, FinalResponse(response_id="response_1", text="Resposta fixture.")
    )
    assert completed.phase is InvestigationPhase.COMPLETED
    assert completed.final_response.text == "Resposta fixture."
    with pytest.raises(StateTransitionError):
        attach_final_response(completed, FinalResponse(response_id="response_2", text="Outra."))


def test_handoff_placeholder_requires_human_phase() -> None:
    state = record_decision(investigating(), decision(InvestigationDecisionType.ESCALATE))
    updated = attach_human_handoff(
        state,
        HumanHandoff(handoff_id="handoff_1", reason_codes=("specialist_required",)),
    )
    assert updated.phase is InvestigationPhase.HUMAN_REQUIRED
    assert updated.human_handoff.handoff_id == "handoff_1"
    with pytest.raises(StateTransitionError):
        attach_human_handoff(investigating(), updated.human_handoff)


def test_mark_failed_records_minimal_operational_error() -> None:
    failed = mark_failed(
        initialized().state,
        InvestigationError(
            code=InvestigationErrorCode.UNDERSTANDING_UNAVAILABLE,
            can_continue=False,
            summary="Understanding indisponível.",
        ),
    )
    assert failed.phase is InvestigationPhase.FAILED
    assert failed.error.can_continue is False
    with pytest.raises(StateTransitionError):
        mark_failed(failed, failed.error)


def test_state_has_no_provider_model_or_chain_of_thought_fields() -> None:
    fields = set(InvestigationState.model_fields)
    assert fields.isdisjoint(
        {
            "provider",
            "model",
            "model_id",
            "routing",
            *forbidden_state_field_names(),
        }
    )


def test_state_does_not_duplicate_understanding_or_observability_fields() -> None:
    fields = set(InvestigationState.model_fields)
    assert fields.isdisjoint(
        {
            "questions",
            "entities",
            "missing_information",
            "investigation_targets",
            "tool_history",
            "evidence",
        }
    )


def test_phase_and_decision_enums_contain_no_action_execution() -> None:
    values = {item.value for enum in (InvestigationPhase, InvestigationDecisionType) for item in enum}
    assert "action" not in values
    assert "execute_action" not in values


def test_versioned_example_was_generated_from_the_same_flow() -> None:
    expected = json.loads(build_example_state().model_dump_json())
    actual = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert actual == expected


def test_all_contract_enums_are_plain_json_strings() -> None:
    state = build_example_state()
    payload = state.model_dump(mode="json")
    assert not any(isinstance(value, Enum) for value in payload.values())
