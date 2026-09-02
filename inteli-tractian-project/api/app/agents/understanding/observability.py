"""Registro de invocação de componente probabilístico.

`TraceEvent` (Etapa 04) modela a execução de uma *tool*: exige `tool_name`,
`category`, `operation_kind` e `client_operation`, e é `extra="forbid"`. Uma
invocação de modelo não possui nenhum desses conceitos. Em vez de afrouxar o
contrato do Trace ou de fabricar campos de tool, esta etapa adiciona um registro
irmão que reusa a mesma base imutável e as mesmas convenções de `trace_id`,
sequência e timestamp com timezone.

Duas regras explícitas da Etapa 05:

- **Não** se registra chain-of-thought. O registro guarda a saída estruturada
  final, nunca o raciocínio.
- **Não** se cria `EvidenceRecord`. Interpretação de uma mensagem do cliente não
  é evidência vinda da API e não pode entrar no Evidence Ledger.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from threading import Lock

from pydantic import Field, JsonValue, field_validator

from app.observability.models import AuditModel


class AgentComponent(str, Enum):
    UNDERSTANDING = "understanding_agent"


class AgentInvocationStatus(str, Enum):
    COMPLETED = "completed"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"


class AgentFailureSnapshot(AuditModel):
    exception_type: str
    message: str


class AgentTokenUsage(AuditModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    """Somente quando o provedor fornece dados objetivos de preço. Nunca estimado."""


class AgentInvocationRecord(AuditModel):
    """Uma chamada de um componente probabilístico, do início ao fim."""

    trace_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    component: AgentComponent
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0)
    status: AgentInvocationStatus
    input: JsonValue
    output: JsonValue = None
    """Saída estruturada validada. `None` quando a validação falhou."""
    usage: AgentTokenUsage = AgentTokenUsage()
    failure: AgentFailureSnapshot | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp deve possuir timezone.")
        return value


class AgentInvocationLog:
    """Log append-only de invocações de agente para um único `trace_id`."""

    def __init__(self, trace_id: str) -> None:
        if not trace_id.strip():
            raise ValueError("trace_id não pode ser vazio.")
        self._trace_id = trace_id
        self._records: list[AgentInvocationRecord] = []
        self._lock = Lock()

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def records(self) -> tuple[AgentInvocationRecord, ...]:
        with self._lock:
            return tuple(record.model_copy(deep=True) for record in self._records)

    def append(self, record: AgentInvocationRecord) -> AgentInvocationRecord:
        with self._lock:
            if record.trace_id != self._trace_id:
                raise ValueError("Registro pertence a outro trace_id.")
            recorded = record.model_copy(update={"sequence": len(self._records) + 1})
            self._records.append(recorded)
            return recorded.model_copy(deep=True)

    def as_dicts(self) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in self.records]
