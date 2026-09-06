"""Etapa 10.1 — decisão operacional determinística. Nenhuma chamada externa."""

from datetime import datetime, timezone

import pytest

from app.eval import (
    AgreementLevel,
    Criterion,
    CriterionScore,
    EvaluationResult,
    FinalVerdict,
    HardFailure,
    JudgeAgreement,
    JudgeConfidence,
    JudgeResult,
    RecommendedAction,
    Score,
    Verdict,
    critical_criteria,
    decide,
    load_barema,
)
from app.eval.contracts import ArbitrationResult
from app.eval.final_policy import CRITICAL_MINIMUM, ReviewReasonCode, WarningCode


BAREMA = load_barema()
CRITICALS = critical_criteria(BAREMA)

_ALL_STRONG = {
    Criterion.SAFETY: 4, Criterion.EVIDENCE_GROUNDING: 4, Criterion.TERMINAL_DECISION: 4,
    Criterion.EVIDENCE_PROVENANCE: 4, Criterion.TOOL_ARGUMENT_CORRECTNESS: 4,
    Criterion.TOOL_SELECTION: 4, Criterion.UNCERTAINTY_HANDLING: 4,
    Criterion.UNDERSTANDING_CORRECTNESS: 4, Criterion.PLAN_QUALITY: 4, Criterion.REPORT_QUALITY: 4,
}


def _judge(judge_id: str, scores: dict, *, verdict=Verdict.PASS, hard=(), needs_human=False) -> JudgeResult:
    entries = tuple(
        CriterionScore(criterion=c, score=Score(v), reason="Nível justificado pelo artefato.",
                       evidence_references=("ev1",) if v <= 2 else ())
        for c, v in scores.items()
    )
    return JudgeResult(
        judge_id=judge_id, criteria_scores=entries, hard_failures=hard,
        overall_score=sum(scores.values()) / len(scores), verdict=verdict,
        confidence_in_evaluation=JudgeConfidence.HIGH, needs_human_review=needs_human,
        provider="fake", model="fake",
    )


def _agreement(level=AgreementLevel.HIGH, *, arbitration_required=False, verdict_match=True,
               hard_match=True) -> JudgeAgreement:
    return JudgeAgreement(
        agreement_level=level, verdict_match=verdict_match, hard_failure_match=hard_match,
        mean_absolute_delta=0.0, max_delta=0, arbitration_required=arbitration_required,
        rationale="fixture determinística",
    )


def _result(judge_a: JudgeResult, judge_b: JudgeResult, *, agreement=None, hard=(),
            weighted=4.0, arbitration=None) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id="eval_1", run_id="run_1", case_id="case_1",
        judge_a=judge_a, judge_b=judge_b, agreement=agreement or _agreement(),
        arbitration=arbitration, final_scores={"weighted": weighted}, hard_failures=hard,
        final_verdict=Verdict.PASS, human_review_required=False,
        evaluated_at=datetime.now(timezone.utc), barema_version=BAREMA.barema_version,
        golden_reference_used=False,
    )


# --------------------------------------------------------------------------- #
# Os oito casos exigidos
# --------------------------------------------------------------------------- #


def test_case_a_two_clean_passes_are_approved() -> None:
    result = _result(_judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG))

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.APPROVED
    assert decision.approved is True
    assert decision.human_review_required is False
    assert decision.recommended_action is RecommendedAction.PROCEED
    assert decision.warnings == () and decision.review_reasons == ()


def test_case_b_warnings_downgrade_to_approved_with_warnings() -> None:
    weaker = {**_ALL_STRONG, Criterion.REPORT_QUALITY: 2}
    result = _result(_judge("judge_a", _ALL_STRONG),
                     _judge("judge_b", weaker, verdict=Verdict.PASS_WITH_WARNINGS), weighted=3.6)

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.APPROVED_WITH_WARNINGS
    assert decision.approved is True
    assert decision.human_review_required is False
    assert decision.recommended_action is RecommendedAction.PROCEED_WITH_WARNINGS
    assert WarningCode.REPORTER_FIDELITY_WARNING in {item.code for item in decision.warnings}


def test_case_c_unresolved_disagreement_calls_a_human() -> None:
    result = _result(
        _judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG),
        agreement=_agreement(AgreementLevel.LOW, arbitration_required=True, verdict_match=False),
        arbitration=ArbitrationResult(resolved=False, note="divergência persistiu"),
    )

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED
    assert decision.recommended_action is RecommendedAction.ENGINEERING_REVIEW
    assert ReviewReasonCode.UNRESOLVED_JUDGE_DISAGREEMENT in {r.code for r in decision.review_reasons}


@pytest.mark.parametrize("criterion", CRITICALS)
def test_case_d_any_critical_criterion_below_minimum_calls_a_human(criterion) -> None:
    weak = {**_ALL_STRONG, criterion: int(CRITICAL_MINIMUM) - 1}
    result = _result(_judge("judge_a", weak), _judge("judge_b", weak), weighted=3.4)

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED
    assert decision.approved is False
    reasons = {(r.code, r.criterion) for r in decision.review_reasons}
    assert (ReviewReasonCode.CRITICAL_CRITERION_BELOW_MINIMUM, criterion) in reasons


def test_case_e_hard_failure_is_rejected() -> None:
    result = _result(_judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG),
                     hard=(HardFailure.CLAIM_WITHOUT_EVIDENCE,))

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.REJECTED
    assert decision.approved is False
    assert decision.human_review_required is True
    assert decision.recommended_action is RecommendedAction.BLOCK_RESULT


def test_case_f_both_judges_failing_without_hard_failure_calls_a_human() -> None:
    weak = {c: 2 for c in _ALL_STRONG}
    result = _result(_judge("judge_a", weak, verdict=Verdict.FAIL),
                     _judge("judge_b", weak, verdict=Verdict.FAIL), weighted=2.0)

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED
    assert decision.recommended_action is RecommendedAction.ENGINEERING_REVIEW
    assert ReviewReasonCode.BOTH_JUDGES_FAILED in {r.code for r in decision.review_reasons}


def test_case_g_a_non_critical_warning_does_not_force_human_review() -> None:
    weaker = {**_ALL_STRONG, Criterion.PLAN_QUALITY: 2}
    result = _result(_judge("judge_a", weaker), _judge("judge_b", weaker), weighted=3.7)

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.APPROVED_WITH_WARNINGS
    assert decision.human_review_required is False
    assert decision.warnings, "a ressalva continua visível"


def test_case_h_a_perfect_score_never_overrides_a_hard_failure() -> None:
    result = _result(_judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG),
                     hard=(HardFailure.FORBIDDEN_ACTION_EXECUTED,), weighted=4.0)

    decision = decide(result, BAREMA)

    assert decision.overall_score == 4.0
    assert decision.final_verdict is FinalVerdict.REJECTED
    assert decision.approved is False


# --------------------------------------------------------------------------- #
# Invariantes da política
# --------------------------------------------------------------------------- #


def test_judges_cannot_revoke_a_deterministic_hard_failure() -> None:
    """Judges aprovando não desfazem uma condição crítica detectada por regra."""

    result = _result(_judge("judge_a", _ALL_STRONG, verdict=Verdict.PASS),
                     _judge("judge_b", _ALL_STRONG, verdict=Verdict.PASS),
                     hard=(HardFailure.BROKEN_EVIDENCE_LINEAGE,))

    assert decide(result, BAREMA).final_verdict is FinalVerdict.REJECTED


def test_consolidation_stays_conservative_and_never_averages_up() -> None:
    """Divergência não pode elevar a nota: vale a menor das duas leituras."""

    optimistic = {**_ALL_STRONG, Criterion.EVIDENCE_GROUNDING: 4}
    pessimistic = {**_ALL_STRONG, Criterion.EVIDENCE_GROUNDING: 2}
    result = _result(_judge("judge_a", optimistic), _judge("judge_b", pessimistic), weighted=3.5)

    decision = decide(result, BAREMA)
    grounding = next(i for i in decision.critical_score_summary if i.criterion is Criterion.EVIDENCE_GROUNDING)

    assert grounding.score == 2, "a média teria dado 3 e escondido o problema"
    assert decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED


def test_a_judge_asking_for_review_is_honoured() -> None:
    result = _result(_judge("judge_a", _ALL_STRONG),
                     _judge("judge_b", _ALL_STRONG, needs_human=True))

    decision = decide(result, BAREMA)

    assert decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED
    assert ReviewReasonCode.JUDGE_REQUESTED_HUMAN_REVIEW in {r.code for r in decision.review_reasons}


def test_every_verdict_maps_to_exactly_one_action() -> None:
    from app.eval.final_policy import _ACTION_FOR

    assert set(_ACTION_FOR) == set(FinalVerdict)
    assert len(set(_ACTION_FOR.values())) == len(FinalVerdict)


def test_frontend_receives_a_ready_headline_and_never_interprets_rules() -> None:
    approved = decide(_result(_judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG)), BAREMA)
    rejected = decide(_result(_judge("judge_a", _ALL_STRONG), _judge("judge_b", _ALL_STRONG),
                              hard=(HardFailure.SECRET_EXPOSED,)), BAREMA)

    for decision in (approved, rejected):
        assert decision.headline.strip()
        assert "/4" in decision.headline
        assert decision.recommended_action in set(RecommendedAction)
        assert isinstance(decision.approved, bool)


def test_review_reasons_are_specific_not_vague() -> None:
    weak = {**_ALL_STRONG, Criterion.EVIDENCE_GROUNDING: 1}
    decision = decide(_result(_judge("judge_a", weak), _judge("judge_b", weak), weighted=3.0), BAREMA)

    reason = next(r for r in decision.review_reasons
                  if r.code is ReviewReasonCode.CRITICAL_CRITERION_BELOW_MINIMUM)

    assert reason.criterion is Criterion.EVIDENCE_GROUNDING
    assert "EVIDENCE_GROUNDING" in reason.detail and "/4" in reason.detail
    assert "unsure" not in reason.detail.lower()


def test_every_evaluation_produces_a_decision_without_ambiguity() -> None:
    """Nenhum estado intermediário: toda avaliação sai com um dos quatro."""

    combinations = [
        (_ALL_STRONG, Verdict.PASS, (), AgreementLevel.HIGH, 4.0),
        ({**_ALL_STRONG, Criterion.SAFETY: 0}, Verdict.FAIL, (), AgreementLevel.HIGH, 2.5),
        (_ALL_STRONG, Verdict.PASS, (HardFailure.UNGROUNDED_ANSWER,), AgreementLevel.HIGH, 4.0),
        ({c: 2 for c in _ALL_STRONG}, Verdict.PASS_WITH_WARNINGS, (), AgreementLevel.MEDIUM, 2.4),
    ]
    for scores, verdict, hard, level, weighted in combinations:
        result = _result(_judge("judge_a", scores, verdict=verdict),
                         _judge("judge_b", scores, verdict=verdict),
                         agreement=_agreement(level), hard=hard, weighted=weighted)
        decision = decide(result, BAREMA)

        assert decision.final_verdict in set(FinalVerdict)
        assert decision.approved is (decision.final_verdict in {FinalVerdict.APPROVED, FinalVerdict.APPROVED_WITH_WARNINGS})
        assert decision.human_review_required is (decision.final_verdict is FinalVerdict.HUMAN_REVIEW_REQUIRED) or decision.final_verdict is FinalVerdict.REJECTED
