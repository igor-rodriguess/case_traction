"""Estado operacional, pequeno e serializável, de uma investigação.

O state não é histórico de raciocínio. Trace e Evidence Ledger permanecem as
fontes de verdade dos eventos e evidências; o state contém snapshots tipados
dessas estruturas para checkpoint, replay e handoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput
from app.observability import EvidenceLedger, EvidenceRecord, ExecutionTrace, TraceEvent, TraceEventType
from app.tools import get_investigator_tools


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
ReasonCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

DEFAULT_MAX_INVESTIGATION_STEPS = 12
DEFAULT_MAX_TOOL_CALLS = 8

_READ_TOOL_NAMES = frozenset(tool.name for tool in get_investigator_tools())
_FORBIDDEN_STATE_FIELD_NAMES = frozenset(
    {"reasoning", "thoughts", "internal_reasoning", "chain_of_thought", "scratchpad", "internal_monologue"}
)


class StateModel(BaseModel):
    """Base estrita e imutável dos contratos transportados pelo state."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InvestigationPhase(str, Enum):
    RECEIVED = "received"
    UNDERSTANDING_COMPLETE = "understanding_complete"
    INVESTIGATING = "investigating"
    AWAITING_USER = "awaiting_user"
    READY_FOR_RESPONSE = "ready_for_response"
    HUMAN_REQUIRED = "human_required"
    COMPLETED = "completed"
    FAILED = "failed"


class InvestigationDecisionType(str, Enum):
    CONTINUE = "continue"
    TOOL_CALL = "tool_call"
    ASK_USER = "ask_user"
    ANSWER = "answer"
    ESCALATE = "escalate"


class UnderstandingSource(str, Enum):
    MODEL = "model"
    TEST_FIXTURE = "test_fixture"


class InvestigationErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    UNDERSTANDING_UNAVAILABLE = "understanding_unavailable"
    TOOL_EXECUTION_FAILURE = "tool_execution_failure"
    ORCHESTRATION_FAILURE = "orchestration_failure"


class ToolRequest(StateModel):
    """Decisão estruturada de chamar uma READ tool; não executa nada."""

    tool_name: Identifier
    arguments: dict[str, JsonValue]

    @field_validator("tool_name")
    @classmethod
    def require_investigator_read_tool(cls, value: str) -> str:
        if value not in _READ_TOOL_NAMES:
            raise ValueError("tool_name deve identificar uma READ tool autorizada ao Investigator.")
        return value


class InvestigationDecision(StateModel):
    """Decisão observável futura do Investigator, separada da fase."""

    decision_id: Identifier
    type: InvestigationDecisionType
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)
    tool_request: ToolRequest | None = None
    required_information: tuple[Identifier, ...] = ()
    supporting_evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_shape_for_type(self) -> "InvestigationDecision":
        if self.type is InvestigationDecisionType.TOOL_CALL and self.tool_request is None:
            raise ValueError("Decisão TOOL_CALL exige tool_request.")
        if self.type is not InvestigationDecisionType.TOOL_CALL and self.tool_request is not None:
            raise ValueError("tool_request só é permitido em decisão TOOL_CALL.")
        if self.type is InvestigationDecisionType.ASK_USER and not self.required_information:
            raise ValueError("Decisão ASK_USER exige required_information.")
        if self.type is not InvestigationDecisionType.ASK_USER and self.required_information:
            raise ValueError("required_information só é permitido em decisão ASK_USER.")
        return self


class FinalResponse(StateModel):
    """Placeholder estruturado; texto futuro será produzido pelo Reporter LLM."""

    response_id: Identifier
    text: str = Field(min_length=1, max_length=20_000)
    claim_ids: tuple[Identifier, ...] = ()
    supporting_evidence_ids: tuple[Identifier, ...] = ()


class HumanHandoff(StateModel):
    """Contexto mínimo para futura entrega humana, sem executar o handoff."""

    handoff_id: Identifier
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = ()
    missing_information: tuple[Identifier, ...] = ()
    suggested_next_step: str | None = Field(default=None, max_length=1000)


class InvestigationError(StateModel):
    """Erro operacional corrente; detalhes de debugging permanecem no Trace."""

    code: InvestigationErrorCode
    can_continue: bool
    summary: str = Field(min_length=1, max_length=500)


class TraceSnapshot(StateModel):
    trace_id: Identifier
    events: tuple[TraceEvent, ...] = ()

    @model_validator(mode="after")
    def validate_trace_membership(self) -> "TraceSnapshot":
        if any(event.trace_id != self.trace_id for event in self.events):
            raise ValueError("Todos os eventos devem pertencer ao trace_id do snapshot.")
        if [event.sequence for event in self.events] != list(range(1, len(self.events) + 1)):
            raise ValueError("Sequências do Trace devem ser cronológicas e contíguas.")
        return self

    @classmethod
    def from_trace(cls, trace: ExecutionTrace) -> "TraceSnapshot":
        return cls(trace_id=trace.trace_id, events=trace.events)


class EvidenceLedgerSnapshot(StateModel):
    trace_id: Identifier
    records: tuple[EvidenceRecord, ...] = ()

    @model_validator(mode="after")
    def validate_ledger_membership(self) -> "EvidenceLedgerSnapshot":
        if any(record.trace_id != self.trace_id for record in self.records):
            raise ValueError("Todas as evidências devem pertencer ao trace_id do snapshot.")
        if [record.sequence for record in self.records] != list(range(1, len(self.records) + 1)):
            raise ValueError("Sequências do Evidence Ledger devem ser cronológicas e contíguas.")
        return self

    @classmethod
    def from_ledger(cls, ledger: EvidenceLedger) -> "EvidenceLedgerSnapshot":
        return cls(trace_id=ledger.trace_id, records=ledger.records)


class InvestigationState(StateModel):
    """Situação operacional atual de um caso, pronta para checkpoint JSON."""

    case_id: Identifier
    request_id: Identifier
    trace_id: Identifier
    request: UnderstandingInput
    understanding: UnderstandingOutput | None = None
    understanding_source: UnderstandingSource | None = None
    phase: InvestigationPhase = InvestigationPhase.RECEIVED
    decision: InvestigationDecision | None = None
    investigation_step_count: int = Field(default=0, ge=0)
    max_investigation_steps: int = Field(default=DEFAULT_MAX_INVESTIGATION_STEPS, ge=1)
    tool_call_count: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=DEFAULT_MAX_TOOL_CALLS, ge=1)
    trace: TraceSnapshot
    evidence_ledger: EvidenceLedgerSnapshot
    final_response: FinalResponse | None = None
    human_handoff: HumanHandoff | None = None
    error: InvestigationError | None = None

    @model_validator(mode="after")
    def validate_invariants(self) -> "InvestigationState":
        if self.trace.trace_id != self.trace_id or self.evidence_ledger.trace_id != self.trace_id:
            raise ValueError("State, Trace e Evidence Ledger devem compartilhar o trace_id.")
        if (self.understanding is None) != (self.understanding_source is None):
            raise ValueError("understanding e understanding_source devem ser definidos juntos.")
        if self.investigation_step_count > self.max_investigation_steps:
            raise ValueError("investigation_step_count excede max_investigation_steps.")
        if self.tool_call_count > self.max_tool_calls:
            raise ValueError("tool_call_count excede max_tool_calls.")

        phases_requiring_understanding = {
            InvestigationPhase.UNDERSTANDING_COMPLETE,
            InvestigationPhase.INVESTIGATING,
            InvestigationPhase.AWAITING_USER,
            InvestigationPhase.READY_FOR_RESPONSE,
            InvestigationPhase.HUMAN_REQUIRED,
            InvestigationPhase.COMPLETED,
        }
        if self.phase in phases_requiring_understanding and self.understanding is None:
            raise ValueError("A fase atual exige understanding anexado.")
        if self.phase is InvestigationPhase.RECEIVED and self.understanding is not None:
            raise ValueError("RECEIVED não pode conter understanding.")
        if self.phase is InvestigationPhase.COMPLETED and self.final_response is None:
            raise ValueError("COMPLETED exige final_response.")
        if self.phase is not InvestigationPhase.COMPLETED and self.final_response is not None:
            raise ValueError("final_response só é permitido em COMPLETED.")
        if self.phase is not InvestigationPhase.HUMAN_REQUIRED and self.human_handoff is not None:
            raise ValueError("human_handoff só é permitido em HUMAN_REQUIRED.")
        if self.phase is InvestigationPhase.FAILED and self.error is None:
            raise ValueError("FAILED exige error.")
        if self.phase is not InvestigationPhase.FAILED and self.error is not None:
            raise ValueError("error só é permitido em FAILED.")

        terminal_events = {
            (event.call_id, event.sequence)
            for event in self.trace.events
            if event.event_type is TraceEventType.TOOL_COMPLETED
        }
        for record in self.evidence_ledger.records:
            if (record.source_call_id, record.source_trace_sequence) not in terminal_events:
                raise ValueError("EvidenceRecord não aponta para um TOOL_COMPLETED do Trace.")
        terminal_call_count = len(
            {
                event.call_id
                for event in self.trace.events
                if event.event_type in {TraceEventType.TOOL_COMPLETED, TraceEventType.TOOL_FAILED}
            }
        )
        if self.tool_call_count != terminal_call_count:
            raise ValueError("tool_call_count deve refletir chamadas concluídas ou falhas no Trace.")
        return self


@dataclass(slots=True)
class InvestigationRuntime:
    """Recursos vivos fora do objeto checkpointável carregado pelo LangGraph."""

    state: InvestigationState
    trace: ExecutionTrace
    evidence_ledger: EvidenceLedger


class StateTransitionError(ValueError):
    """A fase atual não permite a transição solicitada."""


class LoopLimitExceeded(StateTransitionError):
    """Um limite determinístico do loop foi atingido."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _replace_state(state: InvestigationState, **changes: object) -> InvestigationState:
    payload = state.model_dump(mode="python")
    payload.update(changes)
    return InvestigationState.model_validate(payload)


def create_investigation_state(
    request: UnderstandingInput,
    *,
    case_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    trace: ExecutionTrace | None = None,
    evidence_ledger: EvidenceLedger | None = None,
    max_investigation_steps: int = DEFAULT_MAX_INVESTIGATION_STEPS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> InvestigationRuntime:
    """Única factory segura para state e recursos observáveis correlacionados."""

    resolved_trace_id = trace_id or (trace.trace_id if trace is not None else _new_id("trace"))
    resolved_trace = trace or ExecutionTrace(resolved_trace_id)
    resolved_ledger = evidence_ledger or EvidenceLedger(resolved_trace_id)
    if resolved_trace.trace_id != resolved_trace_id or resolved_ledger.trace_id != resolved_trace_id:
        raise ValueError("trace_id explícito, Trace e Evidence Ledger devem coincidir.")

    state = InvestigationState(
        case_id=case_id or _new_id("case"),
        request_id=request_id or _new_id("request"),
        trace_id=resolved_trace_id,
        request=request,
        max_investigation_steps=max_investigation_steps,
        max_tool_calls=max_tool_calls,
        trace=TraceSnapshot.from_trace(resolved_trace),
        evidence_ledger=EvidenceLedgerSnapshot.from_ledger(resolved_ledger),
    )
    return InvestigationRuntime(state=state, trace=resolved_trace, evidence_ledger=resolved_ledger)


def attach_understanding(
    state: InvestigationState,
    understanding: UnderstandingOutput,
    *,
    source: UnderstandingSource,
) -> InvestigationState:
    if state.phase is not InvestigationPhase.RECEIVED or state.understanding is not None:
        raise StateTransitionError("Understanding só pode ser anexado uma vez na fase RECEIVED.")
    return _replace_state(
        state,
        understanding=understanding,
        understanding_source=source,
        phase=InvestigationPhase.UNDERSTANDING_COMPLETE,
    )


def begin_investigation(state: InvestigationState) -> InvestigationState:
    if state.phase is not InvestigationPhase.UNDERSTANDING_COMPLETE:
        raise StateTransitionError("Investigação exige UNDERSTANDING_COMPLETE.")
    return _replace_state(state, phase=InvestigationPhase.INVESTIGATING)


def record_decision(
    state: InvestigationState,
    decision: InvestigationDecision,
) -> InvestigationState:
    if state.phase is not InvestigationPhase.INVESTIGATING:
        raise StateTransitionError("Decisões só podem ser registradas durante INVESTIGATING.")
    if state.investigation_step_count >= state.max_investigation_steps:
        raise LoopLimitExceeded("Limite de passos de investigação atingido.")
    if (
        decision.type is InvestigationDecisionType.TOOL_CALL
        and state.tool_call_count >= state.max_tool_calls
    ):
        raise LoopLimitExceeded("Limite de chamadas de tool atingido.")

    known_evidence_ids = {record.evidence_id for record in state.evidence_ledger.records}
    unknown = set(decision.supporting_evidence_ids) - known_evidence_ids
    if unknown:
        raise ValueError(f"Decisão referencia evidence_ids desconhecidos: {sorted(unknown)}")

    next_phase = {
        InvestigationDecisionType.CONTINUE: InvestigationPhase.INVESTIGATING,
        InvestigationDecisionType.TOOL_CALL: InvestigationPhase.INVESTIGATING,
        InvestigationDecisionType.ASK_USER: InvestigationPhase.AWAITING_USER,
        InvestigationDecisionType.ANSWER: InvestigationPhase.READY_FOR_RESPONSE,
        InvestigationDecisionType.ESCALATE: InvestigationPhase.HUMAN_REQUIRED,
    }[decision.type]
    return _replace_state(
        state,
        decision=decision,
        phase=next_phase,
        investigation_step_count=state.investigation_step_count + 1,
    )


def synchronize_observability(
    state: InvestigationState,
    trace: ExecutionTrace,
    evidence_ledger: EvidenceLedger,
) -> InvestigationState:
    """Atualiza snapshots após o executor; não decide nem executa tools."""

    if trace.trace_id != state.trace_id or evidence_ledger.trace_id != state.trace_id:
        raise ValueError("Recursos observáveis pertencem a outro trace_id.")
    terminal_call_ids = {
        event.call_id
        for event in trace.events
        if event.event_type in {TraceEventType.TOOL_COMPLETED, TraceEventType.TOOL_FAILED}
    }
    if len(terminal_call_ids) > state.max_tool_calls:
        raise LoopLimitExceeded("Trace excede max_tool_calls.")
    return _replace_state(
        state,
        tool_call_count=len(terminal_call_ids),
        trace=TraceSnapshot.from_trace(trace),
        evidence_ledger=EvidenceLedgerSnapshot.from_ledger(evidence_ledger),
    )


def attach_final_response(state: InvestigationState, response: FinalResponse) -> InvestigationState:
    if state.phase is not InvestigationPhase.READY_FOR_RESPONSE or state.final_response is not None:
        raise StateTransitionError("Resposta final exige READY_FOR_RESPONSE e só pode ser anexada uma vez.")
    known_evidence_ids = {record.evidence_id for record in state.evidence_ledger.records}
    if set(response.supporting_evidence_ids) - known_evidence_ids:
        raise ValueError("Resposta final referencia evidence_ids desconhecidos.")
    return _replace_state(state, final_response=response, phase=InvestigationPhase.COMPLETED)


def attach_human_handoff(state: InvestigationState, handoff: HumanHandoff) -> InvestigationState:
    if state.phase is not InvestigationPhase.HUMAN_REQUIRED or state.human_handoff is not None:
        raise StateTransitionError("Handoff exige HUMAN_REQUIRED e só pode ser anexado uma vez.")
    known_evidence_ids = {record.evidence_id for record in state.evidence_ledger.records}
    if set(handoff.evidence_ids) - known_evidence_ids:
        raise ValueError("Handoff referencia evidence_ids desconhecidos.")
    return _replace_state(state, human_handoff=handoff)


def mark_failed(state: InvestigationState, error: InvestigationError) -> InvestigationState:
    if state.phase in {InvestigationPhase.COMPLETED, InvestigationPhase.FAILED}:
        raise StateTransitionError("State terminal não pode ser marcado como FAILED novamente.")
    return _replace_state(state, error=error, phase=InvestigationPhase.FAILED)


def forbidden_state_field_names() -> frozenset[str]:
    """Exposto apenas para testes arquiteturais contra chain-of-thought."""

    return _FORBIDDEN_STATE_FIELD_NAMES
