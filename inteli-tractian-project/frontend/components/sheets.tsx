/**
 * Painéis laterais: detalhes técnicos e revisão técnica.
 *
 * Tudo que é identificador interno — `call_id`, código HTTP, argumentos,
 * carimbo de tempo bruto — vive aqui, e só aqui. A tela principal não é lugar
 * de metadado de auditoria.
 */

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import type { EvidenceRecord, Investigation, TraceEvent } from '@/lib/investigation-types';
import { evidenceForEvent, plural } from '@/lib/case-facts';
import { EvidenceMark, StateMark } from './indicators';
import { DecisionFindings } from './evaluation';
import type { Evaluation } from '@/lib/eval-types';
import {
  finalVerdictDescription,
  formatDuration,
  handoffReason,
  recommendedActionLabel,
  toolName,
  traceEvent,
} from '@/lib/labels';

// --------------------------------------------------------------------------
// Detalhes técnicos de evidência e de evento
// --------------------------------------------------------------------------

export function InspectionSheet({
  investigation,
  evidence,
  event,
  close,
  onOpenEvidence,
}: {
  investigation?: Investigation;
  evidence?: EvidenceRecord;
  event?: TraceEvent;
  close: () => void;
  onOpenEvidence: (record: EvidenceRecord) => void;
}) {
  /** §14: a chamada e a evidência que ela produziu pertencem ao mesmo painel. */
  const produced =
    investigation && event ? evidenceForEvent(investigation, event) : undefined;

  return (
    <Sheet open={Boolean(evidence || event)} onOpenChange={(open) => !open && close()}>
      <SheetContent className="side-sheet">
        <SheetHeader>
          <p className="label">{evidence ? 'Evidência' : 'Etapa da trajetória'}</p>
          <SheetTitle>
            {evidence ? toolName(evidence.tool_name) : traceEvent(event?.event_type ?? '')}
          </SheetTitle>
          <SheetDescription>
            {evidence
              ? 'Registro consultado durante a investigação, com a origem preservada.'
              : 'Evento operacional persistido. Nenhum raciocínio interno é exposto.'}
          </SheetDescription>
        </SheetHeader>

        {evidence && (
          <div className="side-sheet__body">
            <EvidenceMark status={evidence.evidence_status} />
            <section>
              <h3>Resumo</h3>
              <p>{evidence.summary}</p>
              {evidence.notes && <p className="side-sheet__note">{evidence.notes}</p>}
            </section>
            <section>
              <h3>Origem</h3>
              <dl className="side-sheet__dl">
                <div>
                  <dt>Consulta</dt>
                  <dd>{toolName(evidence.tool_name)}</dd>
                </div>
                <div>
                  <dt>Fonte</dt>
                  <dd>{evidence.source}</dd>
                </div>
                <div>
                  <dt>Coletada em</dt>
                  <dd>{new Date(evidence.collected_at).toLocaleString('pt-BR')}</dd>
                </div>
              </dl>
            </section>
            <section>
              <h3>Detalhes técnicos</h3>
              <dl className="side-sheet__dl side-sheet__dl--tech">
                <div>
                  <dt>Identificador</dt>
                  <dd className="mono">{evidence.evidence_id}</dd>
                </div>
                <div>
                  <dt>Chamada</dt>
                  <dd className="mono">{evidence.source_call_id}</dd>
                </div>
                <div>
                  <dt>Etapa na trajetória</dt>
                  <dd>#{evidence.source_trace_sequence}</dd>
                </div>
                <div>
                  <dt>Transporte HTTP</dt>
                  <dd>
                    {evidence.status_code} · {evidence.transport_ok ? 'sucesso' : 'falha'}
                  </dd>
                </div>
                <div>
                  <dt>Endpoint</dt>
                  <dd className="mono">
                    {evidence.method} {evidence.path}
                  </dd>
                </div>
              </dl>
              <p className="side-sheet__note">
                Transporte e semântica são medidos separadamente: uma resposta pode chegar com
                sucesso e ainda assim ser inconclusiva.
              </p>
              <pre>{JSON.stringify(evidence.arguments, null, 2)}</pre>
            </section>
          </div>
        )}

        {event && (
          <div className="side-sheet__body">
            <section>
              <h3>O que aconteceu</h3>
              <p>{event.summary}</p>
            </section>

            {event.tool_name && (
              <section>
                <h3>Chamada</h3>
                <dl className="side-sheet__dl">
                  <div>
                    <dt>Ferramenta</dt>
                    <dd>
                      {toolName(event.tool_name)}
                      <span className="side-sheet__code"> {event.tool_name}</span>
                    </dd>
                  </div>
                  {produced && (
                    <div>
                      <dt>Argumentos</dt>
                      <dd>
                        {Object.entries(produced.arguments).map(([key, value]) => (
                          <span className="side-sheet__arg" key={key}>
                            {key}: <b>{value}</b>
                          </span>
                        ))}
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt>Duração</dt>
                    <dd>{event.duration_ms ? formatDuration(event.duration_ms) : '—'}</dd>
                  </div>
                  {produced && (
                    <div>
                      <dt>Resultado</dt>
                      <dd>
                        <EvidenceMark status={produced.evidence_status} />
                      </dd>
                    </div>
                  )}
                </dl>
                {produced && (
                  <p className="side-sheet__produced">
                    Evidência criada:{' '}
                    <button
                      type="button"
                      className="link-button mono"
                      onClick={() => onOpenEvidence(produced)}
                    >
                      {produced.evidence_id}
                    </button>
                  </p>
                )}
              </section>
            )}

            <section>
              <h3>Retorno técnico</h3>
              <dl className="side-sheet__dl side-sheet__dl--tech">
                <div>
                  <dt>Etapa</dt>
                  <dd>#{event.sequence}</dd>
                </div>
                <div>
                  <dt>Chamada</dt>
                  <dd className="mono">{event.call_id}</dd>
                </div>
                <div>
                  <dt>Horário</dt>
                  <dd>{new Date(event.timestamp).toLocaleString('pt-BR')}</dd>
                </div>
                <div>
                  <dt>Duração</dt>
                  <dd>{event.duration_ms ? formatDuration(event.duration_ms) : 'não se aplica'}</dd>
                </div>
              </dl>
              {event.details && <pre>{JSON.stringify(event.details, null, 2)}</pre>}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

// --------------------------------------------------------------------------
// Revisão técnica
// --------------------------------------------------------------------------

export function ReviewSheet({
  item,
  evaluation,
  close,
  openCase,
}: {
  item?: Investigation;
  evaluation?: Evaluation;
  close: () => void;
  openCase: (item: Investigation) => void;
}) {
  const handoff = item?.human_handoff;
  const blocked = evaluation?.decision.final_verdict === 'REJECTED';

  return (
    <Sheet open={Boolean(item)} onOpenChange={(open) => !open && close()}>
      <SheetContent className="side-sheet">
        <SheetHeader>
          <p className="label">Encaminhamento</p>
          <SheetTitle>{blocked ? 'Resultado bloqueado' : 'Revisão técnica necessária'}</SheetTitle>
          <SheetDescription>
            {blocked
              ? finalVerdictDescription.REJECTED
              : finalVerdictDescription.HUMAN_REVIEW_REQUIRED}
          </SheetDescription>
        </SheetHeader>

        {item && (
          <div className="side-sheet__body">
            <p className="side-sheet__case">
              <span className="mono">{item.case_id}</span> · {item.asset_name} · {item.company}
            </p>
            <StateMark state={item.terminal_state} />

            {evaluation && <DecisionFindings decision={evaluation.decision} />}

            <section>
              <h3>O que a investigação já fez</h3>
              <ul className="side-sheet__list">
                {item.plan_objectives.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </section>

            <section>
              <h3>O que foi encontrado</h3>
              <p className="side-sheet__counts">
                <span>
                  {plural(
                    item.evidence.filter((e) => e.evidence_status === 'complete').length,
                    'evidência completa',
                    'evidências completas',
                  )}
                </span>
                <span>
                  {plural(
                    item.evidence.filter((e) =>
                      ['partial', 'inconclusive', 'conflict', 'unavailable'].includes(
                        e.evidence_status,
                      ),
                    ).length,
                    'degradada',
                    'degradadas',
                  )}
                </span>
              </p>
              <ul className="side-sheet__list">
                {item.evidence.slice(0, 3).map((record) => (
                  <li key={record.evidence_id}>{record.summary}</li>
                ))}
              </ul>
            </section>

            {(item.unresolved_points.length > 0 || handoff) && (
              <section>
                <h3>O que permanece incerto</h3>
                <ul className="side-sheet__list">
                  {item.unresolved_points.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                  {handoff?.missing_information.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
                {handoff && (
                  <p className="side-sheet__codes">
                    {handoff.reason_codes.map((code) => (
                      <span key={code}>{handoffReason(code)}</span>
                    ))}
                  </p>
                )}
              </section>
            )}

            {evaluation && (
              <section>
                <h3>Próximo passo recomendado</h3>
                <p>
                  <strong>{recommendedActionLabel[evaluation.decision.recommended_action]}.</strong>{' '}
                  {handoff?.suggested_next_step ?? evaluation.decision.headline}
                </p>
              </section>
            )}
            {!evaluation && handoff?.suggested_next_step && (
              <section>
                <h3>Próximo passo recomendado</h3>
                <p>{handoff.suggested_next_step}</p>
              </section>
            )}

            <footer className="side-sheet__footer">
              <button
                type="button"
                className="button button--primary"
                onClick={() => {
                  close();
                  openCase(item);
                }}
              >
                Abrir investigação completa
              </button>
              <button
                type="button"
                className="button"
                disabled
                title="Não existe workflow de atribuição no backend"
              >
                Assumir revisão · indisponível
              </button>
            </footer>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
