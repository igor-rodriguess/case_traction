"""Esqueleto LangGraph para uma investigação, sem agentes ou LLMs reais.

``InvestigationState`` é o contrato canônico. ``GraphEnvelope`` abaixo é apenas
o adaptador mínimo exigido pelo LangGraph: transporta uma única chave, ``state``,
e não introduz campos de domínio paralelos.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput
from app.intelligence import CapabilityReference, EvidenceSummary, InvestigationConclusion, PlannerInput, PlannerOutput, ReporterInput, ReporterOutput, TraceSummary
from app.integrations.tractian_client import ClientResult
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    InvestigationError,
    InvestigationErrorCode,
    InvestigationPhase,
    InvestigationRuntime,
    InvestigationState,
    LLMArtifactSource,
    LoopLimitExceeded,
    StateTransitionError,
    UnderstandingSource,
    attach_understanding,
    attach_conclusion,
    attach_plan,
    attach_technical_report,
    begin_investigation,
    mark_failed,
    record_decision,
    synchronize_observability,
)
from app.observability import TrackedToolExecutor
from app.tools import get_investigator_tools


class UnderstandingBoundary(Protocol):
    """Porta futura do Understanding Agent, independente de provider."""

    def __call__(self, request: UnderstandingInput) -> UnderstandingOutput: ...


class InvestigatorBoundary(Protocol):
    """Porta futura do Investigator Agent; recebe state e retorna decisão tipada."""

    def __call__(self, state: InvestigationState) -> InvestigationDecision: ...


NodeObserver = Callable[[str, InvestigationState], None]


class GraphEnvelope(TypedDict):
    """Adapter de transporte LangGraph; a fonte da verdade continua no state."""

    state: InvestigationState


def _ignore_node(_: str, __: InvestigationState) -> None:
    return None


@dataclass(frozen=True, slots=True)
class InvestigationGraphDependencies:
    """Recursos em memória de uma execução, todos injetados explicitamente."""

    runtime: InvestigationRuntime
    understanding: UnderstandingBoundary
    investigator: InvestigatorBoundary
    tool_executor: TrackedToolExecutor
    node_observer: NodeObserver = _ignore_node
    planner: Callable[[PlannerInput], PlannerOutput] | None = None
    conclusion_builder: Callable[[InvestigationState], InvestigationConclusion] | None = None
    reporter: Callable[[ReporterInput], ReporterOutput] | None = None


def _error(code: InvestigationErrorCode, summary: str) -> InvestigationError:
    return InvestigationError(code=code, can_continue=False, summary=summary)


def _fail(state: InvestigationState, code: InvestigationErrorCode, summary: str) -> InvestigationState:
    if state.phase is InvestigationPhase.FAILED:
        return state
    try:
        return mark_failed(state, _error(code, summary))
    except StateTransitionError:
        return state


def build_investigation_graph(dependencies: InvestigationGraphDependencies):
    """Constrói o grafo síncrono e provider-agnostic da Etapa 06B.

    O grafo não recebe checkpointer: trace, ledger e executor são recursos vivos
    locais associados ao ``InvestigationRuntime`` desta execução. Persistência e
    resume serão adicionados somente com uma fronteira de checkpoint aprovada.
    """

    runtime = dependencies.runtime
    tool_registry = {tool.name: tool for tool in get_investigator_tools()}

    def summaries(state: InvestigationState) -> tuple[EvidenceSummary, TraceSummary]:
        records = state.evidence_ledger.records
        events = state.trace.events
        return (
            EvidenceSummary(
                evidence_ids=tuple(record.evidence_id for record in records),
                statuses=tuple(record.evidence_status.value for record in records),
                relevant_results=tuple({"evidence_id": record.evidence_id, "tool_name": record.tool_name, "data": record.data} for record in records[-3:]),
            ),
            TraceSummary(
                trace_id=state.trace_id,
                tool_call_count=state.tool_call_count,
                last_tool_name=events[-1].tool_name if events else None,
                last_call_id=events[-1].call_id if events else None,
            ),
        )

    def observed(name: str, state: InvestigationState) -> dict[str, InvestigationState]:
        dependencies.node_observer(name, state)
        return {"state": state}

    def entry(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        if not isinstance(state, InvestigationState):
            # LangGraph normalmente entrega o objeto Pydantic, mas esta proteção
            # mantém a falha explícita para callers que violarem o adapter.
            raise TypeError("GraphEnvelope exige InvestigationState canônico.")
        if state.phase is not InvestigationPhase.RECEIVED:
            return observed(
                "entry",
                _fail(state, InvestigationErrorCode.VALIDATION_ERROR, "Estado inicial deve estar em RECEIVED."),
            )
        if (
            state.trace_id != runtime.trace.trace_id
            or state.trace_id != runtime.evidence_ledger.trace_id
            or state.trace_id != runtime.state.trace_id
        ):
            return observed(
                "entry",
                _fail(state, InvestigationErrorCode.VALIDATION_ERROR, "Recursos de runtime pertencem a outro trace."),
            )
        return observed("entry", state)

    def understanding_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        try:
            updated = attach_understanding(
                state, dependencies.understanding(state.request), source=UnderstandingSource.TEST_FIXTURE
            )
        except Exception:
            updated = _fail(
                state,
                InvestigationErrorCode.UNDERSTANDING_UNAVAILABLE,
                "Understanding boundary indisponível para esta execução.",
            )
        return observed("understanding_boundary", updated)

    def investigation_entry(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        try:
            if state.phase is InvestigationPhase.UNDERSTANDING_COMPLETE:
                updated = begin_investigation(state)
            elif state.phase is InvestigationPhase.INVESTIGATING:
                if state.investigation_step_count >= state.max_investigation_steps:
                    raise LoopLimitExceeded("Limite de passos de investigação atingido.")
                updated = state
            else:
                raise StateTransitionError("Investigation entry exige understanding ou investigação ativa.")
        except LoopLimitExceeded:
            updated = _fail(
                state, InvestigationErrorCode.ORCHESTRATION_FAILURE, "Limite de passos de investigação atingido."
            )
        except StateTransitionError:
            updated = _fail(
                state, InvestigationErrorCode.VALIDATION_ERROR, "Transição inválida para investigation entry."
            )
        return observed("investigation_entry", updated)

    def planner_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        if dependencies.planner is None:
            return observed("planner_boundary", state)
        try:
            assert state.understanding is not None
            value = PlannerInput(
                understanding=state.understanding,
                available_capabilities=tuple(CapabilityReference(name=name) for name in tool_registry),
                max_investigation_steps=state.max_investigation_steps,
                max_tool_calls=state.max_tool_calls,
            )
            updated = attach_plan(state, dependencies.planner(value), source=LLMArtifactSource.FAKE_LLM)
        except Exception:
            updated = _fail(state, InvestigationErrorCode.ORCHESTRATION_FAILURE, "Planner boundary retornou plano inválido.")
        return observed("planner_boundary", updated)

    def investigator_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        try:
            updated = record_decision(state, dependencies.investigator(state))
        except LoopLimitExceeded:
            updated = _fail(
                state, InvestigationErrorCode.ORCHESTRATION_FAILURE, "Limite estrutural da investigação atingido."
            )
        except Exception:
            updated = _fail(
                state,
                InvestigationErrorCode.ORCHESTRATION_FAILURE,
                "Investigator boundary retornou decisão inválida.",
            )
        return observed("investigator_boundary", updated)

    def decision_router(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        return observed("decision_router", envelope["state"])

    def tool_executor(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        decision = state.decision
        if decision is None or decision.type is not InvestigationDecisionType.TOOL_CALL:
            return observed(
                "tool_executor",
                _fail(state, InvestigationErrorCode.VALIDATION_ERROR, "TOOL_CALL exige decisão e ToolRequest válidas."),
            )
        request = decision.tool_request
        if request is None or request.tool_name not in tool_registry:
            return observed(
                "tool_executor",
                _fail(state, InvestigationErrorCode.VALIDATION_ERROR, "Tool solicitada não é uma READ tool autorizada."),
            )
        try:
            result: ClientResult = dependencies.tool_executor.execute(
                tool_registry[request.tool_name], request.arguments
            )
            updated = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            if not result.transport_ok:
                updated = _fail(
                    updated,
                    InvestigationErrorCode.TOOL_EXECUTION_FAILURE,
                    "Falha de transporte ao executar a READ tool.",
                )
        except Exception:
            # O executor já registrou TOOL_FAILED quando a exceção veio da tool.
            try:
                updated = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            except Exception:
                updated = state
            updated = _fail(
                updated,
                InvestigationErrorCode.TOOL_EXECUTION_FAILURE,
                "Falha inesperada ao executar a READ tool.",
            )
        return observed("tool_executor", updated)

    def ask_user_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        return observed("ask_user_boundary", envelope["state"])

    def answer_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        return observed("answer_boundary", envelope["state"])

    def conclusion_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        if dependencies.conclusion_builder is None:
            return observed("conclusion_boundary", state)
        try:
            updated = attach_conclusion(state, dependencies.conclusion_builder(state))
        except Exception:
            updated = _fail(state, InvestigationErrorCode.ORCHESTRATION_FAILURE, "Conclusion boundary retornou conclusão inválida.")
        return observed("conclusion_boundary", updated)

    def reporter_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        state = envelope["state"]
        if dependencies.reporter is None:
            return observed("reporter_boundary", state)
        try:
            assert state.understanding is not None and state.plan is not None and state.conclusion is not None
            evidence, trace = summaries(state)
            updated = attach_technical_report(
                state,
                dependencies.reporter(ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=state.understanding, plan=state.plan, conclusion=state.conclusion, evidence=evidence, trace=trace)),
                source=LLMArtifactSource.FAKE_LLM,
            )
        except Exception:
            updated = _fail(state, InvestigationErrorCode.ORCHESTRATION_FAILURE, "Reporter boundary retornou relatório inválido.")
        return observed("reporter_boundary", updated)

    def escalate_boundary(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        return observed("escalate_boundary", envelope["state"])

    def failed(envelope: GraphEnvelope) -> dict[str, InvestigationState]:
        return observed("failed", envelope["state"])

    def after_nonterminal(envelope: GraphEnvelope) -> Literal["understanding_boundary", "failed"]:
        return "failed" if envelope["state"].phase is InvestigationPhase.FAILED else "understanding_boundary"

    def after_investigation_entry(envelope: GraphEnvelope) -> Literal["investigator_boundary", "failed"]:
        return "failed" if envelope["state"].phase is InvestigationPhase.FAILED else "investigator_boundary"

    def after_understanding(envelope: GraphEnvelope) -> Literal["planner_boundary", "investigation_entry", "failed"]:
        if envelope["state"].phase is InvestigationPhase.FAILED:
            return "failed"
        return "planner_boundary" if dependencies.planner is not None else "investigation_entry"

    def after_planner(envelope: GraphEnvelope) -> Literal["investigation_entry", "failed"]:
        return "failed" if envelope["state"].phase is InvestigationPhase.FAILED else "investigation_entry"

    def after_investigator(envelope: GraphEnvelope) -> Literal["decision_router", "failed"]:
        return "failed" if envelope["state"].phase is InvestigationPhase.FAILED else "decision_router"

    def route_decision(
        envelope: GraphEnvelope,
    ) -> Literal["investigation_entry", "tool_executor", "ask_user_boundary", "answer_boundary", "escalate_boundary", "failed"]:
        state = envelope["state"]
        if state.phase is InvestigationPhase.FAILED or state.decision is None:
            return "failed"
        return {
            InvestigationDecisionType.CONTINUE: "investigation_entry",
            InvestigationDecisionType.TOOL_CALL: "tool_executor",
            InvestigationDecisionType.ASK_USER: "ask_user_boundary",
            InvestigationDecisionType.ANSWER: "answer_boundary",
            InvestigationDecisionType.ESCALATE: "escalate_boundary",
        }[state.decision.type]

    def after_tool(envelope: GraphEnvelope) -> Literal["investigation_entry", "failed"]:
        return "failed" if envelope["state"].phase is InvestigationPhase.FAILED else "investigation_entry"

    def after_answer(envelope: GraphEnvelope) -> Literal["conclusion_boundary", "failed", "end"]:
        if envelope["state"].phase is InvestigationPhase.FAILED:
            return "failed"
        return "conclusion_boundary" if dependencies.conclusion_builder is not None else "end"

    def after_conclusion(envelope: GraphEnvelope) -> Literal["reporter_boundary", "failed", "end"]:
        if envelope["state"].phase is InvestigationPhase.FAILED:
            return "failed"
        return "reporter_boundary" if dependencies.reporter is not None else "end"

    graph = StateGraph(GraphEnvelope)
    graph.add_node("entry", entry)
    graph.add_node("understanding_boundary", understanding_boundary)
    graph.add_node("planner_boundary", planner_boundary)
    graph.add_node("investigation_entry", investigation_entry)
    graph.add_node("investigator_boundary", investigator_boundary)
    graph.add_node("decision_router", decision_router)
    graph.add_node("tool_executor", tool_executor)
    graph.add_node("ask_user_boundary", ask_user_boundary)
    graph.add_node("answer_boundary", answer_boundary)
    graph.add_node("conclusion_boundary", conclusion_boundary)
    graph.add_node("reporter_boundary", reporter_boundary)
    graph.add_node("escalate_boundary", escalate_boundary)
    graph.add_node("failed", failed)
    graph.add_edge(START, "entry")
    graph.add_conditional_edges("entry", after_nonterminal)
    graph.add_conditional_edges("understanding_boundary", after_understanding)
    graph.add_conditional_edges("planner_boundary", after_planner)
    graph.add_conditional_edges("investigation_entry", after_investigation_entry)
    graph.add_conditional_edges("investigator_boundary", after_investigator)
    graph.add_conditional_edges("decision_router", route_decision)
    graph.add_conditional_edges("tool_executor", after_tool)
    graph.add_edge("ask_user_boundary", END)
    graph.add_conditional_edges("answer_boundary", after_answer, {"conclusion_boundary": "conclusion_boundary", "failed": "failed", "end": END})
    graph.add_conditional_edges("conclusion_boundary", after_conclusion, {"reporter_boundary": "reporter_boundary", "failed": "failed", "end": END})
    graph.add_edge("reporter_boundary", END)
    graph.add_edge("escalate_boundary", END)
    graph.add_edge("failed", END)
    return graph.compile()
