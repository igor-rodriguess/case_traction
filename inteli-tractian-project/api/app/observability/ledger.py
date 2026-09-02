"""Evidence Ledger correlacionado ao Execution Trace."""

from __future__ import annotations

from threading import Lock

from app.observability.models import EvidenceRecord


class EvidenceLedger:
    """Coleção append-only de evidências produzidas por READ tools."""

    def __init__(self, trace_id: str) -> None:
        if not trace_id.strip():
            raise ValueError("trace_id não pode ser vazio.")
        self._trace_id = trace_id
        self._records: list[EvidenceRecord] = []
        self._lock = Lock()

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        with self._lock:
            return tuple(record.model_copy(deep=True) for record in self._records)

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            if record.trace_id != self._trace_id:
                raise ValueError("Evidência pertence a outro trace_id.")
            expected_sequence = len(self._records) + 1
            recorded = record.model_copy(update={"sequence": expected_sequence})
            self._records.append(recorded)
            return recorded.model_copy(deep=True)

    def as_dicts(self) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in self.records]
