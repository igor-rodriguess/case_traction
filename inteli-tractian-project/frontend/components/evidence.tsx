/**
 * Evidências — as informações que sustentam a conclusão.
 *
 * A tabela mostra o que decide confiança: identificador, origem, estado, resumo
 * e quais afirmações dependem daquele registro. Código HTTP, `call_id` e
 * argumentos ficam no painel de detalhes, não na tabela.
 *
 * Fica ao lado da trajetória, e as duas se destacam em conjunto quando o
 * ponteiro passa sobre a etapa que originou o registro.
 */

import type { Claim, EvidenceRecord } from '@/lib/investigation-types';
import { EvidenceMark } from './indicators';
import { formatDuration, toolName } from '@/lib/labels';

interface Props {
  records: EvidenceRecord[];
  claims: Claim[];
  durations: Record<string, number | undefined>;
  onInspect: (record: EvidenceRecord) => void;
  linked: string | null;
  onLink: (evidenceId: string | null) => void;
}

/**
 * §18: uma seção sem dados precisa dizer o que aconteceu, qual o estado e qual
 * o impacto — não pode ser um retângulo em branco.
 */
export function NoEvidence() {
  return (
    <div className="notice">
      <p className="notice__title">Nenhuma evidência foi coletada</p>
      <p>
        Nenhuma consulta foi executada porque falta a informação que identifica o ativo. O sistema
        não adivinhou um identificador para conseguir seguir.
      </p>
      <dl className="notice__facts">
        <div>
          <dt>Estado</dt>
          <dd>Sem coleta</dd>
        </div>
        <div>
          <dt>Impacto</dt>
          <dd>A investigação não pôde fundamentar nenhuma afirmação.</dd>
        </div>
      </dl>
    </div>
  );
}

export function EvidenceList({
  records,
  claims,
  durations,
  onInspect,
  linked,
  onLink,
}: Props) {
  if (records.length === 0) return <NoEvidence />;

  return (
    <div className="table-wrap">
      <table className="grid-table grid-table--evidence">
        <thead>
          <tr>
            <th scope="col">Evidência</th>
            <th scope="col">Origem</th>
            <th scope="col">Estado</th>
            <th scope="col">Resumo</th>
            <th scope="col">Sustenta</th>
            <th scope="col" className="num">
              Tempo
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const supported = claims.filter((claim) =>
              claim.supporting_evidence_ids.includes(record.evidence_id),
            );
            const duration = durations[record.source_call_id];
            return (
              <tr
                key={record.evidence_id}
                onClick={() => onInspect(record)}
                onMouseEnter={() => onLink(record.evidence_id)}
                onMouseLeave={() => onLink(null)}
                tabIndex={0}
                onFocus={() => onLink(record.evidence_id)}
                onBlur={() => onLink(null)}
                onKeyDown={(event) => event.key === 'Enter' && onInspect(record)}
                className={`grid-table__row--clickable ${
                  linked === record.evidence_id ? 'grid-table__row--linked' : ''
                }`}
              >
                <th scope="row">
                  <span className="mono">{record.evidence_id}</span>
                  <span className="cell-weak">etapa {record.source_trace_sequence}</span>
                </th>
                <td>
                  <span className="cell-strong">{toolName(record.tool_name)}</span>
                  <span className="cell-weak">{record.source}</span>
                </td>
                <td>
                  <EvidenceMark status={record.evidence_status} />
                </td>
                <td className="cell-prose">{record.summary}</td>
                <td>
                  {supported.length > 0 ? (
                    <span className="mono cell-weak">
                      {supported.map((claim) => claim.claim_id).join(', ')}
                    </span>
                  ) : (
                    <span className="cell-weak">—</span>
                  )}
                </td>
                <td className="num">{duration ? formatDuration(duration) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
