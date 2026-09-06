"""Etapa 09.5 — avaliação E2E do split Synthetic DEV completo, em configuração congelada.

A rodada existe para medir, não para consertar: prompts, routing, schemas,
Completion Policy, política de recuperação e limites permanecem exatamente como
a Etapa 09.4F os deixou. Qualquer erro observado é registrado e classificado,
nunca corrigido no meio do experimento.

Execução:
    python -m scripts.run_full_dev_evaluation                # plano, sem LLM
    python -m scripts.run_full_dev_evaluation --execute      # rodada real
    python -m scripts.run_full_dev_evaluation --execute      # retomada (pula concluídos)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from time import perf_counter
from pathlib import Path
from time import sleep
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agents.understanding.dataset import UnderstandingSample, load_dev_split
from app.agents.understanding.metrics import UnderstandingEvaluator
from app.agents.understanding.prompts import PROMPT_VERSION_V2, SYSTEM_PROMPT_V2, build_user_prompt
from app.agents.understanding.schemas import UnderstandingOutput
from app.evaluation.coverage import CaseCoverage, audit_coverage
from app.evaluation.dataset_validation import runtime_payload, validate_split_file
from app.evaluation.gates import evaluate_gates, overall_status, training_decisions
from app.evaluation.tool_capabilities import build_matrix
from app.evaluation.metrics import (
    coverage_correlation,
    e2e_metrics,
    error_metrics,
    investigator_metrics,
    lineage_metrics,
    planner_metrics,
    provider_metrics,
    reporter_metrics,
)
from app.evaluation.taxonomy import (
    EvaluationError,
    EvaluationErrorCode,
    FailureCategory,
    PrimaryLayer,
    RunStatus,
    TerminalStatus,
)
from app.intelligence import (
    CapabilityContract,
    CapabilityReference,
    InvestigatorInput,
    PlannerInput,
    PlannerOutput,
    ReporterInput,
    ReporterOutput,
)
from app.intelligence.boundaries import parse_planner_output, parse_reporter_output
from app.intelligence.grounding import build_claim_lineage, build_grounded_conclusion, validate_reporter_output
from app.integrations.tractian_client import RequestContext, TractianClient
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    LLMArtifactSource,
    assess_temporal_request,
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
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, LLMResponseStatus, StructuredOutputMode
from app.llm.contracts import LLMErrorCode
from app.llm.investigator import InvestigatorRecoveryAction, recovery_action, validate_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from app.observability import RunTiming, TraceEventType, TrackedToolExecutor
from app.tools import get_investigator_tools
from scripts.diagnose_llm_providers import load_local_env
from scripts.run_e2e_dev_pilot import (
    INVESTIGATOR_PROMPT_VERSION,
    INVESTIGATOR_SYSTEM_PROMPT,
    _investigator_request,
    _llm_record,
    _summaries,
    _validation_attempt,
)


# --------------------------------------------------------------------------- #
# Configuração congelada — nada aqui muda durante a rodada (Etapa 09.5, §1/§23)
# --------------------------------------------------------------------------- #

EXPERIMENT_VERSION = "e2e-full-dev-v2"
ROUTING_VERSION = "MODEL_ROUTING_V5"

# Etapa 09.8: o Understanding pode ser roteado ao Gemini para contornar a cota
# diaria do Groq. Coorte separada, nunca misturada com a V2: o experimento e o
# routing mudam junto com o provider, porque a roteirizacao de fato mudou.
UNDERSTANDING_FALLBACK = {
    "provider": ProviderName.GEMINI,
    "experiment_version": "e2e-full-dev-v2b",
    "routing_version": "MODEL_ROUTING_V6",
    "routing_note": (
        "Derivado do MODEL_ROUTING_V5 trocando apenas o provider do Understanding, "
        "de Groq para Gemini. Demais papeis, prompts, schemas e politicas identicos."
    ),
}
ROUTING_NOTE = (
    "Routing assignment unchanged. Version increment reflects configuration, prompt and capability changes."
)
SPLIT = "dev"
PLANNER_PROMPT_VERSION = "e2e_planner_v1"
REPORTER_PROMPT_VERSION = "e2e_reporter_grounded_v1"
UNDERSTANDING_PROMPT_VERSION = PROMPT_VERSION_V2
UNDERSTANDING_SYSTEM_PROMPT = SYSTEM_PROMPT_V2
SCHEMA_VERSION = "InvestigationDecision-1.1"
ADAPTER_VERSION = "gemini-http-v3-token-ceiling"
RECOVERY_POLICY = "one_llm_repair_then_deterministic_safe_escalation"
COMPLETION_POLICY_VERSION = "completion_policy_v1_09_4C"
GROUNDING_VERSION = "grounding_v1_09_4F"
TEMPORAL_POLICY_VERSION = "temporal_policy_v1_09_6"

# Orçamentos por papel. Na V1 o teto do provider era 512 e cortava silenciosamente
# Planner e Reporter; com o teto corrigido, estes valores passam a valer de fato.
UNDERSTANDING_MAX_TOKENS = 2048
PLANNER_MAX_TOKENS = 1200
INVESTIGATOR_MAX_TOKENS = 900
REPORTER_MAX_TOKENS = 1600

PLANNER_SYSTEM_PROMPT = (
    "Return only a JSON object. Plan a read-only investigation; do not execute tools or propose ACTIONs."
)
REPORTER_SYSTEM_PROMPT = (
    "Return only ReporterOutput JSON for tractian_engineering_team. Copy every supplied claim, evidence ID, "
    "limitation and unresolved point exactly. Do not add claims, facts, tools or actions."
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / EXPERIMENT_VERSION
DEFAULT_THROTTLE_SECONDS = 20.0

SMOKE_SAMPLE_IDS: tuple[str, ...] = (
    "syn_u_dev_0025",  # Planner falhou por MAX_TOKENS na V1: valida o teto corrigido
    "syn_u_dev_0036",  # `execute` classificado como `mixed` na V1
    "syn_u_dev_0049",  # `mixed` legítimo: guarda contra super-correção do prompt
    "syn_u_dev_0011",  # pedido temporal que virou ASK_USER na V1
    "syn_u_dev_0012",  # investigação normal, para detectar regressão estrutural
)
"""Seleção fixa que exercita exatamente o que a Etapa 09.6 alterou."""
MAX_CONSECUTIVE_RATE_LIMITS = 3

_QUOTA_ERROR_CODES = {LLMErrorCode.QUOTA_EXCEEDED}
_RATE_LIMIT_ERROR_CODES = {LLMErrorCode.RATE_LIMIT}
_ENTITY_BUCKETS = ("assets", "analyses", "models")
_TEMPORAL_MATRIX = build_matrix()


def capability_contracts() -> tuple[CapabilityContract, ...]:
    """Contrato real de cada READ, copiado do schema que a Tool Layer valida."""

    return tuple(
        CapabilityContract(
            name=item.tool_name,
            accepted_arguments=item.accepted_arguments,
            required_arguments=item.required_arguments,
            argument_schema=item.argument_schema,
        )
        for item in _TEMPORAL_MATRIX.tools
    )


class ProviderQuotaExceeded(RuntimeError):
    """Quota do provider indisponível: a rodada pausa em vez de trocar de provider."""


class RunAborted(RuntimeError):
    """Erro classificado que encerra o caso sem encerrar a rodada."""

    def __init__(self, error: EvaluationError) -> None:
        super().__init__(error.code.value)
        self.error = error


# --------------------------------------------------------------------------- #
# Infraestrutura de chamada
# --------------------------------------------------------------------------- #


def _request(
    role: str,
    system_prompt: str,
    payload: object,
    schema: dict,
    *,
    prompt_version: str,
    max_tokens: int,
) -> LLMRequest:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return LLMRequest(
        request_id=f"fulldev_{role}_{uuid4().hex}",
        agent_role=role,
        messages=(LLMMessage(role="system", content=system_prompt), LLMMessage(role="user", content=content)),
        prompt_version=prompt_version,
        generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=schema,
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=max_tokens,
        timeout_seconds=45,
    )


def _guard_provider(response, *, role: str) -> None:
    """Falha de provider vira erro classificado; quota interrompe a rodada inteira."""

    if response.status is LLMResponseStatus.SUCCESS:
        return
    error = response.error
    code = error.code if error else None
    if code in _QUOTA_ERROR_CODES:
        raise ProviderQuotaExceeded(f"{response.provider}:{code.value}")
    if code in _RATE_LIMIT_ERROR_CODES:
        raise RunAborted(
            EvaluationError.of(
                EvaluationErrorCode.RATE_LIMIT, subcategory=response.provider, detail=f"{role}: rate limit."
            )
        )
    if code is LLMErrorCode.TIMEOUT:
        raise RunAborted(
            EvaluationError.of(
                EvaluationErrorCode.TIMEOUT, subcategory=response.provider, detail=f"{role}: timeout."
            )
        )
    if code is LLMErrorCode.OUTPUT_TRUNCATED:
        # Orçamento de tokens curto é configuração, não prompt: a camada precisa
        # sobrescrever o default da taxonomia para não acusar o agente errado.
        raise RunAborted(
            EvaluationError.of(
                EvaluationErrorCode.PROVIDER_ERROR,
                subcategory="OUTPUT_TRUNCATED",
                detail=f"{role}: saída cortada pelo teto de tokens do provider.",
                primary_layer=PrimaryLayer.PROVIDER,
            )
        )
    raise RunAborted(
        EvaluationError.of(
            EvaluationErrorCode.PROVIDER_ERROR,
            subcategory=code.value if code else "unknown",
            detail=f"{role}: {error.message if error else 'provider failure'}",
        )
    )


def _call(provider: Any, request: LLMRequest, *, role: str, ledger: list[dict[str, Any]]):
    """Registra toda chamada real antes de decidir se ela aborta o caso.

    Na Etapa 09.5 o guard levantava antes de `components[...]` ser atribuído, e
    uma falha de provider sumia da contabilidade — `provider_error_rate` mostrou
    0 com um 5xx observado. O ledger é escrito primeiro, sempre.
    """

    response = provider.infer(request)
    ledger.append({**_llm_record(response), "role": role})
    _guard_provider(response, role=role)
    return response


def _entity_buckets(understanding: UnderstandingOutput) -> tuple[str, ...]:
    """Buckets de identificador realmente disponíveis para escolher capabilities."""

    return tuple(bucket for bucket in _ENTITY_BUCKETS if getattr(understanding.entities, bucket))


# --------------------------------------------------------------------------- #
# Execução de um caso
# --------------------------------------------------------------------------- #


def run_case(
    sample: UnderstandingSample,
    providers: dict[ProviderName, Any],
    client: TractianClient,
    coverage: CaseCoverage,
    understanding_provider: ProviderName = ProviderName.GROQ,
) -> dict[str, Any]:
    """Executa um caso DEV de ponta a ponta e devolve o registro persistível."""

    started_at = datetime.now(timezone.utc)
    # `datetime.now` é relógio de parede e pode andar para trás (ajuste de NTP,
    # fuso, correção manual). Duração é medida com relógio monotônico e
    # `finished_at` é derivado da âncora, para que um salto do sistema não
    # produza duração negativa nem invalide o RunTiming.
    started_monotonic = perf_counter()
    request = runtime_payload(sample)
    runtime = create_investigation_state(
        request,
        case_id=f"case_{sample.sample_id}",
        request_id=f"request_{sample.sample_id}",
        trace_id=f"trace_{sample.sample_id}",
    )
    state = runtime.state
    trace = runtime.trace
    tools = {tool.name: tool for tool in get_investigator_tools()}
    executor = TrackedToolExecutor(client, trace, runtime.evidence_ledger)
    components: dict[str, Any] = {}
    errors: list[EvaluationError] = []
    llm_calls: list[dict[str, Any]] = []
    terminal = TerminalStatus.FAILED
    failure_category: FailureCategory | None = FailureCategory.DEAD_END
    contract_failsafe = False

    try:
        # --- Understanding (Groq por padrao; Gemini na coorte V2b) ---------
        response = _call(
            providers[understanding_provider],
            _request(
                "understanding",
                UNDERSTANDING_SYSTEM_PROMPT,
                build_user_prompt(request),
                UnderstandingOutput.model_json_schema(),
                prompt_version=UNDERSTANDING_PROMPT_VERSION,
                max_tokens=UNDERSTANDING_MAX_TOKENS,
            ),
            role="understanding",
            ledger=llm_calls,
        )
        try:
            raw = json.loads(response.output) if isinstance(response.output, str) else response.output
            understanding = UnderstandingOutput.model_validate(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            components["understanding"] = {**_llm_record(response), "schema_valid": False, "output": None}
            raise RunAborted(
                EvaluationError.of(
                    EvaluationErrorCode.UNDERSTANDING_ERROR,
                    subcategory=type(exc).__name__,
                    detail="Understanding não produziu contrato válido.",
                )
            ) from exc
        components["understanding"] = {
            **_llm_record(response),
            "schema_valid": True,
            "input": request.model_dump(mode="json"),
            "output": understanding.model_dump(mode="json"),
        }
        state = attach_understanding(state, understanding, source=UnderstandingSource.MODEL)
        trace.append_operational(
            TraceEventType.UNDERSTANDING_COMPLETED,
            f"understanding_{uuid4().hex}",
            details={
                "provider": response.provider,
                "model": response.model,
                "request_class": understanding.request_class.value,
                "entity_buckets": list(_entity_buckets(understanding)),
            },
        )

        # --- Planner / Gemini ----------------------------------------------
        planner_input = PlannerInput(
            understanding=understanding,
            permitted_context={"source": "synthetic_dev_full", "split": SPLIT},
            available_capabilities=tuple(CapabilityReference(name=name) for name in tools),
            max_investigation_steps=state.max_investigation_steps,
            max_tool_calls=state.max_tool_calls,
        )
        response = _call(
            providers[ProviderName.GEMINI],
            _request(
                "planner",
                PLANNER_SYSTEM_PROMPT,
                planner_input.model_dump(mode="json"),
                PlannerOutput.model_json_schema(),
                prompt_version=PLANNER_PROMPT_VERSION,
                max_tokens=PLANNER_MAX_TOKENS,
            ),
            role="planner",
            ledger=llm_calls,
        )
        try:
            plan = parse_planner_output(response)
        except Exception as exc:
            components["planner"] = {**_llm_record(response), "schema_valid": False, "output": None}
            raise RunAborted(
                EvaluationError.of(
                    EvaluationErrorCode.PLANNER_ERROR,
                    subcategory=type(exc).__name__,
                    detail="Planner não produziu PlannerOutput válido.",
                )
            ) from exc
        components["planner"] = {
            **_llm_record(response),
            "schema_valid": True,
            "output": plan.model_dump(mode="json"),
            "available_entity_buckets": list(_entity_buckets(understanding)),
        }
        state = begin_investigation(attach_plan(state, plan, source=LLMArtifactSource.REAL_LLM))
        trace.append_operational(
            TraceEventType.PLANNER_COMPLETED,
            plan.plan_id,
            details={
                "provider": response.provider,
                "model": response.model,
                "suggested_capabilities": [item.name for item in plan.suggested_capabilities],
            },
        )

        # --- Investigator / Gemini -----------------------------------------
        # A lista é publicada em `components` antes do laço: se o caso abortar no
        # meio, as decisões já tomadas continuam gravadas. Publicar só no fim
        # descartava o histórico exatamente nos casos que mais precisam dele.
        decisions: list[dict[str, Any]] = []
        components["investigator"] = decisions
        provider = providers[ProviderName.GEMINI]

        # O Investigator recebe o contrato real de cada tool e a limitação
        # temporal apurada, em vez de precisar supor parâmetros.
        contracts = capability_contracts()
        temporal = assess_temporal_request(
            request.message,
            temporal_references=tuple(understanding.entities.temporal_references),
            filterable_tools=_TEMPORAL_MATRIX.filterable_tools,
            timestamped_tools=_TEMPORAL_MATRIX.tools_returning_timestamped_data,
        )
        components["temporal_policy"] = temporal.model_dump(mode="json")
        while state.investigation_step_count < state.max_investigation_steps:
            evidence, trace_summary = _summaries(state)
            value = InvestigatorInput(
                understanding=understanding,
                plan=plan,
                phase=state.phase.value,
                evidence=evidence,
                trace=trace_summary,
                permitted_capabilities=tuple(CapabilityReference(name=name) for name in tools),
                capability_contracts=contracts,
                temporal_guidance=temporal.guidance,
                investigation_step_count=state.investigation_step_count,
                max_investigation_steps=state.max_investigation_steps,
                tool_call_count=state.tool_call_count,
                max_tool_calls=state.max_tool_calls,
            )
            response = _call(
                provider, _investigator_request(value), role="investigator", ledger=llm_calls
            )
            trace.append_operational(
                TraceEventType.LLM_DECISION_PRODUCED,
                f"decision_output_{uuid4().hex}",
                details={
                    "provider": response.provider,
                    "model": response.model,
                    "prompt_version": INVESTIGATOR_PROMPT_VERSION,
                    "step": state.investigation_step_count + 1,
                },
            )
            validation, proposed, parsed = validate_investigation_decision(response)
            attempts = [_validation_attempt(provider, response, validation, parsed, attempt_number=1, value=value)]
            repair_attempted = False
            if not validation.valid and recovery_action(validation) is InvestigatorRecoveryAction.ONE_LLM_REPAIR:
                repair_attempted = True
                repair = {
                    "category": validation.category.value if validation.category else None,
                    "field": validation.field,
                    "output": parsed if parsed is not None else response.output,
                }
                response = provider.infer(_investigator_request(value, repair=repair))
                _guard_provider(response, role="investigator_repair")
                validation, proposed, parsed = validate_investigation_decision(response)
                attempts.append(
                    _validation_attempt(provider, response, validation, parsed, attempt_number=2, value=value)
                )
            trace.append_operational(
                TraceEventType.DECISION_VALIDATED,
                f"decision_validation_{uuid4().hex}",
                details={
                    "valid": validation.valid,
                    "category": validation.category.value if validation.category else None,
                    "repair_attempted": repair_attempted,
                },
            )

            if not validation.valid or proposed is None:
                category = validation.category.value if validation.category else "OTHER_CONTRACT_VIOLATION"
                errors.append(
                    EvaluationError.of(
                        EvaluationErrorCode.INVESTIGATOR_VALIDATION_ERROR,
                        subcategory=category,
                        detail="Decisão inválida após a política de recuperação; escalada determinística.",
                    )
                )
                contract_failsafe = True
                decision = InvestigationDecision(
                    decision_id=f"contract_fail_safe_{uuid4().hex}",
                    type=InvestigationDecisionType.ESCALATE,
                    reason_codes=("INVESTIGATOR_CONTRACT_FAILURE",),
                )
                decisions.append(
                    {
                        "attempts": attempts,
                        "first_pass_valid": attempts[0]["validation"]["valid"],
                        "repair_attempted": repair_attempted,
                        "repair_successful": False,
                        "final_decision_source": "deterministic_fail_safe",
                        "output": decision.model_dump(mode="json"),
                        "completion_policy": None,
                    }
                )
                state = record_decision(state, decision)
                trace.append_operational(
                    TraceEventType.DECISION_ACCEPTED,
                    decision.decision_id,
                    details={"decision_type": decision.type.value, "policy_reason": "DETERMINISTIC_FAIL_SAFE"},
                )
                break

            assessment = assess_completion_decision(state, proposed)
            decision = assessment.decision
            trace.append_operational(
                TraceEventType.DECISION_ACCEPTED if assessment.accepted else TraceEventType.DECISION_REJECTED,
                decision.decision_id,
                details={
                    "decision_type": decision.type.value,
                    "proposed_type": proposed.type.value,
                    "policy_reason": assessment.reason_code,
                },
            )
            decisions.append(
                {
                    "attempts": attempts,
                    "first_pass_valid": attempts[0]["validation"]["valid"],
                    "repair_attempted": repair_attempted,
                    "repair_successful": repair_attempted and validation.valid,
                    "final_decision_source": "repaired_llm" if repair_attempted else "first_pass_llm",
                    "output": decision.model_dump(mode="json"),
                    "completion_policy": {
                        "accepted": assessment.accepted,
                        "reason_code": assessment.reason_code,
                        "rejected_decision_type": (
                            assessment.rejected_decision_type.value if assessment.rejected_decision_type else None
                        ),
                    },
                }
            )
            state = record_decision(state, decision)

            if decision.type is not InvestigationDecisionType.TOOL_CALL:
                break

            assert decision.tool_request is not None
            trace.append_operational(
                TraceEventType.TOOL_REQUESTED,
                decision.decision_id,
                details={
                    "tool_name": decision.tool_request.tool_name,
                    "argument_keys": sorted(decision.tool_request.arguments),
                },
            )
            before = len(runtime.evidence_ledger.records)
            try:
                result = executor.execute(tools[decision.tool_request.tool_name], decision.tool_request.arguments)
            except Exception as exc:
                state = synchronize_observability(state, trace, runtime.evidence_ledger)
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.INVALID_ARGUMENT
                        if type(exc).__name__ == "ValidationError"
                        else EvaluationErrorCode.TOOL_EXECUTION_ERROR,
                        subcategory=type(exc).__name__,
                        detail="Execução da tool falhou antes de produzir evidência.",
                    )
                ) from exc
            state = synchronize_observability(state, trace, runtime.evidence_ledger)
            for record in runtime.evidence_ledger.records[before:]:
                trace.append_operational(
                    TraceEventType.EVIDENCE_CREATED,
                    record.evidence_id,
                    details={
                        "source_call_id": record.source_call_id,
                        "tool_name": record.tool_name,
                        "evidence_status": record.evidence_status.value,
                    },
                )
            state = synchronize_observability(state, trace, runtime.evidence_ledger)
            if not result.transport_ok:
                errors.append(
                    EvaluationError.of(
                        EvaluationErrorCode.TOOL_EXECUTION_ERROR,
                        subcategory=str(result.status_code),
                        detail=f"{result.operation} sem sucesso de transporte.",
                    )
                )
                break

        state = synchronize_observability(state, trace, runtime.evidence_ledger)

        # --- Conclusão, lineage e Reporter ---------------------------------
        current = state.decision
        if current is not None and current.type is InvestigationDecisionType.ANSWER:
            try:
                conclusion = build_grounded_conclusion(state)
                lineage = build_claim_lineage(state, conclusion)
            except ValueError as exc:
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.INVALID_CONCLUSION,
                        subcategory="GROUNDED_CONCLUSION_NOT_MATERIALIZABLE",
                        detail=str(exc)[:200],
                    )
                ) from exc
            if not all(item.valid for item in lineage):
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.UNSUPPORTED_CLAIM,
                        subcategory="INVALID_CLAIM_LINEAGE",
                        detail="Claim sem cadeia íntegra até um tool_completed READ.",
                    )
                )
            state = attach_conclusion(state, conclusion)
            trace.append_operational(
                TraceEventType.CONCLUSION_CREATED,
                conclusion.conclusion_id,
                details={"claim_count": len(conclusion.claims), "lineage_valid": True},
            )
            components["conclusion"] = conclusion.model_dump(mode="json")
            components["claim_lineage"] = [item.model_dump(mode="json") for item in lineage]

            evidence, trace_summary = _summaries(state)
            reporter_input = ReporterInput(
                case_id=state.case_id,
                trace_id=state.trace_id,
                understanding=understanding,
                plan=plan,
                conclusion=conclusion,
                evidence=evidence,
                trace=trace_summary,
            )
            trace.append_operational(
                TraceEventType.REPORTER_STARTED,
                f"reporter_{uuid4().hex}",
                details={"audience": "tractian_engineering_team"},
            )
            response = _call(
                providers[ProviderName.GEMINI],
                _request(
                    "reporter",
                    REPORTER_SYSTEM_PROMPT,
                    reporter_input.model_dump(mode="json"),
                    ReporterOutput.model_json_schema(),
                    prompt_version=REPORTER_PROMPT_VERSION,
                    max_tokens=REPORTER_MAX_TOKENS,
                ),
                role="reporter",
                ledger=llm_calls,
            )
            try:
                report = parse_reporter_output(response)
            except Exception as exc:
                components["reporter"] = {**_llm_record(response), "output": None, "validation": {"valid": False, "schema_valid": False, "violations": ["SCHEMA_INVALID"]}}
                trace.append_operational(
                    TraceEventType.REPORTER_FAILED,
                    f"reporter_schema_{uuid4().hex}",
                    details={"violations": ["SCHEMA_INVALID"]},
                )
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.REPORTER_ERROR,
                        subcategory=type(exc).__name__,
                        detail="Reporter não produziu ReporterOutput válido.",
                    )
                ) from exc
            reporter_validation = validate_reporter_output(reporter_input, report)
            components["reporter"] = {
                **_llm_record(response),
                "output": report.model_dump(mode="json"),
                "validation": reporter_validation.model_dump(mode="json"),
            }
            if not reporter_validation.valid:
                trace.append_operational(
                    TraceEventType.REPORTER_FAILED,
                    report.report_id,
                    details={"violations": list(reporter_validation.violations)},
                )
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.UNSUPPORTED_CLAIM
                        if "UNSUPPORTED_CLAIM" in reporter_validation.violations
                        else EvaluationErrorCode.REPORTER_ERROR,
                        subcategory=",".join(reporter_validation.violations)[:120],
                        detail="Relatório não preservou a conclusão determinística.",
                    )
                )
            try:
                state = attach_technical_report(state, report, source=LLMArtifactSource.REAL_LLM)
            except (ValueError, TypeError) as exc:
                trace.append_operational(
                    TraceEventType.REPORTER_FAILED,
                    report.report_id,
                    details={"violations": ["REPORT_IDENTITY_MISMATCH"]},
                )
                raise RunAborted(
                    EvaluationError.of(
                        EvaluationErrorCode.REPORTER_ERROR,
                        subcategory="REPORT_IDENTITY_MISMATCH",
                        detail=str(exc)[:200],
                    )
                ) from exc
            trace.append_operational(
                TraceEventType.REPORTER_COMPLETED,
                report.report_id,
                details={"schema_valid": True, "unsupported_claim_rate": reporter_validation.unsupported_claim_rate},
            )
            terminal, failure_category = TerminalStatus.GROUNDED_COMPLETION, None
        elif current is not None and current.type is InvestigationDecisionType.ESCALATE:
            terminal, failure_category = TerminalStatus.SAFE_ESCALATION, None
        elif current is not None and current.type is InvestigationDecisionType.ASK_USER:
            terminal, failure_category = TerminalStatus.AWAITING_REQUIRED_INFORMATION, None
        else:
            terminal, failure_category = TerminalStatus.FAILED, FailureCategory.DEAD_END
            errors.append(
                EvaluationError.of(
                    EvaluationErrorCode.INSUFFICIENT_EVIDENCE
                    if not state.evidence_ledger.records
                    else EvaluationErrorCode.LIMIT_REACHED,
                    detail="Investigação encerrou sem decisão terminal.",
                )
            )
    except RunAborted as aborted:
        errors.append(aborted.error)
        terminal = TerminalStatus.FAILED
        failure_category = (
            FailureCategory.INVALID_STATE
            if aborted.error.code
            in {
                EvaluationErrorCode.INVALID_CONCLUSION,
                EvaluationErrorCode.UNSUPPORTED_CLAIM,
                EvaluationErrorCode.REPORTER_ERROR,
            }
            else FailureCategory.UNCLASSIFIED_ERROR
        )
    except ProviderQuotaExceeded:
        raise
    except Exception as exc:  # pragma: no cover - salvaguarda de rodada longa
        errors.append(
            EvaluationError.of(
                EvaluationErrorCode.STATE_TRANSITION_ERROR
                if "Transition" in type(exc).__name__ or "Loop" in type(exc).__name__
                else EvaluationErrorCode.SYSTEM_ERROR,
                subcategory=type(exc).__name__,
                detail=str(exc)[:200],
            )
        )
        terminal, failure_category = TerminalStatus.FAILED, FailureCategory.UNCLASSIFIED_ERROR

    trace.append_operational(
        TraceEventType.TERMINAL_STATE_REACHED,
        f"terminal_{sample.sample_id}",
        details={
            "terminal_status": terminal.value,
            "failure_category": failure_category.value if failure_category else None,
            "phase": state.phase.value,
        },
    )
    elapsed_seconds = max(0.0, perf_counter() - started_monotonic)
    finished_at = started_at + timedelta(seconds=elapsed_seconds)
    timing = RunTiming.between(started_at, finished_at)
    return {
        "run_id": f"fulldev_{sample.sample_id}",
        "sample_id": sample.sample_id,
        "split": SPLIT,
        "training_tags": list(sample.training_tags),
        "experiment_version": EXPERIMENT_VERSION,
        "routing_version": ROUTING_VERSION,
        "providers": {
            "understanding": understanding_provider.value,
            "planner": "gemini",
            "investigator": "gemini",
            "reporter": "gemini",
        },
        **timing.model_dump(mode="json"),
        "llm_calls": llm_calls,
        "components": components,
        "state": state.model_dump(mode="json"),
        "trace": trace.as_dicts(),
        "evidence_ledger": runtime.evidence_ledger.as_dicts(),
        "terminal_status": terminal.value,
        "failure_category": failure_category.value if failure_category else None,
        "contract_failsafe": contract_failsafe,
        "errors": [error.model_dump(mode="json") for error in errors],
        "coverage": {
            "alignment": coverage.alignment.value,
            "grounded_answer_reachable": coverage.grounded_answer_reachable,
            "temporal_context_requested": coverage.temporal_context_requested,
            "warnings": list(coverage.warnings),
        },
    }


# --------------------------------------------------------------------------- #
# Agregação e artefatos
# --------------------------------------------------------------------------- #


def understanding_metrics(runs: list[dict[str, Any]], samples: dict[str, UnderstandingSample]) -> dict[str, Any]:
    """Pontuação offline contra o target do split; o target nunca entra em prompt."""

    evaluator = UnderstandingEvaluator()
    for run in runs:
        component = run.get("components", {}).get("understanding")
        sample = samples.get(run["sample_id"])
        if sample is None:
            continue
        if not component or not component.get("schema_valid") or not component.get("output"):
            evaluator.observe_failure(provider_error=bool(component and component.get("error")))
            continue
        evaluator.observe(
            request=sample.input,
            expected=sample.target,
            predicted=UnderstandingOutput.model_validate(component["output"]),
        )
    return evaluator.as_dict()


def needs_human_review(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Casos cuja adequação não pode ser decidida por regra."""

    flagged: list[dict[str, Any]] = []
    for run in runs:
        reasons: list[str] = []
        components = run.get("components", {})
        coverage = run.get("coverage") or {}
        if run["terminal_status"] == TerminalStatus.SAFE_ESCALATION.value and coverage.get(
            "grounded_answer_reachable"
        ):
            reasons.append("ESCALATION_DESPITE_REACHABLE_GROUNDED_ANSWER")
        if run["terminal_status"] == TerminalStatus.AWAITING_REQUIRED_INFORMATION.value and coverage.get(
            "grounded_answer_reachable"
        ):
            reasons.append("ASK_USER_DESPITE_RESOLVABLE_ENTITY")
        if components.get("planner") and not any(
            event.get("event_type") == "tool_completed" for event in run.get("trace", [])
        ):
            reasons.append("PLAN_PRODUCED_WITHOUT_ANY_TOOL_EXECUTION")
        if components.get("reporter") and run["terminal_status"] == TerminalStatus.GROUNDED_COMPLETION.value:
            reasons.append("REPORT_TECHNICALLY_VALID_UTILITY_UNSCORED")
        if run.get("contract_failsafe"):
            reasons.append("CONTRACT_FAILSAFE_ESCALATION")
        if reasons:
            flagged.append(
                {
                    "sample_id": run["sample_id"],
                    "terminal_status": run["terminal_status"],
                    "coverage_alignment": coverage.get("alignment"),
                    "reasons": reasons,
                }
            )
    return flagged


_SHOWCASE_SELECTORS: tuple[tuple[str, Any], ...] = (
    ("grounded_completion", lambda run: run["terminal_status"] == TerminalStatus.GROUNDED_COMPLETION.value),
    ("safe_escalation", lambda run: run["terminal_status"] == TerminalStatus.SAFE_ESCALATION.value),
    (
        "awaiting_information",
        lambda run: run["terminal_status"] == TerminalStatus.AWAITING_REQUIRED_INFORMATION.value,
    ),
    ("evidence_partial", lambda run: any(r["evidence_status"] == "partial" for r in run["evidence_ledger"])),
    ("evidence_conflict", lambda run: any(r["evidence_status"] == "conflict" for r in run["evidence_ledger"])),
    (
        "evidence_unavailable",
        lambda run: any(r["evidence_status"] == "unavailable" for r in run["evidence_ledger"]),
    ),
    (
        "evidence_inconclusive",
        lambda run: any(r["evidence_status"] == "inconclusive" for r in run["evidence_ledger"]),
    ),
    ("data_coverage_gap", lambda run: "DATA_COVERAGE_WARNING" in (run.get("coverage") or {}).get("warnings", [])),
    ("descriptor_misaligned", lambda run: (run.get("coverage") or {}).get("alignment") == "MISALIGNED"),
    ("real_error", lambda run: bool(run.get("errors"))),
    ("contract_failsafe", lambda run: bool(run.get("contract_failsafe"))),
)


def build_showcase(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Escolhe casos por categoria observada, incluindo os desfavoráveis."""

    selected: dict[str, dict[str, Any]] = {}
    for label, predicate in _SHOWCASE_SELECTORS:
        match = next((run for run in runs if predicate(run)), None)
        if match is not None:
            selected[label] = match
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "routing_version": ROUTING_VERSION,
        "selection_policy": "primeira ocorrência por categoria observada, sucessos e falhas",
        "categories_absent": [label for label, _ in _SHOWCASE_SELECTORS if label not in selected],
        "cases": {
            label: {
                "sample_id": run["sample_id"],
                "training_tags": run.get("training_tags", []),
                "request": run.get("state", {}).get("request"),
                "understanding": run["components"].get("understanding"),
                "planner": run["components"].get("planner"),
                "investigator_decisions": run["components"].get("investigator"),
                "conclusion": run["components"].get("conclusion"),
                "claim_lineage": run["components"].get("claim_lineage"),
                "reporter": run["components"].get("reporter"),
                "trace": run["trace"],
                "evidence_ledger": run["evidence_ledger"],
                "terminal_status": run["terminal_status"],
                "failure_category": run["failure_category"],
                "coverage": run["coverage"],
                "errors": run["errors"],
                "duration_ms": run["duration_ms"],
            }
            for label, run in selected.items()
        },
    }


def build_manifest(sample_ids: list[str], configs: dict[ProviderName, Any], understanding_provider: ProviderName = ProviderName.GROQ) -> dict[str, Any]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "phase": "B_FULL_DEV",
        "routing_version": ROUTING_VERSION,
        "routing_note": ROUTING_NOTE,
        "temporal_policy_version": TEMPORAL_POLICY_VERSION,
        "output_token_budgets": {
            "understanding": UNDERSTANDING_MAX_TOKENS,
            "planner": PLANNER_MAX_TOKENS,
            "investigator": INVESTIGATOR_MAX_TOKENS,
            "reporter": REPORTER_MAX_TOKENS,
        },
        "provider_output_ceilings": {
            name.value: configs[name].max_output_tokens for name in (ProviderName.GROQ, ProviderName.GEMINI)
        },
        "temporal_capability": {
            "any_tool_supports_temporal_filter": _TEMPORAL_MATRIX.any_tool_supports_temporal_filter,
            "tools_returning_timestamped_data": list(_TEMPORAL_MATRIX.tools_returning_timestamped_data),
        },
        "routing": {
            "understanding": {
                "provider": understanding_provider.value,
                "model": configs[understanding_provider].model,
            },
            "planner": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model},
            "investigator": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model},
            "reporter": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model},
        },
        "prompt_versions": {
            "understanding": UNDERSTANDING_PROMPT_VERSION,
            "planner": PLANNER_PROMPT_VERSION,
            "investigator": INVESTIGATOR_PROMPT_VERSION,
            "reporter": REPORTER_PROMPT_VERSION,
        },
        "prompt_digests_sha256": {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in (
                ("understanding", UNDERSTANDING_SYSTEM_PROMPT),
                ("planner", PLANNER_SYSTEM_PROMPT),
                ("investigator", INVESTIGATOR_SYSTEM_PROMPT),
                ("reporter", REPORTER_SYSTEM_PROMPT),
            )
        },
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "completion_policy_version": COMPLETION_POLICY_VERSION,
        "grounding_version": GROUNDING_VERSION,
        "recovery_policy": RECOVERY_POLICY,
        "tool_surface": sorted(tool.name for tool in get_investigator_tools()),
        "max_investigation_steps": 12,
        "max_tool_calls": 8,
        "retry_policy": {"provider_max_attempts": configs[ProviderName.GEMINI].retry.max_attempts},
        "temperature": 0.0,
        "split": SPLIT,
        "sample_count": len(sample_ids),
        "sample_ids": sample_ids,
        "forbidden_splits_not_loaded": ["train", "holdout", "golden"],
        "train_accessed": False,
        "holdout_accessed": False,
        "golden_accessed": False,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_lines(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8"
    )


def load_completed_runs(path: Path) -> list[dict[str, Any]]:
    """Lê os casos já concluídos, tolerando um kill no meio do append.

    O sink é append-only, então a única linha que pode estar truncada é a
    última. Ela é descartada e o caso volta para a fila de pendentes — retomar
    precisa funcionar justamente no cenário em que o processo morreu.
    """

    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    runs: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            if number != len(lines):
                raise
            print(f"AVISO: última linha de {path.name} truncada; o caso será reexecutado.")
    return runs


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliação E2E do Synthetic DEV completo (Etapa 09.5).")
    parser.add_argument("--execute", action="store_true", help="Autoriza chamadas reais a provider e API.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--throttle-seconds", type=float, default=DEFAULT_THROTTLE_SECONDS)
    parser.add_argument("--limit", type=int, default=None, help="Executa no máximo N casos ainda pendentes.")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Executa apenas os casos de SMOKE_SAMPLE_IDS num diretório separado.",
    )
    parser.add_argument(
        "--understanding-provider",
        choices=("groq", "gemini"),
        default="groq",
        help="Provider do Understanding. 'gemini' grava na coorte e2e-full-dev-v2b.",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Recalcula métricas e artefatos a partir de runs.jsonl, sem chamar provider.",
    )
    args = parser.parse_args(argv)

    # A troca do provider do Understanding cria uma coorte separada: experimento,
    # routing e diretorio mudam juntos, para que V2 (Groq) e V2b (Gemini) nunca
    # sejam somadas como se fossem uma unica condicao experimental.
    global EXPERIMENT_VERSION, ROUTING_VERSION
    understanding_provider = ProviderName(args.understanding_provider)
    experiment_dir = OUTPUT_DIR
    if understanding_provider is UNDERSTANDING_FALLBACK["provider"]:
        EXPERIMENT_VERSION = UNDERSTANDING_FALLBACK["experiment_version"]
        ROUTING_VERSION = UNDERSTANDING_FALLBACK["routing_version"]
        experiment_dir = ROOT / "experiments" / EXPERIMENT_VERSION

    load_local_env(ROOT / "api" / ".env")
    configs = default_provider_configs()
    all_samples = load_dev_split()
    # O smoke valida só as correções da etapa e nunca escreve no diretório da
    # rodada completa, para não misturar as duas evidências.
    output_dir = experiment_dir.with_name(experiment_dir.name + "-smoke") if args.smoke else experiment_dir
    samples = (
        tuple(sample for sample in all_samples if sample.sample_id in SMOKE_SAMPLE_IDS)
        if args.smoke
        else all_samples
    )
    samples_by_id = {sample.sample_id: sample for sample in samples}
    sample_ids = [sample.sample_id for sample in samples]

    with TractianClient(RequestContext(), base_url=args.api_base_url) as probe_client:
        coverage_report = audit_coverage(tuple(samples), probe_client)
    coverage_by_sample = {case.sample_id: case for case in coverage_report.cases}
    dataset_report = validate_split_file(
        SPLIT, root=ROOT, coverage_warnings={case.sample_id: case.warnings for case in coverage_report.cases}
    )

    if not dataset_report.valid:
        print(json.dumps({"status": "DATASET_VALIDATION_FAILED", **dataset_report.model_dump(mode="json", exclude={"samples"})}, ensure_ascii=False))
        return 2

    manifest = build_manifest(sample_ids, configs, understanding_provider)
    if args.aggregate_only:
        runs = load_completed_runs(output_dir / "runs.jsonl")
        if not runs:
            print(json.dumps({"status": "NOTHING_TO_AGGREGATE", "output_dir": str(output_dir)}, ensure_ascii=False))
            return 2
        checkpoint = output_dir / "checkpoint.json"
        recorded = (
            json.loads(checkpoint.read_text(encoding="utf-8")).get("run_status") if checkpoint.exists() else None
        )
        status = (
            RunStatus(recorded)
            if recorded
            else (RunStatus.COMPLETED if len(runs) == len(sample_ids) else RunStatus.RUN_PAUSED_PROVIDER_QUOTA)
        )
        aggregate = write_artifacts(
            runs,
            sample_ids=sample_ids,
            samples_by_id=samples_by_id,
            dataset_report=dataset_report,
            coverage_report=coverage_report,
            run_status=status,
            output_dir=output_dir,
        )
        print(
            json.dumps(
                {
                    "status": "AGGREGATED",
                    "run_status": status.value,
                    "executed_cases": len(runs),
                    "terminal": aggregate["e2e"]["terminal_state_counts"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "split": SPLIT,
                    "sample_count": len(sample_ids),
                    "sample_ids": sample_ids,
                    "dataset_valid": dataset_report.valid,
                    "coverage": coverage_report.model_dump(mode="json", exclude={"cases", "probes"}),
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
            )
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    runs_path = output_dir / "runs.jsonl"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        frozen_keys = ("routing", "prompt_versions", "schema_version", "completion_policy_version", "grounding_version", "sample_ids")
        if any(previous.get(key) != manifest.get(key) for key in frozen_keys):
            raise RuntimeError(
                "Retomada recusada: o manifesto existente descreve outra configuração congelada."
            )
    else:
        _write(manifest_path, manifest)

    runs = load_completed_runs(runs_path)
    # §13: a coorte Gemini executa apenas o que a coorte Groq nao mediu. Os
    # `sample_id` ja medidos na V2 saem da fila sem que seus runs sejam copiados
    # para ca — as duas populacoes permanecem em arquivos e manifestos distintos.
    previously_measured: set[str] = set()
    if understanding_provider is UNDERSTANDING_FALLBACK["provider"] and not args.smoke:
        groq_runs = load_completed_runs(ROOT / "experiments" / "e2e-full-dev-v2" / "runs.jsonl")
        latest_groq = {run["sample_id"]: run for run in groq_runs}
        previously_measured = {
            sid
            for sid, run in latest_groq.items()
            if not (run.get("errors") and all(e.get("primary_layer") == PrimaryLayer.PROVIDER.value for e in run["errors"]))
        }
        if previously_measured:
            print(
                f"COORTE: {len(previously_measured)} caso(s) ja medidos com Groq na V2 nao serao repetidos; "
                f"a V2b executa os {len(sample_ids) - len(previously_measured)} restantes."
            )
    # Um caso derrubado pela infraestrutura nunca chegou a ser medido: quota,
    # 503 e timeout do provider são todos a mesma situação. Mantê-lo no artefato
    # como evidência, mas fora de `done`, deixa a retomada refazê-lo. Se houver
    # qualquer causa não-provider junto, o caso foi medido e não se repete.
    infrastructure_blocked = {
        run["sample_id"]
        for run in runs
        if run.get("errors") and all(error.get("primary_layer") == PrimaryLayer.PROVIDER.value for error in run["errors"])
    }
    runs = [run for run in runs if run["sample_id"] not in infrastructure_blocked]
    done = {run["sample_id"] for run in runs}
    if infrastructure_blocked:
        print(
            f"AVISO: {len(infrastructure_blocked)} caso(s) derrubados por infraestrutura do provider "
            f"serão reexecutados: {sorted(infrastructure_blocked)}"
        )
    pending = [sample for sample in samples if sample.sample_id not in done | previously_measured]
    if args.limit is not None:
        pending = pending[: max(0, args.limit)]

    if infrastructure_blocked:
        # Reescreve o arquivo sem as tentativas derrubadas pela infraestrutura,
        # para que a reexecucao nao gere duplicata do mesmo sample_id (§7).
        _write_lines(runs_path, runs)

    run_status = RunStatus.COMPLETED
    providers = {name: create_provider(configs[name]) for name in (ProviderName.GROQ, ProviderName.GEMINI)}
    consecutive_rate_limits = 0
    try:
        with TractianClient(RequestContext(), base_url=args.api_base_url) as client, runs_path.open(
            "a", encoding="utf-8"
        ) as sink:
            for index, sample in enumerate(pending):
                if index or done:
                    sleep(args.throttle_seconds)
                try:
                    record = run_case(
                        sample, providers, client, coverage_by_sample[sample.sample_id], understanding_provider
                    )
                except ProviderQuotaExceeded as exc:
                    run_status = RunStatus.RUN_PAUSED_PROVIDER_QUOTA
                    print(f"RUN_PAUSED_PROVIDER_QUOTA {exc}")
                    break
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                sink.flush()
                runs.append(record)
                if any(error["code"] == EvaluationErrorCode.RATE_LIMIT.value for error in record["errors"]):
                    consecutive_rate_limits += 1
                    if consecutive_rate_limits >= MAX_CONSECUTIVE_RATE_LIMITS:
                        run_status = RunStatus.RUN_PAUSED_PROVIDER_QUOTA
                        print("RUN_PAUSED_PROVIDER_QUOTA consecutive_rate_limits")
                        break
                else:
                    consecutive_rate_limits = 0
                print(
                    f"[{len(runs)}/{len(sample_ids)}] {sample.sample_id} "
                    f"{record['terminal_status']} {round(record['duration_ms'])}ms"
                )
    finally:
        for provider in providers.values():
            provider.close()

    aggregate = write_artifacts(
        runs,
        sample_ids=sample_ids,
        samples_by_id=samples_by_id,
        dataset_report=dataset_report,
        coverage_report=coverage_report,
        run_status=run_status,
        output_dir=output_dir,
    )
    print(
        json.dumps(
            {
                "run_status": run_status.value,
                "executed_cases": len(runs),
                "terminal": aggregate["e2e"]["terminal_state_counts"],
                "grounded_completion_rate": aggregate["e2e"]["grounded_completion_rate"],
                "valid_terminal_state_rate": aggregate["e2e"]["valid_terminal_state_rate"],
                "errors": aggregate["errors"]["by_code"],
                "final_status": aggregate["final_status"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if run_status is RunStatus.COMPLETED else 3


def write_artifacts(
    runs: list[dict[str, Any]],
    *,
    sample_ids: list[str],
    samples_by_id: dict[str, UnderstandingSample],
    dataset_report,
    coverage_report,
    run_status: RunStatus,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Deriva todos os artefatos a partir dos registros já persistidos.

    `runs.jsonl` é a fronteira do experimento congelado; tudo aqui é análise.
    Reagregar não reexecuta nada, então uma rodada retomada e uma rodada
    contínua produzem exatamente o mesmo agregado.
    """

    target = output_dir or OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)

    # Um caso derrubado por cota não foi medido: contá-lo como FAILED atribuiria
    # ao sistema uma falha que pertence ao provider. Ele sai da população das
    # métricas e permanece listado como pendente.
    quota_blocked = [
        run
        for run in runs
        if run.get("errors") and all(error.get("primary_layer") == PrimaryLayer.PROVIDER.value for error in run["errors"])
    ]
    blocked_ids = {run["sample_id"] for run in quota_blocked}
    runs = [run for run in runs if run["sample_id"] not in blocked_ids]
    executed_ids = {run["sample_id"] for run in runs}
    aggregate = {
        "experiment_version": EXPERIMENT_VERSION,
        "run_status": run_status.value,
        "dataset": {
            "split": SPLIT,
            "sample_count": len(sample_ids),
            "measured_cases": len(runs),
            "executed_cases": len(runs),
            "quota_blocked_cases": sorted(blocked_ids),
            "pending_cases": [item for item in sample_ids if item not in executed_ids],
            "coverage_of_split": round(len(runs) / len(sample_ids), 4) if sample_ids else None,
        },
        "e2e": e2e_metrics(runs),
        "understanding": understanding_metrics(runs, samples_by_id),
        "planner": planner_metrics(runs),
        "investigator": investigator_metrics(runs),
        "evidence_and_lineage": lineage_metrics(runs),
        "reporter": reporter_metrics(runs),
        "providers": provider_metrics(runs),
        "errors": error_metrics(runs),
        "data_coverage_correlation": coverage_correlation(runs),
        "contract_failsafe_cases": sum(bool(run.get("contract_failsafe")) for run in runs),
        "security": {
            "action_decisions": sum(
                decision["output"]["type"] == "action"
                for run in runs
                for decision in run["components"].get("investigator", [])
            ),
            "action_tools_executed": sum(
                event.get("operation_kind") == "ACTION"
                for run in runs
                for event in run["trace"]
            ),
            "train_accessed": False,
            "holdout_accessed": False,
            "golden_accessed": False,
        },
    }

    component_rows = [
        {"component": name, **payload}
        for name, payload in (
            ("understanding", {"cases_reached": sum("understanding" in run["components"] for run in runs)}),
            ("planner", {"cases_reached": sum("planner" in run["components"] for run in runs)}),
            ("investigator", {"cases_reached": sum("investigator" in run["components"] for run in runs)}),
            ("reporter", {"cases_reached": sum("reporter" in run["components"] for run in runs)}),
        )
    ]

    coverage_payload = coverage_report.model_dump(mode="json")
    gates = evaluate_gates(aggregate, coverage_payload)
    decisions = training_decisions(aggregate, coverage_payload)
    status = overall_status(gates, aggregate)
    aggregate["quality_gates"] = [gate.model_dump(mode="json") for gate in gates]
    aggregate["training_assessment"] = [item.model_dump(mode="json") for item in decisions]
    aggregate["final_status"] = status

    _write(
        target / "quality-gates.json",
        {
            "experiment_version": EXPERIMENT_VERSION,
            "final_status": status,
            "gates": [gate.model_dump(mode="json") for gate in gates],
            "training_assessment": [item.model_dump(mode="json") for item in decisions],
        },
    )
    _write(target / "aggregate-metrics.json", aggregate)
    _write(target / "dataset-validation.json", dataset_report.model_dump(mode="json"))
    _write(target / "data-coverage.json", coverage_payload)
    _write(target / "showcase.json", build_showcase(runs))
    _write(target / "needs-human-review.json", {"cases": needs_human_review(runs)})
    _write_lines(target / "component-metrics.jsonl", component_rows)
    _write_lines(
        target / "errors.jsonl",
        [
            {"run_id": run["run_id"], "sample_id": run["sample_id"], "terminal_status": run["terminal_status"], "errors": run["errors"]}
            for run in runs
            if run["errors"]
        ],
    )
    _write(
        target / "checkpoint.json",
        {
            "run_status": run_status.value,
            "executed_cases": len(runs),
            "executed_sample_ids": sorted(executed_ids),
            "pending_sample_ids": [item for item in sample_ids if item not in executed_ids],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return aggregate


if __name__ == "__main__":
    raise SystemExit(main())
