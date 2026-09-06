/**
 * Rastreabilidade da conclusão.
 *
 * Responde a pergunta que decide confiança: *de onde saiu essa afirmação?* — em
 * português, e sem exigir que o leitor conheça a arquitetura. A cadeia
 * `claim → evidence → call → trace` continua íntegra por baixo; o que aparece é
 * a leitura dela: afirmação, sustentada por, obtida por, origem.
 */

import type { Claim, EvidenceRecord, TraceEvent } from '@/lib/investigation-types';
import { toolName } from '@/lib/labels';

interface Props {
  claims: Claim[];
  evidence: EvidenceRecord[];
  trace: TraceEvent[];
  onInspectEvidence: (record: EvidenceRecord) => void;
}

const claimStatusLabel: Record<Claim['status'], string> = {
  supported: 'Sustentada',
  qualified: 'Sustentada com ressalva',
  contradicted: 'Contradita',
  unresolved: 'Não resolvida',
};

export function Provenance({ claims, evidence, trace, onInspectEvidence }: Props) {
  if (claims.length === 0) return null;

  return (
    <div className="provenance">
      {claims.map((claim) => {
        const supporting = claim.supporting_evidence_ids
          .map((id) => evidence.find((record) => record.evidence_id === id))
          .filter((record): record is EvidenceRecord => Boolean(record));

        return (
          <article className="claim" key={claim.claim_id}>
            <header className="claim__head">
              <span className={`claim__status claim__status--${claim.status}`}>
                {claimStatusLabel[claim.status]}
              </span>
              <span className="mono claim__id">{claim.claim_id}</span>
            </header>

            <p className="claim__statement">{claim.statement}</p>

            {supporting.map((record) => {
              const event = trace.find(
                (item) =>
                  item.call_id === record.source_call_id && item.event_type === 'tool_completed',
              );
              return (
                <dl className="chain" key={record.evidence_id}>
                  <div>
                    <dt>Sustentada por</dt>
                    <dd>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => onInspectEvidence(record)}
                      >
                        Evidência {record.evidence_id}
                      </button>
                    </dd>
                  </div>
                  <div>
                    <dt>Obtida por</dt>
                    <dd>
                      {toolName(record.tool_name)}
                      {event && <span className="chain__aside">etapa {event.sequence}</span>}
                    </dd>
                  </div>
                  <div>
                    <dt>Origem</dt>
                    <dd>{record.source}</dd>
                  </div>
                </dl>
              );
            })}

            {claim.limitation && (
              <p className="claim__limitation">
                <span>Limitação</span>
                {claim.limitation}
              </p>
            )}
          </article>
        );
      })}
    </div>
  );
}
