/**
 * Trajetória da investigação — a leitura humana do Trace.
 *
 * O horário fica na coluna da esquerda, como numa folha de ocorrências: o olho
 * desce pela linha do tempo antes de ler o conteúdo. Só eventos persistidos
 * aparecem; nenhum raciocínio interno é exposto.
 *
 * Quando uma etapa produziu evidência, a etapa e a linha correspondente da
 * tabela ao lado se destacam juntas — é assim que "o que aconteceu" e "o que
 * sustentou a conclusão" se conectam sem precisar de setas desenhadas.
 */

import type { EvidenceRecord, Investigation, TraceEvent } from '@/lib/investigation-types';
import { evidenceForEvent } from '@/lib/case-facts';
import { formatDuration, formatTimeSeconds, toolName, traceEvent } from '@/lib/labels';

interface Props {
  item: Investigation;
  onInspect: (event: TraceEvent) => void;
  linked: string | null;
  onLink: (evidenceId: string | null) => void;
  onOpenEvidence: (record: EvidenceRecord) => void;
}

export function Trajectory({ item, onInspect, linked, onLink, onOpenEvidence }: Props) {
  return (
    <ol className="steps">
      {item.trace.map((event) => {
        const evidence =
          event.event_type === 'tool_completed' ? evidenceForEvent(item, event) : undefined;
        const terminal = event.event_type === 'terminal_state_reached';
        const failed = event.event_type.endsWith('_failed');
        const isLinked = Boolean(evidence && linked === evidence.evidence_id);
        return (
          <li
            key={`${event.call_id}-${event.sequence}`}
            className={[
              'step',
              terminal ? 'step--terminal' : '',
              failed ? 'step--failed' : '',
              isLinked ? 'step--linked' : '',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <time className="step__time" dateTime={event.timestamp}>
              {formatTimeSeconds(event.timestamp)}
            </time>
            <span className="step__rail" aria-hidden="true">
              <i className="step__dot" />
            </span>
            <div className="step__body">
              <p className="step__head">
                <strong>{event.tool_name ? toolName(event.tool_name) : traceEvent(event.event_type)}</strong>
                {event.tool_name && <span className="step__kind">{traceEvent(event.event_type)}</span>}
                {typeof event.duration_ms === 'number' && (
                  <span className="step__duration">{formatDuration(event.duration_ms)}</span>
                )}
              </p>
              <p className="step__text">{event.summary}</p>
              <p className="step__links">
                {evidence && (
                  <button
                    type="button"
                    className="evidence-chip"
                    onClick={() => onOpenEvidence(evidence)}
                    onMouseEnter={() => onLink(evidence.evidence_id)}
                    onMouseLeave={() => onLink(null)}
                    onFocus={() => onLink(evidence.evidence_id)}
                    onBlur={() => onLink(null)}
                    title={`Destacar e abrir a evidência ${evidence.evidence_id}`}
                  >
                    Evidência {evidence.evidence_id}
                  </button>
                )}
                {(event.tool_name || event.details) && (
                  <button type="button" className="link-button" onClick={() => onInspect(event)}>
                    {event.tool_name ? 'Inspecionar chamada' : 'Detalhes técnicos'}
                  </button>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
