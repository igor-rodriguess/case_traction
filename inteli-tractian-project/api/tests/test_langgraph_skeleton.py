"""Contrato determinístico do esqueleto LangGraph, sem rede nem provider."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import pytest
from pydantic import ValidationError

from app.integrations.tractian_client import ClientError, ClientErrorKind, ClientResult, EvidenceStatus, OperationKind
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    InvestigationPhase,
    ToolRequest,
    create_investigation_state,
)
from app.observability import TrackedToolExecutor
from app.orchestration import InvestigationGraphDependencies, build_investigation_graph
from scripts.generate_langgraph_skeleton_example import EXAMPLE_PATH, build_showcase
from scripts.generate_investigation_state_example import example_request, example_understanding


class FixtureClient:
    def __init__(self, results: Iterable[ClientResult]) -> None:
        self.results = deque(results)

    def get_asset(self, asset_id: str) -> ClientResult:
        return self.results.popleft()

    def get_rms(self, asset_id: str, *, point_id: str | None = None) -> ClientResult:
        return self.results.popleft()


class Decisions:
    def __init__(self, values: Iterable[InvestigationDecision]) -> None:
        self.values = deque(values)
        self.states = []

    def __call__(self, state):
        self.states.append(state)
        return self.values.popleft()


def read_result(status: EvidenceStatus = EvidenceStatus.COMPLETE, *, transport_ok: bool = True) -> ClientResult:
    return ClientResult(
        operation="get_asset",
        operation_kind=OperationKind.READ,
        method="GET",
        path="/assets/asset_B211",
        transport_ok=transport_ok,
        status_code=200 if transport_ok else None,
        evidence_status=status if transport_ok else None,
        data={"id": "asset_B211"},
        error=None if transport_ok else ClientError(ClientErrorKind.TIMEOUT, "fixture timeout"),
    )


def decision(kind: InvestigationDecisionType, index: int, **extra) -> InvestigationDecision:
    payload = {"decision_id": f"decision_{index}", "type": kind, "reason_codes": ("fixture",)}
    if kind is InvestigationDecisionType.TOOL_CALL:
        payload["tool_request"] = ToolRequest(
            tool_name=extra.pop("tool_name", "get_asset_context"),
            arguments={"asset_id": "asset_B211"},
        )
    if kind is InvestigationDecisionType.ASK_USER:
        payload["required_information"] = ("asset_id",)
    payload.update(extra)
    return InvestigationDecision(**payload)


def run_graph(
    decisions: Iterable[InvestigationDecision],
    results: Iterable[ClientResult] = (),
    **runtime_kwargs,
):
    runtime = create_investigation_state(
        example_request(), case_id="case_graph", request_id="request_graph", trace_id="trace_graph", **runtime_kwargs
    )
    executor = TrackedToolExecutor(FixtureClient(results), runtime.trace, runtime.evidence_ledger)  # type: ignore[arg-type]
    fixture = Decisions(decisions)
    graph = build_investigation_graph(
        InvestigationGraphDependencies(
            runtime=runtime,
            understanding=lambda _: example_understanding(),
            investigator=fixture,
            tool_executor=executor,
        )
    )
    return graph.invoke({"state": runtime.state})["state"], fixture


def test_happy_path_tool_then_answer_preserves_canonical_state_and_audit_data() -> None:
    state, fixture = run_graph(
        [decision(InvestigationDecisionType.TOOL_CALL, 1), decision(InvestigationDecisionType.ANSWER, 2)],
        [read_result()],
    )
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert (state.case_id, state.request_id, state.trace_id) == ("case_graph", "request_graph", "trace_graph")
    assert state.request == example_request()
    assert state.understanding == example_understanding()
    assert state.tool_call_count == 1 and state.investigation_step_count == 2
    assert len(state.trace.events) == 2 and len(state.evidence_ledger.records) == 1
    assert fixture.states[1].evidence_ledger.records[0].source_call_id == state.trace.events[-1].call_id


def test_multiple_tool_calls_return_to_investigator_before_answer() -> None:
    state, fixture = run_graph(
        [
            decision(InvestigationDecisionType.TOOL_CALL, 1),
            decision(InvestigationDecisionType.TOOL_CALL, 2, tool_name="get_asset_rms"),
            decision(InvestigationDecisionType.ANSWER, 3),
        ],
        [read_result(), read_result()],
    )
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert state.tool_call_count == 2 and state.investigation_step_count == 3
    assert [record.tool_name for record in state.evidence_ledger.records] == ["get_asset_context", "get_asset_rms"]
    assert len(fixture.states) == 3


def test_ask_user_and_escalate_stop_at_their_explicit_boundaries() -> None:
    awaiting, _ = run_graph([decision(InvestigationDecisionType.ASK_USER, 1)])
    escalated, _ = run_graph([decision(InvestigationDecisionType.ESCALATE, 1)])
    assert awaiting.phase is InvestigationPhase.AWAITING_USER
    assert awaiting.decision is not None and awaiting.decision.required_information == ("asset_id",)
    assert escalated.phase is InvestigationPhase.HUMAN_REQUIRED
    assert escalated.tool_call_count == 0 and escalated.human_handoff is None


@pytest.mark.parametrize("status", [EvidenceStatus.PARTIAL, EvidenceStatus.INCONCLUSIVE, EvidenceStatus.CONFLICT, EvidenceStatus.UNAVAILABLE])
def test_semantic_statuses_are_evidence_not_orchestration_failures(status: EvidenceStatus) -> None:
    state, fixture = run_graph(
        [decision(InvestigationDecisionType.TOOL_CALL, 1), decision(InvestigationDecisionType.ANSWER, 2)],
        [read_result(status)],
    )
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert state.evidence_ledger.records[0].evidence_status is status
    assert len(fixture.states) == 2


def test_transport_failure_becomes_structured_failed_state_without_evidence() -> None:
    state, _ = run_graph([decision(InvestigationDecisionType.TOOL_CALL, 1)], [read_result(transport_ok=False)])
    assert state.phase is InvestigationPhase.FAILED
    assert state.error is not None and state.error.code.value == "tool_execution_failure"
    assert len(state.trace.events) == 2 and state.evidence_ledger.records == ()


def test_investigation_and_tool_limits_stop_deterministically() -> None:
    steps, _ = run_graph(
        [decision(InvestigationDecisionType.CONTINUE, 1), decision(InvestigationDecisionType.ANSWER, 2)],
        max_investigation_steps=1,
    )
    tools, _ = run_graph(
        [decision(InvestigationDecisionType.TOOL_CALL, 1), decision(InvestigationDecisionType.TOOL_CALL, 2)],
        [read_result(), read_result()],
        max_tool_calls=1,
    )
    assert steps.phase is InvestigationPhase.FAILED and steps.error is not None
    assert tools.phase is InvestigationPhase.FAILED and tools.tool_call_count == 1


def test_action_is_blocked_before_it_can_cross_the_graph_boundary() -> None:
    with pytest.raises(ValidationError, match="READ tool"):
        ToolRequest(tool_name="request_case_escalation", arguments={"case_id": "case_graph"})


def test_graph_is_provider_independent_and_does_not_need_an_api_key() -> None:
    state, _ = run_graph([decision(InvestigationDecisionType.ANSWER, 1)])
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert not {"provider", "model", "api_key"} & set(type(state).model_fields)


def test_versioned_showcase_is_generated_from_the_representative_graph_flow() -> None:
    import json

    expected = build_showcase()
    actual = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert actual == expected
