"""Contratos e E2E determinístico da Etapa 08, sem provider externo."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind, TractianClient
from app.intelligence.boundaries import PlannerLLMBoundary, ReporterLLMBoundary, parse_planner_output, parse_reporter_output
from app.intelligence.contracts import (
    CapabilityReference, Claim, InvestigationConclusion, PlannerInput, PlannerOutput, ReporterInput,
)
from app.investigation import InvestigationPhase, create_investigation_state
from app.llm import FakeLLMProvider, LLMGenerationParameters, LLMMessage, LLMMetadata, LLMRequest, LLMResponse, LLMResponseStatus, LLMUsage
from app.llm.investigator import LLMInvestigatorBoundary
from app.observability import TrackedToolExecutor
from app.orchestration import InvestigationGraphDependencies, build_investigation_graph
from scripts.generate_investigation_state_example import example_request, example_understanding


def request(request_id: str, role: str) -> LLMRequest:
    return LLMRequest(request_id=request_id, agent_role=role, messages=(LLMMessage(role="system", content="JSON somente."),), prompt_version=f"{role}.v1", generation=LLMGenerationParameters(), expected_schema={"type": "object"}, max_output_tokens=400, timeout_seconds=10)


def response(request_id: str, output: dict) -> LLMResponse:
    return LLMResponse(request_id=request_id, response_id=f"response_{request_id}", provider="fake", model="fixture", status=LLMResponseStatus.SUCCESS, output=output, usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2), duration_ms=1, metadata=LLMMetadata(prompt_version="fixture.v1"))


def plan_output() -> dict:
    return {"plan_id": "plan_1", "objectives": ["Verificar desvio de vibração."], "investigation_questions": ["O RMS diverge do baseline?"], "suggested_capabilities": [{"name": "get_asset_rms"}, {"name": "get_asset_baseline"}], "dependencies": [], "missing_information": [], "stopping_conditions": ["Evidência suficiente ou limitação explícita."], "reason_codes": ["RMS_DEVIATION"]}


def test_planner_contract_is_strict_read_only_and_adaptable() -> None:
    value = PlannerInput(understanding=example_understanding(), available_capabilities=(CapabilityReference(name="get_asset_rms"),), max_investigation_steps=12, max_tool_calls=8)
    plan = PlannerOutput.model_validate(plan_output())
    assert value.understanding == example_understanding()
    assert [item.name for item in plan.suggested_capabilities] == ["get_asset_rms", "get_asset_baseline"]
    with pytest.raises(ValidationError, match="READ tool"):
        PlannerOutput.model_validate({**plan_output(), "suggested_capabilities": [{"name": "request_case_escalation"}]})
    with pytest.raises(ValidationError):
        PlannerInput.model_validate({**value.model_dump(), "chain_of_thought": "no"})


def test_planner_and_reporter_boundaries_reject_invalid_output() -> None:
    planner = PlannerLLMBoundary(FakeLLMProvider([response("planner_1", {"bad": True})]), lambda _: request("planner_1", "planner"))
    with pytest.raises(ValueError):
        planner(PlannerInput(understanding=example_understanding(), available_capabilities=(CapabilityReference(name="get_asset_rms"),), max_investigation_steps=12, max_tool_calls=8))
    with pytest.raises(ValueError):
        parse_reporter_output(response("reporter_1", {"report_id": "r"}))


def test_claims_and_report_keep_evidence_references() -> None:
    claim = Claim(claim_id="claim_1", statement="RMS está elevado.", supporting_evidence_ids=("evidence_1",))
    conclusion = InvestigationConclusion(conclusion_id="conclusion_1", claims=(claim,), supporting_evidence_ids=("evidence_1",), reason_codes=("EVIDENCE_COLLECTED",))
    assert conclusion.claims[0].supporting_evidence_ids == ("evidence_1",)
    with pytest.raises(ValidationError, match="evidências declaradas"):
        InvestigationConclusion(conclusion_id="bad", claims=(claim,), supporting_evidence_ids=("other",), reason_codes=("X",))


def test_end_to_end_fake_llms_planner_advises_but_investigator_adapts_and_reports() -> None:
    runtime = create_investigation_state(example_request(), case_id="case_8", request_id="request_8", trace_id="trace_8")
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = ClientResult("get_asset", OperationKind.READ, "GET", "/assets/asset_B211", True, 200, EvidenceStatus.COMPLETE, {"criticality": "high"})
    client.get_rms.return_value = ClientResult("get_rms", OperationKind.READ, "GET", "/assets/asset_B211/rms", True, 200, EvidenceStatus.PARTIAL, {"trend": "elevated"})
    planner = PlannerLLMBoundary(FakeLLMProvider([response("planner_8", plan_output())]), lambda _: request("planner_8", "planner"))
    investigator = LLMInvestigatorBoundary(FakeLLMProvider([
        response("request_8", {"decision_id": "d1", "type": "tool_call", "reason_codes": ["CONTEXT"], "tool_request": {"tool_name": "get_asset_context", "arguments": {"asset_id": "asset_B211"}}}),
        response("request_8", {"decision_id": "d2", "type": "tool_call", "reason_codes": ["UNEXPECTED_DATA_QUALITY_NEED"], "tool_request": {"tool_name": "get_asset_rms", "arguments": {"asset_id": "asset_B211"}}}),
        response("request_8", {"decision_id": "d3", "type": "answer", "reason_codes": ["ENOUGH_EVIDENCE"]}),
    ]), lambda state: request(state.request_id, "investigator"))
    def conclusion(state):
        evidence = tuple(record.evidence_id for record in state.evidence_ledger.records)
        return InvestigationConclusion(conclusion_id="conclusion_8", claims=(Claim(claim_id="claim_8", statement="Há tendência RMS elevada, com evidência parcial.", supporting_evidence_ids=(evidence[1],), limitation="A leitura RMS é parcial."),), supporting_evidence_ids=evidence, limitations=("Evidência RMS parcial.",), reason_codes=("EVIDENCE_COLLECTED",))
    report_payload = {"report_id": "report_8", "case_id": "case_8", "executive_summary": "Investigar tendência RMS elevada.", "investigation_performed": ["Contexto e RMS consultados."], "findings": ["RMS elevado com evidência parcial."], "claims": [{"claim_id": "claim_8", "statement": "Há tendência RMS elevada, com evidência parcial.", "supporting_evidence_ids": ["trace_8:evidence:000002"], "contradictory_evidence_ids": [], "limitation": "A leitura RMS é parcial.", "status": "supported"}], "evidence_references": ["trace_8:evidence:000001", "trace_8:evidence:000002"], "limitations": ["Evidência RMS parcial."], "trace_id": "trace_8"}
    reporter = ReporterLLMBoundary(FakeLLMProvider([response("reporter_8", report_payload)]), lambda _: request("reporter_8", "reporter"))
    graph = build_investigation_graph(InvestigationGraphDependencies(runtime=runtime, understanding=lambda _: example_understanding(), investigator=investigator, tool_executor=TrackedToolExecutor(client, runtime.trace, runtime.evidence_ledger), planner=planner, conclusion_builder=conclusion, reporter=reporter))
    state = graph.invoke({"state": runtime.state})["state"]
    assert state.phase is InvestigationPhase.READY_FOR_RESPONSE
    assert state.plan is not None and state.planner_source.value == "fake_llm"
    assert state.tool_call_count == 2 and len(state.evidence_ledger.records) == 2
    assert state.conclusion is not None and state.technical_report is not None
    assert state.technical_report.audience == "tractian_engineering_team"
