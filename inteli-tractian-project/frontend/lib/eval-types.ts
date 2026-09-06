/**
 * Contratos da camada de avaliação, espelhados de `api/app/eval/`.
 *
 * Os nomes e as formas seguem o backend literalmente. O frontend não recalcula
 * regra de negócio: ele recebe `FinalEvaluationDecision` pronta e renderiza.
 */

/** Espelha `app.eval.contracts.Criterion`. */
export type Criterion =
  | 'UNDERSTANDING_CORRECTNESS'
  | 'PLAN_QUALITY'
  | 'TOOL_SELECTION'
  | 'TOOL_ARGUMENT_CORRECTNESS'
  | 'EVIDENCE_GROUNDING'
  | 'EVIDENCE_PROVENANCE'
  | 'UNCERTAINTY_HANDLING'
  | 'TERMINAL_DECISION'
  | 'SAFETY'
  | 'REPORT_QUALITY'
  | 'GOLDEN_ALIGNMENT';

/** Escala 0–4 do barema. Cada nível tem semântica declarada no backend. */
export type Score = 0 | 1 | 2 | 3 | 4;

export type JudgeVerdict = 'PASS' | 'PASS_WITH_WARNINGS' | 'FAIL' | 'HUMAN_REVIEW_REQUIRED';

export type JudgeConfidence = 'HIGH' | 'MEDIUM' | 'LOW';

export type AgreementLevel = 'HIGH' | 'MEDIUM' | 'LOW';

/** Espelha `app.eval.contracts.HardFailure`. Reprovam sozinhas. */
export type HardFailure =
  | 'FORBIDDEN_ACTION_EXECUTED'
  | 'CLAIM_WITHOUT_EVIDENCE'
  | 'EVIDENCE_REFERENCE_NOT_FOUND'
  | 'BROKEN_EVIDENCE_LINEAGE'
  | 'GOLDEN_LEAKED_INTO_RUNTIME'
  | 'UNKNOWN_TOOL_EXECUTED'
  | 'UNGROUNDED_ANSWER'
  | 'SECRET_EXPOSED'
  | 'CHAIN_OF_THOUGHT_PERSISTED'
  | 'REPORTER_FABRICATED_CLAIM';

/** Espelha `app.eval.final_policy.FinalVerdict`. */
export type FinalVerdict =
  | 'APPROVED'
  | 'APPROVED_WITH_WARNINGS'
  | 'HUMAN_REVIEW_REQUIRED'
  | 'REJECTED';

/** Espelha `app.eval.final_policy.RecommendedAction`. */
export type RecommendedAction =
  | 'PROCEED'
  | 'PROCEED_WITH_WARNINGS'
  | 'ENGINEERING_REVIEW'
  | 'BLOCK_RESULT';

export type WarningCode =
  | 'LOW_GROUNDING_MARGIN'
  | 'INCOMPLETE_EVIDENCE'
  | 'REPORTER_FIDELITY_WARNING'
  | 'JUDGE_DISAGREEMENT'
  | 'DATA_LIMITATION'
  | 'TOOL_PATH_DEVIATION'
  | 'NON_CRITICAL_CRITERION_BELOW_TARGET';

export type ReviewReasonCode =
  | 'HARD_FAILURE_PRESENT'
  | 'CRITICAL_CRITERION_BELOW_MINIMUM'
  | 'UNRESOLVED_JUDGE_DISAGREEMENT'
  | 'JUDGE_VERDICT_CONFLICT'
  | 'BOTH_JUDGES_FAILED'
  | 'OVERALL_SCORE_BELOW_MINIMUM'
  | 'JUDGE_REQUESTED_HUMAN_REVIEW';

export interface CriterionScore {
  criterion: Criterion;
  score: Score;
  reason: string;
  /** Obrigatório no backend quando a nota é ≤ 2 em critérios de grounding. */
  evidence_references: string[];
}

export interface JudgeResult {
  judge_id: 'judge_a' | 'judge_b';
  criteria_scores: CriterionScore[];
  hard_failures: HardFailure[];
  strengths: string[];
  weaknesses: string[];
  evidence_references: string[];
  overall_score: number;
  verdict: JudgeVerdict;
  /** Confiança do avaliador na própria avaliação, não na investigação. */
  confidence_in_evaluation: JudgeConfidence;
  needs_human_review: boolean;
  provider: string | null;
  model: string | null;
}

export interface CriterionDisagreement {
  criterion: Criterion;
  judge_a_score: Score;
  judge_b_score: Score;
  delta: number;
}

export interface JudgeAgreement {
  agreement_level: AgreementLevel;
  verdict_match: boolean;
  hard_failure_match: boolean;
  mean_absolute_delta: number;
  max_delta: number;
  disagreements: CriterionDisagreement[];
  arbitration_required: boolean;
  rationale: string;
}

export interface ArbitrationResult {
  arbitrated_criteria: Criterion[];
  resolved: boolean;
  note: string;
}

export interface WarningItem {
  code: WarningCode;
  detail: string;
  criterion: Criterion | null;
}

export interface ReviewReason {
  code: ReviewReasonCode;
  detail: string;
  criterion: Criterion | null;
}

export interface CriticalScoreSummary {
  criterion: Criterion;
  score: Score;
  meets_minimum: boolean;
}

/**
 * Espelha `app.eval.final_policy.FinalEvaluationDecision`.
 *
 * Este é o contrato que o frontend consome. `headline`, `approved`,
 * `human_review_required` e `recommended_action` já vêm decididos.
 */
export interface FinalEvaluationDecision {
  evaluation_id: string;
  run_id: string;
  case_id: string;
  final_verdict: FinalVerdict;
  approved: boolean;
  human_review_required: boolean;
  recommended_action: RecommendedAction;
  overall_score: number;
  overall_score_max: number;
  critical_score_summary: CriticalScoreSummary[];
  agreement_level: AgreementLevel;
  hard_failures: HardFailure[];
  warnings: WarningItem[];
  review_reasons: ReviewReason[];
  judge_a_verdict: JudgeVerdict;
  judge_b_verdict: JudgeVerdict;
  arbitration_used: boolean;
  barema_version: string;
  evaluated_at: string;
  headline: string;
}

/** Bloco completo de avaliação anexado a uma investigação. */
export interface Evaluation {
  decision: FinalEvaluationDecision;
  judge_a: JudgeResult;
  judge_b: JudgeResult;
  agreement: JudgeAgreement;
  arbitration?: ArbitrationResult;
}

/* Os rótulos de apresentação vivem em `lib/labels.ts`. Este arquivo guarda
   apenas os contratos, para que exista uma única fonte de tradução. */
