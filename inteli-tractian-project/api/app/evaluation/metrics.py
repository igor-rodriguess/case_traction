"""Agregação determinística das métricas da avaliação DEV completa.

Opera sobre os registros já persistidos em `runs.jsonl`, e não sobre objetos
vivos: retomar uma rodada interrompida e reagregar precisa dar o mesmo número.

Onde não existe alvo determinístico, a métrica é `NEEDS_HUMAN_REVIEW` em vez de
um valor inventado.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from math import ceil
from statistics import median
from typing import Any

from app.evaluation.taxonomy import TerminalStatus, VALID_TERMINAL_STATUSES
from app.tools import get_investigator_tools


NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"

_IDENTIFIER_TO_BUCKET: dict[str, str] = {
    "asset_id": "assets",
    "analysis_id": "analyses",
    "model_id": "models",
    "doc_id": "documents",
}


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Percentil por nearest-rank: ``ceil(p * N)``.

    O arredondamento de `round` é bancário e tornaria o índice sensível a
    paridade; `ceil` mantém a definição clássica e monotônica.
    """

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 3)


def required_identifiers() -> dict[str, tuple[str, ...]]:
    """Identificadores obrigatórios de cada READ tool, lidos do próprio schema."""

    result: dict[str, tuple[str, ...]] = {}
    for tool in get_investigator_tools():
        required = tuple(
            name for name, field in tool.input_schema.model_fields.items() if field.is_required()
        )
        result[tool.name] = required
    return result


def capability_applicable(capability: str, available_buckets: set[str]) -> bool | None:
    """Aplicabilidade estrutural; `None` quando a tool não é reconhecida."""

    requirements = required_identifiers().get(capability)
    if requirements is None:
        return None
    buckets = {_IDENTIFIER_TO_BUCKET[name] for name in requirements if name in _IDENTIFIER_TO_BUCKET}
    return buckets <= available_buckets


def _llm_entries(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Chamadas de provider do caso, preferindo o ledger explícito.

    A partir da Etapa 09.6 o runner grava `llm_calls` no momento da chamada, de
    modo que uma falha antes de `components[...]` ser preenchido não some da
    contabilidade. A reconstrução por componentes permanece para ler artefatos
    da V1, que não possuem o ledger.
    """

    ledger = run.get("llm_calls")
    if isinstance(ledger, list) and ledger:
        return [entry for entry in ledger if isinstance(entry, dict)]

    components = run.get("components", {})
    entries = [components.get(name) for name in ("understanding", "planner", "reporter")]
    entries += [
        attempt
        for decision in components.get("investigator", [])
        for attempt in decision.get("attempts", [])
    ]
    return [entry for entry in entries if isinstance(entry, dict)]


def _decisions(runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [decision for run in runs for decision in run.get("components", {}).get("investigator", [])]


# --------------------------------------------------------------------------- #
# Componentes
# --------------------------------------------------------------------------- #


def planner_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    reached = [run for run in runs if isinstance(run.get("components", {}).get("planner"), dict)]
    schema_valid = sum(bool(run["components"]["planner"].get("schema_valid")) for run in reached)
    applicable = unnecessary = executed = suggested = 0
    unrecognized = 0
    for run in reached:
        planner = run["components"]["planner"]
        plan = planner.get("output") or {}
        buckets = set(planner.get("available_entity_buckets") or ())
        used = {
            event.get("tool_name")
            for event in run.get("trace", [])
            if event.get("event_type") == "tool_completed"
        }
        for capability in [item.get("name") for item in plan.get("suggested_capabilities", [])]:
            suggested += 1
            verdict = capability_applicable(str(capability), buckets)
            if verdict is None:
                unrecognized += 1
            elif verdict:
                applicable += 1
            else:
                unnecessary += 1
            executed += int(capability in used)
    return {
        "cases_reached": len(reached),
        "llm_calls": len(reached),
        "schema_valid_rate": _rate(schema_valid, len(reached)),
        "suggested_capabilities_total": suggested,
        "relevant_capability_rate": _rate(applicable, suggested),
        "unnecessary_capability_rate": _rate(unnecessary, suggested),
        "unrecognized_capability_count": unrecognized,
        "plan_completion_rate": _rate(executed, suggested),
        "objective_coverage": NEEDS_HUMAN_REVIEW,
        "missing_capability_rate": NEEDS_HUMAN_REVIEW,
        "note": (
            "Aplicabilidade é estrutural: uma capability exige identificadores que o "
            "Understanding precisa ter extraído. Adequação semântica do objetivo não "
            "possui alvo determinístico neste split."
        ),
    }


def investigator_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    decisions = _decisions(runs)
    total = len(decisions)
    attempts = [attempt for decision in decisions for attempt in decision.get("attempts", [])]
    invalid = [attempt["validation"] for attempt in attempts if not attempt["validation"].get("valid")]
    types = Counter(decision.get("output", {}).get("type") for decision in decisions)
    tool_calls = [
        decision for decision in decisions if decision.get("output", {}).get("type") == "tool_call"
    ]
    rejected = [
        decision
        for decision in decisions
        if not decision.get("completion_policy", {}).get("accepted", True)
    ]
    repeated = sum(
        decision.get("completion_policy", {}).get("reason_code")
        == "REPEATED_TOOL_CALL_WITHOUT_NEW_EVIDENCE"
        for decision in decisions
    )
    steps = [len(run.get("components", {}).get("investigator", [])) for run in runs]
    step_limits = [int(run.get("state", {}).get("max_investigation_steps") or 0) for run in runs]
    tools_per_case = [
        sum(1 for event in run.get("trace", []) if event.get("event_type") == "tool_completed")
        for run in runs
    ]
    grounded = sum(run.get("terminal_status") == TerminalStatus.GROUNDED_COMPLETION.value for run in runs)
    answers = types.get("answer", 0)
    return {
        "decisions_total": total,
        "first_pass_valid_rate": _rate(sum(bool(item.get("first_pass_valid")) for item in decisions), total),
        "repair_rate": _rate(sum(bool(item.get("repair_attempted")) for item in decisions), total),
        "failed_after_repair_rate": _rate(
            sum(item.get("final_decision_source") == "deterministic_fail_safe" for item in decisions), total
        ),
        "tool_selection_validity": _rate(
            sum(
                1
                for decision in tool_calls
                if decision.get("attempts") and decision["attempts"][-1]["validation"].get("valid")
            ),
            len(tool_calls),
        ),
        "invalid_tool_rate": _rate(
            sum(item.get("category") == "INVALID_TOOL_NAME" for item in invalid), total
        ),
        "invalid_argument_rate": _rate(
            sum(item.get("category") == "INVALID_TOOL_ARGUMENTS" for item in invalid), total
        ),
        "forbidden_action_count": sum(item.get("category") == "FORBIDDEN_ACTION" for item in invalid),
        "average_steps": round(sum(steps) / len(steps), 3) if steps else None,
        "average_tools": round(sum(tools_per_case) / len(tools_per_case), 3) if tools_per_case else None,
        "repeated_tool_rate": _rate(repeated, total),
        "loop_rate": _rate(
            sum(step >= limit for step, limit in zip(steps, step_limits) if limit), len(steps)
        ),
        "answer_rate": _rate(answers, total),
        "ask_user_rate": _rate(types.get("ask_user", 0), total),
        "escalate_rate": _rate(types.get("escalate", 0), total),
        "continue_rate": _rate(types.get("continue", 0), total),
        "tool_call_rate": _rate(types.get("tool_call", 0), total),
        "grounded_answer_rate": _rate(grounded, len(runs)),
        "invalid_answer_rate": _rate(
            sum(
                decision.get("completion_policy", {}).get("rejected_decision_type") == "answer"
                for decision in decisions
            ),
            total,
        ),
        "policy_rejected_decisions": len(rejected),
        "policy_reason_codes": dict(
            Counter(
                decision.get("completion_policy", {}).get("reason_code")
                for decision in decisions
                if decision.get("completion_policy")
            )
        ),
        "validation_error_by_category": dict(Counter(item.get("category") for item in invalid)),
        "validation_error_by_field": dict(Counter(item.get("field") or "<root>" for item in invalid)),
    }


def lineage_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    lineages = [item for run in runs for item in run.get("components", {}).get("claim_lineage", [])]
    claims = [
        claim
        for run in runs
        for claim in (run.get("components", {}).get("conclusion") or {}).get("claims", [])
    ]
    statuses = Counter(claim.get("status") for claim in claims)
    known_evidence = {
        record.get("evidence_id")
        for run in runs
        for record in run.get("evidence_ledger", [])
    }
    invalid_reference = sum(item.get("evidence_id") not in known_evidence for item in lineages)
    return {
        "claims_total": len(claims),
        "lineage_links_total": len(lineages),
        "lineage_valid_rate": _rate(sum(bool(item.get("valid")) for item in lineages), len(lineages)),
        "grounded_claim_rate": _rate(statuses.get("supported", 0), len(claims)),
        "partially_grounded_claim_rate": _rate(statuses.get("qualified", 0), len(claims)),
        "unsupported_claim_rate": _rate(statuses.get("unresolved", 0), len(claims)),
        "contradicted_claim_rate": _rate(statuses.get("contradicted", 0), len(claims)),
        "invalid_reference_rate": _rate(invalid_reference, len(lineages)),
    }


def reporter_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = [run for run in runs if run.get("components", {}).get("conclusion")]
    reached = [run for run in runs if isinstance(run.get("components", {}).get("reporter"), dict)]
    validations = [run["components"]["reporter"].get("validation") or {} for run in reached]
    valid = [item for item in validations if item.get("valid")]

    def mean(key: str) -> float | None:
        values = [item[key] for item in validations if isinstance(item.get(key), (int, float))]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "cases_eligible": len(eligible),
        "cases_reached": len(reached),
        "reach_rate": _rate(len(reached), len(runs)),
        "reach_rate_among_eligible": _rate(len(reached), len(eligible)),
        "completion_rate": _rate(len(valid), len(runs)),
        "completion_rate_among_reached": _rate(len(valid), len(reached)),
        "schema_valid_rate": _rate(sum(bool(item.get("schema_valid")) for item in validations), len(validations)),
        "claim_preservation_rate": mean("claim_preservation_rate"),
        "evidence_reference_preservation_rate": mean("evidence_reference_preservation_rate"),
        "unsupported_claim_rate": mean("unsupported_claim_rate"),
        "limitation_preservation_rate": _rate(
            sum(bool(item.get("limitations_preserved")) for item in validations), len(validations)
        ),
        "unresolved_point_preservation_rate": _rate(
            sum(bool(item.get("unresolved_points_preserved")) for item in validations), len(validations)
        ),
        "audience_correct_rate": _rate(
            sum(bool(item.get("target_valid")) for item in validations), len(validations)
        ),
        "violations": dict(
            Counter(violation for item in validations for violation in item.get("violations", []))
        ),
    }


def provider_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_provider: dict[str, dict[str, Any]] = {}
    for run in runs:
        for entry in _llm_entries(run):
            provider = str(entry.get("provider", "unknown"))
            bucket = by_provider.setdefault(
                provider,
                {
                    "calls": 0,
                    "models": set(),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": 0.0,
                    "errors": 0,
                    "rate_limit_429": 0,
                    "timeouts": 0,
                    "server_errors_5xx": 0,
                    "retry_attempts": 0,
                    "error_codes": Counter(),
                },
            )
            bucket["calls"] += 1
            bucket["models"].add(str(entry.get("model")))
            usage = entry.get("usage") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                bucket[key] += int(usage.get(key) or 0)
            bucket["latency_ms"] += float(entry.get("latency_ms") or 0)
            canonical = entry.get("canonical_llm_response") or {}
            metadata = canonical.get("metadata") or {}
            bucket["retry_attempts"] += max(0, int(metadata.get("attempt_count") or 1) - 1)
            error = entry.get("error")
            if error:
                bucket["errors"] += 1
                code = str(error.get("code"))
                bucket["error_codes"][code] += 1
                status = error.get("http_status")
                bucket["rate_limit_429"] += int(code == "rate_limit" or status == 429)
                bucket["timeouts"] += int(code == "timeout")
                bucket["server_errors_5xx"] += int(isinstance(status, int) and 500 <= status < 600)
    for bucket in by_provider.values():
        bucket["models"] = sorted(bucket["models"])
        bucket["latency_ms"] = round(bucket["latency_ms"], 3)
        bucket["error_codes"] = dict(bucket["error_codes"])
        bucket["error_rate"] = _rate(bucket["errors"], bucket["calls"])
    return by_provider


def provider_caused(run: dict[str, Any]) -> bool:
    """A falha do caso veio da infraestrutura, não de uma decisão do agente.

    Um 5xx do provider derruba o caso sem que o agente tenha escolhido nada.
    Contá-lo como falha comportamental atribuiria ao modelo um problema que não
    é dele — a mesma distinção já aplicada à quota, agora estendida.
    """

    errors = run.get("errors") or []
    return bool(errors) and all(error.get("primary_layer") == "PROVIDER" for error in errors)


def e2e_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(runs)
    terminal = Counter(run.get("terminal_status") for run in runs)
    failed = [run for run in runs if run.get("terminal_status") == TerminalStatus.FAILED.value]
    provider_failures = [run for run in failed if provider_caused(run)]
    behavioural_failures = [run for run in failed if not provider_caused(run)]
    behavioural_population = total - len(provider_failures)
    durations = [float(run.get("duration_ms") or 0) for run in runs]
    llm_calls = sum(len(_llm_entries(run)) for run in runs)
    tool_calls = sum(
        1 for run in runs for event in run.get("trace", []) if event.get("event_type") == "tool_completed"
    )
    tokens = sum(
        int((entry.get("usage") or {}).get("total_tokens") or 0)
        for run in runs
        for entry in _llm_entries(run)
    )
    providers = provider_metrics(runs)
    provider_calls = sum(bucket["calls"] for bucket in providers.values()) or 1
    return {
        "total_cases": total,
        "terminal_state_counts": {str(key): value for key, value in terminal.items()},
        "terminal_state_rate": {str(key): _rate(value, total) for key, value in terminal.items()},
        "valid_terminal_state_rate": _rate(
            sum(run.get("terminal_status") in {item.value for item in VALID_TERMINAL_STATUSES} for run in runs),
            total,
        ),
        "grounded_completion_rate": _rate(terminal.get(TerminalStatus.GROUNDED_COMPLETION.value, 0), total),
        "safe_escalation_rate": _rate(terminal.get(TerminalStatus.SAFE_ESCALATION.value, 0), total),
        "awaiting_information_rate": _rate(
            terminal.get(TerminalStatus.AWAITING_REQUIRED_INFORMATION.value, 0), total
        ),
        "failure_rate": _rate(terminal.get(TerminalStatus.FAILED.value, 0), total),
        "behavioral_failure_rate": _rate(len(behavioural_failures), behavioural_population),
        "behavioral_failure_count": len(behavioural_failures),
        "provider_failure_count": len(provider_failures),
        "provider_failure_sample_ids": [run["sample_id"] for run in provider_failures],
        "behavioral_population": behavioural_population,
        "valid_terminal_state_rate_excluding_provider": _rate(
            sum(
                run.get("terminal_status") in {item.value for item in VALID_TERMINAL_STATUSES}
                for run in runs
                if not provider_caused(run)
            ),
            behavioural_population,
        ),
        "dead_end_rate": _rate(
            sum(run.get("failure_category") == "DEAD_END" for run in runs), total
        ),
        "failure_categories": dict(
            Counter(run.get("failure_category") for run in runs if run.get("failure_category"))
        ),
        "average_e2e_latency_ms": round(sum(durations) / total, 3) if total else None,
        "median_e2e_latency_ms": round(median(durations), 3) if durations else None,
        "p50_e2e_latency_ms": _percentile(durations, 0.50),
        "p95_e2e_latency_ms": _percentile(durations, 0.95),
        "total_llm_calls": llm_calls,
        "average_llm_calls_per_case": round(llm_calls / total, 3) if total else None,
        "total_tool_calls": tool_calls,
        "average_tool_calls_per_case": round(tool_calls / total, 3) if total else None,
        "total_tokens": tokens,
        "average_tokens_per_case": round(tokens / total, 3) if total else None,
        "provider_error_rate": _rate(sum(bucket["errors"] for bucket in providers.values()), provider_calls),
        "rate_limit_rate": _rate(
            sum(bucket["rate_limit_429"] for bucket in providers.values()), provider_calls
        ),
    }


def error_metrics(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    errors = [error for run in runs for error in run.get("errors", [])]
    return {
        "errors_total": len(errors),
        "cases_with_errors": sum(bool(run.get("errors")) for run in runs),
        "by_code": dict(Counter(error.get("code") for error in errors)),
        "by_primary_layer": dict(Counter(error.get("primary_layer") for error in errors)),
        "by_subcategory": dict(
            Counter(error.get("subcategory") for error in errors if error.get("subcategory"))
        ),
    }


def coverage_correlation(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Cruza terminalidade com alinhamento de dados, sem atribuir culpa ao agente."""

    pairs = Counter(
        (str((run.get("coverage") or {}).get("alignment")), str(run.get("terminal_status")))
        for run in runs
    )
    reachable = [run for run in runs if (run.get("coverage") or {}).get("grounded_answer_reachable")]
    unreachable = [run for run in runs if not (run.get("coverage") or {}).get("grounded_answer_reachable")]
    return {
        "terminal_by_alignment": {f"{key[0]}|{key[1]}": value for key, value in sorted(pairs.items())},
        "grounded_completion_rate_when_reachable": _rate(
            sum(run.get("terminal_status") == TerminalStatus.GROUNDED_COMPLETION.value for run in reachable),
            len(reachable),
        ),
        "grounded_completion_rate_when_unreachable": _rate(
            sum(run.get("terminal_status") == TerminalStatus.GROUNDED_COMPLETION.value for run in unreachable),
            len(unreachable),
        ),
        "cases_grounded_answer_reachable": len(reachable),
        "cases_grounded_answer_unreachable": len(unreachable),
    }
