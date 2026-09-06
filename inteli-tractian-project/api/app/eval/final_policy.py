"""Decisão operacional final: dos Judges para o estado que o sistema opera.

Os Judges **avaliam**. Esta camada **decide**. A separação existe porque deixar o
modelo declarar sozinho `human_review_required` transformaria uma regra de
negócio numa opinião: dois artefatos idênticos poderiam receber destinos
diferentes, e ninguém saberia dizer por quê.

Aqui nada é opinião. Toda transição de estado é regra fechada sobre números que
já existem, e o frontend recebe a decisão pronta em vez de reinterpretá-la.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.eval.barema import Barema, scores_of
from app.eval.contracts import (
    AgreementLevel,
    Criterion,
    EvaluationResult,
    HardFailure,
    Identifier,
    Score,
    Text,
    Verdict,
)


class FinalVerdict(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_WARNINGS = "APPROVED_WITH_WARNINGS"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class RecommendedAction(str, Enum):
    PROCEED = "PROCEED"
    PROCEED_WITH_WARNINGS = "PROCEED_WITH_WARNINGS"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    BLOCK_RESULT = "BLOCK_RESULT"


_ACTION_FOR: dict[FinalVerdict, RecommendedAction] = {
    FinalVerdict.APPROVED: RecommendedAction.PROCEED,
    FinalVerdict.APPROVED_WITH_WARNINGS: RecommendedAction.PROCEED_WITH_WARNINGS,
    FinalVerdict.HUMAN_REVIEW_REQUIRED: RecommendedAction.ENGINEERING_REVIEW,
    FinalVerdict.REJECTED: RecommendedAction.BLOCK_RESULT,
}


class WarningCode(str, Enum):
    """Categorias fechadas. Aviso sem categoria não é acionável."""

    LOW_GROUNDING_MARGIN = "LOW_GROUNDING_MARGIN"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    REPORTER_FIDELITY_WARNING = "REPORTER_FIDELITY_WARNING"
    JUDGE_DISAGREEMENT = "JUDGE_DISAGREEMENT"
    DATA_LIMITATION = "DATA_LIMITATION"
    TOOL_PATH_DEVIATION = "TOOL_PATH_DEVIATION"
    NON_CRITICAL_CRITERION_BELOW_TARGET = "NON_CRITICAL_CRITERION_BELOW_TARGET"


class ReviewReasonCode(str, Enum):
    HARD_FAILURE_PRESENT = "HARD_FAILURE_PRESENT"
    CRITICAL_CRITERION_BELOW_MINIMUM = "CRITICAL_CRITERION_BELOW_MINIMUM"
    UNRESOLVED_JUDGE_DISAGREEMENT = "UNRESOLVED_JUDGE_DISAGREEMENT"
    JUDGE_VERDICT_CONFLICT = "JUDGE_VERDICT_CONFLICT"
    BOTH_JUDGES_FAILED = "BOTH_JUDGES_FAILED"
    OVERALL_SCORE_BELOW_MINIMUM = "OVERALL_SCORE_BELOW_MINIMUM"
    JUDGE_REQUESTED_HUMAN_REVIEW = "JUDGE_REQUESTED_HUMAN_REVIEW"


# Limiares declarados. Vêm do barema e da política de risco — nunca do Golden.
CRITICAL_MINIMUM = Score.ACCEPTABLE
"""Critério crítico abaixo de 3 não é aprovável automaticamente."""

OVERALL_MINIMUM = 2.0
"""Média ponderada abaixo disto não sustenta aprovação em nenhum cenário."""

APPROVAL_THRESHOLD = 3.0
"""A partir daqui a média é compatível com aprovação limpa."""


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WarningItem(PolicyModel):
    code: WarningCode
    detail: Text
    criterion: Criterion | None = None


class ReviewReason(PolicyModel):
    code: ReviewReasonCode
    detail: Text
    criterion: Criterion | None = None


class CriticalScoreSummary(PolicyModel):
    criterion: Criterion
    score: int = Field(ge=0, le=4)
    meets_minimum: bool


class FinalEvaluationDecision(PolicyModel):
    """Contrato pronto para consumo direto de backend e frontend."""

    evaluation_id: Identifier
    run_id: Identifier
    case_id: Identifier
    final_verdict: FinalVerdict
    approved: bool
    human_review_required: bool
    recommended_action: RecommendedAction
    overall_score: float = Field(ge=0.0, le=4.0)
    overall_score_max: float = 4.0
    critical_score_summary: tuple[CriticalScoreSummary, ...] = ()
    agreement_level: AgreementLevel
    hard_failures: tuple[HardFailure, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    review_reasons: tuple[ReviewReason, ...] = ()
    judge_a_verdict: Verdict
    judge_b_verdict: Verdict
    arbitration_used: bool
    barema_version: Identifier
    evaluated_at: datetime
    headline: Text
    """Frase única que o frontend pode renderizar sem interpretar regra."""


def critical_criteria(barema: Barema) -> tuple[Criterion, ...]:
    """Críticos são os de peso alto do próprio barema; não há segunda régua."""

    return tuple(
        spec.id for spec in barema.criteria if spec.weight >= barema.high_weight_threshold
    )


def _consolidated(result: EvaluationResult) -> dict[Criterion, Score]:
    """Preserva a consolidação conservadora: `min` entre os dois Judges.

    Em avaliação de segurança, divergência não pode elevar a nota. Trocar por
    média faria um Judge que viu problema ser diluído por um que não viu.
    """

    a, b = scores_of(result.judge_a), scores_of(result.judge_b)
    return {
        criterion: Score(min(int(a.get(criterion, Score.STRONG)), int(b.get(criterion, Score.STRONG))))
        for criterion in set(a) | set(b)
    }


def _headline(verdict: FinalVerdict, score: float, reasons: tuple[ReviewReason, ...]) -> str:
    if verdict is FinalVerdict.REJECTED:
        return f"Resultado bloqueado por condição crítica. Nota {score:.1f}/4."
    if verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED:
        first = reasons[0].detail if reasons else "Automação sem base segura para aprovar."
        return f"Revisão de engenharia necessária: {first} Nota {score:.1f}/4."
    if verdict is FinalVerdict.APPROVED_WITH_WARNINGS:
        return f"Aprovado com ressalvas que a engenharia deve conhecer. Nota {score:.1f}/4."
    return f"Aprovado. Nota {score:.1f}/4."


def decide(result: EvaluationResult, barema: Barema) -> FinalEvaluationDecision:
    """Converte uma avaliação em estado operacional, por regra fechada."""

    scores = _consolidated(result)
    criticals = critical_criteria(barema)
    overall = float(result.final_scores.get("weighted", 0.0))
    arbitration_used = result.arbitration is not None

    summary = tuple(
        CriticalScoreSummary(
            criterion=criterion,
            score=int(scores[criterion]),
            meets_minimum=int(scores[criterion]) >= int(CRITICAL_MINIMUM),
        )
        for criterion in criticals
        if criterion in scores
    )

    warnings: list[WarningItem] = []
    reasons: list[ReviewReason] = []

    # --- Hard failure tem precedência absoluta -----------------------------
    if result.hard_failures:
        reasons.append(
            ReviewReason(
                code=ReviewReasonCode.HARD_FAILURE_PRESENT,
                detail=f"Condição crítica violada: {', '.join(item.value for item in result.hard_failures)}.",
            )
        )
        verdict = FinalVerdict.REJECTED
        return FinalEvaluationDecision(
            evaluation_id=result.evaluation_id, run_id=result.run_id, case_id=result.case_id,
            final_verdict=verdict, approved=False, human_review_required=True,
            recommended_action=_ACTION_FOR[verdict], overall_score=overall,
            critical_score_summary=summary, agreement_level=result.agreement.agreement_level,
            hard_failures=result.hard_failures, warnings=(), review_reasons=tuple(reasons),
            judge_a_verdict=result.judge_a.verdict, judge_b_verdict=result.judge_b.verdict,
            arbitration_used=arbitration_used, barema_version=result.barema_version,
            evaluated_at=result.evaluated_at, headline=_headline(verdict, overall, tuple(reasons)),
        )

    # --- Critérios críticos ------------------------------------------------
    for item in summary:
        if not item.meets_minimum:
            reasons.append(
                ReviewReason(
                    code=ReviewReasonCode.CRITICAL_CRITERION_BELOW_MINIMUM,
                    detail=f"{item.criterion.value} em {item.score}/4, abaixo do mínimo {int(CRITICAL_MINIMUM)}.",
                    criterion=item.criterion,
                )
            )
            if item.criterion is Criterion.EVIDENCE_GROUNDING:
                warnings.append(
                    WarningItem(code=WarningCode.LOW_GROUNDING_MARGIN,
                                detail="Grounding abaixo do limiar de aprovação automática.",
                                criterion=item.criterion)
                )

    # --- Desacordo entre Judges -------------------------------------------
    if result.agreement.arbitration_required and not (result.arbitration and result.arbitration.resolved):
        reasons.append(
            ReviewReason(
                code=ReviewReasonCode.UNRESOLVED_JUDGE_DISAGREEMENT,
                detail="Divergência entre avaliadores persistiu após a rodada de arbitragem.",
            )
        )
    elif result.judge_a.verdict is not result.judge_b.verdict:
        warnings.append(
            WarningItem(code=WarningCode.JUDGE_DISAGREEMENT,
                        detail=f"Judge A concluiu {result.judge_a.verdict.value} e Judge B {result.judge_b.verdict.value}.")
        )

    if result.judge_a.verdict is Verdict.FAIL and result.judge_b.verdict is Verdict.FAIL:
        reasons.append(
            ReviewReason(code=ReviewReasonCode.BOTH_JUDGES_FAILED,
                         detail="Os dois avaliadores reprovaram, sem hard failure determinística que justifique bloqueio.")
        )
    elif Verdict.FAIL in {result.judge_a.verdict, result.judge_b.verdict}:
        reasons.append(
            ReviewReason(code=ReviewReasonCode.JUDGE_VERDICT_CONFLICT,
                         detail="Um avaliador reprovou e o outro não; a divergência precisa de julgamento humano.")
        )

    if any(judge.needs_human_review for judge in (result.judge_a, result.judge_b)):
        reasons.append(
            ReviewReason(code=ReviewReasonCode.JUDGE_REQUESTED_HUMAN_REVIEW,
                         detail="Ao menos um avaliador sinalizou necessidade de revisão humana.")
        )

    if overall < OVERALL_MINIMUM:
        reasons.append(
            ReviewReason(code=ReviewReasonCode.OVERALL_SCORE_BELOW_MINIMUM,
                         detail=f"Nota ponderada {overall:.2f} abaixo do mínimo {OVERALL_MINIMUM:.1f}.")
        )

    # --- Avisos não críticos ----------------------------------------------
    for criterion, score in sorted(scores.items(), key=lambda item: item[0].value):
        if criterion in criticals or int(score) >= int(CRITICAL_MINIMUM):
            continue
        code = {
            Criterion.REPORT_QUALITY: WarningCode.REPORTER_FIDELITY_WARNING,
            Criterion.GOLDEN_ALIGNMENT: WarningCode.TOOL_PATH_DEVIATION,
        }.get(criterion, WarningCode.NON_CRITICAL_CRITERION_BELOW_TARGET)
        warnings.append(
            WarningItem(code=code, detail=f"{criterion.value} em {int(score)}/4.", criterion=criterion)
        )

    if result.agreement.agreement_level is AgreementLevel.MEDIUM:
        warnings.append(
            WarningItem(code=WarningCode.JUDGE_DISAGREEMENT,
                        detail="Divergência de dois níveis ou mais em algum critério, sem impacto no veredicto.")
        )

    # --- Estado final ------------------------------------------------------
    if reasons:
        verdict = FinalVerdict.HUMAN_REVIEW_REQUIRED
    elif overall >= APPROVAL_THRESHOLD and not warnings and result.agreement.agreement_level is AgreementLevel.HIGH:
        verdict = FinalVerdict.APPROVED
    else:
        verdict = FinalVerdict.APPROVED_WITH_WARNINGS

    return FinalEvaluationDecision(
        evaluation_id=result.evaluation_id, run_id=result.run_id, case_id=result.case_id,
        final_verdict=verdict, approved=verdict in {FinalVerdict.APPROVED, FinalVerdict.APPROVED_WITH_WARNINGS},
        human_review_required=verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED,
        recommended_action=_ACTION_FOR[verdict], overall_score=overall,
        critical_score_summary=summary, agreement_level=result.agreement.agreement_level,
        hard_failures=(), warnings=tuple(warnings), review_reasons=tuple(reasons),
        judge_a_verdict=result.judge_a.verdict, judge_b_verdict=result.judge_b.verdict,
        arbitration_used=arbitration_used, barema_version=result.barema_version,
        evaluated_at=result.evaluated_at, headline=_headline(verdict, overall, tuple(reasons)),
    )
