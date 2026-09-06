'use client';

/**
 * Console de investigação — bancada de trabalho, não painel.
 *
 * A tela de detalhe é o produto: um dossiê que se lê de cima para baixo. A
 * composição segue uma grade de 12 colunas — 8+4 no topo (o caso à esquerda, o
 * resultado fixo à direita), 5+7 no meio (trajetória ao lado das evidências), e
 * largura total onde o texto manda.
 *
 * Toda a superfície visível está em português; os contratos do backend não são
 * traduzidos, apenas apresentados através de `lib/labels.ts`.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError, api } from '@/lib/api';
import type { InvestigationSummary } from '@/lib/api-adapters';
import { ConsoleProvider, reviewQueueOf, useConsole, useDossier } from '@/lib/use-console';
import type { AppView, EvidenceRecord, Investigation, TraceEvent } from '@/lib/investigation-types';
import type { Evaluation, FinalVerdict } from '@/lib/eval-types';
import {
  agreementLabel,
  evidenceQualityLabel,
  evidenceQualityTone,
  finalVerdictLabel,
  finalVerdictTone,
  formatScore,
  recommendedActionLabel,
  requestClassLabel,
  terminalStateHint,
  terminalStateLabel,
  toolName,
  viewLabel,
} from '@/lib/labels';
import { capabilityUse, plural, toolCalls } from '@/lib/case-facts';
import { QualityMark, StateMark, VerdictMark } from '@/components/indicators';
import { Trajectory } from '@/components/trajectory';
import { EvidenceList } from '@/components/evidence';
import { Provenance } from '@/components/provenance';
import { TechnicalReport } from '@/components/report';
import { LimitsAndSafety } from '@/components/limits';
import { HandoffBand } from '@/components/handoff-band';
import { InspectionSheet, ReviewSheet } from '@/components/sheets';
import {
  BaremaTable,
  CriteriaSummary,
  DecisionBanner,
  DecisionFindings,
  EvaluationNotReached,
  JudgeAnalysisSection,
  JudgeCards,
} from '@/components/evaluation';

const sections = [
  ['solicitacao', 'Solicitação'],
  ['trajetoria', 'Trajetória e evidências'],
  ['conclusao', 'Conclusão'],
  ['relatorio', 'Relatório'],
  ['avaliacao', 'Avaliação'],
] as const;

const nav: AppView[] = ['overview', 'investigations', 'human-review', 'evaluations', 'system-health'];

const verdictOrder: FinalVerdict[] = [
  'APPROVED',
  'APPROVED_WITH_WARNINGS',
  'HUMAN_REVIEW_REQUIRED',
  'REJECTED',
];

// --------------------------------------------------------------------------
// Estrutura
// --------------------------------------------------------------------------

function Shell({
  view,
  setView,
  queueCount,
  children,
}: {
  view: AppView;
  setView: (view: AppView) => void;
  queueCount: number;
  children: React.ReactNode;
}) {
  const active = view === 'investigation-detail' ? 'investigations' : view;
  const queue = queueCount;

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead__inner">
          <p className="wordmark">
            <span>TRACTIAN</span>
            <span className="wordmark__product">Investigação com AI</span>
          </p>
          <nav className="tabs" aria-label="Navegação principal">
            {nav.map((id) => (
              <button
                key={id}
                type="button"
                className={active === id ? 'tabs__item tabs__item--active' : 'tabs__item'}
                aria-current={active === id ? 'page' : undefined}
                onClick={() => setView(id)}
              >
                {viewLabel[id]}
                {id === 'human-review' && queue > 0 && <b className="tabs__count">{queue}</b>}
              </button>
            ))}
          </nav>
          <p className="masthead__env">Ambiente piloto · dados reais</p>
        </div>
      </header>
      <main className="workspace">{children}</main>
    </div>
  );
}

function PageHead({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="page-head">
      <p className="label">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="page-head__desc">{description}</p>
    </header>
  );
}

/** Seção numerada. O número dá ordem de leitura sem gastar hierarquia extra. */
function Section({
  id,
  n,
  title,
  hint,
  children,
}: {
  id?: string;
  n: string;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="section" id={id}>
      <header className="section-head">
        <span className="section-head__n" aria-hidden="true">
          {n}
        </span>
        <h2>{title}</h2>
        {hint && <p>{hint}</p>}
      </header>
      {children}
    </section>
  );
}

function Dossier({
  item,
  evaluation,
  running,
  back,
  onEvidence,
  onTrace,
  openReview,
}: {
  item: Investigation;
  evaluation?: Evaluation;
  running: boolean;
  back: () => void;
  onEvidence: (record: EvidenceRecord) => void;
  onTrace: (event: TraceEvent) => void;
  openReview: () => void;
}) {
  const [baremaOpen, setBaremaOpen] = useState(false);
  const [linked, setLinked] = useState<string | null>(null);

  const calls = toolCalls(item);
  const durations = Object.fromEntries(
    calls.map((event) => [event.call_id, event.duration_ms]),
  ) as Record<string, number | undefined>;
  const capabilities = capabilityUse(item);
  const review = Boolean(item.human_handoff || evaluation?.decision.human_review_required);

  return (
    <article className="page page--dossier">
      <button type="button" className="link-button back" onClick={back}>
        Todas as investigações
      </button>

      <div className="split split--8-4 dossier-top">
        <div>
          <header className="case">
            <p className="case__meta">
              <span className="mono">{item.case_id}</span>
              <span>{item.started_at}</span>
              {running && <span className="tag tag--live">em execução</span>}
            </p>
            <h1>{item.asset_name}</h1>
            <p className="case__sub">
              {item.company} · <span className="mono">{item.asset_id}</span>
            </p>
          </header>

          <Section
            id="solicitacao"
            n="01"
            title="Solicitação original"
            hint="Texto recebido do cliente, sem reescrita."
          >
            <blockquote className="quote">{item.request}</blockquote>
            <dl className="facts">
              <div>
                <dt>Interpretação</dt>
                <dd>{requestClassLabel[item.request_class]}</dd>
              </div>
              <div>
                <dt>Entidades identificadas</dt>
                <dd>{item.entities.join(' · ') || '—'}</dd>
              </div>
              <div>
                <dt>O que foi investigado</dt>
                <dd>{item.investigation_targets.join(' · ') || '—'}</dd>
              </div>
              {item.missing_information.length > 0 && (
                <div>
                  <dt>Informação faltante</dt>
                  <dd className="facts__warn">{item.missing_information.join(' · ')}</dd>
                </div>
              )}
            </dl>
          </Section>

          <Section
            n="02"
            title="Plano de investigação"
            hint="Objetivos definidos antes de qualquer consulta, e as capacidades de leitura autorizadas."
          >
            {item.plan_objectives.length > 0 ? (
              <ol className="objectives">
                {item.plan_objectives.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ol>
            ) : (
              <p className="pending">
                {running ? 'Em preparação…' : 'Nenhum plano foi produzido.'}
              </p>
            )}
            <div className="caps">
              <p className="label">Capacidades autorizadas</p>
              <ul>
                {capabilities.length > 0 ? (
                  capabilities.map((capability) => (
                    <li
                      key={capability.name}
                      className={capability.used ? 'caps--used' : 'caps--idle'}
                    >
                      <span className="caps__mark" aria-hidden="true" />
                      <b>{toolName(capability.name)}</b>
                      <span>{capability.used ? 'executada' : 'não foi necessária'}</span>
                    </li>
                  ))
                ) : (
                  <li className="caps--idle">
                    <span className="caps__mark" aria-hidden="true" />
                    <b>Nenhuma consulta autorizada</b>
                    <span>falta identificar o ativo</span>
                  </li>
                )}
              </ul>
            </div>
          </Section>
        </div>

        {/* Área nobre: o que decide o que o engenheiro faz agora. */}
        <aside className="result-panel">
          <div className="result-panel__block">
            <p className="label">Estado da investigação</p>
            <StateMark state={item.terminal_state} />
            <p className="result-panel__hint">{terminalStateHint[item.terminal_state]}</p>
          </div>

          <div className="result-panel__block">
            <p className="label">Avaliação</p>
            {evaluation ? (
              <>
                <VerdictMark verdict={evaluation.decision.final_verdict} />
                <p className="result-panel__score">
                  {formatScore(evaluation.decision.overall_score)}
                  <span> / 4,0</span>
                </p>
                <dl className="result-panel__dl">
                  <div>
                    <dt>Concordância</dt>
                    <dd>{agreementLabel[evaluation.decision.agreement_level]}</dd>
                  </div>
                  <div>
                    <dt>Ação recomendada</dt>
                    <dd
                      className={`result-panel__action result-panel__action--${
                        finalVerdictTone[evaluation.decision.final_verdict]
                      }`}
                    >
                      {recommendedActionLabel[evaluation.decision.recommended_action]}
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <>
                <span className="muted">Não avaliada</span>
                <p className="result-panel__hint">
                  A investigação não chegou à etapa de avaliação.
                </p>
              </>
            )}
          </div>

          <div className="result-panel__block">
            <p className="label">Qualidade das evidências</p>
            <p
              className={`result-panel__quality result-panel__quality--${
                evidenceQualityTone[item.evidence_quality]
              }`}
            >
              {evidenceQualityLabel[item.evidence_quality]}
            </p>
            <ul className="result-panel__reasons">
              {item.evidence_quality_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>

          <div className="result-panel__block">
            <p className="label">Execução</p>
            <dl className="result-panel__dl">
              <div>
                <dt>Tempo total</dt>
                <dd>{item.duration}</dd>
              </div>
              <div>
                <dt>Consultas executadas</dt>
                <dd>{calls.length}</dd>
              </div>
              <div>
                <dt>Afirmações fundamentadas</dt>
                <dd>{item.claims.length}</dd>
              </div>
            </dl>
          </div>

          {review && (
            <button type="button" className="button button--primary" onClick={openReview}>
              Abrir revisão técnica
            </button>
          )}
        </aside>
      </div>

      <nav className="rail" aria-label="Seções do dossiê">
        {sections.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </nav>

      {/* §13: o que aconteceu, ao lado do que sustentou a conclusão. */}
      <Section
        id="trajetoria"
        n="03"
        title="Trajetória e evidências"
        hint="À esquerda, as etapas executadas. À direita, o que cada consulta produziu. Passar o ponteiro sobre uma etapa destaca a evidência correspondente."
      >
        <div className="split split--5-7 pair">
          <div className="pair__left">
            <p className="label">Etapas executadas</p>
            <Trajectory
              item={item}
              onInspect={onTrace}
              linked={linked}
              onLink={setLinked}
              onOpenEvidence={onEvidence}
            />
          </div>
          <div className="pair__right">
            <p className="label">Evidências coletadas</p>
            <EvidenceList
              records={item.evidence}
              claims={item.claims}
              durations={durations}
              onInspect={onEvidence}
              linked={linked}
              onLink={setLinked}
            />
          </div>
        </div>
      </Section>

      <Section
        id="conclusao"
        n="04"
        title="Conclusão"
        hint="Cada afirmação e o caminho até a informação que a sustenta."
      >
        <div className="split split--7-5">
          <div>
            {item.claims.length > 0 ? (
              <Provenance
                claims={item.claims}
                evidence={item.evidence}
                trace={item.trace}
                onInspectEvidence={onEvidence}
              />
            ) : (
              <div className="notice">
                <p className="notice__title">Nenhuma conclusão foi produzida</p>
                <p>
                  {item.terminal_state === 'SAFE_ESCALATION'
                    ? 'A investigação parou porque a evidência disponível não sustenta uma conclusão. As evidências coletadas foram preservadas para a continuação humana.'
                    : 'Falta informação obrigatória. Nenhuma afirmação foi inventada para preencher a lacuna.'}
                </p>
                <dl className="notice__facts">
                  <div>
                    <dt>Estado</dt>
                    <dd>{terminalStateLabel[item.terminal_state]}</dd>
                  </div>
                  <div>
                    <dt>Impacto</dt>
                    <dd>
                      A resposta ao solicitante depende de uma decisão humana ou de informação
                      adicional.
                    </dd>
                  </div>
                </dl>
              </div>
            )}

            {item.unresolved_points.length > 0 && (
              <div className="open-points">
                <p className="label">Pontos ainda não resolvidos</p>
                <ul className="open-list">
                  {item.unresolved_points.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <LimitsAndSafety item={item} evaluation={evaluation} />
        </div>
      </Section>

      {review && (
        <Section
          n="05"
          title="Revisão técnica"
          hint="O que a engenharia precisa decidir neste caso."
        >
          <HandoffBand item={item} evaluation={evaluation} openReview={openReview} />
        </Section>
      )}

      <Section
        id="relatorio"
        n={review ? '06' : '05'}
        title="Relatório técnico"
        hint="Documento preparado para a equipe de engenharia."
      >
        <TechnicalReport item={item} onInspectEvidence={onEvidence} />
      </Section>

      <Section
        id="avaliacao"
        n={review ? '07' : '06'}
        title="Avaliação"
        hint="Estado da investigação e resultado da avaliação são julgamentos separados."
      >
        {evaluation ? (
          <div className="evaluation">
            <DecisionBanner decision={evaluation.decision} />

            <div className="split split--7-5">
              <div className="evaluation__criteria">
                <p className="section-title">Critérios principais</p>
                <CriteriaSummary
                  decision={evaluation.decision}
                  onOpenBarema={() => setBaremaOpen((open) => !open)}
                />
              </div>
              <div className="evaluation__findings">
                <DecisionFindings decision={evaluation.decision} />
              </div>
            </div>

            {baremaOpen && (
              <div className="evaluation__barema">
                <p className="section-title">
                  Todos os critérios · {evaluation.decision.barema_version}
                </p>
                <BaremaTable evaluation={evaluation} />
              </div>
            )}

            <div className="evaluation__analysis">
              <p className="section-title">Análise dos avaliadores</p>
              <JudgeAnalysisSection evaluation={evaluation} />
            </div>

            <div className="evaluation__judges">
              <p className="section-title">Notas por avaliador</p>
              <JudgeCards evaluation={evaluation} />
            </div>
          </div>
        ) : (
          <EvaluationNotReached terminalStateText={terminalStateLabel[item.terminal_state]} />
        )}
      </Section>
    </article>
  );
}


// --------------------------------------------------------------------------
// Estados de carga e de falha
// --------------------------------------------------------------------------

/**
 * §40: quando a API cai, a interface diz que caiu. Não existe queda para mock —
 * dado falso esconderia a falha real justamente no momento em que ela importa.
 */
function ServiceDown({ error, retry }: { error: ApiError; retry: () => void }) {
  return (
    <div className="page">
      <div className="notice notice--danger">
        <p className="notice__title">Não foi possível conectar ao serviço de investigação.</p>
        <p>{error.message}</p>
        <dl className="notice__facts">
          <div>
            <dt>Código</dt>
            <dd className="mono">{error.code}</dd>
          </div>
          {error.detail && (
            <div>
              <dt>Detalhe</dt>
              <dd>{error.detail}</dd>
            </div>
          )}
        </dl>
        <button type="button" className="button button--primary" onClick={retry}>
          Tentar novamente
        </button>
      </div>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="page">
      <p className="pending">{label}</p>
    </div>
  );
}

// --------------------------------------------------------------------------
// Nova investigação
// --------------------------------------------------------------------------

function NewInvestigationForm({
  close,
  onCreated,
}: {
  close: () => void;
  onCreated: (caseId: string) => void;
}) {
  const [message, setMessage] = useState('');
  const [asset, setAsset] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    setSending(true);
    setError(null);
    try {
      const created = await api.create({
        message,
        tenant_ref: 'company_alpha',
        asset_refs: asset ? [asset] : [],
      });
      onCreated(created.case_id);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : 'Não foi possível iniciar a investigação.');
      setSending(false);
    }
  }

  return (
    <dialog className="modal" open aria-labelledby="new-title">
      <form className="modal__panel" onSubmit={submit}>
        <header>
          <p className="label">Nova investigação</p>
          <h2 id="new-title">Descreva a dúvida técnica</h2>
          <p className="modal__hint">
            O texto vai para o agente exatamente como escrito. Ele decide o que consultar; nenhuma
            ação de escrita é possível.
          </p>
        </header>

        <label className="modal__field">
          <span>Dúvida técnica</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            minLength={8}
            required
            placeholder="Ex.: o RMS do ativo asset_C710 subiu nas últimas leituras e nenhum insight foi emitido."
          />
        </label>

        <label className="modal__field">
          <span>Ativo (opcional)</span>
          <input
            value={asset}
            onChange={(event) => setAsset(event.target.value)}
            placeholder="asset_C710"
          />
        </label>

        {error && <p className="modal__error">{error}</p>}

        <footer>
          <button type="button" className="button" onClick={close} disabled={sending}>
            Cancelar
          </button>
          <button
            type="submit"
            className="button button--primary"
            disabled={sending || message.trim().length < 8}
          >
            {sending ? 'Iniciando…' : 'Iniciar investigação'}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

// --------------------------------------------------------------------------
// Visão geral
// --------------------------------------------------------------------------

function Overview({
  summaries,
  openCase,
  go,
  onNew,
}: {
  summaries: InvestigationSummary[];
  openCase: (caseId: string) => void;
  go: (view: AppView) => void;
  onNew: () => void;
}) {
  const queue = reviewQueueOf(summaries);
  const concluded = summaries.filter((i) => i.terminal_state === 'GROUNDED_COMPLETION').length;
  const waiting = summaries.filter(
    (i) => i.terminal_state === 'AWAITING_REQUIRED_INFORMATION',
  ).length;
  const failed = summaries.filter((i) => i.terminal_state === 'FAILED').length;
  const evaluated = summaries.filter((i) => i.final_verdict);

  return (
    <div className="page">
      <div className="page-head-row">
        <PageHead
          eyebrow="Operação"
          title="Visão geral"
          description="Situação atual das investigações, postura das evidências e exceções que exigem decisão humana."
        />
        <button type="button" className="button button--primary" onClick={onNew}>
          Nova investigação
        </button>
      </div>

      <div className="figures">
        <div className="figure">
          <b>{summaries.length}</b>
          <span>investigações registradas</span>
        </div>
        <div className="figure">
          <b>{concluded}</b>
          <span>com conclusão fundamentada</span>
        </div>
        <div className="figure figure--review">
          <b>{queue.length}</b>
          <span>aguardando revisão técnica</span>
          <button type="button" className="link-button" onClick={() => go('human-review')}>
            Abrir fila
          </button>
        </div>
        <div className="figure">
          <b>{waiting}</b>
          <span>aguardando informações</span>
        </div>
        <div className="figure">
          <b>{failed}</b>
          <span>com falha operacional</span>
        </div>
      </div>

      <div className="split split--7-5">
        <Section
          n="01"
          title="Investigações recentes"
          hint="Selecione um caso para abrir o dossiê completo."
        >
          {summaries.length === 0 ? (
            <p className="pending">
              Nenhuma investigação registrada ainda. Comece por “Nova investigação”.
            </p>
          ) : (
            <ul className="feed">
              {summaries.map((item) => (
                <li key={item.case_id}>
                  <button
                    type="button"
                    className="feed__row"
                    onClick={() => openCase(item.case_id)}
                  >
                    <span className="feed__when">{item.started_at.split('· ')[1] ?? ''}</span>
                    <span className="feed__what">
                      <b>{item.asset_name}</b>
                      <span>{item.request}</span>
                    </span>
                    <span className="feed__state">
                      {item.terminal_state ? (
                        <StateMark state={item.terminal_state} />
                      ) : (
                        <span className="running-mark">
                          <i aria-hidden="true" />
                          Em execução
                        </span>
                      )}
                      {item.final_verdict ? (
                        <VerdictMark verdict={item.final_verdict} />
                      ) : (
                        <span className="muted">Sem avaliação</span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <div className="stack">
          <Section
            n="02"
            title="Aguardando decisão humana"
            hint="Casos parados com evidência preservada."
          >
            {queue.length > 0 ? (
              <ul className="mini-queue">
                {queue.map((item) => (
                  <li key={item.case_id}>
                    <button type="button" onClick={() => openCase(item.case_id)}>
                      <span className="mini-queue__head">
                        <b className="mono">{item.case_id}</b>
                        {item.final_verdict && <VerdictMark verdict={item.final_verdict} />}
                      </span>
                      <span className="mini-queue__asset">{item.asset_name}</span>
                      <span className="mini-queue__reason">
                        {item.recommended_action
                          ? recommendedActionLabel[
                              item.recommended_action as keyof typeof recommendedActionLabel
                            ]
                          : 'Encaminhado para decisão humana'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Nenhum caso aguardando decisão humana.</p>
            )}
          </Section>

          <Section
            n="03"
            title="Distribuição dos resultados"
            hint="Vereditos registrados pela avaliação."
          >
            <ul className="dist">
              {verdictOrder.map((verdict) => {
                const count = evaluated.filter((entry) => entry.final_verdict === verdict).length;
                return (
                  <li key={verdict}>
                    <span
                      className={`dist__dot dist__dot--${finalVerdictTone[verdict]}`}
                      aria-hidden="true"
                    />
                    <span className="dist__name">{finalVerdictLabel[verdict]}</span>
                    <span className="dist__bar" aria-hidden="true">
                      <i
                        className={`dist__fill dist__fill--${finalVerdictTone[verdict]}`}
                        style={{ width: `${(count / Math.max(1, evaluated.length)) * 100}%` }}
                      />
                    </span>
                    <b>{count}</b>
                  </li>
                );
              })}
            </ul>
            <p className="dist__note">
              {plural(
                summaries.reduce((total, row) => total + row.evidence_count, 0),
                'evidência registrada',
                'evidências registradas',
              )}{' '}
              no total das execuções.
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Investigações
// --------------------------------------------------------------------------

function InvestigationsPage({
  summaries,
  openCase,
  onNew,
}: {
  summaries: InvestigationSummary[];
  openCase: (caseId: string) => void;
  onNew: () => void;
}) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState('all');
  const [review, setReview] = useState('all');

  const rows = summaries.filter((item) => {
    const matchesState = state === 'all' || item.terminal_state === state;
    const matchesReview = review === 'all' || (review === 'yes') === item.human_review_required;
    const matchesQuery = `${item.case_id} ${item.asset_name} ${item.company} ${item.request}`
      .toLowerCase()
      .includes(query.toLowerCase());
    return matchesState && matchesReview && matchesQuery;
  });

  return (
    <div className="page">
      <div className="page-head-row">
        <PageHead
          eyebrow="Bancada de investigação"
          title="Investigações"
          description="Estado final, qualidade das evidências e resultado da avaliação, caso a caso."
        />
        <button type="button" className="button button--primary" onClick={onNew}>
          Nova investigação
        </button>
      </div>

      <div className="filters">
        <label className="field field--search">
          <span className="sr-only">Buscar investigações</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar caso, ativo ou solicitação"
          />
        </label>
        <label className="field">
          <span>Estado</span>
          <select value={state} onChange={(event) => setState(event.target.value)}>
            <option value="all">Todos</option>
            <option value="GROUNDED_COMPLETION">Conclusão fundamentada</option>
            <option value="SAFE_ESCALATION">Encaminhado para revisão</option>
            <option value="AWAITING_REQUIRED_INFORMATION">Aguardando informações</option>
            <option value="FAILED">Falhou</option>
          </select>
        </label>
        <label className="field">
          <span>Revisão humana</span>
          <select value={review} onChange={(event) => setReview(event.target.value)}>
            <option value="all">Todas</option>
            <option value="yes">Necessária</option>
            <option value="no">Não necessária</option>
          </select>
        </label>
        <p className="filters__count">{plural(rows.length, 'investigação', 'investigações')}</p>
      </div>

      <div className="table-wrap">
        <table className="grid-table">
          <thead>
            <tr>
              <th scope="col">Caso</th>
              <th scope="col">Ativo</th>
              <th scope="col">Solicitação</th>
              <th scope="col">Estado da investigação</th>
              <th scope="col">Evidências</th>
              <th scope="col">Avaliação</th>
              <th scope="col">Revisão</th>
              <th scope="col" className="num">
                Duração
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr
                key={item.case_id}
                className="grid-table__row--clickable"
                tabIndex={0}
                onClick={() => openCase(item.case_id)}
                onKeyDown={(event) => event.key === 'Enter' && openCase(item.case_id)}
              >
                <th scope="row">
                  <span className="cell-strong mono">{item.case_id}</span>
                  <span className="cell-weak">{item.company}</span>
                </th>
                <td>
                  <span className="cell-strong">{item.asset_name}</span>
                  <span className="cell-weak mono">{item.asset_id}</span>
                </td>
                <td className="cell-prose">{item.request}</td>
                <td>
                  {item.terminal_state ? (
                    <StateMark state={item.terminal_state} />
                  ) : (
                    <span className="running-mark">
                      <i aria-hidden="true" />
                      Em execução
                    </span>
                  )}
                </td>
                <td>
                  <QualityMark quality={item.evidence_quality} />
                  <span className="cell-weak">
                    {plural(item.evidence_count, 'registro', 'registros')}
                  </span>
                </td>
                <td>
                  {item.final_verdict ? (
                    <>
                      <VerdictMark verdict={item.final_verdict} />
                      <span className="cell-weak">
                        {item.overall_score != null ? `${formatScore(item.overall_score)} de 4` : ''}
                      </span>
                    </>
                  ) : (
                    <span className="muted">Não avaliada</span>
                  )}
                </td>
                <td>
                  {item.human_review_required ? (
                    <span className="pill pill--review">Necessária</span>
                  ) : (
                    <span className="cell-muted">—</span>
                  )}
                </td>
                <td className="num">{item.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <div className="notice">
          <p className="notice__title">Nenhuma investigação corresponde à busca</p>
          <p>Ajuste o texto buscado ou os filtros de estado e revisão.</p>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Revisão técnica
// --------------------------------------------------------------------------

function HumanReviewPage({
  summaries,
  openCase,
}: {
  summaries: InvestigationSummary[];
  openCase: (caseId: string) => void;
}) {
  const queue = reviewQueueOf(summaries);

  return (
    <div className="page">
      <PageHead
        eyebrow="Fila da engenharia"
        title="Revisão técnica"
        description="Casos em que parar foi o comportamento correto do sistema e a decisão cabe a um engenheiro."
      />

      <p className="lede">
        <b>{queue.length}</b>{' '}
        {queue.length === 1 ? 'investigação aguarda' : 'investigações aguardam'} revisão. Todas
        preservaram suas evidências e pararam antes de afirmar o que não podiam sustentar.
      </p>

      {queue.length === 0 ? (
        <p className="pending">Nenhum caso aguardando decisão humana.</p>
      ) : (
        <>
          <div className="queue__head">
            <span>Caso</span>
            <span>Situação</span>
            <span>Avaliação</span>
            <span className="sr-only">Ações</span>
          </div>
          <ul className="queue">
            {queue.map((item) => (
              <li className="queue__item" key={item.case_id}>
                <div className="queue__case">
                  <p className="mono cell-strong">{item.case_id}</p>
                  <p className="cell-weak">
                    {item.asset_name} · {item.company}
                  </p>
                  {item.terminal_state && <StateMark state={item.terminal_state} />}
                </div>

                <div className="queue__why">
                  <p className="queue__reason">
                    {item.final_verdict === 'REJECTED'
                      ? 'Resultado bloqueado'
                      : 'Revisão técnica necessária'}
                  </p>
                  <p className="cell-prose">{item.request}</p>
                </div>

                <div className="queue__eval">
                  {item.final_verdict ? (
                    <>
                      <VerdictMark verdict={item.final_verdict} />
                      <p className="cell-weak">
                        {item.overall_score != null ? `${formatScore(item.overall_score)} de 4` : ''}
                        {item.recommended_action
                          ? ` · ${
                              recommendedActionLabel[
                                item.recommended_action as keyof typeof recommendedActionLabel
                              ]
                            }`
                          : ''}
                      </p>
                    </>
                  ) : (
                    <>
                      <span className="muted">Não avaliada</span>
                      <p className="cell-weak">Encaminhada pela investigação</p>
                    </>
                  )}
                  <p className="cell-weak">
                    Qualidade das evidências: <QualityMark quality={item.evidence_quality} />
                  </p>
                </div>

                <div className="queue__actions">
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => openCase(item.case_id)}
                  >
                    Abrir investigação
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="footnote">
        Atribuição de responsável permanece indisponível: não existe workflow de posse no backend, e
        a interface não simula um.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------
// Avaliações
// --------------------------------------------------------------------------

function EvaluationsPage({
  summaries,
  openCase,
}: {
  summaries: InvestigationSummary[];
  openCase: (caseId: string) => void;
}) {
  const evaluated = summaries.filter((row) => row.final_verdict);

  return (
    <div className="page">
      <PageHead
        eyebrow="Avaliação pós-execução"
        title="Avaliações"
        description="Cada investigação é pontuada contra um barema versionado por dois avaliadores independentes. A decisão operacional é derivada de forma determinística — a interface apresenta, não recalcula."
      />

      <div className="figures">
        {verdictOrder.map((verdict) => (
          <div key={verdict} className={`figure figure--${finalVerdictTone[verdict]}`}>
            <b>{evaluated.filter((row) => row.final_verdict === verdict).length}</b>
            <span>{finalVerdictLabel[verdict]}</span>
          </div>
        ))}
        <div className="figure">
          <b>{summaries.length - evaluated.length}</b>
          <span>sem avaliação</span>
        </div>
      </div>

      <div className="table-wrap">
        <table className="grid-table">
          <thead>
            <tr>
              <th scope="col">Caso</th>
              <th scope="col">Estado da investigação</th>
              <th scope="col">Avaliação</th>
              <th scope="col" className="num">
                Pontuação
              </th>
              <th scope="col">Próximo passo</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((item) => (
              <tr
                key={item.case_id}
                className="grid-table__row--clickable"
                tabIndex={0}
                onClick={() => openCase(item.case_id)}
                onKeyDown={(event) => event.key === 'Enter' && openCase(item.case_id)}
              >
                <th scope="row">
                  <span className="cell-strong mono">{item.case_id}</span>
                  <span className="cell-weak">{item.asset_name}</span>
                </th>
                <td>
                  {item.terminal_state ? (
                    <StateMark state={item.terminal_state} />
                  ) : (
                    <span className="running-mark">
                      <i aria-hidden="true" />
                      Em execução
                    </span>
                  )}
                </td>
                <td>
                  {item.final_verdict ? (
                    <VerdictMark verdict={item.final_verdict} />
                  ) : (
                    <span className="muted">Não avaliada</span>
                  )}
                </td>
                <td className="num">
                  {item.overall_score != null ? formatScore(item.overall_score) : '—'}
                </td>
                <td>
                  <span className="cell-muted">
                    {item.recommended_action
                      ? recommendedActionLabel[
                          item.recommended_action as keyof typeof recommendedActionLabel
                        ]
                      : '—'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="footnote">
        As notas por critério e a análise dos avaliadores ficam dentro de cada investigação, na seção
        Avaliação.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------
// Operação
// --------------------------------------------------------------------------

function SystemHealth() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let active = true;
    api
      .health()
      .then((value) => active && setHealth(value))
      .catch((exc) => active && setError(exc as ApiError));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="page">
      <PageHead
        eyebrow="Observabilidade"
        title="Operação"
        description="Situação do serviço de investigação e da persistência. Informação secundária em relação à investigação."
      />
      {error ? (
        <div className="notice notice--danger">
          <p className="notice__title">Serviço indisponível</p>
          <p>{error.message}</p>
        </div>
      ) : (
        <dl className="runtime">
          <div>
            <dt>API</dt>
            <dd>{health?.api ?? '—'}</dd>
          </div>
          <div>
            <dt>Banco de dados</dt>
            <dd>{health?.database ?? '—'}</dd>
          </div>
          <div>
            <dt>Investigações em execução</dt>
            <dd>{health?.running_investigations ?? 0}</dd>
          </div>
        </dl>
      )}
      <p className="footnote">
        Execução em processo: adequada para demonstração e instância única. Um worker durável é
        evolução futura, e a limitação está documentada em vez de disfarçada.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------
// Raiz
// --------------------------------------------------------------------------

function Console() {
  const { summaries, loading, error, reload } = useConsole();
  const [view, setView] = useState<AppView>('overview');
  const [selectedId, setSelectedId] = useState<string>();
  const [evidence, setEvidence] = useState<EvidenceRecord>();
  const [event, setEvent] = useState<TraceEvent>();
  const [reviewCase, setReviewCase] = useState<Investigation>();
  const [creating, setCreating] = useState(false);

  const { dossier, loading: loadingCase, error: caseError } = useDossier(
    view === 'investigation-detail' ? selectedId : undefined,
  );

  const openCase = useCallback((caseId: string) => {
    setSelectedId(caseId);
    setView('investigation-detail');
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    // Sincroniza com a URL (sistema externo) uma única vez, fora do render.
    const timer = setTimeout(() => {
      const caseId = new URLSearchParams(window.location.search).get('case');
      if (caseId) openCase(caseId);
    }, 0);
    return () => clearTimeout(timer);
  }, [openCase]);

  const queue = reviewQueueOf(summaries);
  const title = useMemo(() => viewLabel[view], [view]);

  if (error) return <ServiceDown error={error} retry={reload} />;

  return (
    <Shell view={view} setView={setView} queueCount={queue.length}>
      <span className="sr-only" aria-live="polite">
        Seção atual: {title}
      </span>

      {loading && summaries.length === 0 && <Loading label="Carregando investigações…" />}

      {!loading && view === 'overview' && (
        <Overview
          summaries={summaries}
          openCase={openCase}
          go={setView}
          onNew={() => setCreating(true)}
        />
      )}
      {!loading && view === 'investigations' && (
        <InvestigationsPage
          summaries={summaries}
          openCase={openCase}
          onNew={() => setCreating(true)}
        />
      )}
      {!loading && view === 'human-review' && (
        <HumanReviewPage summaries={summaries} openCase={openCase} />
      )}
      {!loading && view === 'evaluations' && (
        <EvaluationsPage summaries={summaries} openCase={openCase} />
      )}
      {view === 'system-health' && <SystemHealth />}

      {view === 'investigation-detail' && caseError && (
        <ServiceDown error={caseError} retry={() => openCase(selectedId!)} />
      )}
      {view === 'investigation-detail' && !caseError && loadingCase && !dossier && (
        <Loading label="Carregando o dossiê…" />
      )}
      {view === 'investigation-detail' && dossier && (
        <Dossier
          item={dossier.investigation}
          evaluation={dossier.evaluation}
          running={dossier.running || !dossier.investigation.terminal_state}
          back={() => setView('investigations')}
          onEvidence={setEvidence}
          onTrace={setEvent}
          openReview={() => setReviewCase(dossier.investigation)}
        />
      )}

      <InspectionSheet
        investigation={dossier?.investigation}
        evidence={evidence}
        event={event}
        close={() => {
          setEvidence(undefined);
          setEvent(undefined);
        }}
        onOpenEvidence={setEvidence}
      />
      <ReviewSheet
        item={reviewCase}
        evaluation={dossier?.evaluation}
        close={() => setReviewCase(undefined)}
        openCase={() => reviewCase && openCase(reviewCase.case_id)}
      />

      {creating && (
        <NewInvestigationForm
          close={() => setCreating(false)}
          onCreated={(caseId) => {
            setCreating(false);
            reload();
            openCase(caseId);
          }}
        />
      )}
    </Shell>
  );
}

export default function Home() {
  return (
    <ConsoleProvider>
      <Console />
    </ConsoleProvider>
  );
}

export function FrontendLoadingState() {
  return (
    <div className="loading-page">
      <Skeleton className="loading-title" />
      <Skeleton className="loading-strip" />
      <div>
        <Skeleton />
        <Skeleton />
      </div>
    </div>
  );
}
