"""Showcase curado da Etapa 09.5 para revisão humana.

O `showcase.json` do experimento tem ~500 KB porque carrega o payload íntegro de
cada evidência e o snapshot bruto de cada tentativa. Este gerador preserva a
cadeia auditável — requisição, decisão, política, tool, Trace, evidência,
terminalidade — e descarta apenas o volume que não muda a leitura.

Os casos não são escolhidos aqui: vêm das categorias que o runner já selecionou,
incluindo as desfavoráveis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments" / "e2e-full-dev-v1"
OUTPUT = ROOT / "docs" / "architecture" / "examples" / "09-5-full-dev-showcase.json"

_MAX_TEXT = 180
_MAX_ITEMS = 3
_MAX_DEPTH = 3


def _clip(value: Any, *, depth: int = 0) -> Any:
    """Mantém forma e tipo; encurta texto, listas e aninhamento profundo.

    O objetivo do exemplo é deixar a cadeia auditável legível, não replicar o
    payload — este já está íntegro em `experiments/e2e-full-dev-v1/`.
    """

    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…[truncado]"
    if isinstance(value, list):
        if depth >= _MAX_DEPTH:
            return f"…[{len(value)} itens omitidos]"
        clipped = [_clip(item, depth=depth + 1) for item in value[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            clipped.append(f"…[+{len(value) - _MAX_ITEMS} itens]")
        return clipped
    if isinstance(value, dict):
        if depth >= _MAX_DEPTH:
            return f"…[{len(value)} campos omitidos: {', '.join(sorted(value)[:4])}]"
        return {key: _clip(item, depth=depth + 1) for key, item in value.items()}
    return value


def _decision(entry: dict[str, Any]) -> dict[str, Any]:
    """Decisão sem o envelope bruto do provider, que não muda a auditoria."""

    attempts = entry.get("attempts") or []
    return _compact(
        {
            "output": _compact(entry.get("output") or {}),
            "first_pass_valid": entry.get("first_pass_valid"),
            "repair_attempted": entry.get("repair_attempted"),
            "final_decision_source": entry.get("final_decision_source"),
            "completion_policy": _compact(entry.get("completion_policy") or {}),
            "attempt_validations": [
                _compact(
                    {
                        "attempt_number": attempt.get("attempt_number"),
                        "valid": attempt["validation"].get("valid"),
                        "category": attempt["validation"].get("category"),
                        "field": attempt["validation"].get("field"),
                        "latency_ms": attempt.get("latency_ms"),
                        "usage": attempt.get("usage"),
                    }
                )
                for attempt in attempts
                if "validation" in attempt
            ],
        }
    )


def _llm(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    return _compact({
        "provider": entry.get("provider"),
        "model": entry.get("model"),
        "prompt_version": entry.get("prompt_version"),
        "schema_valid": entry.get("schema_valid"),
        "finish_reason": entry.get("finish_reason"),
        "latency_ms": entry.get("latency_ms"),
        "usage": entry.get("usage"),
        "error": entry.get("error"),
        "output": _clip(entry.get("output")),
    })


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove chaves nulas ou vazias; num evento operacional a maioria é nula."""

    return {key: value for key, value in payload.items() if value not in (None, {}, [], "")}


def _trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _compact(
            {
                "sequence": event["sequence"],
                "event_type": event["event_type"],
                "tool_name": event.get("tool_name"),
                "operation_kind": event.get("operation_kind"),
                "duration_ms": event.get("duration_ms"),
                "details": _clip(event.get("details") or {}),
                "evidence_status": (event.get("result") or {}).get("evidence_status"),
            }
        )
        for event in events
    ]


def _evidence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": record["evidence_id"],
            "source_call_id": record["source_call_id"],
            "source_trace_sequence": record["source_trace_sequence"],
            "tool_name": record["tool_name"],
            "client_operation": record["client_operation"],
            "arguments": record["arguments"],
            "evidence_status": record["evidence_status"],
            "method": record["method"],
            "path": record["path"],
            "notes": _clip(record.get("notes")),
            "data": _clip(record.get("data")),
        }
        for record in records
    ]


def build(showcase: dict[str, Any], gates: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    # Um mesmo caso costuma ilustrar várias categorias (escalada segura, gap de
    # cobertura e evidência inconclusiva podem ser o mesmo run). Guardar o caso
    # uma vez, com a lista de categorias, evita repetir o payload inteiro.
    labels_by_sample: dict[str, list[str]] = {}
    for label, case in showcase["cases"].items():
        labels_by_sample.setdefault(case["sample_id"], []).append(label)
    unique = {case["sample_id"]: case for case in showcase["cases"].values()}

    cases = {
        sample_id: {
            "illustrates": labels_by_sample[sample_id],
            "sample_id": case["sample_id"],
            "training_tags": case["training_tags"],
            "request": case["request"],
            "understanding": _llm(case.get("understanding")),
            "planner": _llm(case.get("planner")),
            "investigator_decisions": [_decision(item) for item in case.get("investigator_decisions") or []],
            "conclusion": case.get("conclusion"),
            "claim_lineage": case.get("claim_lineage"),
            "reporter": _llm(case.get("reporter")),
            "trace": _trace(case["trace"]),
            "evidence_ledger": _evidence(case["evidence_ledger"]),
            "terminal_status": case["terminal_status"],
            "failure_category": case["failure_category"],
            "coverage": case["coverage"],
            "errors": case["errors"],
            "duration_ms": case["duration_ms"],
        }
        for sample_id, case in unique.items()
    }
    return {
        "experiment_version": showcase["experiment_version"],
        "routing_version": showcase["routing_version"],
        "selection_policy": showcase["selection_policy"],
        "categories_absent": showcase["categories_absent"],
        "final_status": gates["final_status"],
        "quality_gates": {item["dimension"]: item["verdict"] for item in gates["gates"]},
        "training_assessment": {item["component"]: item["assessment"] for item in gates["training_assessment"]},
        "data_coverage_summary": {
            key: coverage[key]
            for key in (
                "cases_fully_aligned",
                "cases_partially_aligned",
                "cases_misaligned",
                "cases_impossible_from_api",
                "cases_grounded_answer_reachable",
                "cases_requesting_unavailable_temporal_context",
                "temporal_filtering_supported_by_tools",
            )
        },
        "cases": cases,
    }


def main() -> int:
    payload = build(
        json.loads((EXPERIMENT / "showcase.json").read_text(encoding="utf-8")),
        json.loads((EXPERIMENT / "quality-gates.json").read_text(encoding="utf-8")),
        json.loads((EXPERIMENT / "data-coverage.json").read_text(encoding="utf-8")),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{OUTPUT} categorias={len(payload['cases'])} kb={OUTPUT.stat().st_size / 1024:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
