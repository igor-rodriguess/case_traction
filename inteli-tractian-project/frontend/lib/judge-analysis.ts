/**
 * Organiza a análise dos dois avaliadores para leitura humana.
 *
 * Este módulo **não inventa diálogo** e **não expõe raciocínio interno**. Ele
 * apenas agrupa campos que já vêm persistidos nos contratos — `strengths`,
 * `weaknesses`, `criteria_scores` e `disagreements` — em três blocos que um
 * engenheiro consegue ler: no que concordaram, o que preocupa, onde divergiram.
 *
 * Nada aqui recalcula veredicto ou pontuação.
 */

import type { Criterion, Evaluation, JudgeResult, Score } from './eval-types';
import { baremaCriterionById } from './barema';

export interface AnalysisNote {
  text: string;
  /** Quem registrou a observação. "Ambos" quando os dois escreveram o mesmo. */
  source: 'Avaliador A' | 'Avaliador B' | 'Ambos';
}

export interface Divergence {
  criterion: Criterion;
  judgeA: { score: Score; reason: string };
  judgeB: { score: Score; reason: string };
  delta: number;
}

export interface JudgeAnalysis {
  agreements: AnalysisNote[];
  convergedCriteria: { criterion: Criterion; score: Score }[];
  attentions: AnalysisNote[];
  divergences: Divergence[];
  hasDivergence: boolean;
}

const scoreOf = (judge: JudgeResult, criterion: Criterion): Score | undefined =>
  judge.criteria_scores.find((item) => item.criterion === criterion)?.score;

const reasonOf = (judge: JudgeResult, criterion: Criterion): string =>
  judge.criteria_scores.find((item) => item.criterion === criterion)?.reason ?? '';

const weightOf = (criterion: Criterion): number => baremaCriterionById(criterion)?.weight ?? 0;

/** Une listas de texto dos dois avaliadores, marcando quem disse o quê. */
function merge(a: string[], b: string[]): AnalysisNote[] {
  const notes: AnalysisNote[] = [];
  for (const text of a) {
    notes.push({ text, source: b.includes(text) ? 'Ambos' : 'Avaliador A' });
  }
  for (const text of b) {
    if (!a.includes(text)) notes.push({ text, source: 'Avaliador B' });
  }
  return notes;
}

export function analyzeJudges(evaluation: Evaluation): JudgeAnalysis {
  const { judge_a: a, judge_b: b, agreement } = evaluation;

  const divergentCriteria = new Set(agreement.disagreements.map((item) => item.criterion));

  /**
   * Convergência real: mesmo critério, mesma nota, e nota suficiente. Notas
   * baixas iguais não são um ponto de concordância positivo — são um problema
   * compartilhado, e aparecem em "pontos de atenção".
   */
  const convergedCriteria = a.criteria_scores
    .filter((item) => {
      const other = scoreOf(b, item.criterion);
      return other === item.score && item.score >= 3 && !divergentCriteria.has(item.criterion);
    })
    .map((item) => ({ criterion: item.criterion, score: item.score }))
    .sort((x, y) => weightOf(y.criterion) - weightOf(x.criterion));

  const sharedLowCriteria = a.criteria_scores
    .filter((item) => {
      const other = scoreOf(b, item.criterion);
      return other === item.score && item.score <= 2;
    })
    .map((item) => ({ criterion: item.criterion, score: item.score }));

  const divergences: Divergence[] = agreement.disagreements
    .map((item) => ({
      criterion: item.criterion,
      judgeA: { score: item.judge_a_score, reason: reasonOf(a, item.criterion) },
      judgeB: { score: item.judge_b_score, reason: reasonOf(b, item.criterion) },
      delta: item.delta,
    }))
    .sort((x, y) => y.delta - x.delta || weightOf(y.criterion) - weightOf(x.criterion));

  const attentions = merge(a.weaknesses, b.weaknesses);
  for (const item of sharedLowCriteria) {
    attentions.push({
      text: `Nota ${item.score} de 4 atribuída pelos dois avaliadores.`,
      source: 'Ambos',
    });
  }

  return {
    agreements: merge(a.strengths, b.strengths),
    convergedCriteria,
    attentions,
    divergences,
    hasDivergence: divergences.length > 0 || !agreement.verdict_match,
  };
}
