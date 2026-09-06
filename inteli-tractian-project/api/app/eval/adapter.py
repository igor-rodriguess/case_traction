"""Converte uma run persistida em `EvaluationInput`.

O Eval consome artefato, não objeto vivo: qualquer run gravada em
`experiments/*/runs.jsonl` pode ser avaliada depois, sem reexecutar nada. Isso é
o que torna a avaliação repetível e o que garante que ela não altera a execução.

O payload bruto das evidências não atravessa: o Eval recebe os **nomes dos
campos** presentes, o suficiente para julgar materialização sem transportar
medição inteira.
"""

from __future__ import annotations

from typing import Any

from app.eval.contracts import (
    DecisionSnapshot,
    EvaluationInput,
    EvaluationReference,
    EvidenceSnapshot,
    TraceSnapshot,
)


def _decisions(run: dict[str, Any]) -> tuple[DecisionSnapshot, ...]:
    snapshots: list[DecisionSnapshot] = []
    for entry in run.get("components", {}).get("investigator", []) or []:
        output = entry.get("output") or {}
        request = output.get("tool_request") or {}
        policy = entry.get("completion_policy") or {}
        snapshots.append(
            DecisionSnapshot(
                decision_id=output.get("decision_id", "unknown"),
                type=output.get("type", "unknown"),
                reason_codes=tuple(output.get("reason_codes", ())),
                tool_name=request.get("tool_name"),
                arguments=request.get("arguments") or {},
                supporting_evidence_ids=tuple(output.get("supporting_evidence_ids", ())),
                first_pass_valid=entry.get("first_pass_valid"),
                policy_reason_code=policy.get("reason_code"),
            )
        )
    return tuple(snapshots)


def _evidence(run: dict[str, Any]) -> tuple[EvidenceSnapshot, ...]:
    records = []
    for item in run.get("evidence_ledger", []) or []:
        data = item.get("data")
        records.append(
            EvidenceSnapshot(
                evidence_id=item["evidence_id"],
                trace_id=item["trace_id"],
                source_call_id=item["source_call_id"],
                source_trace_sequence=item["source_trace_sequence"],
                tool_name=item["tool_name"],
                client_operation=item["client_operation"],
                method=item["method"],
                path=item["path"],
                evidence_status=item["evidence_status"],
                arguments=item.get("arguments") or {},
                data_fields=tuple(sorted(data)) if isinstance(data, dict) else (),
                notes=item.get("notes"),
            )
        )
    return tuple(records)


def _trace(run: dict[str, Any]) -> TraceSnapshot:
    events = run.get("trace", []) or []
    trace_id = events[0]["trace_id"] if events else run.get("state", {}).get("trace_id", "unknown")
    return TraceSnapshot(
        trace_id=trace_id,
        event_types=tuple(event["event_type"] for event in events),
        tool_completed_calls=tuple(
            (event["call_id"], event["sequence"]) for event in events if event["event_type"] == "tool_completed"
        ),
        action_events=sum(1 for event in events if event.get("operation_kind") == "ACTION"),
    )


def build_evaluation_input(
    run: dict[str, Any],
    *,
    evaluation_id: str,
    reference: EvaluationReference | None = None,
    context: dict[str, Any] | None = None,
) -> EvaluationInput:
    components = run.get("components", {})
    request = (run.get("state") or {}).get("request") or {}
    understanding = components.get("understanding") or {}
    planner = components.get("planner") or {}
    reporter = components.get("reporter") or {}

    return EvaluationInput(
        evaluation_id=evaluation_id,
        run_id=run.get("run_id", run.get("sample_id", "unknown")),
        case_id=run.get("sample_id", run.get("run_id", "unknown")),
        original_request=request.get("message", "(mensagem ausente no artefato)"),
        understanding_output=understanding.get("output"),
        planner_output=planner.get("output"),
        investigation_decisions=_decisions(run),
        trace=_trace(run),
        evidence_records=_evidence(run),
        investigation_conclusion=components.get("conclusion"),
        claim_lineage=tuple(components.get("claim_lineage") or ()),
        reporter_output=reporter.get("output"),
        terminal_state=run.get("terminal_status", "UNKNOWN"),
        human_handoff=(run.get("state") or {}).get("human_handoff"),
        reference=reference,
        evaluation_context={
            "experiment_version": run.get("experiment_version"),
            "routing_version": run.get("routing_version"),
            "coverage_alignment": (run.get("coverage") or {}).get("alignment"),
            "failure_category": run.get("failure_category"),
            **(context or {}),
        },
    )
