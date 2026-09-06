/**
 * Tradução do DTO da API para os tipos que os componentes já consomem.
 *
 * A camada existe para que a interface refinada não precise ser redesenhada:
 * o backend fala em linhas de banco, o frontend fala em `Investigation` e
 * `Evaluation`, e a conversão mora aqui — num arquivo só.
 *
 * Campos ausentes durante a execução são normais, não erro: uma investigação
 * em andamento ainda não tem plano, conclusão nem avaliação.
 */

import type { Evaluation, FinalVerdict, RecommendedAction } from './eval-types';
import type {
  Claim,
  EvidenceQuality,
  EvidenceRecord,
  Investigation,
  TerminalState,
  TraceEvent,
} from './investigation-types';

/** Linha crua da API. O formato exato é validado pelos adapters abaixo. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

const TERMINAL: TerminalState[] = [
  'GROUNDED_COMPLETION',
  'SAFE_ESCALATION',
  'AWAITING_REQUIRED_INFORMATION',
  'FAILED',
];

/** O banco grava `INSUFFICIENT_EVIDENCE`; a interface usa o rótulo com espaço. */
function quality(value: string | null | undefined): EvidenceQuality {
  const raw = (value ?? '').toUpperCase();
  if (raw === 'HIGH' || raw === 'MEDIUM' || raw === 'LOW') return raw;
  return 'INSUFFICIENT EVIDENCE';
}

function terminal(value: string | null | undefined): TerminalState | undefined {
  const raw = value ?? '';
  return TERMINAL.includes(raw as TerminalState) ? (raw as TerminalState) : undefined;
}

function duration(ms: unknown): string {
  const value = Number(ms ?? 0);
  if (!value) return '—';
  return value < 1000
    ? `${value} ms`
    : `${(value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`;
}

function startedAt(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return `${date.toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })} · ${date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
}

// --------------------------------------------------------------------------
// Listagem
// --------------------------------------------------------------------------

export interface InvestigationSummary {
  case_id: string;
  asset_name: string;
  asset_id: string;
  company: string;
  request: string;
  terminal_state: TerminalState | undefined;
  evidence_quality: EvidenceQuality;
  evidence_count: number;
  final_verdict: FinalVerdict | undefined;
  overall_score: number | undefined;
  recommended_action: RecommendedAction | undefined;
  human_review_required: boolean;
  started_at: string;
  duration: string;
  running: boolean;
}

export function adaptSummary(row: Row): InvestigationSummary {
  return {
    case_id: row.case_id,
    asset_name: row.asset_name ?? row.asset_id ?? 'Ativo não identificado',
    asset_id: row.asset_id ?? '—',
    company: row.company ?? '—',
    request: row.request_message ?? '',
    terminal_state: terminal(row.terminal_state),
    evidence_quality: quality(row.evidence_quality),
    evidence_count: Number(row.evidence_count ?? 0),
    final_verdict: (row.final_verdict as FinalVerdict) ?? undefined,
    overall_score: row.overall_score != null ? Number(row.overall_score) : undefined,
    recommended_action: (row.recommended_action as RecommendedAction) ?? undefined,
    human_review_required: Boolean(row.human_review_required) || Boolean(row.has_handoff),
    started_at: startedAt(row.started_at),
    duration: duration(row.duration_ms),
    running: Boolean(row.running),
  };
}

// --------------------------------------------------------------------------
// Dossiê
// --------------------------------------------------------------------------

function adaptTrace(rows: Row[]): TraceEvent[] {
  return rows.map((row) => ({
    trace_id: row.trace_id,
    call_id: row.call_id,
    sequence: Number(row.sequence),
    event_type: row.event_type,
    timestamp: row.occurred_at,
    tool_name: row.tool_name ?? undefined,
    duration_ms: row.duration_ms != null ? Number(row.duration_ms) : undefined,
    summary: summaryFor(row),
    details: row.details ?? undefined,
  }));
}

/** O banco guarda metadados; a frase legível é montada aqui. */
function summaryFor(row: Row): string {
  const details = row.details ?? {};
  switch (row.event_type) {
    case 'understanding_completed':
      return `Solicitação classificada como ${details.request_class ?? '—'}, com ${
        details.investigation_targets ?? 0
      } alvo(s) de investigação.`;
    case 'planner_completed':
      return `Plano criado com ${details.objectives ?? 0} objetivo(s).`;
    case 'decision_accepted':
      return `Decisão ${details.decision_type ?? '—'} aceita pela política de conclusão.`;
    case 'tool_requested':
      return `Consulta solicitada pelo investigador.`;
    case 'tool_completed':
      return `Consulta concluída${
        details.evidence_status ? ` com estado ${details.evidence_status}` : ''
      }.`;
    case 'conclusion_created':
      return `Conclusão produzida com ${details.claims ?? 0} afirmação(ões).`;
    case 'reporter_completed':
      return 'Relatório técnico gerado para a equipe de engenharia.';
    case 'terminal_state_reached':
      return `Investigação encerrada em ${details.terminal_state ?? '—'}.`;
    default:
      return String(row.event_type ?? '').replaceAll('_', ' ');
  }
}

function adaptEvidence(rows: Row[]): EvidenceRecord[] {
  return rows.map((row) => ({
    evidence_id: row.evidence_id,
    trace_id: row.trace_id,
    source_call_id: row.source_call_id,
    source_trace_sequence: Number(row.source_trace_sequence),
    sequence: Number(row.sequence),
    collected_at: row.collected_at,
    tool_name: row.tool_name,
    client_operation: row.client_operation,
    arguments: row.arguments ?? {},
    evidence_status: row.evidence_status,
    transport_ok: Boolean(row.transport_ok),
    status_code: row.status_code ?? null,
    method: row.method,
    path: row.path,
    summary: row.notes ?? `${row.method} ${row.path}`,
    notes: row.notes ?? undefined,
    source: `API TRACTIAN · ${row.client_operation}`,
  }));
}

function adaptClaims(rows: Row[]): Claim[] {
  return rows.map((row) => ({
    claim_id: row.claim_id,
    statement: row.statement,
    supporting_evidence_ids: row.supporting_evidence_ids ?? [],
    contradictory_evidence_ids: row.contradictory_evidence_ids ?? [],
    limitation: row.limitation ?? undefined,
    status: row.status,
  }));
}

function adaptEvaluation(raw: Row | null | undefined): Evaluation | undefined {
  if (!raw?.decision) return undefined;
  const decision = raw.decision;
  return {
    decision: {
      evaluation_id: decision.evaluation_id,
      run_id: decision.eval_run_id ?? decision.run_id,
      case_id: decision.case_id ?? '',
      final_verdict: decision.final_verdict,
      approved: Boolean(decision.approved),
      human_review_required: Boolean(decision.human_review_required),
      recommended_action: decision.recommended_action,
      overall_score: Number(decision.overall_score),
      overall_score_max: Number(decision.overall_score_max ?? 4),
      critical_score_summary: (decision.critical_score_summary ?? []).map((item: Row) => ({
        criterion: item.criterion,
        score: Number(item.score),
        meets_minimum: Boolean(item.meets_minimum),
      })),
      agreement_level: decision.agreement_level,
      hard_failures: decision.hard_failures ?? [],
      warnings: (decision.warnings ?? []).map((item: Row) => ({
        code: item.code,
        detail: item.detail,
        criterion: item.criterion ?? null,
      })),
      review_reasons: (decision.review_reasons ?? []).map((item: Row) => ({
        code: item.code,
        detail: item.detail,
        criterion: item.criterion ?? null,
      })),
      judge_a_verdict: decision.judge_a_verdict,
      judge_b_verdict: decision.judge_b_verdict,
      arbitration_used: Boolean(decision.arbitration_used),
      barema_version: decision.barema_version,
      evaluated_at: decision.evaluated_at,
      headline: decision.headline,
    },
    judge_a: adaptJudge(raw.judge_a),
    judge_b: adaptJudge(raw.judge_b),
    agreement: {
      agreement_level: raw.agreement?.agreement_level ?? 'HIGH',
      verdict_match: Boolean(raw.agreement?.verdict_match),
      hard_failure_match: Boolean(raw.agreement?.hard_failure_match),
      mean_absolute_delta: Number(raw.agreement?.mean_absolute_delta ?? 0),
      max_delta: Number(raw.agreement?.max_delta ?? 0),
      disagreements: (raw.agreement?.disagreements ?? []).map((item: Row) => ({
        criterion: item.criterion,
        judge_a_score: Number(item.judge_a_score),
        judge_b_score: Number(item.judge_b_score),
        delta: Number(item.delta),
      })),
      arbitration_required: Boolean(raw.agreement?.arbitration_required),
      rationale: raw.agreement?.rationale ?? '',
    },
    arbitration: raw.arbitration
      ? {
          arbitrated_criteria: raw.arbitration.arbitrated_criteria ?? [],
          resolved: Boolean(raw.arbitration.resolved),
          note: raw.arbitration.note ?? '',
        }
      : undefined,
  };
}

function adaptJudge(raw: Row | null | undefined): Evaluation['judge_a'] {
  return {
    judge_id: raw?.judge_id ?? 'judge_a',
    criteria_scores: (raw?.criteria_scores ?? []).map((item: Row) => ({
      criterion: item.criterion,
      score: Number(item.score),
      reason: item.reason ?? '',
      evidence_references: item.evidence_references ?? [],
    })),
    hard_failures: raw?.hard_failures ?? [],
    strengths: raw?.strengths ?? [],
    weaknesses: raw?.weaknesses ?? [],
    evidence_references: raw?.evidence_references ?? [],
    overall_score: Number(raw?.overall_score ?? 0),
    verdict: raw?.verdict ?? 'PASS',
    confidence_in_evaluation: raw?.confidence_in_evaluation ?? 'MEDIUM',
    needs_human_review: Boolean(raw?.needs_human_review),
    provider: raw?.provider ?? null,
    model: raw?.model ?? null,
  };
}

export function adaptDossier(raw: Row): {
  investigation: Investigation;
  evaluation?: Evaluation;
  running: boolean;
} {
  const understanding = raw.understanding ?? {};
  const plan = raw.plan ?? {};
  const entities = understanding.entities ?? {};

  const investigation: Investigation = {
    case_id: raw.case_id,
    request_id: raw.request_id,
    trace_id: raw.trace_id,
    asset_id: raw.asset_id ?? '—',
    asset_name: raw.asset_name ?? raw.asset_id ?? 'Ativo não identificado',
    company: raw.company ?? '—',
    request: raw.request_message ?? '',
    request_class: understanding.request_class ?? 'investigate',
    entities: [
      ...(entities.assets ?? []),
      ...(entities.technical_terms ?? []),
      ...(entities.temporal_references ?? []),
    ],
    investigation_targets: understanding.investigation_targets ?? [],
    missing_information: (understanding.missing_information ?? []).map(
      (item: Row) => item.suggested_question ?? item.field,
    ),
    plan_objectives: plan.objectives ?? [],
    planned_capabilities: (plan.suggested_capabilities ?? []).map((item: Row) => item.name),
    started_at: startedAt(raw.started_at),
    duration: duration(raw.duration_ms),
    terminal_state: terminal(raw.terminal_state) ?? 'AWAITING_REQUIRED_INFORMATION',
    evidence_quality: quality(raw.evidence_quality),
    evidence_quality_reasons: raw.evidence_quality_reasons ?? [],
    unresolved_points: raw.unresolved_points ?? [],
    trace: adaptTrace(raw.trace ?? []),
    evidence: adaptEvidence(raw.evidence ?? []),
    claims: adaptClaims(raw.claims ?? []),
    report: raw.report
      ? {
          report_id: raw.report.report_id,
          audience: 'tractian_engineering_team',
          executive_summary: raw.report.executive_summary,
          investigation_performed: raw.report.investigation_performed ?? [],
          findings: raw.report.findings ?? [],
          evidence_references: raw.report.evidence_references ?? [],
          limitations: raw.report.limitations ?? [],
          missing_information: raw.report.missing_information ?? [],
          suggested_engineer_next_steps: raw.report.suggested_engineer_next_steps ?? [],
        }
      : undefined,
    human_handoff: raw.human_handoff
      ? {
          handoff_id: raw.human_handoff.handoff_id,
          reason_codes: raw.human_handoff.reason_codes ?? [],
          evidence_ids: raw.human_handoff.evidence_ids ?? [],
          missing_information: raw.human_handoff.missing_information ?? [],
          suggested_next_step: raw.human_handoff.suggested_next_step ?? undefined,
        }
      : undefined,
    mock: true,
  };

  return {
    investigation,
    evaluation: adaptEvaluation(raw.evaluation),
    running: Boolean(raw.running),
  };
}
