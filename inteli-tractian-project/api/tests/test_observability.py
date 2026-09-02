"""Testes determinísticos do Execution Trace e Evidence Ledger, sem LLM."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.integrations.tractian_client import (
    ClientError,
    ClientErrorKind,
    ClientResult,
    EvidenceStatus,
    OperationKind,
    TractianClient,
)
from app.observability import EvidenceLedger, ExecutionTrace, TraceEventType, TrackedToolExecutor
from app.tools import get_action_tools, get_investigator_tools


BASE_TIME = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def tool_by_name(name: str):
    return next(tool for tool in (*get_investigator_tools(), *get_action_tools()) if tool.name == name)


def read_result(
    status: EvidenceStatus | None = EvidenceStatus.COMPLETE,
    *,
    data: object = None,
    transport_ok: bool = True,
    error: ClientError | None = None,
) -> ClientResult:
    return ClientResult(
        operation="get_asset",
        operation_kind=OperationKind.READ,
        method="GET",
        path="/assets/asset_1",
        transport_ok=transport_ok,
        status_code=200 if transport_ok else None,
        evidence_status=status,
        data={"id": "asset_1"} if data is None else data,
        notes="resultado observado",
        error=error,
    )


def action_result() -> ClientResult:
    return ClientResult(
        operation="reprocess_analysis",
        operation_kind=OperationKind.ACTION,
        method="POST",
        path="/analyses/an_1/reprocess",
        transport_ok=True,
        status_code=200,
        evidence_status=None,
        data={"accepted": True, "action_id": "act_1"},
    )


def iterator_factory(values: list):
    iterator: Iterator = iter(values)
    return lambda: next(iterator)


def executor_for(
    client: TractianClient,
    *,
    trace_id: str = "trace_1",
    times: list[datetime] | None = None,
    monotonic: list[float] | None = None,
):
    trace = ExecutionTrace(trace_id)
    ledger = EvidenceLedger(trace_id)
    executor = TrackedToolExecutor(
        client,
        trace,
        ledger,
        clock=iterator_factory(times or [BASE_TIME, BASE_TIME + timedelta(milliseconds=125)]),
        monotonic_clock=iterator_factory(monotonic or [10.0, 10.125]),
        call_id_factory=lambda: "call_1",
        evidence_id_factory=lambda: "evidence_1",
    )
    return executor, trace, ledger


def test_tracked_executor_records_start_completion_duration_and_result() -> None:
    client = Mock(spec=TractianClient)
    expected = read_result(data={"id": "asset_1", "criticality": "high"})
    client.get_asset.return_value = expected
    executor, trace, ledger = executor_for(client)

    returned = executor.execute(tool_by_name("get_asset_context"), {"asset_id": " asset_1 "})

    assert returned is expected
    assert [event.event_type for event in trace.events] == [
        TraceEventType.TOOL_STARTED,
        TraceEventType.TOOL_COMPLETED,
    ]
    started, completed = trace.events
    assert (started.sequence, completed.sequence) == (1, 2)
    assert started.call_id == completed.call_id == "call_1"
    assert completed.arguments == {"asset_id": "asset_1"}
    assert completed.duration_ms == 125.0
    assert completed.result is not None
    assert completed.result.evidence_status is EvidenceStatus.COMPLETE
    assert completed.result.data == {"id": "asset_1", "criticality": "high"}
    assert len(ledger.records) == 1


@pytest.mark.parametrize("status", list(EvidenceStatus))
def test_every_semantic_status_becomes_correlated_evidence(status: EvidenceStatus) -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(status)
    executor, trace, ledger = executor_for(client)

    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    evidence = ledger.records[0]
    completed = trace.events[1]
    assert evidence.evidence_status is status
    assert evidence.trace_id == trace.trace_id
    assert evidence.source_call_id == completed.call_id
    assert evidence.source_trace_sequence == completed.sequence
    assert evidence.tool_name == "get_asset_context"
    assert evidence.client_operation == "get_asset"
    assert evidence.arguments == completed.arguments


def test_semantic_unavailable_remains_distinct_from_transport_failure() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(EvidenceStatus.UNAVAILABLE, data={})
    executor, _, ledger = executor_for(client)

    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    evidence = ledger.records[0]
    assert evidence.transport_ok is True
    assert evidence.status_code == 200
    assert evidence.evidence_status is EvidenceStatus.UNAVAILABLE


def test_transport_or_protocol_failure_stays_in_trace_but_not_ledger() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(
        None,
        transport_ok=False,
        error=ClientError(ClientErrorKind.CONNECTION, "conexão recusada"),
    )
    executor, trace, ledger = executor_for(client)

    result = executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    assert result.transport_ok is False
    assert ledger.records == ()
    snapshot = trace.events[1].result
    assert snapshot is not None
    assert snapshot.error is not None
    assert snapshot.error.kind is ClientErrorKind.CONNECTION


def test_action_is_traced_but_never_added_to_evidence_ledger() -> None:
    client = Mock(spec=TractianClient)
    client.reprocess_analysis.return_value = action_result()
    executor, trace, ledger = executor_for(client)

    executor.execute(
        tool_by_name("request_analysis_reprocessing"),
        {"analysis_id": "an_1", "justification": "Existem novas medições para reprocessamento."},
    )

    assert len(trace.events) == 2
    assert trace.events[1].operation_kind is OperationKind.ACTION
    assert ledger.records == ()


def test_invalid_input_is_audited_without_logging_forbidden_identity() -> None:
    client = Mock(spec=TractianClient)
    executor, trace, ledger = executor_for(client)

    with pytest.raises(ValidationError):
        executor.execute(
            tool_by_name("get_asset_context"),
            {"asset_id": "asset_1", "user_id": "attacker"},
        )

    assert [event.event_type for event in trace.events] == [
        TraceEventType.TOOL_STARTED,
        TraceEventType.TOOL_FAILED,
    ]
    assert trace.events[0].arguments == {"asset_id": "asset_1"}
    assert "attacker" not in json.dumps(trace.as_dicts())
    assert trace.events[1].failure is not None
    assert trace.events[1].failure.exception_type == "ValidationError"
    assert ledger.records == ()
    client.get_asset.assert_not_called()


def test_unexpected_tool_exception_is_recorded_and_reraised() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.side_effect = RuntimeError("falha controlada")
    executor, trace, ledger = executor_for(client)

    with pytest.raises(RuntimeError, match="falha controlada"):
        executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    assert trace.events[-1].event_type is TraceEventType.TOOL_FAILED
    assert trace.events[-1].failure is not None
    assert trace.events[-1].failure.exception_type == "RuntimeError"
    assert trace.events[-1].duration_ms == 125.0
    assert ledger.records == ()


def test_trace_and_ledger_snapshot_mutable_inputs_and_result_data() -> None:
    arguments = {"asset_id": "asset_1"}
    data = {"points": [{"id": "point_1"}]}
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(data=data)
    executor, trace, ledger = executor_for(client)

    executor.execute(tool_by_name("get_asset_context"), arguments)
    arguments["asset_id"] = "changed"
    data["points"][0]["id"] = "changed"

    assert trace.events[1].arguments == {"asset_id": "asset_1"}
    assert trace.events[1].result is not None
    assert trace.events[1].result.data == {"points": [{"id": "point_1"}]}
    assert ledger.records[0].data == {"points": [{"id": "point_1"}]}


def test_exported_nested_data_cannot_mutate_internal_audit_records() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(data={"points": [{"id": "point_1"}]})
    executor, trace, ledger = executor_for(client)
    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    exported_trace_data = trace.events[1].result.data
    exported_evidence_data = ledger.records[0].data
    assert isinstance(exported_trace_data, dict)
    assert isinstance(exported_evidence_data, dict)
    exported_trace_data["points"][0]["id"] = "changed"
    exported_evidence_data["points"][0]["id"] = "changed"

    assert trace.events[1].result.data == {"points": [{"id": "point_1"}]}
    assert ledger.records[0].data == {"points": [{"id": "point_1"}]}


def test_multiple_calls_have_global_chronological_sequences() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result()
    call_ids = iter(["call_1", "call_2"])
    evidence_ids = iter(["evidence_1", "evidence_2"])
    trace = ExecutionTrace("trace_multi")
    ledger = EvidenceLedger("trace_multi")
    executor = TrackedToolExecutor(
        client,
        trace,
        ledger,
        clock=iterator_factory(
            [
                BASE_TIME,
                BASE_TIME + timedelta(milliseconds=10),
                BASE_TIME + timedelta(milliseconds=20),
                BASE_TIME + timedelta(milliseconds=30),
            ]
        ),
        monotonic_clock=iterator_factory([1.0, 1.01, 2.0, 2.01]),
        call_id_factory=lambda: next(call_ids),
        evidence_id_factory=lambda: next(evidence_ids),
    )

    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})
    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_2"})

    assert [event.sequence for event in trace.events] == [1, 2, 3, 4]
    assert [event.call_id for event in trace.events] == ["call_1", "call_1", "call_2", "call_2"]
    assert [record.sequence for record in ledger.records] == [1, 2]
    assert [record.source_call_id for record in ledger.records] == ["call_1", "call_2"]


def test_default_correlation_ids_are_deterministic_within_trace() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result()
    trace = ExecutionTrace("trace_stable")
    ledger = EvidenceLedger("trace_stable")
    executor = TrackedToolExecutor(
        client,
        trace,
        ledger,
        clock=iterator_factory(
            [BASE_TIME, BASE_TIME, BASE_TIME + timedelta(seconds=1), BASE_TIME + timedelta(seconds=1)]
        ),
        monotonic_clock=iterator_factory([1.0, 1.0, 2.0, 2.0]),
    )

    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})
    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_2"})

    assert [trace.events[index].call_id for index in (0, 2)] == [
        "trace_stable:call:000001",
        "trace_stable:call:000002",
    ]
    assert [record.evidence_id for record in ledger.records] == [
        "trace_stable:evidence:000001",
        "trace_stable:evidence:000002",
    ]


def test_trace_and_ledger_are_json_serializable() -> None:
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = read_result(EvidenceStatus.PARTIAL)
    executor, trace, ledger = executor_for(client)
    executor.execute(tool_by_name("get_asset_context"), {"asset_id": "asset_1"})

    trace_payload = json.loads(json.dumps(trace.as_dicts(), ensure_ascii=False))
    ledger_payload = json.loads(json.dumps(ledger.as_dicts(), ensure_ascii=False))

    assert trace_payload[1]["result"]["evidence_status"] == "partial"
    assert ledger_payload[0]["source_call_id"] == "call_1"


def test_trace_and_ledger_must_share_the_same_execution_id() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        TrackedToolExecutor(
            Mock(spec=TractianClient),
            ExecutionTrace("trace_1"),
            EvidenceLedger("trace_2"),
        )


@pytest.mark.parametrize("container", [ExecutionTrace, EvidenceLedger])
def test_audit_containers_reject_blank_execution_id(container: type) -> None:
    with pytest.raises(ValueError, match="trace_id"):
        container("   ")
