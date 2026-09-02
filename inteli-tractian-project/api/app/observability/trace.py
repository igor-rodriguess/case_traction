"""Execution Trace cronológico e append-only em memória."""

from __future__ import annotations

from threading import Lock

from app.observability.models import TraceEvent


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
