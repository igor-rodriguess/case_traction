"""Testes determinísticos da Provider Layer, sem SDK, rede ou API key."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind, TractianClient
from app.investigation import InvestigationDecisionType, InvestigationPhase, create_investigation_state
from app.llm import (
    FakeLLMProvider,
    LLMError,
    LLMErrorCode,
    LLMGenerationParameters,
    LLMInvestigatorBoundary,
    LLMMessage,
    LLMMetadata,
    LLMOutputValidationError,
    LLMRequest,
    LLMResponse,
    LLMResponseStatus,
    LLMUsage,
    parse_investigation_decision,
)
from app.observability import TrackedToolExecutor
from app.orchestration import InvestigationGraphDependencies, build_investigation_graph
from scripts.generate_investigation_state_example import example_request, example_understanding
from scripts.generate_llm_provider_example import EXAMPLE_PATH, build_showcase


def request(request_id: str = "request_llm") -> LLMRequest:
    return LLMRequest(
        request_id=request_id,
        agent_role="investigator",
        messages=(LLMMessage(role="system", content="Retorne somente JSON."),),
        prompt_version="investigator.v1",
        generation=LLMGenerationParameters(temperature=0),
        expected_schema={"type": "object"},
        max_output_tokens=400,
        timeout_seconds=10,
    )


def response(output, *, request_id: str = "request_llm", status: LLMResponseStatus = LLMResponseStatus.SUCCESS):
    error = None
    if status is not LLMResponseStatus.SUCCESS:
        error = LLMError(code=LLMErrorCode.TIMEOUT, message="fixture failure", retryable=True)
    return LLMResponse(
        request_id=request_id,
        response_id="response_llm",
        provider="fake",
        model="fixture-model",
        status=status,
        output=output,
        usage=LLMUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        duration_ms=4.5,
        error=error,
        metadata=LLMMetadata(prompt_version="investigator.v1", finish_reason="stop"),
    )


def tool_output():
    return {
        "decision_id": "decision_llm_1",
        "type": "tool_call",
        "reason_codes": ["NEED_VIBRATION_DATA"],
        "tool_request": {"tool_name": "get_asset_rms", "arguments": {"asset_id": "asset_B211"}},
    }


def test_request_is_strict_serializable_and_has_no_credential_surface() -> None:
    valid = request()
    assert LLMRequest.model_validate_json(valid.model_dump_json()) == valid
    assert not {"api_key", "headers", "client", "sdk", "chain_of_thought"} & set(LLMRequest.model_fields)
    with pytest.raises(ValidationError):
        LLMRequest.model_validate({**valid.model_dump(), "api_key": "never"})
    with pytest.raises(ValidationError):
        request().model_copy(update={"max_output_tokens": 0}).__class__.model_validate(
            {**valid.model_dump(), "max_output_tokens": 0}
        )


def test_response_usage_metadata_and_error_contracts_are_validated() -> None:
    valid = response(tool_output())
    assert LLMResponse.model_validate_json(valid.model_dump_json()) == valid
    assert valid.usage is not None and valid.usage.total_tokens == 20
    assert valid.metadata.prompt_version == "investigator.v1"
    with pytest.raises(ValidationError, match="soma"):
        LLMUsage(input_tokens=1, output_tokens=2, total_tokens=2)
    with pytest.raises(ValidationError, match="exige output"):
        response(None)


@pytest.mark.parametrize(
    "output",
    [
        "{invalid",
        {"decision_id": "bad", "type": "tool_call", "reason_codes": ["x"]},
        {"decision_id": "bad", "type": "tool_call", "reason_codes": ["x"], "tool_request": {"tool_name": "unknown", "arguments": {}}},
        {"decision_id": "bad", "type": "tool_call", "reason_codes": ["x"], "tool_request": {"tool_name": "request_case_escalation", "arguments": {"case_id": "c"}}},
        {"decision_id": "bad", "type": "tool_call", "reason_codes": ["x"], "tool_request": {"tool_name": "get_asset_rms", "arguments": {}}},
    ],
)
def test_invalid_model_outputs_cannot_cross_decision_boundary(output) -> None:
    with pytest.raises(LLMOutputValidationError):
        parse_investigation_decision(response(output))


def test_fake_provider_is_deterministic_and_has_no_external_configuration() -> None:
    provider = FakeLLMProvider([response(tool_output())])
    returned = provider.infer(request())
    assert returned.provider == "fake"
    assert provider.requests == [request()]
    with pytest.raises(RuntimeError, match="não possui"):
        provider.infer(request())


@pytest.mark.parametrize("status", [LLMResponseStatus.TIMEOUT, LLMResponseStatus.PROVIDER_FAILURE])
def test_provider_timeout_and_failure_are_not_accepted_as_decisions(status) -> None:
    with pytest.raises(LLMOutputValidationError, match="não executável"):
        parse_investigation_decision(response(None, status=status))


def test_boundary_validates_request_correlation_and_decision() -> None:
    runtime = create_investigation_state(example_request(), request_id="request_graph", trace_id="trace_graph")
    boundary = LLMInvestigatorBoundary(
        FakeLLMProvider([response(tool_output(), request_id="request_graph")]),
        lambda state: request(state.request_id),
    )
    decision = boundary(runtime.state)
    assert decision.type is InvestigationDecisionType.TOOL_CALL
    assert decision.tool_request is not None and decision.tool_request.tool_name == "get_asset_rms"


def test_fake_llm_connects_to_existing_langgraph_tool_trace_and_ledger() -> None:
    runtime = create_investigation_state(
        example_request(), case_id="case_llm", request_id="request_llm", trace_id="trace_llm"
    )
    client = Mock(spec=TractianClient)
    client.get_rms.return_value = ClientResult(
        operation="get_rms", operation_kind=OperationKind.READ, method="GET", path="/assets/asset_B211/rms",
        transport_ok=True, status_code=200, evidence_status=EvidenceStatus.COMPLETE, data={"trend": "elevated"},
    )
    provider = FakeLLMProvider(
        [
            response(tool_output()),
            response({"decision_id": "decision_llm_2", "type": "answer", "reason_codes": ["ENOUGH_EVIDENCE"]}),
        ]
    )
    boundary = LLMInvestigatorBoundary(provider, lambda state: request(state.request_id))
    graph = build_investigation_graph(
        InvestigationGraphDependencies(
            runtime=runtime,
            understanding=lambda _: example_understanding(),
            investigator=boundary,
            tool_executor=TrackedToolExecutor(client, runtime.trace, runtime.evidence_ledger),
        )
    )
    state = graph.invoke({"state": runtime.state})["state"]
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert state.tool_call_count == 1 and len(state.evidence_ledger.records) == 1
    assert len(provider.requests) == 2


def test_versioned_showcase_is_generated_from_the_provider_contract() -> None:
    import json

    assert json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")) == build_showcase()
