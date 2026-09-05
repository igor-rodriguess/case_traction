"""Guardas locais da Fase A 09.4; nenhum provider ou API é chamado."""

import pytest

from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind
from app.intelligence import Claim, InvestigationConclusion, PlannerOutput, ReporterInput
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    LLMArtifactSource,
    UnderstandingSource,
    assess_completion_decision,
    attach_conclusion,
    attach_plan,
    attach_understanding,
    begin_investigation,
    create_investigation_state,
    record_decision,
    synchronize_observability,
)
from app.observability import TrackedToolExecutor
from app.tools import get_investigator_tools
from app.agents.understanding.dataset import load_dev_split
from scripts.run_e2e_dev_pilot import PILOT_SIZE, ROUTING_VERSION, _conclusion, _summaries, select_pilot
from scripts.generate_investigation_state_example import example_request, example_understanding


class _Client:
    def __init__(self, status: EvidenceStatus) -> None:
        self.status = status

    def get_asset(self, asset_id: str) -> ClientResult:
        return ClientResult("get_asset", OperationKind.READ, "GET", f"/assets/{asset_id}", True, 200, self.status, {"id": asset_id})


def _state(status: EvidenceStatus | None = None, *, max_steps: int = 12):
    runtime = create_investigation_state(example_request(), trace_id="trace_policy", max_investigation_steps=max_steps)
    state = attach_understanding(runtime.state, example_understanding(), source=UnderstandingSource.TEST_FIXTURE)
    plan = PlannerOutput.model_validate({
        "plan_id": "plan_policy", "objectives": ["Verificar o ativo."],
        "investigation_questions": ["Há evidência suficiente?"],
        "suggested_capabilities": [{"name": "get_asset_context"}, {"name": "get_asset_rms"}],
        "stopping_conditions": ["Evidência suficiente ou escalonamento seguro."],
        "reason_codes": ["POLICY_TEST"],
    })
    state = begin_investigation(attach_plan(state, plan, source=LLMArtifactSource.FAKE_LLM))
    if status is not None:
        tool = next(item for item in get_investigator_tools() if item.name == "get_asset_context")
        TrackedToolExecutor(_Client(status), runtime.trace, runtime.evidence_ledger).execute(tool, {"asset_id": "asset_B211"})  # type: ignore[arg-type]
        state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
    return state


def _decision(kind: InvestigationDecisionType, **changes) -> InvestigationDecision:
    payload = {"decision_id": "decision_policy", "type": kind, "reason_codes": ["TEST"]}
    payload.update(changes)
    return InvestigationDecision.model_validate(payload)


def test_pilot_selection_is_deterministic_and_dev_only() -> None:
    first = select_pilot(load_dev_split())
    second = select_pilot(load_dev_split())

    assert len(first) == PILOT_SIZE
    assert [sample.sample_id for sample in first] == [sample.sample_id for sample in second]
    assert all(sample.split == "dev" and sample.sample_id.startswith("syn_u_dev_") for sample in first)
    assert ROUTING_VERSION == "MODEL_ROUTING_V4"


def test_completion_policy_allows_grounded_answer() -> None:
    state = _state(EvidenceStatus.COMPLETE)
    evidence_id = state.evidence_ledger.records[0].evidence_id
    result = assess_completion_decision(state, _decision(InvestigationDecisionType.ANSWER, supporting_evidence_ids=[evidence_id]))
    assert result.accepted and result.decision.type is InvestigationDecisionType.ANSWER


def test_completion_policy_continues_partial_when_useful_tool_remains() -> None:
    result = assess_completion_decision(_state(EvidenceStatus.PARTIAL), _decision(InvestigationDecisionType.CONTINUE))
    assert result.accepted and result.decision.type is InvestigationDecisionType.CONTINUE


def test_completion_policy_escalates_unavailable_or_conflict_without_safe_answer() -> None:
    for status in (EvidenceStatus.UNAVAILABLE, EvidenceStatus.CONFLICT):
        state = _state(status)
        evidence_id = state.evidence_ledger.records[0].evidence_id
        result = assess_completion_decision(state, _decision(InvestigationDecisionType.ANSWER, supporting_evidence_ids=[evidence_id]))
        assert not result.accepted and result.decision.type is InvestigationDecisionType.ESCALATE


def test_completion_policy_preserves_ask_user() -> None:
    result = assess_completion_decision(_state(), _decision(InvestigationDecisionType.ASK_USER, required_information=["asset_id"]))
    assert result.accepted and result.decision.type is InvestigationDecisionType.ASK_USER


def test_completion_policy_escalates_at_limit_without_grounding() -> None:
    result = assess_completion_decision(_state(max_steps=1), _decision(InvestigationDecisionType.CONTINUE))
    assert not result.accepted and result.reason_code == "UNGROUNDED_LIMIT_REACHED"


def test_completion_policy_rejects_answer_without_evidence() -> None:
    result = assess_completion_decision(_state(), _decision(InvestigationDecisionType.ANSWER))
    assert not result.accepted and result.reason_code == "ANSWER_REQUIRES_KNOWN_EVIDENCE"


def test_completion_policy_blocks_repeated_tool_call() -> None:
    state = _state(EvidenceStatus.COMPLETE)
    proposed = _decision(InvestigationDecisionType.TOOL_CALL, tool_request={"tool_name": "get_asset_context", "arguments": {"asset_id": "asset_B211"}})
    result = assess_completion_decision(state, proposed)
    assert not result.accepted and result.reason_code == "REPEATED_TOOL_CALL_WITHOUT_NEW_EVIDENCE"


def test_grounded_answer_builds_conclusion_and_reporter_handoff() -> None:
    state = _state(EvidenceStatus.COMPLETE)
    evidence_id = state.evidence_ledger.records[0].evidence_id
    state = record_decision(state, _decision(InvestigationDecisionType.ANSWER, supporting_evidence_ids=[evidence_id]))
    conclusion = _conclusion(state)
    evidence, trace = _summaries(state)
    value = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=conclusion, evidence=evidence, trace=trace)
    assert value.conclusion.claims[0].supporting_evidence_ids == (evidence_id,)
    assert value.evidence.evidence_ids == (evidence_id,)


def test_conclusion_rejects_unknown_evidence_reference() -> None:
    state = _state(EvidenceStatus.COMPLETE)
    evidence_id = state.evidence_ledger.records[0].evidence_id
    state = record_decision(state, _decision(InvestigationDecisionType.ANSWER, supporting_evidence_ids=[evidence_id]))
    invalid = InvestigationConclusion(
        conclusion_id="bad", claims=(Claim(claim_id="bad", statement="Sem proveniência válida.", supporting_evidence_ids=("unknown",)),),
        supporting_evidence_ids=("unknown",), reason_codes=("TEST",),
    )
    with pytest.raises(ValueError, match="evidence_ids desconhecidos"):
        attach_conclusion(state, invalid)
