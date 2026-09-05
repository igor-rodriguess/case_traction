"""Quality gates da Etapa 09.5 e decisão de treinamento por componente.

Os limiares são declarados aqui, e não escritos à mão no relatório, para que o
veredicto seja reproduzível a partir de `aggregate-metrics.json`. "O código
rodou" não é critério: cada dimensão exige uma métrica observada.

Métrica ausente nunca vira PASS. Quando o componente não foi exercitado o
suficiente, o resultado é `INSUFFICIENT_EVIDENCE_TO_DECIDE`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.taxonomy import QualityVerdict, TrainingAssessment


class GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateResult(GateModel):
    dimension: str
    verdict: QualityVerdict
    rationale: str = Field(max_length=400)
    observed: dict[str, Any] = Field(default_factory=dict)


class ComponentDecision(GateModel):
    component: str
    assessment: TrainingAssessment
    rationale: str = Field(max_length=400)
    observed: dict[str, Any] = Field(default_factory=dict)


def _verdict(*, ok: bool, warn: bool) -> QualityVerdict:
    if ok:
        return QualityVerdict.PASS
    return QualityVerdict.PASS_WITH_WARNINGS if warn else QualityVerdict.FAIL


MINIMUM_SPLIT_COVERAGE = 0.80
"""Fração do split que precisa ter sido medida para um veredicto ser interpretável.

Uma rodada interrompida produz números altos sobre poucos casos fáceis. Sem este
piso, três casos `contextualize` corretos bastariam para declarar um componente
`NO_TRAINING_NEEDED` — exatamente o tipo de conclusão que a avaliação existe para
impedir.
"""


def split_coverage(aggregate: dict[str, Any]) -> float:
    dataset = aggregate.get("dataset", {})
    measured = dataset.get("measured_cases", dataset.get("executed_cases", 0))
    total = dataset.get("sample_count") or 0
    return measured / total if total else 0.0


def _num(value: Any, default: float) -> float:
    """`None` significa 'não observado' e nunca deve ser lido como zero favorável."""

    return float(value) if isinstance(value, (int, float)) else default


def evaluate_gates(aggregate: dict[str, Any], coverage: dict[str, Any]) -> list[GateResult]:
    e2e = aggregate["e2e"]
    investigator = aggregate["investigator"]
    lineage = aggregate["evidence_and_lineage"]
    reporter = aggregate["reporter"]
    errors = aggregate["errors"]
    correlation = aggregate["data_coverage_correlation"]
    providers = aggregate["providers"]
    total = e2e["total_cases"] or 1

    results: list[GateResult] = []

    # 1. Arquitetura: o grafo termina sempre num estado declarado e íntegro.
    valid_rate = _num(e2e["valid_terminal_state_rate"], 0.0)
    dead_end = _num(e2e["dead_end_rate"], 1.0)
    structural = errors["by_code"].get("STATE_TRANSITION_ERROR", 0) + errors["by_code"].get("SYSTEM_ERROR", 0)
    results.append(
        GateResult(
            dimension="ARCHITECTURE_STABILITY",
            verdict=_verdict(
                ok=valid_rate == 1.0 and dead_end == 0.0 and structural == 0,
                warn=valid_rate >= 0.95 and dead_end <= 0.05 and structural == 0,
            ),
            rationale="Terminalidade declarada em todos os casos, sem dead end nem quebra de transição de estado.",
            observed={
                "valid_terminal_state_rate": valid_rate,
                "dead_end_rate": dead_end,
                "structural_errors": structural,
            },
        )
    )

    # 2. Contratos: a fronteira LLM→decisão aguenta o split inteiro.
    first_pass = _num(investigator["first_pass_valid_rate"], 0.0)
    failed_after_repair = _num(investigator["failed_after_repair_rate"], 1.0)
    invalid_tool = _num(investigator["invalid_tool_rate"], 1.0)
    invalid_argument = _num(investigator["invalid_argument_rate"], 1.0)
    forbidden = investigator["forbidden_action_count"]
    results.append(
        GateResult(
            dimension="CONTRACT_RELIABILITY",
            verdict=_verdict(
                ok=first_pass >= 0.98 and failed_after_repair == 0.0 and invalid_tool == 0.0 and invalid_argument == 0.0 and forbidden == 0,
                warn=first_pass >= 0.90 and failed_after_repair <= 0.02 and forbidden == 0,
            ),
            rationale="Decisões válidas na primeira passagem, sem falha após repair, tool inválida ou ACTION.",
            observed={
                "first_pass_valid_rate": first_pass,
                "failed_after_repair_rate": failed_after_repair,
                "invalid_tool_rate": invalid_tool,
                "invalid_argument_rate": invalid_argument,
                "forbidden_action_count": forbidden,
            },
        )
    )

    # 3. Investigação: concluir quando havia como concluir, sem loop nem repetição.
    reachable = correlation["cases_grounded_answer_reachable"]
    grounded_when_reachable = _num(correlation["grounded_completion_rate_when_reachable"], 0.0)
    loop_rate = _num(investigator["loop_rate"], 1.0)
    repeated = _num(investigator["repeated_tool_rate"], 1.0)
    if reachable == 0:
        investigation = QualityVerdict.PASS_WITH_WARNINGS
        investigation_reason = "Nenhum caso tinha conclusão factual alcançável; a taxa não é interpretável."
    else:
        investigation = _verdict(
            ok=grounded_when_reachable >= 0.60 and loop_rate == 0.0,
            warn=grounded_when_reachable >= 0.20 and loop_rate == 0.0,
        )
        investigation_reason = (
            "Conclusão grounded nos casos em que o cadastro permitia concluir, sem loop nem repetição de tool."
        )
    results.append(
        GateResult(
            dimension="INVESTIGATION_QUALITY",
            verdict=investigation,
            rationale=investigation_reason,
            observed={
                "cases_grounded_answer_reachable": reachable,
                "grounded_completion_rate_when_reachable": grounded_when_reachable,
                "loop_rate": loop_rate,
                "repeated_tool_rate": repeated,
                "safe_escalation_rate": e2e["safe_escalation_rate"],
                "awaiting_information_rate": e2e["awaiting_information_rate"],
            },
        )
    )

    # 4. Grounding: nenhuma claim sem cadeia até um READ observado.
    claims = lineage["claims_total"]
    if claims == 0:
        grounding = QualityVerdict.PASS_WITH_WARNINGS
        grounding_reason = "Nenhuma conclusão factual foi produzida; a integridade do grounding não foi exercitada."
    else:
        grounding = _verdict(
            ok=_num(lineage["lineage_valid_rate"], 0.0) == 1.0
            and _num(lineage["unsupported_claim_rate"], 1.0) == 0.0
            and _num(lineage["invalid_reference_rate"], 1.0) == 0.0,
            warn=_num(lineage["lineage_valid_rate"], 0.0) >= 0.95,
        )
        grounding_reason = "Toda claim rastreia até EvidenceRecord, call_id, tool_completed e READ."
    results.append(
        GateResult(
            dimension="GROUNDING_QUALITY",
            verdict=grounding,
            rationale=grounding_reason,
            observed={
                "claims_total": claims,
                "lineage_valid_rate": lineage["lineage_valid_rate"],
                "unsupported_claim_rate": lineage["unsupported_claim_rate"],
                "invalid_reference_rate": lineage["invalid_reference_rate"],
            },
        )
    )

    # 5. Reporter: alcançado por regra, e fiel quando alcançado.
    reached = reporter["cases_reached"]
    if reached == 0:
        reporter_verdict = QualityVerdict.PASS_WITH_WARNINGS
        reporter_reason = "Reporter não foi alcançado: por regra exige conclusão válida, que não ocorreu."
    else:
        reporter_verdict = _verdict(
            ok=_num(reporter["completion_rate_among_reached"], 0.0) == 1.0
            and _num(reporter["claim_preservation_rate"], 0.0) == 1.0
            and _num(reporter["unsupported_claim_rate"], 1.0) == 0.0,
            warn=_num(reporter["completion_rate_among_reached"], 0.0) >= 0.90,
        )
        reporter_reason = "Relatórios preservam claims, evidence refs e limitações sem inventar fato."
    results.append(
        GateResult(
            dimension="REPORTER_QUALITY",
            verdict=reporter_verdict,
            rationale=reporter_reason,
            observed={
                "cases_eligible": reporter["cases_eligible"],
                "cases_reached": reached,
                "completion_rate_among_reached": reporter["completion_rate_among_reached"],
                "claim_preservation_rate": reporter["claim_preservation_rate"],
                "unsupported_claim_rate": reporter["unsupported_claim_rate"],
            },
        )
    )

    # 6. Dados: o split descreve o que a API realmente contém?
    aligned_rate = coverage["cases_fully_aligned"] / total
    misaligned_rate = coverage["cases_misaligned"] / total
    impossible_rate = coverage["cases_impossible_from_api"] / total
    results.append(
        GateResult(
            dimension="DATA_COVERAGE",
            verdict=_verdict(
                ok=aligned_rate >= 0.80 and misaligned_rate == 0.0,
                warn=misaligned_rate <= 0.10 and impossible_rate <= 0.20,
            ),
            rationale="O texto do split precisa descrever os ativos que a API de fato serve.",
            observed={
                "cases_fully_aligned": coverage["cases_fully_aligned"],
                "cases_partially_aligned": coverage["cases_partially_aligned"],
                "cases_misaligned": coverage["cases_misaligned"],
                "cases_impossible_from_api": coverage["cases_impossible_from_api"],
                "cases_requesting_unavailable_temporal_context": coverage[
                    "cases_requesting_unavailable_temporal_context"
                ],
            },
        )
    )

    # 7. Providers: a rodada inteira sem erro de infraestrutura.
    provider_errors = sum(bucket["errors"] for bucket in providers.values())
    rate_limits = sum(bucket["rate_limit_429"] for bucket in providers.values())
    timeouts = sum(bucket["timeouts"] for bucket in providers.values())
    results.append(
        GateResult(
            dimension="PROVIDER_STABILITY",
            verdict=_verdict(
                ok=provider_errors == 0,
                warn=_num(e2e["provider_error_rate"], 1.0) <= 0.02,
            ),
            rationale="Rodada longa sem erro, rate limit ou timeout de provider.",
            observed={
                "provider_errors": provider_errors,
                "rate_limit_429": rate_limits,
                "timeouts": timeouts,
                "provider_error_rate": e2e["provider_error_rate"],
                "calls": {name: bucket["calls"] for name, bucket in providers.items()},
            },
        )
    )
    return results


def overall_status(gates: list[GateResult], aggregate: dict[str, Any]) -> str:
    """Critério de aprovação da Etapa 09.5 (§32), decidido por regra."""

    by_name = {gate.dimension: gate.verdict for gate in gates}
    structural = {"ARCHITECTURE_STABILITY", "CONTRACT_RELIABILITY", "GROUNDING_QUALITY"}
    if aggregate["run_status"] != "COMPLETED":
        return "RUN_PAUSED_PROVIDER_QUOTA"
    if split_coverage(aggregate) < MINIMUM_SPLIT_COVERAGE:
        return "INSUFFICIENT_SPLIT_COVERAGE"
    if any(by_name.get(name) is QualityVerdict.FAIL for name in structural):
        return "FIX_ARCHITECTURE_BEFORE_TRAINING"
    if aggregate["security"]["action_decisions"] or aggregate["security"]["action_tools_executed"]:
        return "FIX_ARCHITECTURE_BEFORE_TRAINING"
    behavioural_clean = (
        by_name.get("INVESTIGATION_QUALITY") is QualityVerdict.PASS
        and by_name.get("REPORTER_QUALITY") is QualityVerdict.PASS
        and by_name.get("DATA_COVERAGE") is QualityVerdict.PASS
    )
    return "READY_FOR_HOLDOUT" if behavioural_clean else "READY_FOR_CALIBRATION_OR_TRAINING"


def training_decisions(aggregate: dict[str, Any], coverage: dict[str, Any]) -> list[ComponentDecision]:
    """Classifica cada componente sem executar treinamento (§29)."""

    understanding = aggregate["understanding"]
    planner = aggregate["planner"]
    investigator = aggregate["investigator"]
    reporter = aggregate["reporter"]
    correlation = aggregate["data_coverage_correlation"]
    decisions: list[ComponentDecision] = []

    coverage_of_split = split_coverage(aggregate)
    if coverage_of_split < MINIMUM_SPLIT_COVERAGE:
        # Amostra insuficiente: nenhum componente pode ser absolvido nem condenado.
        return [
            ComponentDecision(
                component=name,
                assessment=TrainingAssessment.INSUFFICIENT_EVIDENCE_TO_DECIDE,
                rationale=(
                    f"Apenas {coverage_of_split:.0%} do split foi medido; o mínimo interpretável "
                    f"é {MINIMUM_SPLIT_COVERAGE:.0%}."
                ),
                observed={"split_coverage": round(coverage_of_split, 4), "minimum": MINIMUM_SPLIT_COVERAGE},
            )
            for name in ("understanding", "planner", "investigator", "reporter")
        ]

    # Understanding — comparado ao target determinístico do próprio split.
    schema_rate = _num(understanding["schema_valid_rate"], 0.0)
    class_accuracy = _num(understanding["intent_accuracy"]["request_class_accuracy"], 0.0)
    fabricated = understanding["fabrication"]["fabricated_identifier_count"]
    if schema_rate >= 0.99 and class_accuracy >= 0.90 and fabricated == 0:
        understanding_assessment = TrainingAssessment.NO_TRAINING_NEEDED
    elif schema_rate >= 0.99 and class_accuracy >= 0.70:
        understanding_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    elif schema_rate >= 0.99:
        understanding_assessment = TrainingAssessment.TRAINING_CANDIDATE
    else:
        understanding_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    decisions.append(
        ComponentDecision(
            component="understanding",
            assessment=understanding_assessment,
            rationale="Contrato e classificação de intenção medidos contra o target do split DEV.",
            observed={
                "schema_valid_rate": schema_rate,
                "request_class_accuracy": class_accuracy,
                "entity_extraction_f1": understanding["entity_extraction"]["overall"]["f1"],
                "fabricated_identifier_count": fabricated,
            },
        )
    )

    # Planner — só aplicabilidade estrutural é decidível por regra.
    relevant = _num(planner["relevant_capability_rate"], 0.0)
    if planner["cases_reached"] == 0:
        planner_assessment = TrainingAssessment.INSUFFICIENT_EVIDENCE_TO_DECIDE
    elif _num(planner["schema_valid_rate"], 0.0) < 0.99:
        planner_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    elif relevant >= 0.90:
        planner_assessment = TrainingAssessment.NO_TRAINING_NEEDED
    else:
        planner_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    decisions.append(
        ComponentDecision(
            component="planner",
            assessment=planner_assessment,
            rationale="Adequação semântica do plano permanece NEEDS_HUMAN_REVIEW; só a aplicabilidade é medida.",
            observed={
                "schema_valid_rate": planner["schema_valid_rate"],
                "relevant_capability_rate": planner["relevant_capability_rate"],
                "unnecessary_capability_rate": planner["unnecessary_capability_rate"],
                "plan_completion_rate": planner["plan_completion_rate"],
            },
        )
    )

    # Investigator — contrato separado de comportamento.
    first_pass = _num(investigator["first_pass_valid_rate"], 0.0)
    reachable = correlation["cases_grounded_answer_reachable"]
    grounded_when_reachable = _num(correlation["grounded_completion_rate_when_reachable"], 0.0)
    data_dominant = coverage["cases_fully_aligned"] == 0
    if first_pass < 0.90:
        investigator_assessment = TrainingAssessment.TRAINING_CANDIDATE
    elif reachable == 0:
        investigator_assessment = TrainingAssessment.DATA_PROBLEM_FIRST
    elif grounded_when_reachable >= 0.60:
        investigator_assessment = TrainingAssessment.NO_TRAINING_NEEDED
    elif data_dominant:
        investigator_assessment = TrainingAssessment.DATA_PROBLEM_FIRST
    else:
        investigator_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    decisions.append(
        ComponentDecision(
            component="investigator",
            assessment=investigator_assessment,
            rationale="Contrato confiável não implica escolha de tool adequada; dados desalinhados vêm antes.",
            observed={
                "first_pass_valid_rate": first_pass,
                "grounded_completion_rate_when_reachable": grounded_when_reachable,
                "cases_grounded_answer_reachable": reachable,
                "average_tools": investigator["average_tools"],
                "cases_fully_aligned": coverage["cases_fully_aligned"],
            },
        )
    )

    # Reporter — só decidível se tiver sido alcançado.
    if reporter["cases_reached"] == 0:
        reporter_assessment = TrainingAssessment.INSUFFICIENT_EVIDENCE_TO_DECIDE
    elif (
        _num(reporter["completion_rate_among_reached"], 0.0) == 1.0
        and _num(reporter["unsupported_claim_rate"], 1.0) == 0.0
    ):
        reporter_assessment = TrainingAssessment.NO_TRAINING_NEEDED
    else:
        reporter_assessment = TrainingAssessment.PROMPT_CALIBRATION_FIRST
    decisions.append(
        ComponentDecision(
            component="reporter",
            assessment=reporter_assessment,
            rationale="Fidelidade é medida por regra; utilidade percebida do relatório permanece humana.",
            observed={
                "cases_reached": reporter["cases_reached"],
                "completion_rate_among_reached": reporter["completion_rate_among_reached"],
                "claim_preservation_rate": reporter["claim_preservation_rate"],
                "unsupported_claim_rate": reporter["unsupported_claim_rate"],
            },
        )
    )
    return decisions
