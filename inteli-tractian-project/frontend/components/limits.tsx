/**
 * Limitações e segurança do caso.
 *
 * Duas informações que a arquitetura promete e que a interface precisava tornar
 * verificáveis: o que esta investigação **não** conseguiu responder, e o fato de
 * que nenhuma escrita foi executada. Ambas derivam do registro — a postura
 * somente-leitura é conferida pelo método de cada consulta, não afirmada.
 */

import type { Evaluation } from '@/lib/eval-types';
import type { Investigation } from '@/lib/investigation-types';
import { limitations, plural, securityPosture } from '@/lib/case-facts';
import { hardFailureLabel } from '@/lib/labels';

export function LimitsAndSafety({
  item,
  evaluation,
}: {
  item: Investigation;
  evaluation?: Evaluation;
}) {
  const limits = limitations(item);
  const safety = securityPosture(item, evaluation);

  return (
    <div className="limits-block">
      <section>
        <p className="label">Limitações desta investigação</p>
        {limits.length > 0 ? (
          <ul className="limits">
            {limits.map((limit) => (
              <li key={`${limit.origin}-${limit.text}`}>
                <p>{limit.text}</p>
                <p className="limits__origin">{limit.origin}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="limits__none">
            Nenhuma limitação foi registrada. Todas as consultas necessárias retornaram dados
            completos e nenhuma afirmação precisou de ressalva.
          </p>
        )}
      </section>

      <section className="safety">
        <p className="label">Segurança</p>
        <ul className="safety__list">
          <li className={safety.readOnly ? 'safety__ok' : 'safety__bad'}>
            <b>
              {safety.readOnly
                ? 'Nenhuma ação de escrita foi executada'
                : `${plural(safety.writeCount, 'consulta de escrita', 'consultas de escrita')} executadas`}
            </b>
            <span>
              {plural(safety.readCount, 'consulta de leitura verificada', 'consultas de leitura verificadas')}{' '}
              pelo método HTTP registrado.
            </span>
          </li>

          {safety.hardFailures.length === 0 ? (
            <li className="safety__ok">
              <b>Nenhuma condição crítica violada</b>
              <span>A avaliação não encontrou invenção de dado, vazamento nem afirmação sem lastro.</span>
            </li>
          ) : (
            safety.hardFailures.map((code) => (
              <li className="safety__bad" key={code}>
                <b>{hardFailureLabel[code as keyof typeof hardFailureLabel]}</b>
                <span>Condição crítica: reprova o resultado sozinha.</span>
              </li>
            ))
          )}

          {safety.blocked && (
            <li className="safety__bad">
              <b>Resultado bloqueado</b>
              <span>Este resultado não deve ser usado como resposta final ao solicitante.</span>
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
