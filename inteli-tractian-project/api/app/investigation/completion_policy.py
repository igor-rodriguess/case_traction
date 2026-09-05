"""Política determinística de terminalidade da investigação.

Não decide conteúdo técnico e não chama LLM. Ela valida uma decisão proposta
contra evidências, limites e histórico observável, podendo substituí-la apenas
por ESCALATE quando prosseguir ou responder seria inseguro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.tractian_client import EvidenceStatus
from app.investigation.state import (
    InvestigationDecision,
    InvestigationDecisionType,
    InvestigationState,
)


@dataclass(frozen=True, slots=True)
class CompletionAssessment:
    decision: InvestigationDecision
    accepted: bool
    reason_code: str
    rejected_decision_type: InvestigationDecisionType | None = None


def _escalation(proposed: InvestigationDecision, reason_code: str) -> CompletionAssessment:
    replacement = InvestigationDecision(
        decision_id=f"{proposed.decision_id}_safe_escalation",
        type=InvestigationDecisionType.ESCALATE,
        reason_codes=(reason_code,),
        supporting_evidence_ids=proposed.supporting_evidence_ids,
    )
    return CompletionAssessment(
        decision=replacement,
        accepted=False,
        reason_code=reason_code,
        rejected_decision_type=proposed.type,
    )


def assess_completion_decision(
    state: InvestigationState,
    proposed: InvestigationDecision,
) -> CompletionAssessment:
    """Valida terminalidade e repetição usando somente estado estruturado."""

    records = state.evidence_ledger.records
    evidence_by_id = {record.evidence_id: record for record in records}
    used_tools = {
        event.tool_name
        for event in state.trace.events
        if event.result is not None
    }
    planned_tools = {item.name for item in state.plan.suggested_capabilities} if state.plan else set()
    useful_untried = planned_tools - used_tools

    if proposed.type is InvestigationDecisionType.ANSWER:
        referenced = set(proposed.supporting_evidence_ids)
        if not referenced or not referenced <= set(evidence_by_id):
            return _escalation(proposed, "ANSWER_REQUIRES_KNOWN_EVIDENCE")
        statuses = {evidence_by_id[item].evidence_status for item in referenced}
        if statuses & {EvidenceStatus.CONFLICT, EvidenceStatus.UNAVAILABLE, EvidenceStatus.INCONCLUSIVE}:
            return _escalation(proposed, "ANSWER_EVIDENCE_NOT_SUFFICIENT")
        return CompletionAssessment(proposed, True, "GROUNDED_ANSWER_ALLOWED")

    at_step_limit = state.investigation_step_count + 1 >= state.max_investigation_steps
    at_tool_limit = state.tool_call_count >= state.max_tool_calls
    if proposed.type in {InvestigationDecisionType.CONTINUE, InvestigationDecisionType.TOOL_CALL}:
        if at_step_limit or (proposed.type is InvestigationDecisionType.TOOL_CALL and at_tool_limit):
            return _escalation(proposed, "UNGROUNDED_LIMIT_REACHED")

    if proposed.type is InvestigationDecisionType.TOOL_CALL:
        request = proposed.tool_request
        assert request is not None
        for event in state.trace.events:
            if event.result is not None and event.tool_name == request.tool_name and event.arguments == request.arguments:
                return _escalation(proposed, "REPEATED_TOOL_CALL_WITHOUT_NEW_EVIDENCE")
        return CompletionAssessment(proposed, True, "USEFUL_READ_TOOL_ALLOWED")

    if proposed.type is InvestigationDecisionType.CONTINUE and not useful_untried:
        return _escalation(proposed, "NO_USEFUL_READ_TOOL_REMAINING")

    if proposed.type is InvestigationDecisionType.ASK_USER:
        return CompletionAssessment(proposed, True, "EXTERNAL_INFORMATION_REQUIRED")
    if proposed.type is InvestigationDecisionType.ESCALATE:
        return CompletionAssessment(proposed, True, "SAFE_ESCALATION_ACCEPTED")
    return CompletionAssessment(proposed, True, "CONTINUATION_ALLOWED")
