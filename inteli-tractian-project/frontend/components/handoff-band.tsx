/**
 * Faixa de revisão técnica dentro do dossiê.
 *
 * §17: quando o caso exige um engenheiro, isso não pode ficar escondido atrás de
 * um botão que abre um painel estreito. A faixa ocupa a largura toda e responde,
 * lado a lado, as quatro perguntas de quem vai assumir o caso: por quê, o que já
 * foi feito, o que falta, e qual é o próximo passo.
 */

import type { Evaluation } from '@/lib/eval-types';
import type { Investigation } from '@/lib/investigation-types';
import { handoffReason, recommendedActionLabel, reviewReasonLabel } from '@/lib/labels';

export function HandoffBand({
  item,
  evaluation,
  openReview,
}: {
  item: Investigation;
  evaluation?: Evaluation;
  openReview: () => void;
}) {
  const handoff = item.human_handoff;
  const decision = evaluation?.decision;
  const blocked = decision?.final_verdict === 'REJECTED';
  const reason = decision?.review_reasons[0];

  const done = item.plan_objectives;
  const missing = [...(handoff?.missing_information ?? []), ...item.unresolved_points];

  return (
    <section className={`handoff-band ${blocked ? 'handoff-band--blocked' : ''}`}>
      <header className="handoff-band__head">
        <h3>{blocked ? 'Resultado bloqueado' : 'Revisão técnica necessária'}</h3>
        <p>
          {blocked
            ? 'Uma condição crítica foi violada. O caso segue para a engenharia, mas o resultado não deve ser usado como resposta.'
            : 'A avaliação não encontrou segurança suficiente para aprovar automaticamente esta investigação.'}
        </p>
      </header>

      <div className="handoff-band__grid">
        <div>
          <p className="label">Motivo</p>
          <p className="handoff-band__reason">
            {reason
              ? reviewReasonLabel[reason.code]
              : handoffReason(handoff?.reason_codes[0] ?? 'UNRESOLVED_DATA_GAP')}
          </p>
          <p className="handoff-band__detail">
            {reason?.detail ??
              item.unresolved_points[0] ??
              'A evidência disponível não sustentava uma conclusão.'}
          </p>
        </div>

        <div>
          <p className="label">O que já foi investigado</p>
          <ul className="handoff-band__list">
            {done.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </div>

        <div>
          <p className="label">O que falta</p>
          <ul className="handoff-band__list handoff-band__list--open">
            {missing.length > 0 ? (
              missing.map((text) => <li key={text}>{text}</li>)
            ) : (
              <li>Validação humana das evidências já coletadas.</li>
            )}
          </ul>
        </div>

        <div>
          <p className="label">Próximo passo</p>
          <p className="handoff-band__next">
            {decision ? recommendedActionLabel[decision.recommended_action] : 'Revisão da engenharia'}
          </p>
          <p className="handoff-band__detail">
            {handoff?.suggested_next_step ?? decision?.headline}
          </p>
          <button type="button" className="button button--primary" onClick={openReview}>
            Abrir encaminhamento
          </button>
        </div>
      </div>
    </section>
  );
}
