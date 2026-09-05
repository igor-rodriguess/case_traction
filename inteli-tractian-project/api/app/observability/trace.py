"""Execution Trace cronológico e append-only em memória."""

from __future__ import annotations

from threading import Lock
from datetime import datetime, timezone

from app.observability.models import TraceEvent, TraceEventType


class ExecutionTrace:
    """Armazena eventos ordenados de uma única execução."""

    def __init__(self, trace_id: str) -> None:
        if not trace_id.strip():
            raise ValueError("trace_id não pode ser vazio.")
        self._trace_id = trace_id
        self._events: list[TraceEvent] = []
        self._lock = Lock()

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(event.model_copy(deep=True) for event in self._events)

    def append(self, event: TraceEvent) -> TraceEvent:
        with self._lock:
            if event.trace_id != self._trace_id:
                raise ValueError("Evento pertence a outro trace_id.")
            expected_sequence = len(self._events) + 1
            recorded = event.model_copy(update={"sequence": expected_sequence})
            self._events.append(recorded)
            return recorded.model_copy(deep=True)

    def as_dicts(self) -> list[dict[str, object]]:
        return [event.model_dump(mode="json") for event in self.events]

    def append_operational(
        self,
        event_type: TraceEventType,
        event_id: str,
        *,
        details: dict[str, object] | None = None,
        timestamp: datetime | None = None,
    ) -> TraceEvent:
        """Registra somente metadados operacionais, nunca raciocínio privado."""

        return self.append(TraceEvent(
            trace_id=self._trace_id,
            call_id=event_id,
            sequence=1,
            event_type=event_type,
            timestamp=timestamp or datetime.now(timezone.utc),
            details=details or {},
        ))
