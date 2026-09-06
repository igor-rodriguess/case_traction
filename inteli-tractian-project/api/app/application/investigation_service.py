"""Serviço de aplicação da investigação.

Coordena o ciclo de vida — cria, executa, avalia, persiste — sem tomar nenhuma
decisão que pertença ao domínio. O pipeline decide; o Eval julga; a política
final resolve. Aqui só se organiza a ordem e se garante que cada etapa chegue ao
banco no momento em que passa a ser verdade.

O ponto que sustenta a auditoria: a persistência acontece **por checkpoint**,
não no fim. Se a execução morrer no Investigator, o banco continua mostrando a
solicitação, o entendimento, o plano, a trajetória até ali e as evidências já
coletadas. Uma investigação parcial é um registro de auditoria válido.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from app.agents.understanding.schemas import AvailableContext, UnderstandingInput
from app.application.evaluation_runner import EvaluationOutcome, evaluate_run
from app.application.pipeline import PipelineConfig, PipelineResult, run_pipeline
from app.investigation.state import InvestigationState
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from app.persistence import PersistenceError, ProgressiveWriter, RunIdentity

logger = logging.getLogger(__name__)

TERMINAL_STATES = {
    "GROUNDED_COMPLETION",
    "SAFE_ESCALATION",
    "AWAITING_REQUIRED_INFORMATION",
    "FAILED",
}

# A avaliação só faz sentido quando houve trabalho para julgar.
EVALUABLE = {"GROUNDED_COMPLETION", "SAFE_ESCALATION"}


@dataclass(frozen=True)
class CreatedInvestigation:
    case_id: str
    run_id: str
    phase: str
    created_at: datetime


@dataclass(frozen=True)
class NewInvestigation:
    """Entrada mínima que o console envia."""

    message: str
    tenant_ref: str | None = None
    asset_refs: tuple[str, ...] = ()
    role: str | None = None


def _snapshot(state: InvestigationState, *, terminal_state: str | None = None) -> dict[str, Any]:
    """Serializa o estado na forma que a persistência consome."""
    payload = state.model_dump(mode="json")
    understanding = payload.get("understanding")
    conclusion = payload.get("conclusion")

    asset_refs = (payload.get("request") or {}).get("available_context", {}).get("asset_refs") or []
    entities = ((understanding or {}).get("entities") or {}).get("assets") or []
    asset_id = (entities or asset_refs or [None])[0]

    snapshot: dict[str, Any] = {
        "case_id": payload["case_id"],
        "request_id": payload["request_id"],
        "trace_id": payload["trace_id"],
        "request_message": payload["request"]["message"],
        "request_context": payload["request"].get("available_context") or {},
        "request_class": (understanding or {}).get("request_class"),
        "phase": payload.get("phase"),
        "terminal_state": terminal_state,
        "understanding": understanding,
        "plan": payload.get("plan"),
        "understanding_source": payload.get("understanding_source"),
        "planner_source": payload.get("planner_source"),
        "reporter_source": payload.get("reporter_source"),
        "asset_id": asset_id,
        "investigation_step_count": payload.get("investigation_step_count"),
        "tool_call_count": payload.get("tool_call_count"),
        "trace": (payload.get("trace") or {}).get("events") or [],
        "evidence": (payload.get("evidence_ledger") or {}).get("records") or [],
        "conclusion": conclusion,
        "report": payload.get("technical_report"),
        "human_handoff": payload.get("human_handoff"),
    }

    error = payload.get("error")
    if error:
        snapshot["error_code"] = error.get("code")
        snapshot["error_summary"] = error.get("summary")
        snapshot["error_can_continue"] = error.get("can_continue")

    snapshot["evidence_quality"] = _evidence_quality(snapshot["evidence"], snapshot["conclusion"])
    snapshot["evidence_quality_reasons"] = _quality_reasons(
        snapshot["evidence"], snapshot["conclusion"]
    )
    return snapshot


def _evidence_quality(evidence: list[dict], conclusion: dict | None) -> str:
    """Qualidade derivada do estado semântico, não de opinião."""
    if not evidence:
        return "INSUFFICIENT_EVIDENCE"
    complete = sum(1 for e in evidence if e.get("evidence_status") == "complete")
    degraded = len(evidence) - complete
    if conclusion and degraded == 0:
        return "HIGH"
    if complete and degraded <= complete:
        return "MEDIUM"
    return "LOW"


def _quality_reasons(evidence: list[dict], conclusion: dict | None) -> list[str]:
    if not evidence:
        return ["Nenhuma evidência foi coletada"]
    complete = sum(1 for e in evidence if e.get("evidence_status") == "complete")
    degraded = len(evidence) - complete
    claims = len((conclusion or {}).get("claims") or [])
    reasons = [f"{complete} de {len(evidence)} evidências completas"]
    if degraded:
        reasons.append(f"{degraded} evidência(s) com estado degradado")
    if claims:
        reasons.append(f"{claims} afirmação(ões) fundamentada(s)")
    return reasons


class InvestigationService:
    """Ciclo de vida completo de uma investigação."""

    def __init__(
        self,
        *,
        config: PipelineConfig | None = None,
        providers: Mapping[ProviderName, Any] | None = None,
        evaluate: bool = True,
    ) -> None:
        self._config = config or PipelineConfig()
        self._providers = providers
        self._evaluate = evaluate

    # ------------------------------------------------------------------

    def _resolve_providers(self) -> Mapping[ProviderName, Any]:
        if self._providers is not None:
            return self._providers
        configs = default_provider_configs()
        return {name: create_provider(configs[name]) for name in configs if configs[name].enabled}

    def create(self, request: NewInvestigation) -> CreatedInvestigation:
        """Registra o caso e devolve o identificador. Rápido de propósito.

        A execução continua depois; o console precisa do id para abrir a página.
        """
        suffix = uuid4().hex[:8]
        case_id = f"CASE-{datetime.now(timezone.utc):%Y%m%d}-{suffix}"
        identity = RunIdentity(
            case_id=case_id,
            request_id=f"req_{suffix}",
            trace_id=f"trace_{suffix}",
            request_message=request.message,
            request_context={
                "tenant_ref": request.tenant_ref,
                "asset_refs": list(request.asset_refs),
                "role": request.role,
            },
        )
        writer = ProgressiveWriter()
        run_id = writer.open_run(identity)
        return CreatedInvestigation(
            case_id=case_id,
            run_id=run_id,
            phase="received",
            created_at=datetime.now(timezone.utc),
        )

    def execute(self, created: CreatedInvestigation, request: NewInvestigation) -> PipelineResult:
        """Roda o pipeline real, persistindo a cada etapa concluída."""
        writer = ProgressiveWriter()
        writer.open_run(
            RunIdentity(
                case_id=created.case_id,
                request_id=f"req_{created.case_id}",
                trace_id=f"trace_{created.case_id}",
                request_message=request.message,
            )
        )

        def checkpoint(stage: str, state: InvestigationState) -> None:
            try:
                writer.sync(_snapshot(state))
            except PersistenceError as exc:
                # Uma falha de gravação não pode derrubar a investigação em curso:
                # o próximo checkpoint reenvia o que faltou.
                logger.warning("checkpoint %s não persistiu: %s", stage, exc)

        understanding_input = UnderstandingInput(
            message=request.message,
            available_context=AvailableContext(
                tenant_ref=request.tenant_ref,
                asset_refs=request.asset_refs,
                role=request.role,
                permissions=(),
            ),
        )

        result = run_pipeline(
            understanding_input,
            providers=self._resolve_providers(),
            config=self._config,
            case_id=created.case_id,
            request_id=f"req_{created.case_id}",
            trace_id=f"trace_{created.case_id}",
            checkpoint=checkpoint,
        )

        # Último sync com o estado terminal já resolvido.
        try:
            writer.sync(_snapshot(result.state, terminal_state=result.terminal_state))
            writer.finish(
                terminal_state=result.terminal_state, duration_ms=result.duration_ms
            )
        except PersistenceError as exc:
            logger.error("não foi possível fechar a execução %s: %s", created.case_id, exc)

        if self._evaluate and result.terminal_state in EVALUABLE:
            self._run_evaluation(writer, created.case_id, result)

        return result

    def _run_evaluation(
        self, writer: ProgressiveWriter, case_id: str, result: PipelineResult
    ) -> EvaluationOutcome | None:
        """Avaliação pós-execução, persistida num commit atômico."""
        try:
            outcome = evaluate_run(result.state, terminal_state=result.terminal_state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("avaliação de %s falhou: %s", case_id, exc)
            return None

        try:
            writer.record_evaluation(outcome.as_payload())
        except PersistenceError as exc:
            logger.error("avaliação de %s não persistiu: %s", case_id, exc)
            return None

        # Revisão exigida gera encaminhamento persistido, se ainda não houver.
        if outcome.decision.human_review_required:
            try:
                writer.sync(
                    {
                        "case_id": case_id,
                        "human_handoff": {
                            "handoff_id": f"handoff_{case_id}",
                            "reason_codes": [
                                reason.code.value if hasattr(reason.code, "value") else reason.code
                                for reason in outcome.decision.review_reasons
                            ]
                            or ["HUMAN_REVIEW_REQUIRED"],
                            "evidence_ids": [],
                            "missing_information": [
                                reason.detail for reason in outcome.decision.review_reasons
                            ],
                            "suggested_next_step": outcome.decision.headline,
                        },
                    }
                )
            except PersistenceError as exc:
                logger.warning("encaminhamento de %s não persistiu: %s", case_id, exc)
        return outcome

    def run(self, request: NewInvestigation) -> tuple[CreatedInvestigation, PipelineResult]:
        """Cria e executa em sequência. Usado por scripts e testes."""
        created = self.create(request)
        return created, self.execute(created, request)
