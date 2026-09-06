"""Provas offline do caminho Evidence → Conclusion → Reporter."""

from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind
from app.intelligence import Claim, PlannerOutput, ReporterInput, ReporterOutput
from app.intelligence.grounding import build_claim_lineage, build_grounded_conclusion, validate_reporter_output
from app.investigation import InvestigationDecision, InvestigationDecisionType, LLMArtifactSource, UnderstandingSource, attach_plan, attach_understanding, begin_investigation, create_investigation_state, record_decision, synchronize_observability
from app.observability import RunTiming, TraceEvent, TraceEventType, TrackedToolExecutor
from app.tools import get_investigator_tools
from scripts.generate_investigation_state_example import example_request, example_understanding
from scripts.run_e2e_dev_pilot import _summaries


class AnalysisClient:
    def get_analysis(self, analysis_id: str) -> ClientResult:
        return ClientResult(
            "get_analysis", OperationKind.READ, "GET", f"/analyses/{analysis_id}", True, 200, EvidenceStatus.COMPLETE,
            {"id": analysis_id, "asset_id": "asset_S425", "type": "none", "severity": "none", "confidence": 0.95, "status": "current", "limitations": []},
        )


class AssetClient:
    def get_asset(self, asset_id: str) -> ClientResult:
        return ClientResult("get_asset", OperationKind.READ, "GET", f"/assets/{asset_id}", True, 200, EvidenceStatus.COMPLETE, {"id": asset_id, "name": "Spindle secundário", "machine_type": "spindle", "criticality": "medium", "sensor_status": "online"})


def grounded_state():
    runtime = create_investigation_state(example_request(), case_id="integration_positive", trace_id="trace_positive")
    plan = PlannerOutput(plan_id="plan_positive", objectives=("Verificar análise atual.",), investigation_questions=("Qual é a condição registrada?",), suggested_capabilities=tuple(item for item in ({"name": "get_analysis_details"},)), stopping_conditions=("Análise atual encontrada.",), reason_codes=("POSITIVE_FIXTURE",))
    state = attach_understanding(runtime.state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE)
    state = begin_investigation(attach_plan(state, plan, source=LLMArtifactSource.FAKE_LLM))
    tool = next(item for item in get_investigator_tools() if item.name == "get_analysis_details")
    TrackedToolExecutor(AnalysisClient(), runtime.trace, runtime.evidence_ledger).execute(tool, {"analysis_id": "an_9920"})  # type: ignore[arg-type]
    state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
    evidence_id = state.evidence_ledger.records[0].evidence_id
    state = record_decision(state, InvestigationDecision(decision_id="answer_positive", type=InvestigationDecisionType.ANSWER, reason_codes=("SUFFICIENT_ANALYSIS",), supporting_evidence_ids=(evidence_id,)))
    return runtime, state


def test_sufficient_evidence_builds_conclusion_and_valid_lineage() -> None:
    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state)
    lineage = build_claim_lineage(state, conclusion)
    assert len(conclusion.claims) == 1 and conclusion.claims[0].status.value == "supported"
    assert len(lineage) == 1 and lineage[0].valid and lineage[0].operation_kind is OperationKind.READ


def test_asset_context_can_ground_a_simple_factual_claim() -> None:
    runtime = create_investigation_state(example_request(), case_id="asset_positive", trace_id="trace_asset")
    state = attach_understanding(runtime.state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE)
    plan = PlannerOutput(plan_id="asset_plan", objectives=("Consultar cadastro.",), investigation_questions=("Qual é o cadastro?",), suggested_capabilities=({"name": "get_asset_context"},), stopping_conditions=("Cadastro obtido.",), reason_codes=("FACT_LOOKUP",))
    state = begin_investigation(attach_plan(state, plan, source=LLMArtifactSource.FAKE_LLM))
    tool = next(item for item in get_investigator_tools() if item.name == "get_asset_context")
    TrackedToolExecutor(AssetClient(), runtime.trace, runtime.evidence_ledger).execute(tool, {"asset_id": "asset_S425"})  # type: ignore[arg-type]
    state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
    evidence_id = state.evidence_ledger.records[0].evidence_id
    state = record_decision(state, InvestigationDecision(decision_id="asset_answer", type=InvestigationDecisionType.ANSWER, reason_codes=("FACT_FOUND",), supporting_evidence_ids=(evidence_id,)))
    conclusion = build_grounded_conclusion(state)
    assert "Spindle secundário" in conclusion.claims[0].statement


def test_reporter_preserves_claims_and_evidence() -> None:
    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state)
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    output = ReporterOutput(report_id="report_positive", case_id=state.case_id, executive_summary="Condição registrada na análise atual.", investigation_performed=("Consulta READ da análise.",), findings=(conclusion.claims[0].statement,), claims=conclusion.claims, evidence_references=conclusion.supporting_evidence_ids, limitations=conclusion.limitations, missing_information=conclusion.unresolved_points, trace_id=state.trace_id)
    result = validate_reporter_output(value, output)
    assert result.valid and result.claim_preservation_rate == result.evidence_reference_preservation_rate == 1


def test_reporter_added_claim_is_detected() -> None:
    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state)
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    invented = Claim(claim_id="invented", statement="Falha crítica inventada.", supporting_evidence_ids=conclusion.supporting_evidence_ids)
    output = ReporterOutput(report_id="bad", case_id=state.case_id, executive_summary="Inválido.", investigation_performed=("Consulta.",), findings=("Inválido.",), claims=(*conclusion.claims, invented), evidence_references=conclusion.supporting_evidence_ids, trace_id=state.trace_id)
    result = validate_reporter_output(value, output)
    assert not result.valid and result.unsupported_claim_rate > 0 and "UNSUPPORTED_CLAIM" in result.violations


def test_reporter_missing_conclusion_limitation_is_detected() -> None:
    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state).model_copy(update={"limitations": ("Escopo limitado ao cadastro atual.",)})
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    output = ReporterOutput(report_id="missing_limit", case_id=state.case_id, executive_summary="Resumo.", investigation_performed=("Consulta.",), findings=(conclusion.claims[0].statement,), claims=conclusion.claims, evidence_references=conclusion.supporting_evidence_ids, trace_id=state.trace_id)
    result = validate_reporter_output(value, output)
    assert not result.valid and "LIMITATION_NOT_PRESERVED" in result.violations


def test_trace_records_operational_decision_event_without_private_reasoning() -> None:
    runtime, _ = grounded_state()
    event = runtime.trace.append_operational(TraceEventType.DECISION_VALIDATED, "decision_001", details={"decision_type": "answer", "valid": True})
    assert event.event_type is TraceEventType.DECISION_VALIDATED
    assert event.details == {"decision_type": "answer", "valid": True}
    assert "reasoning" not in event.model_dump()


def test_run_timing_is_derived_from_timezone_aware_timestamps() -> None:
    started = datetime(2026, 9, 4, tzinfo=timezone.utc)
    timing = RunTiming.between(started, started + timedelta(milliseconds=1250))
    assert timing.duration_ms == 1250 and timing.finished_at > timing.started_at


def test_tool_trace_event_cannot_omit_operation_metadata() -> None:
    with pytest.raises(ValueError, match="metadados completos"):
        TraceEvent(trace_id="trace", call_id="call", sequence=1, event_type=TraceEventType.TOOL_STARTED, timestamp=datetime.now(timezone.utc))



def test_rewritten_claim_is_not_labelled_as_fabrication() -> None:
    """Achado da revisão final: o provider devolveu a mesma claim sem acentos.

    O relatório continua rejeitado — a validação não foi relaxada —, mas chamar
    reescrita de `UNSUPPORTED_CLAIM` sugeria invenção de fato onde não houve.
    """

    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state)
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    original = conclusion.claims[0]
    rewritten = original.model_copy(update={"statement": original.statement.replace("á", "a").replace("é", "e")})
    output = ReporterOutput(report_id="rewritten", case_id=state.case_id, executive_summary="Texto reescrito.", investigation_performed=("Consulta.",), findings=(rewritten.statement,), claims=(rewritten,), evidence_references=conclusion.supporting_evidence_ids, limitations=conclusion.limitations, missing_information=conclusion.unresolved_points, trace_id=state.trace_id)

    result = validate_reporter_output(value, output)

    assert result.valid is False, "relatório infiel continua rejeitado"
    assert result.altered_claims == 1
    assert result.fabricated_claims == 0
    assert "CLAIM_TEXT_ALTERED" in result.violations
    assert "UNSUPPORTED_CLAIM" not in result.violations


def test_a_claim_absent_from_the_conclusion_is_still_fabrication() -> None:
    _, state = grounded_state()
    conclusion = build_grounded_conclusion(state)
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    invented = Claim(claim_id="claim_inventada", statement="Fato que a conclusão nunca produziu.", supporting_evidence_ids=conclusion.supporting_evidence_ids)
    output = ReporterOutput(report_id="fabricated", case_id=state.case_id, executive_summary="Inválido.", investigation_performed=("Consulta.",), findings=("Inválido.",), claims=(*conclusion.claims, invented), evidence_references=conclusion.supporting_evidence_ids, trace_id=state.trace_id)

    result = validate_reporter_output(value, output)

    assert result.valid is False
    assert result.fabricated_claims == 1
    assert "UNSUPPORTED_CLAIM" in result.violations
