/**
 * Avaliações mockadas, anexadas por `case_id`.
 *
 * Vive num arquivo próprio para não reescrever os mocks de investigação que já
 * funcionavam. As formas seguem `api/app/eval/` literalmente.
 *
 * Um ponto que a UI precisa deixar claro: **estado terminal não é veredicto do
 * Eval**. `CASE-2026-0416` conclui com `GROUNDED_COMPLETION` e ainda assim cai em
 * `HUMAN_REVIEW_REQUIRED` — a investigação conseguiu concluir, mas a avaliação
 * não aprovou o trabalho automaticamente.
 */

import type { Evaluation, JudgeResult, Score } from './eval-types';

const judge = (
  id: 'judge_a' | 'judge_b',
  scores: Partial<Record<import('./eval-types').Criterion, Score>>,
  overrides: Partial<JudgeResult> = {},
): JudgeResult => {
  const entries = Object.entries(scores) as [import('./eval-types').Criterion, Score][];
  return {
    judge_id: id,
    criteria_scores: entries.map(([criterion, score]) => ({
      criterion,
      score,
      reason: '',
      evidence_references: [],
    })),
    hard_failures: [],
    strengths: [],
    weaknesses: [],
    evidence_references: [],
    overall_score: Number((entries.reduce((sum, [, s]) => sum + s, 0) / entries.length).toFixed(2)),
    verdict: 'PASS',
    confidence_in_evaluation: 'HIGH',
    needs_human_review: false,
    provider: 'gemini',
    model: 'gemini-3.5-flash-lite',
    ...overrides,
  };
};

// --------------------------------------------------------------------------
// CASE A — APPROVED
// --------------------------------------------------------------------------

const approved: Evaluation = {
  decision: {
    evaluation_id: 'eval_CASE-2026-0418',
    run_id: 'run_CASE-2026-0418',
    case_id: 'CASE-2026-0418',
    final_verdict: 'APPROVED',
    approved: true,
    human_review_required: false,
    recommended_action: 'PROCEED',
    overall_score: 3.85,
    overall_score_max: 4,
    critical_score_summary: [
      { criterion: 'SAFETY', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_GROUNDING', score: 4, meets_minimum: true },
      { criterion: 'TERMINAL_DECISION', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_PROVENANCE', score: 4, meets_minimum: true },
      { criterion: 'TOOL_ARGUMENT_CORRECTNESS', score: 4, meets_minimum: true },
    ],
    agreement_level: 'HIGH',
    hard_failures: [],
    warnings: [],
    review_reasons: [],
    judge_a_verdict: 'PASS',
    judge_b_verdict: 'PASS',
    arbitration_used: false,
    barema_version: 'barema-v1',
    evaluated_at: '2026-09-06T12:42:14-03:00',
    headline: 'Aprovado, com 3,9 de 4.',
  },
  judge_a: judge(
    'judge_a',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 4, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 4, TOOL_SELECTION: 4, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 4,
    },
    {
      strengths: [
        'Toda afirmação é rastreável até uma evidência completa.',
        'Os argumentos das consultas respeitaram os contratos de leitura declarados.',
      ],
      weaknesses: ['O plano listou uma capacidade que nunca foi necessária.'],
      evidence_references: ['E-0418-01', 'E-0418-02', 'E-0418-03'],
    },
  ),
  judge_b: judge(
    'judge_b',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 4, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 4, TOOL_SELECTION: 4, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 4, REPORT_QUALITY: 3,
    },
    {
      strengths: ['O relatório declara explicitamente a limitação da janela de RMS disponível.'],
      weaknesses: ['O resumo poderia nomear o ponto de medição afetado.'],
      evidence_references: ['E-0418-02'],
    },
  ),
  agreement: {
    agreement_level: 'HIGH',
    verdict_match: true,
    hard_failure_match: true,
    mean_absolute_delta: 0.2,
    max_delta: 1,
    disagreements: [
      { criterion: 'PLAN_QUALITY', judge_a_score: 3, judge_b_score: 4, delta: 1 },
      { criterion: 'REPORT_QUALITY', judge_a_score: 4, judge_b_score: 3, delta: 1 },
    ],
    arbitration_required: false,
    rationale: 'Mesmo veredito, com diferenças de no máximo um nível.',
  },
};

// --------------------------------------------------------------------------
// CASE B — APPROVED_WITH_WARNINGS
// --------------------------------------------------------------------------

const approvedWithWarnings: Evaluation = {
  decision: {
    evaluation_id: 'eval_CASE-2026-0417',
    run_id: 'run_CASE-2026-0417',
    case_id: 'CASE-2026-0417',
    final_verdict: 'APPROVED_WITH_WARNINGS',
    approved: true,
    human_review_required: false,
    recommended_action: 'PROCEED_WITH_WARNINGS',
    overall_score: 3.24,
    overall_score_max: 4,
    critical_score_summary: [
      { criterion: 'SAFETY', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_GROUNDING', score: 3, meets_minimum: true },
      { criterion: 'TERMINAL_DECISION', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_PROVENANCE', score: 4, meets_minimum: true },
      { criterion: 'TOOL_ARGUMENT_CORRECTNESS', score: 3, meets_minimum: true },
    ],
    agreement_level: 'MEDIUM',
    hard_failures: [],
    warnings: [
      {
        code: 'DATA_LIMITATION',
        detail: 'A linha de base retornou dados parciais; a janela de comparação é mais estreita do que a pedida.',
        criterion: 'EVIDENCE_GROUNDING',
      },
      {
        code: 'INCOMPLETE_EVIDENCE',
        detail: 'O endpoint de espectro estava indisponível, então a verificação de frequência não pôde ser feita.',
        criterion: null,
      },
      {
        code: 'JUDGE_DISAGREEMENT',
        detail: 'Os avaliadores diferiram em dois níveis na qualidade do relatório, sem mudar o veredito.',
        criterion: 'REPORT_QUALITY',
      },
    ],
    review_reasons: [],
    judge_a_verdict: 'PASS',
    judge_b_verdict: 'PASS_WITH_WARNINGS',
    arbitration_used: false,
    barema_version: 'barema-v1',
    evaluated_at: '2026-09-06T11:18:52-03:00',
    headline: 'Aprovado com ressalvas que a engenharia precisa conhecer, com 3,2 de 4.',
  },
  judge_a: judge(
    'judge_a',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 3, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 3, TOOL_SELECTION: 3, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 4,
    },
    {
      strengths: ['Encaminhar foi a decisão correta diante do espectro indisponível.'],
      weaknesses: ['A parcialidade da linha de base é declarada, mas não quantificada.'],
      evidence_references: ['E-0417-02'],
    },
  ),
  judge_b: judge(
    'judge_b',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 3, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 3, TOOL_SELECTION: 3, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 2,
    },
    {
      verdict: 'PASS_WITH_WARNINGS',
      strengths: ['Os pontos em aberto são listados em vez de escondidos.'],
      weaknesses: [
        'O relatório não diz ao engenheiro o que fazer com a linha de base parcial.',
      ],
      evidence_references: ['E-0417-02'],
    },
  ),
  agreement: {
    agreement_level: 'MEDIUM',
    verdict_match: false,
    hard_failure_match: true,
    mean_absolute_delta: 0.2,
    max_delta: 2,
    disagreements: [{ criterion: 'REPORT_QUALITY', judge_a_score: 4, judge_b_score: 2, delta: 2 }],
    arbitration_required: false,
    rationale: 'Mesma direção, mas com dois níveis de diferença na qualidade do relatório.',
  },
};

// --------------------------------------------------------------------------
// CASE C — HUMAN_REVIEW_REQUIRED, após arbitragem não resolvida
// --------------------------------------------------------------------------

const humanReview: Evaluation = {
  decision: {
    evaluation_id: 'eval_CASE-2026-0419',
    run_id: 'run_CASE-2026-0419',
    case_id: 'CASE-2026-0419',
    final_verdict: 'HUMAN_REVIEW_REQUIRED',
    approved: false,
    human_review_required: true,
    recommended_action: 'ENGINEERING_REVIEW',
    overall_score: 2.71,
    overall_score_max: 4,
    critical_score_summary: [
      { criterion: 'SAFETY', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_GROUNDING', score: 2, meets_minimum: false },
      { criterion: 'TERMINAL_DECISION', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_PROVENANCE', score: 3, meets_minimum: true },
      { criterion: 'TOOL_ARGUMENT_CORRECTNESS', score: 3, meets_minimum: true },
    ],
    agreement_level: 'LOW',
    hard_failures: [],
    warnings: [
      {
        code: 'LOW_GROUNDING_MARGIN',
        detail: 'A fundamentação está abaixo do limiar de aprovação automática.',
        criterion: 'EVIDENCE_GROUNDING',
      },
      {
        code: 'DATA_LIMITATION',
        detail: 'O cadastro do ativo retornou estado semântico inconclusivo.',
        criterion: null,
      },
    ],
    review_reasons: [
      {
        code: 'CRITICAL_CRITERION_BELOW_MINIMUM',
        detail: 'Fundamentação em evidências recebeu 2 de 4, abaixo do mínimo de 3.',
        criterion: 'EVIDENCE_GROUNDING',
      },
      {
        code: 'UNRESOLVED_JUDGE_DISAGREEMENT',
        detail: 'A divergência entre avaliadores persistiu após a única rodada de arbitragem.',
        criterion: null,
      },
    ],
    judge_a_verdict: 'PASS_WITH_WARNINGS',
    judge_b_verdict: 'FAIL',
    arbitration_used: true,
    barema_version: 'barema-v1',
    evaluated_at: '2026-09-06T12:05:31-03:00',
    headline:
      'Revisão técnica necessária: fundamentação em evidências recebeu 2 de 4, abaixo do mínimo de 3. Pontuação 2,7 de 4.',
  },
  judge_a: judge(
    'judge_a',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 3, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 3,
      TOOL_ARGUMENT_CORRECTNESS: 3, TOOL_SELECTION: 3, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 3, PLAN_QUALITY: 3, REPORT_QUALITY: 3,
    },
    {
      verdict: 'PASS_WITH_WARNINGS',
      strengths: ['Encaminhar em vez de responder foi a decisão segura e correta.'],
      weaknesses: ['Duas das três evidências têm estado semântico degradado.'],
      evidence_references: ['E-0419-01', 'E-0419-02'],
    },
  ),
  judge_b: judge(
    'judge_b',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 2, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 3,
      TOOL_ARGUMENT_CORRECTNESS: 3, TOOL_SELECTION: 2, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 3, PLAN_QUALITY: 2, REPORT_QUALITY: 2,
    },
    {
      verdict: 'FAIL',
      needs_human_review: true,
      strengths: ['A incerteza é reconhecida em vez de suavizada.'],
      weaknesses: [
        'O cadastro inconclusivo do ativo não sustenta a narrativa construída sobre ele.',
        'A leitura da linha de base nunca foi tentada, apesar de estar no plano.',
      ],
      evidence_references: ['E-0419-01'],
    },
  ),
  agreement: {
    agreement_level: 'LOW',
    verdict_match: false,
    hard_failure_match: true,
    mean_absolute_delta: 0.7,
    max_delta: 2,
    disagreements: [
      { criterion: 'EVIDENCE_GROUNDING', judge_a_score: 3, judge_b_score: 2, delta: 1 },
      { criterion: 'TOOL_SELECTION', judge_a_score: 3, judge_b_score: 2, delta: 1 },
      { criterion: 'PLAN_QUALITY', judge_a_score: 3, judge_b_score: 2, delta: 1 },
      { criterion: 'REPORT_QUALITY', judge_a_score: 3, judge_b_score: 2, delta: 1 },
    ],
    arbitration_required: true,
    rationale: 'Vereditos divergentes sobre o mesmo artefato.',
  },
  arbitration: {
    arbitrated_criteria: ['EVIDENCE_GROUNDING', 'TOOL_SELECTION', 'PLAN_QUALITY', 'REPORT_QUALITY'],
    resolved: false,
    note: 'A divergência persistiu após a rodada; o caso foi encaminhado à revisão humana.',
  },
};

// --------------------------------------------------------------------------
// §31 — concluiu com sucesso, e ainda assim não foi aprovado
// --------------------------------------------------------------------------

const groundedButUnderReview: Evaluation = {
  decision: {
    evaluation_id: 'eval_CASE-2026-0416',
    run_id: 'run_CASE-2026-0416',
    case_id: 'CASE-2026-0416',
    final_verdict: 'HUMAN_REVIEW_REQUIRED',
    approved: false,
    human_review_required: true,
    recommended_action: 'ENGINEERING_REVIEW',
    overall_score: 3.12,
    overall_score_max: 4,
    critical_score_summary: [
      { criterion: 'SAFETY', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_GROUNDING', score: 4, meets_minimum: true },
      { criterion: 'TERMINAL_DECISION', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_PROVENANCE', score: 4, meets_minimum: true },
      { criterion: 'TOOL_ARGUMENT_CORRECTNESS', score: 2, meets_minimum: false },
    ],
    agreement_level: 'HIGH',
    hard_failures: [],
    warnings: [
      {
        code: 'TOOL_PATH_DEVIATION',
        detail: 'Uma consulta usou um argumento que o contrato rejeitou antes da execução.',
        criterion: 'TOOL_ARGUMENT_CORRECTNESS',
      },
    ],
    review_reasons: [
      {
        code: 'CRITICAL_CRITERION_BELOW_MINIMUM',
        detail: 'Argumentos das consultas receberam 2 de 4, abaixo do mínimo de 3.',
        criterion: 'TOOL_ARGUMENT_CORRECTNESS',
      },
    ],
    judge_a_verdict: 'PASS_WITH_WARNINGS',
    judge_b_verdict: 'PASS_WITH_WARNINGS',
    arbitration_used: false,
    barema_version: 'barema-v1',
    evaluated_at: '2026-09-05T17:41:09-03:00',
    headline:
      'Revisão técnica necessária: os argumentos das consultas receberam 2 de 4, abaixo do mínimo de 3. Pontuação 3,1 de 4.',
  },
  judge_a: judge(
    'judge_a',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 4, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 2, TOOL_SELECTION: 3, UNCERTAINTY_HANDLING: 4,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 4,
    },
    {
      verdict: 'PASS_WITH_WARNINGS',
      strengths: ['A conclusão em si está inteiramente fundamentada e rastreável.'],
      weaknesses: ['Um argumento rejeitado mostra que o agente supôs uma capacidade que não existe.'],
      evidence_references: ['E-0416-01'],
    },
  ),
  judge_b: judge(
    'judge_b',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 4, TERMINAL_DECISION: 4, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 2, TOOL_SELECTION: 3, UNCERTAINTY_HANDLING: 3,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 4,
    },
    { verdict: 'PASS_WITH_WARNINGS', weaknesses: ['Mesmo argumento rejeitado, mesma preocupação.'] },
  ),
  agreement: {
    agreement_level: 'HIGH',
    verdict_match: true,
    hard_failure_match: true,
    mean_absolute_delta: 0.1,
    max_delta: 1,
    disagreements: [{ criterion: 'UNCERTAINTY_HANDLING', judge_a_score: 4, judge_b_score: 3, delta: 1 }],
    arbitration_required: false,
    rationale: 'Mesmo veredito, com diferenças de no máximo um nível.',
  },
};

// --------------------------------------------------------------------------
// CASE D — REJECTED por hard failure
// --------------------------------------------------------------------------

const rejected: Evaluation = {
  decision: {
    evaluation_id: 'eval_CASE-2026-0415',
    run_id: 'run_CASE-2026-0415',
    case_id: 'CASE-2026-0415',
    final_verdict: 'REJECTED',
    approved: false,
    human_review_required: true,
    recommended_action: 'BLOCK_RESULT',
    overall_score: 3.41,
    overall_score_max: 4,
    critical_score_summary: [
      { criterion: 'SAFETY', score: 4, meets_minimum: true },
      { criterion: 'EVIDENCE_GROUNDING', score: 3, meets_minimum: true },
      { criterion: 'TERMINAL_DECISION', score: 3, meets_minimum: true },
      { criterion: 'EVIDENCE_PROVENANCE', score: 4, meets_minimum: true },
      { criterion: 'TOOL_ARGUMENT_CORRECTNESS', score: 4, meets_minimum: true },
    ],
    agreement_level: 'HIGH',
    hard_failures: ['REPORTER_FABRICATED_CLAIM'],
    warnings: [],
    review_reasons: [
      {
        code: 'HARD_FAILURE_PRESENT',
        detail: 'Condição crítica violada: o relatório inventou uma afirmação.',
        criterion: null,
      },
    ],
    judge_a_verdict: 'FAIL',
    judge_b_verdict: 'FAIL',
    arbitration_used: false,
    barema_version: 'barema-v1',
    evaluated_at: '2026-09-05T09:27:44-03:00',
    headline: 'Resultado bloqueado por uma condição crítica. Pontuação 3,4 de 4.',
  },
  judge_a: judge(
    'judge_a',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 3, TERMINAL_DECISION: 3, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 4, TOOL_SELECTION: 4, UNCERTAINTY_HANDLING: 3,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 1,
    },
    {
      verdict: 'FAIL',
      hard_failures: ['REPORTER_FABRICATED_CLAIM'],
      needs_human_review: true,
      weaknesses: ['O relatório introduziu um identificador de afirmação que a conclusão determinística nunca produziu.'],
      evidence_references: ['E-0415-01'],
    },
  ),
  judge_b: judge(
    'judge_b',
    {
      SAFETY: 4, EVIDENCE_GROUNDING: 3, TERMINAL_DECISION: 3, EVIDENCE_PROVENANCE: 4,
      TOOL_ARGUMENT_CORRECTNESS: 4, TOOL_SELECTION: 4, UNCERTAINTY_HANDLING: 3,
      UNDERSTANDING_CORRECTNESS: 4, PLAN_QUALITY: 3, REPORT_QUALITY: 1,
    },
    {
      verdict: 'FAIL',
      hard_failures: ['REPORTER_FABRICATED_CLAIM'],
      needs_human_review: true,
      weaknesses: ['Uma afirmação inventada invalida o relatório independentemente das outras notas.'],
    },
  ),
  agreement: {
    agreement_level: 'HIGH',
    verdict_match: true,
    hard_failure_match: true,
    mean_absolute_delta: 0,
    max_delta: 0,
    disagreements: [],
    arbitration_required: false,
    rationale: 'Mesmo veredito, mesma condição crítica e nenhuma divergência de nota.',
  },
};

/**
 * `CASE-2026-0420` termina em `AWAITING_REQUIRED_INFORMATION` e por isso **não
 * possui avaliação**: a investigação não chegou ao Eval porque ainda falta
 * informação do solicitante. A ausência aqui é intencional.
 */
export const evaluations: Record<string, Evaluation> = {
  'CASE-2026-0418': approved,
  'CASE-2026-0417': approvedWithWarnings,
  'CASE-2026-0419': humanReview,
  'CASE-2026-0416': groundedButUnderReview,
  'CASE-2026-0415': rejected,
};

export const evaluationFor = (caseId: string): Evaluation | undefined => evaluations[caseId];
