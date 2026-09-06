/**
 * Camada única de tradução para a interface.
 *
 * Regra: os contratos do backend permanecem intactos — `GROUNDED_COMPLETION`
 * continua sendo `GROUNDED_COMPLETION` no dado. Aqui mora apenas a superfície
 * visível ao engenheiro, em português. Nenhum componente deve escrever tradução
 * inline; se falta um rótulo, ele nasce neste arquivo.
 */

import type {
  AgreementLevel,
  Criterion,
  FinalVerdict,
  HardFailure,
  JudgeConfidence,
  JudgeVerdict,
  RecommendedAction,
  ReviewReasonCode,
  Score,
  WarningCode,
} from './eval-types';
import type { EvidenceQuality, EvidenceStatus, Investigation, TerminalState } from './investigation-types';

// --------------------------------------------------------------------------
// Números em português
// --------------------------------------------------------------------------

/** 3.85 → "3,9". A vírgula decimal não é detalhe: é o idioma do leitor. */
export const formatScore = (value: number): string =>
  value.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const formatTime = (iso: string): string =>
  new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

export const formatTimeSeconds = (iso: string): string =>
  new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export const formatDuration = (ms: number): string =>
  ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} s`;

// --------------------------------------------------------------------------
// Estado terminal da investigação
// --------------------------------------------------------------------------

export const terminalStateLabel: Record<TerminalState, string> = {
  GROUNDED_COMPLETION: 'Conclusão fundamentada',
  SAFE_ESCALATION: 'Encaminhado para revisão',
  AWAITING_REQUIRED_INFORMATION: 'Aguardando informações',
  FAILED: 'Falhou',
};

export const terminalStateHint: Record<TerminalState, string> = {
  GROUNDED_COMPLETION: 'A investigação chegou a uma conclusão sustentada por evidências.',
  SAFE_ESCALATION: 'A evidência disponível não sustentava uma conclusão, e o sistema parou.',
  AWAITING_REQUIRED_INFORMATION: 'Falta informação do solicitante para iniciar a investigação.',
  FAILED: 'A execução foi interrompida por uma falha operacional.',
};

export const terminalStateTone: Record<TerminalState, string> = {
  GROUNDED_COMPLETION: 'success',
  SAFE_ESCALATION: 'review',
  AWAITING_REQUIRED_INFORMATION: 'waiting',
  FAILED: 'danger',
};

// --------------------------------------------------------------------------
// Evidências
// --------------------------------------------------------------------------

export const evidenceStatusLabel: Record<EvidenceStatus, string> = {
  complete: 'Completa',
  partial: 'Parcial',
  inconclusive: 'Inconclusiva',
  conflict: 'Conflitante',
  unavailable: 'Indisponível',
};

export const evidenceQualityLabel: Record<EvidenceQuality, string> = {
  HIGH: 'Alta',
  MEDIUM: 'Média',
  LOW: 'Baixa',
  'INSUFFICIENT EVIDENCE': 'Evidência insuficiente',
};

export const evidenceQualityTone: Record<EvidenceQuality, string> = {
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
  'INSUFFICIENT EVIDENCE': 'insufficient',
};

// --------------------------------------------------------------------------
// Entendimento
// --------------------------------------------------------------------------

export const requestClassLabel: Record<Investigation['request_class'], string> = {
  investigate: 'Investigar',
  contextualize: 'Contextualizar',
  execute: 'Solicitação de ação',
  mixed: 'Mista',
  unclear: 'Ambígua',
};

// --------------------------------------------------------------------------
// Trajetória — nomes dos eventos persistidos
// --------------------------------------------------------------------------

export const traceEventLabel: Record<string, string> = {
  request_received: 'Solicitação recebida',
  understanding_completed: 'Entendimento concluído',
  planner_completed: 'Plano de investigação criado',
  tool_requested: 'Consulta solicitada',
  tool_completed: 'Consulta concluída',
  evidence_created: 'Evidência registrada',
  decision_accepted: 'Decisão aceita',
  conclusion_created: 'Conclusão produzida',
  reporter_completed: 'Relatório técnico gerado',
  reporter_failed: 'Falha na geração do relatório',
  terminal_state_reached: 'Encerramento da investigação',
};

export const traceEvent = (type: string): string =>
  traceEventLabel[type] ?? type.replaceAll('_', ' ');

/** O que cada ferramenta de leitura consulta, em linguagem de engenharia. */
export const toolLabel: Record<string, string> = {
  get_asset_context: 'Contexto do ativo',
  get_asset_rms: 'Leituras de RMS',
  get_asset_insights: 'Histórico de insights',
  get_asset_report: 'Relatório do especialista',
  get_asset_baseline: 'Linha de base do ativo',
  get_asset_spectrum: 'Espectro de vibração',
  get_analysis_details: 'Detalhes da análise',
};

export const toolName = (tool: string): string => toolLabel[tool] ?? tool;

export const handoffReasonLabel: Record<string, string> = {
  CONFLICTING_DIAGNOSES: 'Diagnósticos conflitantes',
  INSUFFICIENT_DIAGNOSTIC_DETAIL: 'Detalhe diagnóstico insuficiente',
  MISSING_ASSET_IDENTIFIER: 'Ativo não identificado',
  UNRESOLVED_DATA_GAP: 'Lacuna de dados não resolvida',
};

export const handoffReason = (code: string): string =>
  handoffReasonLabel[code] ?? code.replaceAll('_', ' ').toLowerCase();

// --------------------------------------------------------------------------
// Avaliação — decisão final
// --------------------------------------------------------------------------

export const finalVerdictLabel: Record<FinalVerdict, string> = {
  APPROVED: 'Aprovado',
  APPROVED_WITH_WARNINGS: 'Aprovado com ressalvas',
  HUMAN_REVIEW_REQUIRED: 'Revisão técnica necessária',
  REJECTED: 'Rejeitado',
};

export const finalVerdictDescription: Record<FinalVerdict, string> = {
  APPROVED:
    'A investigação atendeu aos critérios necessários para seguir sem revisão técnica adicional.',
  APPROVED_WITH_WARNINGS:
    'O resultado é válido, mas carrega ressalvas que a engenharia precisa conhecer antes de usá-lo.',
  HUMAN_REVIEW_REQUIRED:
    'A avaliação não encontrou segurança suficiente para aprovar automaticamente esta investigação.',
  REJECTED: 'Uma condição crítica foi violada. Este resultado não deve ser usado como resposta final.',
};

export const recommendedActionLabel: Record<RecommendedAction, string> = {
  PROCEED: 'Pode seguir',
  PROCEED_WITH_WARNINGS: 'Seguir com ressalvas',
  ENGINEERING_REVIEW: 'Encaminhar à engenharia',
  BLOCK_RESULT: 'Bloquear resultado',
};

export const finalVerdictTone: Record<FinalVerdict, 'success' | 'warning' | 'review' | 'danger'> = {
  APPROVED: 'success',
  APPROVED_WITH_WARNINGS: 'warning',
  HUMAN_REVIEW_REQUIRED: 'review',
  REJECTED: 'danger',
};

// --------------------------------------------------------------------------
// Avaliação — critérios do barema
// --------------------------------------------------------------------------

export const criterionLabel: Record<Criterion, string> = {
  SAFETY: 'Segurança',
  EVIDENCE_GROUNDING: 'Fundamentação em evidências',
  TERMINAL_DECISION: 'Decisão da investigação',
  EVIDENCE_PROVENANCE: 'Rastreabilidade das evidências',
  TOOL_ARGUMENT_CORRECTNESS: 'Argumentos das consultas',
  TOOL_SELECTION: 'Escolha das ferramentas',
  UNCERTAINTY_HANDLING: 'Tratamento da incerteza',
  UNDERSTANDING_CORRECTNESS: 'Interpretação da solicitação',
  PLAN_QUALITY: 'Qualidade do plano',
  REPORT_QUALITY: 'Qualidade do relatório',
  GOLDEN_ALIGNMENT: 'Aderência à referência',
};

/** Níveis da escala 0–4, como declarados em `barema-v1.json`. */
export const scoreLevelLabel: Record<Score, string> = {
  0: 'Falha',
  1: 'Fraco',
  2: 'Parcial',
  3: 'Aceitável',
  4: 'Forte',
};

export const warningLabel: Record<WarningCode, string> = {
  LOW_GROUNDING_MARGIN: 'Margem de fundamentação baixa',
  INCOMPLETE_EVIDENCE: 'Evidência incompleta',
  REPORTER_FIDELITY_WARNING: 'Fidelidade do relatório',
  JUDGE_DISAGREEMENT: 'Divergência entre avaliadores',
  DATA_LIMITATION: 'Limitação dos dados',
  TOOL_PATH_DEVIATION: 'Desvio no uso das ferramentas',
  NON_CRITICAL_CRITERION_BELOW_TARGET: 'Critério abaixo do alvo',
};

export const hardFailureLabel: Record<HardFailure, string> = {
  FORBIDDEN_ACTION_EXECUTED: 'Ação proibida executada',
  CLAIM_WITHOUT_EVIDENCE: 'Afirmação sem evidência',
  EVIDENCE_REFERENCE_NOT_FOUND: 'Evidência citada não encontrada',
  BROKEN_EVIDENCE_LINEAGE: 'Rastreabilidade quebrada',
  GOLDEN_LEAKED_INTO_RUNTIME: 'Referência vazou para a execução',
  UNKNOWN_TOOL_EXECUTED: 'Ferramenta desconhecida executada',
  UNGROUNDED_ANSWER: 'Resposta sem fundamentação',
  SECRET_EXPOSED: 'Credencial exposta',
  CHAIN_OF_THOUGHT_PERSISTED: 'Raciocínio interno persistido',
  REPORTER_FABRICATED_CLAIM: 'Relatório inventou uma afirmação',
};

export const reviewReasonLabel: Record<ReviewReasonCode, string> = {
  HARD_FAILURE_PRESENT: 'Condição crítica violada',
  CRITICAL_CRITERION_BELOW_MINIMUM: 'Critério crítico abaixo do mínimo',
  UNRESOLVED_JUDGE_DISAGREEMENT: 'Divergência não resolvida entre avaliadores',
  JUDGE_VERDICT_CONFLICT: 'Vereditos conflitantes entre avaliadores',
  BOTH_JUDGES_FAILED: 'Os dois avaliadores reprovaram',
  OVERALL_SCORE_BELOW_MINIMUM: 'Pontuação geral abaixo do mínimo',
  JUDGE_REQUESTED_HUMAN_REVIEW: 'Avaliador solicitou revisão humana',
};

// --------------------------------------------------------------------------
// Avaliadores
// --------------------------------------------------------------------------

export const judgeName: Record<'judge_a' | 'judge_b', string> = {
  judge_a: 'Avaliador A',
  judge_b: 'Avaliador B',
};

export const judgeFocus: Record<'judge_a' | 'judge_b', string> = {
  judge_a: 'Correção técnica',
  judge_b: 'Consistência e qualidade',
};

export const judgeVerdictLabel: Record<JudgeVerdict, string> = {
  PASS: 'Aprovou',
  PASS_WITH_WARNINGS: 'Aprovou com ressalvas',
  FAIL: 'Reprovou',
  HUMAN_REVIEW_REQUIRED: 'Pediu revisão humana',
};

export const agreementLabel: Record<AgreementLevel, string> = {
  HIGH: 'Alta',
  MEDIUM: 'Média',
  LOW: 'Baixa',
};

export const confidenceLabel: Record<JudgeConfidence, string> = {
  HIGH: 'Alta',
  MEDIUM: 'Média',
  LOW: 'Baixa',
};

// --------------------------------------------------------------------------
// Navegação
// --------------------------------------------------------------------------

export const viewLabel = {
  overview: 'Visão geral',
  investigations: 'Investigações',
  'human-review': 'Revisão técnica',
  evaluations: 'Avaliações',
  'system-health': 'Operação',
  'investigation-detail': 'Investigação',
} as const;
