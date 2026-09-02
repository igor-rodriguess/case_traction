"""Fronteira comum e determinística de execução observável das tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from itertools import count
from time import perf_counter
from typing import TypeAlias

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from app.integrations.tractian_client import ClientResult, OperationKind, TractianClient
from app.observability.ledger import EvidenceLedger
from app.observability.models import (
    ClientErrorSnapshot,
    ClientResultSnapshot,
    EvidenceRecord,
    FailureSnapshot,
    TraceEvent,
    TraceEventType,
)
from app.observability.trace import ExecutionTrace
from app.tools.base import ToolDefinition


Clock: TypeAlias = Callable[[], datetime]
MonotonicClock: TypeAlias = Callable[[], float]
IdFactory: TypeAlias = Callable[[], str]

_JSON_ADAPTER = TypeAdapter(JsonValue)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_snapshot(value: object) -> JsonValue:
    """Valida e copia profundamente um valor do contrato JSON."""

    return _JSON_ADAPTER.validate_python(value)


def _result_snapshot(result: ClientResult) -> ClientResultSnapshot:
    error = None
    if result.error is not None:
        error = ClientErrorSnapshot(
            kind=result.error.kind,
            message=result.error.message,
            code=result.error.code,
        )
    return ClientResultSnapshot(
        operation=result.operation,
        operation_kind=result.operation_kind,
        method=result.method,
        path=result.path,
        transport_ok=result.transport_ok,
        status_code=result.status_code,
        evidence_status=result.evidence_status,
        data=_json_snapshot(result.data),
        notes=result.notes,
        error=error,
    )


class TrackedToolExecutor:
    """Executa uma ToolDefinition e registra Trace/Ledger sem raciocínio.

    O executor observa qualquer capability que uma camada superior já tenha
    autorizado. Ele não concede autorização e não altera execution_policy.
    """

    def __init__(
        self,
        client: TractianClient,
        trace: ExecutionTrace,
        ledger: EvidenceLedger,
        *,
        clock: Clock = _utc_now,
        monotonic_clock: MonotonicClock = perf_counter,
        call_id_factory: IdFactory | None = None,
        evidence_id_factory: IdFactory | None = None,
    ) -> None:
        if trace.trace_id != ledger.trace_id:
            raise ValueError("Trace e Evidence Ledger devem compartilhar o trace_id.")
        self._client = client
        self._trace = trace
        self._ledger = ledger
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        call_sequence = count(1)
        evidence_sequence = count(1)
        self._call_id_factory = call_id_factory or (
            lambda: f"{trace.trace_id}:call:{next(call_sequence):06d}"
        )
        self._evidence_id_factory = evidence_id_factory or (
            lambda: f"{trace.trace_id}:evidence:{next(evidence_sequence):06d}"
        )

    def execute(
        self,
        tool: ToolDefinition,
        arguments: Mapping[str, object] | BaseModel,
    ) -> ClientResult:
        call_id = self._call_id_factory()
        safe_arguments = self._safe_arguments(tool, arguments)
        started_at = self._clock()
        started_monotonic = self._monotonic_clock()
        self._trace.append(
            self._event(
                tool=tool,
                call_id=call_id,
                event_type=TraceEventType.TOOL_STARTED,
                timestamp=started_at,
                arguments=safe_arguments,
            )
        )

        try:
            validated = tool.input_schema.model_validate(arguments)
            validated_arguments = _json_snapshot(validated.model_dump(mode="json", exclude_none=True))
            result = tool.invoke(self._client, validated)
            snapshot = _result_snapshot(result)
        except Exception as exc:
            duration_ms = self._duration_ms(started_monotonic)
            failure_message = (
                "Argumentos inválidos para o schema da tool."
                if isinstance(exc, ValidationError)
                else "Falha inesperada durante a execução da tool."
            )
            self._trace.append(
                self._event(
                    tool=tool,
                    call_id=call_id,
                    event_type=TraceEventType.TOOL_FAILED,
                    timestamp=self._clock(),
                    arguments=safe_arguments,
                    duration_ms=duration_ms,
                    failure=FailureSnapshot(
                        exception_type=type(exc).__name__,
                        message=failure_message,
                    ),
                )
            )
            raise

        completed = self._trace.append(
            self._event(
                tool=tool,
                call_id=call_id,
                event_type=TraceEventType.TOOL_COMPLETED,
                timestamp=self._clock(),
                arguments=validated_arguments,
                duration_ms=self._duration_ms(started_monotonic),
                result=snapshot,
            )
        )
        self._record_evidence(tool, completed, snapshot)
        return result

    def _record_evidence(
        self,
        tool: ToolDefinition,
        completed: TraceEvent,
        result: ClientResultSnapshot,
    ) -> None:
        if tool.operation_kind is not OperationKind.READ or result.evidence_status is None:
            return
        self._ledger.append(
            EvidenceRecord(
                evidence_id=self._evidence_id_factory(),
                trace_id=self._trace.trace_id,
                source_call_id=completed.call_id,
                source_trace_sequence=completed.sequence,
                sequence=1,
                collected_at=completed.timestamp,
                tool_name=tool.name,
                client_operation=tool.client_operation,
                arguments=completed.arguments,
                evidence_status=result.evidence_status,
                transport_ok=result.transport_ok,
                status_code=result.status_code,
                method=result.method,
                path=result.path,
                data=result.data,
                notes=result.notes,
            )
        )

    def _duration_ms(self, started_monotonic: float) -> float:
        return round(max(0.0, self._monotonic_clock() - started_monotonic) * 1000, 3)

    def _event(
        self,
        *,
        tool: ToolDefinition,
        call_id: str,
        event_type: TraceEventType,
        timestamp: datetime,
        arguments: dict[str, JsonValue],
        duration_ms: float | None = None,
        result: ClientResultSnapshot | None = None,
        failure: FailureSnapshot | None = None,
    ) -> TraceEvent:
        return TraceEvent(
            trace_id=self._trace.trace_id,
            call_id=call_id,
            sequence=1,
            event_type=event_type,
            timestamp=timestamp,
            tool_name=tool.name,
            category=tool.category,
            operation_kind=tool.operation_kind,
            client_operation=tool.client_operation,
            arguments=arguments,
            duration_ms=duration_ms,
            result=result,
            failure=failure,
        )

    @staticmethod
    def _safe_arguments(
        tool: ToolDefinition,
        arguments: Mapping[str, object] | BaseModel,
    ) -> dict[str, JsonValue]:
        raw = arguments.model_dump(mode="json") if isinstance(arguments, BaseModel) else dict(arguments)
        allowed = {key: value for key, value in raw.items() if key in tool.input_schema.model_fields}
        try:
            snapshot = _json_snapshot(allowed)
        except ValidationError:
            return {}
        if not isinstance(snapshot, dict):
            return {}
        return snapshot
