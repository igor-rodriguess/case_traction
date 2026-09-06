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

import { useEffect, useMemo, useState } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { investigations } from '@/lib/mock-investigations';
import { evaluationFor } from '@/lib/mock-evaluations';
import type { AppView, EvidenceRecord, Investigation, TraceEvent } from '@/lib/investigation-types';
import type { Evaluation, FinalVerdict } from '@/lib/eval-types';
import {
  agreementLabel,
  evidenceQualityLabel,
  evidenceQualityTone,
  finalVerdictLabel,
  finalVerdictTone,
  formatScore,
  handoffReason,
  recommendedActionLabel,
  requestClassLabel,
  reviewReasonLabel,
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

const nav: AppView[] = ['overview', 'investigations', 'human-review', 'evaluations', 'system-health'];

const verdictOrder: FinalVerdict[] = [
  'APPROVED',
  'APPROVED_WITH_WARNINGS',
  'HUMAN_REVIEW_REQUIRED',
  'REJECTED',
];

const evidenceStatusWord: Record<string, string> = {
  complete: 'completas',
  partial: 'parciais',
  inconclusive: 'inconclusivas',
  conflict: 'conflitantes',
  unavailable: 'indisponíveis',
};

/**
 * Regra única da fila de revisão. O contador do menu, a coluna da lista e a
 * página derivam daqui, para que os números não possam divergir.
 */
function reviewQueue(): Investigation[] {
  return investigations.filter((item) => {
    const evaluation = evaluationFor(item.case_id);
    return (
      Boolean(item.human_handoff) ||
      Boolean(
        evaluation &&
          (evaluation.decision.human_review_required ||
            evaluation.decision.final_verdict === 'REJECTED'),
      )
    );
  });
}

const needsReview = (item: Investigation): boolean =>
  reviewQueue().some((entry) => entry.case_id === item.case_id);

// --------------------------------------------------------------------------
// Estrutura
// --------------------------------------------------------------------------

function Shell({
  view,
  setView,
  children,
}: {
  view: AppView;
  setView: (view: AppView) => void;
  children: React.ReactNode;
}) {
  const active = view === 'investigation-detail' ? 'investigations' : view;
  const queue = reviewQueue().length;

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
          <p className="masthead__env">Ambiente piloto · dados simulados</p>
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

// --------------------------------------------------------------------------
// Visão geral
// --------------------------------------------------------------------------

function Overview({
  openCase,
  go,
}: {
  openCase: (item: Investigation) => void;
  go: (view: AppView) => void;
}) {
  const queue = reviewQueue();
  const concluded = investigations.filter((i) => i.terminal_state === 'GROUNDED_COMPLETION').length;
  const waiting = investigations.filter(
    (i) => i.terminal_state === 'AWAITING_REQUIRED_INFORMATION',
  ).length;
  const failed = investigations.filter((i) => i.terminal_state === 'FAILED').length;

  const evaluated = investigations
    .map((item) => evaluationFor(item.case_id))
    .filter((entry): entry is Evaluation => Boolean(entry));

  const evidenceTotals = investigations.flatMap((item) => item.evidence);
  const statusCounts = (['complete', 'partial', 'inconclusive', 'conflict', 'unavailable'] as const)
    .map((status) => ({
      status,
      count: evidenceTotals.filter((record) => record.evidence_status === status).length,
    }))
    .filter((entry) => entry.count > 0);

  return (
    <div className="page">
      <PageHead
        eyebrow="Operação · 6 de setembro de 2026"
        title="Visão geral"
        description="Situação atual das investigações, postura das evidências e exceções que exigem decisão humana."
      />

      <div className="figures">
        <div className="figure">
          <b>{investigations.length}</b>
          <span>investigações no período</span>
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
          <ul className="feed">
            {investigations.map((item) => {
              const evaluation = evaluationFor(item.case_id);
              return (
                <li key={item.case_id}>
                  <button type="button" className="feed__row" onClick={() => openCase(item)}>
                    <span className="feed__when">{item.started_at.split('· ')[1]}</span>
                    <span className="feed__what">
                      <b>{item.asset_name}</b>
                      <span>{item.request}</span>
                    </span>
                    <span className="feed__state">
                      <StateMark state={item.terminal_state} />
                      {evaluation ? (
                        <VerdictMark verdict={evaluation.decision.final_verdict} />
                      ) : (
                        <span className="muted">Sem avaliação</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Section>

        <div className="stack">
          <Section
            n="02"
            title="Aguardando decisão humana"
            hint="Casos parados com evidência preservada."
          >
            {queue.length > 0 ? (
              <ul className="mini-queue">
                {queue.map((item) => {
                  const evaluation = evaluationFor(item.case_id);
                  const reason = evaluation?.decision.review_reasons[0];
                  return (
                    <li key={item.case_id}>
                      <button type="button" onClick={() => openCase(item)}>
                        <span className="mini-queue__head">
                          <b className="mono">{item.case_id}</b>
                          {evaluation && <VerdictMark verdict={evaluation.decision.final_verdict} />}
                        </span>
                        <span className="mini-queue__asset">{item.asset_name}</span>
                        <span className="mini-queue__reason">
                          {reason
                            ? reviewReasonLabel[reason.code]
                            : handoffReason(item.human_handoff?.reason_codes[0] ?? '')}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="muted">Nenhum caso aguardando decisão humana.</p>
            )}
          </Section>

          <Section
            n="03"
            title="Distribuição dos resultados"
            hint="Vereditos da avaliação e estado semântico das evidências."
          >
            <ul className="dist">
              {verdictOrder.map((verdict) => {
                const count = evaluated.filter(
                  (entry) => entry.decision.final_verdict === verdict,
                ).length;
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
              {plural(evidenceTotals.length, 'evidência registrada', 'evidências registradas')}:{' '}
              {statusCounts
                .map((entry) => `${entry.count} ${evidenceStatusWord[entry.status]}`)
                .join(' · ')}
              .
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

function InvestigationsPage({ openCase }: { openCase: (item: Investigation) => void }) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState('all');
  const [review, setReview] = useState('all');

  const rows = investigations.filter((item) => {
    const matchesState = state === 'all' || item.terminal_state === state;
    const matchesReview = review === 'all' || (review === 'yes') === needsReview(item);
    const matchesQuery = `${item.case_id} ${item.asset_name} ${item.company} ${item.request}`
      .toLowerCase()
      .includes(query.toLowerCase());
    return matchesState && matchesReview && matchesQuery;
  });

  return (
    <div className="page">
      <PageHead
        eyebrow="Bancada de investigação"
        title="Investigações"
        description="Estado final, qualidade das evidências e resultado da avaliação, caso a caso."
      />

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
            {rows.map((item) => {
              const evaluation = evaluationFor(item.case_id);
              return (
                <tr
                  key={item.case_id}
                  className="grid-table__row--clickable"
                  tabIndex={0}
                  onClick={() => openCase(item)}
                  onKeyDown={(event) => event.key === 'Enter' && openCase(item)}
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
                    <StateMark state={item.terminal_state} />
                  </td>
                  <td>
                    <QualityMark quality={item.evidence_quality} />
                    <span className="cell-weak">
                      {plural(item.evidence.length, 'registro', 'registros')}
                    </span>
                  </td>
                  <td>
                    {evaluation ? (
                      <>
                        <VerdictMark verdict={evaluation.decision.final_verdict} />
                        <span className="cell-weak">
                          {formatScore(evaluation.decision.overall_score)} de 4
                        </span>
                      </>
                    ) : (
                      <span className="muted">Não avaliada</span>
                    )}
                  </td>
                  <td>
                    {needsReview(item) ? (
                      <span className="pill pill--review">Necessária</span>
                    ) : (
                      <span className="cell-muted">—</span>
                    )}
                  </td>
                  <td className="num">{item.duration}</td>
                </tr>
              );
            })}
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
// Dossiê da investigação
// --------------------------------------------------------------------------

const sections = [
  ['solicitacao', 'Solicitação'],
  ['trajetoria', 'Trajetória e evidências'],
  ['conclusao', 'Conclusão'],
  ['relatorio', 'Relatório'],
  ['avaliacao', 'Avaliação'],
] as const;

function Dossier({
  item,
  back,
  onEvidence,
  onTrace,
  openReview,
}: {
  item: Investigation;
  back: () => void;
  onEvidence: (record: EvidenceRecord) => void;
  onTrace: (event: TraceEvent) => void;
  openReview: () => void;
}) {
  const evaluation = evaluationFor(item.case_id);
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
              <span className="tag">dados simulados</span>
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
            <ol className="objectives">
              {item.plan_objectives.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ol>
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
// Revisão técnica
// --------------------------------------------------------------------------

function HumanReviewPage({
  openCase,
  openReview,
}: {
  openCase: (item: Investigation) => void;
  openReview: (item: Investigation) => void;
}) {
  const queue = reviewQueue();

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

      <div className="queue__head">
        <span>Caso</span>
        <span>Motivo da revisão</span>
        <span>Avaliação</span>
        <span className="sr-only">Ações</span>
      </div>
      <ul className="queue">
        {queue.map((item) => {
          const evaluation = evaluationFor(item.case_id);
          const reason = evaluation?.decision.review_reasons[0];
          return (
            <li className="queue__item" key={item.case_id}>
              <div className="queue__case">
                <p className="mono cell-strong">{item.case_id}</p>
                <p className="cell-weak">
                  {item.asset_name} · {item.company}
                </p>
                <StateMark state={item.terminal_state} />
              </div>

              <div className="queue__why">
                <p className="queue__reason">
                  {reason
                    ? reviewReasonLabel[reason.code]
                    : handoffReason(item.human_handoff?.reason_codes[0] ?? 'UNRESOLVED_DATA_GAP')}
                </p>
                <p className="cell-prose">
                  {reason?.detail ??
                    item.unresolved_points[0] ??
                    'A evidência disponível não sustentava uma conclusão.'}
                </p>
                {item.human_handoff && item.human_handoff.missing_information.length > 0 && (
                  <p className="queue__missing">
                    Falta: {item.human_handoff.missing_information.join(' · ')}
                  </p>
                )}
              </div>

              <div className="queue__eval">
                {evaluation ? (
                  <>
                    <VerdictMark verdict={evaluation.decision.final_verdict} />
                    <p className="cell-weak">
                      {formatScore(evaluation.decision.overall_score)} de 4 ·{' '}
                      {recommendedActionLabel[evaluation.decision.recommended_action]}
                    </p>
                  </>
                ) : (
                  <>
                    <span className="muted">Não avaliada</span>
                    <p className="cell-weak">Não chegou à etapa de avaliação</p>
                  </>
                )}
                <p className="cell-weak">
                  Qualidade das evidências: <QualityMark quality={item.evidence_quality} />
                </p>
              </div>

              <div className="queue__actions">
                <button type="button" className="button" onClick={() => openCase(item)}>
                  Abrir investigação
                </button>
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => openReview(item)}
                >
                  Ver encaminhamento
                </button>
              </div>
            </li>
          );
        })}
      </ul>

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

function EvaluationsPage({ openCase }: { openCase: (item: Investigation) => void }) {
  const rows = investigations.map((item) => ({ item, evaluation: evaluationFor(item.case_id) }));
  const evaluated = rows.filter((row) => row.evaluation);
  const counts = evaluated.reduce<Record<string, number>>((acc, row) => {
    const key = row.evaluation!.decision.final_verdict;
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

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
            <b>{counts[verdict] ?? 0}</b>
            <span>{finalVerdictLabel[verdict]}</span>
          </div>
        ))}
        <div className="figure">
          <b>{rows.length - evaluated.length}</b>
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
              <th scope="col">Concordância</th>
              <th scope="col" className="num">
                Aval. A
              </th>
              <th scope="col" className="num">
                Aval. B
              </th>
              <th scope="col">Próximo passo</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ item, evaluation }) => (
              <tr
                key={item.case_id}
                className="grid-table__row--clickable"
                tabIndex={0}
                onClick={() => openCase(item)}
                onKeyDown={(event) => event.key === 'Enter' && openCase(item)}
              >
                <th scope="row">
                  <span className="cell-strong mono">{item.case_id}</span>
                  <span className="cell-weak">{item.asset_name}</span>
                </th>
                <td>
                  <StateMark state={item.terminal_state} />
                </td>
                <td>
                  {evaluation ? (
                    <VerdictMark verdict={evaluation.decision.final_verdict} />
                  ) : (
                    <span className="muted">Não avaliada</span>
                  )}
                </td>
                <td className="num">
                  {evaluation ? formatScore(evaluation.decision.overall_score) : '—'}
                </td>
                <td>
                  <span className="cell-muted">
                    {evaluation ? agreementLabel[evaluation.agreement.agreement_level] : '—'}
                  </span>
                  {evaluation?.arbitration && <span className="cell-weak">com arbitragem</span>}
                </td>
                <td className="num">
                  {evaluation ? formatScore(evaluation.judge_a.overall_score) : '—'}
                </td>
                <td className="num">
                  {evaluation ? formatScore(evaluation.judge_b.overall_score) : '—'}
                </td>
                <td>
                  <span className="cell-muted">
                    {evaluation
                      ? recommendedActionLabel[evaluation.decision.recommended_action]
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

const providers = [
  ['Gemini', '642 ms', '1.284', '0,3%'],
  ['Groq', '511 ms', '846', '0,1%'],
  ['API TRACTIAN', '186 ms', '2.341', '0,2%'],
];

function SystemHealth() {
  return (
    <div className="page">
      <PageHead
        eyebrow="Observabilidade"
        title="Operação"
        description="Indicadores dos provedores e da execução no ambiente piloto. Informação secundária em relação à investigação."
      />
      <div className="split split--8-4">
        <Section n="01" title="Provedores" hint="Situação dos serviços de que a execução depende.">
          <div className="table-wrap">
            <table className="grid-table">
              <thead>
                <tr>
                  <th scope="col">Serviço</th>
                  <th scope="col">Situação</th>
                  <th scope="col" className="num">
                    Latência p50
                  </th>
                  <th scope="col" className="num">
                    Chamadas 24 h
                  </th>
                  <th scope="col" className="num">
                    Taxa de erro
                  </th>
                </tr>
              </thead>
              <tbody>
                {providers.map(([name, latency, requests, errors]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td>
                      <span className="mark mark--success">
                        <span className="mark__glyph" aria-hidden="true" />
                        Operacional
                      </span>
                    </td>
                    <td className="num">{latency}</td>
                    <td className="num">{requests}</td>
                    <td className="num">{errors}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section n="02" title="Execução" hint="Últimas 24 horas.">
          <dl className="runtime">
            <div>
              <dt>Chamadas de modelo</dt>
              <dd>2.130</dd>
            </div>
            <div>
              <dt>Consultas de leitura</dt>
              <dd>2.341</dd>
            </div>
            <div>
              <dt>Duração mediana</dt>
              <dd>8,2 s</dd>
            </div>
            <div>
              <dt>Eventos de limite de taxa</dt>
              <dd>3</dd>
            </div>
          </dl>
          <p className="footnote">
            Telemetria simulada do piloto — não está conectada às APIs dos provedores.
          </p>
        </Section>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------

export default function Home() {
  const [view, setView] = useState<AppView>('overview');
  const [selected, setSelected] = useState<Investigation>();
  const [evidence, setEvidence] = useState<EvidenceRecord>();
  const [event, setEvent] = useState<TraceEvent>();
  const [review, setReview] = useState<Investigation>();

  const title = useMemo(() => viewLabel[view], [view]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const params = new URLSearchParams(window.location.search);
      const match = investigations.find((item) => item.case_id === params.get('case'));
      const requestedView = params.get('view');
      if (match) {
        setSelected(match);
        setView('investigation-detail');
        if (params.get('review') === '1') setReview(match);
      } else if (requestedView && (nav as string[]).includes(requestedView)) {
        setView(requestedView as AppView);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  function openCase(item: Investigation) {
    setSelected(item);
    setView('investigation-detail');
    window.scrollTo(0, 0);
  }

  return (
    <Shell view={view} setView={setView}>
      <span className="sr-only" aria-live="polite">
        Seção atual: {title}
      </span>
      {view === 'overview' && <Overview openCase={openCase} go={setView} />}
      {view === 'investigations' && <InvestigationsPage openCase={openCase} />}
      {view === 'human-review' && <HumanReviewPage openCase={openCase} openReview={setReview} />}
      {view === 'evaluations' && <EvaluationsPage openCase={openCase} />}
      {view === 'system-health' && <SystemHealth />}
      {view === 'investigation-detail' && selected && (
        <Dossier
          item={selected}
          back={() => setView('investigations')}
          onEvidence={setEvidence}
          onTrace={setEvent}
          openReview={() => setReview(selected)}
        />
      )}
      <InspectionSheet
        investigation={selected}
        evidence={evidence}
        event={event}
        close={() => {
          setEvidence(undefined);
          setEvent(undefined);
        }}
        onOpenEvidence={setEvidence}
      />
      <ReviewSheet item={review} close={() => setReview(undefined)} openCase={openCase} />
    </Shell>
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
