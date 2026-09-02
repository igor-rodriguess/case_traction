"""Understanding Agent — baseline prompt-only.

Responsabilidade única: transformar uma solicitação do cliente em uma
representação estruturada do problema.

O agente é deliberadamente pobre em dependências. Ele recebe um provider de
modelo e nada mais. Não recebe `TractianClient`, não recebe `ToolDefinition`,
não recebe `TrackedToolExecutor` e não recebe `EvidenceLedger` — por construção
não há como ele consultar a API, chamar tool ou executar ACTION.

Interface pública: `understand_request(request) -> UnderstandingInvocation`.
Compatível com um futuro node de LangGraph, mas LangGraph não é usado aqui.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from itertools import count
from time import perf_counter
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from app.agents.understanding.observability import (
    AgentComponent,
    AgentFailureSnapshot,
    AgentInvocationRecord,
    AgentInvocationStatus,
    AgentTokenUsage,
)
from app.agents.understanding.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.understanding.provider import (
    ModelInvocationError,
    ModelResponse,
    StructuredModelProvider,
)
from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput


Clock: TypeAlias = Callable[[], datetime]
MonotonicClock: TypeAlias = Callable[[], float]

_JSON_ADAPTER = TypeAdapter(JsonValue)

OUTPUT_JSON_SCHEMA: dict[str, JsonValue] = UnderstandingOutput.model_json_schema()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UnderstandingInvocation(BaseModel):
    """Resultado de uma chamada: saída validada ou falha, sempre com registro."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    record: AgentInvocationRecord
    output: UnderstandingOutput | None = None
    raw_content: JsonValue = None
    """Conteúdo bruto do provedor, preservado quando a validação falha."""

    @property
    def ok(self) -> bool:
        return self.output is not None

    @property
    def schema_valid(self) -> bool:
        return self.record.status is AgentInvocationStatus.COMPLETED


class UnderstandingAgent:
    """Componente isolado de compreensão de solicitações."""

    component = AgentComponent.UNDERSTANDING
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        provider: StructuredModelProvider,
        *,
        trace_id: str,
        clock: Clock = _utc_now,
        monotonic_clock: MonotonicClock = perf_counter,
        invocation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not trace_id.strip():
            raise ValueError("trace_id não pode ser vazio.")
        self._provider = provider
        self._trace_id = trace_id
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        sequence = count(1)
        self._invocation_id_factory = invocation_id_factory or (
            lambda: f"{trace_id}:agent:{next(sequence):06d}"
        )

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def understand_request(self, request: UnderstandingInput) -> UnderstandingInvocation:
        """Interpreta uma solicitação. Nunca levanta por saída inválida do modelo."""

        invocation_id = self._invocation_id_factory()
        started_at = self._clock()
        started_monotonic = self._monotonic_clock()
        input_snapshot = _JSON_ADAPTER.validate_python(request.model_dump(mode="json"))

        try:
            response = self._provider.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(request),
                json_schema=OUTPUT_JSON_SCHEMA,
            )
        except Exception as exc:
            return UnderstandingInvocation(
                record=self._record(
                    invocation_id=invocation_id,
                    model_id=getattr(self._provider, "model_id", "unknown"),
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                    status=AgentInvocationStatus.PROVIDER_ERROR,
                    input_snapshot=input_snapshot,
                    failure=AgentFailureSnapshot(
                        exception_type=type(exc).__name__,
                        message=self._safe_message(exc),
                    ),
                )
            )

        # Sem loop de retry nesta etapa: uma saída inválida é registrada como
        # inválida. Nenhum valor é inventado para "consertar" o output.
        try:
            output = UnderstandingOutput.model_validate(response.content)
        except ValidationError as exc:
            return UnderstandingInvocation(
                record=self._record(
                    invocation_id=invocation_id,
                    model_id=response.model_id,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                    status=AgentInvocationStatus.INVALID_OUTPUT,
                    input_snapshot=input_snapshot,
                    usage=self._usage(response),
                    failure=AgentFailureSnapshot(
                        exception_type=type(exc).__name__,
                        message=self._validation_message(exc),
                    ),
                ),
                raw_content=self._safe_snapshot(response.content),
            )

        return UnderstandingInvocation(
            record=self._record(
                invocation_id=invocation_id,
                model_id=response.model_id,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status=AgentInvocationStatus.COMPLETED,
                input_snapshot=input_snapshot,
                usage=self._usage(response),
                output_snapshot=_JSON_ADAPTER.validate_python(output.model_dump(mode="json")),
            ),
            output=output,
            raw_content=self._safe_snapshot(response.content),
        )

    def _record(
        self,
        *,
        invocation_id: str,
        model_id: str,
        started_at: datetime,
        started_monotonic: float,
        status: AgentInvocationStatus,
        input_snapshot: JsonValue,
        usage: AgentTokenUsage | None = None,
        output_snapshot: JsonValue = None,
        failure: AgentFailureSnapshot | None = None,
    ) -> AgentInvocationRecord:
        return AgentInvocationRecord(
            trace_id=self._trace_id,
            invocation_id=invocation_id,
            sequence=1,
            component=self.component,
            model_id=model_id,
            prompt_version=self.prompt_version,
            started_at=started_at,
            completed_at=self._clock(),
            duration_ms=round(max(0.0, self._monotonic_clock() - started_monotonic) * 1000, 3),
            status=status,
            input=input_snapshot,
            output=output_snapshot,
            usage=usage or AgentTokenUsage(),
            failure=failure,
        )

    @staticmethod
    def _usage(response: ModelResponse) -> AgentTokenUsage:
        # `estimated_cost_usd` fica ausente: o provider não fornece preço, e
        # custo não é inventado.
        return AgentTokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
        )

    @staticmethod
    def _safe_snapshot(content: object) -> JsonValue:
        try:
            return _JSON_ADAPTER.validate_python(content)
        except ValidationError:
            return None

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        if isinstance(exc, ModelInvocationError):
            return "Falha do provedor de modelo durante a invocação."
        return "Falha inesperada durante a invocação do modelo."

    @staticmethod
    def _validation_message(exc: ValidationError) -> str:
        """Resume os erros sem repetir valores produzidos pelo modelo."""

        locations = sorted(
            {".".join(str(part) for part in error["loc"]) or "<root>" for error in exc.errors()}
        )
        types = sorted({error["type"] for error in exc.errors()})
        return f"Saída inválida para UnderstandingOutput; campos={locations}; tipos={types}"


def understand_request(
    request: UnderstandingInput,
    *,
    provider: StructuredModelProvider,
    trace_id: str,
) -> UnderstandingInvocation:
    """Fachada de uma chamada, para uso futuro como node de grafo."""

    return UnderstandingAgent(provider, trace_id=trace_id).understand_request(request)
