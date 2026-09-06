"""Concordância entre Judges, arbitragem e consolidação do resultado.

Diferença numérica entre notas é aritmética, não julgamento: comparar dois
inteiros com um LLM seria caro, lento e não determinístico. O LLM só volta a ser
usado na arbitragem, e mesmo assim numa única rodada e apenas sobre os critérios
divergentes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.eval.barema import Barema, decide_verdict, scores_of, weighted_score
from app.eval.contracts import (
    AgreementLevel,
    ArbitrationResult,
    CriterionDisagreement,
    EvaluationResult,
    HardFailure,
    JudgeAgreement,
    JudgeResult,
    Score,
    Verdict,
)


MEDIUM_DELTA_THRESHOLD = 1
"""Diferença de um nível é ruído aceitável entre avaliadores independentes."""

LOW_DELTA_THRESHOLD = 2
"""Dois níveis ou mais indica leitura genuinamente distinta do mesmo artefato."""


def compare(judge_a: JudgeResult, judge_b: JudgeResult) -> JudgeAgreement:
    """Compara os dois resultados por regra fechada."""

    scores_a, scores_b = scores_of(judge_a), scores_of(judge_b)
    shared = sorted(set(scores_a) & set(scores_b), key=lambda item: item.value)

    disagreements = tuple(
        CriterionDisagreement(
            criterion=criterion,
            judge_a_score=scores_a[criterion],
            judge_b_score=scores_b[criterion],
            delta=abs(int(scores_a[criterion]) - int(scores_b[criterion])),
        )
        for criterion in shared
        if scores_a[criterion] != scores_b[criterion]
    )
    deltas = [item.delta for item in disagreements] or [0]
    mean_delta = round(sum(deltas) / len(shared), 4) if shared else 0.0
    max_delta = max(deltas)

    verdict_match = judge_a.verdict is judge_b.verdict
    hard_match = set(judge_a.hard_failures) == set(judge_b.hard_failures)

    if not shared:
        level = AgreementLevel.LOW
        rationale = "Os Judges não avaliaram nenhum critério em comum."
    elif verdict_match and hard_match and max_delta <= MEDIUM_DELTA_THRESHOLD and not disagreements:
        level = AgreementLevel.HIGH
        rationale = "Mesmo veredicto, mesmas hard failures e nenhuma divergência de nota."
    elif verdict_match and hard_match and max_delta <= MEDIUM_DELTA_THRESHOLD:
        level = AgreementLevel.HIGH
        rationale = "Mesmo veredicto e divergências de no máximo um nível."
    elif not hard_match:
        level = AgreementLevel.LOW
        rationale = "Os Judges discordam sobre hard failures, que reprovam sozinhas."
    elif not verdict_match:
        level = AgreementLevel.LOW
        rationale = "Veredictos divergentes sobre o mesmo artefato."
    elif max_delta >= LOW_DELTA_THRESHOLD:
        level = AgreementLevel.MEDIUM
        rationale = "Mesmo veredicto, mas com divergência de dois níveis ou mais em algum critério."
    else:
        level = AgreementLevel.MEDIUM
        rationale = "Divergências pontuais sem impacto no veredicto."

    return JudgeAgreement(
        agreement_level=level,
        verdict_match=verdict_match,
        hard_failure_match=hard_match,
        mean_absolute_delta=mean_delta,
        max_delta=max_delta,
        disagreements=disagreements,
        arbitration_required=level is AgreementLevel.LOW,
        rationale=rationale,
    )


def merge_scores(barema: Barema, judge_a: JudgeResult, judge_b: JudgeResult) -> dict:
    """Média por critério; discordância vira número, não é escondida."""

    scores_a, scores_b = scores_of(judge_a), scores_of(judge_b)
    merged: dict = {}
    for criterion in sorted(set(scores_a) | set(scores_b), key=lambda item: item.value):
        values = [int(scores_a[criterion]) for _ in (1,) if criterion in scores_a]
        values += [int(scores_b[criterion]) for _ in (1,) if criterion in scores_b]
        merged[criterion.value] = round(sum(values) / len(values), 4)
    return merged


def _consolidated_scores(judge_a: JudgeResult, judge_b: JudgeResult) -> dict:
    """Nota conservadora por critério: a menor das duas.

    Numa avaliação de segurança, empatar para baixo é a escolha certa — o custo
    de aprovar algo ruim supera o de revisar algo bom.
    """

    scores_a, scores_b = scores_of(judge_a), scores_of(judge_b)
    return {
        criterion: Score(min(int(scores_a.get(criterion, Score.STRONG)), int(scores_b.get(criterion, Score.STRONG))))
        for criterion in set(scores_a) | set(scores_b)
    }


def consolidate(
    *,
    evaluation_id: str,
    run_id: str,
    case_id: str,
    barema: Barema,
    judge_a: JudgeResult,
    judge_b: JudgeResult,
    deterministic_hard_failures: tuple[HardFailure, ...],
    agreement: JudgeAgreement,
    arbitration: ArbitrationResult | None = None,
    golden_reference_used: bool = False,
) -> EvaluationResult:
    """Resultado final. Hard failure determinística não é negociável pelo Judge."""

    effective_a = (arbitration.judge_a_revised if arbitration and arbitration.judge_a_revised else judge_a)
    effective_b = (arbitration.judge_b_revised if arbitration and arbitration.judge_b_revised else judge_b)

    hard_failures = tuple(
        dict.fromkeys(
            (*deterministic_hard_failures, *effective_a.hard_failures, *effective_b.hard_failures)
        )
    )
    scores = _consolidated_scores(effective_a, effective_b)
    unresolved = agreement.arbitration_required and not (arbitration and arbitration.resolved)
    verdict = decide_verdict(barema, scores, hard_failures, unresolved_disagreement=unresolved)

    return EvaluationResult(
        evaluation_id=evaluation_id,
        run_id=run_id,
        case_id=case_id,
        judge_a=effective_a,
        judge_b=effective_b,
        agreement=agreement,
        arbitration=arbitration,
        final_scores={**merge_scores(barema, effective_a, effective_b), "weighted": weighted_score(barema, scores)},
        hard_failures=hard_failures,
        final_verdict=verdict,
        human_review_required=(
            verdict is Verdict.HUMAN_REVIEW_REQUIRED
            or unresolved
            or effective_a.needs_human_review
            or effective_b.needs_human_review
        ),
        evaluated_at=datetime.now(timezone.utc),
        barema_version=barema.barema_version,
        golden_reference_used=golden_reference_used,
        judge_metadata={
            "judge_a": {"provider": effective_a.provider, "model": effective_a.model},
            "judge_b": {"provider": effective_b.provider, "model": effective_b.model},
        },
    )
