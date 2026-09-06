"""Execução real do pipeline de investigação.

Reúne, num lugar só, a montagem que os scripts de experimento já provaram:
Understanding → Planner → Investigator → READ Tools → Trace + Evidence →
Completion Policy → Conclusion → Reporter.

O que muda em relação aos scripts é apenas quem observa: um `checkpoint` recebe
o estado a cada etapa determinística, e é ele quem persiste. Os agentes seguem
sem saber que existe banco.

Nenhuma decisão de investigação vive aqui. A escolha da ferramenta é do
Investigator, a aceitação é da Completion Policy, o veredicto é do Eval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from app.agents.understanding.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput
from app.intelligence import (
    CapabilityReference,
    Claim,
    ClaimStatus,
    EvidenceSummary,
    InvestigationConclusion,
    InvestigatorInput,
    PlannerInput,
    ReporterInput,
    TraceSummary,
)
from app.intelligence.boundaries import parse_planner_output, parse_reporter_output
from app.integrations.tractian_client import RequestContext, TractianClient
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    LLMArtifactSource,
    UnderstandingSource,
    assess_completion_decision,
    attach_conclusion,
    attach_plan,
    attach_technical_report,
    attach_understanding,
    begin_investigation,
    create_investigation_state,
    record_decision,
    synchronize_observability,
)
from app.investigation.state import HumanHandoff, InvestigationState
from app.llm import (
    LLMGenerationParameters,
    LLMMessage,
    LLMRequest,
    LLMResponseStatus,
    StructuredOutputMode,
)
from app.llm.investigator import (
    InvestigatorRecoveryAction,
    recovery_action,
    validate_investigation_decision,
)
from app.llm.real_providers import ProviderName
from app.observability import TrackedToolExecutor
from app.observability.models import TraceEventType
from app.tools import get_investigator_tools

Checkpoint = Callable[[str, InvestigationState], None]

INVESTIGATOR_PROMPT_VERSION = "console_investigator_v1"
INVESTIGATOR_SYSTEM_PROMPT = """Return only one JSON object matching InvestigationDecision exactly.
Allowed type values: continue, tool_call, ask_user, answer, escalate. Never emit ACTION.
Always include decision_id, type, non-empty reason_codes, tool_request, required_information, supporting_evidence_ids.
For tool_call, tool_request is required and must contain one permitted READ tool with schema-valid arguments.
For every non-tool_call decision, tool_request must be null.
For ask_user, required_information must be non-empty; for every other decision it must be empty.
For answer, cite only supporting_evidence_ids present in the input and only when existing evidence is sufficient.
Use ask_user for required external information; use escalate for exhausted, unavailable, inconclusive, or conflicting evidence.
Do not repeat a tool without new evidence. Do not add fields."""


class Provider(Protocol):
    def infer(self, request: LLMRequest) -> Any: ...


@dataclass
class PipelineResult:
    state: InvestigationState
    terminal_state: str
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    tool_calls_executed: int = 0


@dataclass
class PipelineConfig:
    """Provedores por papel. Espelha o roteamento já calibrado do projeto."""

    understanding: ProviderName = ProviderName.GROQ
    planner: ProviderName = ProviderName.GEMINI
    investigator: ProviderName = ProviderName.GEMINI
    reporter: ProviderName = ProviderName.GEMINI
    api_base_url: str = "http://127.0.0.1:8000"


def _request(
    role: str,
    messages: tuple[LLMMessage, ...],
    schema: dict,
    *,
    prompt_version: str,
    max_tokens: int,
) -> LLMRequest:
    return LLMRequest(
        request_id=f"console_{role}_{uuid4().hex}",
        agent_role=role,
        messages=messages,
        prompt_version=prompt_version,
        expected_schema=schema,
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        generation=LLMGenerationParameters(temperature=0.0),
        max_output_tokens=max_tokens,
        timeout_seconds=45,
    )


def _json_of(response: Any) -> dict:
    if response.status is not LLMResponseStatus.SUCCESS:
        raise RuntimeError(response.error.code.value if response.error else "provider_failure")
    return json.loads(response.output) if isinstance(response.output, str) else response.output


def _investigator_request(
    value: InvestigatorInput, *, repair: dict[str, object] | None = None
) -> LLMRequest:
    messages = [LLMMessage(role="system", content=INVESTIGATOR_SYSTEM_PROMPT)]
    if repair is not None:
        messages.append(
            LLMMessage(
                role="user",
                content=json.dumps(
                    {
                        "instruction": (
                            "The prior output violated the contract. Return one schema-valid "
                            "replacement. Do not infer or reveal an expected decision."
                        ),
                        "validation_category": repair["category"],
                        "invalid_field": repair["field"],
                        "previous_output_sanitized": repair["output"],
                    },
                    ensure_ascii=False,
                ),
            )
        )
    messages.append(
        LLMMessage(role="user", content=json.dumps(value.model_dump(mode="json"), ensure_ascii=False))
    )
    return _request(
        "investigator",
        tuple(messages),
        InvestigationDecision.model_json_schema(),
        prompt_version=INVESTIGATOR_PROMPT_VERSION,
        max_tokens=700,
    )


def _lifecycle(runtime: Any, event_type: TraceEventType, event_id: str, **details: Any) -> None:
    """Registra uma etapa do ciclo de vida na trajetória.

    Os tipos já existem em `TraceEventType`; faltava alguém emiti-los. Sem isso a
    trajetória só mostraria chamadas de ferramenta, e o engenheiro não veria o
    que aconteceu antes da primeira consulta.

    Só metadado operacional entra aqui — nunca raciocínio interno.
    """
    runtime.trace.append_operational(event_type, event_id, details=details)


def _summaries(state: InvestigationState) -> tuple[EvidenceSummary, TraceSummary]:
    records = state.evidence_ledger.records
    events = state.trace.events
    return (
        EvidenceSummary(
            evidence_ids=tuple(r.evidence_id for r in records),
            statuses=tuple(r.evidence_status.value for r in records),
            relevant_results=tuple(
                {"evidence_id": r.evidence_id, "tool_name": r.tool_name, "data": r.data}
                for r in records[-3:]
            ),
        ),
        TraceSummary(
            trace_id=state.trace_id,
            tool_call_count=state.tool_call_count,
            last_tool_name=events[-1].tool_name if events else None,
            last_call_id=events[-1].call_id if events else None,
        ),
    )


def _conclusion_from_evidence(state: InvestigationState) -> InvestigationConclusion:
    """Conclusão determinística: uma afirmação por evidência utilizável.

    Não há modelo aqui. A conclusão é montada do que foi observado, e é por isso
    que a proveniência não depende de o texto ter saído bom.
    """
    usable = [
        record
        for record in state.evidence_ledger.records
        if record.evidence_status.value in {"complete", "partial"}
    ]
    if not usable:
        raise ValueError("nenhuma evidência utilizável para fundamentar a conclusão")

    claims = tuple(
        Claim(
            claim_id=f"claim_{index + 1:02d}",
            statement=(
                f"A consulta {record.tool_name} retornou {record.method} {record.path} "
                f"com estado semântico {record.evidence_status.value}."
            )[:2000],
            supporting_evidence_ids=(record.evidence_id,),
            limitation=(
                "Evidência parcial: a fonte não retornou todos os campos esperados."
                if record.evidence_status.value == "partial"
                else None
            ),
            status=(
                ClaimStatus.QUALIFIED
                if record.evidence_status.value == "partial"
                else ClaimStatus.SUPPORTED
            ),
        )
        for index, record in enumerate(usable)
    )
    return InvestigationConclusion(
        conclusion_id=f"conclusion_{state.case_id}",
        claims=claims,
        supporting_evidence_ids=tuple(r.evidence_id for r in usable),
        limitations=("A investigação não infere além do que a fonte expôs.",),
        reason_codes=("EVIDENCE_SUFFICIENT",),
    )


def _attach_handoff(
    state: InvestigationState, decision: InvestigationDecision
) -> InvestigationState:
    """Encaminhamento com o motivo que a decisão realmente registrou."""
    handoff = HumanHandoff(
        handoff_id=f"handoff_{state.case_id}",
        reason_codes=decision.reason_codes,
        evidence_ids=tuple(r.evidence_id for r in state.evidence_ledger.records),
        missing_information=decision.required_information,
        suggested_next_step=(
            "Revisar as evidências coletadas e decidir com o contexto de engenharia."
        ),
    )
    return state.model_copy(update={"human_handoff": handoff})


def run_pipeline(
    request: UnderstandingInput,
    *,
    providers: Mapping[ProviderName, Provider],
    config: PipelineConfig,
    case_id: str,
    request_id: str,
    trace_id: str,
    checkpoint: Checkpoint,
    client: TractianClient | None = None,
) -> PipelineResult:
    """Executa a investigação de verdade, sinalizando cada etapa concluída."""
    started = perf_counter()
    errors: list[str] = []
    terminal = "FAILED"
    tool_calls = 0

    runtime = create_investigation_state(
        request, case_id=case_id, request_id=request_id, trace_id=trace_id
    )
    state = runtime.state
    owns_client = client is None
    client = client or TractianClient(RequestContext(), base_url=config.api_base_url)
    executor = TrackedToolExecutor(client, runtime.trace, runtime.evidence_ledger)
    tools = {tool.name: tool for tool in get_investigator_tools()}

    try:
        checkpoint("received", state)

        # --- Understanding ------------------------------------------------
        response = providers[config.understanding].infer(
            _request(
                "understanding",
                (
                    LLMMessage(role="system", content=SYSTEM_PROMPT),
                    LLMMessage(role="user", content=build_user_prompt(request)),
                ),
                UnderstandingOutput.model_json_schema(),
                prompt_version="understanding_prompt_v2",
                max_tokens=1800,
            )
        )
        understanding = UnderstandingOutput.model_validate(_json_of(response))
        state = attach_understanding(state, understanding, source=UnderstandingSource.MODEL)
        _lifecycle(
            runtime,
            TraceEventType.UNDERSTANDING_COMPLETED,
            f"understanding_{case_id}",
            request_class=understanding.request_class.value,
            investigation_targets=len(understanding.investigation_targets),
            blocking_gaps=sum(1 for m in understanding.missing_information if m.blocking),
        )
        state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
        checkpoint("understanding", state)

        # --- Planner ------------------------------------------------------
        planner_input = PlannerInput(
            understanding=understanding,
            permitted_context={"source": "console"},
            available_capabilities=tuple(CapabilityReference(name=name) for name in tools),
            max_investigation_steps=state.max_investigation_steps,
            max_tool_calls=state.max_tool_calls,
        )
        response = providers[config.planner].infer(
            _request(
                "planner",
                (
                    LLMMessage(
                        role="system",
                        content=(
                            "Return only a JSON object. Plan a read-only investigation; "
                            "do not execute tools or propose ACTIONs."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            planner_input.model_dump(mode="json"), ensure_ascii=False
                        ),
                    ),
                ),
                __import__(
                    "app.intelligence", fromlist=["PlannerOutput"]
                ).PlannerOutput.model_json_schema(),
                prompt_version="console_planner_v1",
                max_tokens=900,
            )
        )
        plan = parse_planner_output(response)
        state = attach_plan(state, plan, source=LLMArtifactSource.REAL_LLM)
        state = begin_investigation(state)
        _lifecycle(
            runtime,
            TraceEventType.PLANNER_COMPLETED,
            f"planner_{case_id}",
            objectives=len(plan.objectives),
            suggested_capabilities=[c.name for c in plan.suggested_capabilities],
        )
        state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
        checkpoint("planner", state)

        # --- Investigator + READ tools -------------------------------------
        while state.investigation_step_count < state.max_investigation_steps:
            evidence, trace = _summaries(state)
            value = InvestigatorInput(
                understanding=understanding,
                plan=plan,
                phase=state.phase.value,
                evidence=evidence,
                trace=trace,
                permitted_capabilities=tuple(CapabilityReference(name=name) for name in tools),
                investigation_step_count=state.investigation_step_count,
                max_investigation_steps=state.max_investigation_steps,
                tool_call_count=state.tool_call_count,
                max_tool_calls=state.max_tool_calls,
            )
            provider = providers[config.investigator]
            response = provider.infer(_investigator_request(value))
            validation, proposed, parsed = validate_investigation_decision(response)

            if (
                not validation.valid
                and recovery_action(validation) is InvestigatorRecoveryAction.ONE_LLM_REPAIR
            ):
                repair = {
                    "category": validation.category.value if validation.category else None,
                    "field": validation.field,
                    "output": parsed if parsed is not None else response.output,
                }
                response = provider.infer(_investigator_request(value, repair=repair))
                validation, proposed, parsed = validate_investigation_decision(response)

            if not validation.valid or proposed is None:
                # Contrato violado duas vezes: encaminha em vez de adivinhar.
                errors.append("INVESTIGATOR_CONTRACT_FAILURE")
                state = record_decision(
                    state,
                    InvestigationDecision(
                        decision_id=f"fail_safe_{uuid4().hex}",
                        type=InvestigationDecisionType.ESCALATE,
                        reason_codes=("INVESTIGATOR_CONTRACT_FAILURE",),
                    ),
                )
                break

            assessment = assess_completion_decision(state, proposed)
            decision = assessment.decision
            state = record_decision(state, decision)
            _lifecycle(
                runtime,
                TraceEventType.DECISION_ACCEPTED,
                decision.decision_id,
                decision_type=decision.type.value,
                reason_codes=list(decision.reason_codes),
                accepted_by_policy=assessment.accepted,
                policy_reason=assessment.reason_code,
            )
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            checkpoint("decision", state)

            if decision.type is not InvestigationDecisionType.TOOL_CALL:
                break

            assert decision.tool_request is not None
            result = executor.execute(
                tools[decision.tool_request.tool_name], decision.tool_request.arguments
            )
            tool_calls += 1
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            # Evento e evidências desta consulta entram no mesmo commit.
            checkpoint("tool_call", state)
            if not result.transport_ok:
                errors.append("TOOL_EXECUTION_ERROR")
                break

        # --- Desfecho -------------------------------------------------------
        final = state.decision
        if final and final.type is InvestigationDecisionType.ANSWER:
            state = attach_conclusion(state, _conclusion_from_evidence(state))
            _lifecycle(
                runtime,
                TraceEventType.CONCLUSION_CREATED,
                f"conclusion_{case_id}",
                claims=len(state.conclusion.claims) if state.conclusion else 0,
            )
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            checkpoint("conclusion", state)

            evidence, trace = _summaries(state)
            reporter_input = ReporterInput(
                case_id=state.case_id,
                trace_id=state.trace_id,
                understanding=understanding,
                plan=plan,
                conclusion=state.conclusion,
                evidence=evidence,
                trace=trace,
            )
            response = providers[config.reporter].infer(
                _request(
                    "reporter",
                    (
                        LLMMessage(
                            role="system",
                            content=(
                                "Return only a ReporterOutput JSON for tractian_engineering_team. "
                                "Preserve supplied claims and evidence IDs exactly; do not invent facts."
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                reporter_input.model_dump(mode="json"), ensure_ascii=False
                            ),
                        ),
                    ),
                    __import__(
                        "app.intelligence", fromlist=["ReporterOutput"]
                    ).ReporterOutput.model_json_schema(),
                    prompt_version="console_reporter_v1",
                    max_tokens=1200,
                )
            )
            state = attach_technical_report(
                state, parse_reporter_output(response), source=LLMArtifactSource.REAL_LLM
            )
            _lifecycle(runtime, TraceEventType.REPORTER_COMPLETED, f"report_{case_id}")
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            checkpoint("report", state)
            terminal = "GROUNDED_COMPLETION"

        elif final and final.type is InvestigationDecisionType.ESCALATE:
            state = _attach_handoff(state, final)
            terminal = "SAFE_ESCALATION"
            checkpoint("escalation", state)

        elif final and final.type is InvestigationDecisionType.ASK_USER:
            terminal = "AWAITING_REQUIRED_INFORMATION"
            checkpoint("awaiting", state)

        else:
            errors.append(
                "INSUFFICIENT_EVIDENCE"
                if not state.evidence_ledger.records
                else "INVESTIGATION_NOT_ANSWERED"
            )

    except Exception as exc:  # noqa: BLE001 — a falha vira registro, não sumiço
        errors.append(type(exc).__name__)
        try:
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            checkpoint("failure", state)
        except Exception:
            pass
    finally:
        if owns_client:
            client.close()

    try:
        _lifecycle(
            runtime,
            TraceEventType.TERMINAL_STATE_REACHED,
            f"terminal_{case_id}",
            terminal_state=terminal,
            errors=errors,
        )
        state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
        checkpoint("terminal", state)
    except Exception:  # noqa: BLE001 - fechar a trajetória nunca derruba o resultado
        pass

    return PipelineResult(
        state=state,
        terminal_state=terminal,
        errors=errors,
        duration_ms=int((perf_counter() - started) * 1000),
        tool_calls_executed=tool_calls,
    )
