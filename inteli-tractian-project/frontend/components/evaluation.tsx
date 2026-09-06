/**
 * Avaliação da investigação.
 *
 * Ordem deliberada: o resultado final primeiro, os critérios logo abaixo, e os
 * avaliadores por último — recolhidos. Um engenheiro precisa saber se pode
 * seguir antes de precisar saber o que dois avaliadores acharam de cada item.
 *
 * O frontend não recalcula nada. `FinalEvaluationDecision` chega decidida pela
 * política do backend; aqui ela é traduzida e apresentada.
 */

import type {
  Criterion,
  Evaluation,
  FinalEvaluationDecision,
  JudgeResult,
  Score,
} from '@/lib/eval-types';
import {
  agreementLabel,
  confidenceLabel,
  criterionLabel,
  finalVerdictDescription,
  finalVerdictLabel,
  finalVerdictTone,
  formatScore,
  hardFailureLabel,
  judgeFocus,
  judgeName,
  judgeVerdictLabel,
  recommendedActionLabel,
  reviewReasonLabel,
  scoreLevelLabel,
  warningLabel,
} from '@/lib/labels';
import { baremaCriteria, WEIGHT_EXPLANATION } from '@/lib/barema';
import { analyzeJudges } from '@/lib/judge-analysis';

// --------------------------------------------------------------------------
// Resultado final
// --------------------------------------------------------------------------

/**
 * O resultado tem mais destaque do que qualquer nota de avaliador, do barema ou
 * da concordância. É a única informação que muda o que o engenheiro faz agora.
 */
export function DecisionBanner({ decision }: { decision: FinalEvaluationDecision }) {
  const tone = finalVerdictTone[decision.final_verdict];
  return (
    <section className={`verdict verdict--${tone}`} aria-labelledby="verdict-heading">
      <div className="verdict__main">
        <h2 className="verdict__name" id="verdict-heading">
          <span className="verdict__glyph" aria-hidden="true" />
          {finalVerdictLabel[decision.final_verdict]}
        </h2>
        <p className="verdict__desc">{finalVerdictDescription[decision.final_verdict]}</p>
      </div>
      <dl className="verdict__facts">
        <div>
          <dt>Pontuação</dt>
          <dd className="verdict__score">
            {formatScore(decision.overall_score)}
            <span> / {formatScore(decision.overall_score_max)}</span>
          </dd>
        </div>
        <div>
          <dt>Concordância dos avaliadores</dt>
          <dd>{agreementLabel[decision.agreement_level]}</dd>
        </div>
        <div>
          <dt>Próximo passo</dt>
          <dd className={`verdict__action verdict__action--${tone}`}>
            {recommendedActionLabel[decision.recommended_action]}
          </dd>
        </div>
      </dl>
    </section>
  );
}

// --------------------------------------------------------------------------
// Critérios
// --------------------------------------------------------------------------

function ScoreBar({ score, below }: { score: Score; below?: boolean }) {
  return (
    <span className={`score-bar ${below ? 'score-bar--below' : ''}`} aria-hidden="true">
      {[1, 2, 3, 4].map((step) => (
        <i key={step} className={step <= score ? 'on' : ''} />
      ))}
    </span>
  );
}

/**
 * Resumo do barema: os critérios de maior peso, que a política final trata como
 * críticos. A lista vem do backend em `critical_score_summary` — não é montada
 * nem reordenada aqui por conveniência visual.
 */
export function CriteriaSummary({
  decision,
  onOpenBarema,
}: {
  decision: FinalEvaluationDecision;
  onOpenBarema: () => void;
}) {
  if (decision.critical_score_summary.length === 0) return null;
  return (
    <div className="criteria">
      <ul className="criteria__list">
        {decision.critical_score_summary.map((item) => (
          <li key={item.criterion} className={item.meets_minimum ? '' : 'criteria__item--below'}>
            <span className="criteria__name">{criterionLabel[item.criterion]}</span>
            <ScoreBar score={item.score} below={!item.meets_minimum} />
            <span className="criteria__score">
              {item.score} <span>/ 4</span>
            </span>
            <span className="criteria__level">
              {item.meets_minimum ? scoreLevelLabel[item.score] : 'Abaixo do mínimo'}
            </span>
          </li>
        ))}
      </ul>
      <p className="criteria__note">
        {WEIGHT_EXPLANATION}{' '}
        <button type="button" className="link-button" onClick={onOpenBarema}>
          Ver barema completo
        </button>
      </p>
    </div>
  );
}

/** Os 11 critérios reais do `barema-v1`, com a nota de cada avaliador. */
export function BaremaTable({ evaluation }: { evaluation: Evaluation }) {
  const scoreFor = (judge: JudgeResult, criterion: Criterion) =>
    judge.criteria_scores.find((item) => item.criterion === criterion)?.score;

  return (
    <div className="table-wrap">
      <table className="grid-table grid-table--barema">
      <thead>
        <tr>
          <th scope="col">Critério</th>
          <th scope="col">O que pergunta</th>
          <th scope="col" className="num">
            Peso
          </th>
          <th scope="col" className="num">
            Aval. A
          </th>
          <th scope="col" className="num">
            Aval. B
          </th>
        </tr>
      </thead>
      <tbody>
        {baremaCriteria.map((criterion) => {
          const a = scoreFor(evaluation.judge_a, criterion.id);
          const b = scoreFor(evaluation.judge_b, criterion.id);
          const notScored = a === undefined && b === undefined;
          return (
            <tr key={criterion.id} className={notScored ? 'grid-table__row--muted' : ''}>
              <th scope="row">
                <span className="cell-strong">{criterionLabel[criterion.id]}</span>
                {criterion.onlyWithReference && (
                  <span className="cell-weak">Só pontua quando existe caso de referência</span>
                )}
              </th>
              <td className="cell-prose">{criterion.question}</td>
              <td className="num">{formatScore(criterion.weight)}</td>
              <td className="num">{a ?? '—'}</td>
              <td className="num">{b ?? '—'}</td>
            </tr>
          );
        })}
      </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------
// Achados
// --------------------------------------------------------------------------

interface Finding {
  code: string;
  label: string;
  detail: string;
  criterion?: string | null;
}

export function FindingList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: 'warning' | 'review' | 'danger';
  items: Finding[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="findings">
      <p className="label">{title}</p>
      <ul>
        {items.map((item) => (
          <li key={`${item.code}-${item.detail}`} className={`finding finding--${tone}`}>
            <p className="finding__label">{item.label}</p>
            <p className="finding__detail">{item.detail}</p>
            {item.criterion && <p className="finding__criterion">Critério: {item.criterion}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DecisionFindings({ decision }: { decision: FinalEvaluationDecision }) {
  return (
    <>
      <FindingList
        title="Condições críticas violadas"
        tone="danger"
        items={decision.hard_failures.map((code) => ({
          code,
          label: hardFailureLabel[code],
          detail: 'Esta condição reprova o resultado sozinha, independentemente da pontuação.',
        }))}
      />
      <FindingList
        title="Por que a revisão é necessária"
        tone="review"
        items={decision.review_reasons.map((item) => ({
          code: item.code,
          label: reviewReasonLabel[item.code],
          detail: item.detail,
          criterion: item.criterion ? criterionLabel[item.criterion] : null,
        }))}
      />
      <FindingList
        title="Ressalvas"
        tone="warning"
        items={decision.warnings.map((item) => ({
          code: item.code,
          label: warningLabel[item.code],
          detail: item.detail,
          criterion: item.criterion ? criterionLabel[item.criterion] : null,
        }))}
      />
    </>
  );
}

// --------------------------------------------------------------------------
// Análise dos avaliadores
// --------------------------------------------------------------------------

/**
 * A "discussão" dos avaliadores, montada só a partir de campos persistidos.
 * Não há diálogo simulado nem raciocínio interno: concordância vem de
 * `strengths` e de notas iguais, atenção vem de `weaknesses`, divergência vem de
 * `disagreements` com a justificativa que cada avaliador registrou.
 */
export function JudgeAnalysisSection({ evaluation }: { evaluation: Evaluation }) {
  const analysis = analyzeJudges(evaluation);
  const { agreement, arbitration } = evaluation;

  return (
    <div className="analysis">
      {(analysis.agreements.length > 0 || analysis.convergedCriteria.length > 0) && (
        <section className="analysis__block">
          <p className="label">Pontos de concordância</p>
          <ul className="analysis__list">
            {analysis.convergedCriteria.slice(0, 3).map((item) => (
              <li key={item.criterion}>
                {criterionLabel[item.criterion]}: os dois avaliaram como{' '}
                {scoreLevelLabel[item.score].toLowerCase()}.
              </li>
            ))}
            {analysis.agreements.map((note) => (
              <li key={note.text}>
                {note.text}
                <span className="analysis__source">{note.source}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {analysis.attentions.length > 0 && (
        <section className="analysis__block">
          <p className="label">Pontos de atenção</p>
          <ul className="analysis__list">
            {analysis.attentions.map((note) => (
              <li key={note.text}>
                {note.text}
                <span className="analysis__source">{note.source}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {analysis.divergences.length > 0 && (
        <section className="analysis__block">
          <p className="label">Divergências</p>
          <ul className="divergences">
            {analysis.divergences.map((item) => (
              <li key={item.criterion}>
                <p className="divergence__criterion">{criterionLabel[item.criterion]}</p>
                <p className="divergence__scores">
                  <span>Avaliador A: {item.judgeA.score} de 4</span>
                  <span>Avaliador B: {item.judgeB.score} de 4</span>
                  <span className="divergence__delta">
                    {item.delta === 1 ? 'um nível' : `${item.delta} níveis`} de diferença
                  </span>
                </p>
                {(item.judgeA.reason || item.judgeB.reason) && (
                  <div className="divergence__reasons">
                    {item.judgeA.reason && <p>Avaliador A: {item.judgeA.reason}</p>}
                    {item.judgeB.reason && <p>Avaliador B: {item.judgeB.reason}</p>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="analysis__block analysis__block--result">
        <p className="label">Resultado</p>
        <p className="analysis__result">
          Concordância: <strong>{agreementLabel[agreement.agreement_level]}</strong>.{' '}
          {agreement.rationale}
        </p>
        {arbitration ? (
          <p className="analysis__result">
            <strong>Arbitragem.</strong> Foi realizada uma rodada adicional sobre{' '}
            {arbitration.arbitrated_criteria.length === 1
              ? 'um critério divergente'
              : `${arbitration.arbitrated_criteria.length} critérios divergentes`}
            {': '}
            {arbitration.arbitrated_criteria.map((item) => criterionLabel[item]).join(', ')}.{' '}
            {arbitration.note}
          </p>
        ) : (
          !analysis.hasDivergence && (
            <p className="analysis__result">
              Os dois avaliadores chegaram a conclusões compatíveis. Não foi necessária arbitragem.
            </p>
          )
        )}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------
// Avaliadores — detalhe recolhido
// --------------------------------------------------------------------------

function JudgeCard({ judge }: { judge: JudgeResult }) {
  const notes = [...judge.strengths, ...judge.weaknesses].slice(0, 3);
  return (
    <details className="judge">
      <summary>
        <span className="judge__caret" aria-hidden="true" />
        <span className="judge__name">
          {judgeName[judge.judge_id]}
          <span>{judgeFocus[judge.judge_id]}</span>
        </span>
        <span className="judge__score">
          {formatScore(judge.overall_score)} <span>/ 4</span>
        </span>
        <span className={`judge__verdict judge__verdict--${judge.verdict}`}>
          {judgeVerdictLabel[judge.verdict]}
        </span>
      </summary>
      <div className="judge__body">
        <ul className="judge__criteria">
          {judge.criteria_scores.map((item) => (
            <li key={item.criterion} className={item.score <= 2 ? 'low' : ''}>
              <span>{criterionLabel[item.criterion]}</span>
              <b>{item.score}</b>
            </li>
          ))}
        </ul>
        {notes.length > 0 && (
          <ul className="judge__notes">
            {notes.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        )}
        <p className="judge__meta">
          Confiança do avaliador na própria avaliação: {confidenceLabel[judge.confidence_in_evaluation]}
          {judge.model ? ` · ${judge.model}` : ''}
        </p>
      </div>
    </details>
  );
}

export function JudgeCards({ evaluation }: { evaluation: Evaluation }) {
  return (
    <div className="judges">
      <JudgeCard judge={evaluation.judge_a} />
      <JudgeCard judge={evaluation.judge_b} />
    </div>
  );
}

// --------------------------------------------------------------------------
// Ausência de avaliação
// --------------------------------------------------------------------------

export function EvaluationNotReached({ terminalStateText }: { terminalStateText: string }) {
  return (
    <div className="notice">
      <p className="notice__title">Esta investigação não foi avaliada</p>
      <p>
        Ela terminou em <b>{terminalStateText.toLowerCase()}</b> e não chegou à etapa de avaliação. A
        avaliação acontece depois de uma conclusão ou de um encaminhamento — não há o que pontuar
        ainda, e isso é o comportamento esperado, não uma falha.
      </p>
    </div>
  );
}
