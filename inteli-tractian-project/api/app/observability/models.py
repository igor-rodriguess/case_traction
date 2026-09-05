"""Modelos imutáveis para rastreabilidade de execução e evidências."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.integrations.tractian_client import ClientErrorKind, EvidenceStatus, OperationKind


class AuditModel(BaseModel):
    """Base estrita e imutável dos registros de auditoria."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TraceEventType(str, Enum):
    LLM_DECISION_PRODUCED = "llm_decision_produced"
    DECISION_VALIDATED = "decision_validated"
    DECISION_ACCEPTED = "decision_accepted"
    DECISION_REJECTED = "decision_rejected"
    TOOL_REQUESTED = "tool_requested"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    CONCLUSION_CREATED = "conclusion_created"
    REPORTER_STARTED = "reporter_started"
    REPORTER_COMPLETED = "reporter_completed"
    REPORTER_FAILED = "reporter_failed"


class ClientErrorSnapshot(AuditModel):
    kind: ClientErrorKind
    message: str
    code: str | None = None


class ClientResultSnapshot(AuditModel):
    operation: str
    operation_kind: OperationKind
    method: str
    path: str
    transport_ok: bool
    status_code: int | None
    evidence_status: EvidenceStatus | None
    data: JsonValue = None
    notes: str | None = None
    error: ClientErrorSnapshot | None = None


class FailureSnapshot(AuditModel):
    exception_type: str
    message: str


class TraceEvent(AuditModel):
    trace_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    event_type: TraceEventType
    timestamp: datetime
    tool_name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1)
    operation_kind: OperationKind | None = None
    client_operation: str | None = Field(default=None, min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    duration_ms: float | None = Field(default=None, ge=0)
    result: ClientResultSnapshot | None = None
    failure: FailureSnapshot | None = None

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp deve possuir timezone.")
        return value

    @model_validator(mode="after")
    def tool_events_require_tool_metadata(self) -> "TraceEvent":
        if self.event_type in {TraceEventType.TOOL_STARTED, TraceEventType.TOOL_COMPLETED, TraceEventType.TOOL_FAILED}:
            if not all((self.tool_name, self.category, self.operation_kind, self.client_operation)):
                raise ValueError("Eventos de tool exigem metadados completos da operação.")
        return self


class EvidenceRecord(AuditModel):
    evidence_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    source_call_id: str = Field(min_length=1)
    source_trace_sequence: int = Field(ge=1)
    sequence: int = Field(ge=1)
    collected_at: datetime
    tool_name: str = Field(min_length=1)
    client_operation: str = Field(min_length=1)
    arguments: dict[str, JsonValue]
    evidence_status: EvidenceStatus
    transport_ok: bool
    status_code: int | None
    method: str = Field(min_length=1)
    path: str = Field(min_length=1)
    data: JsonValue = None
    notes: str | None = None

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at deve possuir timezone.")
        return value
