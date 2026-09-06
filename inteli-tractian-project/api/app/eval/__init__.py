"""Camada de avaliacao pos-execucao: barema, Judges independentes e arbitragem."""

from app.eval.adapter import build_evaluation_input
from app.eval.agreement import compare, consolidate, merge_scores
from app.eval.arbitration import arbitrate
from app.eval.barema import Barema, decide_verdict, detect_hard_failures, load_barema, scores_of, weighted_score
from app.eval.contracts import (
    AgreementLevel, ArbitrationResult, Criterion, CriterionScore, EvaluationInput, EvaluationReference,
    EvaluationResult, EvidenceSnapshot, HardFailure, JudgeAgreement, JudgeConfidence, JudgeResult, Score, Verdict,
)
from app.eval.final_policy import (
    CriticalScoreSummary, FinalEvaluationDecision, FinalVerdict, RecommendedAction, ReviewReason,
    ReviewReasonCode, WarningCode, WarningItem, critical_criteria, decide,
)
from app.eval.golden import GoldenAccessError, align_path, assert_no_golden_in_runtime, available_reference_ids, load_reference
from app.eval.judges import JudgeOutputError, JudgeRole, parse_judge_result, run_judge

__all__ = [
    "AgreementLevel", "ArbitrationResult", "CriticalScoreSummary", "FinalEvaluationDecision", "FinalVerdict",
    "RecommendedAction", "ReviewReason", "ReviewReasonCode", "WarningCode", "WarningItem", "critical_criteria", "decide", "Barema", "Criterion", "CriterionScore", "EvaluationInput",
    "EvaluationReference", "EvaluationResult", "EvidenceSnapshot", "GoldenAccessError", "HardFailure",
    "JudgeAgreement", "JudgeConfidence", "JudgeOutputError", "JudgeResult", "JudgeRole", "Score", "Verdict",
    "align_path", "arbitrate", "assert_no_golden_in_runtime", "available_reference_ids",
    "build_evaluation_input", "compare", "consolidate", "decide_verdict", "detect_hard_failures",
    "load_barema", "load_reference", "merge_scores", "parse_judge_result", "run_judge", "scores_of",
    "weighted_score",
]
